import copy
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
import zipfile

import weknora_live_egress as egress
import weknora_live_probe as probe
import weknora_live_rehearsal as live


class LiveTests(unittest.TestCase):
    def workspace_models(self):
        models = self.fixture_models()
        models["embedding"] = {
            "name": "text-embedding-v3",
            "type": "Embedding",
            "source": "remote",
            "parameters": {
                "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                "api_key": "enc:v1:embedding-secret",
                "dimensions": 1024,
            },
        }
        models["chat"] = {
            "name": "deepseek-v4-flash",
            "parameters": {"api_key": "enc:v1:chat-secret"},
        }
        return models

    def test_workspace_migration_preserves_models_credentials_dimensions_and_source(self):
        original = self.workspace_models()
        baseline = copy.deepcopy(original)
        host = "ws-test123.cn-beijing.maas.aliyuncs.com"
        migrated, adjustments = live.prepare_fixture_models(original, workspace_id="ws-test123")
        expected = copy.deepcopy(baseline)
        for slot, path in (
            ("embedding", "/compatible-mode/v1"),
            ("rerank", "/api/v1/services/rerank/text-rerank/text-rerank"),
        ):
            expected[slot]["parameters"].update(
                provider="aliyun", base_url="https://" + host + path
            )
        self.assertEqual(migrated, expected)
        self.assertEqual(original, baseline)
        self.assertEqual({a["usage"] for a in adjustments}, {"embedding", "rerank"})
        self.assertNotIn("secret", json.dumps(adjustments))
        report = {"not_verified": []}
        probe.record_configuration_adjustments({"configuration_adjustments": adjustments}, report)
        self.assertTrue(any("embedding workspace" in v for v in report["not_verified"]))
        self.assertTrue(any("rerank endpoint" in v for v in report["not_verified"]))

    def test_workspace_migration_rejects_unexpected_models_and_endpoints(self):
        for slot in ("embedding", "rerank"):
            for key, value in (
                ("base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1?secret=x"),
                ("base_url", "https://evil.invalid/compatible-mode/v1"),
                ("base_url", "https://ws-other.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"),
                ("provider", "generic"),
                ("spec", {"api": "other"}),
                ("extra_config", {"remote_model_name": "other"}),
            ):
                with self.subTest(slot=slot, key=key):
                    original = self.workspace_models()
                    original[slot]["parameters"][key] = value
                    baseline = copy.deepcopy(original)
                    with self.assertRaisesRegex(RuntimeError, "workspace migration"):
                        live.prepare_fixture_models(original, workspace_id="ws-test123")
                    self.assertEqual(original, baseline)
            original = self.workspace_models()
            original[slot]["name"] = "other"
            with self.assertRaises(RuntimeError):
                live.prepare_fixture_models(original, workspace_id="ws-test123")
        with self.assertRaises(RuntimeError):
            live.prepare_fixture_models(
                self.workspace_models(), workspace_id="ws-test123", correct_rerank_endpoint=True
            )

    def test_workspace_json_parameters_and_native_rerank_source(self):
        original = self.workspace_models()
        original["rerank"]["parameters"]["base_url"] = (
            "https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank/"
        )
        original["embedding"]["parameters"]["base_url"] += "/"
        for model in original.values():
            model["parameters"] = json.dumps(model["parameters"])
        migrated, _ = live.prepare_fixture_models(original, workspace_id="ws-test123")
        self.assertEqual(migrated["embedding"]["parameters"]["dimensions"], 1024)
        self.assertEqual(migrated["rerank"]["parameters"]["api_key"], "enc:v1:synthetic-secret")
        self.assertEqual(migrated["chat"], original["chat"])

    def test_workspace_id_cannot_expand_gateway_allowlist(self):
        for value in (
            "",
            "ws-",
            "ws-a.evil",
            "ws-a:443",
            "ws-a/",
            "ws-a@evil",
            "ws-a\n",
            "ws-" + "a" * 61,
            "../ws-a",
            "https://ws-a",
            "*",
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                egress.workspace_host(value)
        host = egress.workspace_host("ws-test123")
        allowed = egress.allowed_hosts("ws-test123")
        self.assertEqual(allowed, {host, "api.deepseek.com"})
        self.assertNotIn("dashscope.aliyuncs.com", allowed)
        mapping = {h: ["1.1.1.1"] for h in allowed}
        self.assertEqual(live.model_host_args(mapping, allowed).count("--add-host"), 2)
        for bad in (
            {**mapping, "dashscope.aliyuncs.com": ["1.1.1.1"]},
            {**mapping, host: ["1.1.1.1", "127.0.0.1"]},
        ):
            with self.assertRaises(ValueError):
                live.model_host_args(bad, allowed)

    def test_gateway_resolver_and_probe_receive_same_workspace_in_fresh_process(self):
        workspace = "ws-test123"
        args = live.gateway_runtime_args("fixed-image", "source", workspace)
        env_args = live.workspace_env_args(workspace)
        self.assertEqual(args[args.index("-e") : args.index("-e") + 2], env_args)
        # Test separate import-time configuration, as used by the gateway,
        # docker exec resolver and the synthetic probe process.
        code = """
import json
from unittest.mock import patch
import weknora_live_egress as e
import weknora_live_probe as p
host = e.workspace_host("ws-test123")
assert e.ALLOWED == p.ALLOWED == {host, "api.deepseek.com"}
assert e.target(host + ":443") == host
assert p.endpoint_allowed("https://" + host + "/compatible-mode/v1")
for denied in ("dashscope.aliyuncs.com", "ws-other.cn-beijing.maas.aliyuncs.com", host + ".evil.invalid"):
    assert not p.endpoint_allowed("https://" + denied)
    try:
        e.target(denied + ":443")
    except ValueError:
        pass
    else:
        raise AssertionError("unexpected allowed host")
with patch.object(e.socket, "getaddrinfo", return_value=[(2,1,6,"",("1.1.1.1",443))]):
    assert set(e.resolve_model_hosts()) == e.ALLOWED
print("workspace process checks passed")
"""
        env = dict(os.environ, **{egress.WORKSPACE_ENV: workspace})
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=Path(egress.__file__).parent,
            env=env,
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def fixture_models(self):
        return {
            "rerank": {
                "name": "qwen3-rerank",
                "type": "Rerank",
                "source": "remote",
                "parameters": {
                    "provider": "aliyun",
                    "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                    "api_key": "enc:v1:synthetic-secret",
                },
            },
            "embedding": {"parameters": {"base_url": "synthetic-original"}},
        }

    def test_rerank_correction_is_opt_in_and_does_not_mutate_source(self):
        original = self.fixture_models()
        baseline = copy.deepcopy(original)
        unchanged, adjustments = live.prepare_fixture_models(original)
        self.assertEqual(unchanged, baseline)
        self.assertEqual(adjustments, [])
        corrected, adjustments = live.prepare_fixture_models(original, correct_rerank_endpoint=True)
        expected = copy.deepcopy(baseline)
        expected["rerank"]["parameters"]["base_url"] = (
            "https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank"
        )
        self.assertEqual(corrected, expected)
        self.assertEqual(original, baseline)
        self.assertTrue(probe.endpoint_allowed(corrected["rerank"]["parameters"]["base_url"]))
        self.assertEqual(adjustments[0]["scope"], "synthetic_model_only")
        self.assertFalse(adjustments[0]["production_configuration_changed"])
        self.assertNotIn("secret", json.dumps(adjustments))

    def test_rerank_correction_accepts_json_parameters_and_trailing_slash(self):
        original = self.fixture_models()
        params = original["rerank"]["parameters"]
        params["base_url"] += "/"
        original["rerank"]["parameters"] = json.dumps(params)
        baseline = copy.deepcopy(original)
        corrected, _ = live.prepare_fixture_models(original, correct_rerank_endpoint=True)
        self.assertTrue(corrected["rerank"]["parameters"]["base_url"].endswith("/text-rerank"))
        self.assertEqual(original, baseline)

    def test_rerank_correction_rejects_undiagnosed_configurations(self):
        for key, value in (
            ("base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1?key=secret"),
            ("base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1#fragment"),
            ("base_url", "https://dashscope.aliyuncs.com.evil.invalid/compatible-mode/v1"),
            ("base_url", "https://127.0.0.1/compatible-mode/v1"),
            ("base_url", "http://dashscope.aliyuncs.com/compatible-mode/v1"),
            ("base_url", "https://dashscope.aliyuncs.com/compatible-api/v1/reranks"),
            ("provider", "generic"),
            ("spec", {"api": "custom"}),
            ("extra_config", {"remote_model_name": "other"}),
        ):
            with self.subTest(key=key, value=value):
                original = self.fixture_models()
                original["rerank"]["parameters"][key] = value
                baseline = copy.deepcopy(original)
                with self.assertRaisesRegex(RuntimeError, "exact diagnosed"):
                    live.prepare_fixture_models(original, correct_rerank_endpoint=True)
                self.assertEqual(original, baseline)
        for key, value in (("name", "other"), ("type", "Embedding"), ("source", "local")):
            original = self.fixture_models()
            original["rerank"][key] = value
            with self.assertRaisesRegex(RuntimeError, "exact diagnosed"):
                live.prepare_fixture_models(original, correct_rerank_endpoint=True)

    def test_corrected_fixture_pass_cannot_claim_production_config_validated(self):
        _, adjustments = live.prepare_fixture_models(
            self.fixture_models(), correct_rerank_endpoint=True
        )
        report = {"not_verified": ["KAP three-role end-to-end authorization"]}
        probe.record_configuration_adjustments({"configuration_adjustments": adjustments}, report)
        self.assertEqual(report["configuration_adjustments"], adjustments)
        self.assertIn(
            "production rerank endpoint correction and validation", report["not_verified"]
        )
        unchanged = {"not_verified": []}
        probe.record_configuration_adjustments({}, unchanged)
        self.assertEqual(unchanged, {"not_verified": [], "configuration_adjustments": []})

    def test_model_dns_resolution_is_allowlisted_and_deduplicated(self):
        answers = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("1.1.1.1", 443)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("1.1.1.1", 443)),
            (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("2606:4700::1111", 443, 0, 0)),
        ]
        with patch.object(egress.socket, "getaddrinfo", return_value=answers) as lookup:
            result = egress.resolve_model_hosts()
            self.assertEqual(set(result), egress.ALLOWED)
            self.assertEqual(result["api.deepseek.com"], ["1.1.1.1", "2606:4700::1111"])
            self.assertEqual({call.args[0] for call in lookup.call_args_list}, egress.ALLOWED)
            lookup.reset_mock()
            with self.assertRaises(ValueError):
                egress.resolve_public("forbidden.invalid")
            lookup.assert_not_called()

    def test_only_verified_public_model_hosts_become_docker_arguments(self):
        valid = {host: ["1.1.1.1"] for host in egress.ALLOWED}
        args = live.model_host_args(valid)
        self.assertEqual(args.count("--add-host"), 2)
        invalid = [
            {},
            {**valid, "extra.invalid": ["1.1.1.1"]},
            {**valid, "api.deepseek.com": []},
        ]
        for address in (
            "127.0.0.1",
            "10.0.0.1",
            "169.254.169.254",
            "224.0.0.1",
            "::1",
            "ff02::1",
            "host-gateway",
            "1.1.1.1\nother",
            "2606:4700::1111%eth0",
        ):
            invalid.append({**valid, "api.deepseek.com": ["1.1.1.1", address]})
        for mapping in invalid:
            with self.subTest(mapping=mapping), self.assertRaises(ValueError):
                live.model_host_args(mapping)

    def test_child_hosts_must_actually_share_parent_file(self):
        live.assert_shared_hosts({"HostsPath": "/fixture/hosts"}, {"HostsPath": "/fixture/hosts"})
        for child, parent in (({}, {}), ({"HostsPath": "/other"}, {"HostsPath": "/fixture"})):
            with self.assertRaises(RuntimeError):
                live.assert_shared_hosts(child, parent)

    def test_gateway_requires_no_host_source_or_secret_mount(self):
        source = Path(egress.__file__).read_text()
        args = live.gateway_runtime_args("fixed-image", source)
        self.assertNotIn("--mount", args)
        self.assertNotIn("--user", args)
        self.assertIn("--read-only", args)
        self.assertEqual(args[args.index("fixed-image") + 1 :], ["-u", "-c", source])
        compile(source, "gateway", "exec")

    def test_gateway_exit_fails_before_attempting_readiness(self):
        with (
            patch.object(live.pg, "inspect", return_value={"State": {"Running": False}}),
            patch.object(live.subprocess, "run") as execute,
        ):
            with self.assertRaisesRegex(RuntimeError, "gateway exited"):
                live.wait_gateway("synthetic-gateway")
            execute.assert_not_called()

    def test_gateway_unhealthy_is_bounded_and_never_accepted(self):
        with (
            patch.object(live.pg, "inspect", return_value={"State": {"Running": True}}),
            patch.object(
                live.subprocess, "run", return_value=subprocess.CompletedProcess([], 1)
            ) as execute,
            patch.object(live.time, "sleep"),
        ):
            with self.assertRaisesRegex(RuntimeError, "readiness timeout"):
                live.wait_gateway("synthetic-gateway")
            self.assertEqual(execute.call_count, 20)

    def test_only_exact_approved_tls_targets(self):
        for host in egress.ALLOWED:
            self.assertEqual(egress.target(host + ":443"), host)
            self.assertTrue(probe.endpoint_allowed("https://" + host + "/v1"))
        for authority in (
            "api.deepseek.com:80",
            "api.deepseek.com.evil:443",
            "api.deepseek.com@127.0.0.1:443",
            "127.0.0.1:443",
            "[::1]:443",
            "api.deepseek.com.:443",
            "example.com:443",
        ):
            with self.subTest(authority=authority), self.assertRaises(ValueError):
                egress.target(authority)
        for url in (
            "http://api.deepseek.com",
            "https://secret@api.deepseek.com",
            "https://api.deepseek.com:8443",
            "https://example.com",
            "",
        ):
            self.assertFalse(probe.endpoint_allowed(url))

    def test_dns_private_and_mixed_answers_denied_before_connect(self):
        for ips in (
            ("127.0.0.1",),
            ("10.0.0.1",),
            ("169.254.169.254",),
            ("2606:4700::1111", "::1"),
            ("1.1.1.1", "192.168.0.1"),
        ):
            answers = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443)) for ip in ips]
            with (
                patch.object(socket, "getaddrinfo", return_value=answers),
                patch.object(socket, "socket") as connect,
            ):
                with self.assertRaises(ValueError):
                    egress.connect_public("api.deepseek.com")
                connect.assert_not_called()

    def test_validated_ip_used_without_second_resolution(self):
        address = ("1.1.1.1", 443)
        with (
            patch.object(
                socket,
                "getaddrinfo",
                return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", address)],
            ) as resolve,
            patch.object(socket, "socket") as factory,
        ):
            egress.connect_public("api.deepseek.com")
            resolve.assert_called_once()
            factory.return_value.connect.assert_called_once_with(address)

    def test_connect_tunnel_and_denial_on_real_local_sockets(self):
        server = egress.ThreadingHTTPServer(("127.0.0.1", 0), egress.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        outbound, echo = socket.socketpair()
        try:
            readiness = subprocess.run(
                [sys.executable, "-c", live.GATEWAY_CHECK, *map(str, server.server_address)],
                capture_output=True,
                timeout=5,
            )
            self.assertEqual(readiness.returncode, 0, readiness.stderr)
            with socket.create_connection(server.server_address, timeout=3) as client:
                client.sendall(
                    b"CONNECT forbidden.invalid:443 HTTP/1.1\r\nHost: forbidden.invalid\r\n\r\n"
                )
                self.assertIn(b"403", client.recv(1024))
            with patch.object(egress, "connect_public", return_value=outbound):
                with socket.create_connection(server.server_address, timeout=3) as client:
                    echo.settimeout(3)
                    client.sendall(
                        b"CONNECT api.deepseek.com:443 HTTP/1.1\r\nHost: api.deepseek.com\r\n\r\n"
                    )
                    headers = b""
                    while b"\r\n\r\n" not in headers:
                        headers += client.recv(1024)
                    self.assertIn(b"200", headers)
                    client.sendall(b"synthetic-input")
                    self.assertEqual(echo.recv(1024), b"synthetic-input")
                    echo.sendall(b"synthetic-reply")
                    self.assertEqual(client.recv(1024), b"synthetic-reply")
        finally:
            echo.close()
            outbound.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

    def test_network_guard_rejects_extra_network_ports_and_privilege(self):
        run = Path("/synthetic")
        item = {
            "Config": {"Labels": {live.pg.LABEL: str(run)}},
            "HostConfig": {"PortBindings": {}, "Privileged": False},
            "NetworkSettings": {"Networks": {"internal": {}}},
        }
        live.assert_network(item, ["internal"], run)
        for section, key, value in (
            ("NetworkSettings", "Networks", {"internal": {}, "bridge": {}}),
            ("HostConfig", "PortBindings", {"8080/tcp": [{}]}),
            ("HostConfig", "Privileged", True),
        ):
            modified = copy.deepcopy(item)
            modified[section][key] = value
            with self.assertRaises(RuntimeError):
                live.assert_network(modified, ["internal"], run)

    def test_docx_fixture_is_valid_package_with_synthetic_content(self):
        with zipfile.ZipFile(io.BytesIO(probe.docx_bytes())) as z:
            self.assertEqual(len(z.namelist()), 3)
            for name in z.namelist():
                ET.fromstring(z.read(name))
            self.assertIn(b"OFFICECHECK4826", z.read("word/document.xml"))


if __name__ == "__main__":
    unittest.main()

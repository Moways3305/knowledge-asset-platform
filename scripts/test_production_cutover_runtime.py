"""Unit guards plus opt-in local Docker recovery verification (synthetic data only)."""

import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
import uuid
from unittest.mock import patch
import production_cutover_runtime as runtime_module

from execute_production_cutover import corrected_models, escape_compose
from prepare_production_release import Runner
from production_cutover_runtime import Engine, LABEL, Runtime, payload


class PayloadTests(unittest.TestCase):
    def sample(self):
        return {
            "Name": "/WeKnora-app",
            "Config": {"Image": "old", "Cmd": ["old"], "Env": ["SECRET=keep"], "Labels": {}},
            "HostConfig": {
                "NetworkMode": "network",
                "PortBindings": {"8080/tcp": [{"HostIp": "", "HostPort": "8090"}]},
                "RestartPolicy": {"Name": "unless-stopped"},
                "Binds": ["stale"],
            },
            "Mounts": [
                {
                    "Type": "volume",
                    "Name": "actual",
                    "Source": "/private",
                    "Destination": "/data",
                    "RW": True,
                }
            ],
            "NetworkSettings": {"Networks": {"network": {"Aliases": ["app"], "IPAMConfig": None}}},
        }

    def test_staged_container_has_no_published_port_and_keeps_actual_storage_and_secret(self):
        old = self.sample()
        result = payload(
            old, "new", {"Cmd": ["new"], "Env": ["NEW=yes"]}, {"Cmd": ["old"]}, "token"
        )
        self.assertEqual(result["Cmd"], ["new"])
        self.assertIn("SECRET=keep", result["Env"])
        self.assertIn("AUTO_MIGRATE=false", result["Env"])
        self.assertEqual(result["HostConfig"]["PortBindings"], {})
        self.assertEqual(result["HostConfig"]["RestartPolicy"]["Name"], "no")
        self.assertEqual(result["HostConfig"]["Mounts"][0]["Source"], "actual")
        self.assertNotIn("Binds", result["HostConfig"])
        self.assertEqual(old, self.sample())

    def test_custom_command_is_retained_and_unsafe_volume_inheritance_rejected(self):
        old = self.sample()
        old["Config"]["Cmd"] = ["custom"]
        result = payload(old, "new", {"Cmd": ["new"]}, {"Cmd": ["old"]}, "token")
        self.assertEqual(result["Cmd"], ["custom"])
        old["HostConfig"]["VolumesFrom"] = ["untracked"]
        with self.assertRaises(RuntimeError):
            payload(old, "new", {}, {}, "token")

    def test_opened_traffic_forbids_data_rollback(self):
        runtime = object.__new__(Runtime)
        runtime.state = {"traffic_opening": True}
        with self.assertRaisesRegex(RuntimeError, "automatic data rollback forbidden"):
            runtime.recover([])


class EntrypointRecoveryTests(unittest.TestCase):
    def runtime(self, tags):
        class TagRunner:
            def image_identity(self, tag):
                return tags.get(tag)

            def docker(self, *args):
                if args[0] == "tag":
                    tags[args[2]] = args[1]
                elif args[:2] == ("image", "rm"):
                    tags.pop(args[2])
                else:
                    raise AssertionError(args)

        runtime = object.__new__(Runtime)
        runtime.r = TagRunner()
        runtime.state = {"config_replacements": [], "tag_replacements": []}
        runtime.save = lambda: None
        return runtime

    def test_new_consumer_tags_resume_without_losing_original_journal(self):
        tags = {"kap-backend:latest": "new", "kap-parse_worker:latest": "old-parse"}
        runtime = self.runtime(tags)
        original = {"tag": "kap-backend:latest", "old": "old-backend", "new": "new"}
        runtime.state["tag_replacements"].append(original.copy())
        images = {"backend": "new", "parse_worker": "new", "notification_worker": "new"}
        runtime.configure_entrypoints([], None, images)
        runtime.configure_entrypoints([], None, images)
        self.assertEqual(len(runtime.state["tag_replacements"]), 3)
        self.assertEqual(runtime.state["tag_replacements"][0], original)
        self.assertEqual(set(tags.values()), {"new"})
        runtime.restore_entrypoints()
        self.assertEqual(
            tags, {"kap-backend:latest": "old-backend", "kap-parse_worker:latest": "old-parse"}
        )

    def test_unknown_service_rejected_before_any_tag_change(self):
        tags = {"kap-backend:latest": "old"}
        runtime = self.runtime(tags)
        with self.assertRaisesRegex(RuntimeError, "unexpected operational image"):
            runtime.configure_entrypoints([], None, {"backend": "new", "unrecognized": "new"})
        self.assertEqual(tags, {"kap-backend:latest": "old"})
        self.assertEqual(runtime.state["tag_replacements"], [])

    def test_changed_or_duplicated_journal_refused_before_updates(self):
        for records in (
            [{"tag": "kap-worker:latest", "old": "old", "new": "wrong"}],
            [{"tag": "kap-worker:latest", "old": "old", "new": "new"}] * 2,
            [{"tag": "kap-worker:latest", "old": "other", "new": "new"}],
        ):
            with self.subTest(records=records):
                tags = {"kap-backend:latest": "old", "kap-worker:latest": "old"}
                runtime = self.runtime(tags)
                runtime.state["tag_replacements"] = records
                with self.assertRaises(RuntimeError):
                    runtime.configure_entrypoints([], None, {"backend": "new", "worker": "new"})
                self.assertEqual(tags, {"kap-backend:latest": "old", "kap-worker:latest": "old"})

    def test_configuration_and_mutable_tags_are_restored_together(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp).resolve()
            target = directory / "docker-compose.yml"
            target.write_text("original configuration")
            managed = directory / "managed.json"
            managed.write_text("new configuration")
            tags = {"kap-backend:latest": "old-image"}

            class Runner:
                def image_identity(self, tag):
                    return tags.get(tag)

                def docker(self, *args):
                    if args[0] == "tag":
                        tags[args[2]] = args[1]
                    elif args[:2] == ("image", "rm"):
                        tags.pop(args[2])
                    else:
                        raise AssertionError(args)

            runtime = object.__new__(Runtime)
            runtime.r = Runner()
            runtime.directory, runtime.token = directory, "cutover-test"
            runtime.state = {"config_replacements": [], "tag_replacements": []}
            runtime.save = lambda: None
            with patch.object(runtime_module, "OPERATIONAL_DIRECTORIES", {directory}):
                runtime.configure_entrypoints(
                    [target], managed, {"backend": "new-image", "migrate": "new-migrate"}
                )
                self.assertEqual(target.read_text(), "new configuration")
                self.assertEqual(tags["kap-backend:latest"], "new-image")
                runtime.restore_entrypoints()
                self.assertEqual(target.read_text(), "original configuration")
                self.assertEqual(tags, {"kap-backend:latest": "old-image"})


class ComposeLiteralTests(unittest.TestCase):
    def test_password_and_shell_expansion_are_not_reinterpolated_by_compose(self):
        value = {
            "services": {
                "app": {
                    "environment": {"KEY": "abc$SECRET${NAME}$$end"},
                    "command": ["sh", "-c", "exec app --workers ${COUNT:-2}"],
                }
            }
        }
        safe = escape_compose(value)
        self.assertEqual(
            safe["services"]["app"]["environment"]["KEY"], "abc$$SECRET$${NAME}$$$$end"
        )
        self.assertEqual(safe["services"]["app"]["command"][-1], "exec app --workers $${COUNT:-2}")
        self.assertEqual(value["services"]["app"]["environment"]["KEY"], "abc$SECRET${NAME}$$end")


class ModelCorrectionTests(unittest.TestCase):
    def records(self):
        rows = {}
        for slot, name, kind in (
            ("embedding", "text-embedding-v3", "Embedding"),
            ("rerank", "qwen3-rerank", "Rerank"),
            ("chat", "deepseek-v4-flash", "KnowledgeQA"),
        ):
            rows[slot] = {
                "id": slot,
                "name": name,
                "type": kind,
                "source": "remote",
                "parameters": {
                    "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                    "api_key": "cipher-" + slot,
                },
            }
        return rows, {"selected": {slot: slot for slot in rows}}

    def test_only_selected_aliyun_parameters_change_and_shared_key_comes_from_embedding(self):
        rows, picked = self.records()
        before = copy.deepcopy(rows)
        result = corrected_models(rows, picked)
        self.assertEqual(rows, before)
        self.assertEqual(result["chat"], rows["chat"])
        self.assertEqual(result["rerank"]["parameters"]["api_key"], "cipher-embedding")
        self.assertTrue(
            result["rerank"]["parameters"]["base_url"].endswith(
                "/api/v1/services/rerank/text-rerank/text-rerank"
            )
        )
        self.assertEqual(result, corrected_models(result, picked))

    def test_unexpected_provider_override_or_authentication_fails_closed(self):
        for delta in (
            {"provider": "other"},
            {"spec": {"x": 1}},
            {"custom_headers": {"Authorization": "secret"}},
            {"base_url": "http://localhost"},
        ):
            rows, picked = self.records()
            rows["rerank"]["parameters"].update(delta)
            with self.assertRaises(RuntimeError):
                corrected_models(rows, picked)


@unittest.skipUnless(os.environ.get("KAP_CUTOVER_DOCKER_TEST") == "1", "opt-in local Docker test")
class RealDockerRecovery(unittest.TestCase):
    def test_cold_copy_mutation_recovery_and_original_container_identity(self):
        token = "cutover-local-" + uuid.uuid4().hex[:10]
        name = "kap-cutover-test-" + token[-10:]
        network = name + "-net"
        volume = name + "-data"
        image = "kap-cutover-tools:local"
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / token
            out.mkdir()
            with (out / "private.log").open("ab") as log:
                r = Runner(log)
                api = Engine(log)
                runtime = None
                original = None
                try:
                    r.docker("network", "create", "--internal", network)
                    r.docker("volume", "create", "--label", LABEL + "=" + token, volume)
                    original = r.docker(
                        "run",
                        "-d",
                        "--name",
                        name,
                        "--network",
                        network,
                        "--network-alias",
                        "original-service",
                        "--restart",
                        "unless-stopped",
                        "--user",
                        "0",
                        "--entrypoint",
                        "python",
                        "--mount",
                        f"type=volume,src={volume},dst=/data",
                        image,
                        "-c",
                        "import signal,sys,time; signal.signal(signal.SIGTERM,lambda *a:sys.exit(0)); time.sleep(3600)",
                    )
                    r.docker(
                        "exec",
                        name,
                        "python",
                        "-c",
                        "from pathlib import Path; import os; Path('/data/item').write_text('before'); os.chmod('/data/item',0o640); os.symlink('item','/data/link')",
                    )
                    old = r.inspect(name)
                    runtime = Runtime(r, api, out, {name: old}, image)
                    runtime.freeze([name])
                    runtime.recover([name])
                    self.assertTrue(r.inspect(name)["State"]["Running"])
                    runtime = Runtime(r, api, out, {name: old}, image)
                    runtime.freeze([name])
                    runtime.backup([{"mount": old["Mounts"][0]}])
                    runtime.detach_originals()
                    cfg = json.loads(r.docker("image", "inspect", image))[0]["Config"]
                    runtime.create(name, payload(old, old["Image"], cfg, cfg, token))
                    runtime.state["data_mutated"] = True
                    runtime.save()
                    runtime.start(name)
                    r.docker(
                        "exec",
                        name,
                        "python",
                        "-c",
                        "from pathlib import Path; Path('/data/item').write_text('after'); Path('/data/new').write_text('new')",
                    )
                    runtime.recover([name])
                    self.assertEqual(r.inspect(name)["Id"], original)
                    self.assertEqual(
                        r.inspect(name)["HostConfig"]["RestartPolicy"]["Name"], "unless-stopped"
                    )
                    r.docker(
                        "exec",
                        name,
                        "python",
                        "-c",
                        "from pathlib import Path; import os,stat; assert Path('/data/item').read_text()=='before'; assert not Path('/data/new').exists(); assert os.readlink('/data/link')=='item'; assert stat.S_IMODE(os.stat('/data/item').st_mode)==0o640",
                    )
                    self.assertTrue(runtime.state["backup_complete"])
                    self.assertTrue(runtime.state["recovered"])
                    r.docker(
                        "exec",
                        name,
                        "python",
                        "-c",
                        "from pathlib import Path; Path('/data/item').write_text('after-recovery')",
                    )
                    runtime.recover([name])
                    r.docker(
                        "exec",
                        name,
                        "python",
                        "-c",
                        "from pathlib import Path; assert Path('/data/item').read_text()=='after-recovery'",
                    )
                except BaseException:
                    log.flush()
                    # This test uses only generated synthetic fixtures; no production data.
                    print((out / "private.log").read_text(errors="replace")[-6000:])
                    raise
                finally:
                    # Only exact identities created by this test. Never a production name.
                    for identity in r.docker(
                        "ps", "-aq", "--filter", "label=" + LABEL + "=" + token
                    ).splitlines():
                        self.assertEqual(r.inspect(identity)["Config"]["Labels"][LABEL], token)
                        r.docker("rm", "-f", identity)
                    if original:
                        self.assertTrue(
                            r.inspect(original)["Name"].lstrip("/").startswith("kap-cutover-test-")
                        )
                        r.docker("rm", "-f", original)
                    for vol in r.docker(
                        "volume", "ls", "-q", "--filter", "label=" + LABEL + "=" + token
                    ).splitlines():
                        self.assertEqual(
                            json.loads(r.docker("volume", "inspect", vol))[0]["Labels"][LABEL],
                            token,
                        )
                        r.docker("volume", "rm", vol)
                    r.docker("network", "rm", network)


if __name__ == "__main__":
    unittest.main()

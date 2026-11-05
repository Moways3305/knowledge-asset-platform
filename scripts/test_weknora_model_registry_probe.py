import copy
import json
import os
from pathlib import Path
import tempfile
import unittest

import weknora_model_registry_probe as probe


class RegistryLiveTests(unittest.TestCase):
    def test_public_report_is_utf8_and_never_overwrites_existing_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "live-report.json"
            report = {"passed": True, "scope": "虚构验收"}
            probe.write_public_report(path, report)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), report)
            with self.assertRaises(FileExistsError):
                probe.write_public_report(path, {"passed": False})
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), report)

    @unittest.skipUnless(
        hasattr(os, "geteuid") and os.geteuid() == 0, "requires isolated Linux root"
    )
    def test_root_container_report_readable_by_host_owner_private_file_stays_private(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            root.chmod(0o700)
            os.chown(root, 10001, 10001)
            private = root / "private.log"
            private.write_text("synthetic private fixture")
            private.chmod(0o600)
            report = root / "live-report.json"
            probe.write_public_report(report, {"passed": True})
            self.assertEqual(report.stat().st_uid, 10001)
            self.assertEqual(report.stat().st_mode & 0o777, 0o600)
            self.assertEqual(private.stat().st_uid, 0)
            child = os.fork()
            if child == 0:
                try:
                    os.setgid(10001)
                    os.setuid(10001)
                    assert json.loads(report.read_text())["passed"] is True
                    try:
                        private.read_text()
                    except PermissionError:
                        os._exit(0)
                except Exception:
                    pass
                os._exit(1)
            _, status = os.waitpid(child, 0)
            self.assertEqual(status, 0)

    def setUp(self):
        probe.REPORT["checks"] = []
        root = "https://ws-fixture.cn-beijing.maas.aliyuncs.com"
        self.data = {
            "aes_key": "unused",
            "models": {
                "embedding": {
                    "name": "text-embedding-v3",
                    "parameters": {
                        "base_url": root + "/compatible-mode/v1",
                        "api_key": "synthetic-shared",
                    },
                },
                "rerank": {
                    "name": "qwen3-rerank",
                    "parameters": {
                        "base_url": root + "/api/v1/services/rerank/text-rerank/text-rerank",
                        "api_key": "synthetic-shared",
                    },
                },
                "chat": {
                    "name": "deepseek-chat",
                    "parameters": {
                        "base_url": "https://api.deepseek.com/v1",
                        "api_key": "synthetic-deepseek",
                    },
                },
            },
        }

    def test_shared_key_and_selected_configuration_are_read_only(self):
        original = copy.deepcopy(self.data)
        selected = probe.selected_models(self.data, "ws-fixture")
        self.assertEqual(selected["embedding"]["key"], selected["rerank"]["key"])
        self.assertEqual(self.data, original)
        self.assertNotIn("synthetic-shared", str(probe.REPORT))

    def test_different_rerank_key_fails_closed(self):
        self.data["models"]["rerank"]["parameters"]["api_key"] = "wrong-synthetic-key"
        with self.assertRaisesRegex(RuntimeError, "aliyun_same_api_key"):
            probe.selected_models(self.data, "ws-fixture")

    def test_unapproved_endpoint_and_custom_auth_rejected(self):
        for field, value in (
            ("base_url", "https://other.invalid/v1"),
            ("custom_headers", {"Authorization": "synthetic"}),
        ):
            with self.subTest(field=field):
                changed = copy.deepcopy(self.data)
                changed["models"]["chat"]["parameters"][field] = value
                with self.assertRaises(RuntimeError):
                    probe.selected_models(changed, "ws-fixture")


if __name__ == "__main__":
    unittest.main()

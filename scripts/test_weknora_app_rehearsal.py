"""Offline rehearsal isolation and authenticated-decryption regression checks."""

import base64
import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

import weknora_app_probe as probe
import weknora_app_rehearsal as app


class AppRehearsalTests(unittest.TestCase):
    def original(self):
        return {
            "SYSTEM_AES_KEY": "a" * 32,
            "DB_USER": "test",
            "DB_PASSWORD": "fixture",
            "DB_HOST": "production-db",
            "REDIS_ADDR": "production-redis:6379",
            "HTTPS_PROXY": "http://production-proxy",
            "LANGFUSE_SECRET_KEY": "fixture",
            "WEKNORA_BOOTSTRAP_SYSTEM_ADMIN_EMAIL": "fixture@example.invalid",
        }

    def test_does_not_inherit_production_endpoints_or_bootstrap_controls(self):
        env = app.isolated_app_env(self.original())
        self.assertEqual(env["DB_HOST"], "127.0.0.1")
        self.assertEqual(env["REDIS_ADDR"], "127.0.0.1:6379")
        self.assertEqual(env["AUTO_MIGRATE"], "false")
        self.assertEqual(env["WEKNORA_HOUSEKEEPING_ENABLED"], "false")
        self.assertEqual(env["SYSTEM_AES_KEY"], "a" * 32)
        for key in ["HTTPS_PROXY", "LANGFUSE_SECRET_KEY", "WEKNORA_BOOTSTRAP_SYSTEM_ADMIN_EMAIL"]:
            self.assertNotIn(key, env)

    def test_refuses_unmodelled_storage_and_missing_original_credentials(self):
        for key, value in [
            ("SYSTEM_AES_KEY", ""),
            ("DB_PASSWORD", ""),
            ("STORAGE_TYPE", "s3"),
            ("RETRIEVE_DRIVER", "milvus"),
        ]:
            original = self.original()
            original[key] = value
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                app.isolated_app_env(original)

    def test_env_file_injection_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            target = Path(root) / "env"
            with self.assertRaises(RuntimeError):
                app.write_env(target, {"KEY": "value\nDB_HOST=production"})
            self.assertFalse(target.exists())

    def test_child_must_share_only_verified_isolated_namespace(self):
        item = {
            "Config": {"Labels": {app.pg.LABEL: str(Path("/run"))}},
            "HostConfig": {"NetworkMode": "container:parent", "PortBindings": {}},
        }
        with patch.object(app.pg, "inspect", return_value=item):
            app.guard_child("child", "parent", "parent-id", Path("/run"))
            for network in ["host", "bridge", "container:production"]:
                item["HostConfig"]["NetworkMode"] = network
                with self.subTest(network=network), self.assertRaises(RuntimeError):
                    app.guard_child("child", "parent", "parent-id", Path("/run"))

    def test_authentication_tag_detects_wrong_key_and_corrupt_ciphertext(self):
        key, nonce = b"a" * 32, b"b" * 12
        encrypted = nonce + AESGCM(key).encrypt(nonce, b"synthetic-secret", None)
        value = "enc:v1:" + base64.urlsafe_b64encode(encrypted).decode().rstrip("=")
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(
                probe.decrypt_values({"models": [{"api_key": value}], "legacy": "plain"}, key), 1
            )
            with self.assertRaises(InvalidTag):
                probe.decrypt_values(value, b"c" * 32)
            corrupt = "enc:v1:" + base64.urlsafe_b64encode(
                encrypted[:-1] + bytes([encrypted[-1] ^ 1])
            ).decode().rstrip("=")
            with self.assertRaises(InvalidTag):
                probe.decrypt_values(corrupt, key)
        self.assertEqual(output.getvalue(), "")


if __name__ == "__main__":
    unittest.main()

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import weknora_kap_role_probe as role


class RoleProbeTests(unittest.TestCase):
    def input(self):
        return {
            "database_url": "postgresql+asyncpg://wkfixture:synthetic@127.0.0.1:5432/kap_role_fixture",
            "weknora_base_url": "http://127.0.0.1:8080",
            "weknora_api_key": "fixture-only-key",
        }

    def test_environment_does_not_inherit_production_configuration(self):
        with patch.dict(
            os.environ,
            {
                "DATABASE_URL": "production",
                "POSTGRES_PASSWORD": "production",
                "LLM_API_KEY": "production",
                "WECOM_APP_SECRET": "production",
                "CELERY_BROKER_URL": "production",
            },
        ):
            env = role.isolated_env(self.input())
        self.assertNotIn("production", json.dumps(env))
        self.assertEqual(env["APP_ENV"], "prod")
        self.assertEqual(env["SESSION_COOKIE_SECURE"], "true")
        self.assertEqual(env["NO_PROXY"], "127.0.0.1,localhost")
        self.assertNotEqual(
            env["GENERATION_MODEL_ENCRYPTION_KEY"],
            role.isolated_env(self.input())["GENERATION_MODEL_ENCRYPTION_KEY"],
        )

    def test_rejects_non_fixture_database_or_weknora(self):
        baseline = self.input()
        for old, new in (
            ("127.0.0.1", "production"),
            ("5432", "5433"),
            ("kap_role_fixture", "WeKnora"),
            ("wkfixture", "postgres"),
            ("/kap_role_fixture", "/kap_role_fixture?host=production"),
        ):
            data = dict(baseline, database_url=baseline["database_url"].replace(old, new))
            with self.assertRaisesRegex(RuntimeError, "isolated fixture database"):
                role.isolated_env(data)
        with self.assertRaisesRegex(RuntimeError, "isolated WeKnora endpoint"):
            role.isolated_env(dict(baseline, weknora_base_url="http://production:8080"))

    def test_response_guard_rejects_identifiers_and_unauthorized_content(self):
        fixtures = {"own": {"kb": "hidden-kb", "doc": "hidden-doc", "marker": "original-only"}}
        for secret in ("hidden-kb", "hidden-doc", "original-only", "api_key", "storage_ref"):
            with self.assertRaisesRegex(RuntimeError, "forbidden fixture information"):
                role.assert_safe({"answer": secret}, fixtures)
        role.assert_safe({"answer": "original-only"}, fixtures, {"own"})
        with self.assertRaises(RuntimeError):
            role.assert_safe({"answer": "hidden-doc"}, fixtures, {"own"})

    def test_local_certificate_has_loopback_san_and_matching_key(self):
        from cryptography import x509
        from cryptography.hazmat.primitives import serialization
        import ipaddress

        with tempfile.TemporaryDirectory() as directory:
            cert_path, key_path = role.tls_files(Path(directory))
            cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
            key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
            self.assertEqual(cert.public_key().public_numbers(), key.public_key().public_numbers())
            self.assertIn(
                ipaddress.ip_address("127.0.0.1"),
                cert.extensions.get_extension_for_class(
                    x509.SubjectAlternativeName
                ).value.get_values_for_type(x509.IPAddress),
            )


if __name__ == "__main__":
    unittest.main()

import json
from pathlib import Path
import tempfile
import unittest

from production_prepare_diagnostics import classify, diagnose


class Diagnostics(unittest.TestCase):
    def test_private_values_never_returned(self):
        secret = "sk-synthetic-private-do-not-echo"
        with tempfile.TemporaryDirectory() as temp:
            stage = Path(temp)
            (stage / "private.log").write_text("env file /private/.env not found " + secret)
            (stage / "runtime-private.json").write_text(
                json.dumps(
                    {
                        "one": {
                            "Config": {
                                "Env": [secret],
                                "Labels": {
                                    "com.docker.compose.project": "weknora",
                                    "com.docker.compose.project.working_dir": "/data/weknora/repo",
                                    "com.docker.compose.project.config_files": secret,
                                },
                            }
                        }
                    }
                )
            )
            result = diagnose(stage)
            self.assertNotIn(secret, json.dumps(result))
            self.assertIn("compose_env_file_missing", result["signals"])
            self.assertEqual(result["compose_sources"][0]["directory"], "/data/weknora/repo")
            self.assertFalse(result["compose_sources"][0]["rendered"])

    def test_fixed_signal_labels_only(self):
        self.assertEqual(
            classify("password authentication failed for user secret"), ["database_authentication"]
        )
        self.assertEqual(classify("unknown flag: --format secret"), ["unsupported_option"])
        self.assertEqual(
            classify("invalid interpolation format for secret"), ["invalid_interpolation"]
        )

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import diagnose_production_cutover as diagnostic


class SafeCutoverDiagnostics(unittest.TestCase):
    def test_private_text_is_reduced_to_allowlisted_locations_and_signals(self):
        raw = """SECRET_PASSWORD=never-print
ERROR: could not resize shared memory segment SECRET_NAME: No space left on device
Traceback (most recent call last):
  File "/private/SECRET/execute_production_cutover.py", line 517, in execute
  File "/private/SECRET.py", line 99, in secret
KeyError: 'POSTGRES_PASSWORD'
KeyError: 'SECRET_VALUE'
"""
        result = diagnostic.classify(raw)
        self.assertEqual(result["missing_environment_fields"], ["POSTGRES_PASSWORD"])
        self.assertEqual(
            result["code_locations"], [{"file": "execute_production_cutover.py", "line": 517}]
        )
        self.assertIn("shared_memory", result["signals"])
        self.assertNotIn("SECRET", json.dumps(result))
        self.assertNotIn("never-print", json.dumps(result))

    def test_diagnosis_does_not_emit_helper_commands_environment_or_runtime_config(self):
        names = [
            "kap-" + s + "-1"
            for s in ("backend", "worker", "ocr_worker", "beat", "frontend", "postgres", "redis")
        ]
        names += ["WeKnora-" + s for s in ("app", "frontend", "docreader", "postgres", "redis")]
        originals = {
            name: {
                "Id": name,
                "Image": "image",
                "HostConfig": {"Memory": 1024**3, "ShmSize": 64 * 1024**2},
            }
            for name in names
        }
        helper = "a" * 64

        def inspect(name):
            if name == helper:
                return {
                    "Config": {
                        "Cmd": [
                            "-ec",
                            "exec migrate -path /app/migrations/versioned -database SECRET",
                        ],
                        "Env": ["KEY=SECRET"],
                    },
                    "State": {"Running": False, "ExitCode": 1},
                }
            return {
                **originals[name],
                "Config": {"Env": ["KEY=SECRET"]},
                "State": {"Running": True, "Health": {"Status": "healthy"}},
            }

        with tempfile.TemporaryDirectory() as temp:
            stage = Path(temp)
            (stage / "private.log").write_text(
                "RuntimeError: cutover helper failed\nSECRET", encoding="utf-8"
            )
            (stage / "state-private.json").write_text(
                json.dumps(
                    {
                        "originals": originals,
                        "helpers": [helper],
                        "recovered": True,
                        "traffic_opening": False,
                    }
                )
            )
            with patch.object(diagnostic, "inspect", side_effect=inspect):
                result = diagnostic.diagnose(stage)
            self.assertNotIn("SECRET", json.dumps(result))
            self.assertEqual(
                result["migration_helpers"],
                [{"kind": "weknora_sql", "running": False, "exit_code": 1}],
            )
            self.assertTrue(
                all(
                    item["original_image"] and item["original_container"]
                    for item in result["restored_services"]
                )
            )
            self.assertEqual(
                result["original_database_limits"]["WeKnora-postgres"]["shared_memory_mib"], 64
            )


if __name__ == "__main__":
    unittest.main()

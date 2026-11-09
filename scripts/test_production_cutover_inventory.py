import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import production_cutover_inventory as inventory
import resume_production_build as resume
from test_resume_production_build import ResumeGuards


class PreparedGuards(unittest.TestCase):
    def test_successful_preparation_can_be_read_but_cannot_be_resumed(self):
        fixture = ResumeGuards()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.validate()
        (fixture.stage / "PREPARED").touch()
        report = fixture.records["prepare-report.json"]
        report["passed"] = True
        (fixture.stage / "prepare-report.json").write_text(json.dumps(report))
        with patch.object(resume, "digest", return_value=b"synthetic"):
            result = resume.validate_records(
                fixture.runner, fixture.stage, fixture.revision, prepared=True
            )
            self.assertTrue(result[2]["passed"])
            with self.assertRaisesRegex(RuntimeError, "已准备完成"):
                resume.validate_records(fixture.runner, fixture.stage, fixture.revision)
        report["production_switched"] = True
        (fixture.stage / "prepare-report.json").write_text(json.dumps(report))
        with self.assertRaisesRegex(RuntimeError, "未切换"):
            resume.validate_records(fixture.runner, fixture.stage, fixture.revision, prepared=True)

    def test_missing_prepared_marker_stops_before_docker(self):
        with tempfile.TemporaryDirectory() as tmp:
            stage = Path(tmp)
            (stage / "prepare-report.json").write_text('{"passed":true}')
            with self.assertRaisesRegex(RuntimeError, "尚未完成"):
                resume.validate_records(None, stage, inventory.REVISION, prepared=True)


class StorageGuards(unittest.TestCase):
    def mount(self, kind="volume", source="/var/lib/docker/volumes/uploads/_data", rw=True):
        return {
            "Type": kind,
            "Source": source,
            "Name": "uploads",
            "Destination": "/data/uploads",
            "RW": rw,
        }

    def test_other_writers_and_parent_bind_mounts_are_detected(self):
        original = {"kap-backend-1": {"Id": "known", "Mounts": [self.mount()]}}
        cases = [self.mount(), self.mount("bind", "/var/lib/docker"), self.mount("bind", "/")]
        for mount in cases:
            with self.subTest(mount=mount):
                result = inventory.storage_inventory(
                    original, [{"Id": "external", "Mounts": [mount]}]
                )
                self.assertEqual(result[0]["unknown_writers"], 1)

    def test_readonly_and_different_prefix_are_not_writers(self):
        original = {"kap-backend-1": {"Id": "known", "Mounts": [self.mount("bind", "/data/files")]}}
        others = [
            {
                "Id": "external",
                "Mounts": [self.mount("bind", "/data/files2"), self.mount("bind", "/data", False)],
            }
        ]
        result = inventory.storage_inventory(original, others)
        self.assertEqual(result[0]["unknown_writers"], 0)

    def test_summary_does_not_emit_sources_or_external_names(self):
        calls = []

        class Runner:
            def docker(self, *args, **kwargs):
                calls.append(args)
                if "df" in args:
                    return "Filesystem 1024-blocks Used Available Capacity Mounted on\nSECRET 2048 1024 1024 50% /data/uploads"
                return "2048\tSECRET-PATH"

        stores = [
            {
                "owners": [("kap-backend-1", "/data/uploads")],
                "mount": self.mount(),
                "unknown_writers": 1,
            }
        ]
        result = inventory.storage_summary(Runner(), stores)
        self.assertEqual(result[0]["used_mib"], 2)
        self.assertNotIn("SECRET", json.dumps(result))
        self.assertNotIn("Source", json.dumps(result))
        self.assertTrue(
            all(args[0] == "exec" and any(op in args for op in ("du", "df")) for args in calls)
        )

    def test_unrecognized_mount_is_not_executed(self):
        stores = [
            {"owners": [("kap-backend-1", "/unknown")], "mount": self.mount(), "unknown_writers": 0}
        ]
        with self.assertRaisesRegex(RuntimeError, "未覆盖"):
            inventory.storage_summary(None, stores)


class DatabaseAndPrivacy(unittest.TestCase):
    def runner(self, outputs, calls):
        class Runner:
            def docker(self, *args, **kwargs):
                calls.append(args)
                return outputs.pop(0)

        return Runner()

    def test_database_queries_are_readonly_bounded_and_only_emit_reduced_values(self):
        calls = []
        runner = self.runner(['{"version":"0079_private_suffix"}', "{}", "3"], calls)
        result = inventory.database_state(
            runner,
            "kap-postgres-1",
            {"Config": {"Env": ["POSTGRES_USER=SECRET", "POSTGRES_DB=PRIVATE"]}},
        )
        self.assertEqual(result["migration"], "0079")
        self.assertNotIn("SECRET", json.dumps(result))
        self.assertNotIn("private_suffix", json.dumps(result))
        for args in calls:
            self.assertIn("default_transaction_read_only=on", args[2])
            self.assertIn("statement_timeout=20000", args[2])
            self.assertTrue(args[-1].startswith("SELECT "))

    def test_arbitrary_migration_or_extension_content_is_rejected(self):
        for values in [
            ['{"version":"SECRET"}'],
            ['{"version":74,"dirty":false}', '{"pg_search":"SECRET"}'],
        ]:
            name = "kap-postgres-1" if len(values) == 1 else "WeKnora-postgres"
            with self.assertRaises(RuntimeError):
                inventory.database_state(self.runner(values, []), name, {"Config": {"Env": []}})

    def test_bindings_redact_ips(self):
        result = inventory.bindings(
            {
                "HostConfig": {
                    "PortBindings": {
                        "8000/tcp": [{"HostIp": "192.0.2.123", "HostPort": "8001"}],
                        "80/tcp": [{"HostIp": "127.0.0.1", "HostPort": "18080"}],
                    }
                }
            }
        )
        self.assertEqual({x["binding"] for x in result}, {"loopback", "other"})
        self.assertNotIn("192.0.2", json.dumps(result))


class InventoryFlow(unittest.TestCase):
    def test_complete_inventory_never_creates_or_stops_containers_and_keeps_env_private(self):
        with tempfile.TemporaryDirectory() as tmp:
            stage = Path(tmp)
            out = stage / "out"
            out.mkdir()
            names = ["kap-" + s + "-1" for s in inventory.SERVICES] + [
                "kap-postgres-1",
                "WeKnora-postgres",
            ]
            original = {
                name: {
                    "Id": name,
                    "Image": "image",
                    "Mounts": [],
                    "HostConfig": {},
                    "Config": {"Env": ["API_KEY=SENTINEL-SECRET"]},
                    "NetworkSettings": {"Networks": {}},
                    "State": {"Running": name != "kap-migrate-1"},
                }
                for name in names
            }
            (stage / "runtime-private.json").write_text(json.dumps(original))
            (stage / "compose-sources-private.json").write_text("[]")
            calls = []

            class Runner:
                def inspect(self, name):
                    return copy.deepcopy(original[name])

                def docker(self, *args, **kwargs):
                    calls.append(args)
                    if args == ("ps", "-q"):
                        return "\n".join(n for n in names if n != "kap-migrate-1")
                    if args[0] == "compose" and args[-3:] == ("config", "--format", "json"):
                        return json.dumps(
                            {
                                "services": {
                                    s: {"environment": {"API_KEY": "SENTINEL-SECRET"}}
                                    for s in inventory.SERVICES
                                }
                            }
                        )
                    raise AssertionError("unexpected Docker mutation or query")

            report = {}
            with (
                patch.object(inventory, "validate_records", return_value=(stage, {}, {})),
                patch.object(inventory, "verify_candidates", return_value={}),
                patch.object(
                    inventory,
                    "database_state",
                    return_value={
                        "migration": 74,
                        "dirty": False,
                        "extensions": {"pg_search": "0.22.2"},
                    },
                ),
            ):
                inventory.collect(Runner(), stage, out, report)
            self.assertTrue(report["passed"])
            self.assertFalse(report["cutover_completed"])
            self.assertFalse(report["consistent_backup_completed"])
            self.assertNotIn("SENTINEL-SECRET", json.dumps(report))
            self.assertIn("SENTINEL-SECRET", (out / "candidate-compose-private.json").read_text())
            self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()

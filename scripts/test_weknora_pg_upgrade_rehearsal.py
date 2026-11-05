"""Safety checks for the isolated rehearsal; never requires a Docker daemon."""

import copy
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "rehearsal", Path(__file__).with_name("weknora_pg_upgrade_rehearsal.py")
)
rehearsal = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rehearsal)


class RehearsalSafetyTests(unittest.TestCase):
    def setUp(self):
        rehearsal.RUN = Path("/data/weknora/upgrade-rehearsals/run-test")
        self.container = {
            "Config": {"Labels": {rehearsal.LABEL: str(rehearsal.RUN)}},
            "HostConfig": {"NetworkMode": "none", "PortBindings": {}},
            "Mounts": [{"Destination": "/var/lib/postgresql/data", "Name": "test-copy"}],
        }

    def check_rejected(self, container):
        with patch.object(rehearsal, "inspect", return_value=container):
            with self.assertRaises(RuntimeError):
                rehearsal.guard("candidate", "test-copy")

    def test_accepts_exact_isolated_copy(self):
        with patch.object(rehearsal, "inspect", return_value=self.container):
            self.assertIs(rehearsal.guard("candidate", "test-copy"), self.container)

    def test_rejects_production_container_without_rehearsal_label(self):
        self.container["Config"]["Labels"] = {}
        self.check_rejected(self.container)

    def test_rejects_other_rehearsal(self):
        self.container["Config"]["Labels"][rehearsal.LABEL] += "-other"
        self.check_rejected(self.container)

    def test_rejects_network_or_published_ports(self):
        for field, value in [("NetworkMode", "bridge"), ("PortBindings", {"5432/tcp": [{}]})]:
            with self.subTest(field=field):
                container = copy.deepcopy(self.container)
                container["HostConfig"][field] = value
                self.check_rejected(container)

    def test_rejects_production_volume_bind_mount_and_missing_mount(self):
        for mounts in [
            [{"Destination": "/var/lib/postgresql/data", "Name": "weknora_postgres-data"}],
            [{"Destination": "/var/lib/postgresql/data", "Source": "/data/production"}],
            [],
        ]:
            with self.subTest(mounts=mounts):
                self.container["Mounts"] = mounts
                self.check_rejected(self.container)

    def test_data_or_retrieval_differences_fail_closed(self):
        before = {"tables": {"assets": "2|hash"}, "retrieval": {"query": "1|0.1"}}
        rehearsal.compare(before, copy.deepcopy(before))
        for after in [
            {**before, "tables": {"assets": "1|changed"}},
            {**before, "retrieval": {"query": "2|0.1"}},
            {"tables": before["tables"]},
            {**before, "unexpected": "data"},
        ]:
            with self.subTest(after=after), self.assertRaises(RuntimeError):
                rehearsal.compare(before, after)

    def test_sql_is_bounded_and_not_interpolated_into_shell(self):
        query = "SELECT 'private sample';"
        with patch.object(rehearsal, "docker", return_value="ok") as execute:
            self.assertEqual(rehearsal.sql("isolated", query), "ok")
        args, kwargs = execute.call_args
        self.assertIn("PGOPTIONS=-c statement_timeout=900000 -c lock_timeout=30000", args)
        self.assertNotIn(query, args)
        self.assertEqual(kwargs["data"], query.encode())


if __name__ == "__main__":
    unittest.main()

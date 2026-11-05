import copy
import unittest

import prepare_production_release as prepare


class Guards(unittest.TestCase):
    def fixture(self):
        root = "/data/weknora/upgrade-rehearsals/run-eDkLxh7B"
        return {
            "Name": "/wk-live-99b59b1df6-probe",
            "Config": {
                "Labels": {"com.docker.compose.project": "kap", prepare.REHEARSAL_LABEL: root}
            },
            "Mounts": [
                {"Type": "bind", "Source": root + "/live090-99b59b1df6", "Destination": "/evidence"}
            ],
        }

    def test_known_rehearsal_container_only(self):
        item = self.fixture()
        self.assertTrue(prepare.removable_fixture(item, {"kap_pgdata"}))
        item["Name"] = "/wk-live-99b59b1df6-egress"
        item["Mounts"] = []
        self.assertTrue(prepare.removable_fixture(item, set()))

    def test_production_names_labels_and_mounts_never_authorize_removal(self):
        for name in ("/kap-backend-1", "/WeKnora-app", "/kap-frontend-1", "/unknown"):
            item = self.fixture()
            item["Name"] = name
            self.assertFalse(prepare.removable_fixture(item, set()))
        item = self.fixture()
        del item["Config"]["Labels"][prepare.REHEARSAL_LABEL]
        self.assertFalse(prepare.removable_fixture(item, set()))
        for mount in (
            {
                "Type": "volume",
                "Name": "kap_pgdata",
                "Source": "/data/docker/volumes/kap_pgdata/_data",
                "Destination": "/evidence",
            },
            {"Type": "bind", "Source": "/data/kap/repo", "Destination": "/probe"},
            {
                "Type": "bind",
                "Source": "/data/weknora/upgrade-rehearsals/run-eDkLxh7B/../../repo",
                "Destination": "/probe",
            },
            {
                "Type": "bind",
                "Source": "/data/weknora/upgrade-rehearsals/run-eDkLxh7B/x",
                "Destination": "/var/run/docker.sock",
            },
        ):
            item = self.fixture()
            item["Mounts"] = [mount]
            self.assertFalse(prepare.removable_fixture(item, {"kap_pgdata"}))

    def test_fingerprint_ignores_mount_order_but_detects_environment_and_runtime_changes(self):
        item = {
            "Id": "one",
            "Image": "sha256:one",
            "Config": {"Env": ["SYNTHETIC=yes"]},
            "HostConfig": {"NetworkMode": "kap_internal"},
            "Mounts": [{"Source": "a"}, {"Source": "b"}],
        }
        changed = copy.deepcopy(item)
        changed["Mounts"].reverse()
        self.assertEqual(prepare.fingerprint(item), prepare.fingerprint(changed))
        changed["HostConfig"]["NetworkMode"] = "none"
        self.assertNotEqual(prepare.fingerprint(item), prepare.fingerprint(changed))

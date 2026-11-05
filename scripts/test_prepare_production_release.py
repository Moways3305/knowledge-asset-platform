import copy
import io
import subprocess
from unittest.mock import patch
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


class RollbackImages(unittest.TestCase):
    image_id = "sha256:" + "a" * 64

    def item(self):
        return {
            "Name": "/kap-migrate-1",
            "Image": self.image_id,
            "State": {"Status": "exited", "Running": False, "ExitCode": 0},
            "HostConfig": {"RestartPolicy": {"Name": "no"}},
            "Config": {
                "Image": "mutable-current-tag",
                "Labels": {
                    "com.docker.compose.project": "kap",
                    "com.docker.compose.service": "migrate",
                },
            },
        }

    def runner(self, available=False):
        image_id = self.image_id

        class FakeRunner:
            def __init__(self):
                self.calls = []

            def image_identity(self, ref):
                self.calls.append(("inspect", ref))
                return image_id if available else None

            def docker(self, *args):
                self.calls.append(args)

        return FakeRunner()

    def test_completed_job_exception_is_explicit_and_never_uses_mutable_tag(self):
        runner = self.runner()
        with self.assertRaises(RuntimeError):
            prepare.preserve_rollback_image(runner, "kap-migrate-1", self.item(), "test")
        result = prepare.preserve_rollback_image(
            runner, "kap-migrate-1", self.item(), "test", allow_completed_migrate=True
        )
        self.assertEqual(result["status"], "completed_job_image_missing")
        self.assertIsNone(result["tag"])
        self.assertFalse(result["recreate_on_rollback"])
        self.assertTrue(result["container_preserved"])
        self.assertEqual(runner.calls, [("inspect", self.image_id)] * 2)

    def test_no_other_container_can_use_exception(self):
        for name in sorted((prepare.KAP_NAMES | prepare.WK_NAMES) - {"kap-migrate-1"}):
            with self.subTest(name=name), self.assertRaises(RuntimeError):
                prepare.preserve_rollback_image(
                    self.runner(), name, self.item(), "test", allow_completed_migrate=True
                )

    def test_unfinished_failed_foreign_or_restartable_migration_is_rejected(self):
        changes = [
            ("State", "Running", True),
            ("State", "Status", "created"),
            ("State", "ExitCode", 1),
            ("State", "Dead", True),
            ("State", "Restarting", True),
        ]
        items = []
        for section, key, value in changes:
            item = self.item()
            item[section][key] = value
            items.append(item)
        for key, value in [
            ("com.docker.compose.project", "foreign"),
            ("com.docker.compose.service", "backend"),
            (prepare.REHEARSAL_LABEL, "synthetic"),
        ]:
            item = self.item()
            item["Config"]["Labels"][key] = value
            items.append(item)
        item = self.item()
        item["HostConfig"]["RestartPolicy"]["Name"] = "always"
        items.append(item)
        for item in items:
            with self.subTest(item=item), self.assertRaises(RuntimeError):
                prepare.preserve_rollback_image(
                    self.runner(), "kap-migrate-1", item, "test", allow_completed_migrate=True
                )

    def test_available_image_is_pinned_by_id_and_verified(self):
        runner = self.runner(available=True)
        result = prepare.preserve_rollback_image(runner, "kap-backend-1", self.item(), "test")
        self.assertEqual(result["status"], "preserved")
        self.assertTrue(result["recreate_on_rollback"])
        self.assertEqual(
            runner.calls,
            [
                ("inspect", self.image_id),
                ("tag", self.image_id, "kap-rollback:test-kap-backend-1"),
                ("inspect", "kap-rollback:test-kap-backend-1"),
            ],
        )

    def test_wrong_identity_and_failed_tag_verification_stop(self):
        for values in [["sha256:" + "b" * 64], [self.image_id, None]]:
            runner = self.runner()
            with patch.object(runner, "image_identity", side_effect=values):
                with self.assertRaises(RuntimeError):
                    prepare.preserve_rollback_image(runner, "kap-backend-1", self.item(), "test")

    def test_image_inspect_only_accepts_explicit_missing_image_error(self):
        log = io.BytesIO()
        runner = prepare.Runner(log)
        for stderr in [b"permission denied", b"Cannot connect to the Docker daemon", b"timeout"]:
            with (
                patch.object(
                    prepare.subprocess,
                    "run",
                    return_value=subprocess.CompletedProcess([], 1, stdout=b"", stderr=stderr),
                ),
                self.assertRaises(RuntimeError),
            ):
                runner.image_identity(self.image_id)
        with patch.object(
            prepare.subprocess,
            "run",
            return_value=subprocess.CompletedProcess(
                [], 1, stdout=b"", stderr=b"Error response from daemon: No such image: synthetic"
            ),
        ):
            self.assertIsNone(runner.image_identity(self.image_id))
        with (
            patch.object(
                prepare.subprocess,
                "run",
                return_value=subprocess.CompletedProcess(
                    [], 0, stdout=b"unexpected-private-result", stderr=b""
                ),
            ),
            self.assertRaises(RuntimeError),
        ):
            runner.image_identity(self.image_id)

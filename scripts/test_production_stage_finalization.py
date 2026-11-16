"""Exercise partial-tag finalization; fake Docker refuses service/data mutations."""

import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import finalize_stage_release as finish
import deploy_stage_release as deploy
from production_cutover_runtime import LABEL


@unittest.skipIf(os.name == "nt", "durable directory fsync is exercised on Linux")
class Finalization(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.out = self.root / "release-1234567890"
        self.out.mkdir()
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.addCleanup(patch.stopall)
        patch.object(deploy, "ROOT", self.root).start()
        patch.object(deploy, "REPO", self.repo).start()
        patch.object(finish, "source_owner", return_value="ubuntu").start()
        self.images = {"backend": "sha256:" + "a" * 64, "frontend": "sha256:" + "b" * 64}
        names = (
            list(deploy.ORIGINAL_START)
            + ["kap-migrate-1"]
            + ["WeKnora-" + s for s in ("app", "frontend", "docreader", "postgres", "redis")]
        )
        self.old = {
            name: {
                "Id": f"{i:064x}",
                "Name": "/" + name,
                "Image": "sha256:" + f"{i:064x}",
                "Config": {"Env": ["X=synthetic"], "Labels": {}},
                "HostConfig": {},
                "Mounts": [],
                "State": {"Running": name != "kap-migrate-1"},
                "NetworkSettings": {"Networks": {}},
            }
            for i, name in enumerate(names, 1)
        }
        self.configs = {
            name: {
                "Image": self.old[name]["Image"]
                if name in deploy.INFRA
                else self.images["frontend" if name == "kap-frontend-1" else "backend"],
                "Labels": {LABEL: self.out.name},
                "Env": ["X=synthetic"],
            }
            for name in deploy.START
        }
        self.state = {
            "new": {name: f"{i:064x}" for i, name in enumerate(deploy.START, 100)},
            "originals": {n: self.old[n] for n in deploy.ORIGINAL_START},
            "traffic_opening": True,
            "backup_complete": True,
            "data_mutated": True,
            "recovered": False,
            "passed": False,
            "config_replacements": [],
            "tag_replacements": [
                {
                    "tag": "kap-" + s + ":latest",
                    "old": self.old["kap-" + s + "-1"]["Image"],
                    "new": self.images["backend"],
                }
                for s in ("backend", "worker", "ocr_worker")
            ],
        }
        self.report = {
            "phase": "production_stage_rollout",
            "passed": False,
            "production_switched": True,
            "revision": deploy.REVISION,
            "version": deploy.VERSION,
            "checkpoint": "opening_traffic",
            "error": "deployment_failed_private_details_retained",
            "manual_recovery_required": True,
        }
        self.managed = {
            "services": {
                n[4:-2]: {"image": c["Image"], "environment": {"X": "synthetic"}}
                for n, c in self.configs.items()
            }
        }
        self.files = {
            "state-private.json": self.state,
            "runtime-private.json": self.old,
            "candidate-image-ids.json": self.images,
            "candidate-runtime-private.json": self.configs,
            "report.json": self.report,
            "kap-compose-private.json": self.managed,
        }
        self.save()
        self.current = {
            n: {
                "Id": self.state["new"][n],
                "Name": "/" + n,
                "Image": c["Image"],
                "Config": {"Labels": c["Labels"]},
                "State": {"Running": True, "Health": {"Status": "healthy"}},
            }
            for n, c in self.configs.items()
        }
        self.tags = {row["tag"]: row["new"] for row in self.state["tag_replacements"]}
        self.head = deploy.BASELINE
        self.dirty = False
        self.mutations = []
        self.remaining = {v["Id"] for v in self.state["originals"].values()}
        self.cleanup_running = False
        owner = self

        class Runner:
            def inspect(self, identity):
                if identity in owner.current:
                    return copy.deepcopy(owner.current[identity])
                if identity in owner.old:
                    return copy.deepcopy(owner.old[identity])
                for name, old in owner.state["originals"].items():
                    if old["Id"] == identity:
                        result = copy.deepcopy(old)
                        result["Name"] = "/" + name + "-previous-" + owner.out.name[-10:]
                        result["State"]["Running"] = owner.cleanup_running
                        return result
                raise AssertionError(identity)

            def image_identity(self, tag):
                return owner.tags.get(tag)

            def capture(self, *args, **kwargs):
                if args[-2:] == ("rev-parse", "HEAD"):
                    return owner.head
                if args[-2:] == ("status", "--porcelain"):
                    return " M fixture" if owner.dirty else ""
                if args[0] == "runuser" and args[-3:] == ("merge", "--ff-only", deploy.REVISION):
                    owner.mutations.append("git_fast_forward")
                    owner.head = deploy.REVISION
                    return ""
                raise AssertionError(args)

            def docker(self, *args, **kwargs):
                if args[0] == "compose" and args[-3:] == ("config", "--format", "json"):
                    return (owner.out / "kap-compose-private.json").read_text()
                if args[0] == "exec":
                    query = kwargs.get("data", b"").decode()
                    if query:
                        assert query.startswith("SET standard_conforming_strings=on;\nSELECT ")
                        return deploy.SCHEMA if "alembic_version" in query else "1"
                    assert "verify_deployment" in args[-1]
                    return ""
                if args[0] == "tag":
                    owner.mutations.append("tag")
                    owner.tags[args[2]] = args[1]
                    return ""
                if args[:2] == ("ps", "-aq"):
                    identity = args[-1].removeprefix("id=")
                    return identity if identity in owner.remaining else ""
                if args[0] == "rm" and len(args) == 2:
                    assert args[1] in owner.remaining and not owner.cleanup_running
                    owner.mutations.append("remove_stopped_original")
                    owner.remaining.remove(args[1])
                    return ""
                raise AssertionError("Forbidden Docker operation: " + repr(args))

        self.r = Runner()

    def save(self):
        for name, value in self.files.items():
            (self.out / name).write_text(json.dumps(value))

    def run_finish(self):
        result = {"phase": "production_stage_finalization", "production_switched": True}
        with patch("builtins.print"):
            finish.finalize(self.r, self.out, result)
        return result

    def test_partial_tags_finish_and_repeat_without_restarting_or_writing_database(self):
        failed = (self.out / "report.json").read_bytes()
        first = self.run_finish()
        self.assertTrue(first["passed"])
        self.assertEqual(first["post_deployment_tasks_pending"], [])
        self.assertEqual(len(self.tags), 8)
        self.assertEqual(self.head, deploy.REVISION)
        self.assertEqual((self.out / "report-before-finalization.json").read_bytes(), failed)
        state = json.loads((self.out / "state-private.json").read_text())
        self.assertEqual(len(state["tag_replacements"]), 8)
        self.assertEqual(state["tag_replacements"][0], self.state["tag_replacements"][0])
        mutations = list(self.mutations)
        second = self.run_finish()
        self.assertTrue(second["passed"])
        self.assertEqual(self.mutations, mutations)
        self.assertEqual((self.out / "report-before-finalization.json").read_bytes(), failed)

    def test_unhealthy_or_replaced_service_refuses_all_mutations(self):
        for field in ("health", "identity"):
            with self.subTest(field=field):
                original = copy.deepcopy(self.current["kap-backend-1"])
                if field == "health":
                    self.current["kap-backend-1"]["State"]["Health"]["Status"] = "unhealthy"
                else:
                    self.current["kap-backend-1"]["Id"] = "0" * 64
                with self.assertRaises(RuntimeError):
                    self.run_finish()
                self.assertEqual(self.mutations, [])
                self.current["kap-backend-1"] = original

    def test_closed_or_recovered_journal_refuses_all_mutations(self):
        for field, value in (
            ("traffic_opening", False),
            ("backup_complete", False),
            ("recovered", True),
        ):
            with self.subTest(field=field):
                old = self.state[field]
                self.state[field] = value
                self.save()
                with self.assertRaises(RuntimeError):
                    self.run_finish()
                self.assertEqual(self.mutations, [])
                self.state[field] = old

    def test_dirty_checkout_or_altered_compose_refuses_changes(self):
        self.dirty = True
        with self.assertRaisesRegex(RuntimeError, "repository_has_changes"):
            self.run_finish()
        self.assertEqual(self.mutations, [])
        self.dirty = False
        self.managed["services"]["backend"]["environment"]["X"] = "changed"
        self.save()
        with self.assertRaisesRegex(RuntimeError, "managed_environment_changed"):
            self.run_finish()
        self.assertEqual(self.mutations, [])

    def test_running_old_containers_are_retained(self):
        self.cleanup_running = True
        result = self.run_finish()
        self.assertTrue(result["passed"])
        self.assertEqual(len(result["post_deployment_tasks_pending"]), len(deploy.ORIGINAL_START))
        self.assertEqual(len(self.remaining), len(deploy.ORIGINAL_START))
        self.assertNotIn("remove_stopped_original", self.mutations)

    def test_compose_literal_dollar_escaping_is_accepted(self):
        self.configs["kap-backend-1"]["Env"] = ["X=synthetic$literal$$suffix"]
        self.managed["services"]["backend"]["environment"]["X"] = "synthetic$$literal$$$$suffix"
        self.save()
        self.assertTrue(self.run_finish()["passed"])


if __name__ == "__main__":
    unittest.main()

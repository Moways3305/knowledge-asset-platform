"""Application-only rollback must retain writes made after replacement."""

import copy
import json
import os
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

import rollout_vision_fix as rollout
from prepare_production_release import Runner
from production_cutover_runtime import Engine, Runtime, payload


class RolloutGuards(unittest.TestCase):
    def test_managed_compose_changes_only_the_two_accepted_images(self):
        old = {
            "kap-" + name + "-1": {"Image": "old-" + name}
            for name in ("backend", "frontend", "postgres", "worker")
        }
        original = {
            "services": {
                name[4:-2]: {"image": item["Image"], "environment": {"PRIVATE": "$$literal"}}
                for name, item in old.items()
            }
        }
        before = copy.deepcopy(original)
        result = rollout.next_compose(
            original, old, {"backend": "new-back", "frontend": "new-front"}
        )
        self.assertEqual(original, before)
        for name in ("postgres", "worker"):
            self.assertEqual(result["services"][name], original["services"][name])
        self.assertEqual(result["services"]["backend"]["environment"], {"PRIVATE": "$$literal"})
        with self.assertRaises(RuntimeError):
            rollout.next_compose(original, old, {"postgres": "forbidden"})
        original["services"]["worker"]["image"] = "concurrently-changed"
        with self.assertRaises(RuntimeError):
            rollout.next_compose(original, old, {"backend": "new", "frontend": "new"})

    def test_recovery_refuses_storage_snapshots_other_services_and_committed_rollout(self):
        runtime = object.__new__(rollout.ApplicationRuntime)
        good = {
            "originals": dict.fromkeys(rollout.TARGETS),
            "data_mutated": False,
            "backup_complete": False,
            "backups": [],
            "config_replacements": [],
            "passed": False,
        }
        for field, value in (
            ("originals", {"kap-postgres-1": {}}),
            ("data_mutated", True),
            ("backup_complete", True),
            ("backups", [{"volume": "business"}]),
            ("config_replacements", [{"target": "/data/private"}]),
            ("passed", True),
        ):
            with self.subTest(field=field), patch.object(Runtime, "recover") as base:
                runtime.state = {**good, field: value}
                with self.assertRaises(RuntimeError):
                    runtime.recover(rollout.TARGETS)
                base.assert_not_called()
        runtime.state = good
        with patch.object(Runtime, "recover") as base:
            runtime.recover(rollout.TARGETS)
            base.assert_called_once_with(rollout.TARGETS)

    def test_replacement_does_not_start_dependencies_and_failure_propagates(self):
        calls = []

        class Fake:
            def freeze(self, names):
                calls.append(("freeze", names))

            def detach_originals(self):
                calls.append(("detach",))

            def create(self, name, config):
                calls.append(("create", name))

            def start(self, name):
                calls.append(("start", name))

        def fail(name):
            if name == "kap-frontend-1":
                raise RuntimeError("injected failure")

        with self.assertRaisesRegex(RuntimeError, "injected failure"):
            rollout.replace(Fake(), dict.fromkeys(rollout.TARGETS), fail)
        self.assertEqual(
            calls,
            [
                ("freeze", tuple(reversed(rollout.TARGETS))),
                ("detach",),
                ("create", "kap-backend-1"),
                ("start", "kap-backend-1"),
                ("create", "kap-frontend-1"),
                ("start", "kap-frontend-1"),
            ],
        )
        calls.clear()
        with self.assertRaises(RuntimeError):
            rollout.replace(Fake(), {"kap-postgres-1": {}}, fail)
        self.assertEqual(calls, [])

    def test_sanitized_public_check_code_compiles_and_pins_origin_and_identity(self):
        class Capture:
            def docker(self, *args, **kwargs):
                self.args = args

        runner = Capture()
        rollout.public_health(runner, "exact-id", rollout.REVISION, "v1.0.1")
        compile(runner.args[-1], "public-check", "exec")
        self.assertEqual(runner.args[:3], ("exec", "exact-id", "python"))
        self.assertIn(rollout.ORIGIN, runner.args[-1])
        self.assertIn("follow_redirects=False", runner.args[-1])


@unittest.skipUnless(os.environ.get("KAP_VISION_DOCKER_TEST") == "1", "opt-in local Docker test")
class LiveApplicationRecovery(unittest.TestCase):
    def test_failure_after_both_started_restores_original_ids_and_retains_new_writes(self):
        token = "vision-local-" + uuid.uuid4().hex[:10]
        names = (token + "-backend", token + "-frontend")
        network, volume = token + "-net", token + "-data"
        image = "kap-cutover-tools:local"
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / token
            out.mkdir()
            with (out / "private.log").open("ab") as log:
                r, api = Runner(log), Engine(log)
                originals = {}
                try:
                    r.docker("network", "create", "--internal", network)
                    r.docker("volume", "create", "--label", "kap.vision.local=" + token, volume)
                    for index, name in enumerate(names):
                        identity = r.docker(
                            "run",
                            "-d",
                            "--name",
                            name,
                            "--network",
                            network,
                            "--network-alias",
                            "original-" + str(index),
                            "--restart",
                            "unless-stopped",
                            "--user",
                            "0",
                            "--label",
                            "kap.vision.local=" + token,
                            "--publish",
                            "127.0.0.1::8000",
                            "--mount",
                            "type=volume,src=" + volume + ",dst=/data",
                            "--entrypoint",
                            "python",
                            image,
                            "-c",
                            "import signal,sys,time; signal.signal(signal.SIGTERM,lambda *a:sys.exit(0)); time.sleep(3600)",
                        )
                        originals[name] = r.inspect(identity)
                    r.docker(
                        "exec",
                        names[0],
                        "python",
                        "-c",
                        "from pathlib import Path; Path('/data/item').write_text('before')",
                    )
                    runtime = rollout.ApplicationRuntime(r, api, out, originals, image)
                    cfg = json.loads(r.docker("image", "inspect", image))[0]["Config"]
                    configs = {
                        name: payload(item, item["Image"], cfg, cfg, token, publish=True)
                        for name, item in originals.items()
                    }

                    def fail_after_write(name):
                        if name == names[1]:
                            r.docker(
                                "exec",
                                names[0],
                                "python",
                                "-c",
                                "from pathlib import Path; Path('/data/item').write_text('new-write'); Path('/data/new').write_text('keep')",
                            )
                            raise RuntimeError("simulated public health failure")

                    with patch.object(rollout, "TARGETS", names):
                        with self.assertRaisesRegex(RuntimeError, "simulated public health"):
                            rollout.replace(runtime, configs, fail_after_write)
                        runtime.recover(names)
                    for name, previous in originals.items():
                        current = r.inspect(name)
                        self.assertEqual(current["Id"], previous["Id"])
                        self.assertTrue(current["State"]["Running"])
                        self.assertEqual(
                            current["HostConfig"]["PortBindings"],
                            previous["HostConfig"]["PortBindings"],
                        )
                        self.assertEqual(
                            current["HostConfig"]["RestartPolicy"],
                            previous["HostConfig"]["RestartPolicy"],
                        )
                        self.assertEqual(current["Config"]["Env"], previous["Config"]["Env"])
                    r.docker(
                        "exec",
                        names[0],
                        "python",
                        "-c",
                        "from pathlib import Path; assert Path('/data/item').read_text()=='new-write'; assert Path('/data/new').read_text()=='keep'",
                    )
                    self.assertFalse(runtime.state["backups"])
                    self.assertFalse(runtime.state["data_mutated"])
                    self.assertTrue(runtime.state["recovered"])
                except BaseException:
                    log.flush()
                    # Only generated local fixtures, never production configuration.
                    print((out / "private.log").read_text(errors="replace")[-5000:])
                    raise
                finally:
                    for identity in r.docker(
                        "ps", "-aq", "--filter", "label=kap.vision.local=" + token
                    ).splitlines():
                        self.assertEqual(
                            r.inspect(identity)["Config"]["Labels"]["kap.vision.local"], token
                        )
                        r.docker("rm", "-f", identity)
                    info = json.loads(r.docker("volume", "inspect", volume))[0]
                    self.assertEqual(info["Labels"]["kap.vision.local"], token)
                    r.docker("volume", "rm", volume)
                    r.docker("network", "rm", network)


if __name__ == "__main__":
    unittest.main()

"""Deployment guard regressions; these tests never connect to a Docker engine."""

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import deploy_stage_release as deploy
from production_cutover_runtime import Runtime


def original(name):
    service = name[4:-2]
    return {
        "Id": "original-" + service,
        "Name": "/" + name,
        "Image": "old-" + service,
        "Config": {
            "Image": "old-" + service,
            "Hostname": "old-host",
            "Cmd": ["old", service],
            "Env": [
                "SECRET=keep$literal",
                "CELERY_DEFAULT_QUEUE=default",
                "CELERY_TASK_ALWAYS_EAGER=false",
            ],
            "Labels": {
                "com.docker.compose.project": "kap",
                "com.docker.compose.service": service,
                "com.docker.compose.project.config_files": "scaffold.json",
            },
            "Healthcheck": {"Test": ["CMD", "true"], "Interval": 10_000_000_000},
        },
        "State": {"Running": True},
        "HostConfig": {
            "NetworkMode": "kap_internal",
            "PortBindings": {"8000/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8001"}]},
            "RestartPolicy": {"Name": "unless-stopped"},
            "NanoCpus": 1_000_000_000,
            "Memory": 4096 * 1024**2,
            "MemorySwap": 8 * 1024**3,
            "ShmSize": 64 * 1024**2,
            "CpuQuota": 100000,
            "CpuPeriod": 100000,
        },
        "Mounts": [
            {
                "Type": "volume",
                "Name": "real-upload",
                "Source": "/private/volume",
                "Destination": "/data/uploads",
                "RW": True,
            }
        ],
        "NetworkSettings": {
            "Networks": {"kap_internal": {"Aliases": [service, name], "IPAMConfig": None}}
        },
    }


class ImageRunner:
    def docker(self, *args):
        assert args[:2] == ("image", "inspect")
        service = args[2].removeprefix("old-")
        return json.dumps([{"Config": {"Cmd": ["old", service], "Env": ["DEFAULT=yes"]}}])


class ConfigGuards(unittest.TestCase):
    def setUp(self):
        self.old = {n: original(n) for n in deploy.ORIGINAL_START}
        self.copy = copy.deepcopy(self.old)
        self.configs = deploy.deployment_configs(
            ImageRunner(),
            self.old,
            {"backend": "new-backend", "frontend": "new-frontend"},
            Path("/tmp/release-1234567890"),
        )

    def test_preserves_secrets_storage_and_inputs(self):
        self.assertEqual(self.old, self.copy)
        backend = self.configs["kap-backend-1"]
        self.assertIn("SECRET=keep$literal", backend["Env"])
        self.assertEqual(backend["HostConfig"]["Mounts"][0]["Source"], "real-upload")
        for config in self.configs.values():
            self.assertEqual(config["HostConfig"]["PortBindings"], {})
            self.assertEqual(config["HostConfig"]["RestartPolicy"]["Name"], "no")

    def test_added_consumers_have_distinct_aliases_health_and_no_upload_mount(self):
        for name, queue in zip(deploy.ADDED, ("parse", "notifications")):
            config = self.configs[name]
            self.assertEqual(config["HostConfig"]["Mounts"], [])
            self.assertEqual(
                config["NetworkingConfig"]["EndpointsConfig"]["kap_internal"]["Aliases"],
                [name[4:-2], name],
            )
            self.assertIn("--queues=" + queue, config["Cmd"])
            self.assertIn(queue + "@$HOSTNAME", config["Healthcheck"]["Test"][1])
            self.assertEqual(config["Labels"]["com.docker.compose.service"], name[4:-2])

    def test_budget_change_does_not_retain_a_second_conflicting_cpu_quota(self):
        total_cpu = total_memory = 0
        for role, (cpu, memory) in deploy.RESOURCES.items():
            host = self.configs["kap-" + role + "-1"]["HostConfig"]
            self.assertEqual(host["NanoCpus"], cpu)
            self.assertEqual(host["Memory"], memory * 1024**2)
            self.assertEqual(host["MemorySwap"], 2 * host["Memory"])
            self.assertEqual(host["CpuQuota"], 0)
            self.assertEqual(host["CpuPeriod"], 0)
            total_cpu += host["NanoCpus"]
            total_memory += host["Memory"]
        self.assertEqual(total_cpu, 1_750_000_000)
        self.assertEqual(total_memory, 4 * 1024**3)

    def test_databases_keep_images_and_resources(self):
        for name in deploy.INFRA:
            self.assertEqual(self.configs[name]["Image"], self.old[name]["Image"])
            for key in ("NanoCpus", "Memory", "ShmSize"):
                self.assertEqual(
                    self.configs[name]["HostConfig"][key], self.old[name]["HostConfig"][key]
                )

    def test_unsafe_runtime_mount_inheritance_is_rejected(self):
        self.old["kap-worker-1"]["HostConfig"]["VolumesFrom"] = ["unknown"]
        with self.assertRaises(RuntimeError):
            deploy.deployment_configs(
                ImageRunner(), self.old, {"backend": "new", "frontend": "new"}, Path("/tmp/release")
            )

    def test_operational_compose_preserves_dollar_secrets_and_all_new_consumers(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            scaffold = tmp / "scaffold.json"
            scaffold.write_text("{}")
            for item in self.old.values():
                item["Config"]["Labels"]["com.docker.compose.project.config_files"] = str(scaffold)
            old_services = {
                n[4:-2]: {
                    "image": "stale-tag",
                    "build": "wrong",
                    "depends_on": {"migrate": {}},
                    "healthcheck": {"test": ["CMD", "wrong"]},
                }
                for n in self.old
            }

            class ComposeRunner:
                def docker(self, *args):
                    path = Path(args[args.index("-f") + 1])
                    return (
                        json.dumps({"services": old_services})
                        if path == scaffold
                        else path.read_text()
                    )

            result = json.loads(
                deploy.operational_compose(ComposeRunner(), self.old, self.configs, tmp).read_text()
            )
            self.assertEqual(len(result["services"]), 9)
            for role in ("backend", "worker", "parse_worker", "notification_worker"):
                self.assertEqual(result["services"][role]["environment"]["SECRET"], "keep$$literal")
                self.assertNotIn("depends_on", result["services"][role])
            self.assertEqual(result["services"]["parse_worker"]["volumes"], [])
            self.assertEqual(
                result["services"]["notification_worker"]["memswap_limit"], str(1024 * 1024**2)
            )
            self.assertEqual(result["services"]["backend"]["ports"][0]["host_ip"], "127.0.0.1")


class RecoveryGuards(unittest.TestCase):
    def test_saved_recovery_rejects_changed_storage_target(self):
        old = {n: original(n) for n in deploy.ORIGINAL_START}
        state = {
            "originals": old,
            "passed": False,
            "traffic_opening": False,
            "backups": [
                {"mount": old[deploy.INFRA[0]]["Mounts"][0], "volume": "kap-cold-1234567890-0"}
            ],
        }
        deploy.validate_recovery_state(state, old, "release-1234567890")
        state["backups"][0]["mount"] = {"Type": "bind", "Source": "/unexpected"}
        with self.assertRaisesRegex(RuntimeError, "recovery_backup_target_changed"):
            deploy.validate_recovery_state(state, old, "release-1234567890")

    def test_saved_recovery_refuses_postopening_journal(self):
        for state in ({"passed": True}, {"traffic_opening": True}):
            with self.assertRaisesRegex(RuntimeError, "automatic data rollback forbidden"):
                deploy.validate_recovery_state(state, {}, "release-1234567890")

    def test_after_boundary_recovery_refuses_before_any_docker_operation(self):
        runtime = object.__new__(deploy.StageRuntime)
        runtime.state = {"traffic_opening": True}
        runtime.r = Mock()
        with self.assertRaisesRegex(RuntimeError, "automatic data rollback forbidden"):
            runtime.recover(deploy.ORIGINAL_START)
        runtime.r.docker.assert_not_called()

    def test_recovery_removes_additions_even_when_create_was_not_saved(self):
        runtime = object.__new__(deploy.StageRuntime)
        runtime.state = {"traffic_opening": False, "new": {}}
        runtime.token = "owned"
        runtime.r = Mock()
        runtime.r.docker.return_value = "new-one\nnew-two"
        runtime.owned = lambda identity: {
            "Name": "/" + deploy.ADDED[0 if identity == "new-one" else 1],
            "State": {"Running": False},
        }
        with patch.object(Runtime, "recover") as parent:
            runtime.recover(deploy.ORIGINAL_START)
        runtime.r.docker.assert_any_call("rm", "new-one")
        runtime.r.docker.assert_any_call("rm", "new-two")
        parent.assert_called_once_with(deploy.ORIGINAL_START)

    def test_unexpected_started_consumer_blocks_preboundary_restore(self):
        runtime = object.__new__(deploy.StageRuntime)
        runtime.state = {"traffic_opening": False}
        runtime.token = "owned"
        runtime.r = Mock()
        runtime.r.docker.return_value = "new-one"
        runtime.owned = lambda _: {"Name": "/" + deploy.ADDED[0], "State": {"Running": True}}
        with patch.object(Runtime, "recover") as parent, self.assertRaises(RuntimeError):
            runtime.recover(deploy.ORIGINAL_START)
        parent.assert_not_called()

    def test_durable_boundary_precedes_first_restart_even_when_opening_fails(self):
        runtime = Mock()
        runtime.state = {"new": {name: name for name in deploy.START}, "traffic_opening": False}
        events = []
        runtime.save.side_effect = lambda: events.append(
            ("saved", runtime.state["traffic_opening"])
        )
        runtime.owned.return_value = {"State": {"Running": True}}
        runtime.r.docker.side_effect = RuntimeError("stop failed")
        with self.assertRaisesRegex(RuntimeError, "stop failed"):
            deploy.open_release(runtime, {}, {})
        self.assertEqual(events, [("saved", True)])
        self.assertTrue(runtime.state["traffic_opening"])
        runtime.create.assert_not_called()

    def test_reference_contains_no_weknora_mutation_targets(self):
        self.assertTrue(all(n.startswith("kap-") for n in deploy.START))
        self.assertNotIn("kap-migrate-1", deploy.ORIGINAL_START)
        self.assertEqual(deploy.REVISION, "309e75d5e802aed2d152785b173db5e7c507f95d")


if __name__ == "__main__":
    unittest.main()

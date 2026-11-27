"""Exercise bounded nginx shutdown without Docker or production connections."""

import copy
import io
import json
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock, patch

import deploy_navigation_update as release
import production_frontend_shutdown as shutdown
from production_cutover_runtime import LABEL


def frontend():
    return {
        "Id": "a" * 64,
        "Name": "/kap-frontend-1",
        "Image": "sha256:" + "b" * 64,
        "Config": {
            "Cmd": ["nginx", "-g", "daemon off;"],
            "Entrypoint": ["/docker-entrypoint.sh"],
            "StopSignal": "SIGQUIT",
            "Labels": {
                "com.docker.compose.project": "kap",
                "com.docker.compose.service": "frontend",
            },
        },
        "HostConfig": {"RestartPolicy": {"Name": "no"}},
        "State": {
            "Running": True,
            "ExitCode": 0,
            "OOMKilled": False,
            "Dead": False,
            "Paused": False,
            "Restarting": False,
        },
    }


class Clock:
    def __init__(self):
        self.now = 0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        assert seconds > 0
        self.now += seconds


class Runner:
    def __init__(self, item=None, *, exit_on=None, on_inspect=None, on_signal=None):
        self.item = copy.deepcopy(item or frontend())
        self.exit_on, self.on_inspect, self.on_signal = exit_on, on_inspect, on_signal
        self.calls = []

    def inspect(self, identity):
        return json.loads(self.docker("inspect", identity))[0]

    def docker(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if args[0] == "inspect":
            if self.on_inspect:
                self.on_inspect(self)
            return json.dumps([self.item])
        if args[0] == "kill":
            signal = args[1].removeprefix("--signal=")
            assert signal in {"QUIT", "TERM"}, "Unexpected destructive signal"
            if self.on_signal:
                self.on_signal(signal, self)
            if signal == self.exit_on:
                self.item["State"].update(Running=False, ExitCode=0)
            return self.item["Id"]
        raise AssertionError(f"Unexpected operation: {args[0]}")

    @property
    def signals(self):
        return [args[1] for args, _ in self.calls if args[0] == "kill"]


class FrontendShutdown(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.output = io.StringIO()

    def stop(self, runner, reference=None, **kwargs):
        with (
            patch.object(shutdown.time, "monotonic", self.clock.monotonic),
            patch.object(shutdown.time, "sleep", self.clock.sleep),
            redirect_stdout(self.output),
        ):
            shutdown.stop_frontend(
                runner,
                copy.deepcopy(reference or frontend()),
                grace=kwargs.pop("grace", 4),
                terminate_grace=kwargs.pop("terminate_grace", 2),
                **kwargs,
            )

    def test_clean_quit_never_sends_term(self):
        runner = Runner(exit_on="QUIT")
        reference = frontend()
        saved = copy.deepcopy(reference)
        self.stop(runner, reference)
        self.assertEqual(runner.signals, ["--signal=QUIT"])
        self.assertEqual(self.clock.now, 0)
        self.assertEqual(reference, saved)
        self.assertFalse(runner.item["State"]["Running"])

    def test_lingering_request_gets_term_only_after_grace(self):
        sent_at = []
        runner = Runner(
            exit_on="TERM",
            on_signal=lambda signal, _runner: sent_at.append((signal, self.clock.now)),
        )
        self.stop(runner)
        self.assertEqual(sent_at, [("QUIT", 0), ("TERM", 4)])
        self.assertEqual(runner.item["State"]["ExitCode"], 0)
        self.assertIn("关闭剩余 HTTP 连接", self.output.getvalue())

    def test_unresponsive_frontend_fails_without_sigkill_or_docker_stop(self):
        runner = Runner()
        with self.assertRaisesRegex(RuntimeError, "frontend_termination_timeout"):
            self.stop(runner)
        self.assertEqual(self.clock.now, 6)
        self.assertEqual(runner.signals, ["--signal=QUIT", "--signal=TERM"])
        self.assertTrue(runner.item["State"]["Running"])
        self.assertEqual({args[0] for args, _ in runner.calls}, {"inspect", "kill"})

    def test_long_wait_emits_progress_without_raw_runtime_configuration(self):
        runner = Runner(exit_on="TERM")
        runner.item["Config"]["Env"] = ["PRIVATE_TEST_SECRET=must-not-be-printed"]
        self.stop(runner, grace=34)
        output = self.output.getvalue()
        self.assertGreaterEqual(output.count("等待前端退出，已用时"), 2)
        self.assertNotIn("PRIVATE_TEST_SECRET", output)
        self.assertNotIn("must-not-be-printed", output)

    def test_wrong_runtime_reference_is_rejected_before_any_docker_call(self):
        changes = [
            lambda item: item.update(Name="/kap-worker-1"),
            lambda item: item["Config"].update(Cmd=["python", "worker.py"]),
            lambda item: item["Config"].update(Entrypoint=["/custom-entrypoint.sh"]),
            lambda item: item["Config"].update(StopSignal="SIGTERM"),
            lambda item: item["Config"]["Labels"].update({"com.docker.compose.project": "other"}),
            lambda item: item["Config"]["Labels"].update({"com.docker.compose.service": "worker"}),
        ]
        for change in changes:
            with self.subTest(change=changes.index(change)):
                reference, runner = frontend(), Runner()
                change(reference)
                with self.assertRaisesRegex(RuntimeError, "unexpected_frontend_runtime"):
                    self.stop(runner, reference)
                self.assertEqual(runner.calls, [])

    def test_changed_id_image_command_or_name_never_receives_signal(self):
        changes = [
            lambda item: item.update(Id="c" * 64),
            lambda item: item.update(Image="sha256:" + "d" * 64),
            lambda item: item.update(Name="/kap-backend-1"),
            lambda item: item["Config"].update(Cmd=["nginx", "-s", "reload"]),
            lambda item: item["Config"].update(StopSignal="SIGTERM"),
        ]
        for change in changes:
            with self.subTest(change=changes.index(change)):
                runner = Runner()
                change(runner.item)
                with self.assertRaises(RuntimeError):
                    self.stop(runner)
                self.assertEqual(runner.signals, [])

    def test_restart_policy_and_unsafe_states_are_rejected(self):
        for condition in ("restart", "OOMKilled", "Dead", "Paused", "Restarting"):
            with self.subTest(condition=condition):
                runner = Runner()
                if condition == "restart":
                    runner.item["HostConfig"]["RestartPolicy"]["Name"] = "unless-stopped"
                else:
                    runner.item["State"][condition] = True
                with self.assertRaises(RuntimeError):
                    self.stop(runner)
                self.assertEqual(runner.signals, [])

    def test_nonzero_exit_and_oom_after_signal_are_not_success(self):
        for exit_code, oom in ((137, False), (143, False), (1, False), (0, True)):
            with self.subTest(exit_code=exit_code, oom=oom):

                def stopped(_signal, runner):
                    runner.item["State"].update(Running=False, ExitCode=exit_code, OOMKilled=oom)

                runner = Runner(on_signal=stopped)
                with self.assertRaises(RuntimeError):
                    self.stop(runner)
                self.assertEqual(runner.signals, ["--signal=QUIT"])

    def test_candidate_requires_current_deployment_token(self):
        reference = frontend()
        reference["Config"]["Labels"][LABEL] = "release-expected"
        for actual in (None, "release-other"):
            with self.subTest(actual=actual):
                runner = Runner(reference)
                runner.item["Config"]["Labels"][LABEL] = actual
                with self.assertRaisesRegex(RuntimeError, "frontend_identity_changed"):
                    self.stop(runner, reference, token="release-expected")
                self.assertEqual(runner.signals, [])
        runner = Runner(reference, exit_on="QUIT")
        self.stop(runner, reference, token="release-expected")
        self.assertEqual(runner.signals, ["--signal=QUIT"])

    def test_identity_is_rechecked_before_fallback_signal(self):
        def changed(runner):
            if self.clock.now >= 4:
                runner.item["Image"] = "sha256:" + "e" * 64

        runner = Runner(on_inspect=changed)
        with self.assertRaisesRegex(RuntimeError, "frontend_identity_changed"):
            self.stop(runner)
        self.assertEqual(runner.signals, ["--signal=QUIT"])

    def test_natural_clean_exit_racing_with_signal_is_accepted(self):
        def raced(_signal, runner):
            runner.item["State"].update(Running=False, ExitCode=0)
            raise RuntimeError("container already exited")

        runner = Runner(on_signal=raced)
        self.stop(runner)
        self.assertEqual(runner.signals, ["--signal=QUIT"])

    def test_failed_signal_to_live_container_is_not_swallowed(self):
        def failed(_signal, _runner):
            raise RuntimeError("synthetic signal failure")

        runner = Runner(on_signal=failed)
        with self.assertRaisesRegex(RuntimeError, "synthetic signal failure"):
            self.stop(runner)
        self.assertEqual(runner.signals, ["--signal=QUIT"])

    def test_already_cleanly_exited_container_needs_no_signal(self):
        runner = Runner()
        runner.item["State"].update(Running=False, ExitCode=0)
        self.stop(runner)
        self.assertEqual(runner.signals, [])


class NavigationShutdownDispatch(unittest.TestCase):
    def runtime(self):
        runtime = object.__new__(release.NavigationRuntime)
        runtime.r = Mock()
        runtime.token = "release-synthetic"
        runtime.state = {"originals": {shutdown.FRONTEND: frontend()}, "new": {}}
        return runtime

    def test_original_frontend_uses_bounded_nginx_path(self):
        runtime = self.runtime()
        old = runtime.state["originals"][shutdown.FRONTEND]
        with patch.object(release, "stop_frontend") as stop:
            runtime.stop(shutdown.FRONTEND, old["Id"], grace=600)
        stop.assert_called_once_with(runtime.r, old, token=None)
        runtime.r.docker.assert_not_called()

    def test_candidate_frontend_uses_bounded_path_with_deployment_identity(self):
        runtime = self.runtime()
        candidate = frontend()
        candidate.update(Id="c" * 64, Image="sha256:" + "d" * 64)
        candidate["Config"]["Labels"][LABEL] = runtime.token
        runtime.state["new"][shutdown.FRONTEND] = candidate["Id"]
        runtime.r.inspect.return_value = candidate
        with patch.object(release, "stop_frontend") as stop:
            runtime.stop(shutdown.FRONTEND, candidate["Id"])
        stop.assert_called_once_with(runtime.r, candidate, token=runtime.token)
        runtime.r.docker.assert_not_called()

    def test_unrecorded_frontend_cannot_be_stopped(self):
        runtime = self.runtime()
        with patch.object(release, "stop_frontend") as stop:
            with self.assertRaisesRegex(RuntimeError, "unexpected_frontend_identity"):
                runtime.stop(shutdown.FRONTEND, "unrecorded")
        stop.assert_not_called()
        runtime.r.inspect.assert_not_called()

    def test_non_frontend_keeps_existing_stop_signal_and_grace(self):
        for name in ("kap-worker-1", "kap-backend-1", "kap-postgres-1", "kap-redis-1"):
            with self.subTest(name=name):
                runtime = self.runtime()
                with patch.object(release, "stop_frontend") as stop:
                    runtime.stop(name, "existing-identity", grace=600)
                stop.assert_not_called()
                runtime.r.docker.assert_called_once_with(
                    "stop", "-t", "600", "existing-identity", timeout=660
                )


if __name__ == "__main__":
    unittest.main()

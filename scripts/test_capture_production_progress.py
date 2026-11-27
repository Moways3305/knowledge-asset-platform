"""Exercise quiet-command progress without exposing subprocess data or leaving children."""

from contextlib import redirect_stdout
import hashlib
import io
import os
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import prepare_production_release as release


class CaptureProgress(unittest.TestCase):
    def setUp(self):
        self.private = tempfile.TemporaryFile()
        self.addCleanup(self.private.close)
        self.public = io.StringIO()
        self.runner = release.Runner(self.private)
        self.created = []
        self.inputs = []
        original_popen = subprocess.Popen

        def spawn(*args, **kwargs):
            process = original_popen(*args, **kwargs)
            self.created.append(process)
            self.inputs.append(kwargs.get("stdin"))
            return process

        self.progress = patch.object(release, "CAPTURE_PROGRESS_INTERVAL", 0.03)
        self.progress.start()
        self.addCleanup(self.progress.stop)
        self.popen = patch.object(release.subprocess, "Popen", side_effect=spawn)
        self.popen.start()
        self.addCleanup(self.popen.stop)

    def assert_reaped(self):
        self.assertEqual(len(self.created), 1)
        process = self.created[0]
        self.assertIsNotNone(process.poll())
        self.assertTrue(process.stdout.closed)
        if process.stdin is not None:
            self.assertTrue(process.stdin.closed)
        if self.inputs[0] is not None:
            self.assertTrue(self.inputs[0].closed)
        if os.name == "posix":
            with self.assertRaises(ChildProcessError):
                os.waitpid(process.pid, os.WNOHANG)

    def test_partial_stdin_large_stdout_and_private_data_survive_multiple_heartbeats(self):
        payload = b"synthetic-private-input\n" * 100000
        expected = hashlib.sha256(payload).hexdigest()
        code = (
            "import hashlib,os,sys,time; "
            "time.sleep(0.15); data=sys.stdin.buffer.read(); "
            "sys.stderr.write('synthetic-private-error'); sys.stderr.flush(); "
            "time.sleep(0.15); "
            "sys.stdout.write('X'*1048576+'\\n'+str(len(data))+'\\n'+"
            "hashlib.sha256(data).hexdigest()+'\\n'+sys.argv[1]+'\\n'+"
            "os.environ['KAP_CAPTURE_SYNTHETIC_SECRET']); sys.stdout.flush(); time.sleep(0.1)"
        )
        with (
            patch.dict(os.environ, {"KAP_CAPTURE_SYNTHETIC_SECRET": "synthetic-private-env"}),
            redirect_stdout(self.public),
        ):
            result = self.runner.capture(
                sys.executable, "-c", code, "synthetic-private-argument", data=payload, timeout=5
            )
        self.assertEqual(
            result,
            "X" * 1048576
            + f"\n{len(payload)}\n{expected}\nsynthetic-private-argument\nsynthetic-private-env".replace(
                "\n", os.linesep
            ),
        )
        public = self.public.getvalue()
        self.assertGreaterEqual(public.count("当前步骤仍在运行"), 2)
        for secret in (
            "synthetic-private-input",
            "synthetic-private-error",
            "synthetic-private-env",
            "synthetic-private-argument",
            expected,
            "XXXX",
        ):
            self.assertNotIn(secret, public)
        self.private.seek(0)
        self.assertEqual(self.private.read(), b"synthetic-private-error")
        self.assert_reaped()

    def test_timeout_is_overall_deadline_and_reaps_child(self):
        started = time.monotonic()
        with redirect_stdout(self.public), self.assertRaises(subprocess.TimeoutExpired) as raised:
            self.runner.capture(
                sys.executable,
                "-c",
                "import sys,time; print('synthetic-private-output',flush=True); time.sleep(30)",
                timeout=0.4,
            )
        elapsed = time.monotonic() - started
        self.assertGreaterEqual(elapsed, 0.35)
        self.assertLess(elapsed, 3)
        self.assertEqual(raised.exception.timeout, 0.4)
        self.assertEqual(raised.exception.output, b"synthetic-private-output" + os.linesep.encode())
        self.assertNotIn("synthetic-private-output", self.public.getvalue())
        self.assertGreaterEqual(self.public.getvalue().count("当前步骤仍在运行"), 2)
        self.assert_reaped()

    def test_nonzero_exit_keeps_safe_error_and_private_stderr(self):
        with (
            redirect_stdout(self.public),
            self.assertRaisesRegex(RuntimeError, "操作失败，详细信息已保存在 private.log"),
        ):
            self.runner.capture(
                sys.executable,
                "-c",
                "import sys; print('synthetic-private-output'); "
                "sys.stderr.write('synthetic-private-error'); sys.exit(7)",
            )
        self.assertNotIn("synthetic-private", self.public.getvalue())
        self.private.seek(0)
        self.assertEqual(self.private.read(), b"synthetic-private-error")
        self.assertEqual(self.created[0].returncode, 7)
        self.assert_reaped()

    def test_interrupted_progress_kills_and_reaps_the_child(self):
        with (
            patch("builtins.print", side_effect=KeyboardInterrupt),
            self.assertRaises(KeyboardInterrupt),
        ):
            self.runner.capture(sys.executable, "-c", "import time; time.sleep(30)")
        self.assert_reaped()


if __name__ == "__main__":
    unittest.main()

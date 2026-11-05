import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import prepare_production_release as prepare
import resume_production_build as resume


class CandidateBuild(unittest.TestCase):
    def test_mirrors_are_build_only_and_all_artifacts_are_checked(self):
        with tempfile.TemporaryDirectory() as tmp:
            stage = Path(tmp)
            source = stage / "source"
            source.mkdir()
            manifest = {"version": "1.0.0", "commit": "a" * 40}
            calls = []

            class Fake:
                def execute(self, args, **kwargs):
                    calls.append((args, kwargs))

                def capture(self, *args, **kwargs):
                    return ""

                def docker(self, *args):
                    if args[:2] == ("image", "inspect"):
                        return json.dumps([{"Id": args[-1]}])
                    self_outer.assertIn("--network", args)
                    self_outer.assertEqual(args[args.index("--network") + 1], "none")
                    if args[-1] == "heads":
                        return "0083_model_registry (head)"
                    return json.dumps(manifest)

            self_outer = self
            report = {}
            with patch("builtins.print"):
                images = prepare.build_candidates(
                    Fake(),
                    stage,
                    source,
                    manifest,
                    report,
                    debian_mirror=resume.MIRROR,
                    security_mirror=resume.SECURITY,
                    timeout=1800,
                )
            self.assertEqual(len(images), 6)
            self.assertEqual(len(calls), 6)
            self.assertTrue(report["image_release_identities_verified"])
            for args, kwargs in calls:
                self.assertIn("build", args)
                self.assertNotIn("up", args)
                self.assertIn("KAP_DEBIAN_MIRROR=" + resume.MIRROR, args)
                self.assertIn("KAP_DEBIAN_SECURITY_MIRROR=" + resume.SECURITY, args)
                self.assertEqual(kwargs["timeout"], 1800)
            overlay = json.loads((stage / "candidate-images.json").read_text())
            self.assertEqual(set(overlay), {"services"})
            self.assertTrue(all(set(v) == {"image"} for v in overlay["services"].values()))

    def test_changed_candidate_tags_stop_before_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            stage = Path(tmp)
            (stage / "candidate-images.json").write_text(
                '{"services":{"backend":{"image":"production"}}}'
            )
            with self.assertRaisesRegex(RuntimeError, "候选镜像标签记录"):
                prepare.build_candidates(None, stage, stage, {}, {})

    def test_private_build_output_is_reduced_to_fixed_phase(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "private.log"
            path.write_text(
                "SECRET=value\n#10 RUN apt-get install\n#10 50.2 Unpacking private-package"
            )
            self.assertEqual(resume.progress_phase(path), "解包系统组件")


class ResumeGuards(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.stage = Path(self.tmp.name).resolve()
        self.source = self.stage / "source"
        self.source.mkdir()
        self.revision = "a" * 40
        self.records = {
            "prepare-report.json": {
                "production_switched": False,
                "passed": False,
                "database_archives_readable": True,
                "running_service_rollback_images_preserved": True,
            },
            "release-manifest.json": {"commit": self.revision},
        }
        self.originals = {}
        rollback = {}
        for index, name in enumerate(sorted(prepare.KAP_NAMES | prepare.WK_NAMES)):
            image = "sha256:" + f"{index:064x}"
            self.originals[name] = {
                "Id": name,
                "Name": "/" + name,
                "Image": image,
                "Config": {"Env": ["synthetic"]},
                "HostConfig": {},
                "Mounts": [],
                "State": {
                    "Running": name != "kap-migrate-1",
                    "Status": "exited" if name == "kap-migrate-1" else "running",
                    "ExitCode": 0,
                },
            }
            rollback[name] = {
                "image_id": image,
                "tag": "kap-rollback:" + self.stage.name + "-" + name.lower().replace("_", "-"),
            }
        rollback["kap-migrate-1"].update(
            tag=None, status="completed_job_image_missing", recreate_on_rollback=False
        )
        self.records["runtime-private.json"] = self.originals
        self.records["rollback-images.json"] = rollback
        configs = {}
        for index, rel in enumerate((".env", "backend/.env")):
            backup = self.stage / f"config-private-{index}"
            backup.write_text("synthetic")
            configs[str(Path("/data/kap/repo") / rel)] = str(backup)
        self.records["config-backups-private.json"] = configs
        databases = {}
        for name in ("kap-postgres-1", "WeKnora-postgres"):
            archive = self.stage / (name + ".dump")
            archive.write_bytes(b"synthetic")
            databases[name] = [{"archive": str(archive), "bytes": 9}]
            (self.stage / (name + "-globals-private.sql")).write_text("synthetic")
        self.records["database-backups-private.json"] = databases
        services = ("backend", "worker", "ocr_worker", "beat", "frontend", "migrate")
        self.records["candidate-images.json"] = {
            "services": {
                s: {"image": "kap-candidate:" + self.stage.name + "-" + s.replace("_", "-")}
                for s in services
            }
        }
        owner = self

        class Fake:
            def capture(self, *args):
                if "status" in args:
                    return ""
                return owner.revision if str(owner.source) in args else prepare.BASELINE

            def inspect(self, name):
                return copy.deepcopy(owner.originals[name])

            def image_identity(self, tag):
                return next(v["image_id"] for v in rollback.values() if v["tag"] == tag)

        self.runner = Fake()

    def validate(self):
        for name, value in self.records.items():
            (self.stage / name).write_text(json.dumps(value))
        with patch.object(resume, "digest", return_value=b"synthetic-hash"):
            return resume.validate_records(self.runner, self.stage, self.revision)

    def test_completed_migrate_exception_and_unchanged_records_are_accepted(self):
        source, manifest, _ = self.validate()
        self.assertEqual(source, self.source)
        self.assertEqual(manifest["commit"], self.revision)

    def test_changed_production_identity_or_stopped_service_is_rejected(self):
        old_inspect = self.runner.inspect
        for alteration in ({"Id": "changed"}, {"State": {"Running": False}}):

            def changed(name):
                value = old_inspect(name)
                if name == "kap-backend-1":
                    value.update(alteration)
                return value

            with (
                patch.object(self.runner, "inspect", side_effect=changed),
                self.assertRaises(RuntimeError),
            ):
                self.validate()

    def test_missing_backup_or_changed_candidate_tag_is_rejected(self):
        self.records["database-backups-private.json"]["kap-postgres-1"][0]["bytes"] = 10
        with self.assertRaisesRegex(RuntimeError, "备份文件"):
            self.validate()
        self.records["database-backups-private.json"]["kap-postgres-1"][0]["bytes"] = 9
        self.records["candidate-images.json"]["services"]["backend"]["image"] = "kap-backend"
        with self.assertRaisesRegex(RuntimeError, "候选标签"):
            self.validate()

    def test_prepared_stage_and_dirty_source_are_rejected(self):
        (self.stage / "PREPARED").touch()
        with self.assertRaisesRegex(RuntimeError, "已准备完成"):
            self.validate()
        (self.stage / "PREPARED").unlink()
        old_capture = self.runner.capture
        with (
            patch.object(
                self.runner,
                "capture",
                side_effect=lambda *a: "dirty" if "status" in a else old_capture(*a),
            ),
            self.assertRaisesRegex(RuntimeError, "未提交修改"),
        ):
            self.validate()

    def test_config_drift_and_rollback_loss_are_rejected(self):
        self.validate()
        with (
            patch.object(resume, "digest", side_effect=[b"old", b"changed"]),
            self.assertRaisesRegex(RuntimeError, "生产配置"),
        ):
            resume.validate_records(self.runner, self.stage, self.revision)
        with (
            patch.object(self.runner, "image_identity", return_value=None),
            self.assertRaisesRegex(RuntimeError, "回滚镜像"),
        ):
            self.validate()


class BuildTimeout(unittest.TestCase):
    def test_timeout_terminates_only_the_spawned_build_process_group(self):
        import signal
        import subprocess
        from unittest.mock import MagicMock

        process = MagicMock()
        process.pid = 12345
        process.wait.side_effect = [subprocess.TimeoutExpired("synthetic", 1), 0]
        process.poll.return_value = None
        runner = resume.ResumeRunner(MagicMock())
        with (
            patch.object(resume.subprocess, "Popen", return_value=process) as start,
            patch.object(resume.time, "monotonic", side_effect=[0, 2, 2]),
            patch.object(resume.os, "killpg", create=True) as kill,
        ):
            with self.assertRaisesRegex(RuntimeError, "时间上限"):
                runner.execute(["synthetic"], timeout=1)
            self.assertTrue(start.call_args.kwargs["start_new_session"])
            kill.assert_called_once_with(process.pid, signal.SIGTERM)

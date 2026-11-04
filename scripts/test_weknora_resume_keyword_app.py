import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import weknora_app_rehearsal as app
import weknora_keyword_app_rehearsal as build
import weknora_resume_keyword_app as resume


class ResumeTests(unittest.TestCase):
    def fixture(self):
        return {
            "Name": "/WeKnora-app",
            "Id": "original-container",
            "Image": "original-image",
            "Config": {"Env": ["FIXTURE=test"], "Labels": {"fixture": "one"}},
            "Mounts": [
                {"Source": "/fixture/files", "Destination": "/data/files", "RW": True},
                {"Source": "/fixture/config", "Destination": "/app/config", "RW": False},
            ],
        }

    def test_mount_order_ignored_but_content_changes_detected(self):
        original = self.fixture()
        expected = app.container_fingerprint(original)
        reordered = copy.deepcopy(original)
        reordered["Mounts"].reverse()
        self.assertEqual(app.container_fingerprint(reordered), expected)
        self.assertEqual(original, self.fixture())
        variants = []
        for key in ("Id", "Image", "Config"):
            item = copy.deepcopy(original)
            item[key] = "different"
            variants.append(item)
        for key in ("Source", "Destination", "RW"):
            item = copy.deepcopy(original)
            item["Mounts"][0][key] = "different"
            variants.append(item)
        for mounts in ([], original["Mounts"] * 2, original["Mounts"][:1]):
            item = copy.deepcopy(original)
            item["Mounts"] = mounts
            variants.append(item)
        for item in variants:
            self.assertNotEqual(app.container_fingerprint(item), expected)

    def test_original_backup_required_and_current_changes_still_block(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            original = self.fixture()
            (run / "runtime-private.json").write_text(json.dumps([original]))
            current = {"WeKnora-app": app.container_fingerprint(original), "kap-backend-1": "same"}
            with patch.object(app, "production_fingerprint", return_value=current):
                report = resume.recheck_production(run)
                self.assertEqual(report["backup_containers_checked"], ["WeKnora-app"])
            changed = {**current, "WeKnora-app": "changed"}
            with patch.object(app, "production_fingerprint", return_value=changed):
                with self.assertRaises(RuntimeError):
                    resume.recheck_production(run)
            with patch.object(
                app,
                "production_fingerprint",
                side_effect=[current, {**current, "kap-backend-1": "changed"}],
            ):
                with self.assertRaises(RuntimeError):
                    resume.recheck_production(run)

    def test_resume_rejects_incomplete_or_unverified_builds(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory).resolve()
            stage = run / "keyword-build-fixture"
            sql = run / "app090-fixture" / "search-plan-fixture"
            stage.mkdir()
            sql.mkdir(parents=True)
            (stage / "exit-code").write_text("1")
            (stage / "private.log").write_text("comparison differs; do not upgrade production")
            (sql / "exit-code").write_text("0")
            (sql / "report.json").write_text(
                json.dumps({"plan_guard_verification": {"passed": True}})
            )
            (sql.parent / "images.json").write_text(json.dumps({"app": "base"}))
            manifest = {
                "sql_stage": str(sql),
                "anydoc": True,
                "rust_toolchain": build.RUST_TOOLCHAIN,
                "source": {"source_manifest_sha256": build.SOURCE_MANIFEST_SHA},
            }
            target = stage / "build-manifest.json"
            target.write_text(json.dumps(manifest))
            with patch.object(app, "verify_built_image", return_value="verified-image") as verify:
                self.assertEqual(resume.validate_completed_build(stage, run), "verified-image")
                verify.assert_called_once_with(stage, run, "base")
                for key, value in (("anydoc", False), ("rust_toolchain", "stable"), ("source", {})):
                    target.write_text(json.dumps({**manifest, key: value}))
                    with self.assertRaises(RuntimeError):
                        resume.validate_completed_build(stage, run)
                target.write_text(json.dumps(manifest))
                (stage / "private.log").write_text("build timeout")
                with self.assertRaises(RuntimeError):
                    resume.validate_completed_build(stage, run)
            self.assertFalse((stage / "PASS-BUILD").exists())


if __name__ == "__main__":
    unittest.main()

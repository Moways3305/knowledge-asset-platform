import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import json

import weknora_keyword_app_rehearsal as build
import weknora_app_rehearsal as app


class KeywordAppTests(unittest.TestCase):
    def test_patch_integrity_and_scope(self):
        target = Path(__file__).resolve().parents[1] / "patches/weknora-v0.9.0-keyword.patch"
        data = target.read_bytes()
        self.assertEqual(hashlib.sha256(data).hexdigest(), build.PATCH_SHA)
        paths = [
            line.split()[2][2:]
            for line in data.decode().splitlines()
            if line.startswith("diff --git ")
        ]
        self.assertEqual(len(paths), 5)
        self.assertTrue(
            all(p.startswith("internal/application/repository/retriever/postgres/") for p in paths)
        )

    def test_builder_keeps_native_parser_and_gates_binary_on_tests(self):
        upstream = (
            "# browser stage not needed\n# Build stage\nFROM golang:1.26-bookworm AS builder\n"
            "RUN go install -tags 'postgres' github.com/golang-migrate/migrate/v4/cmd/migrate@latest\n"
            "COPY cmd/download cmd/download\nRUN go run cmd/download/duckdb/duckdb.go\n"
            "RUN --mount=type=cache,target=/go/pkg/mod bash ./scripts/copy-licenses.sh /license-bundle\n"
            "RUN --mount=type=cache,target=/go/pkg/mod cp -r /go/pkg/mod/github.com/yanyiwu/ /app/yanyiwu/\n"
            "# Link the anydoc parser engine\nARG WITH_ANYDOC=1\nRUN make build-prod GO_BUILD_TAGS=anydoc\n"
            "# Final stage\nFROM ignored\n"
        )
        dockerfile = build.dockerfile(upstream)
        self.assertNotIn("migrate@latest", dockerfile)
        self.assertNotIn("browser stage", dockerfile)
        self.assertIn("FROM ${KAP_RUNTIME_IMAGE}", dockerfile)
        self.assertIn("GO_BUILD_TAGS=anydoc", dockerfile)
        self.assertLess(dockerfile.index("go test "), dockerfile.index("make build-prod"))
        self.assertIn("GOMAXPROCS=2 GOFLAGS=-p=2 CARGO_BUILD_JOBS=2", dockerfile)
        with self.assertRaises(RuntimeError):
            build.dockerfile("unexpected layout")

    def test_runtime_cannot_be_swapped_without_pass_marker_and_matching_labels(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory).resolve()
            stage = run / "keyword-build-fixture"
            stage.mkdir()
            manifest = {
                "base_image": "original",
                "upstream": build.UPSTREAM,
                "image_id": "patched",
                "patch_sha256": build.PATCH_SHA,
            }
            (stage / "build-manifest.json").write_text(json.dumps(manifest))
            with self.assertRaises(RuntimeError):
                app.patched_image(stage, run, "original")
            (stage / "PASS-BUILD").write_text("fixture")
            item = {
                "Id": "patched",
                "Config": {
                    "Labels": {
                        "kap.weknora.keyword.patch": build.PATCH_SHA,
                        "kap.weknora.keyword.base": "original",
                        app.pg.LABEL: str(run),
                    }
                },
            }
            with patch.object(app.pg, "docker", side_effect=lambda *args: json.dumps([item])):
                self.assertEqual(app.patched_image(stage, run, "original"), "patched")
                with self.assertRaises(RuntimeError):
                    app.patched_image(stage, run, "different-runtime")
                manifest["patch_sha256"] = "stale-patch"
                (stage / "build-manifest.json").write_text(json.dumps(manifest))
                with self.assertRaisesRegex(RuntimeError, "different patch"):
                    app.patched_image(stage, run, "original")
                manifest["patch_sha256"] = build.PATCH_SHA
                (stage / "build-manifest.json").write_text(json.dumps(manifest))
                item["Config"]["Labels"][app.pg.LABEL] = "different-run"
                with self.assertRaises(RuntimeError):
                    app.patched_image(stage, run, "original")


if __name__ == "__main__":
    unittest.main()

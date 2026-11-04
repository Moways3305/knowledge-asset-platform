import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import json
import zipfile

import weknora_keyword_app_rehearsal as build
import weknora_app_rehearsal as app


class KeywordAppTests(unittest.TestCase):
    def test_local_zip_verifies_content_before_extracting(self):
        data = b"#!/bin/sh\necho fixture\n"
        blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        manifest = hashlib.sha256(b"run.sh\0" + b"100755\0" + blob.encode() + b"\n").hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "source.zip"
            destination = root / "source"
            destination.mkdir()

            def write_zip(commit=build.UPSTREAM, name="run.sh", content=data, mode=0o100755):
                with zipfile.ZipFile(archive, "w") as z:
                    z.comment = commit.encode()
                    item = zipfile.ZipInfo("WeKnora-" + build.UPSTREAM + "/" + name)
                    item.external_attr = mode << 16
                    z.writestr(item, content)

            with patch.object(build, "SOURCE_MANIFEST_SHA", manifest):
                for kwargs in (
                    {"commit": "main"},
                    {"name": "../outside"},
                    {"name": "/outside"},
                    {"name": ".git/config"},
                    {"mode": 0o120777},
                    {"content": b"tampered"},
                    {"mode": 0o100644},
                ):
                    with self.subTest(kwargs=kwargs):
                        write_zip(**kwargs)
                        with self.assertRaises(RuntimeError):
                            build.extract_source_zip(archive, destination)
                        self.assertEqual(list(destination.iterdir()), [])
                write_zip()
                result = build.extract_source_zip(archive, destination)
                self.assertEqual(result["files"], 1)
                self.assertEqual((destination / "run.sh").read_bytes(), data)
                with self.assertRaises(RuntimeError):
                    build.extract_source_zip(archive, destination)

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
            "# Link the anydoc parser engine\nARG WITH_ANYDOC=1\n"
            "RUN --mount=type=cache,target=/usr/local/cargo/registry \\\n"
            "    --mount=type=cache,target=/usr/local/cargo/git \\\n"
            '    if [ "$WITH_ANYDOC" = "1" ]; then \\\n'
            "        curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \\\n"
            "            | sh -s -- -y --profile minimal --default-toolchain stable && \\\n"
            "        ./scripts/build-anydoc-lib.sh; \\\n"
            "    fi\nRUN make build-prod GO_BUILD_TAGS=anydoc\n"
            "# Final stage\nFROM ignored\n"
        )
        dockerfile = build.dockerfile(upstream)
        self.assertNotIn("migrate@latest", dockerfile)
        self.assertNotIn("browser stage", dockerfile)
        self.assertIn("FROM ${KAP_RUNTIME_IMAGE}", dockerfile)
        self.assertIn("GO_BUILD_TAGS=anydoc", dockerfile)
        self.assertLess(dockerfile.index("go test "), dockerfile.index("make build-prod"))
        self.assertIn("GOMAXPROCS=2 GOFLAGS=-p=2 CARGO_BUILD_JOBS=2", dockerfile)
        self.assertNotIn("https://sh.rustup.rs", dockerfile)
        self.assertNotIn("--default-toolchain stable", dockerfile)
        self.assertIn("--default-toolchain " + build.RUST_TOOLCHAIN, dockerfile)
        self.assertIn("RUSTUP_DIST_SERVER=https://rsproxy.cn", dockerfile)
        self.assertIn("sparse+https://rsproxy.cn/index/", dockerfile)
        self.assertIn("--max-time 120", dockerfile)
        self.assertIn("1200s sh /tmp/kap-rustup-init.sh", dockerfile)
        self.assertIn("1800s ./scripts/build-anydoc-lib.sh", dockerfile)
        self.assertNotIn("--insecure", dockerfile)
        with self.assertRaisesRegex(RuntimeError, "Rust build step changed"):
            build.dockerfile(
                upstream.replace("--default-toolchain stable", "--default-toolchain other")
            )
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

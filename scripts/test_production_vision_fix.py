import json
from pathlib import Path
import tempfile
import unittest

from prepare_vision_fix import PROBE, build_command, check_candidate


class VisionPreparationTests(unittest.TestCase):
    def test_builds_only_candidate_images_without_compose_or_production_env(self):
        for component in ("backend", "frontend"):
            args = build_command(
                component, Path("/source"), "kap-vision-candidate:isolated", "PUBLIC-MANIFEST"
            )
            self.assertEqual(args[:2], ["docker", "build"])
            self.assertIn("kap-vision-candidate:isolated", args)
            self.assertNotIn("compose", args)
            self.assertNotIn("--env-file", args)
        with self.assertRaises(RuntimeError):
            build_command("postgres", Path("/source"), "forbidden", "manifest")

    def test_probe_removes_only_its_container_and_private_environment_even_on_failure(self):
        for success in (True, False):
            with self.subTest(success=success), tempfile.TemporaryDirectory() as directory:
                stage = Path(directory)
                calls = []
                image = "sha256:" + "a" * 64
                created = {}

                class Runner:
                    def docker(self, *args, **kwargs):
                        calls.append(args)
                        if args[0] == "create":
                            created["name"] = args[args.index("--name") + 1]
                            self_env = Path(args[args.index("--env-file") + 1]).read_text()
                            if "SECRET=synthetic" not in self_env:
                                raise AssertionError("missing environment")
                            return "new-helper-id"
                        if args[0] == "start":
                            if kwargs.get("data") != PROBE.encode():
                                raise AssertionError("unexpected probe")
                            return json.dumps({"passed": success})
                        if args == ("rm", "-f", "new-helper-id"):
                            return ""
                        raise AssertionError(args)

                    def inspect(self, identity):
                        if identity != "new-helper-id":
                            raise AssertionError(identity)
                        return {
                            "Name": "/" + created["name"],
                            "Image": image,
                            "Config": {"Labels": {"kap.vision-preparation": stage.name}},
                        }

                backend = {"Id": "production-backend-id", "Config": {"Env": ["SECRET=synthetic"]}}
                self.assertEqual(
                    check_candidate(Runner(), stage, image, backend)["passed"], success
                )
                self.assertFalse((stage / "probe-env-private.txt").exists())
                self.assertEqual(calls[-1], ("rm", "-f", "new-helper-id"))
                self.assertEqual(
                    calls[0][calls[0].index("--network") + 1], "container:production-backend-id"
                )
                self.assertNotIn("SECRET", json.dumps(calls))


if __name__ == "__main__":
    unittest.main()

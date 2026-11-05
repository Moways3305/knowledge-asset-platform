import unittest

import weknora_kap_upload_probe as upload
from weknora_kap_role_probe import isolated_env


class UploadProbeTests(unittest.TestCase):
    def test_preview_never_follows_external_url(self):
        for url in (
            "https://example.com/api/v1/preview/a",
            "//example.com/api/v1/preview/a",
            "http://127.0.0.1/api/v1/preview/a",
            "/unrelated",
            "file:///tmp/file",
        ):
            with self.subTest(url=url), self.assertRaises(RuntimeError):
                upload.relative_preview_url(url)
        path = "/api/v1/preview/fixture/file?ft=synthetic"
        self.assertEqual(upload.relative_preview_url(path), path)

    def test_workflow_requires_real_worker_mode_and_isolated_broker(self):
        data = {
            "database_url": "postgresql+asyncpg://wkfixture:synthetic@127.0.0.1:5432/kap_role_fixture",
            "weknora_base_url": "http://127.0.0.1:8080",
            "weknora_api_key": "sk-fixture",
            "kap_upload_flow": True,
        }
        env = isolated_env(data)
        self.assertEqual(env["CELERY_TASK_ALWAYS_EAGER"], "false")
        self.assertEqual(env["REDIS_URL"], "redis://127.0.0.1:6379/5")


class UploadPollingTests(unittest.IsolatedAsyncioTestCase):
    async def test_failed_or_degraded_processing_never_passes(self):
        class Response:
            status_code = 200

            def __init__(self, body):
                self.body = body

            def json(self):
                return self.body

        class Client:
            def __init__(self, body):
                self.body = body

            async def get(self, _path):
                return Response(self.body)

        def check(name, passed, **_):
            if not passed:
                raise RuntimeError(name)

        for body in (
            {"status": "failed", "stage": "failed"},
            {"status": "degraded", "stage": "degraded_complete"},
            {"status": "waiting", "stage": "waiting_generation_config"},
        ):
            with (
                self.subTest(body=body),
                self.assertRaisesRegex(RuntimeError, "kap_upload_worker_processed"),
            ):
                await upload.wait_for_processing(check, Client(body), "fixture")
        await upload.wait_for_processing(
            check,
            Client({"status": "action_required", "stage": "awaiting_confirmation"}),
            "fixture",
        )


if __name__ == "__main__":
    unittest.main()

import copy
from contextlib import redirect_stdout
import io
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from diagnose_saved_multimodal import collect, inspect_gate, main, metadata


def saved(kind="VLLM"):
    return {
        "id": "private-model-id",
        "name": "qwen3.6-plus",
        "type": kind,
        "source": "remote",
        "status": "active",
        "credentials": {"api_key": {"configured": True}},
        "parameters": {
            "provider": "aliyun",
            "api_key": "SECRET-KEY",
            "base_url": "https://ws-private.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
            "custom_headers": {"Authorization": "SECRET-HEADER"},
            "spec": {"private": "SECRET-SPEC"},
        },
    }


class SafeMetadataTests(unittest.TestCase):
    def test_report_only_contains_allowlisted_categories(self):
        model = saved()
        before = copy.deepcopy(model)
        report = metadata(model)
        self.assertEqual(model, before)
        self.assertEqual(report["endpoint_kind"], "openai_base")
        self.assertTrue(report["is_other_workspace_host"])
        self.assertTrue(report["custom_authorization_present"])
        self.assertEqual(report["credential_status"], "configured")
        for secret in ("SECRET", "ws-private", "private-model-id", "https://"):
            self.assertNotIn(secret, json.dumps(report))


class DeployedGateTests(unittest.IsolatedAsyncioTestCase):
    async def test_multimodal_is_rejected_without_provider_call(self):
        model = saved()
        before = copy.deepcopy(model)
        self.assertEqual(await inspect_gate(model), "weknora_saved_model_check_unsupported")
        self.assertEqual(model, before)

    async def test_chat_dispatch_is_blocked_without_provider_call(self):
        self.assertEqual(
            await inspect_gate(saved("KnowledgeQA")), "probe_branch_reached_but_not_executed"
        )

    async def test_collection_uses_only_metadata_gets_and_reports_missing_target(self):
        from app.services.weknora_client import WeKnoraClient

        calls = []

        async def fake_call(client, method, path, **kwargs):
            calls.append((method, path))
            self.assertEqual(method, "GET")
            if path == "/models":
                return [saved()]
            self.assertEqual(path, "/models/private-model-id")
            return saved()

        with (
            patch(
                "app.core.config.get_settings",
                return_value=SimpleNamespace(
                    weknora_base_url="http://synthetic.invalid", weknora_api_key="sk-SECRET-KEY"
                ),
            ),
            patch.object(WeKnoraClient, "_call", fake_call),
        ):
            result = await collect()
        self.assertEqual(len(calls), 2)
        self.assertEqual(
            result["models"][0]["records"][0]["local_test_gate"],
            "weknora_saved_model_check_unsupported",
        )
        self.assertEqual(result["models"][1]["match_count"], 0)
        self.assertFalse(result["provider_connectivity_tested"])
        self.assertNotIn("SECRET", json.dumps(result))


class SafeFailureTests(unittest.TestCase):
    def test_inside_failure_suppresses_application_output_and_exception_details(self):
        async def fail():
            print("SECRET-OUTPUT")
            raise RuntimeError("SECRET-EXCEPTION")

        out = io.StringIO()
        with (
            patch("sys.argv", ["diagnostic", "--inside"]),
            patch("diagnose_saved_multimodal.collect", fail),
            redirect_stdout(out),
        ):
            self.assertEqual(main(), 1)
        self.assertTrue(json.loads(out.getvalue())["diagnostic_read_failed"])
        self.assertNotIn("SECRET", out.getvalue())


if __name__ == "__main__":
    unittest.main()

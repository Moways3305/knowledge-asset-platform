import copy
from contextlib import asynccontextmanager, redirect_stdout
import io
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from diagnose_saved_multimodal import (
    collect,
    inspect_gate,
    main,
    metadata,
    probe_result,
    probe_saved_vision,
)


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

    def test_debug_response_and_errors_are_reduced_to_allowlisted_facts(self):
        response = {
            "success": True,
            "data": {
                "ok": False,
                "request": {"base_url": "SECRET-URL"},
                "raw_response": "SECRET-RESPONSE",
                "error": "Endpoint.AccessDenied SECRET-KEY; this model only supports streaming output",
            },
        }
        result = probe_result(200, response)
        self.assertFalse(result["vision_call_succeeded"])
        self.assertEqual(result["provider_error_codes"], ["Endpoint.AccessDenied"])
        self.assertIn("streaming_required", result["error_flags"])
        self.assertNotIn("SECRET", json.dumps(result))
        response["data"]["ok"] = True
        response["data"].pop("error")
        self.assertTrue(probe_result(200, response)["vision_call_succeeded"])
        response["data"]["raw_response"] = ""
        self.assertFalse(probe_result(200, response)["vision_call_succeeded"])


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

    async def test_native_probe_uses_saved_id_and_synthetic_image_only(self):
        import httpx
        from app.services.weknora_client import WeKnoraClient

        calls = []

        def handle(request):
            calls.append(request)
            self.assertEqual(
                str(request.url), "http://synthetic.invalid/api/v1/models/private-model-id/debug"
            )
            self.assertEqual(request.method, "POST")
            self.assertEqual(request.headers["X-API-Key"], "sk-internal-only")
            self.assertIn(b"synthetic-vision.png", request.content)
            self.assertIn(b"\x89PNG\r\n\x1a\n", request.content)
            self.assertNotIn(b"api_key", request.content)
            self.assertNotIn(b"base_url", request.content)
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "data": {
                        "ok": True,
                        "raw_response": "SECRET-OUTPUT",
                        "request": {"private": "SECRET-DETAIL"},
                    },
                },
            )

        @asynccontextmanager
        async def pool(**kwargs):
            async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
                yield http

        with patch("app.services.http_pool.pooled_http_client", pool):
            result = await probe_saved_vision(
                WeKnoraClient(base_url="http://synthetic.invalid", api_key="sk-internal-only"),
                "private-model-id",
            )
        self.assertEqual(len(calls), 1)
        self.assertTrue(result["vision_call_succeeded"])
        self.assertNotIn("SECRET", json.dumps(result))

    async def test_live_collection_refuses_unapproved_workspace_and_checks_readback(self):
        from app.services.weknora_client import WeKnoraClient

        model = saved()
        probes = []

        async def fake_call(client, method, path, **kwargs):
            self.assertEqual(method, "GET")
            return [model] if path == "/models" else copy.deepcopy(model)

        async def fake_probe(client, mid):
            probes.append(mid)
            return {"attempted": True, "vision_call_succeeded": True}

        with (
            patch(
                "app.core.config.get_settings",
                return_value=SimpleNamespace(
                    weknora_base_url="http://synthetic.invalid", weknora_api_key="sk-internal-only"
                ),
            ),
            patch.object(WeKnoraClient, "_call", fake_call),
            patch("diagnose_saved_multimodal.probe_saved_vision", fake_probe),
        ):
            result = await collect(live=True)
            self.assertEqual(probes, [])
            self.assertFalse(result["models"][0]["records"][0]["native_vision_probe"]["attempted"])
            model["parameters"]["base_url"] = "https://dashscope.aliyuncs.com/compatible-mode/v1"
            model["parameters"].pop("custom_headers")
            model["parameters"].pop("spec")
            result = await collect(live=True)
        self.assertEqual(probes, ["private-model-id"])
        self.assertTrue(result["models"][0]["records"][0]["saved_metadata_unchanged"])
        self.assertTrue(result["configuration_read_only"])
        self.assertFalse(result["read_only"])
        self.assertNotIn("SECRET", json.dumps(result))


class SafeFailureTests(unittest.TestCase):
    def test_inside_failure_suppresses_application_output_and_exception_details(self):
        async def fail(**kwargs):
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

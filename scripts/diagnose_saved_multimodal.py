"""Read saved model metadata and exercise the deployed KAP gate without provider calls."""

import asyncio
from contextlib import redirect_stderr, redirect_stdout
import io
import json
import logging
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import urlsplit

TARGETS = ("qwen3.6-plus", "qwen3.5-omni-plus")
WORKSPACE_HOST = "ws-47k0t1zmjgch8h33.cn-beijing.maas.aliyuncs.com"
EXPECTED_IMAGES = {
    "kap-backend-1": "sha256:f47a43f921655cc7bb29129c9baac23856b140d1c15230455ab2d880d80b06b2",
    "WeKnora-app": "sha256:9b614bbb9ef9c8316acf886e94932cb7126103a421d1a7e6ba150307033b6a33",
}


def metadata(saved):
    params = saved.get("parameters") or {}
    if not isinstance(params, dict):
        return {"metadata_unrecognized": True}
    url = str(params.get("base_url") or params.get("api_url") or "").strip()
    try:
        parsed = urlsplit(url)
        host, path = parsed.hostname or "", parsed.path.rstrip("/")
        secure = parsed.scheme == "https"
    except ValueError:
        host, path, secure = "", "", False
    paths = {
        "/compatible-mode/v1": "openai_base",
        "/compatible-mode/v1/chat/completions": "openai_chat_full_endpoint",
        "/api/v1": "dashscope_base",
        "/api/v1/services/aigc/multimodal-generation/generation": "dashscope_multimodal_endpoint",
    }
    credentials = saved.get("credentials") or {}
    fields = credentials.get("fields", credentials) if isinstance(credentials, dict) else {}
    key = fields.get("api_key", {}) if isinstance(fields, dict) else {}
    configured = key.get("configured") if isinstance(key, dict) else None
    headers = params.get("custom_headers") or {}
    return {
        "model_type": saved.get("type")
        if saved.get("type") in {"VLLM", "KnowledgeQA", "Embedding", "Rerank", "ASR"}
        else "other",
        "remote": saved.get("source") == "remote",
        "enabled": saved.get("status") == "active",
        "provider_is_aliyun": params.get("provider") == "aliyun",
        "endpoint_present": bool(url),
        "https": secure,
        "matches_previously_verified_workspace": host == WORKSPACE_HOST,
        "is_other_workspace_host": host.endswith(".maas.aliyuncs.com") and host != WORKSPACE_HOST,
        "is_legacy_dashscope_host": host == "dashscope.aliyuncs.com",
        "endpoint_kind": paths.get(path, "other_or_missing"),
        "credential_status": "configured"
        if configured is True
        else "missing"
        if configured is False
        else "unknown",
        "custom_authorization_present": isinstance(headers, dict)
        and any(str(k).lower() == "authorization" for k in headers),
        "spec_override_present": bool(params.get("spec")),
        "extra_config_present": bool(params.get("extra_config")),
    }


class ProbeDispatchBlocked(Exception):
    pass


async def inspect_gate(saved):
    from fastapi import HTTPException
    from app.schemas.weknora_admin import ModelCheckRequest
    from app.services import weknora_models as wm

    class LocalOnlyClient:
        async def list_models(self, **kwargs):
            return [saved]

        async def get_model(self, *args, **kwargs):
            return saved

        async def get_model_credentials(self, *args, **kwargs):
            # Metadata already fetched by GET; never call the live credentials PUT.
            return saved.get("credentials") or {}

        def __getattr__(self, name):
            async def block(*args, **kwargs):
                raise ProbeDispatchBlocked()

            return block

    try:
        result = await wm.check_model(
            LocalOnlyClient(),
            ModelCheckRequest(model_ref=wm._model_ref(str(saved["id"]))),
            trace_id=None,
        )
        code = result.error_code
        return (
            code
            if code in {"credential_missing", "credential_unconfirmed"}
            else "returned_without_probe"
        )
    except ProbeDispatchBlocked:
        return "probe_branch_reached_but_not_executed"
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        code = detail.get("denied_reason")
        return (
            code
            if code
            in {
                "weknora_saved_model_check_unsupported",
                "weknora_model_connection_config_missing",
                "weknora_model_not_found",
                "weknora_model_ref_invalid",
            }
            else "other_local_rejection"
        )
    except Exception:
        return "local_gate_inspection_failed"


async def collect():
    from app.core.config import get_settings
    from app.services.model_provider_catalog import CATALOG
    from app.services.weknora_client import WeKnoraClient

    class GetOnlyClient(WeKnoraClient):
        async def _call(self, method, path, **kwargs):
            if method != "GET":
                raise RuntimeError("non-read request blocked")
            return await super()._call(method, path, **kwargs)

    settings = get_settings()
    client = GetOnlyClient(
        base_url=settings.weknora_base_url, api_key=settings.weknora_api_key, timeout=10
    )
    report = {
        "scope": "saved_multimodal_metadata_and_local_gate",
        "read_only": True,
        "raw_logs_included": False,
        "provider_connectivity_tested": False,
        "credential_validity_verified": False,
        "registry_advertises_multimodal": any(
            p.get("id") == "aliyun" and "vllm" in p.get("capabilities", []) for p in CATALOG
        ),
        "models": [],
    }
    models = await client.list_models()
    for target in TARGETS:
        matches = [m for m in models if isinstance(m, dict) and m.get("name") == target]
        item = {"model_name": target, "match_count": len(matches), "records": []}
        for record in matches[:5]:
            try:
                saved = await client.get_model(str(record["id"]))
                facts = metadata(saved)
                facts["local_test_gate"] = await inspect_gate(saved)
                item["records"].append(facts)
            except Exception:
                item["records"].append({"metadata_read_failed": True})
        item["records_truncated"] = len(matches) > 5
        report["models"].append(item)
    return report


def main():
    report = {"read_only": True, "raw_logs_included": False}
    try:
        if "--inside" in sys.argv:
            # Never expose imported application logging or exception messages.
            logging.disable(logging.CRITICAL)
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                report = asyncio.run(asyncio.wait_for(collect(), timeout=90))
        else:
            services = []
            for name, expected in EXPECTED_IMAGES.items():
                result = subprocess.run(
                    ["docker", "inspect", name], capture_output=True, timeout=15, check=True
                )
                item = json.loads(result.stdout)[0]
                image = item.get("Image", "")
                services.append(
                    {
                        "container": name,
                        "running": item["State"].get("Running") is True,
                        "image_id": image
                        if re.fullmatch(r"sha256:[a-f0-9]{64}", image)
                        else "unrecognized",
                        "matches_successful_cutover_image": image == expected,
                    }
                )
            result = subprocess.run(
                ["docker", "exec", "-i", "kap-backend-1", "python", "-", "--inside"],
                input=Path(__file__).read_bytes(),
                capture_output=True,
                timeout=110,
                check=True,
            )
            report = json.loads(result.stdout)
            report["services"] = services
    except Exception:
        report["diagnostic_read_failed"] = True
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if report.get("diagnostic_read_failed") else 0


if __name__ == "__main__":
    raise SystemExit(main())

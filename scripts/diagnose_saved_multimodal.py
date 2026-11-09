"""Read saved model metadata and exercise the deployed KAP gate without provider calls."""

import asyncio
from contextlib import redirect_stderr, redirect_stdout
import io
import json
import logging
from pathlib import Path
import re
import struct
import subprocess
import sys
from urllib.parse import quote, urlsplit
import zlib

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


def synthetic_image():
    """A generated 64x64 red square on white; no uploaded or business image."""

    def chunk(kind, data):
        return (
            struct.pack("!I", len(data)) + kind + data + struct.pack("!I", zlib.crc32(kind + data))
        )

    rows = b"".join(
        b"\x00"
        + b"".join(
            b"\xff\x00\x00" if 16 <= x < 48 and 16 <= y < 48 else b"\xff\xff\xff" for x in range(64)
        )
        for y in range(64)
    )
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack("!2I5B", 64, 64, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


def probe_result(status, body):
    """Allowlisted facts only; upstream debug previews and answers stay private."""
    data = body.get("data") if isinstance(body, dict) else None
    success = (
        200 <= status < 300
        and isinstance(body, dict)
        and body.get("success") is True
        and isinstance(data, dict)
        and data.get("ok") is True
        and not data.get("error")
        and isinstance(data.get("raw_response"), str)
        and bool(data["raw_response"].strip())
    )
    error = data.get("error", "") if isinstance(data, dict) else ""
    if not error and isinstance(body, dict):
        error = body.get("error", "")
    raw = json.dumps(error, ensure_ascii=False)[:65536]
    codes = (
        "Endpoint.AccessDenied",
        "Workspace.AccessDenied",
        "Model.AccessDenied",
        "Arrearage",
        "InvalidApiKey",
        "invalid_api_key",
        "insufficient_quota",
        "InvalidParameter",
        "ModelNotFound",
        "model_not_found",
        "Throttling.RateQuota",
        "AllocationQuota.FreeTierOnly",
    )
    flags = {
        "streaming_required": r"only support.{0,30}stream|stream.{0,40}(?:must be true|is required)|stream.{0,10}true.{0,30}required",
        "thinking_parameter_mentioned": r"enable_thinking",
        "model_missing": r"model.{0,60}(?:does not exist|not found)",
        "credential_rejected": r"invalid.{0,10}api.?key|incorrect.{0,10}api.?key",
        "timeout": r"deadline exceeded|timed out|timeout",
        "dns_failure": r"no such host|name resolution",
        "images_unsupported": r"does not accept images|image.{0,20}not supported",
        "empty_or_incomplete_output": r"truncat|finish_reason=length",
    }
    return {
        "attempted": True,
        "weknora_http_status": status,
        "vision_call_succeeded": success,
        "provider_error_codes": [
            code for code in codes if re.search(r"(?<![\w.])" + re.escape(code) + r"(?![\w.])", raw)
        ],
        "error_flags": [label for label, pattern in flags.items() if re.search(pattern, raw, re.I)],
        "provider_output_included": False,
    }


async def probe_saved_vision(client, model_id):
    import httpx
    from app.services.http_pool import pooled_http_client

    try:
        async with pooled_http_client(timeout=60) as http:
            async with http.stream(
                "POST",
                client._base + "/models/" + quote(model_id, safe="") + "/debug",
                headers=client._headers(None),
                data={
                    "input": "Describe the main shape and its color in this image in one short sentence."
                },
                files={"file": ("synthetic-vision.png", synthetic_image(), "image/png")},
                follow_redirects=False,
            ) as response:
                payload = bytearray()
                async for part in response.aiter_bytes():
                    payload.extend(part)
                    if len(payload) > 1024 * 1024:
                        return {
                            "attempted": True,
                            "vision_call_succeeded": False,
                            "diagnostic": "response_too_large",
                        }
                try:
                    body = json.loads(payload)
                except (ValueError, UnicodeDecodeError):
                    body = {}
                return probe_result(response.status_code, body)
    except httpx.TimeoutException:
        return {"attempted": True, "vision_call_succeeded": False, "diagnostic": "timeout"}
    except Exception:
        return {
            "attempted": True,
            "vision_call_succeeded": False,
            "diagnostic": "native_probe_failed",
        }


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


async def collect(*, live=False):
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
    if live:
        report.update(
            scope="saved_vision_live_probe", read_only=False, configuration_read_only=True
        )
        report.pop("provider_connectivity_tested")
        report.pop("credential_validity_verified")
    models = await client.list_models()
    for target in TARGETS:
        matches = [m for m in models if isinstance(m, dict) and m.get("name") == target]
        item = {"model_name": target, "match_count": len(matches), "records": []}
        for record in matches[:5]:
            try:
                saved = await client.get_model(str(record["id"]))
                facts = metadata(saved)
                facts["local_test_gate"] = await inspect_gate(saved)
                if live:
                    params = saved.get("parameters") or {}
                    eligible = (
                        len(matches) == 1
                        and saved.get("name") == target
                        and facts.get("model_type") == "VLLM"
                        and facts.get("remote")
                        and facts.get("enabled")
                        and facts.get("provider_is_aliyun")
                        and facts.get("https")
                        and facts.get("endpoint_kind") == "openai_base"
                        and (
                            facts.get("is_legacy_dashscope_host")
                            or facts.get("matches_previously_verified_workspace")
                        )
                        and facts.get("credential_status") == "configured"
                        and not facts.get("custom_authorization_present")
                        and not facts.get("spec_override_present")
                        and not facts.get("extra_config_present")
                        and params.get("interface_type", "") in ("", "openai")
                    )
                    if eligible:
                        facts["native_vision_probe"] = await probe_saved_vision(
                            client, str(record["id"])
                        )
                        after = await client.get_model(str(record["id"]))
                        facts["saved_metadata_unchanged"] = after == saved
                    else:
                        facts["native_vision_probe"] = {
                            "attempted": False,
                            "diagnostic": "outside_fixed_probe_scope",
                        }
                item["records"].append(facts)
            except Exception:
                item["records"].append({"metadata_read_failed": True})
        item["records_truncated"] = len(matches) > 5
        report["models"].append(item)
    return report


def main():
    live = "--probe-saved-vision" in sys.argv
    report = {"read_only": not live, "configuration_read_only": True, "raw_logs_included": False}
    try:
        if "--inside" in sys.argv:
            # Never expose imported application logging or exception messages.
            logging.disable(logging.CRITICAL)
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                report = asyncio.run(
                    asyncio.wait_for(collect(live=live), timeout=180 if live else 90)
                )
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
            if live and not all(
                s["running"] and s["matches_successful_cutover_image"] for s in services
            ):
                raise RuntimeError("probe requires the diagnosed running images")
            result = subprocess.run(
                ["docker", "exec", "-i", "kap-backend-1", "python", "-", "--inside"]
                + (["--probe-saved-vision"] if live else []),
                input=Path(__file__).read_bytes(),
                capture_output=True,
                timeout=200 if live else 110,
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

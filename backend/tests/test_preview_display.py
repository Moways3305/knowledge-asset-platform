import base64
import json
from types import SimpleNamespace

import pytest

from app.seed.dev_seed import KA_PERSONAL, USER_CONSULTANT
from app.services import onlyoffice, preview
from app.services.storage import safe_filename


def office_settings(monkeypatch):
    settings = SimpleNamespace(
        onlyoffice_enabled=True,
        onlyoffice_document_server_url="https://office.invalid",
        onlyoffice_internal_base_url="",
        kap_public_base_url="https://platform.invalid",
        onlyoffice_jwt_secret="local-test-signing-secret",
    )
    monkeypatch.setattr(onlyoffice, "get_settings", lambda: settings)


@pytest.mark.parametrize(
    "filename,expected",
    [
        ("项目复盘与实施方案.docx", "项目复盘与实施方案.docx"),
        (r"C:\private\项目复盘.docx", "项目复盘.docx"),
        ("../../private/总结\r\n\x00\u202e.docx", "总结.docx"),
    ],
)
async def test_preview_entry_preserves_safe_unicode_display_title(
    client, monkeypatch, filename, expected
):
    office_settings(monkeypatch)

    async def original(_session, _asset_id, _version_id):
        return "local://private-test-source", filename, "application/octet-stream"

    monkeypatch.setattr(preview, "_resolve_original", original)
    headers = {"X-Dev-User-Id": str(USER_CONSULTANT)}
    issued = await client.post(f"/api/v1/knowledge/{KA_PERSONAL}/preview", headers=headers)
    assert issued.status_code == 200
    response = await client.get(issued.json()["preview_entry_url"], headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["document_title"] == expected
    assert body["onlyoffice_config"]["document"]["title"] == expected
    assert "private" not in response.text
    assert "local://" not in response.text


def test_readonly_preview_suppresses_guest_prompt_without_sharing_user_identity(monkeypatch):
    office_settings(monkeypatch)
    config = onlyoffice.build_view_config(
        document_key="safe-version-key",
        document_title="项目复盘.docx",
        file_name="项目复盘.docx",
        fetch_url="https://platform.invalid/api/v1/preview/test/file?ft=opaque",
    )
    assert config["editorConfig"]["customization"]["anonymous"] == {"request": False}
    assert "user" not in config["editorConfig"]
    assert config["editorConfig"]["mode"] == "view"
    assert config["document"]["permissions"] == {
        "edit": False,
        "download": False,
        "print": False,
        "copy": False,
        "review": False,
    }
    encoded = config["token"].split(".")[1]
    payload = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
    assert payload["editorConfig"] == config["editorConfig"]
    assert payload["document"] == config["document"]
    assert "local-test-signing-secret" not in json.dumps(config)


@pytest.mark.parametrize(
    "filename,expected",
    [
        ("项目复盘.docx", "项目复盘.docx"),
        ("日本語 résumé Обзор.xlsx", "日本語 résumé Обзор.xlsx"),
        (r"C:\folder\项目.docx", "项目.docx"),
        ("../../folder/项目.docx", "项目.docx"),
        ("报告\r\n\x00\u202e.docx", "报告.docx"),
        ("  .  ", "document"),
        (None, "document"),
        ("a" * 300, "a" * 255),
    ],
    ids=[
        "chinese",
        "multilingual",
        "windows-path",
        "posix-path",
        "controls",
        "dots",
        "empty",
        "bounded",
    ],
)
def test_display_title_is_not_a_storage_key(filename, expected):
    assert preview._display_document_title(filename) == expected
    # Storage and response-header filenames retain their existing conservative sanitizer.
    assert safe_filename("项目复盘.docx") != "项目复盘.docx"

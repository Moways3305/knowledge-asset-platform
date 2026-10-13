from types import SimpleNamespace

import pytest

from app.services import onlyoffice


@pytest.mark.parametrize(
    "internal, expected",
    [
        ("", "https://platform.invalid/api/v1/preview/x/file?ft=opaque"),
        ("http://backend:8000/", "http://backend:8000/api/v1/preview/x/file?ft=opaque"),
        ("http://[::1]:8000", "http://[::1]:8000/api/v1/preview/x/file?ft=opaque"),
    ],
)
def test_fetch_url_is_absolute_and_preserves_controlled_token(monkeypatch, internal, expected):
    monkeypatch.setattr(
        onlyoffice,
        "get_settings",
        lambda: SimpleNamespace(
            onlyoffice_internal_base_url=internal, kap_public_base_url="https://platform.invalid/"
        ),
    )
    assert onlyoffice.controlled_fetch_url("/api/v1/preview/x/file?ft=opaque") == expected


@pytest.mark.parametrize(
    "base",
    [
        "/relative",
        "file:///local",
        "https://u:p@host",
        "https://host/?secret=x",
        "https://host/#x",
        "https://host/prefix",
        "https://host/prefix/",
        "https://host:abc",
        "https://host:70000",
        "https://host:0",
        "https://host:",
        "http://[broken",
        "https://host/\n",
    ],
)
def test_invalid_fetch_base_fails_safely(monkeypatch, base):
    monkeypatch.setattr(
        onlyoffice,
        "get_settings",
        lambda: SimpleNamespace(
            onlyoffice_internal_base_url=base, kap_public_base_url="https://platform.invalid"
        ),
    )
    with pytest.raises(onlyoffice.OnlyOfficeError) as exc:
        onlyoffice.controlled_fetch_url("/api/v1/preview/x/file?ft=opaque")
    assert exc.value.code == "onlyoffice_fetch_url_invalid"
    assert base not in str(exc.value)

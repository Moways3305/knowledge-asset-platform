"""Build mirror overrides must not weaken repository authenticity or omit security updates."""

import runpy
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
configure = runpy.run_path(str(ROOT / "backend/build_tools/configure_apt.py"))["configure"]
SOURCE = """Types: deb
URIs: http://deb.debian.org/debian
Suites: trixie trixie-updates
Components: main
Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg

Types: deb
URIs: http://deb.debian.org/debian-security
Suites: trixie-security
Components: main
Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg
"""
MAIN = "https://mirror.example/debian"
SECURITY = "https://mirror.example/debian-security"


def test_default_is_byte_for_byte_unchanged():
    assert configure(SOURCE, "", "") == SOURCE
    assert configure("future base image layout", "", "") == "future base image layout"


def test_override_changes_only_repository_uris():
    expected = SOURCE.replace("http://deb.debian.org/debian-security", SECURITY).replace(
        "http://deb.debian.org/debian", MAIN
    )
    assert configure(SOURCE, MAIN + "/", SECURITY + "/") == expected
    assert configure(SOURCE.replace("http://", "https://"), MAIN, SECURITY) == expected


@pytest.mark.parametrize("main,security", [(MAIN, ""), ("", SECURITY)])
def test_partial_override_rejected(main, security):
    with pytest.raises(ValueError):
        configure(SOURCE, main, security)


@pytest.mark.parametrize(
    "value",
    [
        "http://mirror.example/debian",
        "https:///debian",
        "https://user:password@mirror.example/debian",
        "https://mirror.example:bad/debian",
        "https://mirror.example:99999/debian",
        "https://mirror.example:0/debian",
        "https://mirror.example/debian?token=secret",
        "https://mirror.example/debian#fragment",
        "https://mirror.example/debian\nTrusted: yes",
        "https://mirror.example/deb ian",
    ],
)
def test_invalid_override_rejected_for_either_repository(value):
    with pytest.raises(ValueError):
        configure(SOURCE, value, SECURITY)
    with pytest.raises(ValueError):
        configure(SOURCE, MAIN, value)


@pytest.mark.parametrize(
    "source",
    [
        "",
        SOURCE.split("\n\n")[0],
        SOURCE.replace("deb.debian.org", "unknown.example"),
        SOURCE.replace("URIs:", "# URIs:"),
    ],
)
def test_unknown_base_layout_fails_closed(source):
    with pytest.raises(ValueError):
        configure(source, MAIN, SECURITY)


def test_compose_all_backend_services_share_build_args_not_runtime_env():
    config = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    for name in ("backend", "worker", "ocr_worker", "beat", "migrate"):
        service = config["services"][name]
        assert service["build"]["context"] == "./backend"
        assert service["build"]["args"] == {
            "KAP_DEBIAN_MIRROR": "${KAP_DEBIAN_MIRROR:-}",
            "KAP_DEBIAN_SECURITY_MIRROR": "${KAP_DEBIAN_SECURITY_MIRROR:-}",
        }
        assert "KAP_DEBIAN_MIRROR" not in service.get("environment", {})


def test_dockerfile_keeps_signature_checks_and_bounded_retries():
    dockerfile = (ROOT / "backend/Dockerfile").read_text(encoding="utf-8")
    assert "python /tmp/configure_apt.py" in dockerfile
    assert "Acquire::Retries=2" in dockerfile
    assert "Acquire::https::Timeout=30" in dockerfile
    for bypass in ("--allow-unauthenticated", "trusted=yes", "Verify-Peer=false"):
        assert bypass not in dockerfile

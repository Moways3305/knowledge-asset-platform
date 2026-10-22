"""Optional build-only Debian mirror override; retain suites and signature settings."""

import os
import re
from pathlib import Path
from urllib.parse import urlsplit


def validate_mirror(value: str) -> str:
    parsed = urlsplit(value)
    try:
        port = parsed.port
    except ValueError:
        raise ValueError("Invalid mirror port") from None
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or port == 0
        or any(char.isspace() or ord(char) < 32 for char in value)
    ):
        raise ValueError("Mirror must be an HTTPS repository URL without credentials")
    return value.rstrip("/")


def configure(content: str, mirror: str, security: str) -> str:
    if not mirror and not security:
        return content
    if not mirror or not security:
        raise ValueError("Set both Debian and Debian security mirror URLs")
    mirror, security = validate_mirror(mirror), validate_mirror(security)
    counts = {"main": 0, "security": 0}

    def replace_uri(match: re.Match[str]) -> str:
        tokens = match.group(2).split()
        updated = []
        for token in tokens:
            uri = urlsplit(token)
            if uri.hostname == "deb.debian.org" and uri.path.rstrip("/") == "/debian":
                updated.append(mirror)
                counts["main"] += 1
            elif (
                uri.hostname in {"deb.debian.org", "security.debian.org"}
                and uri.path.rstrip("/") == "/debian-security"
            ):
                updated.append(security)
                counts["security"] += 1
            else:
                raise ValueError("Unexpected base-image repository; review before overriding")
        return match.group(1) + " ".join(updated)

    result = re.sub(r"(?m)^(URIs:[ \t]*)([^\r\n]+)", replace_uri, content)
    if not all(counts.values()):
        raise ValueError("Expected Debian and security deb822 repositories were not found")
    return result


if __name__ == "__main__":
    mirror = os.environ.get("KAP_DEBIAN_MIRROR", "")
    security = os.environ.get("KAP_DEBIAN_SECURITY_MIRROR", "")
    if mirror or security:
        path = Path("/etc/apt/sources.list.d/debian.sources")
        original = path.read_text(encoding="utf-8")
        updated = configure(original, mirror, security)
        path.write_text(updated, encoding="utf-8")

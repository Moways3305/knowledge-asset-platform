"""Immutable, non-secret release metadata baked into a deployment image."""

import hashlib
import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.release_note import ReleaseDraft

MANIFEST_PATH = Path(__file__).resolve().parents[2] / "release-manifest.json"


class ReleaseManifest(ReleaseDraft):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    previous_commit: str = Field(pattern=r"^[0-9a-f]{40}$")

    @property
    def digest(self) -> str:
        data = json.dumps(self.model_dump(), sort_keys=True, ensure_ascii=False).encode()
        return hashlib.sha256(data).hexdigest()


class ReleaseIdentity(BaseModel):
    version: str
    commit: str


def load_manifest() -> ReleaseManifest | None:
    if not MANIFEST_PATH.exists():
        return None  # Legacy/local builds remain usable, but cannot certify a deployment.
    return ReleaseManifest.model_validate_json(MANIFEST_PATH.read_text(encoding="utf-8"))

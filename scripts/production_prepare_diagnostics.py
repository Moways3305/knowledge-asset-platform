"""Read a preparation record; emit fixed diagnostic labels, never private log lines."""

import argparse
import json
from pathlib import Path

SIGNALS = {
    "compose_env_file_missing": ("env file", ".env"),
    "file_not_found": ("no such file or directory", "does not exist", "not found"),
    "required_variable_missing": (
        "required variable",
        "missing a value",
        "is required",
        "must be set",
    ),
    "unset_variable": ("variable is not set", "defaulting to a blank string"),
    "invalid_interpolation": ("invalid interpolation", "invalid template", "interpolation format"),
    "undefined_service": ("undefined service", "no such service"),
    "undefined_network": ("undefined network",),
    "undefined_volume": ("undefined volume",),
    "invalid_compose": (
        "invalid compose",
        "validating ",
        "additional property",
        "must be a mapping",
        "must be a string",
    ),
    "permission_denied": ("permission denied", "operation not permitted"),
    "disk_full": ("no space left on device",),
    "docker_unavailable": ("cannot connect to the docker daemon", "error during connect"),
    "unsupported_option": ("unknown flag", "unknown shorthand flag", "unrecognized option"),
    "database_authentication": (
        "password authentication failed",
        "peer authentication failed",
        "no password supplied",
    ),
    "database_role_missing": ("role ", "does not exist"),
    "database_connection": (
        "could not connect to server",
        "connection refused",
        "database system is starting up",
    ),
    "image_missing": ("no such image",),
    "invalid_image_reference": ("invalid reference format",),
}
DIRECTORIES = {"/data/kap/repo", "/data/weknora/repo", "/data/weknora/releases/v0.7.1"}


def classify(raw):
    value = raw.lower()
    # All returned text is defined in source; never serialize a regex match or log excerpt.
    matches = [name for name, needles in SIGNALS.items() if any(n in value for n in needles)]
    for name in ("compose_env_file_missing", "database_role_missing"):
        if name in matches and not all(n in value for n in SIGNALS[name]):
            matches.remove(name)
    return matches


def diagnose(stage):
    log = stage / "private.log"
    raw = ""
    truncated = False
    if log.is_file():
        with log.open("rb") as stream:
            size = log.stat().st_size
            truncated = size > 1024 * 1024
            stream.seek(max(0, size - 1024 * 1024))
            raw = stream.read().decode("utf-8", errors="replace")
    files = (
        "runtime-private.json",
        "config-backups-private.json",
        "compose-sources-private.json",
        "rollback-images.json",
        "database-backups-private.json",
        "weknora-candidate.json",
        "release-manifest.json",
        "candidate-image-ids.json",
        "PREPARED",
    )
    report = {
        "read_only": True,
        "raw_logs_included": False,
        "tail_truncated": truncated,
        "signals": classify(raw),
        "artifacts_present": {name: (stage / name).is_file() for name in files},
        "database_archives": len(list(stage.glob("*-database-*.dump"))),
        "compose_sources": [],
    }
    runtime = stage / "runtime-private.json"
    if runtime.is_file():
        seen = set()
        for item in json.loads(runtime.read_text()).values():
            labels = item.get("Config", {}).get("Labels") or {}
            key = tuple(
                labels.get("com.docker.compose." + field)
                for field in ("project", "project.working_dir", "project.config_files")
            )
            if key in seen:
                continue
            seen.add(key)
            index = len(report["compose_sources"])
            report["compose_sources"].append(
                {
                    "index": index,
                    "project": key[0] if key[0] in {"kap", "weknora"} else "unrecognized",
                    "directory": key[1] if key[1] in DIRECTORIES else "unrecognized",
                    "rendered": (stage / f"compose-private-{index}.json").is_file(),
                }
            )
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", required=True, type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(diagnose(args.stage), ensure_ascii=False, indent=2))
    except (OSError, ValueError, TypeError, AttributeError):
        print(
            json.dumps(
                {"read_only": True, "diagnostic_read_failed": True, "raw_logs_included": False}
            )
        )
        raise SystemExit(1) from None

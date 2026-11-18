"""Independent local inspection; checkpoints and evidence contain no matched values."""

from app.core.personal_information import personal_information_matches
from app.services.maintenance_rules import finding

PRIVACY_RULE_VERSION = 1


def advance_privacy(snapshot, work, findings):
    if "privacy" not in snapshot["coverage"]:
        return  # Compatibility with historical/unit snapshots.
    if work.get("privacy_done"):
        snapshot["coverage"]["privacy"] = work["privacy_result"]
        return
    state = work.setdefault("privacy_scan", {"counts": {}, "locations": [], "total": 0})

    def inspect(text, source, offset=0, owned=None):
        # A previous window may already have counted an entity crossing this boundary.
        # Its suffix can also look like an email/account; keep only the original span.
        covered_until = work.get("privacy_" + source + "_covered_until", 0) if owned else 0
        for hit in personal_information_matches(text):
            if owned is not None and hit.start >= owned:
                continue
            if offset + hit.start < covered_until:
                continue
            if owned is not None:
                work["privacy_" + source + "_covered_until"] = offset + hit.end
            state["counts"][hit.category] = state["counts"].get(hit.category, 0) + 1
            state["total"] += 1
            if len(state["locations"]) < 20:
                location = {
                    "source": source,
                    "category": hit.category,
                    "start": offset + hit.start,
                    "end": offset + hit.end,
                }
                if source == "summary":
                    for summary_range in snapshot["privacy_window"]["summary_ranges"]:
                        if summary_range["start"] <= location["start"] < summary_range["end"]:
                            location["summary_type"] = summary_range["type"]
                            location["start"] -= summary_range["start"]
                            location["end"] = (
                                min(location["end"], summary_range["end"]) - summary_range["start"]
                            )
                            break
                state["locations"].append(location)

    try:
        if not work.get("privacy_metadata_checked"):
            inspect(snapshot["facts"]["title"], "title")
            for tag in snapshot["facts"]["tags"]:
                inspect(tag, "tag")
            work["privacy_metadata_checked"] = True
        window = snapshot.get("privacy_window")
        result = snapshot["coverage"]["privacy"]
        if window:
            for source in ("body", "summary"):
                inspect(window[source], source, window[source + "_offset"], window["size"])
                work["privacy_" + source + "_offset"] = window[source + "_next"]
            done = window["body_last"] and window["summary_last"]
        else:
            done = True
        if done:
            work["privacy_done"], work["privacy_result"] = True, result
        snapshot["coverage"]["privacy"] = result if done else "in_progress"
        if state["total"]:
            findings.append(
                finding(
                    "personal_information",
                    evidence={
                        "basis": "local_personal_information_check",
                        **state,
                        "locations_truncated": state["total"] > len(state["locations"]),
                    },
                )
            )
    except Exception:
        work["privacy_done"], work["privacy_result"] = True, "privacy_check_failed"
        snapshot["coverage"]["privacy"] = "privacy_check_failed"

"""Advance one durable, fenced unit of document/library inspection."""

from copy import deepcopy

from app.services.maintenance_rules import finding

RETRYABLE = {
    "model_timeout",
    "model_rate_limited",
    "model_connection_error",
    "model_server_error",
    "model_response_incomplete",
    "model_evidence_invalid",
    "model_unavailable",
}


def advance(snapshot, settings, previous, findings, reason):
    work = deepcopy(previous or {})
    work["fingerprint"] = snapshot["fingerprint"]
    progress = work.setdefault("progress", {})
    if not work.get("comparison_done"):
        progress["comparison_checked"] = progress.get("comparison_checked", 0) + len(
            snapshot["candidates"]
        )
        if snapshot["candidates"]:
            work["candidate_cursor"] = snapshot["candidates"][-1]["id"]
        work["comparison_done"] = snapshot["comparison_done"]
    progress["comparison_total"] = snapshot["candidate_count"]
    delayed = False
    window = snapshot.get("window")
    if not work.get("quality_done"):
        quality = snapshot["coverage"]["quality"]
        if quality != "complete":
            work["quality_done"], work["quality_result"] = True, quality
        elif reason:
            progress["retry_attempt"] = progress.get("retry_attempt", 0) + 1
            if reason in RETRYABLE and progress["retry_attempt"] < 3:
                delayed = True
            else:
                work["quality_done"], work["quality_result"] = True, reason
        elif window:
            progress["retry_attempt"] = 0
            progress["segments_checked"] = progress.get("segments_checked", 0) + 1
            work["segmented"] = work.get("segmented", False) or window["partial"]
            analysis = snapshot.get("analysis", {})
            work["substantive"] = work.get("substantive", False) or analysis.get(
                "substantive", False
            )
            work["sections"] = sorted(
                set(work.get("sections", [])) | set(analysis.get("sections", []))
            )
            if window["summary_last"]:
                work["summary_offset"] = 0
                work["body_offset"] = window["next_body"]
                progress["body_checked"] = window["body_end"]
                if window["body_last"]:
                    work["quality_done"], work["quality_result"] = True, "complete"
                    if work["segmented"]:
                        if not work["substantive"]:
                            findings.append(
                                finding("cover_only", evidence={"basis": "all_segments_reviewed"})
                            )
                        missing = sorted(set(settings.required_sections) - set(work["sections"]))
                        if missing:
                            findings.append(
                                finding(
                                    "missing_content",
                                    evidence={
                                        "basis": "all_segments_reviewed",
                                        "missing_sections": missing,
                                    },
                                )
                            )
            else:
                work["summary_offset"] = window["next_summary"]
        else:
            work["quality_done"], work["quality_result"] = True, quality
    if window:
        progress["body_total"] = window["body_total"]
    seen = {tuple(key) for key in work.get("seen", [])}
    seen.update((f["rule"], f["related_key"]) for f in findings)
    work["seen"] = [list(key) for key in sorted(seen)]
    snapshot["coverage"]["duplicates"] = "complete" if work["comparison_done"] else "in_progress"
    snapshot["coverage"]["quality"] = work.get("quality_result", "in_progress")
    complete = bool(work.get("quality_done") and work.get("comparison_done"))
    return work, complete, delayed

# Upload processing window

Upload confirmation is a modal. After confirmation, transport remains bounded by
the existing byte/file limits. The file-task table combines transport and ingest
projections by task ID; identical filenames do not imply identical tasks.

## Processing admission

- `INGEST_PROCESSING_WINDOW` defaults to `5` (range 1–32).
- `INGEST_HEAVY_PROCESSING_WINDOW` defaults to `1` (range 1–8).
- A session admits waiting files in ordinal order as earlier processing finishes,
  fails, or is cancelled. Waiting for human confirmation does not occupy a slot.
- PostgreSQL transaction advisory locks bound simultaneous execution across worker
  processes. Heavy extraction has a separate smaller pool; Markdown/text and the
  subsequent content-generation stage do not consume a heavy slot.
- Actual concurrency is also bounded by worker concurrency. The window does not
  raise worker concurrency or container/parser memory limits.
- Completion order is not guaranteed. Separate OCR/default queues and retries can
  change execution order; ordinal order describes admission within one session.
- Worker completion refills the session. Beat also refills waiting sessions, so an
  open browser is not required. Refill errors do not replay completed extraction.

## Deployment and checks

Use identical window configuration and code on all backend, worker, OCR-worker and
beat instances. Rebuild/recreate these services together using the production
Compose overrides. Existing memory safeguards remain necessary: even one malformed
or highly compressed file can exceed a parser's memory budget.

Local SQLite tests do not exercise PostgreSQL advisory locks. Before production
acceptance, run multiple PostgreSQL-backed workers, upload multiple sessions, and
check simultaneous heavy parsing never exceeds the configured limit. Also check
worker termination releases slots, queued work resumes without a browser, and
cancellation prevents new work/asset persistence. Do not treat mocked lock tests
or frontend screenshots as proof of production memory stability.

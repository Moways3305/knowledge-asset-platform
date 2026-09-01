# P1 processing timeout recovery acceptance

Date: 2026-09-01

## Implemented contract

- Candidate selection is restricted to `path_b_upload + failed + processing_timeout + no result_asset_id`.
- Source preflight uses the physical storage object and requires an existing regular file with size greater than zero.
- Dry-run is the default and returns aggregate-only results. Actual execution requires explicit confirmation and the observed OOM-kill baseline.
- Each batch claims no more than three tasks and enforces a minimum 15-second interval.
- Actual recovery is serialized before candidate selection: production workers share a token-owned Redis lease, while eager/test execution uses an equivalent process lock. A concurrent request stops with `batch_in_progress`, and the next request rechecks the 15-second interval inside the lease.
- Redis, OCR worker, queue budget and cgroup OOM-kill checks stop execution before any claim when unsafe.
- Claims are atomic and reuse the existing ingest enqueue/router. Dry-run, rejection, confirmation, enqueue success and enqueue failure have structured audit events.
- Missing, invalid and zero-byte sources converge to the safe `source_file_unavailable` state on execution; all read surfaces project “重新上传” without exposing storage details.
- Status, upload session, notification and workbench entry copy is unified for recoverable timeouts.

## Automated verification

- Backend recovery/status/upload-session/OCR/Celery/notification/workbench/audit regression suite: passed.
- A two-session concurrency regression holds the first batch mid-enqueue and verifies the second request claims zero tasks; total persisted claims remain three.
- Frontend full suite: 76 files, 564 tests passed.
- ESLint with zero warnings: passed.
- TypeScript and Vite production build: passed.
- Upload retry browser QA: passed at 1440, 1024, 768 and 390 widths.
- Admin operations browser QA: all scenarios passed at 1440, 1024 and 390 widths; the recovery scenario reported zero overflow, zero clipping and no console leak.

## Visual evidence

- `timeout-recovery-open-1440.png`: aggregate dry-run result and explicit second confirmation on desktop.
- `timeout-recovery-open-390.png`: the same controls on a 390px mobile viewport.
- `admin-operations-report.json`: machine-readable browser QA results.

## Environment boundary

This change does not claim that the 35 production records were executed from this development workspace. Production recovery remains an explicit operator action: run dry-run in the deployed environment, confirm the aggregate count and OOM baseline, then recover in bounded batches.

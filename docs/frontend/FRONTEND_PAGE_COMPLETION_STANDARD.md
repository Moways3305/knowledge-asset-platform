# Frontend Page Completion Standard

A page redesign is a replacement migration, not a parallel mockup. It is complete only when every
item below is satisfied in the same change.

## Required completion criteria

1. **Single route owner**: the existing `src/App.tsx` route resolves to one formal page component.
   The route address, capability guard, and navigation semantics remain aligned.
2. **Real API closed loop**: every data read and mutation uses an existing `src/api/*` client and
   unified HTTP/CSRF/error handling. Static data, delayed fake success, and frontend-only success
   messages cannot substitute for a backend operation.
3. **Complete states**: loading, empty, error, denied/read-only, submitting, and success states are
   implemented where the workflow can reach them. Retry must repeat the real operation safely.
4. **Key action tests**: tests cover the page's highest-risk read and mutation paths, including
   request payload boundaries and sanitized errors. Route/guard ownership is covered by the
   takeover gate.
5. **Old implementation removal**: after takeover, remove the replaced page, modal, hook, API
   wrapper, type, and exclusive styles only after repository-wide route/import/test/build evidence
   proves they are unused. Uncertain candidates stay registered in the matrix.
6. **Desktop browser smoke**: exercise the actual route and expected network requests against an
   available non-production environment. Unexpected 4xx/5xx responses are failures, not UI polish
   issues. If the environment is unavailable, report the missing topology explicitly.
7. **Security continuity**: backend authorization remains authoritative. Do not expose tokens,
   credentials, original content, storage references, internal service identifiers, private URLs,
   or full request/response bodies in UI, tests, screenshots, logs, or reports.
8. **Quality gates**: `npm test -- --run`, `npm run lint`, `npm run format:check`, and
   `npm run build` pass. The route takeover gate must also pass without weakening its assertions.

## Explicit exception process

An exception must be narrow, documented in `FRONTEND_ROUTE_TAKEOVER_MATRIX.md`, and enforced by a
stable structural rule where possible. It must state the owner, purpose, evidence, and follow-up.
File names, comments, or visual similarity alone are not sufficient evidence for deletion.

Static product/help pages may have no API owner. Ambient declaration files may have no runtime
import. Legitimate timers, such as a bounded external-editor readiness timeout, must be registered
by owner; fake asynchronous success is never an exception.

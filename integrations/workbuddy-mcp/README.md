# WorkBuddy MCP Server

Provider-neutral MCP bridge to the KAP knowledge platform. WorkBuddy calls these
tools; the MCP server forwards each call to KAP's `/api/v1/agent-gateway/*` over HTTP.
It holds no authority and never touches the database.

This package is the compatibility bridge/local Connector. The primary hosted entry is KAP’s
`/mcp`, with optional OAuth and explicitly authorized operations; see
[remote deployment](../../docs/deployment/WORKBUDDY_REMOTE_MCP.md),
[OAuth](../../docs/api/mcp-oauth.md), and [operations](../../docs/mcp-operations.md).
The bridge’s read-only tool surface is not the full hosted MCP surface.

## Identity model (read this first)

Each employee gets their **own** per-user `KAP_AGENT_TOKEN`. The token is bound to one
KAP user in the backend registry; KAP resolves the caller **only** from that binding.
The MCP server never sends a user id. Anyone's token = that one user's permissions.

## Config

For the default local stdio transport, two variables are required (see `.env.example`):

- `KAP_BASE_URL` — KAP backend base URL
- `KAP_AGENT_TOKEN` — the per-user WorkBuddy token

Missing either in stdio mode → the server refuses to start (fail closed). Remote bridge mode
requires the base URL and authenticates each request with its own Bearer, as described below. There is intentionally
**no** caller / user-id config: identity comes from the token binding on the backend.

## Employee installation

Business users open “MCP 接入” (`/my/workbuddy`) from the workbench or account navigation.
Hosted MCP is the primary connection; the versioned local KAP WorkBuddy Connector remains available
for managed-device compatibility. Windows x64, macOS Apple Silicon and macOS Intel packages bundle the Python
runtime and this package; employees do not install Python or pip.

The card generates platform-specific `mcp.json` only after the user explicitly requests it.
The config launches:

- Windows: `C:\Program Files\KAP WorkBuddy Connector\kap-workbuddy-connector.exe`
- macOS: `/Applications/KAP WorkBuddy Connector.app/Contents/MacOS/kap-workbuddy-connector`

The shared installer never contains a token. `KAP_BASE_URL` and the one user's
`KAP_AGENT_TOKEN` exist only in that user's imported MCP configuration.

### Upgrading an existing Python configuration

Existing `python -m workbuddy_mcp.server` configurations keep working. Opening the guide,
selecting a platform or downloading an installer does not rotate or revoke the old token.
Install the connector first, then explicitly generate a new platform configuration. That
generation rotates the token, so import the new config immediately and remove the old Python
entry after the first successful KAP tool call.

## Generating a per-user token (administrative fallback)

An admin registers a WorkBuddy token bound to an active business user via the existing
whitelist API:

```bash
curl -sX POST "$KAP_BASE_URL/api/v1/admin/permissions/agent-whitelist" \
  -H "Content-Type: application/json" -H "<admin auth>" \
  -d '{"provider":"workbuddy","agent_identifier":"wb-<unique>","agent_name":"<employee>",
       "capability":"qa","bound_user_id":"<KAP user uuid>",
       "max_confidentiality_level":"L2","max_ai_access_level":"A2"}'
```

The plaintext `token` is returned **once** — copy it into that employee's WorkBuddy MCP
config. The admin list view shows `bound_user_name` / `bound_user_active` (never the token).
Binding rejects pure-admin / inactive / non-business users.

## Tools

All tools in this compatibility package are **read-only**. There are no write tools (no upload / approve / reject / grant /
revoke / config). Every tool maps 1:1 to a `/api/v1/agent-gateway/*` endpoint, carries the
**per-request bearer**, and the `KapClient` projects each response to an explicit field allowlist —
the backend may return more, but the MCP only surfaces the whitelisted fields.

Knowledge / Q&A:

- `kap_list_knowledge_directories()` returns authorized stable directory keys and display paths, never asset counts.
- `kap_search_knowledge(query, scope?, top_k?, tags?, phase?, directory_key?, project_id?)` returns safe summary cards. If the user explicitly names a directory (such as methodology or deliverables), resolve its exact key with the directory tool first. For a general topic, search broadly; never guess a key or silently add a hard directory filter.
- `kap_answer_from_knowledge(query, scope?)` → `{answer, citations}`
- `kap_list_accessible_projects()` → `[{project_id, name, status, access_mode, access_label}]`.
  `summary_visible / 摘要可见` means the non-member project has reusable safe summaries; it must
  not be described as having no project permission, and it does not grant project workspace or
  original-file access.

Workbench (PBC-37):

- `kap_list_my_todos(limit?)` → `{items, counts}` — pending reviews assigned to me, my original-access
  requests, requests awaiting my approval, ingest tasks awaiting my confirmation.
- `kap_list_recent_knowledge(scope?, project_id?, limit?)` → recent knowledge cards I can see.
- `kap_get_knowledge_summary(asset_id)` → one asset's safe/redacted summary (discovery/summary layer).
- `kap_list_project_knowledge(project_id, limit?, phase?, tags?)` → knowledge I can see in a project.
- `kap_get_project_brief(project_id)` → member metrics, or the minimal
  `{project_id, name, status, access_mode, access_label, message}` view for a summary-visible project.
- `kap_list_pending_reviews(limit?)` → review items I can act on / see.
- `kap_list_original_access_requests(box="mine"|"inbox", limit?)` → original-access requests.

The bridge also exposes `kap_list_my_personal_knowledge`,
`kap_list_accessible_knowledge`, `kap_get_knowledge_detail`, `kap_get_knowledge_content`, and
`kap_list_tags`. The registered tool definitions in `src/workbuddy_mcp/server.py` are authoritative.

All permission, desensitization, and audit happen server-side. **No original-file download, no
preview URL, no write tools in this compatibility package.** `kap_get_knowledge_content` returns
paginated current-version text only after a fresh original-access permission check;
`can_view_original=true` in a prior summary never substitutes for that check. Backend errors surface as a single safe message
(no internal ids / denied_reason / trace / token / URL). Dify stays as a separate legacy adapter
and is unaffected.

## Developer run (local stdio)

```bash
pip install -e .
KAP_BASE_URL=... KAP_AGENT_TOKEN=... workbuddy-mcp
```

## Run the compatibility bridge (remote streamable-http)

This starts a separate development bridge; it does not configure the production KAP `/mcp` endpoint.

```powershell
$env:KAP_BASE_URL="https://kap.example.com"
$env:WORKBUDDY_MCP_TRANSPORT="streamable-http"
$env:WORKBUDDY_MCP_HOST="127.0.0.1"
$env:WORKBUDDY_MCP_PORT="8000"
python -m workbuddy_mcp.server
```

WorkBuddy then points at `"url": "http://127.0.0.1:8000/mcp"`.

### Identity in remote mode (important)

The server reads the **per-request `Authorization: Bearer <token>`** header inside each tool
call (`ctx.request_context.request.headers`) and forwards *that* token to KAP. So each WorkBuddy
user carries their own bound token and gets their own permissions — verified end-to-end by
`tests/test_remote_smoke.py` (a real uvicorn + MCP client run asserts the per-request bearer,
not the process token, reaches KAP).

- In remote mode `KAP_AGENT_TOKEN` is **optional** and only used as a fallback for personal local
  testing. **A shared remote server must NOT rely on the process-level token** — that would map
  every user to one identity. Company-shared remote MCP must pass each user's own Bearer (which
  WorkBuddy must be configured to send).
- If your WorkBuddy deployment cannot send a per-user `Authorization` header, do **not** run a
  shared remote server; use stdio + per-user token instead.

## Test

```bash
pip install -e . && python -m pytest tests/ -q
```

## Release builds

Use `.github/workflows/workbuddy-connector-release.yml`. `internal` can produce unsigned
test candidates. `production` fails unless Windows Authenticode signing succeeds and both
macOS packages receive Developer ID signatures, successful Apple notarization and stapled
tickets. The final manifest contains only platform, architecture, filename, version, signing
booleans and SHA-256 values.

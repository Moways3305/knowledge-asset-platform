# WorkBuddy MCP Server

Provider-neutral MCP bridge to the KAP knowledge platform. WorkBuddy calls these
tools; the MCP server forwards each call to KAP's `/api/v1/agent-gateway/*` over HTTP.
It holds no authority and never touches the database.

## Identity model (read this first)

Each employee gets their **own** per-user `KAP_AGENT_TOKEN`. The token is bound to one
KAP user in the backend registry; KAP resolves the caller **only** from that binding.
The MCP server never sends a user id. Anyone's token = that one user's permissions.

## Config

Exactly two env vars (see `.env.example`):

- `KAP_BASE_URL` — KAP backend base URL
- `KAP_AGENT_TOKEN` — the per-user WorkBuddy token

Missing either → the server refuses to start (fail closed). There is intentionally
**no** caller / user-id config: identity comes from the token binding on the backend.

## Employee installation

Business users install the versioned KAP WorkBuddy Connector from the guided card on KAP's
home dashboard. Windows x64, macOS Apple Silicon and macOS Intel packages bundle the Python
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

All tools are **read-only**. There are no write tools (no upload / approve / reject / grant /
revoke / config). Every tool maps 1:1 to a `/api/v1/agent-gateway/*` endpoint, carries the
**per-request bearer**, and the `KapClient` projects each response to an explicit field allowlist —
the backend may return more, but the MCP only surfaces the whitelisted fields.

Knowledge / Q&A:

- `kap_list_knowledge_directories()` returns authorized stable directory keys and display paths, never asset counts.
- `kap_search_knowledge(query, scope?, top_k?, tags?, phase?, directory_key?, project_id?)` returns safe summary cards. If the user explicitly names a directory (such as methodology or deliverables), resolve its exact key with the directory tool first. For a general topic, search broadly; never guess a key or silently add a hard directory filter.
- `kap_answer_from_knowledge(query, scope?)` → `{answer, citations}`
- `kap_list_accessible_projects()` → `[{project_id, name, status}]`

Workbench (PBC-37):

- `kap_list_my_todos(limit?)` → `{items, counts}` — pending reviews assigned to me, my original-access
  requests, requests awaiting my approval, ingest tasks awaiting my confirmation.
- `kap_list_recent_knowledge(scope?, project_id?, limit?)` → recent knowledge cards I can see.
- `kap_get_knowledge_summary(asset_id)` → one asset's safe/redacted summary (discovery/summary layer).
- `kap_list_project_knowledge(project_id, limit?, phase?, tags?)` → knowledge I can see in a project.
- `kap_get_project_brief(project_id)` → `{my_role, knowledge_count, recent_asset_count, …}`.
- `kap_list_pending_reviews(limit?)` → review items I can act on / see.
- `kap_list_original_access_requests(box="mine"|"inbox", limit?)` → original-access requests.

10 tools total. All permission, desensitization, and audit happen server-side. **No original-file
download, no preview URL, no write tools.** Even when a summary reports `can_view_original=true`,
the original content is never returned over MCP. Backend errors surface as a single safe message
(no internal ids / denied_reason / trace / token / URL). Dify stays as a separate legacy adapter
and is unaffected.

## Developer run (local stdio)

```bash
pip install -e .
KAP_BASE_URL=... KAP_AGENT_TOKEN=... workbuddy-mcp
```

## Run (remote streamable-http)

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

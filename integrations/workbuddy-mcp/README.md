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

## Generating a per-user token (admin)

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

- `kap_search_knowledge(query, scope?, top_k?, tags?, phase?)` → safe summary cards
- `kap_answer_from_knowledge(query, scope?)` → `{answer, citations}`
- `kap_list_accessible_projects()` → `[{project_id, name, status}]`

All permission, desensitization, and audit happen server-side. No original-file download,
no write tools. Backend errors surface as a single safe message (no internal ids / token / URL).

## Run (local stdio — default, per-user token)

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

# MCP protocol bridge

Requires Python 3.11+ and the official `mcp==2.3.0` SDK, not FastMCP. Install `requirements-mcp.txt` in an isolated environment. The implementation uses the official SDK's low-level `Server` callback API so schemas and validation reject coercion and unknown arguments.

## Run

From the repository root:

```sh
python -m mcp_bridge.server --transport stdio
python -m mcp_bridge.server --transport http --host 127.0.0.1 --port 8766
python -m unittest discover -s tests -p test_mcp_bridge.py -v
```

ASGI factory: `mcp_bridge.server:create_app` (factory mode). CLI defaults to stdio; HTTP binds only loopback. Endpoint is exactly `/mcp`, stateless Streamable HTTP with JSON responses. Access logs are disabled. Stdout in stdio mode contains protocol frames only.

## Configuration

- `SHORTS_API_TOKEN_FILE` or `SHORTS_API_TOKEN`: outbound REST credential, required in both modes.
- `SHORTS_MCP_TOKEN_FILE` or `SHORTS_MCP_TOKEN`: independent incoming bearer credential, required for HTTP. File takes precedence. Credentials must be 32–4096 printable bearer-safe characters with at least eight distinct characters; use a cryptographically generated random token, not a memorable password. The two credentials must differ.
- `SHORTS_API_BASE_URL`: defaults to `http://127.0.0.1:8765`. HTTPS or loopback HTTP only; no userinfo, query, fragment, redirects, or environment proxies.
- `SHORTS_MCP_PUBLIC_URL`: public endpoint, including optional `/mcp`. Adds its exact authority to Host validation and its origin to Origin validation. No private deployment hostname is baked into source.
- `SHORTS_MCP_ALLOWED_HOSTS`: optional comma-separated exact authorities, including ports where applicable. No wildcards.
- `SHORTS_MCP_ALLOWED_ORIGINS`: optional comma-separated exact HTTP(S) origins. No wildcards, `null`, paths or broad CORS.

A reverse proxy must preserve the public Host and the client's Authorization and Origin. The outer web application's Origin allowlist also applies; adding an origin only to the MCP service does not override that outer policy. Native clients that omit Origin are accepted subject to bearer authentication. Do not substitute the REST credential, trust forwarded-host headers, or forward cookies. All HTTP requests—including initialization, discovery, prompts and resources—pass the same bearer guard. Duplicate Authorization/Origin/Host headers are rejected. There is no unauthenticated HTTP health endpoint; a 401 on `/mcp` confirms reachability.

This is **pre-shared bearer authentication**, not OAuth. It works with clients supporting a custom Authorization header; it is not a claim of universal cloud-connector compatibility. The bridge itself does not provide TLS: deploy behind the parent's authenticated-header-preserving HTTPS route.

## Capabilities

Exact tools:

- `shorts_list_accounts(platform?, q?, limit=25, offset=0)`
- `shorts_list_videos(account_id?, q?, status?, limit=25, offset=0)`
- `shorts_get_video(video_id)`
- `shorts_list_references(q?, content_type?, limit=25, offset=0)`
- `shorts_get_reference(reference_id)`
- `shorts_get_templates()`
- `shorts_get_template_prompts(template_id)`
- `shorts_create_draft(title, account_id, script='', language='es', format='9:16', notes='')`
- `shorts_update_draft(video_id, changes)`
- `shorts_attach_assets(video_id, preview_url?, thumbnail_url?, youtube_url?)`
- `shorts_submit_for_review(video_id)`
- `shorts_get_metrics(video_id)`
- `shorts_get_workflow()`

`shorts://workflow` resource and `shorts_production_brief(channel, topic, mode)` prompt use only the fixed repository `prompts/SHORTS_AGENT_PROMPT.md`. User brief values and retrieved material are untrusted content, not authority to override workflow.

Updates allow only title, script, language, format, description, tags, notes, account_id, channel and youtube_title. Explicit inventory account IDs are checked; channel remains a separate freeform field. Missing fields are not cleared. Assets are URLs validated by the existing REST application; the bridge never fetches their contents. New records are always drafts. Published records reject all writes. Every PATCH carries the observed non-published status, letting the existing SQLite transaction reject a competing human publication with 409. Each write is followed by a fresh GET verifying supplied fields and account assignment. This is not general optimistic concurrency for two competing non-published edits.

Create is non-idempotent. **After a timeout or uncertain write result, query before retrying.** The bridge never automatically retries POST or PATCH. Mutation annotations conservatively mark writes non-idempotent because the REST application changes timestamps. No metric append, publish/ready transition, shell, filesystem browsing, sampling, generation, rendering, binary upload or arbitrary HTTP tool exists.

## Bounds and result semantics

Lists default to 25 and cap at 100; offsets are bounded. `total` is filtered item count, `original_total` is the original unfiltered count, `returned` is the page count. Inventory `counts` and `recorded_at` retain original source metadata rather than pretending to describe the filtered page. Video lists omit scripts; reference lists are summaries. Full details require get tools.

Inbound HTTP body limit: 256 KiB, ten-second body deadline. REST socket timeout: ten seconds; tool deadline: 45 seconds. Upstream response read limit: 4 MiB; encoded tool result limit: below 2 MiB including JSON escaping. A source exceeding limits returns a sanitized error rather than partial fabricated data. Scripts are limited to 30,000 characters at this interface. Inputs use strict integer IDs (no booleans, floats, exponent strings or negative values).

The REST API currently returns complete collections; paging is applied in the bridge, so very large upstream collections can hit the upstream cap before paging. Error messages never include upstream bodies, credentials, URL exception diagnostics or stack traces. Credential files and real data must remain outside the public repository.

## Tests

Optional tests skip cleanly without MCP installed. With dependencies installed they use the SDK Client, isolated synthetic HTTP/SQLite fixtures, real stdio subprocess and real Streamable HTTP subprocess. Security tests cover published-record races, sanitization, redirect refusal, strict arguments, authentication, duplicate headers, Host/Origin rejection, body/output bounds and readback. No test reads production data.

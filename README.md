# Shorts Agency

A self-hosted editorial workspace for owned video scripts, manually recorded metrics, a separate reference catalog, and a read-only social-account inventory. The interface is primarily Spanish. Python serves the HTML/CSS/JavaScript application and authenticated API; SQLite and media files live on the local filesystem.

**This release is not Vercel-ready.** It is a single-admin, stateful local application, not a hosted service or multi-tenant SaaS. It has no Supabase integration, automatic social analytics, posting integration, or built-in AI generation. Prompt templates are instructions for an operator, not promises about a model's availability or capabilities. Cloud migration planning is separate from this working local version; see [Supabase Free and future Vercel migration](docs/CLOUD_MIGRATION.md).

## Local setup

Use Python **3.11 or newer**, with SQLite and OpenSSL scrypt support, on Linux or macOS. The secure local-media reader uses POSIX file-descriptor operations; Windows is not currently supported. No pip packages are required for normal operation or the core test suite.

From the cloned repository:

```sh
python3 bootstrap.py
python3 run_local.py
```

On POSIX systems, `./bootstrap.py` and `./run_local.py` are also executable. Paths resolve relative to these scripts, not your working directory. Open `http://localhost:8765` and log in with the username and password you chose. The server binds **127.0.0.1:8765 only**.

Bootstrap prompts for a password twice using `getpass`, refuses an echoing fallback, and requires at least 12 characters. It creates:

- `secrets/admin.json`: username and salted scrypt password hash (32-byte random salt; N=16384, r=8, p=1, dkLen=64).
- `secrets/api_token`: independent random bearer token. It is not printed.
- `data/shorts_agency.db`: local SQLite tables and generic editorial templates.
- `data/social-inventory.json`: **empty** inventory, with no real accounts.
- `media/`: empty directory for operator-provided MP4/WebM files.

Secret files have mode 0600 and their directory mode 0700. Rerunning bootstrap preserves existing credentials, inventory, records, and customized templates; it does not repair an invalid existing credential file or rebuild an incomplete database. Back up private state before any manual recovery. The launcher fails with a setup message if credentials or the database are missing/invalid.

## Configuration and private state

`.env.example` contains settings only. Files named `.env` are **not loaded automatically**. Set an environment variable explicitly when needed:

```sh
SHORTS_AGENCY_ORIGIN=https://agency.example python3 run_local.py
```

`SHORTS_AGENCY_ORIGIN` adds one exact HTTP(S) browser origin, without a trailing slash, path, credentials, query, or fragment. Localhost and 127.0.0.1 origins on port 8765 remain allowed. This setting does not change the loopback bind address or provide TLS. Restart after changing it.

Do not expose the development HTTP server directly to the internet. Any intentional remote hosting needs a reviewed reverse proxy/TLS setup, request limits, backups, and access controls. The server trusts `X-Forwarded-Proto` for its Secure-cookie decision; a proxy must overwrite this header rather than forward arbitrary client values. Origin checks supplement authentication; they are not authentication or general cross-origin API support.

The `.gitignore` excludes runtime data, secrets, environment files, databases, media, research, screenshots, and local tooling. Ignore rules are not a security scanner: inspect staged files before every commit, and never force-add private content. Local records may contain confidential scripts and account metadata.

## Using the workspace

The Clarity interface has two main destinations, **Inicio** and **Vídeos**. A searchable channel selector filters owned content by account without merging brands; content search remains independent. Each video opens a full workspace with **Resumen**, **Guion**, **Publicación**, and **Analítica** tabs, script on the left and preview on the right. The external reference catalog remains accessible from a secondary action, not as another main navigation item. `/scripts` and `/social` remain compatible entry points; `/videos` and `/references` open the corresponding views.

Published scripts are read-only. Registering a publication only records editorial state; it does not publish anything to a social network. After confirmation, both the script and `published` state are protected by the backend for browser and bearer API writes, returning HTTP 409 `published_script_locked` on attempted changes. Metadata and timestamped metrics remain editable. See [publication state and API contract](docs/PUBLICATION_STATE.md). Navigation warns about unsaved changes; a publication conflict preserves a recoverable copy rather than discarding the text.

- **Owned library / scripts:** create and edit scripts, metadata, tags, status, and optional social-account assignment. New drafts created by the UI start in draft status.
- **Social accounts:** read-only UI/API inventory; edit the local JSON as the operator. Optional `public_data` displays dated public observations, source links and collection limitations alongside separate historical screenshot measurements. This is not a live platform connection; see [channel data display](docs/CHANNEL_DATA.md). Its shape is `{"accounts": [], "recorded_at": null}`. Each account uses `id`, `platform` (`youtube`, `instagram`, or `tiktok`), `name`, `handle`, `profile_url`, `ownership`, `sync_status`, `source`, and optional `analytics`. Use stable IDs for existing script associations. Only enter profiles you have permission to record; inventory membership does not prove ownership. There is no hardcoded account total.
- **References:** distinct from owned scripts. Import validated reference metadata through the bearer-only endpoint. Source metadata is not a verified transcript or a license to reuse content.
- **Metrics:** manual/agent observations with timestamps; missing values remain unknown, not zero. No live analytics connection exists.
- **Media:** put your own `.mp4`/`.webm` files directly in `media/` and use `/media/filename.mp4`. Authenticated reads support byte ranges; symlinks and traversal are rejected.

The backend does not fetch stored URLs. Browser previews can contact external hosts; YouTube embeds require an explicit load action. Use only content you are authorized to access or display.

## API summary

Bearer authorization is `Authorization: Bearer <contents of secrets/api_token>`. Treat the file as a secret, not a literal example key. Browser sessions use HttpOnly, SameSite=Strict cookies; session writes require an allowed `Origin` plus `X-CSRF-Token` from login or `/auth/me`. Bearer writes do not require CSRF, but any supplied Origin is still checked.

| Method | Route | Purpose |
| --- | --- | --- |
| POST | `/auth/login` | JSON `username`, `password`; returns session cookie and CSRF token |
| GET / POST | `/auth/me` / `/auth/logout` | Current session / revoke session |
| GET | `/v1/health` | Authenticated health check |
| GET | `/v1/templates`, `/v1/prompts?template_id=...`, `/v1/channels` | Generic templates, prompt blocks, research-channel records |
| GET / POST | `/v1/shorts` | List / create owned records; `title` required |
| GET / PATCH | `/v1/shorts/{id}` | Read / partially update a record |
| GET / POST | `/v1/shorts/{id}/metrics` | List / append timestamped metrics |
| GET | `/v1/scripts?q=...` | Search owned titles, scripts, and channels |
| GET | `/v1/social-accounts` | Local inventory and dynamically calculated counts |
| GET | `/v1/references?q=...&type=short` | Search reference catalog |
| GET | `/v1/references/{id}`, `/v1/references/status` | Reference detail / import status |
| POST | `/v1/references/import` | Bearer-only atomic import/upsert; JSON `items` and `run`, maximum 100 items |
| GET / HEAD | `/media/{filename}` | Authenticated local media |

For exact field schemas, inspect `web_validation.py`, `reference_store.py`, and the synthetic acceptance tests. Unknown fields are rejected. There is no delete endpoint, password reset UI, or user-management API.

A local API request without putting the token in shell history or printing it:

```sh
python3 - <<'PY'
from pathlib import Path
from urllib.request import Request, urlopen
request = Request('http://127.0.0.1:8765/v1/health', headers={
    'Authorization': 'Bearer ' + Path('secrets/api_token').read_text().strip()
})
with urlopen(request, timeout=5) as response:
    print(response.read().decode())
PY
```

## Tests

```sh
python3 -m unittest discover -s tests -v
```

All tests use temporary SQLite databases, random ephemeral test credentials, and invented fixtures. They never need a local inventory or production data. Platform-shaped test URLs are **unverified synthetic placeholders**, not real-account claims, and browser tests block external HTTPS requests. The normal inventory fixture is small; only browser regression coverage uses a 21-account fixture.

Browser tests are optional and skipped by default. To opt in, provide both Python Playwright and the Node.js `playwright` module, plus their Chromium browser, then run:

```sh
RUN_BROWSER_TESTS=1 python3 -m unittest discover -s tests -v
```

Missing optional Playwright or Chromium produces a skip, not a core-suite failure. `PLAYWRIGHT_MODULE` may select the Node module location; `PLAYWRIGHT_CHROMIUM_EXECUTABLE` may select an existing browser (for example `/usr/bin/google-chrome`). No browser sandbox is disabled by these tests. An optional read-only CI workflow template is supplied at `docs/github-actions-tests.yml.example`, with no deployment or secrets. It is not active: the publishing GitHub credential lacks workflow scope. A repository owner can enable it by copying it to `.github/workflows/tests.yml` using a credential with the required permission; no CI pass is claimed for this release.

## Publication and licensing

This repository contains code, generic templates, and synthetic test fixtures only. Runtime accounts, databases, media, passwords, and research are not part of the release. No software license has been selected; public visibility alone is not a grant of open-source reuse rights. No cloud deployment is configured.

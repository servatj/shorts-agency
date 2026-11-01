# Channel public-data display

The Clarity UI reads account metadata directly from the existing `GET /v1/social-accounts` inventory. No backend changes, migrations, publication schema changes, platform connection, or automatic synchronization are introduced. The sidebar remains **Inicio / Vídeos**.

## Display contract

- `account.name` is the primary identity; platform and a validated profile link accompany it. A trusted `public_data.canonical_url` can supply a profile link when the inventory link is unavailable, using the existing platform-host validator.
- `public_data.status` accepts `ok`, `partial`, `blocked`, `missing_url`, `not_found`, and `identity_mismatch`. Missing metadata reads **No consultado**. Only `ok` and `partial` expose public profile/metric observations. In particular, identity mismatches never expose the candidate metrics.
- Optional biography and notes are inserted as text, not HTML. Avatars and external images are not loaded. Source links require HTTPS, reject credentials, and use `noopener noreferrer`.
- `metrics` supports followers, subscribers, following, posts, likes, and views. Nonempty `display` takes precedence over numeric `value`; approximate observations receive `≈`. Unknown values are `—`; observed zero remains `0`. Each supplied observation shows its own date and safe source link.
- Collection provenance uses `attempted_at`, `source_method`, and `source_url`. `publications_collected` is explicitly labeled **enlaces recopilados**, never substituted for the channel's total posts. `catalog_status` is shown separately.
- Historical `analytics.subscribers` remains a separate screenshot observation labeled **NO en directo**, including unknown capture dates. Selector tooltips prefer trusted public metrics and their provenance, then fall back to screenshot observations.
- All-channel coverage and pending counts derive from the actual inventory, not a fixed account total. Pending/incomplete accounts are in a collapsed detail list. `Sin canal` and external references hide the public-data summary.
- Account switching retains the existing unsaved-change guard. Updating the inventory reloads metadata, not a platform connection; it does not modify `sync_status`.
- Published records with empty scripts show **Guion no disponible** in the inspector and read-only viewer. Existing publication locks are unchanged.

## Synthetic browser verification

Run with Node and an installed Playwright package/browser:

```sh
node tests/channel_data_browser.cjs
```

Optional environment variables: `PLAYWRIGHT_MODULE` and `PLAYWRIGHT_CHROMIUM_EXECUTABLE`. This browser test serves repository static assets and synthetic API responses through Playwright routing; it uses no live accounts, credentials, or production files. It checks provenance, approximate/display values, zero/unknown values, collection statuses, screenshots kept separate, safe links, HTML injection, no external image requests, the 390px layout, published empty scripts, and the unsaved-change guard.

Existing regression suite (browser dependencies must be installed):

```sh
RUN_BROWSER_TESTS=1 python -m unittest discover -s tests -q
```

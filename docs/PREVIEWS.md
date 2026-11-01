# Owned-video previews

## Metadata contract

`POST /v1/shorts` and `PATCH /v1/shorts/{id}` accept optional `thumbnail_url`:

- String, default `""`; empty removes the image.
- Maximum 4096 characters. Nonempty values pass the shared `https_url` validator: HTTPS with a hostname, no credentials, spaces/control characters, backslashes or malformed ports.
- Unknown fields remain errors. No database migration or backfill is required: legacy records return an empty thumbnail on list, detail and metadata PATCH.
- Updating a published record's thumbnail is an ordinary metadata edit. Published scripts and status remain locked; a forbidden script change rejects the entire PATCH.
- Example synthetic payload: `{"thumbnail_url":"https://images.example/cover.jpg"}`.

The operator must verify that the URL comes from the publication's existing metadata and identifies that publication. This application does not establish provenance, invent covers, turn captions into images, infer original scripts, or generate images. Missing published scripts continue to display **Guion no disponible**.

## Browser behavior and privacy

A supplied image loads directly in the browser, not through a server fetch/proxy. List, inspector and detail use lazy images with descriptive alt text and `referrerPolicy="no-referrer"`. List covers use `object-fit:cover`; inspector/detail use `contain`. Missing or failed images show **Imagen no disponible**. Failed URLs are remembered for the page session, without automatic retries; a corrected URL or page reload permits another attempt.

Video priority is local `/media/<filename>.mp4|webm`, then an existing valid YouTube link, then a supported TikTok publication. Existing remote HTTPS MP4 preview support remains available when no preferred platform player exists. A local-looking path must match the media filename allowlist before being treated as video.

No player iframe or video element is created until **Cargar vista previa** is clicked. YouTube remains opt-in, using its privacy-enhanced origin with `autoplay=0`. TikTok accepts only HTTPS `tiktok.com` or `www.tiktok.com`, an exact `/@handle/video/<digits>` path and optional query string. No subdomains, userinfo, ports, encoded paths, extra path components or fragments are accepted for embedding. It constructs only:

```
https://www.tiktok.com/player/v1/{id}?autoplay=0&loop=0
```

The player contract follows TikTok's official Embed Player documentation (provided and verified in the implementation brief):

```
https://developers.tiktok.com/doc/embed-player
```

Iframes have meaningful titles, fullscreen permission and `strict-origin-when-cross-origin` referrer policy. CSP adds only `https://www.tiktok.com` to the existing YouTube `frame-src`. No `embed.js`, oEmbed HTML, arbitrary iframe host, OAuth or Instagram keys are used. Instagram and other external pages remain image plus external-source link only.

Source links live outside the replaceable player content and remain available before and after requesting a player. **Volver a la portada** removes the requested iframe and restores the image or neutral fallback without changing the record or triggering playback. The UI says the player was **requested**, not that playback succeeded: iframe load events do not prove playback. Platform policies, deleted/private videos, region restrictions, expired image URLs and browser blocking may prevent playback. Open the original when this happens.

The server never downloads/stores video or audio. Clicking a player permits ordinary browser streaming; this is not a server media import. External reference records and their opt-in player flow are unchanged.

## Verification

`tests/test_previews.py` exercises the actual HTTP server and isolated SQLite database: schema validation, malicious URLs, length boundary, persisted metadata, published locking and legacy compatibility. `tests/previews_browser.cjs` drives the real app with synthetic fixtures and intercepted remote requests (no platform video downloads), covering images/fallbacks, editor saves, explicit TikTok/YouTube loading, strict TikTok URLs, source links, Instagram external-only behavior, CSP and local-media priority.

Run with `RUN_BROWSER_TESTS=1`, optionally setting `PLAYWRIGHT_MODULE` and `PLAYWRIGHT_CHROMIUM_EXECUTABLE` for the installed browser environment:

```
python -m unittest discover -s tests -v
```

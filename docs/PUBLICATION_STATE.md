# Publication state and script integrity

Owned shorts are JSON documents in `web_shorts`. Supported statuses remain
`draft`, `review`, `ready`, and `published`. No schema migration or new tables
are required. Publication here records application state; it does not upload,
schedule, or publish anything to a social platform.

## State contract

- Before publication, script and status edits retain their existing validation.
- `POST /v1/shorts` may create an already-published short. Its stored script is
  protected immediately, including an empty script when none was supplied.
- `PATCH /v1/shorts/{id}` may transition an unpublished short to `published`
  together with its final script revision. That exact revision becomes immutable.
- Once published, the short must remain `published`. Rollback to `draft`,
  `review`, or `ready` is not an unlock mechanism.
- A supplied script must equal the stored string exactly. Whitespace, Unicode,
  and newlines are preserved, not normalized or silently truncated.
- Omitting the script or resending the identical script is permitted. Omitting
  status or resending `published` is permitted, including both unchanged fields
  in a larger form submission.
- Metadata remains editable: title, description, tags, notes, URLs, channel,
  social-account assignment, and other existing validated metadata fields.
  Existing account-reference validation is unchanged.
- Metrics may still be appended using `POST /v1/shorts/{id}/metrics`; they do not
  mutate the script or publication state.

`published` is terminal for script integrity, not a read-only lock on the whole
record. The UI can derive its script lock from `status === 'published'`; no
`script_locked` response field was added.

## Conflict contract

An otherwise valid authenticated PATCH that changes a published script or moves
its status away from `published` returns:

```http
HTTP/1.0 409 Conflict
Content-Type: application/json; charset=utf-8
Cache-Control: no-store
```

```json
{"error": "published_script_locked"}
```

The entire PATCH is rejected: accompanying metadata and `updated_at` are also
unchanged. No partial update or silent success occurs. Clients should retain
unsaved edits, report the conflict, and refetch the short to show current state.
Do not retry by changing status to `draft`.

Browser sessions and bearer-agent requests use the same enforcement. Session
writes still require an allowed Origin and valid `X-CSRF-Token`. Existing
unauthorized/CSRF/validation responses remain 401/403/400 respectively; malformed
fields are validated before publication checks. A valid PATCH to an unknown ID
still returns `404 {"error":"not_found"}`.

Direct callers of `WebStore.patch_short` receive
`web_store.PublishedScriptLocked`, whose message is `published_script_locked`.
Missing IDs still raise `KeyError`. The HTTP handler maps only the publication
exception to the explicit 409 conflict.

## Atomicity and persistence

`WebStore.patch_short` starts `BEGIN IMMEDIATE`, reads the current row using that
same connection, checks its existing status and incoming fields, then merges and
updates only if allowed. This prevents stale clients or competing writers from
bypassing a committed publication. Rejected changes roll back. Existing published
documents are protected on reopening the database; no in-memory lock or migration
is involved. Direct SQL access is outside this application API boundary.

## Public shell routes

`/videos` and `/references` are exact aliases of the public application shell,
alongside `/`, `/social`, and `/scripts`. They expose no private data. API auth,
media Range handling, reference APIs, and static-file restrictions are unchanged.

## Verification

`tests/test_publication_lock.py` covers direct SQLite access through WebStore,
fresh/reopened instances, a competing database writer, real HTTP bearer and
CSRF-session paths, publication with a final revision, direct published creation,
rollback and combined-mutation rejection, exact long-script resends, metadata,
metrics, validation, unknown IDs, and shell-route aliases.

Run the focused and regression suites from the repository root:

```sh
python -m unittest discover -s tests -p test_publication_lock.py -v
python -m unittest discover -s tests -v
```

Tests use isolated temporary databases and existing generic test authentication
fixtures; they do not access deployed application data or credentials.

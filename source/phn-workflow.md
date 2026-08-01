# PH-Navigator agent workflow

Use the `phn` MCP server for production PH-Navigator project data. If you are
working inside the PH-Navigator application repository and its `phn-local`
server is available, use `phn-local` for development fixtures; do not mix local
development with production client data.

## Resolve the project first

{project_resolution}

The `phn` MCP bridge reads `{credentials_path}`. Missing, expired,
or revoked credentials trigger browser device authorization automatically. The
only human action is approving or denying the exact request in PH-Navigator.
Never request, print, paste, or store the bearer token in a project folder.
Use {login_command} when the user explicitly asks to replace or refresh the
machine credential.

## Choose focused reads

- `get_project` returns project metadata and versions; `list_versions` returns
  version metadata only.
- `get_document` returns the complete saved document or current user draft.
  Prefer `get_table` for one registered table.
- `list_status_items` reads the relational status tracker.
- `query_unfinished_envelope_work`, `report_missing_envelope_evidence`, and
  catalog-drift/report tools answer focused QA questions without loading the
  full document.
- Use the climate, asset, aperture, and HBJSON tools only for their named
  surfaces. Resolve asset URLs only when the task needs file access.

For a project-status request: resolve the marker, call `get_project`,
`list_status_items`, and `query_unfinished_envelope_work`, then summarize the
active version, status items, and unfinished envelope work with exact record
names/counts.

## Protect production data

Client projects are live production data.

- Read before writing. Draft writes require the latest `version_body_etag` for
  the first write or `draft_etag` for later writes.
- Prefer semantic `apply_envelope_command` and `apply_aperture_command` tools
  for structural edits. `replace_table` is the lower-level whole-table
  primitive: read the current table, preserve its full payload, preview a
  destructive replacement with `preview_replace_table`, then replace.
- Writes land in the issuing user's draft. Read back when another write
  depends on the new draft etag.
- Never call `save_draft` or `save_draft_as` unless the user explicitly asks
  to persist the draft. For a verification-only edit, use `diff_versions` with
  `to="draft"`, then call `discard_draft` and confirm the draft is gone.
- Never call `delete_project`, `restore_project`, or `hard_delete_project`
  unless the user explicitly requests the exact operation. Treat
  `hard_delete_project` as off-limits during autonomous work.

## Recover from structured errors

MCP failures expose a JSON `ToolError` string with `code`, `message`,
`request_id`, `recoverability`, and `details`.

| Recoverability | Required response |
|---|---|
| `refresh` | Re-read project/version/draft state; retry only if still intended. |
| `reauthenticate` | Run device authorization and retry once. |
| `forbidden` | Stop; the reachable project or token lacks the required capability. |
| `retry` | Retry a bounded number of times for a transient failure. |
| `fatal` | Correct the input or stop; never retry unchanged. |

For `version_locked`, use `save_draft_as` only when the user asked to preserve
the work in a new version. For stale etags, refresh and reconstruct the intended
change from current state rather than replaying an old whole-table payload.

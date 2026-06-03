# Ticket Dashboard — Design (2026-05-30)

Read-only local web dashboard to view tickets per project (dev-os host + registered
projects), grouped by status as a kanban board.

## Goal

Give the operator a single localhost page that shows, **per project**, every ticket's
id / owner / status / content — replacing the need to `os3 queue` each project
separately. View-only; the SSOT (QUEUE.yaml / ARCHIVE.yaml) is mutated only by the
existing CLI / dispatch flow.

## Decisions (locked)

- **Interaction**: read-only. No status changes, no editing from the UI.
- **Stack**: Python **stdlib `http.server`** (zero new runtime deps — PyYAML already present)
  + a single build-free `index.html` with vanilla JS. Approach "A".
- **Location**: a new module under `server/` (not `apps/`). Reuses `server/ssot.py`
  and `server/projects_registry.py`.
- **Layout**: project sections + per-status **kanban columns**.
- **Deployment**: localhost only (127.0.0.1). No auth.
- **Entry point**: `os3 dashboard`.

## Architecture

```
bin/os3 dashboard
  → server/cli.py: _handle_dashboard()
      → server/dashboard.py: serve(host_root, port, open_browser)
          ├── data layer (pure, testable):
          │     server/dashboard_data.py
          │       - list_dashboard_projects(host) -> [ProjectSummary]
          │       - load_project_board(host, name) -> Board (status-grouped tickets)
          │       - load_ticket_detail(host, name, ticket_id) -> dict | None
          │     (reuses projects_registry.list_projects,
          │            ssot.read_queue_with_archive / find_ticket / find_archived_ticket)
          └── http layer:
                stdlib http.server.BaseHTTPRequestHandler
                  - GET /                              -> index.html (static)
                  - GET /static/*                      -> static assets (app.js, style.css)
                  - GET /api/projects                  -> project list + status counts
                  - GET /api/projects/{name}/tickets   -> status-grouped tickets (list fields)
                  - GET /api/projects/{name}/tickets/{id} -> full ticket
```

Split data layer (`dashboard_data.py`) from HTTP/serving (`dashboard.py`) so the
aggregation logic is unit-testable without sockets.

### Project discovery

`list_dashboard_projects(host)`:
1. The host itself (dev-os) — `host/devos/tasks/QUEUE.yaml`. Always listed first as `dev-os`.
2. Registered projects from `projects_registry.list_projects(host)` — each record's
   `repo_path` → `<repo_path>/devos/tasks/QUEUE.yaml`.

For each project, resolve the queue path and merge QUEUE + ARCHIVE via
`ssot.read_queue_with_archive(queue_path)`.

### Status grouping

Group tickets into the 7 canonical statuses, in board order:
`todo, doing, code_ready, needs_pm, blocked, parked, done`.
Any ticket whose `status` is unknown/missing → bucket `unknown` (shown last, so data
problems are visible rather than silently dropped).

### Ticket fields

- **List (board card)**: `id`, `owner`, `status`, `priority`, first line of `goal`.
- **Detail**: full ticket dict — `goal`, `context`, `constraints`, `dod`, `files`,
  `verify`, `deps`, `gates`, `tdd`, `test_owner`, `impl_owner`, and `_transition_history`.

## API contract

| Method/Path | Response |
|---|---|
| `GET /api/projects` | `{ "projects": [ { "name", "repo_path", "ok": bool, "error": str\|null, "counts": { "<status>": int }, "total": int } ] }` |
| `GET /api/projects/{name}/tickets` | `{ "name", "ok", "error", "columns": [ { "status", "tickets": [ {id, owner, status, priority, goal_summary} ] } ] }` |
| `GET /api/projects/{name}/tickets/{id}` | full ticket object, or `404 { "error": "not found" }` |
| unknown project name | `404 { "error": "unknown project" }` |

`done` column: include count of all archived+done, but only return the most recent N
(default 30) cards; response carries `"done_truncated": <int omitted>` so the UI shows
a "+N more" affordance. (Recency = order in ARCHIVE, newest last → take tail.)

## Frontend (single page, no build)

- `server/dashboard_static/index.html` + `app.js` + `style.css`.
- Top bar: project tabs (one per project; shows total + a red dot if `ok==false`),
  a **Refresh** button, and an optional **auto-refresh** toggle (poll every 10s).
- Body: kanban columns for the selected project. Each card shows id, owner badge,
  status-colored left border, goal summary.
- Click a card → right-side detail panel renders the full ticket (markdown-ish fields
  shown as preformatted text; `dod`/`files`/`deps` as lists; transition history as a
  small table).
- A project with `ok==false` renders its `error` string in place of columns.

## Error handling

- Missing QUEUE.yaml for a project → that project's `ok=false`, `error="QUEUE.yaml not found"`;
  other projects unaffected; dashboard still serves.
- YAML parse error → `ok=false`, `error=<message>`; never 500 the whole list.
- Unknown route → 404 JSON.
- Port in use → `os3 dashboard` exits non-zero with a clear message (suggest `--port`).

## CLI

`os3 dashboard [--port 8787] [--no-open]`
- Default bind `127.0.0.1:8787`.
- Resolves host root via existing `config` helpers.
- Opens the default browser unless `--no-open` (uses stdlib `webbrowser`).
- Ctrl-C → clean shutdown.

## Testing

Unit (pytest, data layer — the real logic):
- `list_dashboard_projects` includes host as `dev-os` first, then registry projects.
- A project with a missing QUEUE.yaml → `ok=false`, `error` set, others still `ok=true`.
- A project with malformed YAML → `ok=false`, does not raise.
- `load_project_board` groups tickets into the 7 columns in order; an unknown status
  lands in `unknown`.
- `load_project_board` done column truncates to N and reports `done_truncated`.
- `load_ticket_detail` returns a full ticket from QUEUE; returns an archived ticket;
  returns `None` for a missing id.

HTTP layer (pytest, in-process):
- `GET /api/projects` → 200 + `application/json`, shape matches contract.
- `GET /api/projects/{name}/tickets` → 200, columns present.
- `GET /api/projects/dev-os/tickets/{known-id}` → 200 with full fields.
- `GET /api/projects/dev-os/tickets/NOPE` → 404.
- `GET /api/projects/NOPE/tickets` → 404.
- `GET /api/projects` uses a temp host fixture (tmp_path) with synthetic
  QUEUE/ARCHIVE so tests are isolated and order-independent.

Frontend: manual verify procedure (load page, click project tab, click a card, confirm
detail renders; toggle auto-refresh).

## Out of scope (YAGNI)

- Any write/edit/status-change from the UI.
- Auth / non-localhost exposure.
- Cross-project aggregated views, search/filter, charts (could be a fast-follow).
- React/build tooling.

## File layout

```
server/dashboard.py          # http.server handler + serve()/CLI glue
server/dashboard_data.py     # pure aggregation (testable)
server/dashboard_static/
    index.html
    app.js
    style.css
tests/test_dashboard_data.py # unit
tests/test_dashboard_http.py # in-process HTTP
```

`server/cli.py` gains a `dashboard` subcommand → `_handle_dashboard`.

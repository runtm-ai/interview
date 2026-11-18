# Collaborative Workspace

Build a workspace where users upload documents (PDF, PPTX, XLSX), chat with
them, run agents against them, and produce reports. Multiple users can
collaborate in the same workspace.

## Core requirements

- Upload PDFs, PowerPoints, and Excel files to a workspace
- Extract content from uploads to enable search over documents
- Chat interface where users ask questions against one or more documents
- Ability to trigger an agent run that produces a report from workspace
  documents
- Multiple users can be members of a workspace and see each other's
  uploads/chats

## What we're evaluating

Use whatever coding agent you'd like (Claude Code, Cursor, etc.) — we care
about the judgment behind what you build, not whether you typed every line
by hand. Be ready to explain what you built, where you trusted the agent,
and where you overrode it. There's no single correct architecture; make
reasonable tradeoffs and be ready to defend them, including how the design
would change under load (100k users, 5GB files, concurrent uploads, live
collaboration, one workspace with a million documents).

## Structure

```
/frontend       # UI: upload flow, chat, loading/error states
/backend        # API, background jobs, schema
/infra
  architecture.md   # describe your infra choices (no IaC needed)
```

`infra/architecture.md` should describe, in prose/diagrams: hosting,
storage, background job/queue setup, database choice, and how you'd
sandbox any code execution (e.g. agent-generated Python) — containers,
resource limits, network isolation, cleanup. No Terraform required, just
the reasoning.

## Not in scope

- Auth/SSO polish (a stubbed login is fine)
- Production-grade CI/CD
- Algorithmic puzzle-solving — this is a product-building exercise

## Run the demo locally

Use Python 3.11 or newer and Node.js 20.19+ or 22.12+ with npm. Run the
commands from the repository root.

In the first terminal, create the Python environment and start the API.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.txt
.venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

In the second terminal, install the locked frontend dependencies and start Vite.

```sh
npm --prefix frontend ci
npm --prefix frontend run dev
```

Open the [demo entry screen](http://127.0.0.1:5173/) in two tabs and choose a
different user in each. You can also open the workspace directly as
[Alice](http://127.0.0.1:5173/workspaces/launch?user=alice) and
[Bob](http://127.0.0.1:5173/workspaces/launch?user=bob).

1. Both tabs should show **Launch** and list **Alice** and **Bob** once each
   under **Members**. The tabs should say **Viewing as Alice** and **Viewing as Bob**.
2. Refresh Bob’s tab and then Alice’s. Each should retain its own viewer.
3. Stop the API with Ctrl+C and rerun the Uvicorn command. Refresh both tabs
   again. The viewer names and member list should match the previous result.

The Vite server forwards requests under `/api` to the API on port 8000.
The workspace page uses the URL’s `user` value as the API’s `X-Demo-User`
header. This header selects an identity for the local demo. Both commands
bind to loopback. The API stores the workspace and its full-text index in
`backend/data/workspace.sqlite3` by default. To use a different SQLite file,
set `WORKSPACE_DB_PATH` before starting the API. Use a Python build with SQLite
3.35 or newer and FTS5 enabled.

These two requests should each return HTTP 401.

```sh
curl -i http://127.0.0.1:8000/api/workspaces/launch
curl -i -H 'X-Demo-User: unknown' http://127.0.0.1:8000/api/workspaces/launch
```

## Verify document ingestion

1. Open Launch as Alice. Under **Documents**, upload
   `launch-brief.pdf`, `launch-deck.pptx`, and `launch-budget.xlsx` from
   [fixtures](fixtures/), one at a time. Each reaches **ready**.
2. Upload `fixtures/broken.pdf`. Its entry reaches **failed** and displays
   “Could not read this PDF.”
3. Refresh Bob’s tab. Both tabs show the same filenames and statuses, and
   each tab retains its viewer.

The API saves originals under generated IDs in the `uploads/` directory
beside the SQLite file. It indexes embedded PDF text, slide text frames, and
stored spreadsheet cell values. Ready documents and failures survive an API
restart. The demo runs as a single API process. On startup it marks any
interrupted documents **failed** and asks the uploader to upload them again.

To inspect the index in the default database, run this read-only query after
uploading the fixtures. Expect hits on slides 1 and 2 of the deck and
row 4 of the spreadsheet’s **Budget** sheet. Slide 2 and row 4 contain the
launch budget total.

```sh
sqlite3 -readonly backend/data/workspace.sqlite3 <<'SQL'
SELECT d.filename, p.location, p.text
FROM document_passages AS p
JOIN documents AS d ON d.id = p.document_id
WHERE document_passages MATCH 'budget' AND d.workspace_id = 'launch'
ORDER BY d.filename, p.location;
SQL
```

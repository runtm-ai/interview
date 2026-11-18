# One-hour collaborative workspace POC

Alice uploads a PDF, a slide deck, and a spreadsheet. Bob opens the same workspace in another tab, asks “What is the launch budget?”, and checks the cited slide and spreadsheet rows. He narrows the search to the spreadsheet and generates a report. Alice sees his question and completed report, including after a refresh.

## Build schedule

| Minutes | Work | Checkpoint |
| --- | --- | --- |
| 0–10 | Scaffold React, TypeScript, and Vite in `frontend/` and FastAPI with SQLite in `backend/`. Seed two workspace members and prepare three small text-bearing fixtures with known source locations. | Both tabs can open the workspace with different demo identities. |
| 10–25 | Save uploads to local disk under generated IDs. Return a document ID and persist processing status. Extract text with pypdf, python-pptx, and openpyxl. Index passages in SQLite FTS5 with their page, slide, or sheet and row. | Each file reaches ready or failed. A failed extraction has a readable error. |
| 25–38 | Add document selection, ranked keyword retrieval, citations, and shared chat history. Default to all ready documents. Check workspace membership and document scope on the server. | Bob finds the known figure, can narrow the results to one file, and sees a clear message for a query with no matches. |
| 38–48 | Run a key-free report job that collects excerpts from the selected documents and saves a Markdown brief. Show progress and errors. Paginate document and message lists and poll for changes since the last cursor. | Alice sees Bob’s message and saved report in her tab. |
| 48–55 | Write the architecture comparison below in `infra/architecture.md`. Reconcile the POC column with the running application and record any shortcuts taken during the hour. | Each production change has a reason and a way to validate it. |
| 55–60 | Rehearse the walkthrough, check workspace isolation, and record one coding-agent suggestion accepted and one changed, using examples from the build. | The demo and architecture discussion fit the remaining time. |

## Required architecture comparison

Use **POC vs. production** as a section in `infra/architecture.md`. Cover hosting, storage, jobs, database choice, and execution isolation. Distinguish demonstrated behavior, proposed changes, and capacity claims that still need measurement.

| Area | Planned POC | Production difference to document |
| --- | --- | --- |
| Hosting and identity | One local API process, two seeded users, server-side workspace checks | Serve the frontend from a CDN and run stateless API replicas behind a load balancer. Authenticate users and enforce membership revocation across files, search, and live subscriptions. |
| Uploads up to 5 GB | Local files and background parsing for small fixtures | Authorize resumable multipart uploads directly to object storage. Verify completion before queuing extraction. Test each parser against its own memory, expanded-size, disk, and runtime limits. |
| Concurrent uploads and jobs | Persist status in SQLite. In-process work can be interrupted on restart. | Use durable jobs, retry-safe workers, and per-workspace concurrency limits. Check that interrupting a worker cannot lose a job or duplicate passages. |
| One million documents in a workspace | SQLite FTS5, source locations, paginated lists, and scoped retrieval | Start with managed PostgreSQL and indexed passage search. Measure query latency during ingestion in the largest workspace before dedicating a separate service to search. |
| Live collaboration at 100k users | Cursor-based polling between two tabs | Size for peak connected users and activity per workspace. Push committed events with Server-Sent Events and replay missed changes after reconnect. |
| Chat and agent reports | Cited keyword matches and a deterministic evidence report | Evaluate citation quality and cost if model synthesis is introduced. Checkpoint exhaustive reports in batches. Run any future generated code in isolated, short-lived containers with resource limits, restricted networking, and cleanup. |
| Operations and user data | Local demo data and a repeatable walkthrough | Set retention and deletion rules for originals, extracted passages, and reports. Test backup restoration and monitor search latency, indexing delay, and job failures. |

## Completion checks

- Demonstrate all three formats, a correct citation, document filtering, a no-match response, and a failed upload. Confirm chat and reports survive a page refresh.
- Verify that a member cannot retrieve or cite a document from a workspace they cannot access, even by submitting its ID directly.
- In the architecture note, specify a production load test that combines searches in a million-document workspace, concurrent 5 GB uploads, and a report run. Measure 95th-percentile search latency, time from upload completion to search availability, and peak worker memory. Include an interrupted worker and a reconnecting browser.
- If time slips, cut visual polish first. Preserve the two-user walkthrough and the seven-minute architecture write-up.

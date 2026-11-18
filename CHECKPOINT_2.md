# Checkpoint 2 — Upload and index workspace documents

**Implemented, verified, and accepted by the user after hands-on testing.** Alice can upload the three valid files in `fixtures/`, see whether each is ready, and see a reason if a file fails. When Bob refreshes Launch, he sees the same documents. A ready file has searchable text tied to a source location. Chat, ranked results, and clickable citations belong to checkpoint 3.

## Decisions for review

| ID | Proposed feature | What you can check |
| --- | --- | --- |
| A | Accept and store a workspace member’s upload | Two uploads with the same filename get different document IDs. |
| B | Extract text from PDF, PPTX, and XLSX | An extracted amount can be traced to its original slide or spreadsheet row. |
| C | Index the text and persist the outcome | Ready means indexing finished. A broken file gets a readable failure that survives refresh. |
| D | Add a Documents section to Launch | Alice can upload a file, watch its status, and see the same result as Bob after he refreshes. |

Proposed build order is A through D. B reads files saved by A. C publishes B’s output. D reads the document records from A and C. You can approve, decline, or request changes by letter, including individual formats under B. The excerpts below show the proposed code paths. Named helpers describe code to be written after approval.

### A. Accept and store an upload

Add a multipart endpoint under the existing Launch workspace route. Reuse checkpoint 1’s viewer and membership checks for both upload and list requests. Use the original filename for display and a generated ID for storage. Return HTTP 202 once the file and its processing record are saved, so Alice can continue while extraction runs.

```python
@app.post("/api/workspaces/launch/documents", status_code=202)
def upload_document(file: UploadFile, tasks: BackgroundTasks,
                    member: Annotated[User, Depends(require_launch_member)]):
    filename = Path(file.filename or "").name
    suffix = Path(filename).suffix.lower()
    if suffix not in {".pdf", ".pptx", ".xlsx"}:
        raise HTTPException(415, "Choose a PDF, PowerPoint (.pptx), or Excel (.xlsx) file.")

    document_id = uuid4().hex
    path = upload_dir / f"{document_id}{suffix}"
    document = save_upload(file.file, path, document_id, filename, member.id)
    tasks.add_task(index_document, document_id, path)
    return document
```

`save_upload` would stream to a temporary file beside the SQLite database, rename it into the uploads directory on the same filesystem, and commit the document row. If saving or committing fails, it cleans up the files it created. The row records the ID, workspace, uploader, display name, upload time, status, and optional error. The list query filters by the authorized workspace.

**Acceptance check.** Upload the same PDF twice. Both requests return different IDs and both originals exist. A request from a user outside Launch is denied before anything is saved. A plain `.txt` file returns a format error immediately.

### B. Extract text with source locations

Extract one passage per nonempty page, slide, or spreadsheet row. The numbers start at one so a user can find the same place in the original. For this demo, PowerPoint extraction covers text frames and Excel extraction uses stored cell values, including cached formula results when available. The PDF reader extracts embedded text. [PDF text extraction](https://pypdf.readthedocs.io/en/stable/user/extract-text.html) · [PowerPoint text frames](https://python-pptx.readthedocs.io/en/latest/user/quickstart.html) · [Read-only workbooks](https://openpyxl.readthedocs.io/en/stable/optimized.html)

```python
def pdf_passages(path):
    with path.open("rb") as source:
        for page, item in enumerate(PdfReader(source).pages, start=1):
            text = (item.extract_text() or "").strip()
            if text:
                yield {"page": page}, text

def pptx_passages(path):
    for slide, item in enumerate(Presentation(path).slides, start=1):
        text = "\n".join(s.text for s in item.shapes if s.has_text_frame).strip()
        if text:
            yield {"slide": slide}, text

def xlsx_passages(path):
    with closing(load_workbook(path, read_only=True, data_only=True)) as book:
        for sheet in book.worksheets:
            for row, cells in enumerate(sheet.values, start=1):
                text = " | ".join(str(v) for v in cells if v is not None and str(v).strip())
                if text:
                    yield {"sheet": sheet.title, "row": row}, text
```

**Acceptance check.** The PDF produces the campaign brief at page 1. The deck produces “The launch budget is $120,000.” at slide 2. The spreadsheet yields `Media | 80000`, `Events | 40000`, and `Launch budget total | 120000` at Budget rows 2, 3, and 4. A document with zero readable passages gets a failure reason.

### C. Index passages and persist the outcome

Use FastAPI’s in-process background tasks and the existing SQLite database. Add a full-text table with a document ID, structured location stored as JSON, and searchable text. The document ID joins each hit to its workspace through the documents table. [SQLite FTS5](https://www.sqlite.org/fts5.html)

```sql
CREATE VIRTUAL TABLE IF NOT EXISTS document_passages USING fts5(
    document_id UNINDEXED, location UNINDEXED, text
);
```

```python
def index_document(document_id, path):
    try:
        # Parse the small demo file before acquiring the SQLite write lock.
        passages = list(extractors[path.suffix](path))
        if not passages:
            raise NoReadableText()
        with closing(connect()) as db, db:
            db.executemany(
                "INSERT INTO document_passages(document_id, location, text) VALUES (?, ?, ?)",
                ((document_id, json.dumps(location), text) for location, text in passages),
            )
            db.execute("UPDATE documents SET status = 'ready' WHERE id = ?", (document_id,))
    except Exception as error:
        # Record a user-facing reason in a fresh transaction after any rollback.
        mark_failed(document_id, readable_error(error, path.suffix))
```

**Restart decision for review.** In the single-process demo, startup would mark leftover `processing` records as `failed` with “Processing was interrupted. Upload the file again.” Completed documents and their passages persist. This gives Alice an actionable result and keeps durable retries in the production design.

**Acceptance check.** Match “budget” directly against SQLite and inspect the deck and spreadsheet source locations. Feed the parser a malformed PDF and verify a `failed` row with zero indexed passages. Simulate an interrupted job and confirm that a restart preserves ready files and explains the interrupted one.

### D. Show uploads and status in Launch

Add a **Documents** section below **Members**. The proposed control accepts one file per submission. It sends the tab’s existing demo identity. The document list loads on entry and after upload. While it contains processing rows, refresh it once per second after the previous request finishes. Stop polling when every row has reached a final state or the user leaves the view. Bob can refresh his tab to see Alice’s uploads. Cross-tab change polling is scheduled for checkpoint 4.

```tsx
async function uploadFile(file: File, demoUser: string) {
  const body = new FormData()
  body.append('file', file)
  const response = await fetch('/api/workspaces/launch/documents', {
    method: 'POST', headers: { 'X-Demo-User': demoUser }, body,
  })
  if (!response.ok) throw new Error(await uploadErrorMessage(response))
  return response.json()
}

// Inside the Documents section
<ul aria-label="Workspace documents">
  {documents.map(doc => (
    <li key={doc.id}>
      <strong>{doc.filename}</strong> · {doc.status}
      {doc.error && <p>{doc.error}</p>}
    </li>
  ))}
</ul>
```

The form would label the file picker, enable **Upload** after selection, and disable it while the request is in flight. A rejected request shows an error beside the form. An accepted file that fails extraction keeps its own list entry and error. New backend dependencies would be `python-multipart`, `pypdf`, `python-pptx`, and `openpyxl`.

## POC vs. production

Checkpoint 1 demonstrated the two-user workspace. Both designs below are proposals for ingestion. In either design, Alice should see **ready** only when Bob can retrieve the complete indexed version with its source locations.

| Feature | Proposed local demo | Proposed production design and rationale |
| --- | --- | --- |
| **A · Upload** | FastAPI receives the whole upload and saves it on the API machine. A dropped connection means Alice sends the file again. | Authenticate Alice, check workspace membership and quota, then issue short-lived permissions for one generated object key. Her browser uploads parts directly to private object storage and retries interrupted parts. A stateless API can serve other users during a 5 GB transfer. On completion, recheck membership and verify the stored size and checksum before accepting the document. Expire abandoned uploads. [Multipart upload and checksums](https://docs.aws.amazon.com/AmazonS3/latest/userguide/mpuoverview.html) |
| **B · Extraction** | A parser runs in the API process, and the worker holds the fixture’s extracted passages in memory before writing them. | Run parsers in separate workers with per-format memory, temporary-disk, expanded-size, and time limits. Write passages in bounded batches with their page, slide, or sheet and row. Limit concurrent jobs per workspace so one large workbook cannot occupy every worker. Accepting a 5 GB upload and successfully parsing that format at 5 GB are separate capabilities to test. |
| **C · Jobs and indexing** | A FastAPI background task commits passages and the ready flag together in SQLite FTS5. An interrupted task asks Alice to upload again. | Commit the document and a pending job in one database transaction. A durable worker can retry from the stored original after a crash. Give each passage a unique key within its document version, stage batches, then publish the completed version atomically. Start with managed PostgreSQL and a full-text index. A separate search service adds another copy to synchronize and is worth evaluating if measured search latency during ingestion misses the target. [Queue redelivery](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/standard-queues-at-least-once-delivery.html) · [PostgreSQL text-search indexes](https://www.postgresql.org/docs/current/textsearch-indexes.html) |
| **D · Status and collaboration** | Alice’s tab polls the list while a file is processing. Bob refreshes to see the result. | Page the initial document list. Send committed changes over an authorized Server-Sent Events connection with a replay cursor. Bob can reconnect and catch up without fetching a million-document list. Recheck access on reconnect and close active subscriptions when membership is revoked. Size the service using peak connected users and events per busy workspace within the 100k-user population. |

### How to validate the production design

| Exercise | Evidence to collect |
| --- | --- |
| Search one workspace containing one million documents while concurrent 5 GB uploads and a report run are in progress. Record format mix, passage count, upload concurrency, and active clients. | Compare baseline and loaded p95 search latency. Measure upload-complete-to-searchable time, queue wait, peak worker memory and temporary disk by format, and time until Bob sees **ready**. Set latency and resource budgets before running the test. |
| Disconnect Alice midway through a transfer. Kill a worker after it writes a passage batch, then deliver the same job again. | Only missing upload parts are resent. The verified original produces one complete visible version with correct source locations. A parser limit produces a readable failure and releases its resources. |
| Disconnect Bob while a file finishes, then reconnect him. Repeat after removing his membership. | An authorized Bob catches up from his cursor. A revoked Bob loses access to document metadata, contents, and subsequent events. |

These are proposed production tests. Capacity figures and latency targets need measurements before they can become product commitments. Checkpoint 2 approval covers the local A–D code previews above.

## Your hands-on test after implementation

1. **As Alice, upload the three fixtures.** Each filename should reach **ready**. Small files may finish before the first status refresh.
2. **Upload the same PDF again.** Select `launch-brief.pdf` and click **Upload** a second time. You should see two separate ready entries for that filename.
3. **Upload the supplied failure fixture.** Choose `fixtures/broken.pdf` and click **Upload**. It should reach **failed** with “Could not read this PDF.” The four valid uploads should stay ready.
4. **Refresh Bob’s tab.** Bob should see the same five entries, including the error, while the page still says **Viewing as Bob**. Refresh Alice’s tab and confirm the results persist.

## Verification record

The build passed. In a separate test workspace, the browser showed the deck move from processing to ready and Bob saw it after refreshing. Anonymous and nonmember API requests were denied, concurrent uploads preserved distinct originals, and a failed parse produced zero indexed passages. Restarting the test API preserved completed results and marked a simulated interrupted job as failed with instructions to upload again.

| Test upload | Document ID from isolated verification | Indexed result |
| --- | --- | --- |
| Launch brief | `6d93afafbcca4c3f883f1e6a4f80c2c4` | Page 1 |
| Second copy of Launch brief | `51d2dcffb6ca4686af3af17027592e1a` | Independent copy of page 1 |
| Launch deck | `cbc570e0378c4befaaad4f0e715ba3d3` | $120,000 on slide 2 |
| Launch budget | `880e2e5e96b74f95a01b4cd087bfbc92` | Budget rows 2, 3, and 4 contain 80000, 40000, and 120000 |
| Broken PDF | `0a77cf61a37b48098ef9778668009c0d` | Failed, zero passages |

The live demo was empty at handoff. After uploading, you can inspect your own generated IDs, text, and locations using this read-only command from the repository root.

```sh
sqlite3 -readonly -header backend/data/workspace.sqlite3 <<'SQL'
SELECT d.filename, d.id, d.status, p.location, p.text
FROM documents AS d
LEFT JOIN document_passages AS p ON p.document_id = d.id
WHERE d.workspace_id = 'launch'
ORDER BY d.uploaded_at, d.id, p.rowid;
SQL
```

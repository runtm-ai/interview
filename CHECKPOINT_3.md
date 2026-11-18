# Checkpoint 3 — Ask a question and verify the answer

**Awaiting your review.** Bob opens Launch, asks “What is the launch budget?”, and sees excerpts from the deck and spreadsheet. He can open either citation to check its source, repeat the question against one file, and refresh without losing the conversation. Alice sees the same conversation after refreshing her tab. Reports, pagination, and live cross-tab updates belong to checkpoint 4.

| Decision | Feature | What you should see |
| --- | --- | --- |
| A | Choose the search scope | Start with **All ready documents** or choose specific uploads. |
| B | Retrieve and rank matching passages | The budget question finds slide 2 and Budget row 4. An unrelated query gets an explicit no-match result. |
| C | Answer with verifiable citations | Each excerpt identifies a file and opens the actual indexed page, slide, or row text. |
| D | Save shared chat history | Bob’s questions, selected scope, answers, and citations survive refresh and appear for Alice. |

Build order is A → B → C → D. The code below is a review preview. Existing inputs are the checkpoint 2 `documents` and `document_passages` tables and the existing `require_launch_member` check. The proposed endpoints are under `/api/workspaces/launch`.

## A. Choose documents and enforce the scope

Reuse the document list that already updates after an upload. The chat composer offers **All ready documents** and **Selected documents**. In selected mode, Bob can check one or more ready uploads. Use document IDs as values and show an upload timestamp or short ID beside duplicate filenames. Disable **Ask** for an empty question, an empty selection, or a workspace with no ready files.

```tsx
const ready = documents.filter(doc => doc.status === 'ready')
const documentIds = scope === 'all' ? null : checkedIds
const canAsk = question.trim().length > 0 && ready.length > 0 &&
  (documentIds === null || documentIds.length > 0) && !submitting

// POST /api/workspaces/launch/messages with the tab's X-Demo-User header
const body = { question: question.trim(), document_ids: documentIds, request_id: requestId }
```

On the server, `null` means all ready documents in the authorized workspace at submission time. An explicit empty list is a validation error. Validate every supplied ID inside the same transaction as retrieval. A missing, failed, processing, or foreign ID rejects the whole selection with the same message. This also covers a selection that became stale while Bob was composing.

```python
def validate_scope(db, workspace_id, ids):
    if ids is None:
        return None
    selected = sorted(set(ids))
    if not selected:
        raise HTTPException(422, "Choose at least one ready document.")
    rows = db.execute("""
        SELECT id FROM documents
        WHERE workspace_id = ? AND status = 'ready'
          AND id IN (SELECT value FROM json_each(?))
    """, (workspace_id, json.dumps(selected)))
    if {row["id"] for row in rows} != set(selected):
        raise HTTPException(422, "One or more selected documents are unavailable.")
    return selected
```

**Production comparison.** The demo resolves a seeded identity from a header and offers a short in-memory list. Production would derive identity from an authenticated session, page or search the picker, and enforce current workspace and file permissions on question, history, and citation reads. Test revocation between opening the picker and submitting, and again between reading an answer and opening its citation.

## B. Rank passages and handle no matches

Proposed retrieval is key-free and deterministic. Split the question into literal words, discard common question words, and require the remaining terms to occur in the same indexed passage. Rank matches with SQLite FTS5 BM25 and return up to five. This preserves the checkpoint 2 page, slide, and row boundaries. Requiring all terms makes the rule easy to test, though synonyms and questions spanning several rows can miss relevant evidence. [SQLite FTS5 ranking](https://www.sqlite.org/fts5.html#the_bm25_function)

```python
words = re.findall(r"[^\W_]+", question.casefold())
stopwords = {"a", "an", "are", "is", "of", "the", "what", "where", "which"}
terms = dict.fromkeys(word for word in words if word not in stopwords)
expression = " AND ".join(f'"{term}"' for term in terms)
```

```sql
SELECT p.rowid AS passage_id, d.id AS document_id, d.filename, p.location,
       snippet(document_passages, 2, '', '', ' … ', 28) AS excerpt
FROM document_passages AS p
JOIN documents AS d ON d.id = p.document_id
WHERE document_passages MATCH :expression
  AND d.workspace_id = :workspace AND d.status = 'ready'
  AND (:selection IS NULL OR d.id IN (SELECT value FROM json_each(:selection)))
ORDER BY bm25(document_passages), d.id, p.rowid
LIMIT 5;
```

Bind `:selection` as SQL NULL or a JSON array of validated IDs. Skip the query for an empty expression and ask Bob to enter a search term. An actual search with zero hits returns **“No matching passages in the selected documents.”** with zero citations. If there are no ready files, prompt Bob to upload a document before asking.

**Production comparison.** Start with permission-scoped PostgreSQL full-text search and a GIN index. Measure p95 search latency while ingesting documents in a million-document workspace. Evaluate retrieval on labeled questions, including paraphrases, unrelated questions, and totals beside line items. Consider hybrid keyword and semantic retrieval if it improves the fraction of questions whose correct source appears in the top five at an acceptable latency and cost. [PostgreSQL text-search indexes](https://www.postgresql.org/docs/current/textsearch-indexes.html)

## C. Show an answer Bob can check

The proposed answer is a numbered list of matching excerpts in rank order. For example, the deck supplies **“The launch budget is $120,000.”** and the spreadsheet supplies **“Launch budget total | 120000”**. Display the source wording, including numeric formatting. Clicking **launch-deck.pptx · slide 2** opens its indexed slide text inline. A spreadsheet citation displays **Budget · row 4**. This uses the text already extracted in checkpoint 2 and works without an API key or a document viewer.

```python
citations = [
    {"document_id": hit["document_id"], "passage_id": hit["passage_id"],
     "filename": hit["filename"], "location": json.loads(hit["location"]),
     "excerpt": hit["excerpt"]}
    for hit in hits
]
```

```tsx
<li>
  <blockquote>{citation.excerpt}</blockquote>
  <button onClick={() => openPassage(citation.document_id, citation.passage_id)}>
    {citation.filename} · {formatLocation(citation.location)}
  </button>
</li>
```

The source button would call `GET /documents/{document_id}/passages/{passage_id}` under the workspace route. After checking membership, bind **all three** identifiers when fetching the text. Return the same 404 for mismatched or inaccessible sources.

```sql
SELECT p.text, p.location FROM document_passages AS p
JOIN documents AS d ON d.id = p.document_id
WHERE d.workspace_id = ? AND d.status = 'ready'
  AND d.id = ? AND p.rowid = ?;
```

**Production comparison.** Cite an immutable document version and stable passage identifier so reindexing or replacing a file cannot point an old answer at different text. A source viewer could open the original at the highlighted location. If model-written synthesis is added, evaluate every material claim against its cited evidence, including wrong totals and conflicting versions. Test opening an old citation after replacement, deletion, and permission changes.

## D. Persist the shared conversation

Use one SQLite row per exchange. Store the question, server-resolved author, requested scope, outcome, and citation excerpts together. The displayed answer can be reconstructed from that row after restart without rerunning search against a changed index.

```sql
CREATE TABLE IF NOT EXISTS chat_exchanges (
    id INTEGER PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id),
    author_id TEXT NOT NULL REFERENCES users(id),
    request_id TEXT NOT NULL,
    question TEXT NOT NULL,
    selected_ids_json TEXT,
    outcome TEXT NOT NULL CHECK (outcome IN ('matches', 'no_matches')),
    citations_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (workspace_id, author_id, request_id)
);
```

```python
# POST /messages — abbreviated transaction
with closing(connect()) as db, db:
    db.execute("BEGIN IMMEDIATE")
    viewer, workspace = require_launch_member(db, demo_user)
    previous = find_submission(db, workspace["id"], viewer.id, body.request_id)
    if previous:
        return replay_same_request_or_conflict(previous, body)
    selection = validate_scope(db, workspace["id"], body.document_ids)
    hits = search_ready_passages(db, workspace["id"], selection, body.question)
    return save_exchange(db, workspace["id"], viewer.id, body, selection, hits)
```

Generate a request ID for each intentional submission and reuse it on a network retry. A duplicate request with the same payload returns its saved result. Reuse with different content returns a conflict. `GET /messages` rechecks membership and returns Launch exchanges in ascending ID order. Load history on entry and after sending. Retain the draft and surface an error if sending fails. Refreshing Alice’s tab reloads history. Automatic delivery to an already-open tab is scheduled for checkpoint 4.

**Production comparison.** A SQLite write transaction is sufficient for a short local query. In production, keep search outside a long write lock, recheck authorization when saving, and use a durable idempotency key to handle concurrent retries. Page history using a cursor and push committed changes to authorized subscribers. Test simultaneous sends, lost acknowledgments, reconnects, and revocation. Measure duplicate exchanges, missing events, and time until another member sees a committed message.

## Exactly what to test after implementation

Use a workspace with the three valid launch fixtures ready. If this workspace has no uploads, upload those fixtures first.

| Action | Expected result |
| --- | --- |
| As Bob, leave **All ready documents** selected and ask **What is the launch budget?** | The excerpts include the $120,000 figure on deck slide 2 and the 120000 total on Budget row 4. Open both citations and compare the text. |
| Select only **launch-budget.xlsx** and repeat the question. | The new answer cites Budget row 4. Every citation on that answer belongs to the spreadsheet. The earlier answer keeps its original sources. |
| With the spreadsheet selected, ask **quasarpenguin**. | The explicit no-match message appears with zero citations. |
| Select only **launch-brief.pdf** and ask **objective**. | Open the page 1 citation and verify the objective describes driving qualified sign-ups. |
| Refresh Bob’s tab, then Alice’s. | Both show Bob’s four exchanges in the same order, including the no-match response and original citations. |

During implementation review I’ll also test a direct request with a foreign document ID, a citation with mismatched document and passage IDs, an empty selection, duplicate submissions, and persistence after an API restart. These checks use an isolated database.

**Review decision.** Approve A–D together, or name any feature to change or decline. The production comparisons are design proposals. Implementation awaits your approval.

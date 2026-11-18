import json
import logging
import os
import shutil
import sqlite3
from contextlib import asynccontextmanager, closing
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Annotated, BinaryIO, Literal
from uuid import uuid4

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Response, UploadFile
from openpyxl import load_workbook
from pptx import Presentation
from pydantic import BaseModel
from pypdf import PdfReader

DATABASE_PATH = Path(
    os.environ.get(
        "WORKSPACE_DB_PATH",
        Path(__file__).resolve().parent / "data" / "workspace.sqlite3",
    ),
)
WORKSPACE_ID = "launch"
DEMO_USERS = (("alice", "Alice"), ("bob", "Bob"))
logger = logging.getLogger(__name__)
DemoUser = Annotated[str | None, Header(alias="X-Demo-User")]


class User(BaseModel):
    id: str
    name: str


class WorkspaceView(BaseModel):
    id: str
    name: str
    viewing_user: User
    members: list[User]


class Document(BaseModel):
    id: str
    workspace_id: str
    uploader_id: str
    filename: str
    uploaded_at: str
    status: Literal["processing", "ready", "failed"]
    error: str | None


def connect() -> sqlite3.Connection:
    db = sqlite3.connect(DATABASE_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


def initialize_database() -> None:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with closing(connect()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL
            )
            """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS workspaces (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL
            )
            """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS memberships (
                workspace_id TEXT NOT NULL REFERENCES workspaces(id),
                user_id TEXT NOT NULL REFERENCES users(id),
                PRIMARY KEY (workspace_id, user_id)
            )
            """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL REFERENCES workspaces(id),
                uploader_id TEXT NOT NULL REFERENCES users(id),
                filename TEXT NOT NULL,
                uploaded_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                status TEXT NOT NULL CHECK (status IN ('processing', 'ready', 'failed')),
                error TEXT
            )
            """)
        db.execute("""
            CREATE INDEX IF NOT EXISTS documents_by_workspace
            ON documents (workspace_id, uploaded_at DESC, id DESC)
            """)
        db.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS document_passages USING fts5(
                document_id UNINDEXED, location UNINDEXED, text
            )
            """)
        db.execute("""
            UPDATE documents
            SET status = 'failed', error = 'Processing was interrupted. Upload the file again.'
            WHERE status = 'processing'
            """)
        db.executemany(
            "INSERT INTO users (id, name) VALUES (?, ?) ON CONFLICT (id) DO NOTHING",
            DEMO_USERS,
        )
        db.execute(
            "INSERT INTO workspaces (id, name) VALUES (?, ?) ON CONFLICT (id) DO NOTHING",
            (WORKSPACE_ID, "Launch"),
        )
        db.executemany(
            """
            INSERT INTO memberships (workspace_id, user_id) VALUES (?, ?)
            ON CONFLICT (workspace_id, user_id) DO NOTHING
            """,
            ((WORKSPACE_ID, user_id) for user_id, _ in DEMO_USERS),
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    initialize_database()
    yield


app = FastAPI(title="Collaborative Workspace", lifespan=lifespan)


def require_launch_member(db: sqlite3.Connection, demo_user: str | None) -> tuple[User, sqlite3.Row]:
    viewer = db.execute(
        "SELECT id, name FROM users WHERE id = ?", (demo_user,),
    ).fetchone()
    if viewer is None:
        raise HTTPException(401, "Select a valid demo identity.")

    workspace = db.execute(
        """
        SELECT workspaces.id, workspaces.name
        FROM workspaces
        JOIN memberships ON memberships.workspace_id = workspaces.id
        WHERE workspaces.id = ? AND memberships.user_id = ?
        """,
        (WORKSPACE_ID, viewer["id"]),
    ).fetchone()
    if workspace is None:
        raise HTTPException(403, "You do not have access to this workspace.")
    return User(**dict(viewer)), workspace


def authorize_upload(demo_user: DemoUser = None) -> User:
    with closing(connect()) as db, db:
        db.execute("BEGIN")
        viewer, _ = require_launch_member(db, demo_user)
    return viewer


@app.get("/api/workspaces/launch")
def read_launch_workspace(
    response: Response,
    demo_user: DemoUser = None,
) -> WorkspaceView:
    with closing(connect()) as db, db:
        db.execute("BEGIN")
        viewer, workspace = require_launch_member(db, demo_user)

        members = db.execute(
            """
            SELECT users.id, users.name
            FROM memberships
            JOIN users ON users.id = memberships.user_id
            WHERE memberships.workspace_id = ?
            ORDER BY users.name, users.id
            """,
            (workspace["id"],),
        ).fetchall()

    response.headers["Cache-Control"] = "no-store"
    return WorkspaceView(
        id=workspace["id"],
        name=workspace["name"],
        viewing_user=viewer,
        members=[User(**dict(member)) for member in members],
    )


def pdf_passages(path: Path):
    with path.open("rb") as source:
        for page, item in enumerate(PdfReader(source).pages, start=1):
            text = (item.extract_text() or "").strip()
            if text:
                yield {"page": page}, text


def pptx_passages(path: Path):
    for slide, item in enumerate(Presentation(path).slides, start=1):
        text = "\n".join(shape.text for shape in item.shapes if shape.has_text_frame).strip()
        if text:
            yield {"slide": slide}, text


def xlsx_passages(path: Path):
    with closing(load_workbook(path, read_only=True, data_only=True)) as book:
        for sheet in book.worksheets:
            for row, cells in enumerate(sheet.values, start=1):
                values = (str(value).strip() for value in cells if value is not None)
                text = " | ".join(value for value in values if value)
                if text:
                    yield {"sheet": sheet.title, "row": row}, text


EXTRACTORS = {
    ".pdf": (pdf_passages, "PDF"),
    ".pptx": (pptx_passages, "PowerPoint"),
    ".xlsx": (xlsx_passages, "Excel file"),
}


def mark_failed(document_id: str, message: str) -> None:
    with closing(connect()) as db, db:
        db.execute(
            "UPDATE documents SET status = 'failed', error = ? WHERE id = ? AND status = 'processing'",
            (message, document_id),
        )


def index_document(document_id: str, path: Path) -> None:
    extract, format_name = EXTRACTORS[path.suffix]
    try:
        passages = list(extract(path))
    except Exception:
        logger.exception("Could not extract document %s", document_id)
        mark_failed(document_id, f"Could not read this {format_name}.")
        return

    if not passages:
        mark_failed(document_id, "No readable text was found in this file.")
        return

    try:
        with closing(connect()) as db, db:
            updated = db.execute(
                "UPDATE documents SET status = 'ready' WHERE id = ? AND status = 'processing'",
                (document_id,),
            )
            if updated.rowcount:
                db.executemany(
                    "INSERT INTO document_passages (document_id, location, text) VALUES (?, ?, ?)",
                    ((document_id, json.dumps(location), text) for location, text in passages),
                )
    except sqlite3.Error:
        logger.exception("Could not index document %s", document_id)
        mark_failed(document_id, "Could not index this file. Upload the file again.")


def save_upload(source: BinaryIO, path: Path, document_id: str, filename: str, member: User) -> Document:
    temporary_path = None
    moved = False
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(dir=path.parent, suffix=".part", delete=False) as temporary:
            temporary_path = Path(temporary.name)
            shutil.copyfileobj(source, temporary)
        with closing(connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            require_launch_member(db, member.id)
            if path.exists():
                raise FileExistsError(path)
            temporary_path.rename(path)
            moved = True
            row = db.execute(
                """
                INSERT INTO documents (id, workspace_id, uploader_id, filename, status)
                VALUES (?, ?, ?, ?, 'processing')
                RETURNING *
                """,
                (document_id, WORKSPACE_ID, member.id, filename),
            ).fetchone()
            document = Document(**dict(row))
        return document
    except Exception:
        if moved:
            path.unlink(missing_ok=True)
        raise
    finally:
        if temporary_path is not None and not moved:
            temporary_path.unlink(missing_ok=True)


@app.post("/api/workspaces/launch/documents", status_code=202)
def upload_document(
    file: UploadFile,
    tasks: BackgroundTasks,
    member: Annotated[User, Depends(authorize_upload)],
) -> Document:
    filename = Path((file.filename or "").replace("\\", "/")).name
    suffix = Path(filename).suffix.lower()
    if suffix not in EXTRACTORS:
        raise HTTPException(415, "Choose a PDF, PowerPoint (.pptx), or Excel (.xlsx) file.")

    document_id = uuid4().hex
    path = DATABASE_PATH.parent / "uploads" / f"{document_id}{suffix}"
    try:
        document = save_upload(file.file, path, document_id, filename, member)
    except (OSError, sqlite3.Error):
        logger.exception("Could not save document %s", document_id)
        raise HTTPException(500, "Could not save this file. Try uploading it again.") from None
    tasks.add_task(index_document, document_id, path)
    return document


@app.get("/api/workspaces/launch/documents")
def list_documents(response: Response, demo_user: DemoUser = None) -> list[Document]:
    with closing(connect()) as db, db:
        db.execute("BEGIN")
        _, workspace = require_launch_member(db, demo_user)
        documents = db.execute(
            "SELECT * FROM documents WHERE workspace_id = ? ORDER BY uploaded_at DESC, id DESC",
            (workspace["id"],),
        ).fetchall()
    response.headers["Cache-Control"] = "no-store"
    return [Document(**dict(document)) for document in documents]

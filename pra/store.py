"""SQLite 存储层：单文件数据库，方便随论文一起归档复现。"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .schema import Code, Document, now_iso

DEFAULT_DB = Path("data/pra.sqlite3")

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    doc_id      TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    path        TEXT,
    issuer      TEXT,
    doc_number  TEXT,
    date        TEXT,
    level       TEXT,
    region      TEXT,
    domain      TEXT,
    url         TEXT,
    text        TEXT NOT NULL,
    sha256      TEXT,
    created_at  TEXT
);

CREATE TABLE IF NOT EXISTS codes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id      TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    category    TEXT NOT NULL,
    subcategory TEXT NOT NULL,
    evidence    TEXT,
    span_start  INTEGER DEFAULT -1,
    span_end    INTEGER DEFAULT -1,
    method      TEXT,
    model       TEXT,
    confidence  REAL,
    coder       TEXT,
    note        TEXT,
    created_at  TEXT
);

CREATE INDEX IF NOT EXISTS idx_codes_doc ON codes(doc_id);
CREATE INDEX IF NOT EXISTS idx_codes_coder ON codes(coder);
CREATE INDEX IF NOT EXISTS idx_docs_domain ON documents(domain);

CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id      TEXT,
    coder       TEXT,
    method      TEXT,
    model       TEXT,
    params      TEXT,
    created_at  TEXT
);
"""


def connect(db_path: str | Path = DEFAULT_DB) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def upsert_document(conn: sqlite3.Connection, doc: Document) -> None:
    import hashlib

    conn.execute(
        """
        INSERT INTO documents (doc_id, title, path, issuer, doc_number, date, level,
                               region, domain, url, text, sha256, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(doc_id) DO UPDATE SET
            title=excluded.title, path=excluded.path, issuer=excluded.issuer,
            doc_number=excluded.doc_number, date=excluded.date, level=excluded.level,
            region=excluded.region, domain=excluded.domain, url=excluded.url,
            text=excluded.text, sha256=excluded.sha256
        """,
        (
            doc.doc_id, doc.title, doc.path, doc.issuer, doc.doc_number, doc.date,
            doc.level, doc.region, doc.domain, doc.url, doc.text,
            hashlib.sha256(doc.text.encode("utf-8")).hexdigest(), now_iso(),
        ),
    )
    conn.commit()


def list_documents(conn: sqlite3.Connection, domain: str | None = None) -> list[sqlite3.Row]:
    sql = "SELECT doc_id, title, issuer, doc_number, date, level, region, domain, url, length(text) AS n_chars FROM documents"
    args: tuple = ()
    if domain:
        sql += " WHERE domain = ?"
        args = (domain,)
    sql += " ORDER BY date DESC"
    return conn.execute(sql, args).fetchall()


def get_document(conn: sqlite3.Connection, doc_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM documents WHERE doc_id = ?", (doc_id,)).fetchone()


def log_run(conn, coder: str, method: str, model: str = "", doc_id: str = "", params: dict | None = None):
    conn.execute(
        "INSERT INTO runs (doc_id, coder, method, model, params, created_at) VALUES (?,?,?,?,?,?)",
        (doc_id, coder, method, model, json.dumps(params or {}, ensure_ascii=False), now_iso()),
    )
    conn.commit()


def replace_codes(conn: sqlite3.Connection, doc_id: str, coder: str, codes: list[Code]) -> int:
    """替换某个 (doc, coder) 下的全部编码，保证重复运行幂等。"""
    conn.execute("DELETE FROM codes WHERE doc_id = ? AND coder = ?", (doc_id, coder))
    rows = []
    for c in codes:
        rows.append((
            c.doc_id, c.category, c.subcategory, c.evidence, c.span_start, c.span_end,
            c.method, c.model, c.confidence, c.coder, c.note, c.created_at or now_iso(),
        ))
    conn.executemany(
        """INSERT INTO codes (doc_id, category, subcategory, evidence, span_start, span_end,
                              method, model, confidence, coder, note, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        rows,
    )
    conn.commit()
    return len(rows)


def get_codes(conn, doc_id: str | None = None, coder: str | None = None) -> list[sqlite3.Row]:
    sql = """SELECT c.*, d.title FROM codes c JOIN documents d ON d.doc_id = c.doc_id WHERE 1=1"""
    args: list = []
    if doc_id:
        sql += " AND c.doc_id = ?"
        args.append(doc_id)
    if coder:
        sql += " AND c.coder = ?"
        args.append(coder)
    sql += " ORDER BY c.doc_id, c.category, c.subcategory"
    return conn.execute(sql, args).fetchall()


def coders(conn) -> list[str]:
    return [r[0] for r in conn.execute("SELECT DISTINCT coder FROM codes ORDER BY coder")]


def stats(conn) -> dict:
    n_docs = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    n_codes = conn.execute("SELECT COUNT(*) FROM codes").fetchone()[0]
    n_coded_docs = conn.execute("SELECT COUNT(DISTINCT doc_id) FROM codes").fetchone()[0]
    return {"documents": n_docs, "codes": n_codes, "coded_documents": n_coded_docs}

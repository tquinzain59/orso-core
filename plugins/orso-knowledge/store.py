"""Magasin documentaire par client : ingestion, versions, retrait, recherche FTS5, cloisonnement.

Cloisonnement : un fichier SQLite par client sous ``<racine>/<client>/knowledge.db``. Dans un
conteneur client (``ORSO_CLIENT_ID`` posé par le cycle de vie Olympe), la racine est sur le volume
de ce seul conteneur : l'isolation est portée par le sandbox ; le refus de tout autre identifiant
ci-dessous n'est qu'un garde-fou de code, pas le mécanisme principal.

Index : lexical (SQLite FTS5, local). Aucun tiers de traitement, donc aucune exigence UE / accord de
traitement / réversibilité à ce stade ; le choix d'un fournisseur de vectorisation reste ouvert.
"""

from __future__ import annotations

import hashlib
import os
import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .chunking import extract_text, split_text

TENANT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    doc_key TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('active', 'retired')),
    current_version INTEGER NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS versions (
    doc_key TEXT NOT NULL REFERENCES documents(doc_key),
    version INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    byte_size INTEGER NOT NULL,
    chunk_count INTEGER NOT NULL,
    origin_connector TEXT NOT NULL,
    origin_ref TEXT,
    status TEXT NOT NULL CHECK (status IN ('current', 'superseded', 'retired')),
    ingested_at TEXT NOT NULL,
    PRIMARY KEY (doc_key, version)
);
CREATE TABLE IF NOT EXISTS chunks (
    chunk_id INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_key TEXT NOT NULL,
    version INTEGER NOT NULL,
    ordinal INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS chunks_by_doc ON chunks(doc_key, version);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(text, tokenize='unicode61 remove_diacritics 2');
"""


class TenantRequiredError(ValueError):
    """Aucun client désigné : pas de client par défaut, pour ne jamais mélanger les données."""


class TenantIsolationError(PermissionError):
    """Accès demandé à un autre client que celui lié au conteneur."""


class UnknownDocumentError(KeyError):
    pass


def resolve_tenant(requested: str | None = None) -> str:
    bound = os.environ.get("ORSO_CLIENT_ID", "").strip()
    if requested and bound and requested != bound:
        raise TenantIsolationError(
            f"accès refusé : client {requested!r} différent du client lié à ce conteneur"
        )
    tenant = requested or bound
    if not tenant:
        raise TenantRequiredError("client non désigné (option explicite ou ORSO_CLIENT_ID)")
    if not TENANT_RE.match(tenant):
        raise ValueError(f"identifiant client invalide : {tenant!r}")
    return tenant


def default_root() -> Path:
    from hermes_constants import get_hermes_home

    return get_hermes_home() / "knowledge"


@dataclass(frozen=True)
class Passage:
    doc_key: str
    title: str
    version: int
    ordinal: int
    text: str
    score: float
    origin_connector: str
    origin_ref: str | None

    @property
    def citation(self) -> str:
        return f"[Source: {self.title}, v{self.version}, §{self.ordinal}]"


@dataclass(frozen=True)
class IngestResult:
    doc_key: str
    version: int
    status: str  # "created" | "updated" | "unchanged"
    chunk_count: int


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _fts_query(query: str) -> str:
    tokens = [t for t in re.findall(r"\w+", query, re.UNICODE) if len(t) > 1]
    return " OR ".join(f'"{t}"' for t in tokens)


class KnowledgeStore:
    def __init__(self, root: Path | str | None = None, tenant: str | None = None) -> None:
        self.tenant = resolve_tenant(tenant)
        base = Path(root) if root is not None else default_root()
        self.path = base / self.tenant / "knowledge.db"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as db, db:
            db.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        return db

    def ingest(
        self,
        name: str,
        data: bytes,
        *,
        origin_connector: str = "upload",
        origin_ref: str | None = None,
        doc_key: str | None = None,
    ) -> IngestResult:
        """Ingère ``data``. Même ``doc_key`` + contenu identique : aucune nouvelle version. Contenu
        différent : nouvelle version, l'ancienne sort de l'index (la dernière fait foi) mais sa
        trace reste dans ``versions``. Un document retiré redevient actif en repartant d'une version
        supérieure."""
        key = doc_key or name
        text = extract_text(name, data)
        chunks = split_text(text)
        if not chunks:
            raise ValueError(f"{name!r} ne contient aucun texte indexable")
        digest = hashlib.sha256(data).hexdigest()
        title = name.replace("[", "(").replace("]", ")")
        with closing(self._connect()) as db, db:
            row = db.execute(
                "SELECT status, current_version FROM documents WHERE doc_key = ?", (key,)
            ).fetchone()
            if row is not None and row["status"] == "active":
                same = db.execute(
                    "SELECT 1 FROM versions WHERE doc_key = ? AND version = ? AND sha256 = ?",
                    (key, row["current_version"], digest),
                ).fetchone()
                if same:
                    return IngestResult(key, row["current_version"], "unchanged", len(chunks))
            version = (row["current_version"] + 1) if row is not None else 1
            if row is not None:
                self._drop_from_index(db, key, "superseded")
            db.execute(
                "INSERT INTO documents (doc_key, title, status, current_version, updated_at) "
                "VALUES (?, ?, 'active', ?, ?) ON CONFLICT(doc_key) DO UPDATE SET "
                "title = excluded.title, status = 'active', "
                "current_version = excluded.current_version, updated_at = excluded.updated_at",
                (key, title, version, _now()),
            )
            db.execute(
                "INSERT INTO versions (doc_key, version, sha256, byte_size, chunk_count, "
                "origin_connector, origin_ref, status, ingested_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 'current', ?)",
                (key, version, digest, len(data), len(chunks), origin_connector, origin_ref, _now()),
            )
            for chunk in chunks:
                cur = db.execute(
                    "INSERT INTO chunks (doc_key, version, ordinal) VALUES (?, ?, ?)",
                    (key, version, chunk.ordinal),
                )
                db.execute(
                    "INSERT INTO chunks_fts (rowid, text) VALUES (?, ?)", (cur.lastrowid, chunk.text)
                )
        return IngestResult(key, version, "created" if version == 1 else "updated", len(chunks))

    @staticmethod
    def _drop_from_index(db: sqlite3.Connection, key: str, new_status: str) -> None:
        ids = [r[0] for r in db.execute("SELECT chunk_id FROM chunks WHERE doc_key = ?", (key,))]
        db.executemany("DELETE FROM chunks_fts WHERE rowid = ?", [(i,) for i in ids])
        db.execute("DELETE FROM chunks WHERE doc_key = ?", (key,))
        db.execute(
            "UPDATE versions SET status = ? WHERE doc_key = ? AND status = 'current'",
            (new_status, key),
        )

    def retire(self, doc_key: str) -> None:
        with closing(self._connect()) as db, db:
            row = db.execute(
                "SELECT status FROM documents WHERE doc_key = ?", (doc_key,)
            ).fetchone()
            if row is None:
                raise UnknownDocumentError(doc_key)
            self._drop_from_index(db, doc_key, "retired")
            db.execute(
                "UPDATE documents SET status = 'retired', updated_at = ? WHERE doc_key = ?",
                (_now(), doc_key),
            )

    def search(self, query: str, limit: int = 5) -> list[Passage]:
        match = _fts_query(query)
        if not match:
            return []
        with closing(self._connect()) as db:
            rows = db.execute(
                "SELECT c.doc_key, c.version, c.ordinal, f.text, bm25(chunks_fts) AS rank, "
                "d.title, v.origin_connector, v.origin_ref "
                "FROM chunks_fts f JOIN chunks c ON c.chunk_id = f.rowid "
                "JOIN documents d ON d.doc_key = c.doc_key AND d.status = 'active' "
                "AND d.current_version = c.version "
                "JOIN versions v ON v.doc_key = c.doc_key AND v.version = c.version "
                "WHERE chunks_fts MATCH ? ORDER BY rank LIMIT ?",
                (match, limit),
            ).fetchall()
        return [
            Passage(r["doc_key"], r["title"], r["version"], r["ordinal"], r["text"], -r["rank"],
                    r["origin_connector"], r["origin_ref"])
            for r in rows
        ]

    def history(self, doc_key: str) -> list[dict]:
        with closing(self._connect()) as db:
            rows = db.execute(
                "SELECT version, sha256, byte_size, chunk_count, origin_connector, origin_ref, "
                "status, ingested_at FROM versions WHERE doc_key = ? ORDER BY version",
                (doc_key,),
            ).fetchall()
        if not rows:
            raise UnknownDocumentError(doc_key)
        return [dict(r) for r in rows]

    def documents(self) -> list[dict]:
        with closing(self._connect()) as db:
            rows = db.execute(
                "SELECT doc_key, title, status, current_version, updated_at FROM documents "
                "ORDER BY doc_key"
            ).fetchall()
        return [dict(r) for r in rows]

    def has_active_documents(self) -> bool:
        with closing(self._connect()) as db:
            return db.execute("SELECT 1 FROM documents WHERE status = 'active' LIMIT 1").fetchone() is not None

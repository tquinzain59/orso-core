"""Traces de haut niveau des exécutions, exposées au client (KAN-128).

Ce que ce module porte (à la marge du moteur, sans toucher à ``run_agent.py`` ni aux
``agent/turn_*.py``) :
- CA1 : une exécution produit une trace datée (étapes de haut niveau + artefacts) consultable
  par le client via ``/api/client/runs``.
- CA3 : frontière client / cockpit. Le client ne voit que des étapes tirées d'un vocabulaire
  FERMÉ (``STEP_CATALOG``) et aucun identifiant interne (tenant, utilisateur, session, profil,
  modèle, outil). Les erreurs techniques vont dans ``client_run_internal`` (cockpit
  d'exploitation uniquement, lu par :func:`read_internal_diagnostics`, jamais par le routeur).
- CA4 : conservation de 30 jours puis purge réelle (:func:`purge_expired_traces`).
- CA5 : aucun secret en clair (:func:`scrub_secrets`), les secrets sont désignés par leur
  emplacement (``[SECRET:env:NOM]``) et jamais par leur valeur.

Frontière avec KAN-107 : le journal d'activité métier (actions à effet visible, consultable par
le dirigeant) n'est PAS ici. Ces traces décrivent le déroulé technique de haut niveau d'une
exécution ; elles ne portent pas le détail des actions métier.
"""

from __future__ import annotations

import logging
import os
import re
import sqlite3
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from hermes_cli.dashboard_auth.client_jwt import verify_client_access

_log = logging.getLogger("hermes_cli.client_run_traces")

run_traces_router = APIRouter(tags=["Client Run Traces"])

RETENTION_DAYS = 30.0
RETENTION_SECONDS = RETENTION_DAYS * 86400.0

STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"

# Vocabulaire fermé des étapes visibles du client : une étape hors catalogue est refusée à
# l'enregistrement, ce qui rend impossible la fuite d'une étape interne dans une trace client.
STEP_CATALOG: Dict[str, str] = {
    "run_started": "Exécution démarrée",
    "response_prepared": "Réponse préparée",
    "action_proposed": "Action proposée, en attente de votre validation",
    "run_replayed": "Nouvelle tentative automatique",
    "run_completed": "Exécution terminée",
    "run_failed": "Exécution en échec, signalée",
}
STATUS_LABELS: Dict[str, str] = {
    STATUS_RUNNING: "En cours",
    STATUS_COMPLETED: "Terminée",
    STATUS_FAILED: "Échec signalé",
}
ARTIFACT_KINDS = {"reponse", "action"}
FAILURE_NOTICE = (
    "L'exécution n'a pas pu aboutir malgré plusieurs tentatives automatiques. "
    "Votre équipe d'exploitation a été avertie ; vous pouvez réessayer plus tard."
)

_ARTIFACT_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_ARTIFACT_MAX_CHARS = 200_000


# ── CA5 : aucun secret en clair ──────────────────────────────────────────────

_SECRET_ENV_NAME_RE = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL)", re.IGNORECASE)
_SECRET_PATTERNS = (
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),  # JWT
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{12,}"),
    re.compile(r"\b(?:sk|pk|rk)-[A-Za-z0-9_-]{12,}"),
    re.compile(r"\b(?:ghp|gho|ghs|github_pat|xox[abp])[-_][A-Za-z0-9_-]{12,}"),
    re.compile(
        r"(?i)(?<!\[)\b([A-Za-z0-9_.-]*(?:api[_-]?key|token|secret|passw(?:or)?d|credential)[A-Za-z0-9_.-]*)"
        r"(\s*[:=]\s*)(?!\[SECRET)[\"']?[^\s\"',;]{6,}[\"']?"
    ),
)
_MIN_SECRET_VALUE_LEN = 8
_PLACEHOLDER_RE = re.compile(r"\[SECRET:[^\]]*\]")


def scrub_secrets(text: Optional[str]) -> str:
    """Remplace tout secret par la désignation de son emplacement, jamais par sa valeur.

    1. Valeur identique à celle d'une variable d'environnement secrète -> ``[SECRET:env:NOM]``.
    2. Motifs connus (JWT, Bearer, ``sk-...``, ``cle=valeur``) -> ``[SECRET:masque]``.
    3. Filet de sécurité : ``agent.redact`` en mode forcé.
    """
    if not text:
        return ""
    out = str(text)
    env_secrets = sorted(
        (
            (name, value)
            for name, value in os.environ.items()
            if _SECRET_ENV_NAME_RE.search(name) and len(value or "") >= _MIN_SECRET_VALUE_LEN
        ),
        key=lambda item: len(item[1]),
        reverse=True,
    )
    for name, value in env_secrets:
        out = out.replace(value, f"[SECRET:env:{name}]")
    out = _outside_placeholders(out, _mask_known_patterns)
    return _outside_placeholders(out, _safety_net)


def _outside_placeholders(text: str, fn) -> str:
    """Applique ``fn`` hors des marqueurs déjà posés, pour ne pas ré-attaquer ni déformer ``[SECRET:...]``."""
    parts = _PLACEHOLDER_RE.split(text)
    marks = _PLACEHOLDER_RE.findall(text)
    out = [fn(part) for part in parts]
    merged = []
    for idx, part in enumerate(out):
        merged.append(part)
        if idx < len(marks):
            merged.append(marks[idx])
    return "".join(merged)


def _mask_known_patterns(text: str) -> str:
    for idx, pattern in enumerate(_SECRET_PATTERNS):
        if idx == len(_SECRET_PATTERNS) - 1:
            text = pattern.sub(lambda m: f"{m.group(1)}{m.group(2)}[SECRET:masque]", text)
        else:
            text = pattern.sub("[SECRET:masque]", text)
    return text


def _safety_net(text: str) -> str:
    from agent.redact import redact_sensitive_text

    return redact_sensitive_text(text, force=True)


# ── Stockage ─────────────────────────────────────────────────────────────────


def _db_path() -> Path:
    """Base des traces : à côté du registre des sessions client (même volume de données)."""
    from hermes_cli.web_routers.client_ui import _get_client_sessions_db_path

    return _get_client_sessions_db_path().parent / "client_run_traces.db"


def _connect() -> sqlite3.Connection:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=15.0)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS client_run_traces (
            trace_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            agent_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            status TEXT NOT NULL,
            started_at REAL NOT NULL,
            ended_at REAL,
            replay_count INTEGER NOT NULL DEFAULT 0,
            client_notified_at REAL
        );
        CREATE INDEX IF NOT EXISTS idx_run_traces_lookup
            ON client_run_traces(tenant_id, user_id, started_at DESC);
        CREATE TABLE IF NOT EXISTS client_run_steps (
            trace_id TEXT NOT NULL,
            seq INTEGER NOT NULL,
            at REAL NOT NULL,
            code TEXT NOT NULL,
            PRIMARY KEY (trace_id, seq)
        );
        CREATE TABLE IF NOT EXISTS client_run_artifacts (
            trace_id TEXT NOT NULL,
            name TEXT NOT NULL,
            kind TEXT NOT NULL,
            size_chars INTEGER NOT NULL,
            content TEXT NOT NULL,
            created_at REAL NOT NULL,
            PRIMARY KEY (trace_id, name)
        );
        CREATE TABLE IF NOT EXISTS client_run_internal (
            trace_id TEXT NOT NULL,
            seq INTEGER NOT NULL,
            at REAL NOT NULL,
            attempt INTEGER NOT NULL,
            error_class TEXT NOT NULL,
            error_detail TEXT NOT NULL,
            PRIMARY KEY (trace_id, seq)
        );
        """
    )
    return conn


@contextmanager
def _db():
    """Connexion courte : commit en sortie normale, fermeture systématique."""
    conn = _connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _iso(ts: Optional[float]) -> Optional[str]:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="seconds")


def purge_expired_traces(now: Optional[float] = None, retention_days: float = RETENTION_DAYS) -> int:
    """Purge réelle (toutes tables, y compris le diagnostic cockpit) au-delà de 30 jours (CA4)."""
    cutoff = (time.time() if now is None else now) - retention_days * 86400.0
    with _db() as conn:
        ids = [r[0] for r in conn.execute("SELECT trace_id FROM client_run_traces WHERE started_at < ?", (cutoff,))]
        for table in ("client_run_steps", "client_run_artifacts", "client_run_internal"):
            conn.executemany(f"DELETE FROM {table} WHERE trace_id = ?", [(i,) for i in ids])
        conn.executemany("DELETE FROM client_run_traces WHERE trace_id = ?", [(i,) for i in ids])
        conn.commit()
    if ids:
        _log.info("Purge rétention 30 jours : %d traces d'exécution supprimées.", len(ids))
    return len(ids)


class RunRecorder:
    """Enregistre la trace d'une exécution. L'observabilité ne doit jamais casser le tour client :
    toute erreur de stockage est journalisée côté serveur puis ignorée.
    """

    def __init__(self, tenant_id: str, user_id: str, agent_id: str, session_id: str):
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.trace_id = f"run_{uuid.uuid4().hex[:16]}"
        self._seq = 0
        self._internal_seq = 0
        try:
            purge_expired_traces()
            with _db() as conn:
                conn.execute(
                    "INSERT INTO client_run_traces (trace_id, tenant_id, user_id, agent_id, session_id,"
                    " status, started_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (self.trace_id, tenant_id, user_id, agent_id, session_id, STATUS_RUNNING, time.time()),
                )
                conn.commit()
        except Exception as exc:
            _log.warning("Trace %s non créée: %s", self.trace_id, exc)
        self.step("run_started")

    def _safe(self, what: str, fn) -> None:
        try:
            fn()
        except Exception as exc:
            _log.warning("Trace %s: %s en échec: %s", self.trace_id, what, exc)

    def step(self, code: str) -> None:
        if code not in STEP_CATALOG:
            raise ValueError(f"Étape hors catalogue client: {code!r}")
        self._seq += 1
        seq = self._seq

        def _write() -> None:
            with _db() as conn:
                conn.execute(
                    "INSERT INTO client_run_steps (trace_id, seq, at, code) VALUES (?, ?, ?, ?)",
                    (self.trace_id, seq, time.time(), code),
                )
                if code == "run_replayed":
                    conn.execute(
                        "UPDATE client_run_traces SET replay_count = replay_count + 1 WHERE trace_id = ?",
                        (self.trace_id,),
                    )
                conn.commit()

        self._safe(f"étape {code}", _write)

    def artifact(self, name: str, kind: str, content: str) -> None:
        if not _ARTIFACT_NAME_RE.match(name or ""):
            raise ValueError(f"Nom d'artefact invalide: {name!r}")
        if kind not in ARTIFACT_KINDS:
            raise ValueError(f"Type d'artefact hors catalogue client: {kind!r}")
        clean = scrub_secrets(content)[:_ARTIFACT_MAX_CHARS]

        def _write() -> None:
            with _db() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO client_run_artifacts (trace_id, name, kind, size_chars, content,"
                    " created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (self.trace_id, name, kind, len(clean), clean, time.time()),
                )
                conn.commit()

        self._safe(f"artefact {name}", _write)

    def internal_error(self, attempt: int, error: BaseException) -> None:
        """Détail technique d'un échec : cockpit d'exploitation uniquement (CA3)."""
        self._internal_seq += 1
        seq = self._internal_seq
        detail = scrub_secrets(str(error))[:2000]

        def _write() -> None:
            with _db() as conn:
                conn.execute(
                    "INSERT INTO client_run_internal (trace_id, seq, at, attempt, error_class, error_detail)"
                    " VALUES (?, ?, ?, ?, ?, ?)",
                    (self.trace_id, seq, time.time(), attempt, type(error).__name__, detail),
                )
                conn.commit()

        self._safe("diagnostic interne", _write)

    def finish(self, failed: bool) -> None:
        """Clôt l'exécution. En cas d'échec persistant, le signalement au client est horodaté (CA2)."""
        self.step("run_failed" if failed else "run_completed")
        now = time.time()

        def _write() -> None:
            with _db() as conn:
                conn.execute(
                    "UPDATE client_run_traces SET status = ?, ended_at = ?, client_notified_at = ?"
                    " WHERE trace_id = ?",
                    (STATUS_FAILED if failed else STATUS_COMPLETED, now, now if failed else None, self.trace_id),
                )
                conn.commit()

        self._safe("clôture", _write)


def read_internal_diagnostics(trace_id: str) -> List[Dict[str, Any]]:
    """Lecture réservée au cockpit d'exploitation : erreurs techniques par tentative.

    Volontairement non exposée par le routeur client.
    """
    with _db() as conn:
        rows = conn.execute(
            "SELECT attempt, error_class, error_detail, at FROM client_run_internal WHERE trace_id = ?"
            " ORDER BY seq",
            (trace_id,),
        ).fetchall()
    return [
        {"attempt": r[0], "error_class": r[1], "error_detail": r[2], "at": _iso(r[3])} for r in rows
    ]


# ── Vue client (liste blanche explicite) ─────────────────────────────────────


def _identity(auth: Dict[str, Any]) -> tuple[str, str]:
    user_id = str(auth.get("sub") or auth.get("user_id") or "anonymous").strip()
    tenant = auth.get("tenant") or {}
    tenant_id = str(
        tenant.get("tenant_id") or tenant.get("tenant_slug") or os.environ.get("ORSO_CLIENT_ID", "default")
    ).strip()
    return tenant_id, user_id


def _summary(row: tuple) -> Dict[str, Any]:
    trace_id, agent_id, status, started_at, ended_at, replay_count, notified_at = row
    return {
        "trace_id": trace_id,
        "agent": agent_id,
        "status": status,
        "status_label": STATUS_LABELS.get(status, status),
        "started_at": _iso(started_at),
        "ended_at": _iso(ended_at),
        "replays": replay_count,
        "failure_notice": FAILURE_NOTICE if notified_at is not None else None,
        "expires_at": _iso(started_at + RETENTION_SECONDS),
    }


_SUMMARY_COLUMNS = "trace_id, agent_id, status, started_at, ended_at, replay_count, client_notified_at"


def _fetch_owned_trace(conn: sqlite3.Connection, trace_id: str, tenant_id: str, user_id: str) -> tuple:
    """Trace appartenant à l'appelant et non expirée ; sinon 404 (aucune distinction d'existence)."""
    row = conn.execute(
        f"SELECT {_SUMMARY_COLUMNS} FROM client_run_traces"
        " WHERE trace_id = ? AND tenant_id = ? AND user_id = ? AND started_at >= ?",
        (trace_id, tenant_id, user_id, time.time() - RETENTION_SECONDS),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Trace introuvable ou expirée.")
    return row


def _opportunistic_purge() -> None:
    try:
        purge_expired_traces()
    except Exception as exc:
        _log.warning("Purge opportuniste des traces en échec: %s", exc)


@run_traces_router.get("/api/client/runs")
async def list_client_runs(
    agent_id: Optional[str] = Query(None),
    session_id: Optional[str] = Query(None, description="Filtre : conversation du client"),
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    auth: Dict[str, Any] = Depends(verify_client_access),
):
    """Liste les exécutions du client (30 jours glissants), de la plus récente à la plus ancienne."""
    tenant_id, user_id = _identity(auth)
    _opportunistic_purge()
    query = f"SELECT {_SUMMARY_COLUMNS} FROM client_run_traces WHERE tenant_id = ? AND user_id = ? AND started_at >= ?"
    params: List[Any] = [tenant_id, user_id, time.time() - RETENTION_SECONDS]
    for column, value in (("agent_id", agent_id), ("session_id", session_id), ("status", status)):
        if value:
            query += f" AND {column} = ?"
            params.append(value)
    query += " ORDER BY started_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    with _db() as conn:
        rows = conn.execute(query, params).fetchall()
    return {"runs": [_summary(r) for r in rows], "retention_days": int(RETENTION_DAYS)}


@run_traces_router.get("/api/client/runs/{trace_id}")
async def get_client_run(trace_id: str, auth: Dict[str, Any] = Depends(verify_client_access)):
    """Trace de haut niveau d'une exécution : étapes datées et artefacts (CA1, CA3)."""
    tenant_id, user_id = _identity(auth)
    _opportunistic_purge()
    with _db() as conn:
        row = _fetch_owned_trace(conn, trace_id, tenant_id, user_id)
        steps = conn.execute(
            "SELECT at, code FROM client_run_steps WHERE trace_id = ? ORDER BY seq", (trace_id,)
        ).fetchall()
        artifacts = conn.execute(
            "SELECT name, kind, size_chars, created_at FROM client_run_artifacts WHERE trace_id = ?"
            " ORDER BY created_at, name",
            (trace_id,),
        ).fetchall()
    view = _summary(row)
    view["steps"] = [{"at": _iso(at), "label": STEP_CATALOG.get(code, "Étape")} for at, code in steps]
    view["artifacts"] = [
        {"name": n, "kind": k, "size_chars": s, "created_at": _iso(c)} for n, k, s, c in artifacts
    ]
    return view


@run_traces_router.get("/api/client/runs/{trace_id}/artifacts/{name}")
async def get_client_run_artifact(
    trace_id: str, name: str, auth: Dict[str, Any] = Depends(verify_client_access)
):
    """Contenu d'un artefact de l'exécution (déjà expurgé de tout secret, CA5)."""
    tenant_id, user_id = _identity(auth)
    with _db() as conn:
        _fetch_owned_trace(conn, trace_id, tenant_id, user_id)
        row = conn.execute(
            "SELECT name, kind, content, created_at FROM client_run_artifacts WHERE trace_id = ? AND name = ?",
            (trace_id, name),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Artefact introuvable.")
    return {"name": row[0], "kind": row[1], "content": row[2], "created_at": _iso(row[3])}

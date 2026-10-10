"""Routeur d'historique et de gestion des sessions de chat UI Client (KAN-83).

Ce module implémente la couche d'exposition des conversations pour l'interface client :
- Liste des conversations par tenant, utilisateur et agent (CA1, CA5, CA6)
- Réouverture intégrale avec préservation du contexte et chaîne de compression (CA2, CA3)
- Renommage manuel protégé contre l'écrasement automatique
- Titrage automatique du moteur borné à 6 mots
- Suppression réelle et définitive (CA4)
- Règle de conservation absolue de 60 jours sans exception d'épinglage (CA7)
"""

from __future__ import annotations

import logging
import os
import re
import sqlite3
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from hermes_cli.dashboard_auth.client_jwt import verify_client_access

_log = logging.getLogger("hermes_cli.client_chat_history")

history_router = APIRouter(tags=["Client Chat History"])

RETENTION_MAX_DAYS = 60.0
RETENTION_SECONDS = RETENTION_MAX_DAYS * 86400.0


class SessionUpdateRequest(BaseModel):
    title: Optional[str] = None
    dossier_metier_id: Optional[str] = None
    agent_id: Optional[str] = "jerome"


class ThemeCreateRequest(BaseModel):
    title: Optional[str] = None
    agent_id: Optional[str] = "jerome"


class ThemeUpdateRequest(BaseModel):
    title: str


def _get_deps():
    from hermes_cli.web_routers.client_ui import (
        _find_profile_dir,
        _get_client_sessions_db_path,
        _init_client_sessions_db,
        _verify_and_bind_client_session,
        PROJECT_ROOT,
    )
    return (
        _find_profile_dir,
        _get_client_sessions_db_path,
        _init_client_sessions_db,
        _verify_and_bind_client_session,
        PROJECT_ROOT,
    )


def _init_client_themes_db(conn: sqlite3.Connection) -> None:
    """Initialise la table des thèmes de conversation client (KAN-84)."""
    conn.execute(
        """CREATE TABLE IF NOT EXISTS client_chat_themes (
            theme_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            agent_id TEXT NOT NULL,
            title TEXT NOT NULL,
            title_source TEXT NOT NULL DEFAULT 'auto',
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        );"""
    )
    conn.execute(
        """CREATE INDEX IF NOT EXISTS idx_client_themes_lookup
           ON client_chat_themes(tenant_id, user_id, agent_id, updated_at DESC);"""
    )


def generate_auto_title(prompt: str, max_words: int = 6) -> str:
    """Génère un titre automatique à partir du premier message utilisateur, borné à max_words (KAN-83)."""
    cleaned = re.sub(r"[\r\n\t]+", " ", (prompt or "")).strip()
    words = [w for w in cleaned.split(" ") if w]
    if not words:
        return "Nouvelle discussion"
    if len(words) <= max_words:
        return " ".join(words)
    return " ".join(words[:max_words])


def generate_theme_title(prompt: str, max_words: int = 4) -> str:
    """Génère un nom de thème à partir du message, borné strictement à 4 mots maximum en français (KAN-84)."""
    cleaned = re.sub(r"[\r\n\t]+", " ", (prompt or "")).strip()
    cleaned = re.sub(r"^[^\w\s]+|[^\w\s]+$", "", cleaned)
    words = [w for w in cleaned.split(" ") if w]
    if not words:
        return "Sujet de discussion"
    if len(words) <= max_words:
        return " ".join(words)
    return " ".join(words[:max_words])


def purge_client_expired_sessions(max_age_days: float = RETENTION_MAX_DAYS) -> int:
    """Purge définitive et réelle de toutes les sessions clientes inactives depuis plus de max_age_days (CA7).

    La règle est absolue : aucun épinglage n'est pris en compte côté client, la suppression est
    physique et synchrone dans client_chat_sessions.db ET dans le SessionDB de l'agent.
    """
    _find_profile_dir, _get_client_sessions_db_path, _init_client_sessions_db, _, PROJECT_ROOT = _get_deps()
    cutoff = time.time() - (max_age_days * 86400.0)
    db_path = _get_client_sessions_db_path()
    purged_sessions: List[tuple[str, str]] = []

    _init_client_sessions_db()
    try:
        with sqlite3.connect(str(db_path), timeout=15.0) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT session_id, agent_id FROM client_chat_sessions WHERE last_activity_at < ?",
                (cutoff,),
            )
            purged_sessions = cursor.fetchall()
            if purged_sessions:
                cursor.execute("DELETE FROM client_chat_sessions WHERE last_activity_at < ?", (cutoff,))
                conn.commit()
    except Exception as e:
        _log.error("Erreur registre lors de la purge des sessions clientes expirées: %s", e)
        raise

    # Suppression réelle dans le magasin SessionDB de l'agent concerné
    for sid, ag_id in purged_sessions:
        try:
            profile_dir = _find_profile_dir(ag_id)
            if profile_dir and profile_dir.is_dir() and os.access(profile_dir, os.W_OK):
                agent_home = profile_dir.resolve()
            else:
                agent_home = (PROJECT_ROOT / "data" / "agents" / ag_id).resolve()
            state_file = agent_home / "state.db"
            if state_file.exists():
                from hermes_state import SessionDB
                sdb = SessionDB(state_file)
                sdb.delete_session(sid)
        except Exception as e:
            _log.error("Erreur suppression SessionDB lors de la purge de la session %s: %s", sid, e)

    if purged_sessions:
        _log.info("Purge conservation 60 jours : %d sessions supprimées définitivement.", len(purged_sessions))
    return len(purged_sessions)


def maybe_auto_title_session(session_id: str, prompt: str, agent_id: str) -> Optional[str]:
    """Attribue un titre automatique (borné à 6 mots) si la session n'a pas de titre saisi manuellement."""
    _find_profile_dir, _get_client_sessions_db_path, _init_client_sessions_db, _, PROJECT_ROOT = _get_deps()
    _init_client_sessions_db()
    db_path = _get_client_sessions_db_path()
    try:
        with sqlite3.connect(str(db_path), timeout=15.0) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT title, title_source FROM client_chat_sessions WHERE session_id = ?",
                (session_id,),
            )
            row = cursor.fetchone()
            if row is not None:
                current_title, current_source = row[0], row[1]
                # Si l'utilisateur a déjà saisi un titre manuel, on ne l'écrase jamais
                if current_source == "user" and current_title:
                    return current_title

                auto_title = generate_auto_title(prompt, max_words=6)
                cursor.execute(
                    "UPDATE client_chat_sessions SET title = ?, title_source = 'auto' WHERE session_id = ?",
                    (auto_title, session_id),
                )
                conn.commit()

                # Synchronisation vers SessionDB (moteur)
                try:
                    profile_dir = _find_profile_dir(agent_id)
                    if profile_dir and profile_dir.is_dir() and os.access(profile_dir, os.W_OK):
                        agent_home = profile_dir.resolve()
                    else:
                        agent_home = (PROJECT_ROOT / "data" / "agents" / agent_id).resolve()
                    state_file = agent_home / "state.db"
                    if state_file.exists():
                        from hermes_state import SessionDB
                        sdb = SessionDB(state_file)
                        sdb.set_auto_title(session_id, auto_title, source="derived")
                except Exception as e:
                    _log.debug("Synchronisation auto_title SessionDB: %s", e)
                return auto_title
    except Exception as e:
        _log.warning("Erreur auto_title session %s: %s", session_id, e)
    return None


def assign_or_create_theme_for_session(
    session_id: str,
    prompt: str,
    tenant_id: str,
    user_id: str,
    agent_id: str,
    explicit_theme_id: Optional[str] = None,
) -> str:
    """Associe une session à un thème existant ou crée un nouveau thème (4 mots max, KAN-84)."""
    _find_profile_dir, _get_client_sessions_db_path, _init_client_sessions_db, _, PROJECT_ROOT = _get_deps()
    _init_client_sessions_db()
    db_path = _get_client_sessions_db_path()
    now = time.time()

    with sqlite3.connect(str(db_path), timeout=15.0) as conn:
        _init_client_themes_db(conn)
        cursor = conn.cursor()

        # 1. Vérifier si la session a déjà un thème
        cursor.execute("SELECT dossier_metier_id FROM client_chat_sessions WHERE session_id = ?", (session_id,))
        row = cursor.fetchone()
        if row and row[0]:
            current_theme_id = row[0]
            cursor.execute("UPDATE client_chat_themes SET updated_at = ? WHERE theme_id = ?", (now, current_theme_id))
            conn.commit()
            return current_theme_id

        # 2. Si explicit_theme_id fourni (via bouton + sur le thème)
        if explicit_theme_id:
            cursor.execute(
                "SELECT theme_id FROM client_chat_themes WHERE theme_id = ? AND tenant_id = ? AND user_id = ? AND agent_id = ?",
                (explicit_theme_id, tenant_id, user_id, agent_id),
            )
            if cursor.fetchone():
                cursor.execute(
                    "UPDATE client_chat_sessions SET dossier_metier_id = ? WHERE session_id = ?",
                    (explicit_theme_id, session_id),
                )
                cursor.execute("UPDATE client_chat_themes SET updated_at = ? WHERE theme_id = ?", (now, explicit_theme_id))
                conn.commit()
                return explicit_theme_id

        # 3. Rapprochement avec un thème existant basé sur les mots clés significatifs du premier message
        words = {w.lower() for w in re.findall(r"\b\w{4,}\b", prompt)}
        if words:
            cursor.execute(
                """SELECT theme_id, title FROM client_chat_themes 
                   WHERE tenant_id = ? AND user_id = ? AND agent_id = ?
                   ORDER BY updated_at DESC LIMIT 20""",
                (tenant_id, user_id, agent_id),
            )
            existing_themes = cursor.fetchall()
            for t_id, t_title in existing_themes:
                t_words = {w.lower() for w in re.findall(r"\b\w{4,}\b", t_title)}
                if t_words and len(words.intersection(t_words)) >= 1:
                    cursor.execute(
                        "UPDATE client_chat_sessions SET dossier_metier_id = ? WHERE session_id = ?",
                        (t_id, session_id),
                    )
                    cursor.execute("UPDATE client_chat_themes SET updated_at = ? WHERE theme_id = ?", (now, t_id))
                    conn.commit()
                    return t_id

        # 4. Sinon, création d'un nouveau thème en 4 mots max
        theme_title = generate_theme_title(prompt, max_words=4)
        new_theme_id = f"theme_{uuid.uuid4().hex[:12]}"
        cursor.execute(
            """INSERT INTO client_chat_themes 
               (theme_id, tenant_id, user_id, agent_id, title, title_source, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, 'auto', ?, ?)""",
            (new_theme_id, tenant_id, user_id, agent_id, theme_title, now, now),
        )
        cursor.execute(
            "UPDATE client_chat_sessions SET dossier_metier_id = ? WHERE session_id = ?",
            (new_theme_id, session_id),
        )
        conn.commit()
        return new_theme_id


def get_theme_context_for_session(
    session_id: str,
    theme_id: Optional[str],
    tenant_id: str,
    user_id: str,
    agent_id: str,
    max_chars: int = 6000,
) -> str:
    """Construit le contexte issu des conversations antérieures du même thème (KAN-85).

    Plafond strict à max_chars (~1500 tokens). Zéro fuite inter-thèmes ni inter-tenants.
    Retourne une chaîne vide si le thème est neuf ou vide (CA5).
    """
    if not theme_id:
        return ""

    _find_profile_dir, _get_client_sessions_db_path, _init_client_sessions_db, _, PROJECT_ROOT = _get_deps()
    _init_client_sessions_db()
    db_path = _get_client_sessions_db_path()

    theme_title = ""
    prior_sessions: List[tuple[str, str]] = []

    with sqlite3.connect(str(db_path), timeout=15.0) as conn:
        _init_client_themes_db(conn)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT title FROM client_chat_themes WHERE theme_id = ? AND tenant_id = ? AND user_id = ? AND agent_id = ?",
            (theme_id, tenant_id, user_id, agent_id),
        )
        row = cursor.fetchone()
        if not row:
            return ""
        theme_title = row[0]

        # Chercher les sessions antérieures du thème
        cursor.execute(
            """SELECT session_id, title FROM client_chat_sessions 
               WHERE dossier_metier_id = ? AND session_id != ? AND tenant_id = ? AND user_id = ? AND agent_id = ?
               ORDER BY last_activity_at DESC LIMIT 5""",
            (theme_id, session_id, tenant_id, user_id, agent_id),
        )
        prior_sessions = cursor.fetchall()

    if not prior_sessions:
        return ""

    profile_dir = _find_profile_dir(agent_id)
    if profile_dir and profile_dir.is_dir() and os.access(profile_dir, os.W_OK):
        agent_home = profile_dir.resolve()
    else:
        agent_home = (PROJECT_ROOT / "data" / "agents" / agent_id).resolve()
    state_file = agent_home / "state.db"
    if not state_file.exists():
        return ""

    from hermes_state import SessionDB
    sdb = SessionDB(state_file)

    def _extract_text(val: Any) -> str:
        if isinstance(val, str):
            return val
        if isinstance(val, list):
            parts = []
            for item in val:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    parts.append(str(item.get("text") or item.get("content") or ""))
            return " ".join(parts).strip()
        if isinstance(val, dict):
            return str(val.get("text") or val.get("content") or "")
        return str(val or "")

    session_summaries = []
    for sid, stitle in prior_sessions:
        msgs = sdb.get_messages_as_conversation(sid) or []
        if not msgs:
            continue
        user_msgs = [_extract_text(m.get("content")) for m in msgs if m.get("role") == "user" and m.get("content")]
        asst_msgs = [_extract_text(m.get("content")) for m in msgs if m.get("role") == "assistant" and m.get("content")]
        if user_msgs and user_msgs[0].strip():
            first_q = user_msgs[0][:150]
            last_a = asst_msgs[-1][:250] if asst_msgs else ""
            summary_entry = f"- Discussion « {stitle or 'Sans titre'} » :\n  Question : {first_q}\n  Synthèse : {last_a}"
            session_summaries.append(summary_entry)

    if not session_summaries:
        return ""

    header = f"[CONTEXTE DU THÈME : « {theme_title} »]\nHistorique des échanges précédents au sein de ce thème :\n"
    footer = "\n[FIN DU CONTEXTE DU THÈME — Utilise ces éléments pour répondre avec continuité. Si une information n'y figure pas, signale-le sans l'inventer.]"

    body = "\n".join(session_summaries)
    full_context = header + body + footer
    if len(full_context) > max_chars:
        full_context = full_context[: max_chars - len(footer) - 20] + "...\n" + footer
    return full_context


@history_router.get("/api/client/chat/sessions")
async def list_client_sessions_endpoint(
    agent_id: Optional[str] = Query(None, description="Filtrer par agent (ex: jerome)"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    auth: Dict[str, Any] = Depends(verify_client_access),
):
    """Liste les conversations de l'utilisateur pour l'espace client courant (CA1, CA5, CA6).

    Triées de la plus récente à la plus ancienne, bornées à 60 jours de conservation.
    """
    _, _get_client_sessions_db_path, _init_client_sessions_db, _, _ = _get_deps()
    user_id = str(auth.get("sub") or auth.get("user_id") or "anonymous").strip()
    tenant = auth.get("tenant") or {}
    tenant_id = str(tenant.get("tenant_id") or tenant.get("tenant_slug") or os.environ.get("ORSO_CLIENT_ID", "default")).strip()

    # Purge opportuniste des conversations de plus de 60 jours
    try:
        purge_client_expired_sessions(RETENTION_MAX_DAYS)
    except Exception as e:
        _log.warning("Purge opportuniste en échec: %s", e)

    _init_client_sessions_db()
    db_path = _get_client_sessions_db_path()
    cutoff = time.time() - RETENTION_SECONDS

    query = """
        SELECT session_id, tenant_id, user_id, agent_id, title, title_source,
               dossier_metier_id, created_at, last_activity_at
        FROM client_chat_sessions
        WHERE tenant_id = ? AND user_id = ? AND last_activity_at >= ?
    """
    params: List[Any] = [tenant_id, user_id, cutoff]
    if agent_id:
        query += " AND agent_id = ?"
        params.append(agent_id)

    query += " ORDER BY last_activity_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    with sqlite3.connect(str(db_path), timeout=15.0) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(query, params).fetchall()

        count_query = """
            SELECT COUNT(*) FROM client_chat_sessions
            WHERE tenant_id = ? AND user_id = ? AND last_activity_at >= ?
        """
        count_params: List[Any] = [tenant_id, user_id, cutoff]
        if agent_id:
            count_query += " AND agent_id = ?"
            count_params.append(agent_id)
        total = conn.execute(count_query, count_params).fetchone()[0]

    sessions = []
    for r in rows:
        sessions.append({
            "session_id": r["session_id"],
            "tenant_id": r["tenant_id"],
            "user_id": r["user_id"],
            "agent_id": r["agent_id"],
            "title": r["title"] or "Discussion sans titre",
            "title_source": r["title_source"] or "auto",
            "dossier_metier_id": r["dossier_metier_id"],
            "created_at": r["created_at"],
            "last_activity_at": r["last_activity_at"],
        })

    return {
        "sessions": sessions,
        "total": total,
        "retention_days": int(RETENTION_MAX_DAYS),
    }


@history_router.get("/api/client/chat/sessions/{session_id}")
async def get_client_session_details_endpoint(
    session_id: str,
    agent_id: str = Query("jerome"),
    auth: Dict[str, Any] = Depends(verify_client_access),
):
    """Retourne les métadonnées détaillées d'une session cliente après vérification d'étanchéité."""
    cleaned_sid = (session_id or "").strip()
    if not cleaned_sid:
        raise HTTPException(status_code=400, detail="Identifiant de session manquant ou invalide.")

    _, _get_client_sessions_db_path, _, _verify_and_bind_client_session, _ = _get_deps()
    user_id = str(auth.get("sub") or auth.get("user_id") or "anonymous").strip()
    tenant = auth.get("tenant") or {}
    tenant_id = str(tenant.get("tenant_id") or tenant.get("tenant_slug") or os.environ.get("ORSO_CLIENT_ID", "default")).strip()

    _verify_and_bind_client_session(
        session_id=cleaned_sid,
        tenant_id=tenant_id,
        user_id=user_id,
        agent_id=agent_id,
        create_if_missing=False,
    )

    db_path = _get_client_sessions_db_path()
    with sqlite3.connect(str(db_path), timeout=15.0) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """SELECT session_id, tenant_id, user_id, agent_id, title, title_source,
                      dossier_metier_id, created_at, last_activity_at
               FROM client_chat_sessions WHERE session_id = ?""",
            (cleaned_sid,),
        )
        row = cursor.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Conversation introuvable ou supprimée.")

    return {
        "session_id": row[0],
        "tenant_id": row[1],
        "user_id": row[2],
        "agent_id": row[3],
        "title": row[4] or "Discussion sans titre",
        "title_source": row[5] or "auto",
        "dossier_metier_id": row[6],
        "created_at": row[7],
        "last_activity_at": row[8],
        "retention_days": int(RETENTION_MAX_DAYS),
    }


@history_router.patch("/api/client/chat/sessions/{session_id}")
async def update_client_session_endpoint(
    session_id: str,
    req: SessionUpdateRequest,
    auth: Dict[str, Any] = Depends(verify_client_access),
):
    """Renomme une conversation (title_source='user') ou lui associe un dossier métier."""
    cleaned_sid = (session_id or "").strip()
    if not cleaned_sid:
        raise HTTPException(status_code=400, detail="Identifiant de session manquant ou invalide.")

    _find_profile_dir, _get_client_sessions_db_path, _, _verify_and_bind_client_session, PROJECT_ROOT = _get_deps()
    user_id = str(auth.get("sub") or auth.get("user_id") or "anonymous").strip()
    tenant = auth.get("tenant") or {}
    tenant_id = str(tenant.get("tenant_id") or tenant.get("tenant_slug") or os.environ.get("ORSO_CLIENT_ID", "default")).strip()
    agent_id = req.agent_id or "jerome"

    _verify_and_bind_client_session(
        session_id=cleaned_sid,
        tenant_id=tenant_id,
        user_id=user_id,
        agent_id=agent_id,
        create_if_missing=False,
    )

    db_path = _get_client_sessions_db_path()
    with sqlite3.connect(str(db_path), timeout=15.0) as conn:
        cursor = conn.cursor()
        if req.title is not None:
            clean_title = req.title.strip()
            cursor.execute(
                "UPDATE client_chat_sessions SET title = ?, title_source = 'user' WHERE session_id = ?",
                (clean_title, cleaned_sid),
            )
            # Synchronisation SessionDB
            try:
                profile_dir = _find_profile_dir(agent_id)
                if profile_dir and profile_dir.is_dir() and os.access(profile_dir, os.W_OK):
                    agent_home = profile_dir.resolve()
                else:
                    agent_home = (PROJECT_ROOT / "data" / "agents" / agent_id).resolve()
                state_file = agent_home / "state.db"
                if state_file.exists():
                    from hermes_state import SessionDB
                    sdb = SessionDB(state_file)
                    sdb.set_session_title(cleaned_sid, clean_title)
            except Exception as e:
                _log.warning("Impossible de synchroniser le titre dans SessionDB: %s", e)

        if req.dossier_metier_id is not None:
            clean_dossier = req.dossier_metier_id.strip() if req.dossier_metier_id else None
            cursor.execute(
                "UPDATE client_chat_sessions SET dossier_metier_id = ? WHERE session_id = ?",
                (clean_dossier, cleaned_sid),
            )
        conn.commit()

        cursor.execute(
            """SELECT session_id, tenant_id, user_id, agent_id, title, title_source,
                      dossier_metier_id, created_at, last_activity_at
               FROM client_chat_sessions WHERE session_id = ?""",
            (cleaned_sid,),
        )
        row = cursor.fetchone()

    return {
        "session_id": row[0],
        "tenant_id": row[1],
        "user_id": row[2],
        "agent_id": row[3],
        "title": row[4],
        "title_source": row[5],
        "dossier_metier_id": row[6],
        "created_at": row[7],
        "last_activity_at": row[8],
        "retention_days": int(RETENTION_MAX_DAYS),
    }


@history_router.delete("/api/client/chat/sessions/{session_id}")
async def delete_client_session_endpoint(
    session_id: str,
    agent_id: str = Query("jerome"),
    auth: Dict[str, Any] = Depends(verify_client_access),
):
    """Supprime immédiatement et définitivement une conversation de la liste et du moteur (CA4)."""
    cleaned_sid = (session_id or "").strip()
    if not cleaned_sid:
        raise HTTPException(status_code=400, detail="Identifiant de session manquant ou invalide.")

    _find_profile_dir, _get_client_sessions_db_path, _, _verify_and_bind_client_session, PROJECT_ROOT = _get_deps()
    user_id = str(auth.get("sub") or auth.get("user_id") or "anonymous").strip()
    tenant = auth.get("tenant") or {}
    tenant_id = str(tenant.get("tenant_id") or tenant.get("tenant_slug") or os.environ.get("ORSO_CLIENT_ID", "default")).strip()

    # Contrôle d'étanchéité sans création
    _verify_and_bind_client_session(
        session_id=cleaned_sid,
        tenant_id=tenant_id,
        user_id=user_id,
        agent_id=agent_id,
        create_if_missing=False,
    )

    # 1. Suppression physique de client_chat_sessions.db
    db_path = _get_client_sessions_db_path()
    with sqlite3.connect(str(db_path), timeout=15.0) as conn:
        conn.execute("DELETE FROM client_chat_sessions WHERE session_id = ?", (cleaned_sid,))
        conn.commit()

    # 2. Suppression physique du magasin SessionDB du moteur
    try:
        profile_dir = _find_profile_dir(agent_id)
        if profile_dir and profile_dir.is_dir() and os.access(profile_dir, os.W_OK):
            agent_home = profile_dir.resolve()
        else:
            agent_home = (PROJECT_ROOT / "data" / "agents" / agent_id).resolve()
        state_file = agent_home / "state.db"
        if state_file.exists():
            from hermes_state import SessionDB
            sdb = SessionDB(state_file)
            sdb.delete_session(cleaned_sid)
    except Exception as e:
        _log.error("Erreur suppression SessionDB pour %s: %s", cleaned_sid, e)

    return {"success": True, "session_id": cleaned_sid, "deleted": True}


@history_router.post("/api/client/chat/sessions/purge")
async def trigger_client_sessions_purge_endpoint(
    max_age_days: float = Query(RETENTION_MAX_DAYS, ge=1.0),
    auth: Dict[str, Any] = Depends(verify_client_access),
):
    """Point de déclenchement ou de contrôle de la purge de rétention 60 jours (CA7)."""
    count = purge_client_expired_sessions(max_age_days)
    return {
        "success": True,
        "purged_count": count,
        "retention_days": max_age_days,
        "purged_at": datetime.now().isoformat(),
    }


# ============================================================================
# KAN-84 & KAN-85 : Organisation des conversations par thèmes & Contexte
# ============================================================================


@history_router.get("/api/client/chat/themes")
async def list_client_themes_endpoint(
    agent_id: Optional[str] = Query(None, description="Filtrer par agent (ex: jerome)"),
    limit: int = Query(50, ge=1, le=200),
    auth: Dict[str, Any] = Depends(verify_client_access),
):
    """Liste les thèmes de conversations de l'utilisateur avec leurs sessions rattachées (KAN-84, CA1, CA6)."""
    _, _get_client_sessions_db_path, _init_client_sessions_db, _, _ = _get_deps()
    user_id = str(auth.get("sub") or auth.get("user_id") or "anonymous").strip()
    tenant = auth.get("tenant") or {}
    tenant_id = str(tenant.get("tenant_id") or tenant.get("tenant_slug") or os.environ.get("ORSO_CLIENT_ID", "default")).strip()

    _init_client_sessions_db()
    db_path = _get_client_sessions_db_path()

    with sqlite3.connect(str(db_path), timeout=15.0) as conn:
        _init_client_themes_db(conn)
        conn.row_factory = sqlite3.Row

        query = """
            SELECT theme_id, tenant_id, user_id, agent_id, title, title_source, created_at, updated_at
            FROM client_chat_themes
            WHERE tenant_id = ? AND user_id = ?
        """
        params: List[Any] = [tenant_id, user_id]
        if agent_id:
            query += " AND agent_id = ?"
            params.append(agent_id)
        query += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)

        theme_rows = conn.execute(query, params).fetchall()
        themes = []
        for tr in theme_rows:
            t_id = tr["theme_id"]
            s_rows = conn.execute(
                """SELECT session_id, tenant_id, user_id, agent_id, title, title_source,
                          dossier_metier_id, created_at, last_activity_at
                   FROM client_chat_sessions
                   WHERE dossier_metier_id = ? AND tenant_id = ? AND user_id = ?
                   ORDER BY last_activity_at DESC""",
                (t_id, tenant_id, user_id),
            ).fetchall()

            sessions = [
                {
                    "session_id": sr["session_id"],
                    "tenant_id": sr["tenant_id"],
                    "user_id": sr["user_id"],
                    "agent_id": sr["agent_id"],
                    "title": sr["title"] or "Discussion sans titre",
                    "title_source": sr["title_source"] or "auto",
                    "dossier_metier_id": sr["dossier_metier_id"],
                    "created_at": sr["created_at"],
                    "last_activity_at": sr["last_activity_at"],
                }
                for sr in s_rows
            ]

            themes.append({
                "theme_id": t_id,
                "tenant_id": tr["tenant_id"],
                "user_id": tr["user_id"],
                "agent_id": tr["agent_id"],
                "title": tr["title"],
                "title_source": tr["title_source"],
                "created_at": tr["created_at"],
                "updated_at": tr["updated_at"],
                "sessions_count": len(sessions),
                "sessions": sessions,
            })

    return {"themes": themes, "total": len(themes)}


@history_router.post("/api/client/chat/themes")
async def create_client_theme_endpoint(
    req: ThemeCreateRequest,
    auth: Dict[str, Any] = Depends(verify_client_access),
):
    """Crée manuellement un nouveau thème de conversation pour l'utilisateur (KAN-84)."""
    _, _get_client_sessions_db_path, _init_client_sessions_db, _, _ = _get_deps()
    user_id = str(auth.get("sub") or auth.get("user_id") or "anonymous").strip()
    tenant = auth.get("tenant") or {}
    tenant_id = str(tenant.get("tenant_id") or tenant.get("tenant_slug") or os.environ.get("ORSO_CLIENT_ID", "default")).strip()

    _init_client_sessions_db()
    db_path = _get_client_sessions_db_path()
    theme_id = f"theme_{uuid.uuid4().hex[:12]}"
    now = time.time()
    raw_title = (req.title or "").strip()
    title_source = "user" if raw_title else "auto"
    title = generate_theme_title(raw_title, max_words=4) if raw_title else "Nouveau thème"

    with sqlite3.connect(str(db_path), timeout=15.0) as conn:
        _init_client_themes_db(conn)
        conn.execute(
            """INSERT INTO client_chat_themes 
               (theme_id, tenant_id, user_id, agent_id, title, title_source, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (theme_id, tenant_id, user_id, req.agent_id or "jerome", title, title_source, now, now),
        )
        conn.commit()

    return {
        "success": True,
        "theme": {
            "theme_id": theme_id,
            "title": title,
            "title_source": title_source,
            "agent_id": req.agent_id or "jerome",
            "created_at": now,
            "updated_at": now,
        },
    }


@history_router.patch("/api/client/chat/themes/{theme_id}")
async def update_client_theme_endpoint(
    theme_id: str,
    req: ThemeUpdateRequest,
    auth: Dict[str, Any] = Depends(verify_client_access),
):
    """Renomme un thème de conversation (CA3). Protégé contre l'écrasement automatique."""
    clean_title = (req.title or "").strip()
    if not clean_title:
        raise HTTPException(status_code=400, detail="Le titre du thème ne peut pas être vide.")

    _, _get_client_sessions_db_path, _init_client_sessions_db, _, _ = _get_deps()
    user_id = str(auth.get("sub") or auth.get("user_id") or "anonymous").strip()
    tenant = auth.get("tenant") or {}
    tenant_id = str(tenant.get("tenant_id") or tenant.get("tenant_slug") or os.environ.get("ORSO_CLIENT_ID", "default")).strip()

    db_path = _get_client_sessions_db_path()
    with sqlite3.connect(str(db_path), timeout=15.0) as conn:
        _init_client_themes_db(conn)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT theme_id FROM client_chat_themes WHERE theme_id = ? AND tenant_id = ? AND user_id = ?",
            (theme_id, tenant_id, user_id),
        )
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="Thème non trouvé ou accès non autorisé.")

        bounded_title = generate_theme_title(clean_title, max_words=4)
        now = time.time()
        cursor.execute(
            "UPDATE client_chat_themes SET title = ?, title_source = 'user', updated_at = ? WHERE theme_id = ?",
            (bounded_title, now, theme_id),
        )
        conn.commit()

    return {"success": True, "theme_id": theme_id, "title": bounded_title, "title_source": "user"}


@history_router.delete("/api/client/chat/themes/{theme_id}")
async def delete_client_theme_endpoint(
    theme_id: str,
    delete_sessions: bool = Query(False, description="Supprimer également toutes les sessions du thème"),
    auth: Dict[str, Any] = Depends(verify_client_access),
):
    """Supprime un thème de conversation avec option de détachement ou de purge des sessions (CA5)."""
    _find_profile_dir, _get_client_sessions_db_path, _init_client_sessions_db, _, PROJECT_ROOT = _get_deps()
    user_id = str(auth.get("sub") or auth.get("user_id") or "anonymous").strip()
    tenant = auth.get("tenant") or {}
    tenant_id = str(tenant.get("tenant_id") or tenant.get("tenant_slug") or os.environ.get("ORSO_CLIENT_ID", "default")).strip()

    db_path = _get_client_sessions_db_path()
    with sqlite3.connect(str(db_path), timeout=15.0) as conn:
        _init_client_themes_db(conn)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT agent_id FROM client_chat_themes WHERE theme_id = ? AND tenant_id = ? AND user_id = ?",
            (theme_id, tenant_id, user_id),
        )
        t_row = cursor.fetchone()
        if not t_row:
            raise HTTPException(status_code=404, detail="Thème non trouvé ou accès non autorisé.")
        agent_id = t_row[0]

        if delete_sessions:
            cursor.execute(
                "SELECT session_id FROM client_chat_sessions WHERE dossier_metier_id = ? AND tenant_id = ? AND user_id = ?",
                (theme_id, tenant_id, user_id),
            )
            s_rows = cursor.fetchall()
            cursor.execute("DELETE FROM client_chat_sessions WHERE dossier_metier_id = ?", (theme_id,))
            cursor.execute("DELETE FROM client_chat_themes WHERE theme_id = ?", (theme_id,))
            conn.commit()

            try:
                profile_dir = _find_profile_dir(agent_id)
                agent_home = profile_dir.resolve() if (profile_dir and profile_dir.is_dir() and os.access(profile_dir, os.W_OK)) else (PROJECT_ROOT / "data" / "agents" / agent_id).resolve()
                state_file = agent_home / "state.db"
                if state_file.exists():
                    from hermes_state import SessionDB
                    sdb = SessionDB(state_file)
                    for (sid,) in s_rows:
                        sdb.delete_session(sid)
            except Exception as e:
                _log.error("Erreur suppression SessionDB pour thème %s: %s", theme_id, e)
        else:
            cursor.execute("UPDATE client_chat_sessions SET dossier_metier_id = NULL WHERE dossier_metier_id = ?", (theme_id,))
            cursor.execute("DELETE FROM client_chat_themes WHERE theme_id = ?", (theme_id,))
            conn.commit()

    return {"success": True, "theme_id": theme_id, "deleted": True}


@history_router.post("/api/client/chat/themes/{theme_id}/sessions/{session_id}")
async def move_session_to_theme_endpoint(
    theme_id: str,
    session_id: str,
    auth: Dict[str, Any] = Depends(verify_client_access),
):
    """Déplace ou rattache une conversation à un thème spécifique (CA4)."""
    _, _get_client_sessions_db_path, _init_client_sessions_db, _, _ = _get_deps()
    user_id = str(auth.get("sub") or auth.get("user_id") or "anonymous").strip()
    tenant = auth.get("tenant") or {}
    tenant_id = str(tenant.get("tenant_id") or tenant.get("tenant_slug") or os.environ.get("ORSO_CLIENT_ID", "default")).strip()

    db_path = _get_client_sessions_db_path()
    with sqlite3.connect(str(db_path), timeout=15.0) as conn:
        _init_client_themes_db(conn)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT theme_id, agent_id FROM client_chat_themes WHERE theme_id = ? AND tenant_id = ? AND user_id = ?",
            (theme_id, tenant_id, user_id),
        )
        t_row = cursor.fetchone()
        if not t_row:
            raise HTTPException(status_code=404, detail="Thème non trouvé ou accès non autorisé.")
        t_agent_id = t_row[1]

        cursor.execute(
            "SELECT session_id, agent_id FROM client_chat_sessions WHERE session_id = ? AND tenant_id = ? AND user_id = ?",
            (session_id, tenant_id, user_id),
        )
        s_row = cursor.fetchone()
        if not s_row:
            raise HTTPException(status_code=404, detail="Session non trouvée ou accès non autorisé.")
        if s_row[1] != t_agent_id:
            raise HTTPException(status_code=400, detail="Impossible d'associer une session à un thème d'un autre agent.")

        cursor.execute(
            "UPDATE client_chat_sessions SET dossier_metier_id = ? WHERE session_id = ?",
            (theme_id, session_id),
        )
        cursor.execute("UPDATE client_chat_themes SET updated_at = ? WHERE theme_id = ?", (time.time(), theme_id))
        conn.commit()

    return {"success": True, "theme_id": theme_id, "session_id": session_id}


@history_router.post("/api/client/chat/themes/{theme_id}/merge/{target_theme_id}")
async def merge_client_themes_endpoint(
    theme_id: str,
    target_theme_id: str,
    auth: Dict[str, Any] = Depends(verify_client_access),
):
    """Fusionne deux thèmes de conversations (CA4). Toutes les sessions rejoignent target_theme_id."""
    if theme_id == target_theme_id:
        raise HTTPException(status_code=400, detail="Impossible de fusionner un thème avec lui-même.")

    _, _get_client_sessions_db_path, _init_client_sessions_db, _, _ = _get_deps()
    user_id = str(auth.get("sub") or auth.get("user_id") or "anonymous").strip()
    tenant = auth.get("tenant") or {}
    tenant_id = str(tenant.get("tenant_id") or tenant.get("tenant_slug") or os.environ.get("ORSO_CLIENT_ID", "default")).strip()

    db_path = _get_client_sessions_db_path()
    with sqlite3.connect(str(db_path), timeout=15.0) as conn:
        _init_client_themes_db(conn)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT agent_id FROM client_chat_themes WHERE theme_id = ? AND tenant_id = ? AND user_id = ?",
            (theme_id, tenant_id, user_id),
        )
        src = cursor.fetchone()
        cursor.execute(
            "SELECT agent_id FROM client_chat_themes WHERE theme_id = ? AND tenant_id = ? AND user_id = ?",
            (target_theme_id, tenant_id, user_id),
        )
        dst = cursor.fetchone()

        if not src or not dst:
            raise HTTPException(status_code=404, detail="Un ou plusieurs thèmes non trouvés ou accès non autorisé.")
        if src[0] != dst[0]:
            raise HTTPException(status_code=400, detail="Impossible de fusionner deux thèmes d'agents différents.")

        cursor.execute(
            "UPDATE client_chat_sessions SET dossier_metier_id = ? WHERE dossier_metier_id = ?",
            (target_theme_id, theme_id),
        )
        cursor.execute("DELETE FROM client_chat_themes WHERE theme_id = ?", (theme_id,))
        cursor.execute("UPDATE client_chat_themes SET updated_at = ? WHERE theme_id = ?", (time.time(), target_theme_id))
        conn.commit()

    return {"success": True, "source_theme_id": theme_id, "target_theme_id": target_theme_id}


@history_router.get("/api/client/chat/themes/{theme_id}/context")
async def get_client_theme_context_endpoint(
    theme_id: str,
    session_id: Optional[str] = Query(None, description="Session courante à exclure de la reprise de contexte"),
    agent_id: str = Query("jerome"),
    auth: Dict[str, Any] = Depends(verify_client_access),
):
    """Expose le contexte de reprise d'un thème borné et documenté (KAN-85, CA2, CA3, CA5)."""
    user_id = str(auth.get("sub") or auth.get("user_id") or "anonymous").strip()
    tenant = auth.get("tenant") or {}
    tenant_id = str(tenant.get("tenant_id") or tenant.get("tenant_slug") or os.environ.get("ORSO_CLIENT_ID", "default")).strip()

    ctx = get_theme_context_for_session(
        session_id=session_id or "",
        theme_id=theme_id,
        tenant_id=tenant_id,
        user_id=user_id,
        agent_id=agent_id,
    )
    tokens_est = len(ctx) // 4
    return {
        "theme_id": theme_id,
        "context_text": ctx,
        "has_context": bool(ctx.strip()),
        "length_chars": len(ctx),
        "tokens_est": tokens_est,
    }

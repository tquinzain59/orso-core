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


def generate_auto_title(prompt: str, max_words: int = 6) -> str:
    """Génère un titre automatique à partir du premier message utilisateur, borné à max_words."""
    cleaned = re.sub(r"[\r\n\t]+", " ", (prompt or "")).strip()
    words = [w for w in cleaned.split(" ") if w]
    if not words:
        return "Nouvelle discussion"
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

"""Gestionnaire de la politique d'autonomie, des garde-fous HITL et des actions en attente (KAN-106).

Gère :
- Le chargement des politiques d'autonomie par agent (profiles/{agent}/autonomy_policy.yaml)
- L'interception et la mise en attente des actions sensibles (emails, SMS, remises, etc.)
- La persistance dans la base d'audit data/pending_actions.db
- L'approbation ou le rejet par un opérateur habilité (admin, superadmin, daf, direction)
"""

import json
import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
import yaml

_log = logging.getLogger("orso.olympe.autonomy")

DEFAULT_PENDING_DB_PATH = os.environ.get("ORSO_PENDING_ACTIONS_DB", "data/pending_actions.db")
PROFILES_ROOT = Path("profiles")


class AutonomyManager:
    """Contrôleur d'autonomie et registre d'approbation humaine des actions d'agents."""

    def __init__(
        self,
        db_path: Optional[Path] = None,
        profiles_dir: Optional[Path] = None,
    ):
        self.db_path = Path(db_path or DEFAULT_PENDING_DB_PATH).resolve()
        self.profiles_dir = Path(profiles_dir or PROFILES_ROOT).resolve()
        self._policy_cache: Dict[str, Dict[str, Any]] = {}
        self._init_db()

    def _init_db(self) -> None:
        """Initialise la table d'audit des actions en attente d'approbation."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(str(self.db_path), timeout=15.0) as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute(
                """CREATE TABLE IF NOT EXISTS pending_actions (
                    id TEXT PRIMARY KEY,
                    tenant_slug TEXT,
                    agent_id TEXT NOT NULL,
                    action_type TEXT NOT NULL,
                    recipient TEXT,
                    draft_content TEXT,
                    risk_level TEXT NOT NULL DEFAULT 'medium',
                    status TEXT NOT NULL,
                    metadata_json TEXT,
                    created_at TEXT NOT NULL,
                    reviewed_at TEXT,
                    reviewer_id TEXT,
                    reviewer_role TEXT,
                    rejection_reason TEXT,
                    execution_result_json TEXT
                );"""
            )
            conn.execute(
                """CREATE INDEX IF NOT EXISTS idx_pending_actions_slug_status 
                   ON pending_actions (tenant_slug, status);"""
            )
            conn.commit()

    def get_policy(self, agent_id: str) -> Dict[str, Any]:
        """Charge la politique d'autonomie YAML d'un agent."""
        clean_id = agent_id.lower().strip()
        if clean_id in self._policy_cache:
            return self._policy_cache[clean_id]

        policy_file = self.profiles_dir / clean_id / "autonomy_policy.yaml"
        if not policy_file.is_file():
            # Politique par défaut stricte (tout envoi externe requiert validation)
            default_policy = {
                "agent_id": clean_id,
                "autonomy_level": "supervised",
                "approval_policy": {
                    "approval_channel": "client_portal",
                    "auto_reject_after_hours": 48,
                    "allowed_roles": ["admin", "superadmin", "daf", "direction"],
                },
                "supervised_actions": [
                    {"action_type": "send", "requires_approval": True, "risk_level": "high"},
                    {"action_type": "send_email", "requires_approval": True, "risk_level": "high"},
                    {"action_type": "send_sms", "requires_approval": True, "risk_level": "high"},
                ],
                "autonomous_actions": [],
            }
            self._policy_cache[clean_id] = default_policy
            return default_policy

        try:
            with open(policy_file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            self._policy_cache[clean_id] = data
            return data
        except Exception as e:
            _log.error("Impossible de lire la politique d'autonomie pour %s: %s", clean_id, e)
            return {"agent_id": clean_id, "autonomy_level": "supervised", "supervised_actions": []}

    def is_approval_required(self, agent_id: str, action_type: str) -> bool:
        """Détermine si une action requiert formellement une approbation humaine préalable."""
        policy = self.get_policy(agent_id)
        action_clean = action_type.lower().strip()

        # 1. Vérifier si explicitement autonome
        for auto in policy.get("autonomous_actions", []):
            if auto.get("action_type") == action_clean:
                return False

        # 2. Vérifier si explicitement supervisé
        for sup in policy.get("supervised_actions", []):
            if sup.get("action_type") == action_clean:
                return sup.get("requires_approval", True)

        # 3. Règle par défaut pour toute action d'envoi externe
        if action_clean in ("send", "send_email", "send_sms", "execute", "payment", "discount"):
            return True

        return False

    def create_pending_action(
        self,
        action_id: str,
        agent_id: str,
        action_type: str,
        tenant_slug: Optional[str] = None,
        recipient: Optional[str] = None,
        draft_content: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        risk_level: str = "high",
    ) -> Dict[str, Any]:
        """Enregistre une action sensible dans le registre d'attente (pending_actions.db)."""
        now_iso = datetime.now(timezone.utc).isoformat()
        metadata_json = json.dumps(metadata or {}, ensure_ascii=False)

        with sqlite3.connect(str(self.db_path), timeout=15.0) as conn:
            conn.execute(
                """INSERT OR REPLACE INTO pending_actions
                   (id, tenant_slug, agent_id, action_type, recipient, draft_content,
                    risk_level, status, metadata_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'PENDING', ?, ?);""",
                (
                    action_id,
                    tenant_slug,
                    agent_id,
                    action_type,
                    recipient,
                    draft_content,
                    risk_level,
                    metadata_json,
                    now_iso,
                ),
            )
            conn.commit()

        _log.info(
            "Action mise en attente d'approbation : id=%s, agent=%s, type=%s, slug=%s",
            action_id,
            agent_id,
            action_type,
            tenant_slug,
        )

        return {
            "id": action_id,
            "status": "PENDING",
            "agent_id": agent_id,
            "action_type": action_type,
            "recipient": recipient,
            "created_at": now_iso,
            "requires_approval": True,
        }

    def get_pending_actions(
        self,
        tenant_slug: Optional[str] = None,
        status: str = "PENDING",
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Retourne les actions enregistrées selon leur statut."""
        with sqlite3.connect(str(self.db_path), timeout=15.0) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            query = "SELECT * FROM pending_actions WHERE status = ?"
            params: List[Any] = [status]
            if tenant_slug:
                query += " AND tenant_slug = ?"
                params.append(tenant_slug)
            query += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)

            cursor.execute(query, tuple(params))
            rows = cursor.fetchall()
            results = []
            for r in rows:
                item = dict(r)
                if item.get("metadata_json"):
                    try:
                        item["metadata"] = json.loads(item["metadata_json"])
                    except Exception:
                        item["metadata"] = {}
                results.append(item)
            return results

    def approve_action(
        self,
        action_id: str,
        reviewer_id: Optional[str] = None,
        reviewer_role: Optional[str] = None,
        comment: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Approuve une action mise en attente (passage de PENDING à APPROVED)."""
        now_iso = datetime.now(timezone.utc).isoformat()

        with sqlite3.connect(str(self.db_path), timeout=15.0) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM pending_actions WHERE id = ?;", (action_id,))
            row = cursor.fetchone()
            if not row:
                raise KeyError(f"Action introuvable : {action_id}")

            current_status = row["status"]
            if current_status != "PENDING":
                return {
                    "success": False,
                    "action_id": action_id,
                    "status": current_status,
                    "message": f"Action déjà traitée (statut actuel : {current_status}).",
                }

            cursor.execute(
                """UPDATE pending_actions
                   SET status = 'APPROVED', reviewed_at = ?, reviewer_id = ?, reviewer_role = ?
                   WHERE id = ?;""",
                (now_iso, reviewer_id or "user", reviewer_role or "admin", action_id),
            )
            conn.commit()

        _log.info("Action %s approuvée par %s (%s)", action_id, reviewer_id, reviewer_role)
        return {
            "success": True,
            "action_id": action_id,
            "status": "APPROVED",
            "reviewed_at": now_iso,
            "reviewer_id": reviewer_id,
            "message": "Action validée par l'opérateur. Prête pour exécution.",
        }

    def reject_action(
        self,
        action_id: str,
        reviewer_id: Optional[str] = None,
        reviewer_role: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Rejette une action mise en attente (passage de PENDING à REJECTED)."""
        now_iso = datetime.now(timezone.utc).isoformat()

        with sqlite3.connect(str(self.db_path), timeout=15.0) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM pending_actions WHERE id = ?;", (action_id,))
            row = cursor.fetchone()
            if not row:
                raise KeyError(f"Action introuvable : {action_id}")

            current_status = row["status"]
            if current_status != "PENDING":
                return {
                    "success": False,
                    "action_id": action_id,
                    "status": current_status,
                    "message": f"Action déjà traitée (statut actuel : {current_status}).",
                }

            cursor.execute(
                """UPDATE pending_actions
                   SET status = 'REJECTED', reviewed_at = ?, reviewer_id = ?, reviewer_role = ?, rejection_reason = ?
                   WHERE id = ?;""",
                (now_iso, reviewer_id or "user", reviewer_role or "admin", reason or "Refus utilisateur", action_id),
            )
            conn.commit()

        _log.info("Action %s rejetée par %s (%s) : %s", action_id, reviewer_id, reviewer_role, reason)
        return {
            "success": True,
            "action_id": action_id,
            "status": "REJECTED",
            "reviewed_at": now_iso,
            "rejection_reason": reason or "Refus utilisateur",
            "message": "Action annulée et archivée sans effet de bord.",
        }

    def mark_executed(
        self,
        action_id: str,
        result: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Marque une action approuvée comme exécutée (passage à EXECUTED)."""
        now_iso = datetime.now(timezone.utc).isoformat()
        res_json = json.dumps(result or {}, ensure_ascii=False)

        with sqlite3.connect(str(self.db_path), timeout=15.0) as conn:
            conn.execute(
                """UPDATE pending_actions
                   SET status = 'EXECUTED', execution_result_json = ?
                   WHERE id = ?;""",
                (res_json, action_id),
            )
            conn.commit()

        return {"success": True, "action_id": action_id, "status": "EXECUTED", "executed_at": now_iso}


# Instance partagée
autonomy_manager = AutonomyManager()

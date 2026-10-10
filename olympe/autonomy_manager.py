"""Gestionnaire de la politique d'autonomie, des garde-fous HITL et des actions en attente (KAN-106).

Gère :
- Le chargement des politiques d'autonomie par agent (profiles/{agent}/autonomy_policy.yaml)
- La gestion des 3 niveaux d'autonomie : 'libre', 'sous_validation', 'interdit'
- L'interception et la mise en attente des actions sensibles (emails, SMS, remises, ERP, tiers)
- La persistance dans la base d'audit data/pending_actions.db
- L'expiration automatique à 48h et le récapitulatif groupé des demandes en attente
- L'approbation / rejet individuel ou en lot par un opérateur habilité
- L'audit strict des modifications de politiques et le contrôle des planchers contractuels (CA6, CA7)
"""

import json
import logging
import os
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
import yaml

_log = logging.getLogger("orso.olympe.autonomy")

DEFAULT_PENDING_DB_PATH = os.environ.get("ORSO_PENDING_ACTIONS_DB", "data/pending_actions.db")
PROFILES_ROOT = Path("profiles")

# Actions fondamentales obligatoires du périmètre KAN-106
MANDATORY_PERIMETER_ACTIONS = [
    "send_message_third_party",
    "write_erp_accounting",
    "send_payment_reminder",
    "commit_amount_discount",
    "publish_external_document",
    "contact_third_party_person",
]


class AutonomyManager:
    """Contrôleur d'autonomie et registre d'approbation humaine des actions d'agents."""

    def __init__(
        self,
        db_path: Optional[Path] = None,
        profiles_dir: Optional[Path] = None,
        activity_manager: Optional[Any] = None,
    ):
        self.db_path = Path(db_path or DEFAULT_PENDING_DB_PATH).resolve()
        self.profiles_dir = Path(profiles_dir or PROFILES_ROOT).resolve()
        self._policy_cache: Dict[str, Dict[str, Any]] = {}
        self._activity_manager = activity_manager
        self._init_db()

    @property
    def activity_manager(self) -> Optional[Any]:
        if self._activity_manager is None:
            try:
                from olympe.activity_manager import activity_manager
                return activity_manager
            except Exception:
                return None
        return self._activity_manager

    def _init_db(self) -> None:
        """Initialise la table d'audit des actions et la table d'audit des modifications de politiques."""
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
                """CREATE TABLE IF NOT EXISTS policy_change_audit (
                    id TEXT PRIMARY KEY,
                    tenant_slug TEXT,
                    agent_id TEXT NOT NULL,
                    action_type TEXT NOT NULL,
                    old_level TEXT NOT NULL,
                    new_level TEXT NOT NULL,
                    changed_by TEXT NOT NULL,
                    changed_at TEXT NOT NULL,
                    reason TEXT
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
            # Politique par défaut stricte
            default_policy = {
                "agent_id": clean_id,
                "autonomy_level": "supervised",
                "approval_policy": {
                    "approval_channel": "client_portal",
                    "auto_reject_after_hours": 48,
                    "allowed_roles": ["admin", "superadmin", "daf", "direction"],
                },
                "actions": [
                    {"action_type": a, "level": "sous_validation", "contract_floor": "sous_validation"}
                    for a in MANDATORY_PERIMETER_ACTIONS
                ],
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
            return {"agent_id": clean_id, "autonomy_level": "supervised", "actions": []}

    def get_action_level(self, agent_id: str, action_type: str) -> str:
        """Retourne le niveau d'autonomie pour une action : 'libre', 'sous_validation', ou 'interdit'."""
        policy = self.get_policy(agent_id)
        action_clean = action_type.lower().strip()

        # 1. Vérifier dans la liste moderne actions
        for act in policy.get("actions", []):
            if act.get("action_type") == action_clean:
                return act.get("level", "sous_validation")

        # 2. Vérifier dans les listes de compatibilité
        for auto in policy.get("autonomous_actions", []):
            if auto.get("action_type") == action_clean:
                return "libre"

        for sup in policy.get("supervised_actions", []):
            if sup.get("action_type") == action_clean:
                return "sous_validation" if sup.get("requires_approval", True) else "libre"

        # 3. Règle stricte par défaut : tout ce qui sort de l'entreprise est sous validation
        if action_clean in ("send", "send_email", "send_sms", "execute", "payment", "discount"):
            return "sous_validation"

        return "sous_validation"

    def is_approval_required(self, agent_id: str, action_type: str) -> bool:
        """Détermine si une action requiert formellement une approbation humaine préalable."""
        return self.get_action_level(agent_id, action_type) == "sous_validation"

    def is_action_forbidden(self, agent_id: str, action_type: str) -> bool:
        """Détermine si une action est strictement interdite pour l'agent."""
        return self.get_action_level(agent_id, action_type) == "interdit"

    def check_action_execution(
        self,
        agent_id: str,
        action_type: str,
        action_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Vérifie le droit d'exécution d'une action avant déclenchement d'outil (CA5)."""
        level = self.get_action_level(agent_id, action_type)

        if level == "interdit":
            return {
                "allowed": False,
                "level": "interdit",
                "code": "ERR_ACTION_FORBIDDEN",
                "message": f"Action '{action_type}' formellement interdite pour l'agent {agent_id}.",
            }

        if level == "sous_validation":
            if not action_id:
                return {
                    "allowed": False,
                    "level": "sous_validation",
                    "code": "ERR_APPROVAL_REQUIRED",
                    "message": f"Action '{action_type}' requiert une validation humaine préalable (carte d'action requise).",
                }

            with sqlite3.connect(str(self.db_path), timeout=15.0) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute("SELECT status FROM pending_actions WHERE id = ?;", (action_id,))
                row = cursor.fetchone()
                if not row or row["status"] != "APPROVED":
                    cur_stat = row["status"] if row else "NOT_FOUND"
                    return {
                        "allowed": False,
                        "level": "sous_validation",
                        "code": "ERR_APPROVAL_NOT_GRANTED",
                        "message": f"Action '{action_id}' non approuvée (statut actuel : {cur_stat}).",
                    }

        return {
            "allowed": True,
            "level": level,
            "status": "APPROVED" if level == "sous_validation" else "AUTONOMOUS",
        }

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

        if self.activity_manager:
            try:
                self.activity_manager.record_activity(
                    tenant_slug=tenant_slug or "default",
                    agent_id=agent_id,
                    action_type=action_type,
                    source_type="Demande de validation",
                    source_ref=recipient or f"Action {action_type}",
                    status="pending_validation",
                    action_id=action_id,
                    metadata={"recipient": recipient, "risk_level": risk_level},
                    created_at=now_iso,
                )
            except Exception as act_err:
                _log.debug("Erreur synchro journal d'activité: %s", act_err)

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

        if self.activity_manager:
            try:
                self.activity_manager.record_activity(
                    tenant_slug=row["tenant_slug"] or "default",
                    agent_id=row["agent_id"],
                    action_type=row["action_type"],
                    source_type="Validation dirigeant",
                    source_ref=row["recipient"] or f"Action {row['action_type']}",
                    status="done",
                    action_id=action_id,
                    metadata={"reviewed_by": reviewer_id, "reviewer_role": reviewer_role},
                    created_at=now_iso,
                )
            except Exception as act_err:
                _log.debug("Erreur synchro journal d'activité (approve): %s", act_err)

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

        if self.activity_manager:
            try:
                self.activity_manager.record_activity(
                    tenant_slug=row["tenant_slug"] or "default",
                    agent_id=row["agent_id"],
                    action_type=row["action_type"],
                    source_type="Demande refusée",
                    source_ref=row["recipient"] or f"Action {row['action_type']}",
                    status="rejected",
                    rejection_reason=reason or "Refus utilisateur",
                    action_id=action_id,
                    metadata={"reviewed_by": reviewer_id, "reviewer_role": reviewer_role},
                    created_at=now_iso,
                )
            except Exception as act_err:
                _log.debug("Erreur synchro journal d'activité (reject): %s", act_err)

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

    def expire_stale_actions(self, threshold_hours: int = 48) -> int:
        """Bascule les actions PENDING dépassées à EXPIRED avec traçabilité (CA3)."""
        now = datetime.now(timezone.utc)
        threshold_dt = now - timedelta(hours=threshold_hours)
        threshold_iso = threshold_dt.isoformat()
        now_iso = now.isoformat()

        with sqlite3.connect(str(self.db_path), timeout=15.0) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM pending_actions WHERE status = 'PENDING' AND created_at <= ?;",
                (threshold_iso,),
            )
            expired_rows = cursor.fetchall()
            cursor.execute(
                """UPDATE pending_actions
                   SET status = 'EXPIRED', reviewed_at = ?, rejection_reason = 'Délai d expiration dépassé sans réponse (48h)'
                   WHERE status = 'PENDING' AND created_at <= ?;""",
                (now_iso, threshold_iso),
            )
            expired_count = cursor.rowcount
            conn.commit()

        if expired_rows and self.activity_manager:
            try:
                for r in expired_rows:
                    self.activity_manager.record_activity(
                        tenant_slug=r["tenant_slug"] or "default",
                        agent_id=r["agent_id"],
                        action_type=r["action_type"],
                        source_type="Demande expirée",
                        source_ref=r["recipient"] or f"Action {r['action_type']}",
                        status="expired",
                        rejection_reason="Délai d expiration dépassé sans réponse (48h)",
                        action_id=r["id"],
                        created_at=now_iso,
                    )
            except Exception as act_err:
                _log.debug("Erreur synchro journal d'activité (expire): %s", act_err)

        if expired_count > 0:
            _log.info("%d action(s) basculée(s) à EXPIRED (seuil: %dh)", expired_count, threshold_hours)
        return expired_count

    def get_unanswered_recap(self, tenant_slug: Optional[str] = None) -> Dict[str, Any]:
        """Récapitulatif des demandes restées sans réponse (PENDING et EXPIRED) pour traitement groupé (CA8)."""
        self.expire_stale_actions(threshold_hours=48)
        with sqlite3.connect(str(self.db_path), timeout=15.0) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            query = "SELECT * FROM pending_actions WHERE status IN ('PENDING', 'EXPIRED')"
            params: List[Any] = []
            if tenant_slug:
                query += " AND tenant_slug = ?"
                params.append(tenant_slug)
            query += " ORDER BY created_at DESC;"
            cursor.execute(query, tuple(params))
            rows = [dict(r) for r in cursor.fetchall()]

            for item in rows:
                if item.get("metadata_json"):
                    try:
                        item["metadata"] = json.loads(item["metadata_json"])
                    except Exception:
                        item["metadata"] = {}

            pending_items = [r for r in rows if r["status"] == "PENDING"]
            expired_items = [r for r in rows if r["status"] == "EXPIRED"]

            return {
                "unanswered_actions": rows,
                "pending_count": len(pending_items),
                "expired_count": len(expired_items),
                "total_unanswered": len(rows),
                "recap_date": datetime.now(timezone.utc).isoformat(),
            }

    def batch_review_actions(
        self,
        action_ids: List[str],
        decision: str,
        reviewer_id: str,
        reviewer_role: str = "admin",
        comment: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Applique une décision groupée (APPROVE ou REJECT) sur une liste d'actions (CA8)."""
        decision_upper = decision.upper().strip()
        if decision_upper not in ("APPROVE", "REJECT"):
            raise ValueError("Décision invalide. Valeurs acceptées : 'APPROVE' ou 'REJECT'.")

        processed = []
        errors = []
        for aid in action_ids:
            try:
                if decision_upper == "APPROVE":
                    res = self.approve_action(aid, reviewer_id=reviewer_id, reviewer_role=reviewer_role, comment=comment)
                else:
                    res = self.reject_action(aid, reviewer_id=reviewer_id, reviewer_role=reviewer_role, reason=comment or "Refus groupé")
                processed.append(res)
            except Exception as e:
                errors.append({"action_id": aid, "error": str(e)})

        return {
            "success": len(errors) == 0,
            "processed_count": len(processed),
            "errors_count": len(errors),
            "details": processed,
            "errors": errors,
        }

    def update_action_level(
        self,
        agent_id: str,
        action_type: str,
        new_level: str,
        user_id: str,
        user_role: str,
        tenant_slug: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Modifie le niveau d'autonomie d'une action en vérifiant les bornes contractuelles et trace le changement (CA6, CA7)."""
        valid_levels = ("libre", "sous_validation", "interdit")
        level_clean = new_level.lower().strip()
        if level_clean not in valid_levels:
            raise ValueError(f"Niveau invalide '{new_level}'. Niveaux valides : {valid_levels}")

        policy = self.get_policy(agent_id)
        actions = policy.get("actions", [])
        target_action = next((a for a in actions if a.get("action_type") == action_type), None)

        old_level = target_action.get("level", "sous_validation") if target_action else "sous_validation"
        contract_floor = target_action.get("contract_floor", "sous_validation") if target_action else "sous_validation"

        # Contrôle strict du plancher contractuel (CA7)
        if contract_floor == "interdit" and level_clean != "interdit":
            raise PermissionError(f"Action '{action_type}' interdite par le contrat commercial : assouplissement impossible.")
        if contract_floor == "sous_validation" and level_clean == "libre":
            raise PermissionError(f"Action '{action_type}' bornée à 'sous_validation' par le contrat : passage en 'libre' impossible.")

        # Enregistrement dans le journal d'audit de modification de politique (CA6)
        audit_id = f"audit_pol_{int(time.time() * 1000)}"
        now_iso = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(str(self.db_path), timeout=15.0) as conn:
            conn.execute(
                """INSERT INTO policy_change_audit
                   (id, tenant_slug, agent_id, action_type, old_level, new_level, changed_by, changed_at, reason)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);""",
                (audit_id, tenant_slug, agent_id, action_type, old_level, level_clean, user_id, now_iso, reason or "Ajustement client"),
            )
            conn.commit()

        # Mise à jour de la politique en mémoire
        if target_action:
            target_action["level"] = level_clean
        else:
            actions.append({
                "action_type": action_type,
                "level": level_clean,
                "contract_floor": contract_floor,
            })
            policy["actions"] = actions

        _log.info(
            "Politique modifiée pour %s/%s : %s -> %s par %s (audit: %s)",
            agent_id, action_type, old_level, level_clean, user_id, audit_id
        )

        return {
            "success": True,
            "agent_id": agent_id,
            "action_type": action_type,
            "old_level": old_level,
            "new_level": level_clean,
            "changed_by": user_id,
            "changed_at": now_iso,
            "audit_id": audit_id,
        }

    def get_policy_change_history(self, agent_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Retourne l'historique des modifications de politiques d'autonomie (CA6)."""
        with sqlite3.connect(str(self.db_path), timeout=15.0) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            if agent_id:
                cursor.execute(
                    "SELECT * FROM policy_change_audit WHERE agent_id = ? ORDER BY changed_at DESC;",
                    (agent_id,),
                )
            else:
                cursor.execute("SELECT * FROM policy_change_audit ORDER BY changed_at DESC;")
            return [dict(r) for r in cursor.fetchall()]


# Instance partagée
autonomy_manager = AutonomyManager()

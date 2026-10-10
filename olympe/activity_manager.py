"""Gestionnaire du Journal d'Activité Client (KAN-107).

Fournit au dirigeant la vision claire, en français sans jargon, de ce que ses
agents ont fait, avec rétention de dix ans, journal en ajout seul (append-only)
et étanchéité multi-tenant absolue.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

_log = logging.getLogger("orso.olympe.activity")

CANONICAL_AGENT_NAMES: Dict[str, str] = {
    "jerome": "Jérôme (Recouvrement)",
    "lucas": "Lucas (Prospection & Devis)",
    "clara": "Clara (Support Client)",
    "victor": "Victor (Appels d'Offres)",
}

CANONICAL_ACTION_LABELS: Dict[str, str] = {
    "send_message_third_party": "Envoi d'un message tiers",
    "execute_database_write": "Écriture en base de données",
    "commit_amount_discount": "Validation d'une remise financière",
    "send_reminder_email": "Envoi d'un email de relance",
    "send_reminder_sms": "Envoi d'un SMS de relance",
    "schedule_payment_plan": "Mise en place d'un échéancier de paiement",
    "send_quote": "Émission d'un devis",
    "send_prospecting_email": "Envoi d'un email de prospection",
    "book_accounting_entry": "Comptabilisation d'une écriture",
    "reconcile_bank_transaction": "Rapprochement bancaire",
    "publish_report": "Publication d'un rapport de synthèse",
    "read_local_db": "Consultation sécurisée des données",
    "export_report_file": "Génération d'un fichier d'export",
    "prepare_message_draft": "Préparation d'un projet de message",
    "external_escalation": "Transmission au service contentieux externe",
}

STATUS_LABELS: Dict[str, str] = {
    "done": "Faite",
    "pending_validation": "En attente de validation",
    "rejected": "Refusée",
    "expired": "Expirée",
}


def _format_timestamp(dt: Optional[datetime] = None) -> str:
    if dt is None:
        dt = datetime.now(timezone.utc)
    return dt.isoformat()


def _sanitize_metadata(metadata: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Nettoie les métadonnées pour exclure les corps de messages intégraux (CA8)."""
    if not metadata or not isinstance(metadata, dict):
        return {}
    clean: Dict[str, Any] = {}
    for k, v in metadata.items():
        k_lower = str(k).lower()
        # Exclusion stricte des corps de message complets ou contenus bruts
        if any(term in k_lower for term in ("body", "content", "raw_message", "payload", "draft_content")):
            # Ne garder qu'un extrait très court ou résumé si présent
            if isinstance(v, str):
                summary = v.strip().replace("\n", " ")
                clean[f"{k}_summary"] = summary[:120] + ("..." if len(summary) > 120 else "")
            continue
        # Limiter la longueur des valeurs textuelles
        if isinstance(v, str) and len(v) > 300:
            clean[k] = v[:300] + "..."
        else:
            clean[k] = v
    return clean


class ClientActivityManager:
    """Gestionnaire persistant et append-only du journal d'activité client (KAN-107)."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        if db_path is None:
            self.db_path = Path("data/olympe_activity.db")
        else:
            self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        """Initialise la table et les triggers d'inviolabilité append-only (CA6)."""
        with sqlite3.connect(str(self.db_path), timeout=15.0) as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS client_activity_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tenant_slug TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    agent_name TEXT NOT NULL,
                    action_type TEXT NOT NULL,
                    action_label TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_ref TEXT NOT NULL,
                    status TEXT NOT NULL,
                    status_label TEXT NOT NULL,
                    rejection_reason TEXT,
                    action_id TEXT,
                    metadata_json TEXT,
                    created_at TEXT NOT NULL
                );"""
            )
            conn.execute(
                """CREATE INDEX IF NOT EXISTS idx_activity_tenant_date
                   ON client_activity_log (tenant_slug, created_at);"""
            )
            conn.execute(
                """CREATE INDEX IF NOT EXISTS idx_activity_tenant_agent
                   ON client_activity_log (tenant_slug, agent_id);"""
            )

            # Triggers SQLite garantissant l'append-only absolu au niveau du moteur de base de données (CA6)
            conn.execute(
                """CREATE TRIGGER IF NOT EXISTS prevent_client_activity_delete
                   BEFORE DELETE ON client_activity_log
                   BEGIN
                       SELECT RAISE(ABORT, 'APPEND_ONLY_VIOLATION: Les entrées du journal d activité ne peuvent pas être supprimées.');
                   END;"""
            )
            conn.execute(
                """CREATE TRIGGER IF NOT EXISTS prevent_client_activity_update
                   BEFORE UPDATE ON client_activity_log
                   BEGIN
                       SELECT RAISE(ABORT, 'APPEND_ONLY_VIOLATION: Les entrées du journal d activité sont strictement immutables.');
                   END;"""
            )
            conn.commit()

    def record_activity(
        self,
        tenant_slug: str,
        agent_id: str,
        action_type: str,
        source_type: str,
        source_ref: str,
        status: str = "done",
        agent_name: Optional[str] = None,
        action_label: Optional[str] = None,
        rejection_reason: Optional[str] = None,
        action_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        created_at: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Enregistre une nouvelle entrée dans le journal d'activité (CA2, CA8)."""
        clean_tenant = tenant_slug.strip().lower()
        clean_agent = agent_id.strip().lower()
        resolved_agent_name = agent_name or CANONICAL_AGENT_NAMES.get(clean_agent, clean_agent.capitalize())
        resolved_action_label = action_label or CANONICAL_ACTION_LABELS.get(action_type, action_type.replace("_", " ").capitalize())
        clean_status = status.lower().strip()
        status_label = STATUS_LABELS.get(clean_status, clean_status.capitalize())
        timestamp = created_at or _format_timestamp()
        safe_meta = _sanitize_metadata(metadata)

        with sqlite3.connect(str(self.db_path), timeout=15.0) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO client_activity_log (
                    tenant_slug, agent_id, agent_name, action_type, action_label,
                    source_type, source_ref, status, status_label, rejection_reason,
                    action_id, metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);""",
                (
                    clean_tenant,
                    clean_agent,
                    resolved_agent_name,
                    action_type,
                    resolved_action_label,
                    source_type,
                    source_ref,
                    clean_status,
                    status_label,
                    rejection_reason,
                    action_id,
                    json.dumps(safe_meta, ensure_ascii=False) if safe_meta else None,
                    timestamp,
                ),
            )
            entry_id = cursor.lastrowid
            conn.commit()

        _log.info(
            "[CLIENT_ACTIVITY] [%s] %s -> %s (%s) | Issue: %s",
            clean_tenant,
            clean_agent,
            resolved_action_label,
            source_ref,
            status_label,
        )

        return {
            "id": entry_id,
            "tenant_slug": clean_tenant,
            "agent_id": clean_agent,
            "agent_name": resolved_agent_name,
            "action_type": action_type,
            "action_label": resolved_action_label,
            "source_type": source_type,
            "source_ref": source_ref,
            "status": status_label,
            "status_code": clean_status,
            "rejection_reason": rejection_reason,
            "action_id": action_id,
            "metadata": safe_meta,
            "created_at": timestamp,
        }

    def get_activities(
        self,
        tenant_slug: str,
        days: int = 30,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        agent_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 1000,
    ) -> List[Dict[str, Any]]:
        """Consulte les activités du client selon les filtres (CA1, CA5, CA10).

        Par défaut, filtre sur les 30 derniers jours (CA1).
        Permet d'étendre la recherche jusqu'à dix ans (CA10).
        """
        clean_tenant = tenant_slug.strip().lower()
        now = datetime.now(timezone.utc)

        # Calcul de la borne inférieure
        if start_date:
            min_date = start_date
        else:
            min_date = (now - timedelta(days=days)).isoformat()

        # Calcul de la borne supérieure
        if end_date:
            max_date = end_date
        else:
            max_date = now.isoformat()

        query = "SELECT * FROM client_activity_log WHERE tenant_slug = ? AND created_at >= ? AND created_at <= ?"
        params: List[Any] = [clean_tenant, min_date, max_date]

        if agent_id and agent_id != "all":
            query += " AND agent_id = ?"
            params.append(agent_id.strip().lower())

        if status and status != "all":
            query += " AND (status = ? OR status_label = ?)"
            params.extend([status.strip().lower(), status.strip()])

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        with sqlite3.connect(str(self.db_path), timeout=15.0) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(query, tuple(params))
            rows = cursor.fetchall()

        entries: List[Dict[str, Any]] = []
        for r in rows:
            meta = {}
            if r["metadata_json"]:
                try:
                    meta = json.loads(r["metadata_json"])
                except Exception:
                    pass
            entries.append({
                "id": r["id"],
                "timestamp": r["created_at"],
                "created_at": r["created_at"],
                "agent_id": r["agent_id"],
                "agent_name": r["agent_name"],
                "action_type": r["action_type"],
                "action_label": r["action_label"],
                "source_type": r["source_type"],
                "source_ref": r["source_ref"],
                "status": r["status_label"],
                "status_code": r["status"],
                "rejection_reason": r["rejection_reason"],
                "action_id": r["action_id"],
                "metadata": meta,
            })
        return entries

    def export_activities(
        self,
        tenant_slug: str,
        export_format: str = "json",
        days: int = 30,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        agent_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> str:
        """Exporte le journal d'activité dans un format lisible JSON ou CSV (CA9)."""
        entries = self.get_activities(
            tenant_slug=tenant_slug,
            days=days,
            start_date=start_date,
            end_date=end_date,
            agent_id=agent_id,
            status=status,
            limit=10000,
        )

        fmt = export_format.lower().strip()
        if fmt == "csv":
            output = io.StringIO()
            writer = csv.writer(output, delimiter=";")
            # En-têtes en français clair
            writer.writerow([
                "Date",
                "Agent",
                "Action en clair",
                "Source concernée",
                "Issue",
                "Motif de refus / détails",
                "Identifiant Action",
            ])
            for e in entries:
                writer.writerow([
                    e["timestamp"],
                    e["agent_name"],
                    e["action_label"],
                    f"{e['source_type']} : {e['source_ref']}",
                    e["status"],
                    e["rejection_reason"] or "",
                    e["action_id"] or "",
                ])
            return output.getvalue()

        # Format JSON lisible et structuré par défaut
        return json.dumps(
            {
                "tenant_slug": tenant_slug,
                "exported_at": _format_timestamp(),
                "period": {
                    "start_date": start_date or (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(),
                    "end_date": end_date or datetime.now(timezone.utc).isoformat(),
                },
                "total_entries": len(entries),
                "entries": entries,
            },
            ensure_ascii=False,
            indent=2,
        )

    def attempt_delete_entry(
        self,
        entry_id: int,
        tenant_slug: str,
        actor: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Tente de supprimer une entrée et trace l'incident de sécurité (CA6).

        Le journal étant en ajout seul absolu, cette opération est toujours
        bloquée et consigne une alerte de sécurité.
        """
        actor_name = (actor or {}).get("actor") or (actor or {}).get("email") or "client_user"
        _log.warning(
            "[SECURITY_INCIDENT] Tentative de suppression d'entrée du journal d'activité bloquée (entry_id=%s, tenant=%s, actor=%s)",
            entry_id,
            tenant_slug,
            actor_name,
        )

        # Consignation d'audit superviseur
        try:
            from olympe.ops_manager import OpsManager
            ops = OpsManager()
            ops.record_audit_event(
                actor={"actor": actor_name, "role": "security_alert"},
                action="security:unauthorized_deletion_attempt",
                target=f"client_activity:{entry_id}",
                details={"tenant_slug": tenant_slug, "violation": "APPEND_ONLY_MUTATION_DENIED"},
            )
        except Exception as e:
            _log.error("Impossible de consigner l'incident d'audit: %s", e)

        # Tenter la suppression SQL qui déclenche le trigger SQLite RAISE(ABORT)
        try:
            with sqlite3.connect(str(self.db_path), timeout=5.0) as conn:
                conn.execute("DELETE FROM client_activity_log WHERE id = ?;", (entry_id,))
                conn.commit()
        except (sqlite3.OperationalError, sqlite3.IntegrityError, sqlite3.DatabaseError) as sql_err:
            raise PermissionError(
                f"APPEND_ONLY_VIOLATION: Impossible de supprimer l'entrée {entry_id}. Le journal d'activité est en ajout seul."
            ) from sql_err

        raise PermissionError("APPEND_ONLY_VIOLATION: Le journal d'activité est en ajout seul.")


activity_manager = ClientActivityManager()

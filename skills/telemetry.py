#!/usr/bin/env python3
"""
Extraction et consolidation de la télémétrie financière et opérationnelle d'Hermès Core.
Interroge la base SQLite locale en lecture seule non bloquante (?mode=ro)
et génère le rapport telemetry_export.json exploité par le superviseur Olympe et le dashboard.

Usage CLI :
    python skills/telemetry.py [--db chemin/state.db] [--export chemin/telemetry_export.json] [--tenant ID]
"""

import sys
import os
import sqlite3
import json
import time
import argparse
from typing import Any, Dict, List, Optional


def resoudre_chemin_db(custom_path: Optional[str] = None) -> Optional[str]:
    """Recherche dynamique du fichier state.db selon l'environnement (Docker ou Hôte)."""
    if custom_path and os.path.exists(custom_path):
        return os.path.abspath(custom_path)

    env_path = os.environ.get("HERMES_STATE_DB")
    if env_path and os.path.exists(env_path):
        return os.path.abspath(env_path)

    candidats = [
        "/app/data/state.db",
        "/home/hermes/.hermes/state.db",
        "/home/hermes/.hermes/profiles/jerome/state.db",
        "./profiles/jerome/state.db",
        "./hermes_home_dot_hermes/profiles/jerome/state.db",
        "./hermes_home_dot_hermes/state.db",
        "./data/state.db",
    ]
    for c in candidats:
        if os.path.exists(c):
            return os.path.abspath(c)

    return None


def resoudre_chemin_export(custom_export: Optional[str] = None) -> str:
    """Détermine le chemin optimal pour l'export JSON selon le contexte."""
    if custom_export:
        return custom_export

    env_export = os.environ.get("TELEMETRY_EXPORT_PATH")
    if env_export:
        return env_export

    if os.path.isdir("/app/data"):
        return "/app/data/telemetry_export.json"

    # Création du dossier ./data local si besoin
    os.makedirs("./data", exist_ok=True)
    return "./data/telemetry_export.json"


def export_telemetry(
    db_path: Optional[str] = None,
    export_path: Optional[str] = None,
    tenant_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Extrait les métriques clés de la base d'état et les exporte au format JSON.
    Connexion SQLite en URI lecture seule (?mode=ro) avec timeout pour éviter tout conflit de lock WAL.
    """
    effective_db = resoudre_chemin_db(db_path)
    effective_export = resoudre_chemin_export(export_path)
    effective_tenant = tenant_id or os.environ.get("HERMES_TENANT_ID", "hermes_recouvrement")

    now = time.time()

    if not effective_db or not os.path.exists(effective_db):
        msg = f"Base d'état introuvable (recherche effectuée sur {effective_db or 'chemins par défaut'})."
        print(f"⚠️ {msg} — Génération d'une structure télémétrique initiale.")
        telemetry_fallback = {
            "tenant_id": effective_tenant,
            "timestamp": now,
            "last_activity": now,
            "metrics": {
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "api_calls": 0,
                "cost_usd": 0.0,
            },
            "errors": [],
            "status": "idle",
        }
        try:
            with open(effective_export, "w", encoding="utf-8") as f:
                json.dump(telemetry_fallback, f, indent=2, ensure_ascii=False)
        except Exception as write_err:
            print(f"❌ Erreur écriture export de fallback : {write_err}")
        return {"status": "warning", "message": msg, "data": telemetry_fallback}

    conn = None
    try:
        # Ouverture en mode lecture seule non-bloquante avec timeout de 10s
        db_uri = f"file:{effective_db}?mode=ro"
        conn = sqlite3.connect(db_uri, uri=True, timeout=10.0)
        cursor = conn.cursor()

        # Vérification des tables disponibles
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cursor.fetchall()}

        input_tokens = 0
        output_tokens = 0
        api_calls = 0
        cost_usd = 0.0
        last_activity = now

        # 1. Métriques de tokens et coûts
        if "session_model_usage" in tables:
            cursor.execute("""
                SELECT 
                    SUM(COALESCE(input_tokens, 0)), 
                    SUM(COALESCE(output_tokens, 0)), 
                    SUM(COALESCE(api_call_count, 0)), 
                    SUM(COALESCE(actual_cost_usd, 0.0)),
                    SUM(COALESCE(estimated_cost_usd, 0.0)),
                    MAX(COALESCE(last_seen, 0))
                FROM session_model_usage
            """)
            row = cursor.fetchone()
            if row:
                input_tokens = int(row[0] or 0)
                output_tokens = int(row[1] or 0)
                api_calls = int(row[2] or 0)
                actual_cost = float(row[3] or 0.0)
                estimated_cost = float(row[4] or 0.0)
                cost_usd = actual_cost if actual_cost > 0 else estimated_cost
                if row[5] and row[5] > 0:
                    last_activity = float(row[5])

        # 2. Recherche des erreurs récentes
        recent_errors: List[Dict[str, Any]] = []
        if "sessions" in tables:
            # Inspection des colonnes existantes dans 'sessions'
            cursor.execute("PRAGMA table_info(sessions)")
            session_cols = {c[1] for c in cursor.fetchall()}

            has_handoff = "handoff_error" in session_cols
            has_compress = "compression_failure_error" in session_cols

            if has_handoff or has_compress:
                where_clauses = []
                if has_handoff:
                    where_clauses.append("(handoff_error IS NOT NULL AND handoff_error != '')")
                if has_compress:
                    where_clauses.append("(compression_failure_error IS NOT NULL AND compression_failure_error != '')")

                where_sql = " OR ".join(where_clauses)
                query = f"""
                    SELECT id, started_at
                    FROM sessions
                    WHERE {where_sql}
                    ORDER BY started_at DESC
                    LIMIT 5
                """
                cursor.execute(query)
                for er in cursor.fetchall():
                    recent_errors.append({
                        "session_id": er[0],
                        "time": er[1],
                        "type": "execution_error"
                    })

        # Détermination de l'état d'activité
        is_active = (now - last_activity) < 3600

        telemetry_data = {
            "tenant_id": effective_tenant,
            "timestamp": now,
            "last_activity": last_activity,
            "metrics": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": input_tokens + output_tokens,
                "api_calls": api_calls,
                "cost_usd": round(cost_usd, 4),
            },
            "errors": recent_errors,
            "status": "active" if is_active else "idle",
        }

        # Écriture atomique ou directe dans le fichier exporté
        export_dir = os.path.dirname(effective_export)
        if export_dir and not os.path.exists(export_dir):
            os.makedirs(export_dir, exist_ok=True)

        with open(effective_export, "w", encoding="utf-8") as f:
            json.dump(telemetry_data, f, indent=2, ensure_ascii=False)

        print(f"✅ Télémétrie exportée avec succès ({effective_export}) — Coût total : {cost_usd:.4f} USD")
        return {"status": "success", "data": telemetry_data}

    except Exception as e:
        err_msg = f"Erreur lors de l'export de la télémétrie : {str(e)}"
        print(f"❌ {err_msg}")
        return {"status": "error", "message": err_msg}
    finally:
        if conn:
            conn.close()


def main():
    parser = argparse.ArgumentParser(description="Export de la télémétrie financière Hermès Core")
    parser.add_argument("--db", help="Chemin vers le fichier state.db")
    parser.add_argument("--export", help="Chemin de destination de telemetry_export.json")
    parser.add_argument("--tenant", help="Identifiant du tenant/organisation")
    parser.add_argument("--json", action="store_true", help="Afficher les métriques en sortie console JSON")
    args = parser.parse_args()

    res = export_telemetry(db_path=args.db, export_path=args.export, tenant_id=args.tenant)

    if args.json:
        print(json.dumps(res, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

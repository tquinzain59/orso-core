"""Script de restauration / rollback d'urgence post-purge KAN-71.

Restaure exhaustivement l'ensemble des entités sauvegardées dans un dump JSON :
- Comptes Supabase Auth (auth.users) avec leurs identifiants originaux
- Organisations (tenants)
- Profils utilisateurs (profiles)
- Instances conteneurs (tenant_instances)
- Instances agents (agent_instances)
- Abonnements (subscriptions)
- Intégrations (tenant_integrations)
- Canaux (tenant_channels)
- Factures (invoices)

Sécurisé par double verrou : mode simulation par défaut,
requiert --execute et --confirm-rollback pour appliquer la restauration.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

if os.path.exists(".env"):
    with open(".env", "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip("\"'"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
_log = logging.getLogger("kan71.rollback")

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY", "")

BACKUP_DIR = Path(__file__).resolve().parent / "backups"


def _supabase_request(endpoint: str, method: str = "POST", payload: Optional[Any] = None) -> Any:
    url = f"{SUPABASE_URL}/{endpoint.lstrip('/')}"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Prefer": "resolution=merge-duplicates",
    }
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15.0) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else None
    except urllib.error.HTTPError as e:
        err_msg = e.read().decode("utf-8")
        _log.error("Erreur HTTP %s sur %s: %s", e.code, url, err_msg)
        raise RuntimeError(f"Erreur Supabase HTTP {e.code} : {err_msg}")


def main():
    parser = argparse.ArgumentParser(description="Script de rollback d'urgence KAN-71")
    parser.add_argument("backup_file", nargs="?", help="Chemin du fichier JSON de sauvegarde à restaurer")
    parser.add_argument(
        "--execute",
        action="store_true",
        default=False,
        help="Drapeau d'autorisation d'exécution. Sans ce drapeau, le script effectue une simulation.",
    )
    parser.add_argument(
        "--confirm-rollback",
        action="store_true",
        default=False,
        help="Confirmation explicite de l'opération de rollback.",
    )
    args = parser.parse_args()

    is_dry_run = not (args.execute and args.confirm_rollback)

    _log.info("================================================================================")
    _log.info("ORSO AGENTS — KAN-71 : Procédure de Restauration / Rollback")
    _log.info("Mode : %s", "🔴 EXÉCUTION RÉELLE" if not is_dry_run else "🟢 SIMULATION (DRY-RUN)")
    _log.info("================================================================================")

    if not SUPABASE_URL or not SUPABASE_KEY:
        _log.error("SUPABASE_URL ou SUPABASE_SERVICE_ROLE_KEY manquants dans l'environnement.")
        sys.exit(1)

    backup_path: Optional[Path] = None
    if args.backup_file:
        backup_path = Path(args.backup_file)
    else:
        if BACKUP_DIR.exists():
            backup_files = sorted(BACKUP_DIR.glob("backup_kan71_pre_purge_*.json"), key=os.path.getmtime, reverse=True)
            if backup_files:
                backup_path = backup_files[0]

    if not backup_path or not backup_path.exists():
        _log.error("Aucun fichier de backup valide trouvé ou spécifié.")
        sys.exit(1)

    _log.info("Chargement du dump : %s (%d octets)", backup_path, backup_path.stat().st_size)
    with open(backup_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Récapitulatif du contenu du dump
    auth_users = data.get("auth_users", [])
    tenants = data.get("tenants", [])
    profiles = data.get("profiles", [])
    instances = data.get("tenant_instances", [])
    agents = data.get("agent_instances", [])
    subs = data.get("subscriptions", [])
    integrations = data.get("tenant_integrations", [])
    channels = data.get("tenant_channels", [])
    invoices = data.get("invoices", [])

    _log.info("Contenu identifié dans le dump :")
    _log.info("  - Comptes Auth : %d", len(auth_users))
    _log.info("  - Organisations (tenants) : %d", len(tenants))
    _log.info("  - Profils utilisateurs : %d", len(profiles))
    _log.info("  - Instances conteneurs : %d", len(instances))
    _log.info("  - Instances agents : %d", len(agents))
    _log.info("  - Abonnements : %d", len(subs))
    _log.info("  - Intégrations : %d", len(integrations))
    _log.info("  - Canaux : %d", len(channels))
    _log.info("  - Factures : %d", len(invoices))

    if is_dry_run:
        _log.warning("[DRY-RUN] Simulation terminée. Pour exécuter réellement le rollback, passez :")
        _log.warning("  --execute --confirm-rollback %s", backup_path)
        return

    _log.info("══ Application de la restauration en base ══")

    # 1. Restauration auth.users
    for u in auth_users:
        uid = u.get("id")
        email = u.get("email")
        if uid and email:
            try:
                payload = {
                    "id": uid,
                    "email": email,
                    "email_confirm": True,
                    "user_metadata": u.get("user_metadata", {}),
                    "app_metadata": u.get("app_metadata", {}),
                }
                _supabase_request("auth/v1/admin/users", method="POST", payload=payload)
                _log.info("  ✓ Utilisateur Auth restauré : %s (ID: %s)", email, uid)
            except Exception as e:
                _log.warning("Utilisateur auth %s déjà présent ou réinjecté : %s", email, e)

    # 2. Restauration tenants
    if tenants:
        _supabase_request("rest/v1/tenants", method="POST", payload=tenants)
        _log.info("  ✓ %d tenants restaurés", len(tenants))

    # 3. Restauration profiles
    if profiles:
        _supabase_request("rest/v1/profiles", method="POST", payload=profiles)
        _log.info("  ✓ %d profils restaurés", len(profiles))

    # 4. Restauration tenant_instances
    if instances:
        _supabase_request("rest/v1/tenant_instances", method="POST", payload=instances)
        _log.info("  ✓ %d instances conteneurs restaurées", len(instances))

    # 5. Restauration agent_instances
    if agents:
        _supabase_request("rest/v1/agent_instances", method="POST", payload=agents)
        _log.info("  ✓ %d instances agents restaurées", len(agents))

    # 6. Restauration subscriptions
    if subs:
        _supabase_request("rest/v1/subscriptions", method="POST", payload=subs)
        _log.info("  ✓ %d abonnements restaurés", len(subs))

    # 7. Restauration intégrations, canaux, factures
    if integrations:
        _supabase_request("rest/v1/tenant_integrations", method="POST", payload=integrations)
        _log.info("  ✓ %d intégrations restaurées", len(integrations))

    if channels:
        _supabase_request("rest/v1/tenant_channels", method="POST", payload=channels)
        _log.info("  ✓ %d canaux restaurés", len(channels))

    if invoices:
        _supabase_request("rest/v1/invoices", method="POST", payload=invoices)
        _log.info("  ✓ %d factures restaurées", len(invoices))

    _log.info("================================================================================")
    _log.info("Restauration / Rollback KAN-71 terminée avec succès.")
    _log.info("================================================================================")


if __name__ == "__main__":
    main()

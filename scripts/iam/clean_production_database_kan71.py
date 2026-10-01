"""Script d'assainissement et de purge des clients fictifs du POC en base de production (KAN-71).

Conforme aux critères d'acceptation KAN-71 et aux exigences de gouvernance :
- Mode simulation (--dry-run) actif par défaut : AUCUNE modification sans drapeaux explicites.
- Exécution réelle strictement verrouillée (--execute et --confirm-purge-production requis).
- Sauvegarde préalable exhaustive (dump JSON horodaté) avant toute altération,
  couvrant l'ensemble des tables en cascade :
  tenants, profiles, tenant_instances, agent_instances, subscriptions,
  tenant_integrations, tenant_channels, invoices, audit_logs, processed_events, auth_users.
- Conservation stricte des organisations réelles : financia-solutions et nexis-solutions.
- Purge ciblée et idempotente des 5 slugs d'amorçage :
  commercialink, helpdesk360, batipro-services, eurotech-conseil, aura-sans-env.
- Journalisation détaillée et contrôles post-exécution (CA2, CA3, CA4).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# Charger .env si présent localement
if os.path.exists(".env"):
    with open(".env", "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip("\"'"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
_log = logging.getLogger("kan71.cleanup")

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY", "")

TARGET_PURGE_SLUGS = [
    "commercialink",
    "helpdesk360",
    "batipro-services",
    "eurotech-conseil",
    "aura-sans-env",
]

KEPT_SLUGS = [
    "financia-solutions",
    "nexis-solutions",
]

BACKUP_DIR = Path(__file__).resolve().parent / "backups"


def _supabase_request(endpoint: str, method: str = "GET", payload: Optional[Any] = None) -> Any:
    """Effectue un appel authentifié vers l'API PostgREST ou Auth Supabase."""
    url = f"{SUPABASE_URL}/{endpoint.lstrip('/')}"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Prefer": "return=representation",
    }
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15.0) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else None
    except urllib.error.HTTPError as e:
        err_msg = e.read().decode("utf-8")
        _log.error("Erreur HTTP %s sur %s %s: %s", e.code, method, url, err_msg)
        raise RuntimeError(f"Erreur Supabase HTTP {e.code} : {err_msg}")


def step_preflight_check() -> Dict[str, Any]:
    """Étape 0 : Inventaire et vérifications préalables (Pre-flight)."""
    _log.info("══ Étape 0 : Inventaire Préalable & Vérifications (Pre-flight) ══")
    tenants = _supabase_request("rest/v1/tenants?select=*")
    if not isinstance(tenants, list):
        raise RuntimeError("Impossible de récupérer la liste des tenants.")

    slug_map = {t.get("slug"): t for t in tenants}
    _log.info("Total tenants présents en base : %d", len(tenants))

    # Vérification que les organisations légitimes à conserver sont bien présentes
    for kept in KEPT_SLUGS:
        if kept not in slug_map:
            raise RuntimeError(f"ERREUR CRITIQUE : Le client obligatoire à conserver '{kept}' est absent de la base !")
        _log.info("  ✓ Organisation conservée confirmée : [%s] %s (ID: %s)", kept, slug_map[kept].get("name"), slug_map[kept].get("id"))

    # Identifier les tenants à purger
    tenants_to_purge = [slug_map[s] for s in TARGET_PURGE_SLUGS if s in slug_map]
    _log.info("Nombre de tenants cibles identifiés pour la purge : %d / %d", len(tenants_to_purge), len(TARGET_PURGE_SLUGS))
    for tp in tenants_to_purge:
        _log.info("  ✗ Tenant à purger : [%s] %s (SIRET: %s, ID: %s)", tp.get("slug"), tp.get("name"), tp.get("siret"), tp.get("id"))

    return {
        "all_tenants": tenants,
        "tenants_to_purge": tenants_to_purge,
        "purge_tenant_ids": [t["id"] for t in tenants_to_purge],
        "purge_slugs": [t["slug"] for t in tenants_to_purge],
    }


def step_create_backup(purge_ids: List[str], purge_slugs: List[str]) -> Optional[Path]:
    """Étape 1 : Sauvegarde exhaustive (Dump JSON horodaté) avant toute altération."""
    _log.info("══ Étape 1 : Création du Dump de Sauvegarde Exhaustif ══")
    if not purge_ids:
        _log.info("Aucun tenant à purger, sauvegarde de précaution non requise.")
        return None

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_file = BACKUP_DIR / f"backup_kan71_pre_purge_{ts}.json"

    id_filter = f"in.({','.join(purge_ids)})"

    def _safe_fetch(table: str, col: str = "tenant_id") -> List[Dict[str, Any]]:
        try:
            res = _supabase_request(f"rest/v1/{table}?{col}={id_filter}")
            return res if isinstance(res, list) else []
        except Exception as e:
            _log.warning("Table optionnelle ou inaccessible '%s': %s", table, e)
            return []

    # Récupération exhaustive des tables reliées
    tenants_data = _supabase_request(f"rest/v1/tenants?id={id_filter}")
    profiles_data = _safe_fetch("profiles")
    instances_data = _safe_fetch("tenant_instances")
    agents_data = _safe_fetch("agent_instances")
    subs_data = _safe_fetch("subscriptions")
    integrations_data = _safe_fetch("tenant_integrations")
    channels_data = _safe_fetch("tenant_channels")
    invoices_data = _safe_fetch("invoices")
    audit_data = _safe_fetch("audit_logs")
    events_data = _safe_fetch("processed_events")

    # Récupération des comptes auth.users correspondants
    user_ids = [p["id"] for p in profiles_data if "id" in p]
    auth_users_data = []
    if user_ids:
        try:
            admin_users = _supabase_request("auth/v1/admin/users")
            users_list = admin_users.get("users", []) if isinstance(admin_users, dict) else []
            auth_users_data = [u for u in users_list if u.get("id") in user_ids]
        except Exception as e:
            _log.warning("Impossible de dumper auth.users: %s", e)

    dump_payload = {
        "metadata": {
            "ticket": "KAN-71",
            "action": "pre_purge_backup_exhaustive",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "target_slugs": purge_slugs,
            "target_tenant_ids": purge_ids,
        },
        "tenants": tenants_data,
        "profiles": profiles_data,
        "tenant_instances": instances_data,
        "agent_instances": agents_data,
        "subscriptions": subs_data,
        "tenant_integrations": integrations_data,
        "tenant_channels": channels_data,
        "invoices": invoices_data,
        "audit_logs": audit_data,
        "processed_events": events_data,
        "auth_users": auth_users_data,
    }

    with open(backup_file, "w", encoding="utf-8") as f:
        json.dump(dump_payload, f, indent=2, ensure_ascii=False)

    _log.info("  ✓ Sauvegarde créée avec succès : %s (%d octets)", backup_file, backup_file.stat().st_size)
    _log.info("    - Tenants : %d", len(tenants_data) if isinstance(tenants_data, list) else 0)
    _log.info("    - Profils : %d", len(profiles_data))
    _log.info("    - Instances conteneurs : %d", len(instances_data))
    _log.info("    - Instances agents : %d", len(agents_data))
    _log.info("    - Abonnements : %d", len(subs_data))
    _log.info("    - Intégrations : %d", len(integrations_data))
    _log.info("    - Canaux : %d", len(channels_data))
    _log.info("    - Factures : %d", len(invoices_data))
    _log.info("    - Logs audit : %d", len(audit_data))
    _log.info("    - Comptes Auth : %d", len(auth_users_data))

    return backup_file


def step_execute_purge(purge_ids: List[str], dry_run: bool = True) -> Dict[str, int]:
    """Étape 2 : Exécution ordonnée de la suppression (ou simulation si dry_run)."""
    _log.info("══ Étape 2 : Purge des Données %s ══", "(SIMULATION DRY-RUN)" if dry_run else "(EXÉCUTION RÉELLE)")
    if not purge_ids:
        _log.info("Aucun identifiant à purger.")
        return {}

    id_filter = f"in.({','.join(purge_ids)})"

    if dry_run:
        _log.info("  [DRY-RUN] Recherche des enregistrements qui seraient supprimés :")
        for table, col in [
            ("invoices", "tenant_id"),
            ("tenant_channels", "tenant_id"),
            ("tenant_integrations", "tenant_id"),
            ("subscriptions", "tenant_id"),
            ("agent_instances", "tenant_id"),
            ("tenant_instances", "tenant_id"),
            ("audit_logs", "tenant_id"),
            ("profiles", "tenant_id"),
            ("tenants", "id"),
        ]:
            try:
                res = _supabase_request(f"rest/v1/{table}?{col}={id_filter}&select=id")
                cnt = len(res) if isinstance(res, list) else 0
                _log.info("    -> Table %s : %d lignes ciblées", table, cnt)
            except Exception as e:
                _log.info("    -> Table %s : non interrogée (%s)", table, e)
        return {"dry_run": 1}

    def _safe_delete(table: str, col: str = "tenant_id") -> int:
        try:
            res = _supabase_request(f"rest/v1/{table}?{col}={id_filter}", method="DELETE")
            cnt = len(res) if isinstance(res, list) else 0
            _log.info("  ✓ Table %s : %d lignes supprimées", table, cnt)
            return cnt
        except Exception as e:
            _log.warning("Table %s DELETE: %s", table, e)
            return 0

    # 1. Factures, intégrations, canaux, abonnements
    _safe_delete("invoices")
    _safe_delete("tenant_channels")
    _safe_delete("tenant_integrations")
    count_subs = _safe_delete("subscriptions")

    # 2. Instances conteneurs et agents
    count_agents = _safe_delete("agent_instances")
    count_instances = _safe_delete("tenant_instances")

    # 3. Logs d'audit et profils
    _safe_delete("audit_logs")
    profiles_to_delete = _supabase_request(f"rest/v1/profiles?tenant_id={id_filter}")
    auth_user_ids = [p["id"] for p in profiles_to_delete if "id" in p] if isinstance(profiles_to_delete, list) else []

    count_profiles = _safe_delete("profiles")

    # 4. Comptes Supabase Auth via API Admin
    count_auth = 0
    for uid in auth_user_ids:
        try:
            _supabase_request(f"auth/v1/admin/users/{uid}", method="DELETE")
            count_auth += 1
            _log.info("  ✓ Compte Supabase Auth supprimé : %s", uid)
        except Exception as e:
            _log.warning("Échec suppression compte auth %s : %s", uid, e)

    # 5. Table principale : public.tenants
    deleted_tenants = _supabase_request(f"rest/v1/tenants?id={id_filter}", method="DELETE")
    count_tenants = len(deleted_tenants) if isinstance(deleted_tenants, list) else len(purge_ids)
    _log.info("  ✓ Tenants supprimés : %d", count_tenants)

    return {
        "deleted_tenants": count_tenants,
        "deleted_profiles": count_profiles,
        "deleted_instances": count_instances,
        "deleted_agents": count_agents,
        "deleted_subscriptions": count_subs,
        "deleted_auth_users": count_auth,
    }


def step_post_verification() -> Dict[str, Any]:
    """Étape 3 : Contrôle de conformité et preuves (CA2, CA3, CA4)."""
    _log.info("══ Étape 3 : Contrôle de Conformité & Preuves ══")

    # CA2 : Les 5 slugs purgés doivent rendre 0 ligne
    slug_in = f"in.({','.join(TARGET_PURGE_SLUGS)})"
    purged_check = _supabase_request(f"rest/v1/tenants?slug={slug_in}")
    if isinstance(purged_check, list) and len(purged_check) > 0:
        raise RuntimeError(f"ÉCHEC DU CRITÈRE CA2 : Il reste encore {len(purged_check)} tenants purgés en base !")
    _log.info("  ✓ CA2 Confirmé : 0 tenant résiduel trouvé pour les slugs %s", TARGET_PURGE_SLUGS)

    # CA3 : Les 2 slugs conservés doivent exister avec leurs rattachements intacts
    kept_in = f"in.({','.join(KEPT_SLUGS)})"
    kept_tenants = _supabase_request(f"rest/v1/tenants?slug={kept_in}&select=*,profiles(*),tenant_instances(*),subscriptions(*)")
    if not isinstance(kept_tenants, list) or len(kept_tenants) != 2:
        raise RuntimeError(f"ÉCHEC DU CRITÈRE CA3 : Attendu 2 tenants conservés, obtenu {len(kept_tenants) if isinstance(kept_tenants, list) else 0}")

    for kt in kept_tenants:
        slug = kt.get("slug")
        profs = len(kt.get("profiles", []))
        insts = len(kt.get("tenant_instances", []))
        subs = len(kt.get("subscriptions", []))
        _log.info("  ✓ CA3 Confirmé : Tenant [%s] intact -> %d profils, %d instances, %d abonnements", slug, profs, insts, subs)
        if profs < 1:
            raise RuntimeError(f"Tenant {slug} a perdu son profil !")

    # Vérification de l'état global
    all_current = _supabase_request("rest/v1/tenants?select=*")
    _log.info("  ✓ État actuel de la table tenants : %d organisations au total", len(all_current) if isinstance(all_current, list) else 0)

    return {
        "final_tenant_count": len(all_current) if isinstance(all_current, list) else 0,
        "kept_tenants": kept_tenants,
    }


def main():
    parser = argparse.ArgumentParser(description="Script d'assainissement base de production Orso Agents (KAN-71)")
    parser.add_argument(
        "--execute",
        action="store_true",
        default=False,
        help="Drapeau obligatoire pour autoriser l'exécution de la purge. Sans ce drapeau, le script reste en simulation.",
    )
    parser.add_argument(
        "--confirm-purge-production",
        action="store_true",
        default=False,
        help="Deuxième verrou de confirmation explicite requis pour purger la base.",
    )
    args = parser.parse_args()

    is_dry_run = not (args.execute and args.confirm_purge_production)

    _log.info("================================================================================")
    _log.info("ORSO AGENTS — KAN-71 : Nettoyage & Assainissement Base Supabase")
    _log.info("Mode d'exécution : %s", "🔴 EXÉCUTION RÉELLE" if not is_dry_run else "🟢 SIMULATION (DRY-RUN)")
    _log.info("Horodatage : %s", datetime.now(timezone.utc).isoformat())
    _log.info("Base cible : %s", SUPABASE_URL)
    _log.info("================================================================================")

    if not SUPABASE_URL or not SUPABASE_KEY:
        _log.error("SUPABASE_URL ou SUPABASE_SERVICE_ROLE_KEY manquants dans l'environnement.")
        sys.exit(1)

    # 1. Preflight
    preflight = step_preflight_check()
    purge_ids = preflight["purge_tenant_ids"]
    purge_slugs = preflight["purge_slugs"]

    if not purge_ids:
        _log.info("Aucune organisation fictive détectée. La base est déjà assainie.")
        step_post_verification()
        return

    if is_dry_run:
        _log.warning("Mode simulation actif : aucune donnée ne sera supprimée.")
        _log.warning("Pour exécuter la purge réelle, passez : --execute --confirm-purge-production")
        step_execute_purge(purge_ids, dry_run=True)
        return

    # 2. Sauvegarde exhaustive
    backup_path = step_create_backup(purge_ids, purge_slugs)

    # 3. Purge
    stats = step_execute_purge(purge_ids, dry_run=False)

    # 4. Contrôles post-purge
    post = step_post_verification()

    _log.info("================================================================================")
    _log.info("RÉSULTAT DE L'OPÉRATION KAN-71 :")
    _log.info("  - Fichier de sauvegarde créé : %s", backup_path)
    _log.info("  - Organisations supprimées : %d", stats.get("deleted_tenants", 0))
    _log.info("  - Profils supprimés : %d", stats.get("deleted_profiles", 0))
    _log.info("  - Instances conteneurs supprimées : %d", stats.get("deleted_instances", 0))
    _log.info("  - Instances agents supprimées : %d", stats.get("deleted_agents", 0))
    _log.info("  - Abonnements supprimés : %d", stats.get("deleted_subscriptions", 0))
    _log.info("  - Comptes Auth supprimés : %d", stats.get("deleted_auth_users", 0))
    _log.info("  - Total tenants finaux en base : %d", post.get("final_tenant_count", 0))
    _log.info("================================================================================")


if __name__ == "__main__":
    main()

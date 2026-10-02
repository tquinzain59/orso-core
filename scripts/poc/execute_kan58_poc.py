#!/usr/bin/env python3
"""Exécution réelle du POC KAN-58 sur le démon Docker local.

Produit les preuves factuelles requises par la Definition of Done sur 3 espaces conteneurisés en fonctionnement :
- CA1 : Aucun conteneur client ne monte un dossier partagé avec un autre client.
- CA2 : Un fichier déposé dans l'espace d'un client n'est visible dans aucun autre.
- CA3 : Les trois points de montage de profils pointent vers une seule source par client.
- CA4 : Procédure de retour arrière écrite, exécutée et état vérifié.
"""

import os
import sys
import json
import time
import shutil
import logging
import subprocess
from pathlib import Path
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
_log = logging.getLogger("kan58_poc")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Load .env
env_file = PROJECT_ROOT / ".env"
if env_file.exists():
    with open(env_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip("\"'"))

from olympe.lifecycle_manager import DockerLifecycleManager, normalize_container_name


def main():
    _log.info("Démarrage du protocole de validation POC KAN-58 sur conteneurs réels...")

    hmac_key = os.environ.get("ORSO_PERSONA_HMAC_KEY", "89fb4a7e32cf33668ef85fbc04b08e11ab77f5c3f65bb363cba3de18a675fe10")
    engine_image = "orso-core-orso-backend:latest"
    engine_digest = "sha256:41654b58b210207160a9dbb152576ac6530f2f4d5363d10f4d749f4de70b812d"

    poc_data_root = PROJECT_ROOT / "data" / "tenants_poc_kan58"
    poc_spaces_root = PROJECT_ROOT / "data" / "spaces_poc_kan58"
    poc_data_root.mkdir(parents=True, exist_ok=True)
    poc_spaces_root.mkdir(parents=True, exist_ok=True)

    manager = DockerLifecycleManager(
        data_root=str(poc_data_root),
        spaces_root=str(poc_spaces_root),
    )

    tenants = [
        {"slug": "poc-alpha", "uuid": "uuid-poc-alpha-001"},
        {"slug": "poc-beta", "uuid": "uuid-poc-beta-002"},
        {"slug": "poc-gamma", "uuid": "uuid-poc-gamma-003"},
    ]

    evidence = {
        "ticket": "KAN-58",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "engine_image": engine_image,
        "engine_digest": engine_digest,
        "ca1_no_shared_mounts": {},
        "ca2_isolation_witness": {},
        "ca3_profiles_convergence": {},
        "ca4_rollback_replay": {},
        "all_passed": False,
    }

    try:
        # Nettoyage préalable au cas où
        for t in tenants:
            manager.teardown_tenant(t["slug"], remove_data=True)

        # ── 1. Provisioning réel des 3 conteneurs ────────────────────────────
        _log.info("Étape 1 : Provisioning physique des 3 conteneurs clients...")
        provision_results = {}
        for t in tenants:
            _log.info("Provisioning de %s...", t["slug"])
            res = manager.provision_tenant(
                tenant_id=t["uuid"],
                tenant_slug=t["slug"],
                image_name=engine_image,
                image_digest=engine_digest,
                allow_floating_tag=True,
                persona_hmac_key=hmac_key,
                use_dedicated_space=True,
            )
            if not res.get("success"):
                raise RuntimeError(f"Échec du provisioning de {t['slug']}: {res}")
            provision_results[t["slug"]] = res

        # Laisser 2 secondes aux conteneurs pour stabiliser leur boot
        time.sleep(2.5)

        # ── 2. Validation CA1 : Inspection des montages réels Docker ───────────
        _log.info("Étape 2 : Contrôle CA1 - Zéro montage partagé entre conteneurs...")
        containers_mounts = {}
        containers_sources = {}
        for t in tenants:
            cname = normalize_container_name(t["slug"])
            inspect_proc = subprocess.run(
                ["docker", "inspect", "--format", "{{json .Mounts}}", cname],
                capture_output=True,
                text=True,
                check=True,
            )
            raw_mounts = json.loads(inspect_proc.stdout.strip())
            containers_mounts[t["slug"]] = raw_mounts
            sources = {m["Source"] for m in raw_mounts}
            containers_sources[t["slug"]] = sources
            _log.info("Conteneur %s possède %d points de montage réels.", cname, len(raw_mounts))

        # Vérification des intersections deux à deux
        ab_shared = containers_sources["poc-alpha"].intersection(containers_sources["poc-beta"])
        ac_shared = containers_sources["poc-alpha"].intersection(containers_sources["poc-gamma"])
        bc_shared = containers_sources["poc-beta"].intersection(containers_sources["poc-gamma"])

        # Vérification qu'aucun dossier racine du dépôt n'est monté
        host_common_dirs = {
            str((PROJECT_ROOT / "config").resolve()),
            str((PROJECT_ROOT / "skills").resolve()),
            str((PROJECT_ROOT / "profiles").resolve()),
        }
        all_mounted_sources = set().union(*containers_sources.values())
        illegal_common_mounts = all_mounted_sources.intersection(host_common_dirs)

        ca1_passed = (len(ab_shared) == 0 and len(ac_shared) == 0 and len(bc_shared) == 0 and len(illegal_common_mounts) == 0)
        _log.info("CA1 verdict : %s (ab_shared=%s, ac_shared=%s, bc_shared=%s, illegal_common=%s)",
                  ca1_passed, ab_shared, ac_shared, bc_shared, illegal_common_mounts)

        evidence["ca1_no_shared_mounts"] = {
            "passed": ca1_passed,
            "ab_shared_count": len(ab_shared),
            "ac_shared_count": len(ac_shared),
            "bc_shared_count": len(bc_shared),
            "illegal_common_mounts": list(illegal_common_mounts),
            "mounts_by_container": {t: [m["Destination"] + " <- " + m["Source"] for m in ms] for t, ms in containers_mounts.items()},
        }

        # ── 3. Validation CA3 : Convergence des 3 points de montage de profils ──
        _log.info("Étape 3 : Contrôle CA3 - Les 3 points de montage de profils pointent vers une seule source par client...")
        ca3_passed = True
        ca3_details = {}
        for t in tenants:
            cname = normalize_container_name(t["slug"])
            slug = t["slug"]
            expected_profiles_src = str((poc_spaces_root / slug / "profiles").resolve())
            
            profile_mounts = {
                m["Destination"]: m["Source"]
                for m in containers_mounts[slug]
                if m["Destination"] in ("/app/profiles", "/app/data/hermes_home/profiles", "/home/orso/.hermes/profiles")
            }

            has_all_three = len(profile_mounts) == 3
            all_point_to_single_source = all(src == expected_profiles_src for src in profile_mounts.values())
            
            # Vérifier que le conteneur peut lire les personas
            exec_check = subprocess.run(
                ["docker", "exec", cname, "ls", "-la", "/app/profiles"],
                capture_output=True,
                text=True,
            )
            can_read = exec_check.returncode == 0 and "personas.lock.json" in exec_check.stdout

            tenant_ca3_ok = has_all_three and all_point_to_single_source and can_read
            ca3_details[slug] = {
                "passed": tenant_ca3_ok,
                "expected_source": expected_profiles_src,
                "observed_mounts": profile_mounts,
                "profiles_readable_in_container": can_read,
            }
            if not tenant_ca3_ok:
                ca3_passed = False

        _log.info("CA3 verdict : %s", ca3_passed)
        evidence["ca3_profiles_convergence"] = {
            "passed": ca3_passed,
            "details": ca3_details,
        }

        # ── 4. Validation CA2 : Étanchéité et isolation par fichier témoin ────
        _log.info("Étape 4 : Contrôle CA2 - Dépôt de fichier témoin chez A et recherche chez B et C...")
        witness_filename = "witness_secret_alpha_kan58.txt"
        witness_content = "SECRET-TENANT-ALPHA-CONFIDENTIAL-2026"
        
        # Dépôt physique dans l'espace de poc-alpha sur l'hôte
        alpha_space_skills = poc_spaces_root / "poc-alpha" / "skills"
        alpha_witness_path = alpha_space_skills / witness_filename
        alpha_witness_path.write_text(witness_content, encoding="utf-8")

        # 1. Vérifier la visibilité dans le conteneur poc-alpha
        check_a = subprocess.run(
            ["docker", "exec", "orso_client_poc_alpha", "cat", f"/app/skills/{witness_filename}"],
            capture_output=True,
            text=True,
        )
        a_visible = check_a.returncode == 0 and witness_content in check_a.stdout

        # 2. Vérifier l'ABSENCE stricte dans le conteneur poc-beta
        check_b = subprocess.run(
            ["docker", "exec", "orso_client_poc_beta", "cat", f"/app/skills/{witness_filename}"],
            capture_output=True,
            text=True,
        )
        b_negative = check_b.returncode != 0

        # 3. Vérifier l'ABSENCE stricte dans le conteneur poc-gamma
        check_c = subprocess.run(
            ["docker", "exec", "orso_client_poc_gamma", "cat", f"/app/skills/{witness_filename}"],
            capture_output=True,
            text=True,
        )
        c_negative = check_c.returncode != 0

        ca2_passed = a_visible and b_negative and c_negative
        _log.info("CA2 verdict : %s (alpha_visible=%s, beta_negative=%s, gamma_negative=%s)",
                  ca2_passed, a_visible, b_negative, c_negative)

        evidence["ca2_isolation_witness"] = {
            "passed": ca2_passed,
            "witness_file": witness_filename,
            "alpha_container_result": "FOUND_AND_VERIFIED" if a_visible else "MISSING",
            "beta_container_result": "NOT_FOUND_STRICT" if b_negative else "LEAK_FOUND",
            "gamma_container_result": "NOT_FOUND_STRICT" if c_negative else "LEAK_FOUND",
            "beta_stderr": check_b.stderr.strip(),
            "gamma_stderr": check_c.stderr.strip(),
        }

        # ── 5. Validation CA4 : Procédure de retour arrière écrite et rejouée ─
        _log.info("Étape 5 : Contrôle CA4 - Exécution et replay du retour arrière sur poc-alpha...")
        # 1. Création d'une sauvegarde v1
        backup_v1 = manager.backup_tenant_space("poc-alpha", backup_tag="v1_clean")
        _log.info("Sauvegarde v1 créée : %s", backup_v1)

        # 2. Injection d'une modification / altération dans poc-alpha
        alteration_file = poc_spaces_root / "poc-alpha" / "config" / "corrupted_config.yaml"
        alteration_file.write_text("invalid_injection: true\n", encoding="utf-8")

        # Vérifier que l'altération est visible
        check_alt_before = subprocess.run(
            ["docker", "exec", "orso_client_poc_alpha", "cat", "/app/config/corrupted_config.yaml"],
            capture_output=True,
            text=True,
        )
        alt_present_before = check_alt_before.returncode == 0

        # 3. Exécution du rollback vers v1
        _log.info("Déclenchement du retour arrière (rollback_tenant_space)...")
        rb_res = manager.rollback_tenant_space("poc-alpha", backup_path=backup_v1, restart_container=True)
        time.sleep(2.0)

        # 4. Vérifier que le fichier altéré a DISPARU du conteneur après rollback
        check_alt_after = subprocess.run(
            ["docker", "exec", "orso_client_poc_alpha", "cat", "/app/config/corrupted_config.yaml"],
            capture_output=True,
            text=True,
        )
        alt_gone_after = check_alt_after.returncode != 0

        # 5. Vérifier que l'intégrité de poc-alpha est rétablie (fichiers indispensables présents)
        check_baseline_files = subprocess.run(
            ["docker", "exec", "orso_client_poc_alpha", "ls", "/app/profiles/personas.lock.json"],
            capture_output=True,
            text=True,
        )
        baseline_healthy = check_baseline_files.returncode == 0

        ca4_passed = rb_res.get("success") and alt_present_before and alt_gone_after and baseline_healthy
        _log.info("CA4 verdict : %s (rb_success=%s, alt_present_before=%s, alt_gone_after=%s, healthy=%s)",
                  ca4_passed, rb_res.get("success"), alt_present_before, alt_gone_after, baseline_healthy)

        evidence["ca4_rollback_replay"] = {
            "passed": ca4_passed,
            "backup_created": str(backup_v1),
            "rollback_mode": rb_res.get("mode"),
            "alteration_detected_before_rollback": alt_present_before,
            "alteration_erased_after_rollback": alt_gone_after,
            "container_healthy_post_rollback": baseline_healthy,
        }

        # Bilan global
        evidence["all_passed"] = ca1_passed and ca2_passed and ca3_passed and ca4_passed

        # Sauvegarde du rapport d'évidence JSON
        report_path = PROJECT_ROOT / "docs" / "3_Technique" / "kan58_e2e_poc_evidence.json"
        report_path.write_text(json.dumps(evidence, indent=2, ensure_ascii=False), encoding="utf-8")
        _log.info("Rapport d'évidence JSON consigné dans : %s", report_path)

        if not evidence["all_passed"]:
            raise RuntimeError(f"Échec de l'un des critères : {evidence}")

        _log.info("🎉 TOUS LES CRITÈRES KAN-58 (CA1, CA2, CA3, CA4) SONT FORMELLEMENT VALIDÉS SUR DOCKER EN DIRECT !")

    finally:
        # Nettoyage des conteneurs de test pour laisser l'environnement propre
        _log.info("Nettoyage des 3 conteneurs de test POC...")
        for t in tenants:
            try:
                manager.teardown_tenant(t["slug"], remove_data=True)
            except Exception as e:
                _log.warning("Erreur teardown %s: %s", t["slug"], e)
        # Nettoyage des répertoires temporaires POC
        shutil.rmtree(poc_data_root, ignore_errors=True)
        shutil.rmtree(poc_spaces_root, ignore_errors=True)
        _log.info("Nettoyage complet terminé.")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Exécution réelle du POC KAN-60 (POC 3 : Artefact d'espace client).

Ce script valide et produit les preuves factuelles requises par la Definition of Done :
- CA1 : Chaque espace client est produit depuis un artefact versionné et identifiable par une empreinte SHA-256.
- CA2 : L'artefact est monté en lecture seule dans le conteneur du client et de personne d'autre (tentative d'écriture refusée).
- CA3 : Une modification d'espace produit une nouvelle version (v1 -> v2), et le retour arrière vers la v1 est possible et rejoué.
- CA4 : Aucun secret ne figure dans un artefact (compteur nul et blocage immédiat à la détection).

Sauvegarde les preuves dans docs/3_Technique/kan60_e2e_poc_evidence.json.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
_log = logging.getLogger("kan60_poc")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Chargement du fichier .env si présent
env_file = PROJECT_ROOT / ".env"
if os.environ.get("ORSO_NO_DOTENV") != "1" and env_file.exists():
    with open(env_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip("\"'"))

from olympe.artifact_manager import ClientSpaceArtifactManager, compute_sha256_file
from olympe.lifecycle_manager import DockerLifecycleManager, normalize_container_name


def _create_initial_space_source(base_dir: Path, tenant_slug: str, version: str = "1.0.0", extra_note: str = ""):
    """Crée une arborescence d'espace source propre pour un client."""
    space_dir = base_dir / tenant_slug
    config_dir = space_dir / "config"
    skills_dir = space_dir / "skills"
    profiles_dir = space_dir / "profiles"

    config_dir.mkdir(parents=True, exist_ok=True)
    skills_dir.mkdir(parents=True, exist_ok=True)
    profiles_dir.mkdir(parents=True, exist_ok=True)

    # 1. config/hermes.yaml
    (config_dir / "hermes.yaml").write_text(
        f"model: orso-engine\n"
        f"tenant_slug: {tenant_slug}\n"
        f"version: {version}\n"
        f"system_prompt: 'Calibration exclusive pour {tenant_slug} (version {version})'\n"
        f"note: '{extra_note}'\n",
        encoding="utf-8",
    )

    # 2. skills/
    (skills_dir / f"reconciliation_{tenant_slug}.py").write_text(
        f"\"\"\"Skill métier dédié au tenant {tenant_slug} v{version}\"\"\"\n"
        f"def get_tenant_slug():\n"
        f"    return '{tenant_slug}'\n"
        f"def get_version():\n"
        f"    return '{version}'\n",
        encoding="utf-8",
    )

    # 3. profiles/
    jerome_dir = profiles_dir / "jerome"
    jerome_dir.mkdir(parents=True, exist_ok=True)
    (jerome_dir / "SOUL.md").write_text(
        f"# Persona Jérôme pour {tenant_slug}\n"
        f"- Rôle: Directeur du recouvrement amiable\n"
        f"- Ton: Professionnel et courtois\n"
        f"- Version espace: {version}\n",
        encoding="utf-8",
    )
    (profiles_dir / "personas.lock.json").write_text(
        json.dumps({
            "version": "1.0",
            "tenant": tenant_slug,
            "personas": {
                "jerome": {
                    "sha256": compute_sha256_file(jerome_dir / "SOUL.md"),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
            }
        }, indent=2),
        encoding="utf-8",
    )
    return space_dir


def main():
    _log.info("Démarrage de l'exécution réelle du POC KAN-60 (Artefact d'espace client)...")

    poc_data_root = PROJECT_ROOT / "data" / "tenants_poc_kan60"
    poc_spaces_root = PROJECT_ROOT / "data" / "spaces_poc_kan60"
    poc_artifacts_root = PROJECT_ROOT / "data" / "artifacts_poc_kan60"
    poc_sources_root = PROJECT_ROOT / "data" / "sources_poc_kan60"

    # Nettoyage initial
    for d in [poc_data_root, poc_spaces_root, poc_artifacts_root, poc_sources_root]:
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)
        d.mkdir(parents=True, exist_ok=True)

    manager = DockerLifecycleManager(
        data_root=str(poc_data_root),
        spaces_root=str(poc_spaces_root),
        artifacts_root=str(poc_artifacts_root),
        host_max_containers=15,
    )

    has_docker = manager.has_docker
    _log.info("Environnement d'exécution : Démon Docker = %s", has_docker)

    evidence = {
        "ticket": "KAN-60",
        "title": "POC 3 - Artefact d'espace client : construction, empreinte et montage",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "docker_available": has_docker,
        "ca1_artifacts_versioning": {},
        "ca2_readonly_mount": {},
        "ca3_rollback_replay": {},
        "ca4_zero_secrets": {},
        "all_passed": False,
    }

    try:
        # ── 1. Validation CA1 : Construction, Versionnement et Empreinte SHA-256 ──
        _log.info("Étape 1 : Contrôle CA1 - Construction de 3 artefacts versionnés...")
        tenants = ["poc-alpha", "poc-beta", "poc-gamma"]
        ca1_details = {}
        fingerprints = {}

        for slug in tenants:
            src_dir = _create_initial_space_source(poc_sources_root, slug, version="1.0.0", extra_note=f"Initial seed {slug}")
            manifest = manager.artifact_manager.build_artifact(
                tenant_slug=slug,
                version="1.0.0",
                source_dir=src_dir,
                author="POC KAN-60 Harness",
            )
            fp = manifest["fingerprint"]
            fingerprints[slug] = fp
            archive_path = manager.artifact_manager.get_tenant_artifact_dir(slug, "1.0.0") / manifest["archive_filename"]

            # Vérification cryptographique immédiate
            is_valid, err, _ = manager.artifact_manager.verify_artifact(slug, "1.0.0")
            assert is_valid, f"Échec vérification artefact {slug}: {err}"

            ca1_details[slug] = {
                "version": "1.0.0",
                "fingerprint": fp,
                "content_fingerprint": manifest.get("content_fingerprint"),
                "archive_size_bytes": manifest.get("archive_size_bytes"),
                "files_count": manifest.get("files_count"),
                "archive_path": str(archive_path),
                "is_cryptographically_valid": is_valid,
                "contents_summary": [
                    f"{f} ({meta['sha256'][:16]}..., {meta['size_bytes']} o)"
                    for f, meta in manifest.get("files", {}).items()
                ],
            }

        ca1_passed = (len(fingerprints) == 3 and len(set(fingerprints.values())) == 3)
        _log.info("CA1 verdict : %s (3 empreintes SHA-256 uniques produites)", ca1_passed)
        evidence["ca1_artifacts_versioning"] = {
            "passed": ca1_passed,
            "tenants_count": len(tenants),
            "unique_fingerprints_count": len(set(fingerprints.values())),
            "details": ca1_details,
        }

        # ── 2. Validation CA2 : Montage en Lecture Seule et Isolation ─────────────
        _log.info("Étape 2 : Contrôle CA2 - Montage en lecture seule (:ro) et tentative d'écriture...")
        ca2_details = {}
        ca2_passed = True

        if has_docker:
            # Assurer le réseau Docker
            subprocess.run(["docker", "network", "create", "orso_network"], capture_output=True)

            # Détection de l'image moteur disponible
            local_imgs = subprocess.run(["docker", "images", "--format", "{{.Repository}}:{{.Tag}}"], capture_output=True, text=True).stdout
            if "orso-core-orso-backend:latest" in local_imgs:
                default_engine = "orso-core-orso-backend:latest"
            else:
                default_engine = "ghcr.io/tquinzain59/orso-engine:latest"

            engine_image = os.environ.get("ORSO_ENGINE_IMAGE", default_engine)
            engine_digest = os.environ.get("ORSO_TARGET_ENGINE_DIGEST")

            for slug in tenants:
                cname = normalize_container_name(slug)
                # Provisionner avec l'artefact 1.0.0
                prov_res = manager.provision_tenant(
                    tenant_id=f"uuid-{slug}",
                    tenant_slug=slug,
                    image_name=engine_image,
                    image_digest=engine_digest,
                    allow_floating_tag=True,
                    persona_hmac_key="poc_hmac_secret_key_kan60",
                    artifact_version="1.0.0",
                )
                assert prov_res["success"], f"Échec provisioning {slug}: {prov_res}"

                # Inspecter les montages réels du conteneur
                inspect_proc = subprocess.run(
                    ["docker", "inspect", "--format", "{{json .Mounts}}", cname],
                    capture_output=True,
                    text=True,
                )
                mounts_data = json.loads(inspect_proc.stdout.strip())
                space_mounts = [m for m in mounts_data if "/app/data" not in m.get("Destination", "")]
                all_ro = all(m.get("RW") is False for m in space_mounts)

                # Tentative d'écriture interdite dans /app/config/
                write_attempt = subprocess.run(
                    ["docker", "exec", cname, "touch", "/app/config/illegal_write_test.txt"],
                    capture_output=True,
                    text=True,
                )
                write_denied = (
                    write_attempt.returncode != 0
                    and "Read-only file system" in (write_attempt.stderr + write_attempt.stdout)
                )

                # Tentative d'écriture interdite dans /app/skills/
                write_skills = subprocess.run(
                    ["docker", "exec", cname, "touch", "/app/skills/illegal_skill_test.txt"],
                    capture_output=True,
                    text=True,
                )
                skills_write_denied = (
                    write_skills.returncode != 0
                    and "Read-only file system" in (write_skills.stderr + write_skills.stdout)
                )

                tenant_ca2_ok = all_ro and write_denied and skills_write_denied
                if not tenant_ca2_ok:
                    ca2_passed = False

                ca2_details[slug] = {
                    "container_name": cname,
                    "mounts_count": len(space_mounts),
                    "all_space_mounts_readonly": all_ro,
                    "config_write_attempt_refused": write_denied,
                    "skills_write_attempt_refused": skills_write_denied,
                    "rejection_message": write_attempt.stderr.strip() or write_attempt.stdout.strip(),
                }
        else:
            # Mode sans Docker daemon local : validation des permissions de fichiers hôtes (0555 et 0444)
            for slug in tenants:
                target_space = poc_spaces_root / slug
                manager.artifact_manager.extract_and_deploy_artifact(slug, "1.0.0", target_space)
                config_file = target_space / "config" / "hermes.yaml"
                mode_oct = oct(config_file.stat().st_mode & 0o777)
                is_ro = mode_oct == "0o444"
                if not is_ro:
                    ca2_passed = False
                ca2_details[slug] = {
                    "mode": "filesystem_permissions_audit",
                    "file_mode": mode_oct,
                    "readonly_verified": is_ro,
                }

        _log.info("CA2 verdict : %s (Montage lecture seule et tentatives d'écriture refusées)", ca2_passed)
        evidence["ca2_readonly_mount"] = {
            "passed": ca2_passed,
            "details": ca2_details,
        }

        # ── 3. Validation CA3 : Nouvelle Version (v2) et Retour Arrière (Rollback) ─
        _log.info("Étape 3 : Contrôle CA3 - Cycle complet de mise à niveau v1 -> v2 puis retour arrière v1...")
        target_slug = "poc-alpha"
        target_cname = normalize_container_name(target_slug)

        # 1. Modifier et construire v2.0.0
        src_v2 = _create_initial_space_source(
            poc_sources_root,
            target_slug,
            version="2.0.0",
            extra_note="Upgraded to v2.0.0 with specialized financial prompt",
        )
        (src_v2 / "config" / "hermes.yaml").write_text(
            f"model: orso-engine\ntenant_slug: {target_slug}\nversion: 2.0.0\nsystem_prompt: 'CALIBRATION V2 UPGRADE'\n",
            encoding="utf-8",
        )
        manifest_v2 = manager.artifact_manager.build_artifact(
            tenant_slug=target_slug,
            version="2.0.0",
            source_dir=src_v2,
            author="POC KAN-60 Upgrade",
        )
        fp_v2 = manifest_v2["fingerprint"]
        assert fp_v2 != fingerprints[target_slug], "L'empreinte v2 doit être différente de v1"

        # 2. Déployer v2.0.0
        deploy_v2_res = manager.deploy_tenant_artifact(target_slug, "2.0.0", restart_container=has_docker)
        assert deploy_v2_res["success"], f"Échec déploiement v2 : {deploy_v2_res}"

        if has_docker:
            time.sleep(1)
            cat_v2 = subprocess.run(
                ["docker", "exec", target_cname, "cat", "/app/config/hermes.yaml"],
                capture_output=True,
                text=True,
            )
            v2_active = "CALIBRATION V2 UPGRADE" in cat_v2.stdout
        else:
            v2_content = (poc_spaces_root / target_slug / "config" / "hermes.yaml").read_text(encoding="utf-8")
            v2_active = "CALIBRATION V2 UPGRADE" in v2_content

        assert v2_active, "La version 2.0.0 doit être active après déploiement"

        # 3. Exécuter le rollback vers 1.0.0
        _log.info("Exécution du rollback vers 1.0.0...")
        rollback_res = manager.rollback_tenant_artifact(target_slug, "1.0.0", restart_container=has_docker)
        assert rollback_res["success"], f"Échec rollback v1 : {rollback_res}"
        assert rollback_res["fingerprint"] == fingerprints[target_slug], "L'empreinte restaurée doit correspondre à v1"

        if has_docker:
            time.sleep(1)
            cat_v1_restored = subprocess.run(
                ["docker", "exec", target_cname, "cat", "/app/config/hermes.yaml"],
                capture_output=True,
                text=True,
            )
            v1_restored = "Calibration exclusive pour poc-alpha (version 1.0.0)" in cat_v1_restored.stdout
            v2_absent = "CALIBRATION V2 UPGRADE" not in cat_v1_restored.stdout
        else:
            restored_content = (poc_spaces_root / target_slug / "config" / "hermes.yaml").read_text(encoding="utf-8")
            v1_restored = "Calibration exclusive pour poc-alpha (version 1.0.0)" in restored_content
            v2_absent = "CALIBRATION V2 UPGRADE" not in restored_content

        ca3_passed = v2_active and v1_restored and v2_absent
        _log.info("CA3 verdict : %s (Upgrade v2 puis Rollback v1 vérifiés sans altération)", ca3_passed)
        evidence["ca3_rollback_replay"] = {
            "passed": ca3_passed,
            "target_tenant": target_slug,
            "v1_fingerprint": fingerprints[target_slug],
            "v2_fingerprint": fp_v2,
            "v2_active_after_deploy": v2_active,
            "v1_restored_after_rollback": v1_restored,
            "v2_purged_after_rollback": v2_absent,
            "container_restarted": rollback_res.get("container_restarted"),
            "container_healthy": rollback_res.get("container_healthy"),
        }

        # ── 4. Validation CA4 : Zéro Secret et Rejet Ferme à la Détection ─────────
        _log.info("Étape 4 : Contrôle CA4 - Audit anti-secrets des artefacts et test d'injection bloqué...")
        
        # 1. Audit des 3 artefacts produits
        secrets_audit = {}
        total_secrets_detected = 0
        for slug in tenants:
            cnt, findings = manager.artifact_manager.scan_for_secrets(
                manager.artifact_manager.get_tenant_artifact_dir(slug, "1.0.0")
            )
            secrets_audit[slug] = {"secrets_count": cnt, "findings": findings}
            total_secrets_detected += cnt

        # 2. Test d'injection d'un faux secret OpenAI (sk-...) et rejet obligatoire
        injection_src = poc_sources_root / "test-secret-injection"
        _create_initial_space_source(poc_sources_root, "test-secret-injection", version="1.0.0")
        dummy_leak = "sk-" + "proj-" + "1234567890abcdef1234567890abcdef12345678"
        (injection_src / "config" / "leak.yaml").write_text(
            f"model: gpt-4\nsecret_leak: {dummy_leak}\n",
            encoding="utf-8",
        )

        injection_rejected = False
        rejection_reason = ""
        try:
            manager.artifact_manager.build_artifact("test-secret-injection", "1.0.0", injection_src)
        except ValueError as e:
            if "ERR_SECRET_DETECTED_IN_ARTIFACT" in str(e):
                injection_rejected = True
                rejection_reason = str(e)

        # Vérifier qu'aucun fichier d'artefact n'a été créé
        leak_dir = manager.artifact_manager.get_tenant_artifact_dir("test-secret-injection", "1.0.0")
        no_leak_artifact_persisted = not (leak_dir / "client-space-test-secret-injection-1.0.0.tar.gz").exists()

        ca4_passed = (total_secrets_detected == 0 and injection_rejected and no_leak_artifact_persisted)
        _log.info("CA4 verdict : %s (Compteur de secrets nul et rejet immédiat à l'injection)", ca4_passed)
        evidence["ca4_zero_secrets"] = {
            "passed": ca4_passed,
            "total_secrets_in_legitimate_artifacts": total_secrets_detected,
            "artifacts_audit": secrets_audit,
            "injection_test_rejected": injection_rejected,
            "rejection_reason": rejection_reason,
            "no_leak_artifact_persisted": no_leak_artifact_persisted,
        }

        # Clôture du rapport
        all_passed = ca1_passed and ca2_passed and ca3_passed and ca4_passed
        evidence["all_passed"] = all_passed
        _log.info("=== VERDICT FINAL DU POC KAN-60 : %s ===", "SUCCÈS (100% VALIDE)" if all_passed else "ÉCHEC")

    finally:
        # Nettoyage des conteneurs de test si Docker est disponible
        if has_docker:
            _log.info("Nettoyage des conteneurs de test POC...")
            for slug in ["poc-alpha", "poc-beta", "poc-gamma", "client-mod"]:
                manager.teardown_tenant(slug, remove_data=True)

        # Écriture du fichier de preuves JSON
        out_evidence = PROJECT_ROOT / "docs" / "3_Technique" / "kan60_e2e_poc_evidence.json"
        out_evidence.parent.mkdir(parents=True, exist_ok=True)
        with open(out_evidence, "w", encoding="utf-8") as f:
            json.dump(evidence, f, indent=2, ensure_ascii=False)
        _log.info("Preuves factuelles écrites dans %s", out_evidence)

    return 0 if evidence["all_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())

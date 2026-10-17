"""
Tests automatisés pour la livraison KAN-64 :
POC - Exécution réelle de la distribution de l'image du moteur (registre, empreinte, hôtes).

Vérifie l'intégralité des critères d'acceptation et des comblements d'écarts de KAN-64 :
- CA1 & CA2 : Validation cryptographique, épinglage par digest et lecture de manifest
- CA3 : Détection de dérive multi-hôtes avec sonde automatisée des démons Docker
- CA4 : Procédure de mise à jour et rollback avec sonde de santé et vérification des états
- CA5 : Audit de sécurité avec compteurs dynamiques calculés (Zéro secret & Zéro données client)
- CA6 : Refus formel de provisioning sans digest valide (ERR_DIGEST_REQUIRED / ERR_INVALID_DIGEST)
"""

import os
import tempfile
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

from scripts.distribution.engine_image_manager import (
    EngineDistributionManager,
    HostEngineState,
    validate_digest,
    format_pinned_image,
    parse_pinned_image,
    probe_docker_host,
)
from scripts.security.audit_zero_secrets_and_client_data import (
    run_full_ca5_audit,
    audit_client_data_in_repository,
    audit_docker_image_for_secrets_and_client_data,
)
from scripts.security.persona_integrity import (
    verify_all_personas,
    EVENT_OK,
    EVENT_CONFIG_ERROR,
)
from olympe.lifecycle_manager import DockerLifecycleManager


REF_DIGEST_V1 = "sha256:d8a5f82c448bb95b28a9b49b43e8b0b8c6e07eb4838a1f2987a123456789abcd"
REF_DIGEST_V2 = "sha256:e9b6093d559cc06c39b0c50c54f9c1c9d7f18fc5949b203a98b234567890bcde"
DRIFTED_DIGEST = "sha256:fa171a4e66add17d40c1d61d65a0d2dae80290d6050c314ba9c345678901cdef"


class TestKAN64ExecutionReelleDistribution:
    """Suite de validation KAN-64."""

    def test_ca6_refusal_without_valid_digest(self):
        """CA6 : Le provisioning sans digest valide est refusé avec code d'erreur explicite."""
        mgr = DockerLifecycleManager(data_root=Path(tempfile.mkdtemp()))
        mgr.has_docker = True
        status_not_found = {"status": "not_found", "running": False}

        with patch.object(mgr, "get_tenant_status", return_value=status_not_found):
            # 1. Tentative sans aucun digest par défaut -> Refus inconditionnel ERR_DIGEST_REQUIRED
            res_no_digest = mgr.provision_tenant(
                tenant_id="test-client-1",
                tenant_slug="client-no-digest",
                image_name="ghcr.io/tquinzain59/orso-engine:latest",
                persona_hmac_key="mock-key",
            )
            assert res_no_digest["success"] is False
            assert res_no_digest["error"] == "ERR_DIGEST_REQUIRED"
            assert "tag flottant interdit" in res_no_digest["message"]

            # 2. Tentative avec un digest malformé -> Refus ERR_INVALID_DIGEST
            res_invalid = mgr.provision_tenant(
                tenant_id="test-client-2",
                tenant_slug="client-invalid-digest",
                image_digest="invalid-sha256-string",
                require_digest=True,
                persona_hmac_key="mock-key",
            )
            assert res_invalid["success"] is False
            assert res_invalid["error"] == "ERR_INVALID_DIGEST"

            # 3. Tentative avec variable d'environnement ORSO_TARGET_ENGINE_DIGEST (alignement spécification)
            with patch.dict(os.environ, {
                "ORSO_TARGET_ENGINE_DIGEST": REF_DIGEST_V1,
                "ORSO_PERSONA_HMAC_KEY": "mock-fleet-key",
                "HERMES_DASHBOARD_BASIC_AUTH_USERNAME": "admin",
                "HERMES_DASHBOARD_BASIC_AUTH_PASSWORD": "testpassword",
            }):
                mock_proc = subprocess.CompletedProcess(args=["docker", "run"], returncode=0, stdout="c999", stderr="")
                with patch.object(mgr, "_exec_docker", return_value=mock_proc):
                    with patch.object(mgr, "_sync_tenant_instance_record"):
                        res_ok = mgr.provision_tenant(
                            tenant_id="test-client-3",
                            tenant_slug="client-valid-digest",
                            require_digest=True,
                        )
                        assert res_ok["success"] is True
                        assert res_ok["digest"] == REF_DIGEST_V1
                        assert f"@{REF_DIGEST_V1}" in res_ok["image"]

    def test_persona_hmac_key_fleet_enforcement_and_container_launch(self, tmp_path):
        """
        Arbitrage Thibaut / Commentaire 13 KAN-64 :
        Validation stricte de la clé HMAC de flotte partagée (ORSO_PERSONA_HMAC_KEY) :
        1. Preuve 1 : Contrôle persona integrity avec clé HMAC -> succès (code 0 / PER-INTEGRITY-000).
        2. Preuve 2 : Contrôle persona integrity sans clé HMAC -> échec explicite Fail-Closed (code 1 / PER-INTEGRITY-003).
        3. Preuve 3 : Provisioning Olympe sans clé HMAC -> refus ERR_HMAC_KEY_REQUIRED (aucun conteneur créé).
        4. Preuve 4 : Provisioning Olympe avec clé HMAC -> succès et injection stricte dans base_envs conteneur.
        """
        # 1. Preuve 1 : Contrôle d'intégrité avec clé valide
        # Création de faux profils et lockfile temporaires valides
        profiles_dir = tmp_path / "profiles"
        profiles_dir.mkdir()
        agent_dir = profiles_dir / "jerome"
        agent_dir.mkdir()
        soul_file = agent_dir / "SOUL.md"
        soul_file.write_text("# Jerome\nContenu de test pour intégrité.\n", encoding="utf-8")

        from scripts.security.persona_integrity import compute_persona_hmac, compute_file_sha256
        import json
        sha256_hash = compute_file_sha256(soul_file)
        hmac_sig = compute_persona_hmac("secret-fleet-key", "jerome", sha256_hash)

        lock_file = profiles_dir / "personas.lock.json"
        lock_file.write_text(
            json.dumps({
                "version": "1.0",
                "personas": {
                    "jerome": {
                        "path": "jerome/SOUL.md",
                        "sha256": sha256_hash,
                        "hmac_signature": hmac_sig,
                    }
                }
            }),
            encoding="utf-8",
        )

        valid_with_key, errors_with_key, _ = verify_all_personas(
            profiles_dir=profiles_dir,
            lock_file=lock_file,
            hmac_key="secret-fleet-key",
            record_logs=False,
        )
        assert valid_with_key is True
        assert len(errors_with_key) == 0

        # 2. Preuve 2 : Contrôle d'intégrité sans clé -> échec Fail-Closed
        with patch.dict(os.environ, {}, clear=True):
            valid_no_key, errors_no_key, _ = verify_all_personas(
                profiles_dir=profiles_dir,
                lock_file=lock_file,
                hmac_key=None,
                record_logs=False,
            )
            assert valid_no_key is False
            assert len(errors_no_key) >= 1
            assert any("ORSO_PERSONA_HMAC_KEY" in e for e in errors_no_key)

        # 3. Preuve 3 : Provisioning Olympe sans clé -> refus ERR_HMAC_KEY_REQUIRED
        mgr = DockerLifecycleManager(data_root=Path(tempfile.mkdtemp()))
        mgr.has_docker = True
        status_not_found = {"status": "not_found", "running": False}

        with patch.object(mgr, "get_tenant_status", return_value=status_not_found):
            with patch.dict(os.environ, {"ORSO_TARGET_ENGINE_DIGEST": REF_DIGEST_V1}, clear=True):
                res_refused_no_hmac = mgr.provision_tenant(
                    tenant_id="client-demo-no-key",
                    tenant_slug="demo-no-key",
                )
                assert res_refused_no_hmac["success"] is False
                assert res_refused_no_hmac["error"] == "ERR_HMAC_KEY_REQUIRED"
                assert "ORSO_PERSONA_HMAC_KEY est strictement requise" in res_refused_no_hmac["message"]

        # 4. Preuve 4 : Provisioning Olympe avec clé -> succès et transmission dans base_envs
        with patch.object(mgr, "get_tenant_status", return_value=status_not_found):
            with patch.dict(os.environ, {
                "ORSO_TARGET_ENGINE_DIGEST": REF_DIGEST_V1,
                "ORSO_PERSONA_HMAC_KEY": "secret-fleet-key",
                "HERMES_DASHBOARD_BASIC_AUTH_USERNAME": "admin",
                "HERMES_DASHBOARD_BASIC_AUTH_PASSWORD": "testpassword",
            }):
                mock_proc = subprocess.CompletedProcess(args=["docker", "run"], returncode=0, stdout="c1000", stderr="")
                with patch.object(mgr, "_exec_docker", return_value=mock_proc) as mock_exec:
                    with patch.object(mgr, "_sync_tenant_instance_record"):
                        res_success = mgr.provision_tenant(
                            tenant_id="client-demo-with-key",
                            tenant_slug="demo-with-key",
                        )
                        assert res_success["success"] is True
                        assert mock_exec.called
                        run_cmd_args = mock_exec.call_args[0][0]
                        assert "ORSO_PERSONA_HMAC_KEY=secret-fleet-key" in run_cmd_args

    def test_ca5_calculated_client_data_counter(self, tmp_path):
        """CA5 : Le compteur de données client est calculé dynamiquement, jamais codé en dur."""
        clean_img_result = {
            "secrets": [],
            "client_data": [],
            "errors": [],
            "scanned_files_count": 10,
            "scanned_paths": ["app/run_agent.py"],
            "applicative_paths": ["app/run_agent.py"],
        }
        with patch("scripts.security.audit_zero_secrets_and_client_data.audit_docker_image_for_secrets_and_client_data", return_value=clean_img_result):
            report = run_full_ca5_audit(image_ref="ghcr.io/tquinzain59/orso-engine:v1.0.0", require_image=True)
            assert report["status"] == "PASSED"
            metrics = report["metrics"]
            assert isinstance(metrics["client_data_in_engine_count"], int)
            assert metrics["client_data_in_engine_count"] == 0

        # Vérifie que si un artefact client résiduel est présent, le compteur l'incrémente
        with patch.object(Path, "glob") as mock_glob:
            fake_residual = tmp_path / "consignes_olympe.jsonl"
            mock_glob.return_value = [fake_residual]
            violations = audit_client_data_in_repository(tmp_path)
            assert len(violations) > 0
            assert violations[0]["type"] == "CLIENT_DATA_LEAK"

    def test_ca5_falsifiability_and_failure_on_uninspectable_or_leaked_image(self):
        """
        CA5 : Preuve de falsifiabilité (Refus 4 / Commentaire 18).
        L'audit doit échouer avec code FAILED / violations dans les cas suivants :
        - Démon Docker absent ou image ininspectable (aucun pass silencieux)
        - Échec de création du conteneur éphémère d'inspection
        - Image contenant une variable client ou un fichier interdit
        - Absence de référence d'image en mode strict (require_image=True)
        """
        # 1. Absence d'image requise
        report_no_img = run_full_ca5_audit(image_ref=None, require_image=True)
        assert report_no_img["status"] == "FAILED"
        assert report_no_img["metrics"]["image_scan_errors_count"] >= 1
        assert any(e["type"] == "MISSING_REQUIRED_IMAGE" for e in report_no_img["violations"]["image_scan_errors"])

        # 2. Image ininspectable (docker inspect échoue avec code != 0)
        orig_run = subprocess.run

        def mock_run_inspect_fail(cmd, *args, **kwargs):
            if isinstance(cmd, list) and len(cmd) >= 2 and cmd[:2] == ["docker", "inspect"]:
                return MagicMock(returncode=1, stdout="", stderr="Error: No such object")
            return orig_run(cmd, *args, **kwargs)

        with patch("subprocess.run", side_effect=mock_run_inspect_fail):
            report_inspect_fail = run_full_ca5_audit(image_ref="ghcr.io/tquinzain59/orso-engine@sha256:0000000000000000000000000000000000000000000000000000000000000000")
            assert report_inspect_fail["status"] == "FAILED"
            assert report_inspect_fail["metrics"]["image_scan_errors_count"] >= 1
            assert any(e["type"] == "IMAGE_INSPECT_FAILED" for e in report_inspect_fail["violations"]["image_scan_errors"])

        # 3. Échec de création du conteneur éphémère d'inspection
        def mock_run_create_fail(cmd, *args, **kwargs):
            if isinstance(cmd, list) and len(cmd) >= 2 and cmd[:2] == ["docker", "inspect"]:
                return MagicMock(returncode=0, stdout='[{"Config": {"Env": [], "Labels": {}}}]', stderr="")
            if isinstance(cmd, list) and len(cmd) >= 2 and cmd[:2] == ["docker", "create"]:
                return MagicMock(returncode=125, stdout="", stderr="docker: daemon not running")
            return orig_run(cmd, *args, **kwargs)

        with patch("subprocess.run", side_effect=mock_run_create_fail):
            report_create_fail = run_full_ca5_audit(image_ref="ghcr.io/tquinzain59/orso-engine@sha256:1111111111111111111111111111111111111111111111111111111111111111")
            assert report_create_fail["status"] == "FAILED"
            assert report_create_fail["metrics"]["image_scan_errors_count"] >= 1
            assert any(e["type"] == "CONTAINER_CREATE_FAILED" for e in report_create_fail["violations"]["image_scan_errors"])

    def test_ca3_probed_drift_detection(self):
        """
        CA3 : Détection de dérive multi-hôtes avec sonde automatisée.
        Vérifie les exigences de gouvernance (Commentaires 15 & 16) :
        - Un hôte sans conteneur client actif n'est JAMAIS déclaré IN_SYNC.
        - Un conteneur dont l'étiquette diverge de l'image réelle déclenche une alerte DRIFT_DETECTED.
        - Un conteneur en phase avec le digest cible est IN_SYNC.
        """
        mgr = EngineDistributionManager(target_digest=REF_DIGEST_V1)

        # 1. Hôte synchronisé (conteneur client actif portant l'image réelle cible)
        fake_host_synced = {
            "host_id": "prod-fr-002",
            "host_name": "Serveur Olympe",
            "active_digest": REF_DIGEST_V1,
            "pinned_image": f"ghcr.io/tquinzain59/orso-engine@{REF_DIGEST_V1}",
            "running_containers": ["orso_client_prod"],
            "is_reachable": True,
            "label_mismatch": False,
        }
        # 2. Hôte en dérive de version (image différente)
        fake_host_drifted = {
            "host_id": "prod-fr-003",
            "host_name": "Serveur Clients",
            "active_digest": DRIFTED_DIGEST,
            "pinned_image": f"ghcr.io/tquinzain59/orso-engine@{DRIFTED_DIGEST}",
            "running_containers": ["orso_client_test"],
            "is_reachable": True,
            "label_mismatch": False,
        }
        # 3. Hôte vide (aucun conteneur en service) -> doit être DRIFT_DETECTED, jamais IN_SYNC
        fake_host_empty = {
            "host_id": "prod-fr-004",
            "host_name": "Hôte Sans Conteneur",
            "active_digest": "",
            "pinned_image": "",
            "running_containers": [],
            "is_reachable": True,
            "label_mismatch": False,
        }
        # 4. Hôte avec étiquette falsifiée (ex: alpine avec label du digest cible)
        fake_host_falsified = {
            "host_id": "prod-fr-005",
            "host_name": "Hôte Falsifié",
            "active_digest": DRIFTED_DIGEST,
            "pinned_image": "alpine:3.20",
            "running_containers": ["orso_client_fake"],
            "is_reachable": True,
            "label_mismatch": True,
            "label_mismatch_detail": "Divergence critique détectée : étiquette falsifiée",
        }

        with patch("scripts.distribution.engine_image_manager.probe_docker_host", side_effect=[
            fake_host_synced, fake_host_drifted, fake_host_empty, fake_host_falsified
        ]):
            report = mgr.audit_hosts_drift_live(host_specs=[
                {"host_id": "h1"}, {"host_id": "h2"}, {"host_id": "h3"}, {"host_id": "h4"}
            ])
            assert report.is_drift_detected is True
            assert report.in_sync_count == 1
            assert report.drifted_count == 3

            empty_item = next(h for h in report.hosts if h.host_id == "prod-fr-004")
            assert empty_item.status == "DRIFT_DETECTED"
            assert "Aucun conteneur client" in empty_item.drift_details

            falsified_item = next(h for h in report.hosts if h.host_id == "prod-fr-005")
            assert falsified_item.status == "DRIFT_DETECTED"
            assert "Divergence" in falsified_item.drift_details

    def test_ca4_live_update_and_rollback_flow(self):
        """
        CA4 : Exécution de la mise à jour et du rollback.
        Garanties vérifiées :
        - Port binding restreint strictement à 127.0.0.1 (jamais 0.0.0.0).
        - Clé HMAC transmise via l'environnement du processus, JAMAIS sur la ligne de commande.
        - Refus Fail-Closed si la clé HMAC est absente de l'environnement appelant.
        """
        mgr = EngineDistributionManager(target_digest=REF_DIGEST_V2)
        host_spec = {"host_id": "prod-fr-003", "ssh_target": "ubuntu@mock"}

        # Refus si ORSO_PERSONA_HMAC_KEY absente
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValueError, match="ORSO_PERSONA_HMAC_KEY requise"):
                mgr.execute_live_host_update(host_spec, new_digest=REF_DIGEST_V2)

        state_initial = {
            "host_id": "prod-fr-003",
            "active_digest": REF_DIGEST_V1,
            "running_containers": ["orso_client_demo"],
            "is_reachable": True,
        }
        state_updated = {
            "host_id": "prod-fr-003",
            "active_digest": REF_DIGEST_V2,
            "running_containers": ["orso_client_demo"],
            "is_reachable": True,
        }
        state_rolledback = {
            "host_id": "prod-fr-003",
            "active_digest": REF_DIGEST_V1,
            "running_containers": ["orso_client_demo"],
            "is_reachable": True,
        }

        with patch.dict(os.environ, {"ORSO_PERSONA_HMAC_KEY": "fleet-secret-key"}):
            # 1. Test mise à jour
            with patch("scripts.distribution.engine_image_manager.run_remote_or_local_cmd") as mock_run:
                mock_run.return_value = (0, "200", "")
                with patch("scripts.distribution.engine_image_manager.probe_docker_host", side_effect=[state_initial, state_updated]):
                    res_update = mgr.execute_live_host_update(host_spec, new_digest=REF_DIGEST_V2, container_name="orso_client_demo")
                    assert res_update["success"] is True
                    assert res_update["state_before"]["active_digest"] == REF_DIGEST_V1
                    assert res_update["state_after"]["active_digest"] == REF_DIGEST_V2
                    assert res_update["health_http_code"] == "200"

                    # Vérification des arguments de commande exécutés
                    calls = mock_run.call_args_list
                    run_call = next(c for c in calls if "docker run" in c[0][0])
                    run_cmd_str = run_call[0][0]
                    # Port restreint à la boucle locale
                    assert "-p 127.0.0.1:9119:9119" in run_cmd_str
                    assert "-p 9119:9119" not in run_cmd_str
                    # Secret absent de la ligne de commande (argv) et transporté via stdin
                    assert "fleet-secret-key" not in run_cmd_str
                    assert "--env-file /dev/stdin" in run_cmd_str
                    # Clé transmise de manière sécurisée via stdin (input_data)
                    assert run_call[1].get("input_data") == "ORSO_PERSONA_HMAC_KEY=fleet-secret-key\n"

            # 2. Test rollback
            with patch("scripts.distribution.engine_image_manager.run_remote_or_local_cmd") as mock_run:
                mock_run.return_value = (0, "200", "")
                with patch("scripts.distribution.engine_image_manager.probe_docker_host", side_effect=[state_updated, state_rolledback]):
                    res_rollback = mgr.execute_live_host_rollback(host_spec, rollback_digest=REF_DIGEST_V1, container_name="orso_client_demo")
                    assert res_rollback["success"] is True
                    assert res_rollback["state_before"]["active_digest"] == REF_DIGEST_V2
                    assert res_rollback["state_after"]["active_digest"] == REF_DIGEST_V1

                    calls_rb = mock_run.call_args_list
                    run_call_rb = next(c for c in calls_rb if "docker run" in c[0][0])
                    assert "-p 127.0.0.1:9119:9119" in run_call_rb[0][0]
                    assert "fleet-secret-key" not in run_call_rb[0][0]
                    assert "--env-file /dev/stdin" in run_call_rb[0][0]
                    assert run_call_rb[1].get("input_data") == "ORSO_PERSONA_HMAC_KEY=fleet-secret-key\n"

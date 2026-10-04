"""
Tests automatisés pour la livraison d'architecture KAN-63 :
Distribution et versionnement de l'image du moteur vers les hôtes clients.

Couvre l'intégralité des 5 critères d'acceptation :
- CA1 : Note d'architecture et justification économique (ADR 2026-09-30-04)
- CA2 : Épinglage et vérification par empreinte cryptographique (Digest SHA-256)
- CA3 : Détection de dérive de version entre hôtes (test d'écart volontaire)
- CA4 : Procédure de mise à jour et retour arrière rejouable
- CA5 : Audit zéro secret de registre et zéro donnée client
"""

import os
import tempfile
from pathlib import Path
import pytest

from scripts.distribution.engine_image_manager import (
    EngineDistributionManager,
    validate_digest,
    format_pinned_image,
    parse_pinned_image,
    HostEngineState,
)
from scripts.security.audit_zero_secrets_and_client_data import run_full_ca5_audit
from olympe.lifecycle_manager import DockerLifecycleManager


REF_DIGEST_V1 = "sha256:d8a5f82c448bb95b28a9b49b43e8b0b8c6e07eb4838a1f2987a123456789abcd"
REF_DIGEST_V2 = "sha256:e9b6093d559cc06c39b0c50c54f9c1c9d7f18fc5949b203a98b234567890bcde"
DRIFTED_DIGEST = "sha256:fa171a4e66add17d40c1d61d65a0d2dae80290d6050c314ba9c345678901cdef"


class TestKAN63CriteriaAcceptance:
    """Suite de validation formelle des critères d'acceptation KAN-63."""

    def test_ca1_architecture_decision_note_and_adr(self):
        """CA1 : Vérifie la présence, la date, la justification et les options écartées."""
        repo_root = Path(__file__).resolve().parent.parent.parent
        adr_file = repo_root / "docs" / "ADR" / "2026-09-30-04-distribution-versionnement-image-moteur.md"
        spec_file = repo_root / "docs" / "3_Technique" / "spec_kan63_distribution_versionnement_moteur.md"

        assert adr_file.exists(), "L'ADR 2026-09-30-04 doit exister"
        assert spec_file.exists(), "La spécification technique KAN-63 doit exister"

        adr_content = adr_file.read_text(encoding="utf-8")
        assert "30 septembre 2026" in adr_content
        assert "GHCR" in adr_content
        assert "Harbor" in adr_content
        assert "Option D" in adr_content
        assert "Coût" in adr_content or "coût" in adr_content
        assert "Rejet" in adr_content or "rejet" in adr_content

    def test_ca2_pinned_image_and_digest_validation(self):
        """CA2 : Épinglage par empreinte SHA-256 sans intervention manuelle sur le contenu."""
        assert validate_digest(REF_DIGEST_V1) is True
        assert validate_digest("invalid-digest") is False
        assert validate_digest("sha256:123") is False

        pinned = format_pinned_image("ghcr.io/tquinzain59/orso-engine", REF_DIGEST_V1, tag="v1.0.0")
        assert pinned == f"ghcr.io/tquinzain59/orso-engine:v1.0.0@{REF_DIGEST_V1}"

        repo, tag, digest = parse_pinned_image(pinned)
        assert repo == "ghcr.io/tquinzain59/orso-engine"
        assert tag == "v1.0.0"
        assert digest == REF_DIGEST_V1

        # Intégration Olympe DockerLifecycleManager
        from unittest.mock import patch
        import subprocess

        mgr = DockerLifecycleManager(data_root=Path(tempfile.mkdtemp()))
        mgr.has_docker = True
        status_not_found = {"status": "not_found", "running": False}

        mock_proc = subprocess.CompletedProcess(args=["docker", "run"], returncode=0, stdout="cid123", stderr="")
        with patch.object(mgr, "get_tenant_status", return_value=status_not_found):
            with patch.object(mgr, "_exec_docker", return_value=mock_proc) as mock_exec:
                with patch.object(mgr, "_sync_tenant_instance_record"):
                    res = mgr.provision_tenant(
                        tenant_id="test-client-ca2",
                        tenant_slug="client-ca2",
                        image_name="ghcr.io/tquinzain59/orso-engine:latest",
                        image_digest=REF_DIGEST_V1,
                        persona_hmac_key="mock-fleet-hmac-key",
                        env_vars={
                            "HERMES_DASHBOARD_BASIC_AUTH_USERNAME": "admin",
                            "HERMES_DASHBOARD_BASIC_AUTH_PASSWORD": "testpassword",
                        },
                    )
                    assert res["success"] is True
                    assert res["digest"] == REF_DIGEST_V1
                    assert f"@{REF_DIGEST_V1}" in res["image"]

                    # Vérifie que les arguments docker run comportent les labels d'épinglage et l'image par digest
                    assert mock_exec.called
                    run_args = mock_exec.call_args[0][0]
                    assert f"com.orso.engine.digest={REF_DIGEST_V1}" in run_args
                    assert "com.orso.engine.pinned=true" in run_args
                    assert any(arg.endswith(f"@{REF_DIGEST_V1}") for arg in run_args)

    def test_ca3_drift_detection_across_hosts(self):
        """CA3 : Détection d'un écart de version entre hôtes avec test d'écart volontaire."""
        mgr = EngineDistributionManager(target_digest=REF_DIGEST_V1)

        # 1. Hôtes tous synchronisés
        synced_inventory = [
            {
                "host_id": "hote-1-olympe",
                "host_name": "Serveur Olympe & Build",
                "active_digest": REF_DIGEST_V1,
                "running_containers": ["olympe_control_plane"],
            },
            {
                "host_id": "hote-2-clients",
                "host_name": "Serveur Clients OVH",
                "active_digest": REF_DIGEST_V1,
                "running_containers": ["orso-client-financia", "orso-client-alpha"],
            },
        ]
        report_synced = mgr.audit_hosts_drift(synced_inventory)
        assert report_synced.is_drift_detected is False
        assert report_synced.in_sync_count == 2
        assert report_synced.drifted_count == 0

        # 2. Test d'un écart volontaire sur l'hôte client
        drifted_inventory = [
            {
                "host_id": "hote-1-olympe",
                "host_name": "Serveur Olympe & Build",
                "active_digest": REF_DIGEST_V1,
                "running_containers": ["olympe_control_plane"],
            },
            {
                "host_id": "hote-2-clients",
                "host_name": "Serveur Clients OVH",
                "active_digest": DRIFTED_DIGEST,  # Écart volontaire
                "running_containers": ["orso-client-financia"],
            },
        ]
        report_drifted = mgr.audit_hosts_drift(drifted_inventory)
        assert report_drifted.is_drift_detected is True
        assert report_drifted.drifted_count == 1
        assert report_drifted.in_sync_count == 1

        drifted_host = next(h for h in report_drifted.hosts if h.host_id == "hote-2-clients")
        assert drifted_host.status == "DRIFT_DETECTED"
        assert "Dérive détectée" in drifted_host.drift_details

    def test_ca4_update_and_rollback_procedure(self):
        """CA4 : Procédure de mise à jour et retour arrière rejouée avec états vérifiés."""
        mgr = EngineDistributionManager(target_digest=REF_DIGEST_V2)

        initial_state = HostEngineState(
            host_id="hote-2-clients",
            host_name="Serveur Clients OVH",
            active_digest=REF_DIGEST_V1,
            pinned_image=format_pinned_image(mgr.registry_base, REF_DIGEST_V1),
            running_containers=["orso-client-financia"],
            last_checked="2026-09-30T10:00:00Z",
            status="DRIFT_DETECTED",
        )

        # 1. Exécution de la mise à jour vers V2
        updated_state, update_log = mgr.execute_host_update(initial_state, new_digest=REF_DIGEST_V2)
        assert update_log["success"] is True
        assert updated_state.active_digest == REF_DIGEST_V2
        assert updated_state.previous_digest == REF_DIGEST_V1
        assert updated_state.status == "IN_SYNC"

        # 2. Exécution du retour arrière immédiat vers V1
        rollback_state, rollback_log = mgr.execute_host_rollback(updated_state)
        assert rollback_log["success"] is True
        assert rollback_state.active_digest == REF_DIGEST_V1
        assert rollback_state.previous_digest == REF_DIGEST_V2

        # 3. Procédure de secours : validation d'archive bundle SHA-256
        with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as f:
            f.write(b"SIMULATED_DOCKER_IMAGE_PAYLOAD_V1")
            tmp_path = f.name

        try:
            sha_val = EngineDistributionManager.calculate_file_sha256(tmp_path)
            assert len(sha_val) == 64
            assert EngineDistributionManager.verify_bundle_manifest(tmp_path, sha_val) is True
            assert EngineDistributionManager.verify_bundle_manifest(tmp_path, "0" * 64) is False
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def test_ca5_zero_secrets_and_zero_client_data_audit(self):
        """CA5 : Compteurs nuls lors de l'audit des secrets et de la configuration Docker (KAN-63 / KAN-66)."""
        # 1. Vérification de falsifiabilité (CA1) : sans image, l'audit échoue strictement
        audit_without_image = run_full_ca5_audit(image_ref=None, require_image=True)
        assert audit_without_image["status"] == "FAILED"
        assert audit_without_image["metrics"]["image_scan_errors_count"] == 1
        assert audit_without_image["violations"]["image_scan_errors"][0]["type"] == "MISSING_REQUIRED_IMAGE"

        # 2. Avec image inspectée propre (mock de l'inspection conteneur)
        clean_img_result = {
            "secrets": [],
            "client_data": [],
            "errors": [],
            "scanned_files_count": 42,
            "scanned_paths": ["app/run_agent.py", "app/Dockerfile.orso"],
            "applicative_paths": ["app/run_agent.py", "app/Dockerfile.orso"],
        }
        from unittest.mock import patch
        with patch("scripts.security.audit_zero_secrets_and_client_data.audit_docker_image_for_secrets_and_client_data", return_value=clean_img_result):
            audit_report = run_full_ca5_audit(image_ref="ghcr.io/tquinzain59/orso-engine:v1.0.0", require_image=True)
            assert audit_report["status"] == "PASSED", f"Violations détectées : {audit_report['violations']}"
            metrics = audit_report["metrics"]
            assert metrics["secrets_found_count"] == 0
            assert metrics["dockerignore_violations_count"] == 0
            assert metrics["dockerfile_violations_count"] == 0
            assert metrics["client_data_in_engine_count"] == 0
            assert metrics["image_scan_errors_count"] == 0
            assert metrics["total_violations"] == 0
            assert metrics["image_applicative_paths_count"] == 2

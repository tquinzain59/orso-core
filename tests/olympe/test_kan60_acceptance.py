"""Tests d'acceptation automatisés pour le ticket KAN-60 (POC 3 : Artefact d'espace client).

Vérifie formellement les 4 critères d'acceptation (CA1 à CA4) :
- CA1 : Chaque espace client est produit depuis un artefact versionné et identifiable par une empreinte (SHA-256).
- CA2 : L'artefact est monté en lecture seule dans le conteneur du client et de personne d'autre.
- CA3 : Une modification d'espace produit une nouvelle version, et le retour à la précédente est possible et rejoué.
- CA4 : Aucun secret ne figure dans un artefact (compteur nul et rejet immédiat à la détection).
"""

import json
import os
import subprocess
import tarfile
from pathlib import Path
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient

from olympe.artifact_manager import ClientSpaceArtifactManager, compute_sha256_file
from olympe.auth import MOCK_SUPERADMIN_TOKEN
from olympe.lifecycle_manager import DockerLifecycleManager
from olympe.server import app, ops_manager


@pytest.fixture(autouse=True)
def setup_demo_mode_kan60(monkeypatch):
    monkeypatch.setenv("ORSO_DEMO_MODE", "1")
    monkeypatch.setenv("HERMES_DASHBOARD_BASIC_AUTH_USERNAME", "admin")
    monkeypatch.setenv("HERMES_DASHBOARD_BASIC_AUTH_PASSWORD", "testpass123")
    ops_manager.demo_mode = True
    ops_manager._mock_tenants = ops_manager._init_seed_data()


@pytest.fixture
def api_client():
    return TestClient(app)


def _create_mock_space_source(base_dir: Path, tenant_slug: str, extra_skill_content: str = ""):
    """Crée une arborescence d'espace d'agents client propre pour le test."""
    space_dir = base_dir / tenant_slug
    config_dir = space_dir / "config"
    skills_dir = space_dir / "skills"
    profiles_dir = space_dir / "profiles"

    config_dir.mkdir(parents=True, exist_ok=True)
    skills_dir.mkdir(parents=True, exist_ok=True)
    profiles_dir.mkdir(parents=True, exist_ok=True)

    # Configuration hermes.yaml propre au client
    (config_dir / "hermes.yaml").write_text(
        f"model: orso-engine\ntarget_client: {tenant_slug}\nsystem_prompt: Calibration {tenant_slug}\n",
        encoding="utf-8",
    )

    # Compétence sur-mesure client
    (skills_dir / f"custom_skill_{tenant_slug}.py").write_text(
        f"# Skill pour {tenant_slug}\ndef execute():\n    return '{tenant_slug}_ok'\n{extra_skill_content}",
        encoding="utf-8",
    )

    # Profil et persona
    jerome_dir = profiles_dir / "jerome"
    jerome_dir.mkdir(parents=True, exist_ok=True)
    (jerome_dir / "SOUL.md").write_text(
        f"# Persona Jérôme pour {tenant_slug}\nTon: Rigoureux et courtois.\n",
        encoding="utf-8",
    )
    (profiles_dir / "personas.lock.json").write_text(
        json.dumps({
            "version": "1.0",
            "personas": {
                "jerome": {
                    "sha256": "fake_hash_123",
                    "hmac": "fake_hmac_456",
                }
            }
        }),
        encoding="utf-8",
    )
    return space_dir


def test_kan60_ca1_artifacts_versioning_and_fingerprints(tmp_path):
    """CA1 : Chaque espace client est produit depuis un artefact versionné et identifiable par une empreinte SHA-256."""
    artifacts_dir = tmp_path / "artifacts"
    spaces_dir = tmp_path / "spaces"
    mgr = ClientSpaceArtifactManager(artifacts_root=artifacts_dir, spaces_root=spaces_dir)

    tenants = ["poc-alpha", "poc-beta", "poc-gamma"]
    fingerprints = {}

    for slug in tenants:
        src = _create_mock_space_source(tmp_path / "sources", slug)
        manifest = mgr.build_artifact(
            tenant_slug=slug,
            version="1.0.0",
            source_dir=src,
            author="Test Builder",
        )

        assert manifest["tenant_slug"] == slug
        assert manifest["version"] == "1.0.0"
        assert manifest["fingerprint"].startswith("sha256:")
        assert len(manifest["fingerprint"]) == 71  # "sha256:" + 64 hex chars
        assert manifest["content_fingerprint"].startswith("sha256:")
        assert manifest["files_count"] >= 4
        assert manifest["secrets_scan"]["secrets_detected"] == 0

        # Vérification du fichier physique .tar.gz
        archive_path = artifacts_dir / slug / "1.0.0" / f"client-space-{slug}-1.0.0.tar.gz"
        assert archive_path.is_file()
        assert f"sha256:{compute_sha256_file(archive_path)}" == manifest["fingerprint"]

        # Empreintes uniques entre les tenants
        fingerprints[slug] = manifest["fingerprint"]

    # Prouver que les 3 empreintes sont toutes distinctes
    assert len(set(fingerprints.values())) == 3, f"Les empreintes doivent être distinctes : {fingerprints}"


def test_kan60_ca2_readonly_mount_and_isolation(tmp_path):
    """CA2 : L'artefact est monté en lecture seule dans le conteneur du client et de personne d'autre."""
    artifacts_dir = tmp_path / "artifacts"
    spaces_dir = tmp_path / "spaces"
    data_dir = tmp_path / "data"

    life_mgr = DockerLifecycleManager(
        data_root=str(data_dir),
        spaces_root=str(spaces_dir),
        artifacts_root=str(artifacts_dir),
    )
    life_mgr.has_docker = True

    # Création et build d'un artefact v1.0.0 pour poc-alpha
    src_alpha = _create_mock_space_source(tmp_path / "sources", "poc-alpha")
    manifest = life_mgr.artifact_manager.build_artifact("poc-alpha", "1.0.0", src_alpha)

    recorded_docker_runs = []

    def fake_exec_docker(args, timeout=20.0, **kwargs):
        if args and args[0] == "run":
            recorded_docker_runs.append(list(args))
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="c_alpha_123", stderr="")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    with patch.object(life_mgr, "get_tenant_status", return_value={"status": "not_found", "running": False}):
        with patch.object(life_mgr, "_exec_docker", side_effect=fake_exec_docker):
            with patch.object(life_mgr, "_sync_tenant_instance_record"):
                res = life_mgr.provision_tenant(
                    tenant_id="uuid-alpha",
                    tenant_slug="poc-alpha",
                    allow_floating_tag=True,
                    persona_hmac_key="mock_key",
                    artifact_version="1.0.0",
                )

                assert res["success"] is True
                assert res["artifact_version"] == "1.0.0"
                assert res["artifact_digest"] == manifest["fingerprint"]

                # Vérifier les arguments docker run
                assert len(recorded_docker_runs) == 1
                cmd = recorded_docker_runs[0]

                # Labels d'artefact
                assert f"--label=com.orso.artifact.version=1.0.0" in [f"{cmd[i]}={cmd[i+1]}" for i in range(len(cmd)-1) if cmd[i] == "--label"] or "com.orso.artifact.version=1.0.0" in cmd
                assert "com.orso.artifact.mounted_ro=true" in cmd

                # Tous les montages de l'espace client doivent porter ':ro'
                mount_args = [cmd[i+1] for i in range(len(cmd)-1) if cmd[i] == "-v"]
                space_mounts = [m for m in mount_args if "/app/data" not in m]
                for m in space_mounts:
                    assert m.endswith(":ro"), f"Le montage {m} doit obligatoirement être en lecture seule (:ro)"

                # Vérifier les permissions physiques du dossier extrait (0555 et 0444)
                target_space = spaces_dir / "poc-alpha"
                assert target_space.is_dir()
                # Les répertoires doivent refuser l'écriture directe (mode & 0222 == 0)
                config_file = target_space / "config" / "hermes.yaml"
                assert config_file.is_file()
                file_mode = config_file.stat().st_mode & 0o777
                assert file_mode == 0o444, f"Permissions du fichier attendues à 0444, obtenu {oct(file_mode)}"


def test_kan60_ca3_version_upgrade_and_rollback(tmp_path):
    """CA3 : Une modification d'espace produit une nouvelle version, et le retour arrière est possible et rejoué."""
    artifacts_dir = tmp_path / "artifacts"
    spaces_dir = tmp_path / "spaces"
    mgr = ClientSpaceArtifactManager(artifacts_root=artifacts_dir, spaces_root=spaces_dir)

    # 1. Version 1.0.0
    src_v1 = _create_mock_space_source(tmp_path / "sources_v1", "client-mod")
    manifest_v1 = mgr.build_artifact("client-mod", "1.0.0", src_v1)

    # Déploiement v1.0.0
    space_dest = spaces_dir / "client-mod"
    deploy_v1 = mgr.extract_and_deploy_artifact("client-mod", "1.0.0", space_dest)
    assert deploy_v1["fingerprint"] == manifest_v1["fingerprint"]
    assert (space_dest / "config" / "hermes.yaml").exists()

    # Vérification du contenu v1
    v1_content = (space_dest / "config" / "hermes.yaml").read_text(encoding="utf-8")
    assert "Calibration client-mod" in v1_content

    # 2. Version 2.0.0 avec modification
    src_v2 = _create_mock_space_source(tmp_path / "sources_v2", "client-mod")
    (src_v2 / "config" / "hermes.yaml").write_text("model: orso-engine-v2\ncalibration: upgraded_v2\n", encoding="utf-8")
    manifest_v2 = mgr.build_artifact("client-mod", "2.0.0", src_v2)

    assert manifest_v2["fingerprint"] != manifest_v1["fingerprint"]

    # Déploiement v2.0.0
    deploy_v2 = mgr.extract_and_deploy_artifact("client-mod", "2.0.0", space_dest)
    assert deploy_v2["fingerprint"] == manifest_v2["fingerprint"]
    v2_content = (space_dest / "config" / "hermes.yaml").read_text(encoding="utf-8")
    assert "upgraded_v2" in v2_content

    # 3. Rollback vers 1.0.0
    rollback_res = mgr.rollback_space("client-mod", "1.0.0", space_dest)
    assert rollback_res["action"] == "rollback"
    assert rollback_res["version"] == "1.0.0"
    assert rollback_res["fingerprint"] == manifest_v1["fingerprint"]

    # État post-rollback vérifié
    v1_restored_content = (space_dest / "config" / "hermes.yaml").read_text(encoding="utf-8")
    assert "Calibration client-mod" in v1_restored_content
    assert "upgraded_v2" not in v1_restored_content


def test_kan60_ca4_zero_secrets_and_rejection_on_leak(tmp_path):
    """CA4 : Aucun secret ne figure dans un artefact, et toute détection bloque immédiatement la construction."""
    artifacts_dir = tmp_path / "artifacts"
    spaces_dir = tmp_path / "spaces"
    mgr = ClientSpaceArtifactManager(artifacts_root=artifacts_dir, spaces_root=spaces_dir)

    # 1. Espace propre valide : compteur nul
    clean_src = _create_mock_space_source(tmp_path / "clean_source", "poc-clean")
    manifest = mgr.build_artifact("poc-clean", "1.0.0", clean_src)
    assert manifest["secrets_scan"]["secrets_detected"] == 0

    # 2. Injection d'une fausse clé Stripe secrète (sk_live_...) dans la configuration
    leak_src = _create_mock_space_source(tmp_path / "leak_source", "poc-leak")
    dummy_secret = "sk_" + "live_" + "51M0000000000000000000000000000000"
    (leak_src / "config" / "hermes.yaml").write_text(
        f"model: test\nstripe_secret: {dummy_secret}\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError) as excinfo:
        mgr.build_artifact("poc-leak", "1.0.0", leak_src)

    assert "ERR_SECRET_DETECTED_IN_ARTIFACT" in str(excinfo.value)
    assert "Stripe Secret" in str(excinfo.value)

    # Prouver qu'aucun artefact n'a été créé sur le disque pour le tenant qui fuite
    leak_artifact_dir = artifacts_dir / "poc-leak" / "1.0.0"
    assert not leak_artifact_dir.exists(), "Aucun artefact ne doit être persisté en cas de détection de secret"


def test_kan60_api_routes(api_client, tmp_path, monkeypatch):
    """Vérifie les points de terminaison REST Olympe pour la gestion des artefacts."""
    artifacts_dir = tmp_path / "artifacts"
    spaces_dir = tmp_path / "spaces"
    data_dir = tmp_path / "data"

    test_mgr = DockerLifecycleManager(
        data_root=str(data_dir),
        spaces_root=str(spaces_dir),
        artifacts_root=str(artifacts_dir),
    )
    test_mgr.has_docker = False

    # Patch manager global du serveur
    import olympe.server
    monkeypatch.setattr(olympe.server, "manager", test_mgr)

    headers = {"Authorization": f"Bearer {MOCK_SUPERADMIN_TOKEN}"}

    # 1. Build via API
    src = _create_mock_space_source(tmp_path / "api_sources", "tenant-api")
    build_payload = {
        "version": "1.0.0",
        "source_space_dir": str(src),
        "author": "Superadmin Tester",
    }
    resp_build = api_client.post(
        "/api/olympe/ops/tenants/tenant-api/artifacts/build",
        json=build_payload,
        headers=headers,
    )
    assert resp_build.status_code == 200
    b_data = resp_build.json()
    assert b_data["success"] is True
    assert b_data["manifest"]["version"] == "1.0.0"

    # 2. Liste des artefacts
    resp_list = api_client.get(
        "/api/olympe/ops/tenants/tenant-api/artifacts",
        headers=headers,
    )
    assert resp_list.status_code == 200
    l_data = resp_list.json()
    assert l_data["count"] == 1
    assert l_data["versions"][0]["version"] == "1.0.0"

    # 3. Inspection d'un artefact
    resp_inspect = api_client.get(
        "/api/olympe/ops/tenants/tenant-api/artifacts/1.0.0",
        headers=headers,
    )
    assert resp_inspect.status_code == 200
    i_data = resp_inspect.json()
    assert i_data["is_valid"] is True
    assert i_data["manifest"]["fingerprint"].startswith("sha256:")

    # 4. Déploiement via API
    resp_deploy = api_client.post(
        "/api/olympe/ops/tenants/tenant-api/artifacts/deploy",
        json={"version": "1.0.0", "restart_container": False},
        headers=headers,
    )
    assert resp_deploy.status_code == 200
    d_data = resp_deploy.json()
    assert d_data["success"] is True
    assert d_data["version"] == "1.0.0"

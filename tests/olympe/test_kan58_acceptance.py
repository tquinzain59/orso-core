"""Tests d'acceptation automatisés pour le ticket KAN-58 (POC 1 : Espace d'agents propre à chaque client).

Vérifie formellement les 4 critères d'acceptation :
- CA1 : Aucun conteneur client ne monte un dossier partagé avec un autre client.
- CA2 : Un fichier déposé dans l'espace d'un client n'est visible dans aucun autre.
- CA3 : Les trois points de montage de profils pointent vers une seule source par client.
- CA4 : Procédure de retour arrière écrite, rejouée et état vérifié.
"""

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from olympe.auth import MOCK_SUPERADMIN_TOKEN
from olympe.lifecycle_manager import DockerLifecycleManager, normalize_container_name
from olympe.server import app, ops_manager


@pytest.fixture(autouse=True)
def setup_demo_mode_kan58(monkeypatch):
    monkeypatch.setenv("ORSO_DEMO_MODE", "1")
    ops_manager.demo_mode = True
    ops_manager._mock_tenants = ops_manager._init_seed_data()


@pytest.fixture
def api_client():
    return TestClient(app)


def test_kan58_ca1_no_shared_host_directories(tmp_path):
    """CA1 : Vérifie qu'aucun conteneur client ne monte de dossier partagé de l'hôte avec un autre client."""
    data_dir = tmp_path / "tenants"
    spaces_dir = tmp_path / "spaces"
    manager = DockerLifecycleManager(data_root=str(data_dir), spaces_root=str(spaces_dir))
    manager.has_docker = True

    status_not_found = {"status": "not_found", "running": False}

    recorded_calls = []

    def fake_exec_docker(args, timeout=20.0):
        recorded_calls.append(list(args))
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="c_fake_123", stderr="")

    with patch.object(manager, "get_tenant_status", return_value=status_not_found):
        with patch.object(manager, "_exec_docker", side_effect=fake_exec_docker):
            with patch.object(manager, "_sync_tenant_instance_record"):
                test_auth = {
                    "HERMES_DASHBOARD_BASIC_AUTH_USERNAME": "admin",
                    "HERMES_DASHBOARD_BASIC_AUTH_PASSWORD": "testpassword123",
                }
                # Provisionner 3 clients distincts (alpha, beta, gamma)
                res_a = manager.provision_tenant(
                    tenant_id="uuid-alpha",
                    tenant_slug="poc-alpha",
                    allow_floating_tag=True,
                    persona_hmac_key="key-alpha",
                    env_vars=test_auth,
                )
                res_b = manager.provision_tenant(
                    tenant_id="uuid-beta",
                    tenant_slug="poc-beta",
                    allow_floating_tag=True,
                    persona_hmac_key="key-beta",
                    env_vars=test_auth,
                )
                res_c = manager.provision_tenant(
                    tenant_id="uuid-gamma",
                    tenant_slug="poc-gamma",
                    allow_floating_tag=True,
                    persona_hmac_key="key-gamma",
                    env_vars=test_auth,
                )

                assert res_a["success"] is True
                assert res_b["success"] is True
                assert res_c["success"] is True

                assert res_a["dedicated_space"] is True
                assert res_b["dedicated_space"] is True
                assert res_c["dedicated_space"] is True

                # Extraction des montages (-v) pour chaque conteneur
                def extract_mounts(cmd_args):
                    mounts = []
                    for i, arg in enumerate(cmd_args):
                        if arg == "-v" and i + 1 < len(cmd_args):
                            mounts.append(cmd_args[i + 1])
                    return mounts

                run_calls = [c for c in recorded_calls if c and c[0] == "run"]
                mounts_a = extract_mounts(run_calls[0])
                mounts_b = extract_mounts(run_calls[1])
                mounts_c = extract_mounts(run_calls[2])

                # Extraire les chemins sources de l'hôte
                sources_a = {m.split(":")[0] for m in mounts_a}
                sources_b = {m.split(":")[0] for m in mounts_b}
                sources_c = {m.split(":")[0] for m in mounts_c}

                # Aucun chemin source ne doit être partagé entre les clients
                assert len(sources_a.intersection(sources_b)) == 0, f"Chemins partagés A/B: {sources_a.intersection(sources_b)}"
                assert len(sources_a.intersection(sources_c)) == 0, f"Chemins partagés A/C: {sources_a.intersection(sources_c)}"
                assert len(sources_b.intersection(sources_c)) == 0, f"Chemins partagés B/C: {sources_b.intersection(sources_c)}"

                # Vérifier qu'aucun chemin ne pointe vers les dossiers racine partagés
                project_root = Path(__file__).resolve().parent.parent.parent
                shared_root_dirs = {
                    str((project_root / "config").resolve()),
                    str((project_root / "skills").resolve()),
                    str((project_root / "profiles").resolve()),
                }
                for src in sources_a | sources_b | sources_c:
                    assert src not in shared_root_dirs, f"Le chemin hôte partagé {src} ne doit pas être monté directement !"


def test_kan58_ca2_file_isolation_between_spaces(tmp_path):
    """CA2 : Vérifie qu'un fichier déposé dans l'espace d'un client n'est visible dans aucun autre."""
    spaces_dir = tmp_path / "spaces"
    manager = DockerLifecycleManager(data_root=str(tmp_path / "tenants"), spaces_root=str(spaces_dir))

    # Initialisation des espaces pour client A, B et C
    dir_a = manager.get_tenant_space_dir("tenant-a")
    dir_b = manager.get_tenant_space_dir("tenant-b")
    dir_c = manager.get_tenant_space_dir("tenant-c")

    manager._initialize_tenant_space("tenant-a", dir_a)
    manager._initialize_tenant_space("tenant-b", dir_b)
    manager._initialize_tenant_space("tenant-c", dir_c)

    # Déposer un fichier témoin spécifique dans l'espace de A
    witness_file = dir_a / "skills" / "custom_witness_alpha.py"
    witness_file.write_text("# Witness code unique à A", encoding="utf-8")

    assert witness_file.exists()
    assert (dir_b / "skills" / "custom_witness_alpha.py").exists() is False
    assert (dir_c / "skills" / "custom_witness_alpha.py").exists() is False


def test_kan58_ca3_profile_mount_convergence(tmp_path):
    """CA3 : Vérifie que les 3 points de montage de profils pointent vers une seule source par client."""
    data_dir = tmp_path / "tenants"
    spaces_dir = tmp_path / "spaces"
    manager = DockerLifecycleManager(data_root=str(data_dir), spaces_root=str(spaces_dir))
    manager.has_docker = True

    status_not_found = {"status": "not_found", "running": False}
    recorded_calls = []

    def fake_exec_docker(args, timeout=20.0):
        recorded_calls.append(list(args))
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="c_fake_123", stderr="")

    with patch.object(manager, "get_tenant_status", return_value=status_not_found):
        with patch.object(manager, "_exec_docker", side_effect=fake_exec_docker):
            with patch.object(manager, "_sync_tenant_instance_record"):
                res = manager.provision_tenant(
                    tenant_id="uuid-single-source",
                    tenant_slug="client-single-source",
                    allow_floating_tag=True,
                    persona_hmac_key="key-hmac",
                    env_vars={
                        "HERMES_DASHBOARD_BASIC_AUTH_USERNAME": "admin",
                        "HERMES_DASHBOARD_BASIC_AUTH_PASSWORD": "testpassword123",
                    },
                )
                assert res["success"] is True

                run_args = next(c for c in recorded_calls if c and c[0] == "run")
                expected_client_profiles_src = str((spaces_dir / "client-single-source" / "profiles").resolve())

                # Les 3 destinations de profils attendues dans le conteneur
                destinations = {
                    "/app/profiles": False,
                    "/app/data/hermes_home/profiles": False,
                    "/home/orso/.hermes/profiles": False,
                }

                for i, arg in enumerate(run_args):
                    if arg == "-v" and i + 1 < len(run_args):
                        spec = run_args[i + 1]
                        parts = spec.split(":")
                        src, dst, mode = parts[0], parts[1], parts[2] if len(parts) > 2 else ""
                        if dst in destinations:
                            assert src == expected_client_profiles_src, f"Source inattendue pour {dst}: {src}"
                            assert mode == "ro", f"Mode inattendu pour {dst}: {mode} (doit être :ro)"
                            destinations[dst] = True

                assert all(destinations.values()), f"Destinations manquantes : {destinations}"


def test_kan58_ca4_rollback_procedure(tmp_path):
    """CA4 : Vérifie que la procédure de retour arrière est écrite, rejouable et son état vérifié."""
    data_dir = tmp_path / "tenants"
    spaces_dir = tmp_path / "spaces"
    manager = DockerLifecycleManager(data_root=str(data_dir), spaces_root=str(spaces_dir))
    manager.has_docker = True

    tenant_slug = "client-rollback-test"
    space_dir = manager.get_tenant_space_dir(tenant_slug)
    manager._initialize_tenant_space(tenant_slug, space_dir)

    # 1. Sauvegarde de l'état initial
    backup_path = manager.backup_tenant_space(tenant_slug, backup_tag="v1_initial")
    assert backup_path.is_dir()
    assert (backup_path / "profiles").is_dir()

    # 2. Altération de l'espace client (simulation d'une mise à jour défectueuse)
    corrupted_file = space_dir / "skills" / "faulty_skill.py"
    corrupted_file.write_text("SYNTAX ERROR INJECTED", encoding="utf-8")
    assert corrupted_file.exists()

    # 3. Exécution du retour arrière vers la sauvegarde v1
    rollback_res = manager.rollback_tenant_space(tenant_slug, backup_path=backup_path, restart_container=False)
    assert rollback_res["success"] is True
    assert rollback_res["mode"] == "backup_restore"
    assert not corrupted_file.exists(), "Le fichier altéré doit avoir disparu suite au retour arrière !"

    # 4. Altération nouvelle et retour arrière baseline
    new_custom_file = space_dir / "config" / "custom_temp.yaml"
    new_custom_file.write_text("temp: true", encoding="utf-8")
    assert new_custom_file.exists()

    baseline_res = manager.rollback_tenant_space(tenant_slug, backup_path=None, restart_container=False)
    assert baseline_res["success"] is True
    assert baseline_res["mode"] == "baseline_restore"
    assert not new_custom_file.exists()
    assert (space_dir / "profiles" / "personas.lock.json").exists()


def test_kan58_legacy_fallback_mounts(tmp_path, monkeypatch):
    """Vérifie le mode de repli rétro-compatible avec montages partagés legacy."""
    data_dir = tmp_path / "tenants"
    spaces_dir = tmp_path / "spaces"
    manager = DockerLifecycleManager(data_root=str(data_dir), spaces_root=str(spaces_dir))
    manager.has_docker = True

    status_not_found = {"status": "not_found", "running": False}
    recorded_calls = []

    def fake_exec_docker(args, timeout=20.0):
        recorded_calls.append(list(args))
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="c_fake_123", stderr="")

    with patch.object(manager, "get_tenant_status", return_value=status_not_found):
        with patch.object(manager, "_exec_docker", side_effect=fake_exec_docker):
            with patch.object(manager, "_sync_tenant_instance_record"):
                # Provisioning avec use_dedicated_space=False
                res = manager.provision_tenant(
                    tenant_id="uuid-legacy",
                    tenant_slug="client-legacy",
                    allow_floating_tag=True,
                    persona_hmac_key="key-hmac",
                    use_dedicated_space=False,
                    env_vars={
                        "HERMES_DASHBOARD_BASIC_AUTH_USERNAME": "admin",
                        "HERMES_DASHBOARD_BASIC_AUTH_PASSWORD": "testpassword123",
                    },
                )
                assert res["success"] is True
                assert res["dedicated_space"] is False
                assert res["space_directory"] is None

                run_args = next(c for c in recorded_calls if c and c[0] == "run")
                project_root = Path(__file__).resolve().parent.parent.parent
                assert f"{project_root / 'profiles'}:/app/profiles:ro" in run_args


def test_api_olympe_provision_and_rollback_endpoints(api_client, monkeypatch):
    """Vérifie l'API Olympe pour le provisioning dédié et la route de retour arrière."""
    monkeypatch.setenv("ORSO_ALLOW_FLOATING_TAG", "true")
    monkeypatch.setenv("ORSO_PERSONA_HMAC_KEY", "mock-secret-key")
    admin_headers = {"Authorization": f"Bearer {MOCK_SUPERADMIN_TOKEN}"}

    # 1. Provisioning via API avec mock du retour manager
    mock_prov = {
        "success": True,
        "tenant_slug": "api-tenant-test",
        "container_name": "orso_client_api_tenant_test",
        "status": "ready",
        "simulated": True,
        "dedicated_space": True,
        "space_directory": "/tmp/spaces/api-tenant-test",
        "message": "Provisioning simulé avec succès.",
    }
    with patch("olympe.server.manager.provision_tenant", return_value=mock_prov) as mock_p:
        payload = {
            "tenant_id": "test-uuid-api",
            "tenant_slug": "api-tenant-test",
            "image_name": "orso-backend:latest",
            "use_dedicated_space": True,
        }

        resp = api_client.post("/api/olympe/tenants/provision", json=payload, headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["dedicated_space"] is True
        assert data["space_directory"] is not None
        assert mock_p.called

    # 2. Rollback via API
    mock_rb = {
        "success": True,
        "tenant_slug": "api-tenant-test",
        "mode": "baseline_restore",
        "pre_rollback_backup": "/tmp/spaces/.backups/api-tenant-test_pre_rollback",
        "container_restarted": True,
        "container_healthy": True,
        "message": "Retour arrière exécuté.",
    }
    with patch("olympe.server.manager.rollback_tenant_space", return_value=mock_rb) as mock_r:
        payload = {"backup_path": "/tmp/custom_bck", "restart_container": True}
        resp_rollback = api_client.post(
            "/api/olympe/tenants/rollback-space/api-tenant-test",
            json=payload,
            headers=admin_headers,
        )
        assert resp_rollback.status_code == 200
        rb_data = resp_rollback.json()
        assert rb_data["success"] is True
        assert rb_data["mode"] == "baseline_restore"
        assert rb_data["pre_rollback_backup"] is not None
        mock_r.assert_called_once_with("api-tenant-test", backup_path="/tmp/custom_bck", restart_container=True)

    # 3. Rollback via API avec erreur ERR_SPACE_NOT_FOUND (404)
    with patch("olympe.server.manager.rollback_tenant_space", return_value={"success": False, "error": "ERR_SPACE_NOT_FOUND"}):
        resp_err_404 = api_client.post("/api/olympe/tenants/rollback-space/unknown-client", headers=admin_headers)
        assert resp_err_404.status_code == 404
        assert "ERR_SPACE_NOT_FOUND" in resp_err_404.json()["detail"]

    # 4. Rollback via API avec erreur ERR_CONTAINER_RESTART_FAILED (500)
    with patch("olympe.server.manager.rollback_tenant_space", return_value={"success": False, "error": "ERR_CONTAINER_RESTART_FAILED"}):
        resp_err_500 = api_client.post("/api/olympe/tenants/rollback-space/failed-client", headers=admin_headers)
        assert resp_err_500.status_code == 500
        assert "ERR_CONTAINER_RESTART_FAILED" in resp_err_500.json()["detail"]


def test_kan58_legacy_mounts_strictly_forbidden_in_production(tmp_path, monkeypatch):
    """Vérifie le blocage formel des montages partagés legacy en environnement de production."""
    monkeypatch.setenv("ORSO_ENV", "production")

    data_dir = tmp_path / "tenants"
    spaces_dir = tmp_path / "spaces"
    manager = DockerLifecycleManager(data_root=str(data_dir), spaces_root=str(spaces_dir))

    # Test 1 : Sans Docker local (mode délégué / simulation)
    manager.has_docker = False
    res_sim = manager.provision_tenant(
        tenant_id="uuid-prod-reject",
        tenant_slug="prod-client",
        use_dedicated_space=False,
    )
    assert res_sim["success"] is False
    assert res_sim["error"] == "ERR_LEGACY_MOUNTS_FORBIDDEN_IN_PROD"

    # Test 2 : Avec Docker local activé
    manager.has_docker = True
    status_not_found = {"status": "not_found", "running": False}
    with patch.object(manager, "get_tenant_status", return_value=status_not_found):
        res_docker = manager.provision_tenant(
            tenant_id="uuid-prod-reject-2",
            tenant_slug="prod-client-2",
            allow_floating_tag=True,
            persona_hmac_key="key-hmac",
            use_dedicated_space=False,
        )
        assert res_docker["success"] is False
        assert res_docker["error"] == "ERR_LEGACY_MOUNTS_FORBIDDEN_IN_PROD"


def test_kan58_ca4_rollback_hardened_safety_and_restart(tmp_path):
    """Vérifie la robustesse du rollback : sauvegarde préventive, gestion conteneur arrêté ou échec redémarrage."""
    data_dir = tmp_path / "tenants"
    spaces_dir = tmp_path / "spaces"
    manager = DockerLifecycleManager(data_root=str(data_dir), spaces_root=str(spaces_dir))
    manager.has_docker = True

    tenant_slug = "client-hardened-rollback"

    # 1. Tentative sur un espace inexistant -> ERR_SPACE_NOT_FOUND
    res_not_found = manager.rollback_tenant_space("non-existent-tenant")
    assert res_not_found["success"] is False
    assert res_not_found["error"] == "ERR_SPACE_NOT_FOUND"

    # 2. Création et altération d'un espace existant
    space_dir = manager.get_tenant_space_dir(tenant_slug)
    manager._initialize_tenant_space(tenant_slug, space_dir)
    test_marker = space_dir / "config" / "before_rollback.txt"
    test_marker.write_text("before", encoding="utf-8")

    # Simulation d'un conteneur qui tourne mais dont le docker restart échoue
    running_status = {"status": "running", "running": True}
    failed_restart = subprocess.CompletedProcess(args=["docker", "restart"], returncode=1, stdout="", stderr="Restart timeout")

    with patch.object(manager, "get_tenant_status", return_value=running_status):
        with patch.object(manager, "_exec_docker", return_value=failed_restart):
            res_fail = manager.rollback_tenant_space(tenant_slug, restart_container=True)
            assert res_fail["success"] is False
            assert res_fail["error"] == "ERR_CONTAINER_RESTART_FAILED"
            assert res_fail["container_restarted"] is False
            assert res_fail["container_healthy"] is False
            assert res_fail["pre_rollback_backup"] is not None
            assert Path(res_fail["pre_rollback_backup"]).is_dir()


def test_kan58_dashboard_auth_strictly_required_no_fallback(tmp_path):
    """Point 0 / Sécurité KAN-58 : Vérifie le rejet strict ERR_DASHBOARD_AUTH_REQUIRED sans mot de passe ou hash committé."""
    data_dir = tmp_path / "tenants"
    spaces_dir = tmp_path / "spaces"
    manager = DockerLifecycleManager(data_root=str(data_dir), spaces_root=str(spaces_dir))
    manager.has_docker = True

    status_not_found = {"status": "not_found", "running": False}

    with patch.object(manager, "get_tenant_status", return_value=status_not_found):
        with patch.object(manager, "_sync_tenant_instance_record"):
            # 1. Sans env_vars -> Rejet explicite immédiat
            res_no_auth = manager.provision_tenant(
                tenant_id="uuid-no-auth",
                tenant_slug="client-no-auth",
                allow_floating_tag=True,
                persona_hmac_key="key-hmac",
            )
            assert res_no_auth["success"] is False
            assert res_no_auth["error"] == "ERR_DASHBOARD_AUTH_REQUIRED"
            assert res_no_auth["action_taken"] is False

            # 2. Avec seulement username, sans mot de passe -> Rejet explicite
            res_user_only = manager.provision_tenant(
                tenant_id="uuid-user-only",
                tenant_slug="client-user-only",
                allow_floating_tag=True,
                persona_hmac_key="key-hmac",
                env_vars={"HERMES_DASHBOARD_BASIC_AUTH_USERNAME": "admin"},
            )
            assert res_user_only["success"] is False
            assert res_user_only["error"] == "ERR_DASHBOARD_AUTH_REQUIRED"

            # 3. Avec authentification explicite fournie -> Accepté pour lancement Docker
            recorded_calls = []
            def fake_exec_docker(args, timeout=20.0):
                recorded_calls.append(list(args))
                return subprocess.CompletedProcess(args=args, returncode=0, stdout="c_fake_auth", stderr="")

            with patch.object(manager, "_exec_docker", side_effect=fake_exec_docker):
                res_ok = manager.provision_tenant(
                    tenant_id="uuid-auth-ok",
                    tenant_slug="client-auth-ok",
                    allow_floating_tag=True,
                    persona_hmac_key="key-hmac",
                    env_vars={
                        "HERMES_DASHBOARD_BASIC_AUTH_USERNAME": "ops_user",
                        "HERMES_DASHBOARD_BASIC_AUTH_PASSWORD": "ephemeral_secret_123",
                    },
                )
                assert res_ok["success"] is True
                assert res_ok["action_taken"] is True
                run_call = next(c for c in recorded_calls if c and c[0] == "run")
                assert "HERMES_DASHBOARD_BASIC_AUTH_USERNAME=ops_user" in run_call
                assert "HERMES_DASHBOARD_BASIC_AUTH_PASSWORD=ephemeral_secret_123" in run_call


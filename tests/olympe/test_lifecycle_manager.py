"""Tests unitaires automatisés pour le gestionnaire de cycle de vie Olympe.

Valide la normalisation des conteneurs, le statut, le réveil (wake-on-demand),
la mise en veille (suspend), le provisioning et les points d'entrée de l'API Olympe.
"""

import json
import subprocess
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from olympe.lifecycle_manager import DockerLifecycleManager, normalize_container_name
from olympe.server import app


@pytest.fixture
def api_client():
    return TestClient(app)


def test_normalize_container_name():
    """Vérifie la normalisation stricte des noms de conteneurs Docker."""
    assert normalize_container_name("financia-solutions") == "orso_client_financia_solutions"
    assert normalize_container_name("AURA-CONSEIL") == "orso_client_aura_conseil"
    assert normalize_container_name("client.test-1") == "orso_client_client_test_1"
    assert normalize_container_name("  simple  ") == "orso_client_simple"


def test_get_tenant_status_running():
    """Vérifie la détection d'un conteneur en cours d'exécution (ready)."""
    manager = DockerLifecycleManager()
    manager.has_docker = True

    mock_state = {
        "Running": True,
        "Paused": False,
        "Status": "running",
        "StartedAt": "2026-09-20T10:00:00Z",
    }
    mock_proc = subprocess.CompletedProcess(
        args=["docker", "inspect"],
        returncode=0,
        stdout=json.dumps(mock_state),
        stderr="",
    )

    with patch.object(manager, "_exec_docker", return_value=mock_proc):
        status = manager.get_tenant_status("financia-solutions")
        assert status["status"] == "ready"
        assert status["running"] is True
        assert status["container_name"] == "orso_client_financia_solutions"


def test_get_tenant_status_sleeping():
    """Vérifie la détection d'un conteneur arrêté/en veille (sleeping)."""
    manager = DockerLifecycleManager()
    manager.has_docker = True

    mock_state = {
        "Running": False,
        "Paused": False,
        "Status": "exited",
        "ExitCode": 0,
    }
    mock_proc = subprocess.CompletedProcess(
        args=["docker", "inspect"],
        returncode=0,
        stdout=json.dumps(mock_state),
        stderr="",
    )

    with patch.object(manager, "_exec_docker", return_value=mock_proc):
        status = manager.get_tenant_status("financia-solutions")
        assert status["status"] == "sleeping"
        assert status["running"] is False


def test_get_tenant_status_not_found():
    """Vérifie la gestion d'un conteneur qui n'a pas encore été provisionné."""
    manager = DockerLifecycleManager()
    manager.has_docker = True

    mock_proc = subprocess.CompletedProcess(
        args=["docker", "inspect"],
        returncode=1,
        stdout="",
        stderr="Error: No such container",
    )

    with patch.object(manager, "_exec_docker", return_value=mock_proc):
        status = manager.get_tenant_status("inconnu-corp")
        assert status["status"] == "not_found"
        assert status["running"] is False


def test_wake_tenant_success():
    """Vérifie le réveil réussi d'un conteneur en veille."""
    manager = DockerLifecycleManager()
    manager.has_docker = True

    # 1. Étape 1 : statut initial en veille
    # 2. Étape 2 : docker start succès
    # 3. Étape 3 : statut redevient running
    status_sleeping = {"status": "sleeping", "running": False}
    status_ready = {"status": "ready", "running": True}

    with patch.object(manager, "get_tenant_status", side_effect=[status_sleeping, status_ready]):
        mock_start_proc = subprocess.CompletedProcess(args=["docker", "start"], returncode=0, stdout="", stderr="")
        with patch.object(manager, "_exec_docker", return_value=mock_start_proc):
            res = manager.wake_tenant("financia-solutions", wait_healthy=True, timeout=2.0)
            assert res["success"] is True
            assert res["status"] == "ready"


def test_suspend_tenant_success():
    """Vérifie la mise en veille réussie d'un conteneur actif."""
    manager = DockerLifecycleManager()
    manager.has_docker = True

    status_running = {"status": "ready", "running": True}
    with patch.object(manager, "get_tenant_status", return_value=status_running):
        mock_stop_proc = subprocess.CompletedProcess(args=["docker", "stop"], returncode=0, stdout="", stderr="")
        with patch.object(manager, "_exec_docker", return_value=mock_stop_proc):
            res = manager.suspend_tenant("financia-solutions")
            assert res["success"] is True
            assert res["status"] == "sleeping"


def test_provision_tenant(tmp_path):
    """Vérifie la création du dossier et l'invocation de docker run."""
    manager = DockerLifecycleManager(data_root=str(tmp_path))
    manager.has_docker = True

    status_not_found = {"status": "not_found", "running": False}
    with patch.object(manager, "get_tenant_status", return_value=status_not_found):
        mock_run_proc = subprocess.CompletedProcess(args=["docker", "run"], returncode=0, stdout="c12345", stderr="")
        with patch.object(manager, "_exec_docker", return_value=mock_run_proc) as mock_exec:
            with patch.object(manager, "_sync_tenant_instance_record"):
                res = manager.provision_tenant(
                    tenant_id="test-uuid",
                    tenant_slug="nouveau-client",
                )
                assert res["success"] is True
                assert res["container_name"] == "orso_client_nouveau_client"
                # Le dossier de persistance doit exister
                assert (tmp_path / "nouveau-client").is_dir()
                # Vérifie que docker run a bien été appelé
                assert mock_exec.called


def test_api_olympe_health(api_client):
    """Vérifie l'endpoint /api/olympe/health."""
    resp = api_client.get("/api/olympe/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["service"] == "olympe-core"
    assert data["status"] == "healthy"


def test_api_olympe_wake_not_found(api_client):
    """Vérifie qu'un réveil sur un conteneur introuvable renvoie HTTP 404."""
    with patch("olympe.server.manager.wake_tenant", return_value={"success": False, "status": "not_found"}):
        resp = api_client.post("/api/olympe/tenants/wake/client-inexistant")
        assert resp.status_code == 404
        assert "n'a pas été trouvé" in resp.json()["detail"]


def test_api_olympe_wake_success(api_client):
    """Vérifie qu'un réveil réussi renvoie HTTP 200."""
    with patch("olympe.server.manager.wake_tenant", return_value={"success": True, "status": "ready"}):
        resp = api_client.post("/api/olympe/tenants/wake/financia-solutions")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ready"

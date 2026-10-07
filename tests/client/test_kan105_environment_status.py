"""Tests d'acceptation automatisés pour le ticket KAN-105 (Écran d'attente client et statut de l'environnement).

Vérifie formellement :
- L'exposition de l'endpoint GET /api/client/environment/status.
- La restitution de l'état 'ready' lorsque l'environnement est en ligne.
- La restitution de l'état 'provisioning' avec pourcentage d'avancement et étape détaillée.
- La restitution de l'état 'sleeping' avec wake_endpoint exploitable.
- La restitution de l'état 'error' avec contact support et détails d'incident.
- La restitution de l'état 'not_configured' lorsque aucun conteneur n'est alloué.
"""

from unittest.mock import patch
import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hermes_cli.web_routers.client_ui import router


@pytest.fixture
def client_app():
    test_app = FastAPI()
    test_app.include_router(router)
    return TestClient(test_app)


def test_kan105_environment_status_ready_demo(client_app):
    """Vérifie que l'endpoint retourne un statut ready en mode démo / autonome."""
    with patch.dict("os.environ", {"ORSO_DEMO_MODE": "1", "ORSO_CLIENT_SLUG": "demo-acme"}):
        res = client_app.get("/api/client/environment/status")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "ready"
        assert data["ready"] is True
        assert data["tenant_slug"] == "demo-acme"
        assert "jerome" in data["agents_enabled"]


def test_kan105_environment_status_provisioning(client_app):
    """Vérifie que l'état 'provisioning' renvoie le pourcentage d'avancement et l'étape."""
    fake_env = {
        "instance_url": "http://57.131.196.106:9234",
        "docker_container_name": "orso_client_acme",
        "environment_status": "provisioning",
        "progress_percent": 60,
        "current_step": "Injection des lettres de mission et calibrage des agents IA",
        "estimated_remaining_seconds": 40,
    }

    token = jwt.encode(
        {"tenant_slug": "acme-corp", "sub": "user_1", "app_metadata": {"tenant_slug": "acme-corp"}},
        "dummy_secret",
        algorithm="HS256",
    )

    with patch("hermes_cli.web_routers.client_ui._resolve_target_environment", return_value=fake_env):
        res = client_app.get(
            "/api/client/environment/status",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "provisioning"
        assert data["ready"] is False
        assert data["tenant_slug"] == "acme-corp"
        assert data["progress_percent"] == 60
        assert "calibrage des agents" in data["current_step"]
        assert data["estimated_remaining_seconds"] == 40


def test_kan105_environment_status_sleeping(client_app):
    """Vérifie que l'état 'sleeping' renvoie l'endpoint de réveil."""
    fake_env = {
        "instance_url": "http://57.131.196.106:9235",
        "docker_container_name": "orso_client_sleeping",
        "environment_status": "sleeping",
    }

    with patch("hermes_cli.web_routers.client_ui._resolve_target_environment", return_value=fake_env):
        res = client_app.get("/api/client/environment/status?tenant_slug=sleeping-org")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "sleeping"
        assert data["ready"] is False
        assert data["tenant_slug"] == "sleeping-org"
        assert data["wake_endpoint"] == "/api/olympe/tenants/wake/sleeping-org"


def test_kan105_environment_status_error(client_app):
    """Vérifie que l'état 'error' restitue le détail de l'incident et le contact support."""
    fake_env = {
        "instance_url": None,
        "docker_container_name": "orso_client_err",
        "environment_status": "error",
        "error_details": "Échec du montage des volumes ZFS étanches.",
    }

    with patch("hermes_cli.web_routers.client_ui._resolve_target_environment", return_value=fake_env):
        res = client_app.get("/api/client/environment/status?tenant_slug=error-org")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "error"
        assert data["ready"] is False
        assert "volumes ZFS" in data["error_details"]
        assert data["support_contact"] == "support@orso-agents.fr"


def test_kan105_environment_status_not_configured(client_app):
    """Vérifie le retour 'not_configured' lorsque aucun conteneur n'est trouvé en mode connecté."""
    with patch.dict("os.environ", {"ORSO_DEMO_MODE": "0", "SUPABASE_URL": "https://fake.supabase.co"}):
        with patch("hermes_cli.web_routers.client_ui._resolve_target_environment", return_value=None):
            res = client_app.get("/api/client/environment/status?tenant_slug=orphan-org")
            assert res.status_code == 200
            data = res.json()
            assert data["status"] == "not_configured"
            assert data["ready"] is False
            assert "Aucun environnement" in data["message"]

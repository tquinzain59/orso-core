"""Tests d'acceptation automatisés pour le ticket KAN-105 (Écran d'attente client et statut de l'environnement).

Vérifie formellement :
- L'exposition de l'endpoint GET /api/client/environment/status.
- La restitution de l'état 'ready' lorsque l'environnement est en ligne.
- La restitution de l'état 'pending_validation' ou 'provisioning' SANS fausse barre de progression ni faux décompte temporel (arbitrage PO Jarvis du 07/10/2026).
- La présence explicite de la prochaine étape (appel de cadrage) et du contact humain nommé (Thibaut Quinzain, contact@orso-agents.fr).
- La résolution d'un compte nouvellement inscrit sans conteneur vers 'pending_validation' au lieu d'une impasse 'not_configured'.
- La restitution de l'état 'sleeping' avec wake_endpoint exploitable.
- La restitution de l'état 'error' avec contact support et cause lisible.
- La restitution de l'état 'not_configured' avec invitation à contacter l'exploitation.
"""

import json
from unittest.mock import MagicMock, patch
import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hermes_cli.web_routers.client_ui import router, _resolve_target_environment


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


def test_kan105_environment_status_pending_validation_no_fake_metrics(client_app):
    """Vérifie que l'attente annonce la prochaine étape et le contact humain SANS faux pourcentage ni faux délai."""
    fake_env = {
        "instance_url": None,
        "docker_container_name": None,
        "environment_status": "pending_validation",
        "status": "not_provisioned",
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
        assert data["status"] == "pending_validation"
        assert data["ready"] is False
        assert data["tenant_slug"] == "acme-corp"
        assert "préparation" in data["message"]
        assert "cadrage" in data["next_step"]
        assert data["contact_person"] == "Thibaut Quinzain"
        assert data["contact_email"] == "contact@orso-agents.fr"

        # Interdiction formelle des métriques inventées (Arbitrage 2 du 07/10/2026)
        assert "progress_percent" not in data
        assert "estimated_remaining_seconds" not in data


def test_kan105_environment_status_provisioning_honest(client_app):
    """Vérifie que l'état 'provisioning' reste honnête sans fausse barre de temps."""
    fake_env = {
        "instance_url": "http://57.131.196.106:9234",
        "docker_container_name": "orso_client_acme",
        "environment_status": "provisioning",
    }

    with patch("hermes_cli.web_routers.client_ui._resolve_target_environment", return_value=fake_env):
        res = client_app.get("/api/client/environment/status?tenant_slug=acme-corp")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "provisioning"
        assert data["ready"] is False
        assert data["contact_person"] == "Thibaut Quinzain"
        assert "progress_percent" not in data
        assert "estimated_remaining_seconds" not in data


def test_kan105_unprovisioned_tenant_resolution_via_tenants_table():
    """Vérifie qu'un compte inscrit présent dans tenants mais sans conteneur résout vers pending_validation (pas None)."""
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps([{"id": "t-123", "slug": "nouveau-client", "status": "trial"}]).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.__exit__.return_value = None

    def mock_urlopen(req, timeout=3.0):
        # 1er appel tenant_instances -> []
        if "tenant_instances" in req.full_url:
            empty_resp = MagicMock()
            empty_resp.read.return_value = b"[]"
            empty_resp.__enter__.return_value = empty_resp
            empty_resp.__exit__.return_value = None
            return empty_resp
        # 2e appel tenants -> record
        return mock_resp

    with patch("urllib.request.urlopen", side_effect=mock_urlopen):
        env = _resolve_target_environment(
            token_tenant_id="t-123",
            token_tenant_slug="nouveau-client",
            app_meta={},
            supabase_url="https://mock.supabase.co",
            service_key="mock_service_key",
        )
        assert env is not None
        assert env["environment_status"] == "pending_validation"
        assert env["status"] == "not_provisioned"


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
    """Vérifie que l'état 'error' restitue le détail de l'incident et le contact nommé."""
    fake_env = {
        "instance_url": None,
        "docker_container_name": "orso_client_err",
        "environment_status": "error",
        "error_details": "Échec du montage des volumes étanches.",
    }

    with patch("hermes_cli.web_routers.client_ui._resolve_target_environment", return_value=fake_env):
        res = client_app.get("/api/client/environment/status?tenant_slug=error-org")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "error"
        assert data["ready"] is False
        assert "volumes étanches" in data["error_details"]
        assert data["contact_person"] == "Thibaut Quinzain"
        assert data["support_contact"] == "contact@orso-agents.fr"


def test_kan105_environment_status_not_configured(client_app):
    """Vérifie le retour 'not_configured' lorsque aucun compte n'est trouvé."""
    with patch.dict("os.environ", {"ORSO_DEMO_MODE": "0", "SUPABASE_URL": "https://fake.supabase.co"}):
        with patch("hermes_cli.web_routers.client_ui._resolve_target_environment", return_value=None):
            res = client_app.get("/api/client/environment/status?tenant_slug=orphan-org")
            assert res.status_code == 200
            data = res.json()
            assert data["status"] == "not_configured"
            assert data["ready"] is False
            assert "Aucune organisation rattachée" in data["message"]
            assert data["contact_person"] == "Thibaut Quinzain"

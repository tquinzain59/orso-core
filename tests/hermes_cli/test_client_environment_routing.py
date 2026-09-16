"""Tests automatisés pour la résolution de l'environnement cible et le message d'alerte support.

Vérifie l'exigence :
- Si rien n'est renseigné pour l'environnement cible : retour HTTP 404 avec message exact
  "Environnement non trouvé, le support Orso-agents est alerté" et déclenchement de l'alerte support.
- Si l'environnement cible est renseigné : renvoi des références et gestion de la redirection.
"""

import json
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from hermes_cli.web_server import app


@pytest.fixture
def client():
    return TestClient(app)


def test_login_environment_not_found_returns_exact_message_and_triggers_alert(client, monkeypatch):
    """Quand le client s'authentifie correctement mais qu'aucun environnement n'est renseigné,
    l'API DOIT renvoyer 'Environnement non trouvé, le support Orso-agents est alerté' (404)
    et journaliser l'alerte support."""
    monkeypatch.setenv("SUPABASE_URL", "https://mock.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "mock_key")
    monkeypatch.setenv("ORSO_CLIENT_ID", "f3e25379-6531-479e-b276-3b3185e7421b")
    monkeypatch.setenv("ORSO_CLIENT_SLUG", "financia-solutions")

    # Mock de l'authentification Supabase réussie pour un utilisateur sans environnement
    mock_supabase_auth_resp = {
        "access_token": "mock.jwt.token",
        "user": {
            "id": "user-sans-env-id",
            "email": "test.sansenv@orso-agents.fr",
            "app_metadata": {
                "tenant_id": "tenant-sans-env-id",
                "tenant_slug": "aura-sans-env",
                "role": "direction",
                # Pas de target_environment !
            },
            "user_metadata": {
                "full_name": "Testeur Sans Env"
            }
        }
    }

    class MockResp:
        def __init__(self, data):
            self._data = json.dumps(data).encode("utf-8")
        def read(self):
            return self._data
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass

    def mock_urlopen(req, *args, **kwargs):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        # 1. Appel Auth token
        if "auth/v1/token" in url:
            return MockResp(mock_supabase_auth_resp)
        # 2. Appel recherche tenant_instances -> retourne vide (aucun environnement trouvé)
        if "tenant_instances" in url:
            return MockResp([])
        # 3. Appel insertion support_alerts
        if "support_alerts" in url:
            return MockResp({"id": "alert-id-123"})
        return MockResp({})

    with patch("urllib.request.urlopen", side_effect=mock_urlopen):
        with patch("hermes_cli.web_routers.client_ui._log.error") as mock_log_err:
            resp = client.post(
                "/api/client/auth/login",
                json={"email": "test.sansenv@orso-agents.fr", "password": "ValidPassword123!"},
            )

            # Doit renvoyer HTTP 404
            assert resp.status_code == 404
            data = resp.json()

            # LE MESSAGE RENVOYÉ DOIT INDIQUER EXACTEMENT :
            # "Environnement non trouvé, le support Orso-agents est alerté"
            assert data["detail"] == "Environnement non trouvé, le support Orso-agents est alerté"

            # Vérifie que l'alerte support a été émise dans les logs
            assert mock_log_err.called
            call_args = str(mock_log_err.call_args)
            assert "[ALERT_SUPPORT_ORSO]" in call_args
            assert "test.sansenv@orso-agents.fr" in call_args


def test_login_environment_found_matches_instance(client, monkeypatch):
    """Quand l'environnement est renseigné et correspond à l'instance courante,
    le login réussit (200) avec target_environment."""
    monkeypatch.setenv("SUPABASE_URL", "https://mock.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "mock_key")
    monkeypatch.setenv("ORSO_CLIENT_ID", "f3e25379-6531-479e-b276-3b3185e7421b")
    monkeypatch.setenv("ORSO_CLIENT_SLUG", "financia-solutions")

    mock_auth_resp = {
        "access_token": "mock.jwt.token",
        "user": {
            "id": "user-sophie-id",
            "email": "sophie.martin@finarecee20.fr",
            "app_metadata": {
                "tenant_id": "f3e25379-6531-479e-b276-3b3185e7421b",
                "tenant_slug": "financia-solutions",
                "role": "daf",
                "target_environment": {
                    "instance_url": "https://recouvrement.orso-agents.fr",
                    "docker_container_name": "orso_client_backend",
                    "docker_host": "92.222.68.80",
                    "docker_port": 9300,
                    "environment_status": "active"
                }
            },
            "user_metadata": {
                "full_name": "Sophie Martin"
            }
        }
    }

    class MockResp:
        def __init__(self, data):
            self._data = json.dumps(data).encode("utf-8")
        def read(self):
            return self._data
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass

    def mock_urlopen(req, *args, **kwargs):
        return MockResp(mock_auth_resp)

    with patch("urllib.request.urlopen", side_effect=mock_urlopen):
        resp = client.post(
            "/api/client/auth/login",
            json={"email": "sophie.martin@finarecee20.fr", "password": "TempOrso2026!Financia"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["target_environment"]["instance_url"] == "https://recouvrement.orso-agents.fr"
        assert data["target_environment"]["docker_container_name"] == "orso_client_backend"
        assert data["redirect_url"] is None


def test_login_environment_found_on_different_instance_provides_redirect(client, monkeypatch):
    """Quand l'environnement est renseigné sur une autre instance,
    le login fournit l'URL de redirection vers le conteneur dédié."""
    monkeypatch.setenv("SUPABASE_URL", "https://mock.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "mock_key")
    # Instance courante = commercialink
    monkeypatch.setenv("ORSO_CLIENT_ID", "other-tenant-id")
    monkeypatch.setenv("ORSO_CLIENT_SLUG", "other-tenant")

    # Utilisateur Financia se connectant par erreur sur le portail de commercialink
    mock_auth_resp = {
        "access_token": "mock.jwt.token",
        "user": {
            "id": "user-sophie-id",
            "email": "sophie.martin@finarecee20.fr",
            "app_metadata": {
                "tenant_id": "f3e25379-6531-479e-b276-3b3185e7421b",
                "tenant_slug": "financia-solutions",
                "role": "daf",
                "target_environment": {
                    "instance_url": "https://recouvrement.orso-agents.fr",
                    "docker_container_name": "orso_client_backend",
                    "docker_host": "92.222.68.80",
                    "docker_port": 9300,
                    "environment_status": "active"
                }
            },
            "user_metadata": {
                "full_name": "Sophie Martin"
            }
        }
    }

    class MockResp:
        def __init__(self, data):
            self._data = json.dumps(data).encode("utf-8")
        def read(self):
            return self._data
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass

    with patch("urllib.request.urlopen", return_value=MockResp(mock_auth_resp)):
        resp = client.post(
            "/api/client/auth/login",
            json={"email": "sophie.martin@finarecee20.fr", "password": "TempOrso2026!Financia"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["redirect_url"] == "https://recouvrement.orso-agents.fr"

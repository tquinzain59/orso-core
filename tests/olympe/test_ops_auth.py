"""Tests d'intégration et unitaires pour l'authentification Superadmin Orso Ops (olympe/auth.py)."""

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from olympe.auth import authenticate_superadmin, verify_superadmin_token, MOCK_SUPERADMIN_TOKEN
from olympe.server import app


def test_login_superadmin_mock_success():
    """Vérifie la connexion superadmin en mode déconnecté/test."""
    res = authenticate_superadmin("admin@orso-agents.fr", "admin123")
    assert "token" in res
    assert res["user"]["role"] == "superadmin"
    assert res["user"]["email"] == "admin@orso-agents.fr"


def test_login_superadmin_invalid_credentials():
    """Vérifie le rejet d'identifiants incorrects."""
    with pytest.raises(HTTPException) as exc_info:
        authenticate_superadmin("admin@orso-agents.fr", "mauvais_mdp")
    assert exc_info.value.status_code == 401


def test_verify_superadmin_token_success():
    """Vérifie la validation d'un jeton valide."""
    user = verify_superadmin_token(MOCK_SUPERADMIN_TOKEN)
    assert user["role"] == "superadmin"
    assert user["email"] == "admin@orso-agents.fr"


def test_verify_superadmin_token_invalid():
    """Vérifie le rejet d'un faux jeton."""
    with pytest.raises(HTTPException) as exc_info:
        verify_superadmin_token("faux-token-inconnu")
    assert exc_info.value.status_code in [401, 403]


def test_fastapi_endpoints_protection():
    """Vérifie la protection des routes /api/olympe/ops/* via FastAPI TestClient."""
    client = TestClient(app)

    # 1. Routes publiques ouvertes
    health_resp = client.get("/health")
    assert health_resp.status_code == 200

    # 2. Routes ops protégées sans token -> 401
    stats_unauth = client.get("/api/olympe/ops/stats")
    assert stats_unauth.status_code == 401

    tenants_unauth = client.get("/api/olympe/ops/tenants")
    assert tenants_unauth.status_code == 401

    invoices_unauth = client.get("/api/olympe/ops/invoices")
    assert invoices_unauth.status_code == 401

    # 3. Connexion via l'endpoint de login
    login_resp = client.post(
        "/api/olympe/ops/auth/login",
        json={"email": "admin@orso-agents.fr", "password": "admin123"},
    )
    assert login_resp.status_code == 200
    token = login_resp.json()["token"]

    # 4. Requête avec token Bearer -> 200
    auth_headers = {"Authorization": f"Bearer {token}"}

    me_resp = client.get("/api/olympe/ops/auth/me", headers=auth_headers)
    assert me_resp.status_code == 200
    assert me_resp.json()["user"]["role"] == "superadmin"

    stats_auth = client.get("/api/olympe/ops/stats", headers=auth_headers)
    assert stats_auth.status_code == 200
    assert "kpis" in stats_auth.json()

    tenants_auth = client.get("/api/olympe/ops/tenants", headers=auth_headers)
    assert tenants_auth.status_code == 200
    assert "tenants" in tenants_auth.json()

    # 5. Déconnexion
    logout_resp = client.post("/api/olympe/ops/auth/logout", headers=auth_headers)
    assert logout_resp.status_code == 200

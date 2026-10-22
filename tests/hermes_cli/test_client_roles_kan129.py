"""KAN-129 / CA6 : le modèle de rôles existant (utilisateur simple / administrateur) est contrôlé.

Un utilisateur simple est refusé (403) sur chaque action admin ; le même utilisateur, une fois promu
(case « administrateur » cochée => is_admin dans son profil), y accède.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hermes_cli.web_routers.client_ui import _resolve_user_system_role_and_job_title, router
from tests.hermes_cli.test_client_settings_billing import _make_test_jwt

ADMIN_ROUTES = [
    ("get", "/api/client/billing", None),
    ("post", "/api/client/billing/subscription", {"tier_id": "1_agent"}),
    ("post", "/api/client/billing/portal-session", None),
]


@pytest.fixture
def client_app(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "test-jwt-secret")
    monkeypatch.setenv("ORSO_CLIENT_ID", "f3e25379-6531-479e-b276-3b3185e7421b")
    monkeypatch.setenv("ORSO_CLIENT_SLUG", "financia-solutions")
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _call(client, method, path, body, token):
    return getattr(client, method)(path, headers={"Authorization": f"Bearer {token}"}, **({"json": body} if body else {}))


@pytest.mark.parametrize("method,path,body", ADMIN_ROUTES)
def test_simple_user_refused_on_admin_action(client_app, method, path, body):
    token = _make_test_jwt(is_admin=False, role="user", user_id="user-simple")
    assert _call(client_app, method, path, body, token).status_code == 403


@pytest.mark.parametrize("method,path,body", ADMIN_ROUTES)
def test_promoted_user_not_refused_on_admin_action(client_app, method, path, body):
    # Même utilisateur, promu : le contrôle de rôle ne le refuse plus (tout autre statut vient de Stripe/config).
    token = _make_test_jwt(is_admin=True, role="admin", user_id="user-simple")
    assert _call(client_app, method, path, body, token).status_code != 403


def test_role_resolution_two_levels():
    simple = {"app_metadata": {"role": "user"}, "user_metadata": {}}
    assert _resolve_user_system_role_and_job_title(simple)[::2] == ("user", False)
    promoted = {"app_metadata": {"role": "user"}, "user_metadata": {}}
    assert _resolve_user_system_role_and_job_title(promoted, {"is_admin": True})[::2] == ("admin", True)

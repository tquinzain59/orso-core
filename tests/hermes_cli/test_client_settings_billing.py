"""Tests pour la page Paramètres Client, Profil, Mot de Passe et Facturation Stripe."""

import json
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from hermes_cli.web_routers.client_ui import router, _generate_invoice_pdf
from hermes_cli.dashboard_auth.client_jwt import _b64url_encode


def _make_test_jwt(
    tenant_id: str = "f3e25379-6531-479e-b276-3b3185e7421b",
    tenant_slug: str = "financia-solutions",
    is_admin: bool = True,
    role: str = "admin",
    user_id: str = "user-test-123",
    email: str = "sophie.martin@finarecee20.fr",
) -> str:
    """Génère un jeton JWT de test valide pour le client."""
    import hmac, hashlib
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "exp": 9999999999,
        "app_metadata": {
            "tenant_id": tenant_id,
            "tenant_slug": tenant_slug,
            "role": role,
            "is_admin": is_admin,
            "agents": ["jerome", "lucas"],
        },
        "user_metadata": {
            "full_name": "Sophie Martin",
            "role": "DAF",
            "phone": "+33 6 45 78 12 34",
            "is_admin": is_admin,
        },
    }
    h_b64 = _b64url_encode(json.dumps(header).encode("utf-8"))
    p_b64 = _b64url_encode(json.dumps(payload).encode("utf-8"))
    signing_input = f"{h_b64}.{p_b64}".encode("ascii")
    sig = _b64url_encode(hmac.new(b"test-jwt-secret", signing_input, hashlib.sha256).digest())
    return f"{h_b64}.{p_b64}.{sig}"


@pytest.fixture
def client_app(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "test-jwt-secret")
    monkeypatch.setenv("ORSO_CLIENT_ID", "f3e25379-6531-479e-b276-3b3185e7421b")
    monkeypatch.setenv("ORSO_CLIENT_SLUG", "financia-solutions")
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_get_settings_profile(client_app):
    token = _make_test_jwt(is_admin=True)
    res = client_app.get("/api/client/settings/profile", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    data = res.json()
    assert "company" in data
    assert "user" in data

    comp = data["company"]
    assert comp["slug"] == "financia-solutions"
    assert "siret" in comp
    assert "environment" in comp
    assert comp["environment"]["status"] is not None

    usr = data["user"]
    assert usr["email"] == "sophie.martin@finarecee20.fr"
    assert usr["full_name"] == "Sophie Martin"
    assert usr["is_admin"] is True


def test_password_update_validation(client_app):
    token = _make_test_jwt()
    # 1. Mot de passe trop court
    res = client_app.post(
        "/api/client/settings/password",
        json={"new_password": "short", "confirm_password": "short"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 422 or res.status_code == 400

    # 2. Mots de passe non correspondants
    res2 = client_app.post(
        "/api/client/settings/password",
        json={"new_password": "password12345", "confirm_password": "password99999"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res2.status_code == 400
    assert "correspond pas" in res2.json()["detail"]


def test_password_update_success(client_app):
    token = _make_test_jwt()
    res = client_app.post(
        "/api/client/settings/password",
        json={"new_password": "NouveauMotDePasse2026!", "confirm_password": "NouveauMotDePasse2026!"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    assert res.json()["success"] is True


def test_billing_forbidden_for_non_admin(client_app):
    # Jeton non-admin
    token_non_admin = _make_test_jwt(is_admin=False, role="collaborateur")
    res = client_app.get("/api/client/billing", headers={"Authorization": f"Bearer {token_non_admin}"})
    assert res.status_code == 403
    assert "réservée aux administrateurs" in res.json()["detail"]


def test_billing_admin_access(client_app):
    token_admin = _make_test_jwt(is_admin=True)
    res = client_app.get("/api/client/billing", headers={"Authorization": f"Bearer {token_admin}"})
    assert res.status_code == 200
    data = res.json()

    assert "subscription" in data
    assert "available_tiers" in data
    assert "invoices" in data
    assert len(data["available_tiers"]) >= 4

    sub = data["subscription"]
    assert sub["tier_id"] in ["1_agent", "2_agents", "3_agents", "4_agents"]
    assert sub["price_ht"] > 0
    assert sub["payment_method"] is not None

    invs = data["invoices"]
    assert len(invs) >= 1
    assert invs[0]["number"] is not None
    assert invs[0]["amount_ht"] > 0


def test_billing_update_subscription(client_app):
    token_admin = _make_test_jwt(is_admin=True)

    # 1. Palier invalide
    res_err = client_app.post(
        "/api/client/billing/subscription",
        json={"tier_id": "invalid_tier"},
        headers={"Authorization": f"Bearer {token_admin}"},
    )
    assert res_err.status_code == 400

    # 2. Passage au palier 2_agents (Duo)
    res_ok = client_app.post(
        "/api/client/billing/subscription",
        json={"tier_id": "2_agents"},
        headers={"Authorization": f"Bearer {token_admin}"},
    )
    assert res_ok.status_code == 200
    data = res_ok.json()
    assert data["success"] is True
    assert data["subscription"]["tier_id"] == "2_agents"
    assert data["subscription"]["price_ht"] == 169.00


def test_billing_update_subscription_forbidden_non_admin(client_app):
    token_non_admin = _make_test_jwt(is_admin=False, role="collaborateur")
    res = client_app.post(
        "/api/client/billing/subscription",
        json={"tier_id": "2_agents"},
        headers={"Authorization": f"Bearer {token_non_admin}"},
    )
    assert res.status_code == 403


def test_billing_portal_session(client_app, monkeypatch):
    token_admin = _make_test_jwt(is_admin=True)

    # Mock stripe request
    def mock_stripe_request(endpoint, method="GET", data=None):
        if "customers" in endpoint:
            return {"data": [{"id": "cus_test_123"}]}
        if "billing_portal/sessions" in endpoint:
            return {"url": "https://billing.stripe.com/p/session/test_123"}
        return {}

    monkeypatch.setattr("hermes_cli.web_routers.client_ui._stripe_request", mock_stripe_request)
    monkeypatch.setattr("hermes_cli.web_routers.client_ui._get_stripe_secret_key", lambda: "sk_test_fake")

    res = client_app.post("/api/client/billing/portal-session", headers={"Authorization": f"Bearer {token_admin}"})
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert "https://billing.stripe.com" in data["url"]


def test_download_invoice_pdf(client_app):
    token = _make_test_jwt(is_admin=True)
    res = client_app.get(
        "/api/client/billing/invoices/inv_orso_001/download",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/pdf"
    assert "attachment" in res.headers.get("content-disposition", "")
    assert res.content.startswith(b"%PDF-1.4")


def test_generate_invoice_pdf_content():
    pdf = _generate_invoice_pdf(
        title="ORSO AGENTS - FACTURE OFFICIELLE",
        number="ORSO-2026-0001",
        date="28/09/2026",
        client_name="Test Enterprise",
        siret="12345678900012",
        amount_ht=169.00,
        amount_ttc=202.80,
    )
    assert pdf.startswith(b"%PDF-1.4")
    assert b"Test Enterprise" in pdf
    assert b"ORSO-2026-0001" in pdf

"""Tests unitaires automatisés pour le gestionnaire Ops et la facturation Olympe."""

import pytest
from fastapi.testclient import TestClient

from olympe.auth import MOCK_SUPERADMIN_TOKEN
from olympe.ops_manager import OpsManager, TIER_PRICING
from olympe.server import app


@pytest.fixture
def api_client():
    return TestClient(app, headers={"Authorization": f"Bearer {MOCK_SUPERADMIN_TOKEN}"})


def test_ops_manager_seed_data():
    """Vérifie la consistance des données initiales d'amorçage."""
    ops = OpsManager()
    tenants = ops.get_tenants_overview()
    assert len(tenants) >= 4

    # Vérification d'un client bien connu (Financia Solutions)
    financia = next((t for t in tenants if t["slug"] == "financia-solutions"), None)
    assert financia is not None
    assert financia["siret"] == "83214567800012"
    assert "jerome" in financia["agents_enabled"]["active"]
    assert financia["subscription"]["price_ht"] == 99.00


def test_ops_manager_kpis():
    """Vérifie le calcul correct du MRR avec la grille tarifaire (99€, 169€, 279€ HT)."""
    ops = OpsManager()
    stats = ops.get_stats()
    kpis = stats["kpis"]

    assert kpis["total_clients"] >= 4
    assert kpis["active_subscribers"] >= 3
    assert kpis["trialing_clients"] >= 1

    # 99€ (Financia) + 169€ (CommerciaLink) + 279€ (HexaTech) = 547.00 € HT
    assert kpis["mrr_ht"] == 547.00
    assert kpis["arr_ht"] == 547.00 * 12
    assert kpis["mrr_ttc"] == round(547.00 * 1.20, 2)


def test_update_tenant_agents_toggle_and_trials():
    """Vérifie l'activation/désactivation d'un agent et la configuration de période d'essai."""
    ops = OpsManager()
    tenant_id = "f3e25379-6531-479e-b276-3b3185e7421b"

    # Activation de Clara en plus de Jérôme et Lucas avec une période d'essai 14j
    trials = {
        "clara": {
            "is_trial": True,
            "start_date": "2026-09-21T18:00:00Z",
            "end_date": "2026-10-05T18:00:00Z",
            "days_remaining": 14,
        }
    }
    res = ops.update_tenant_agents(
        tenant_id=tenant_id,
        active_agents=["jerome", "lucas", "clara"],
        trials_config=trials,
    )
    assert res["success"] is True
    assert set(res["agents_enabled"]["active"]) == {"jerome", "lucas", "clara"}
    assert res["agents_enabled"]["trials"]["clara"]["days_remaining"] == 14

    # Vérification dans le détail
    detail = ops.get_tenant_detail(tenant_id)
    assert "clara" in detail["agents_enabled"]["active"]


def test_api_ops_endpoints(api_client):
    """Vérifie le bon fonctionnement des routes FastAPI /api/olympe/ops/*."""
    # 1. Stats
    resp_stats = api_client.get("/api/olympe/ops/stats")
    assert resp_stats.status_code == 200
    data_stats = resp_stats.json()
    assert "kpis" in data_stats
    assert data_stats["kpis"]["mrr_ht"] >= 547.00

    # 2. Liste des clients
    resp_tenants = api_client.get("/api/olympe/ops/tenants")
    assert resp_tenants.status_code == 200
    tenants = resp_tenants.json()["tenants"]
    assert len(tenants) >= 4

    # 3. Modification d'agents via API
    target_id = tenants[0]["id"]
    payload = {
        "active": ["jerome", "victor"],
        "trials": {"victor": {"is_trial": True, "days_remaining": 7}},
    }
    resp_update = api_client.post(f"/api/olympe/ops/tenants/{target_id}/agents", json=payload)
    assert resp_update.status_code == 200
    assert resp_update.json()["success"] is True

    # 4. Liste des factures
    resp_invoices = api_client.get("/api/olympe/ops/invoices")
    assert resp_invoices.status_code == 200
    assert len(resp_invoices.json()["invoices"]) >= 3


def test_stripe_webhook_handling(api_client):
    """Vérifie la réception et le traitement des webhooks Stripe."""
    payload = {
        "id": "evt_test_001",
        "type": "customer.subscription.updated",
        "data": {
            "object": {
                "id": "sub_test_123",
                "customer": "cus_test_456",
                "status": "active",
            }
        },
    }
    resp = api_client.post("/api/olympe/ops/webhooks/stripe", json=payload)
    assert resp.status_code == 200
    assert resp.json()["status"] == "processed"


def test_ops_manager_multi_users():
    """Vérifie la présence et la structure multi-utilisateurs pour les clients."""
    ops = OpsManager()
    financia = ops.get_tenant_detail("financia-solutions")
    assert financia is not None
    assert "users" in financia
    assert len(financia["users"]) >= 2

    # Vérification des profils admin vs standard
    sophie = next((u for u in financia["users"] if u["email"] == "sophie.martin@finarecee20.fr"), None)
    assert sophie is not None
    assert sophie["is_admin"] is True
    assert sophie["role"] == "DAF"

    lucas = next((u for u in financia["users"] if u["email"] == "lucas.compta@finarecee20.fr"), None)
    assert lucas is not None
    assert lucas["is_admin"] is False
    assert lucas["role"] == "Comptable"


def test_api_tenant_users_crud(api_client):
    """Vérifie la création, la consultation et la suppression d'un utilisateur pour un client via l'API Olympe."""
    # 1. Liste des utilisateurs
    resp_users = api_client.get("/api/olympe/ops/tenants/financia-solutions/users")
    assert resp_users.status_code == 200
    users = resp_users.json()["users"]
    initial_count = len(users)
    assert initial_count >= 2

    # 2. Création d'un nouvel utilisateur
    new_user_payload = {
        "email": "nicolas.treso@finarecee20.fr",
        "full_name": "Nicolas Trésorier",
        "role": "Trésorier",
        "is_admin": False,
    }
    resp_create = api_client.post(
        "/api/olympe/ops/tenants/financia-solutions/users",
        json=new_user_payload,
    )
    assert resp_create.status_code == 200
    created = resp_create.json()["user"]
    assert created["email"] == "nicolas.treso@finarecee20.fr"
    assert created["is_admin"] is False
    assert created["role"] == "Trésorier"
    user_id = created["id"]

    # 3. Vérification de l'ajout
    resp_after = api_client.get("/api/olympe/ops/tenants/financia-solutions/users")
    users_after = resp_after.json()["users"]
    assert len(users_after) == initial_count + 1

    # 4. Suppression de l'utilisateur
    resp_del = api_client.delete(f"/api/olympe/ops/tenants/financia-solutions/users/{user_id}")
    assert resp_del.status_code == 200
    assert resp_del.json()["success"] is True

    # 5. Vérification post-suppression
    resp_final = api_client.get("/api/olympe/ops/tenants/financia-solutions/users")
    assert len(resp_final.json()["users"]) == initial_count

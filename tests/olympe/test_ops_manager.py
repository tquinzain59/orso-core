import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

from olympe.auth import MOCK_SUPERADMIN_TOKEN
from olympe.ops_manager import OpsManager, TIER_PRICING
from olympe.server import app

@pytest.fixture
def api_client():
    return TestClient(app, headers={"Authorization": f"Bearer {MOCK_SUPERADMIN_TOKEN}"})

def test_ops_manager_seed_data():
    ops = OpsManager()
    tenants = ops.get_tenants_overview()
    assert len(tenants) >= 4

    financia = next((t for t in tenants if t["slug"] == "financia-solutions"), None)
    assert financia is not None
    assert financia["siret"] == "83214567800012"
    assert "jerome" in financia["agents_enabled"]["active"]
    assert financia["subscription"]["price_ht"] == 99.00

def test_ops_manager_kpis():
    ops = OpsManager()
    stats = ops.get_stats()
    kpis = stats["kpis"]

    assert kpis["total_clients"] >= 4
    assert kpis["active_subscribers"] == 1
    assert kpis["mrr_ht"] == 99.00

def test_update_tenant_agents_toggle_and_trials():
    ops = OpsManager()
    # Financia Solutions is Starter (1 agent max)
    tenant_id = "f3e25379-6531-479e-b276-3b3185e7421b"

    # Trying to add 2 agents should fail because of quota
    with pytest.raises(ValueError, match="Quota dépassé"):
        ops.update_tenant_agents(
            tenant_id=tenant_id,
            active_agents=["jerome", "lucas"],
        )

def test_update_tenant_subscription_cascade():
    ops = OpsManager()
    tenant_id = "f3e25379-6531-479e-b276-3b3185e7421b"
    # Upgrade to Duo to add 2 agents
    ops.update_tenant_subscription(tenant_id, "2_agents", "active")
    ops.update_tenant_agents(tenant_id, ["jerome", "lucas"])
    
    # Cancel subscription -> should purge agents
    ops.update_tenant_subscription(tenant_id, "none", "canceled")
    t = ops.get_tenant_detail(tenant_id)
    assert len(t["agents_enabled"]["active"]) == 0
    assert t["instance"]["status"] == "not_provisioned"

def test_api_ops_endpoints(api_client):
    resp_stats = api_client.get("/api/olympe/ops/stats")
    assert resp_stats.status_code == 200
    data_stats = resp_stats.json()
    assert data_stats["kpis"]["mrr_ht"] == 99.00

    resp_overview = api_client.get("/api/olympe/ops/tenants")
    assert resp_overview.status_code == 200
    tenants = resp_overview.json()["tenants"]

    target_id = tenants[0]["id"]
    # Change sub to 4_agents to allow setting 2 agents
    api_client.post(f"/api/olympe/ops/tenants/{target_id}/subscription", json={"tier_id": "4_agents", "status": "active"})

    payload = {
        "active": ["jerome", "victor"],
        "trials": {"victor": {"is_trial": True, "days_remaining": 7}},
    }
    resp_update = api_client.post(f"/api/olympe/ops/tenants/{target_id}/agents", json=payload)
    assert resp_update.status_code == 200
    updated_data = resp_update.json()
    assert "victor" in updated_data["agents_enabled"]["active"]
    assert updated_data["agents_enabled"]["trials"]["victor"]["is_trial"] is True


def test_3_agents_tier_and_quota():
    ops = OpsManager()
    tenant_id = "f3e25379-6531-479e-b276-3b3185e7421b"
    ops.update_tenant_subscription(tenant_id, "3_agents", "active")
    t = ops.get_tenant_detail(tenant_id)
    assert t["subscription"]["price_ht"] == 229.00
    assert t["subscription"]["tier_id"] == "3_agents"

    # Can add 3 agents
    ops.update_tenant_agents(tenant_id, ["jerome", "lucas", "clara"])
    assert len(ops.get_tenant_detail(tenant_id)["agents_enabled"]["active"]) == 3

    # Adding 4th agent fails due to quota
    with pytest.raises(ValueError, match="Quota dépassé"):
        ops.update_tenant_agents(tenant_id, ["jerome", "lucas", "clara", "victor"])


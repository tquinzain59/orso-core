import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

from olympe.auth import MOCK_SUPERADMIN_TOKEN
from olympe.ops_manager import OpsManager, TIER_PRICING
from olympe.server import app, ops_manager

@pytest.fixture(autouse=True)
def enable_demo_mode_for_seed_tests(monkeypatch):
    monkeypatch.setenv("ORSO_DEMO_MODE", "1")
    ops_manager.demo_mode = True
    ops_manager._mock_tenants = ops_manager._init_seed_data()

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


def test_telemetry_endpoints(api_client):
    # 1. Summary
    resp_summary = api_client.get("/api/olympe/ops/telemetry/summary")
    assert resp_summary.status_code == 200
    summary = resp_summary.json()
    assert "total_tokens" in summary
    assert "total_cost_usd" in summary

    # 2. Environments
    resp_envs = api_client.get("/api/olympe/ops/telemetry/environments")
    assert resp_envs.status_code == 200
    envs_data = resp_envs.json()
    assert "environments" in envs_data
    assert len(envs_data["environments"]) == 2
    env_names = [e["display_name"] for e in envs_data["environments"]]
    assert "Recouvrement" not in env_names
    assert "PROD-FR-002" in env_names
    assert "Olympe" in env_names
    container_ids = [e["container_id"] for e in envs_data["environments"]]
    assert "recouvrement_default" not in container_ids
    first_env = envs_data["environments"][0]
    assert "display_name" in first_env
    assert "vitals" in first_env
    assert "tenant" in first_env

    # 3. History
    resp_hist = api_client.get("/api/olympe/ops/telemetry/history/1?limit=5")
    assert resp_hist.status_code == 200
    hist_data = resp_hist.json()
    assert "snapshots" in hist_data

    # 4. Alerts
    resp_alerts = api_client.get("/api/olympe/ops/telemetry/alerts")
    assert resp_alerts.status_code == 200
    alerts_data = resp_alerts.json()
    assert "alerts" in alerts_data


def test_onboarding_pending_and_orders():
    ops = OpsManager()
    pending = ops.get_pending_onboarding()
    assert len(pending) >= 1

    lumina = next((t for t in pending if t["slug"] == "lumina-solutions"), None)
    assert lumina is not None
    assert lumina["siret"] == "91234567800029"
    assert lumina["legal_form"] == "SAS"
    assert lumina["city"] == "Paris"
    assert lumina["contact"]["phone"] == "+33 6 12 34 56 78"

    agent_insts = lumina.get("agent_instances", [])
    assert len(agent_insts) == 2
    jerome = next((a for a in agent_insts if a["agent_slug"] == "jerome"), None)
    assert jerome is not None
    assert jerome["provisioning_status"] == "PENDING_SETUP"
    assert "1. Contexte & Enjeux Stratégiques" in jerome["mission_letter"]
    assert "2. Objectifs Prioritaires & Chiffrés" in jerome["mission_letter"]
    assert "3. Ligne de Conduite, Tonalité & Posture" in jerome["mission_letter"]
    assert "4. Déclencheurs d'Escalade Humaine Immédiate" in jerome["mission_letter"]
    assert jerome["integration_tool"] == "Pennylane"
    assert jerome["escalation_threshold_eur"] == 5000.00


def test_onboarding_provision_order():
    ops = OpsManager()
    lumina_id = "7a192844-3c82-4112-9214-abcdef123456"
    res = ops.provision_onboarding_order(lumina_id)
    assert res["success"] is True
    assert res["status"] == "ACTIVE"

    # Vérification que le statut est mis à jour
    detail = ops.get_onboarding_order_detail(lumina_id)
    assert detail["status"] == "active"
    assert detail["instance"]["status"] == "ready"
    assert all(a["provisioning_status"] == "ACTIVE" for a in detail["agent_instances"])


def test_onboarding_api_endpoints(api_client):
    # 1. Pending
    resp_pending = api_client.get("/api/olympe/ops/onboarding/pending")
    assert resp_pending.status_code == 200
    pending_data = resp_pending.json()
    assert "pending" in pending_data
    assert pending_data["count"] >= 1

    # 2. Orders
    resp_orders = api_client.get("/api/olympe/ops/onboarding/orders")
    assert resp_orders.status_code == 200
    orders_data = resp_orders.json()
    assert "orders" in orders_data

    # 3. OVH Sizing
    resp_sizing = api_client.get("/api/olympe/ops/onboarding/ovh-sizing")
    assert resp_sizing.status_code == 200
    sizing_data = resp_sizing.json()
    assert "recommended_flavor" in sizing_data
    assert "ram_mb_estimated" in sizing_data
    assert "docker_deploy_snippet" in sizing_data


def test_normalize_agent_slugs_and_roles():
    from olympe.ops_manager import normalize_agent_slug, normalize_agents_enabled, OpsManager

    assert normalize_agent_slug("recouvrement") == "jerome"
    assert normalize_agent_slug("commercial") == "lucas"
    assert normalize_agent_slug("prospection") == "lucas"
    assert normalize_agent_slug("support") == "clara"
    assert normalize_agent_slug("ao") == "victor"
    assert normalize_agent_slug("appel_offres") == "victor"
    assert normalize_agent_slug("jerome") == "jerome"

    # Test normalize_agents_enabled list format
    norm_list = normalize_agents_enabled(["recouvrement", "ao"])
    assert norm_list == {"active": ["jerome", "victor"], "trials": {}}

    # Test normalize_agents_enabled dict format with trials
    norm_dict = normalize_agents_enabled({
        "active": ["recouvrement"],
        "trials": {"recouvrement": {"is_trial": True, "days_remaining": 30}}
    })
    assert norm_dict["active"] == ["jerome"]
    assert "jerome" in norm_dict["trials"]
    assert norm_dict["trials"]["jerome"]["is_trial"] is True

    # Test update_tenant_agents with legacy role alias
    ops = OpsManager(demo_mode=True)
    tenant_id = "f3e25379-6531-479e-b276-3b3185e7421b"
    res = ops.update_tenant_agents(tenant_id, ["recouvrement"])
    assert res["agents_enabled"]["active"] == ["jerome"]





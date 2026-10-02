"""Tests d'acceptation stricts pour le ticket KAN-74.

Valide les 5 critères d'acceptation (CA1 à CA5) selon l'arbitrage formel Option B :
- CA1 : Lucidité de la sonde de santé (/api/olympe/health) sur superviseur sans démon local
- CA2 : Interdiction d'écrire un statut actif/prêt en base lors d'opérations simulées en production
- CA3 : Refus explicite et journalisé de création in-process impossible en production
- CA4 : Présence explicite des champs 'mode' et 'action_taken' sur les 4 routes de cycle de vie
- CA5 : Existence et conformité des pièces d'architecture (ADR 2026-10-01-05 et spécification technique)
"""

import os
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from olympe.auth import MOCK_SUPERADMIN_TOKEN
from olympe.lifecycle_manager import DockerLifecycleManager
from olympe.server import app, manager, ops_manager


@pytest.fixture(autouse=True)
def setup_acceptance_env(monkeypatch):
    monkeypatch.setenv("ORSO_DEMO_MODE", "1")
    monkeypatch.setenv("ORSO_PERSONA_HMAC_KEY", "test_secret_hmac_key_for_acceptance_0123456789")
    monkeypatch.setenv("ORSO_TARGET_ENGINE_DIGEST", "sha256:" + "a" * 64)
    ops_manager.demo_mode = True
    ops_manager._mock_tenants = ops_manager._init_seed_data()


@pytest.fixture
def client():
    return TestClient(app)


def test_kan74_ca1_health_probe_reports_delegated_mode_without_local_docker(client, monkeypatch):
    """CA1 — /api/olympe/health reflète l'accès réel et précise le rôle delegated_host_provisioning."""
    monkeypatch.setattr(manager, "has_docker", False)

    resp = client.get("/api/olympe/health")
    assert resp.status_code == 200
    data = resp.json()

    assert data["service"] == "olympe-core"
    assert data["status"] == "healthy"
    assert data["docker_available"] is False
    assert data["fleet_mode"] == "delegated_host_provisioning"
    assert data["mode"] == "delegated_host"


def test_kan74_ca2_no_active_or_ready_written_in_production_db(monkeypatch):
    """CA2 — En production, aucune écriture active ou prête n'est permise après simulation."""
    monkeypatch.setenv("ORSO_ENV", "production")
    monkeypatch.setattr(manager, "has_docker", False)

    slug = "test-prod-guard"
    tenant_id = f"test-{slug}"
    mock_tenant = {
        "id": tenant_id,
        "name": "Prod Guard Test",
        "slug": slug,
        "subscription": {"status": "active", "stripe_customer_id": "cus_prod_test"},
        "instance": {"status": "not_provisioned", "environment_status": "inactive"},
    }
    ops_manager._mock_tenants[tenant_id] = mock_tenant
    monkeypatch.setattr(ops_manager, "get_tenant_detail", lambda tid: mock_tenant if tid == tenant_id else None)

    # Tentative d'écriture simulée en production via le worker/ops_manager
    with pytest.raises(ValueError) as excinfo:
        ops_manager.provision_onboarding_order(tenant_id, is_simulated=True)

    assert "CA2 KAN-74" in str(excinfo.value)
    # L'instance reste inchangée
    assert ops_manager._mock_tenants[tenant_id]["instance"]["status"] == "not_provisioned"
    assert ops_manager._mock_tenants[tenant_id]["instance"]["environment_status"] == "inactive"


def test_kan74_ca3_impossible_creation_produces_explicit_logged_refusal_in_production(monkeypatch):
    """CA3 — Une tentative in-process sans Docker local en production produit un refus explicite journalisé."""
    monkeypatch.setenv("ORSO_ENV", "production")
    monkeypatch.setattr(manager, "has_docker", False)

    res = manager.provision_tenant(
        tenant_id="test-prod-tenant",
        tenant_slug="prod-client",
        image_name="ghcr.io/tquinzain59/orso-engine:latest",
        image_digest="sha256:" + "a" * 64,
    )

    assert res["success"] is False
    assert res["error"] == "ERR_NO_LOCAL_DOCKER_DELEGATED_HOST_REQUIRED"
    assert res["mode"] == "delegated_host"
    assert res["action_taken"] is False
    assert "exclusivement délégué" in res["message"]


def test_kan74_ca4_all_four_lifecycle_routes_explicitly_name_mode_and_action_taken(client, monkeypatch):
    """CA4 — Les 4 routes (status, wake, suspend, provision) portent explicitement mode et action_taken."""
    admin_headers = {"Authorization": f"Bearer {MOCK_SUPERADMIN_TOKEN}"}
    monkeypatch.setattr(manager, "has_docker", False)

    # 1. Route d'état : GET /api/olympe/tenants/status/{slug}
    resp_status = client.get("/api/olympe/tenants/status/financia-solutions", headers=admin_headers)
    assert resp_status.status_code == 200
    st_data = resp_status.json()
    assert st_data["simulated"] is True
    assert st_data["mode"] in ("simulated", "delegated_host")
    assert st_data["action_taken"] is False

    # 2. Route de réveil : POST /api/olympe/tenants/wake/{slug}
    # En environnement hors production (simulé) :
    resp_wake = client.post("/api/olympe/tenants/wake/financia-solutions", headers=admin_headers)
    assert resp_wake.status_code == 200
    wake_data = resp_wake.json()
    assert wake_data["success"] is True
    assert wake_data["mode"] == "simulated"
    assert wake_data["action_taken"] is False

    # En environnement production : refus 400 avec mode et action_taken
    monkeypatch.setenv("ORSO_ENV", "production")
    monkeypatch.setattr(ops_manager, "get_tenant_detail", lambda slug: {"id": "test-financia", "slug": slug, "subscription": {"status": "active"}})
    resp_wake_prod = client.post("/api/olympe/tenants/wake/financia-solutions", headers=admin_headers)
    assert resp_wake_prod.status_code == 400
    wake_prod_detail = resp_wake_prod.json()["detail"]
    assert "ERR_NO_LOCAL_DOCKER_DELEGATED_HOST_REQUIRED" in wake_prod_detail
    assert "mode=delegated_host" in wake_prod_detail
    assert "action_taken=False" in wake_prod_detail
    monkeypatch.delenv("ORSO_ENV", raising=False)
    monkeypatch.setattr(manager, "has_docker", False)

    # 3. Route de mise en veille : POST /api/olympe/tenants/suspend/{slug}
    resp_suspend = client.post("/api/olympe/tenants/suspend/financia-solutions", headers=admin_headers)
    assert resp_suspend.status_code == 200
    susp_data = resp_suspend.json()
    assert susp_data["success"] is True
    assert susp_data["status"] == "sleeping"
    assert susp_data["simulated"] is True
    assert susp_data["mode"] == "simulated"
    assert susp_data["action_taken"] is False
    assert "mode" in susp_data["message"].lower()

    # 4. Route de provisioning : POST /api/olympe/tenants/provision
    # Hors production :
    prov_payload = {
        "tenant_id": "test-new-client",
        "tenant_slug": "nouveau-client",
        "image_name": "orso-backend:latest",
    }
    resp_prov = client.post("/api/olympe/tenants/provision", json=prov_payload, headers=admin_headers)
    assert resp_prov.status_code == 200
    prov_data = resp_prov.json()
    assert prov_data["success"] is True
    assert prov_data["simulated"] is True
    assert prov_data["mode"] == "simulated"
    assert prov_data["action_taken"] is False

    # En production :
    monkeypatch.setenv("ORSO_ENV", "production")
    resp_prov_prod = client.post("/api/olympe/tenants/provision", json=prov_payload, headers=admin_headers)
    assert resp_prov_prod.status_code == 400
    prov_prod_detail = resp_prov_prod.json()["detail"]
    assert "ERR_NO_LOCAL_DOCKER_DELEGATED_HOST_REQUIRED" in prov_prod_detail
    assert "mode=delegated_host" in prov_prod_detail
    assert "action_taken=False" in prov_prod_detail


def test_kan74_ca5_architecture_documentation_presence():
    """CA5 — Vérifie l'existence et la substance des livrables documentaires KAN-74."""
    root_dir = Path(__file__).resolve().parent.parent.parent
    adr_file = root_dir / "docs" / "ADR" / "2026-10-01-05-arbitrage-provisioning-production-kan74.md"
    spec_file = root_dir / "docs" / "3_Technique" / "spec_kan74_arbitrage_provisioning_production.md"

    assert adr_file.is_file(), "Le fichier ADR 05 KAN-74 doit exister dans docs/ADR/"
    assert spec_file.is_file(), "Le fichier de spécification technique KAN-74 doit exister dans docs/3_Technique/"

    adr_text = adr_file.read_text(encoding="utf-8")
    assert "Option B" in adr_text
    assert "PROD-FR-003" in adr_text
    assert "KAN-74" in adr_text
    assert "delegated_host_provisioning" in adr_text

    spec_text = spec_file.read_text(encoding="utf-8")
    assert "Option B" in spec_text
    assert "ERR_NO_LOCAL_DOCKER_DELEGATED_HOST_REQUIRED" in spec_text
    assert "CA1" in spec_text and "CA5" in spec_text

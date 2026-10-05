"""Tests d'acceptation et de non-régression pour KAN-59 (Document 27, section 6 étape 6 & section 9).

Vérifie les 4 critères d'acceptation du ticket :
- CA1 : Aucun conteneur client n'est créé sans limites de processeur, de mémoire, de swap et de processus.
- CA2 : Une demande de provisioning qui dépasserait la capacité disponible est refusée explicitement,
        avec message et journal, sans dégrader les espaces en service.
- CA3 : Les valeurs retenues sont dérivées de mesures empiriques et non de règles de pouce abstraites.
- CA4 : La capacité déclarée par palier tarifaire est écrite et cohérente avec le catalogue de tailles.
"""

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from olympe.auth import MOCK_SUPERADMIN_TOKEN
from olympe.lifecycle_manager import (
    DEFAULT_CLIENT_QUOTAS,
    TIER_RESOURCE_QUOTAS,
    DockerLifecycleManager,
    get_quotas_for_tier,
    parse_cpus_str_to_float,
    parse_memory_str_to_mb,
)
from olympe.ops_manager import TIER_PRICING
from olympe.ovh_client import OVH_FLAVORS, OVHClient
from olympe.server import app, ops_manager


@pytest.fixture(autouse=True)
def setup_demo_mode_kan59(monkeypatch):
    monkeypatch.setenv("ORSO_DEMO_MODE", "1")
    monkeypatch.setenv("HERMES_DASHBOARD_BASIC_AUTH_USERNAME", "admin")
    monkeypatch.setenv("HERMES_DASHBOARD_BASIC_AUTH_PASSWORD", "testpass123")
    ops_manager.demo_mode = True
    ops_manager._mock_tenants = ops_manager._init_seed_data()


@pytest.fixture
def api_client():
    return TestClient(app)


# ── CA1 : Aucun conteneur sans quotas explicites ──────────────────────────────

def test_kan59_ca1_no_container_without_quotas(tmp_path):
    """CA1 : Garantit que même sans quotas spécifiés, les quotas stricts sont toujours appliqués."""
    manager = DockerLifecycleManager(
        data_root=str(tmp_path / "tenants"),
        spaces_root=str(tmp_path / "spaces"),
    )
    manager.has_docker = True

    status_not_found = {"status": "not_found", "running": False}
    recorded_calls = []

    def fake_exec_docker(args, timeout=20.0):
        recorded_calls.append(list(args))
        if args and args[0] == "ps":
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="cid_ca1", stderr="")

    with patch.object(manager, "get_tenant_status", return_value=status_not_found):
        with patch.object(manager, "_exec_docker", side_effect=fake_exec_docker):
            with patch.object(manager, "_sync_tenant_instance_record"):
                # 1. Provisioning sans aucun quota explicite (quotas=None)
                res = manager.provision_tenant(
                    tenant_id="uuid-ca1-default",
                    tenant_slug="client-ca1-default",
                    allow_floating_tag=True,
                    persona_hmac_key="mock-hmac-key",
                )
                assert res["success"] is True
                assert res["quotas"] == DEFAULT_CLIENT_QUOTAS

                run_calls = [c for c in recorded_calls if c and c[0] == "run"]
                assert len(run_calls) == 1
                cmd = run_calls[0]

                # Vérification présence des limites physiques Docker
                assert "--cpus" in cmd
                assert cmd[cmd.index("--cpus") + 1] == "0.5"
                assert "--memory" in cmd
                assert cmd[cmd.index("--memory") + 1] == "512m"
                assert "--memory-swap" in cmd
                assert cmd[cmd.index("--memory-swap") + 1] == "512m"
                assert "--pids-limit" in cmd
                assert cmd[cmd.index("--pids-limit") + 1] == "100"

                # Vérification des labels normalisés
                assert "--label" in cmd
                assert "com.orso.quotas.cpus=0.5" in cmd
                assert "com.orso.quotas.memory=512m" in cmd
                assert "com.orso.quotas.pids_limit=100" in cmd


def test_kan59_ca1_tier_quotas_applied(tmp_path):
    """CA1 : Vérifie que le palier tarifaire Duo (2 agents) applique 1.0 vCPU, 1024m RAM et 150 PIDs."""
    manager = DockerLifecycleManager(
        data_root=str(tmp_path / "tenants"),
        spaces_root=str(tmp_path / "spaces"),
    )
    manager.has_docker = True

    status_not_found = {"status": "not_found", "running": False}
    recorded_calls = []

    def fake_exec_docker(args, timeout=20.0):
        recorded_calls.append(list(args))
        if args and args[0] == "ps":
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="cid_ca1_duo", stderr="")

    with patch.object(manager, "get_tenant_status", return_value=status_not_found):
        with patch.object(manager, "_exec_docker", side_effect=fake_exec_docker):
            with patch.object(manager, "_sync_tenant_instance_record"):
                res = manager.provision_tenant(
                    tenant_id="uuid-ca1-duo",
                    tenant_slug="client-ca1-duo",
                    tier_id="2_agents",
                    allow_floating_tag=True,
                    persona_hmac_key="mock-hmac-key",
                )
                assert res["success"] is True
                assert res["quotas"]["cpus"] == "1.0"
                assert res["quotas"]["memory"] == "1024m"
                assert res["quotas"]["pids_limit"] == "150"

                run_calls = [c for c in recorded_calls if c and c[0] == "run"]
                cmd = run_calls[0]
                assert cmd[cmd.index("--cpus") + 1] == "1.0"
                assert cmd[cmd.index("--memory") + 1] == "1024m"
                assert cmd[cmd.index("--memory-swap") + 1] == "1024m"
                assert cmd[cmd.index("--pids-limit") + 1] == "150"
                assert "com.orso.tier_id=2_agents" in cmd


# ── CA2 : Refus de provisioning au-delà de la capacité de l'hôte ─────────────

def test_kan59_ca2_host_capacity_exceeded_refusal(tmp_path):
    """CA2 : Refuse explicitement une création qui dépasse la capacité hôte sans dégrader les conteneurs existants."""
    # Plafond configuré à 1024 Mo RAM et 1.0 vCPU
    manager = DockerLifecycleManager(
        data_root=str(tmp_path / "tenants"),
        spaces_root=str(tmp_path / "spaces"),
        host_max_memory_mb=1024,
        host_max_cpus=1.0,
    )
    # Mode simulé pour le contrôle d'admission
    manager.has_docker = False

    # 1. Provisioning du 1er client (512 Mo, 0.5 vCPU) -> Succès
    res1 = manager.provision_tenant(
        tenant_id="uuid-client-1",
        tenant_slug="client-1",
        tier_id="1_agent",
        allow_floating_tag=True,
        persona_hmac_key="hmac",
    )
    assert res1["success"] is True
    assert res1["quotas"]["memory"] == "512m"

    # Vérification allocation
    alloc1 = manager.get_host_allocated_resources()
    assert alloc1["allocated_memory_mb"] == 512
    assert alloc1["available_memory_mb"] == 512

    # 2. Provisioning du 2ème client (512 Mo, 0.5 vCPU) -> Succès (hôte plein à 100%)
    res2 = manager.provision_tenant(
        tenant_id="uuid-client-2",
        tenant_slug="client-2",
        tier_id="1_agent",
        allow_floating_tag=True,
        persona_hmac_key="hmac",
    )
    assert res2["success"] is True

    alloc2 = manager.get_host_allocated_resources()
    assert alloc2["allocated_memory_mb"] == 1024
    assert alloc2["available_memory_mb"] == 0

    # 3. Tentative de provisioning d'un 3ème client -> REFUS EXPLICITE (ERR_HOST_CAPACITY_EXCEEDED)
    res3 = manager.provision_tenant(
        tenant_id="uuid-client-3",
        tenant_slug="client-3",
        tier_id="1_agent",
        allow_floating_tag=True,
        persona_hmac_key="hmac",
    )
    assert res3["success"] is False
    assert res3["error"] == "ERR_HOST_CAPACITY_EXCEEDED"
    assert "Capacité mémoire de l'hôte dépassée" in res3["message"]
    assert res3["capacity_details"]["requested_memory_mb"] == 512
    assert res3["capacity_details"]["available_memory_mb"] == 0

    # 4. Vérification que les espaces 1 et 2 en service restent strictement intacts
    alloc_after = manager.get_host_allocated_resources()
    assert alloc_after["allocated_memory_mb"] == 1024
    assert alloc_after["containers_count"] == 2
    assert "client-1" in [c["slug"] for c in alloc_after["containers"]]
    assert "client-2" in [c["slug"] for c in alloc_after["containers"]]
    assert "client-3" not in [c["slug"] for c in alloc_after["containers"]]


def test_kan59_ca2_teardown_releases_host_capacity(tmp_path):
    """CA2 : La suppression d'un conteneur libère immédiatement la capacité matérielle sur l'hôte."""
    manager = DockerLifecycleManager(
        data_root=str(tmp_path / "tenants"),
        spaces_root=str(tmp_path / "spaces"),
        host_max_memory_mb=1024,
    )
    manager.has_docker = False

    manager.provision_tenant(
        tenant_id="uuid-client-rel",
        tenant_slug="client-rel",
        tier_id="2_agents",  # 1024 Mo
        allow_floating_tag=True,
        persona_hmac_key="hmac",
    )
    assert manager.get_host_allocated_resources()["available_memory_mb"] == 0

    # Destruction du conteneur
    del_res = manager.teardown_tenant("client-rel")
    assert del_res["success"] is True

    # Capacité redevenue disponible à 100%
    assert manager.get_host_allocated_resources()["available_memory_mb"] == 1024


# ── CA3 : Valeurs dérivées de mesures réelles du POC ──────────────────────────

def test_kan59_ca3_empirical_sizing_model():
    """CA3 : Valide que le modèle de dimensionnement intègre les mesures réelles au repos et en charge."""
    client = OVHClient()
    sizing = client.estimate_sizing(pending_tenants_count=3, pending_agents_count=4)

    assert sizing["sizing_model"] == "empirical_measured_kan59"
    # Empreinte réelle mesurée : 4 agents * 139 Mo (charge) + 3 conteneurs * 100 Mo (socle) = 856 Mo
    assert sizing["empirical_measured_ram_mb"] == (4 * 139) + (3 * 100)
    assert sizing["tier_quotas_ram_mb"] == (4 * 512)
    # Vérification que le snippet docker run embarque des quotas stricts
    assert "--cpus 0.5" in sizing["docker_deploy_snippet"]
    assert "--memory 512m" in sizing["docker_deploy_snippet"]
    assert "--pids-limit 100" in sizing["docker_deploy_snippet"]


# ── CA4 : Cohérence des paliers tarifaires et catalogue OVH ──────────────────

def test_kan59_ca4_pricing_and_quotas_matrix_consistency():
    """CA4 : Vérifie la cohérence croisée entre TIER_RESOURCE_QUOTAS, TIER_PRICING et OVH_FLAVORS."""
    for tier_id, quotas in TIER_RESOURCE_QUOTAS.items():
        if tier_id == "none":
            continue
        pricing = TIER_PRICING.get(tier_id)
        assert pricing is not None, f"Palier {tier_id} absent de TIER_PRICING"

        max_agents = pricing["max_agents"]
        mem_mb = parse_memory_str_to_mb(quotas["memory"])
        cpus = parse_cpus_str_to_float(quotas["cpus"])

        # Chaque agent supplémentaire est couvert par au moins 512 Mo de RAM
        if max_agents > 0:
            assert mem_mb >= max_agents * 512, f"Mémoire insuffisante pour {tier_id} ({mem_mb} Mo < {max_agents * 512} Mo)"
            assert cpus >= max_agents * 0.5, f"vCPU insuffisant pour {tier_id} ({cpus} < {max_agents * 0.5})"

    # Vérification de l'intégration dans OVH d2-4 (4096 Mo RAM)
    # Peut héberger au moins 3 instances Starter (1 agent) avec 1024 Mo de marge système
    d2_4 = OVH_FLAVORS["d2-4"]
    starter_quota_mem = parse_memory_str_to_mb(TIER_RESOURCE_QUOTAS["1_agent"]["memory"])
    system_margin = 1024
    usable_mem = d2_4["ram_mb"] - system_margin
    assert usable_mem // starter_quota_mem >= 3


# ── Les 3 chemins de provisioning ─────────────────────────────────────────────

def test_kan59_pathway_1_cockpit_onboarding_provision_refusal(api_client, monkeypatch):
    """Chemin 1 : Bouton d'onboarding du cockpit avec refus pour capacité hôte dépassée."""
    admin_headers = {"Authorization": f"Bearer {MOCK_SUPERADMIN_TOKEN}"}

    # Simulation d'un refus de capacité par le manager
    mock_refusal = {
        "success": False,
        "error": "ERR_HOST_CAPACITY_EXCEEDED",
        "tenant_slug": "financia-solutions",
        "message": "Capacité mémoire de l'hôte dépassée : 2048 Mo requis, 512 Mo disponibles.",
        "capacity_details": {"available_memory_mb": 512, "requested_memory_mb": 2048},
    }

    tenant_id = "tenant-001"
    ops_manager._mock_tenants[tenant_id] = {
        "id": tenant_id,
        "slug": "financia-solutions",
        "subscription": {"status": "active", "tier_id": "1_agent"},
    }
    with patch("olympe.server.manager.provision_tenant", return_value=mock_refusal):
        resp = api_client.post(f"/api/olympe/ops/onboarding/{tenant_id}/provision", headers=admin_headers)
        assert resp.status_code == 400
        assert "ERR_HOST_CAPACITY_EXCEEDED" in resp.json()["detail"]


def test_kan59_pathway_2_historic_provision_route(api_client, monkeypatch):
    """Chemin 2 : Route historique /api/olympe/tenants/provision avec quotas explicites."""
    admin_headers = {"Authorization": f"Bearer {MOCK_SUPERADMIN_TOKEN}"}

    recorded_kwargs = {}

    def mock_provision(**kwargs):
        recorded_kwargs.update(kwargs)
        return {
            "success": True,
            "tenant_slug": kwargs["tenant_slug"],
            "container_name": f"orso_client_{kwargs['tenant_slug']}",
            "status": "ready",
            "quotas": kwargs.get("quotas") or DEFAULT_CLIENT_QUOTAS,
        }

    with patch("olympe.server.manager.provision_tenant", side_effect=mock_provision):
        payload = {
            "tenant_id": "test-uuid-hist",
            "tenant_slug": "client-hist",
            "tier_id": "2_agents",
            "quotas": {"cpus": "1.0", "memory": "1024m", "pids_limit": "150"},
        }
        resp = api_client.post("/api/olympe/tenants/provision", json=payload, headers=admin_headers)
        assert resp.status_code == 200
        assert recorded_kwargs["tier_id"] == "2_agents"
        assert recorded_kwargs["quotas"]["memory"] == "1024m"


def test_kan59_pathway_3_stripe_webhook_auto_provision(monkeypatch):
    """Chemin 3 : Traitement webhook Stripe avec application automatique des quotas du forfait."""
    monkeypatch.setenv("ORSO_AUTO_PROVISION_ON_WEBHOOK", "1")

    recorded_kwargs = {}

    def mock_provision(**kwargs):
        recorded_kwargs.update(kwargs)
        return {
            "success": True,
            "tenant_slug": kwargs["tenant_slug"],
            "container_name": f"orso_client_{kwargs['tenant_slug']}",
            "status": "ready",
            "quotas": kwargs.get("quotas"),
        }

    mock_docker_mgr = MagicMock()
    mock_docker_mgr.provision_tenant.side_effect = mock_provision
    mock_docker_mgr.get_tenant_status.return_value = {"running": True}

    with patch("olympe.server.manager", mock_docker_mgr):
        payload = {
            "type": "customer.subscription.updated",
            "data": {
                "object": {
                    "id": "sub_test_stripe_webhook",
                    "customer": "cus_test_123",
                    "status": "active",
                    "metadata": {
                        "tenant_slug": "financia-solutions",
                        "tier_id": "4_agents",
                    },
                }
            },
        }
        res = ops_manager.handle_stripe_webhook(payload)
        assert res.get("status") == "processed"
        assert recorded_kwargs["tier_id"] == "4_agents"
        assert recorded_kwargs["quotas"]["memory"] == "2048m"
        assert recorded_kwargs["quotas"]["cpus"] == "2.0"
        assert recorded_kwargs["quotas"]["pids_limit"] == "250"


def test_kan59_ops_host_capacity_endpoint(api_client):
    """Vérifie l'endpoint cockpit de supervision /api/olympe/ops/host/capacity."""
    admin_headers = {"Authorization": f"Bearer {MOCK_SUPERADMIN_TOKEN}"}
    resp = api_client.get("/api/olympe/ops/host/capacity", headers=admin_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "host_max_memory_mb" in data
    assert "allocated_memory_mb" in data
    assert "available_memory_mb" in data
    assert "containers_count" in data


def test_kan59_point1_empty_env_vars_and_four_resolution_cases(monkeypatch, tmp_path):
    """Point 1 (Voie A Jarvis) : Vérifie que des variables d'environnement vides ne provoquent aucune ValueError,
    et valide les 4 cas de résolution (absente, vide, renseignée, gabarit posé).
    """
    # CAS 2 : Variables vides/blanches (doit être traité comme absent sans planter)
    monkeypatch.setenv("ORSO_HOST_MAX_MEMORY_MB", "")
    monkeypatch.setenv("ORSO_HOST_MAX_CPUS", "   ")
    monkeypatch.setenv("ORSO_HOST_FLAVOR", "")
    monkeypatch.setenv("ORSO_SYSTEM_RESERVED_MEM_MB", "")
    monkeypatch.setenv("ORSO_CPU_OVERCOMMIT_RATIO", "")
    monkeypatch.setenv("ORSO_HOST_MAX_CONTAINERS", "")

    # Cette instanciation échouait avec ValueError avant correction
    mgr_empty = DockerLifecycleManager(
        data_root=str(tmp_path / "tenants_empty"),
        spaces_root=str(tmp_path / "spaces_empty"),
    )
    assert mgr_empty.host_max_memory_mb > 0
    assert mgr_empty.host_max_cpus > 0
    assert mgr_empty.host_max_containers > 0

    # CAS 1 : Variables totalement absentes (priorité sonde physique)
    monkeypatch.delenv("ORSO_HOST_MAX_MEMORY_MB", raising=False)
    monkeypatch.delenv("ORSO_HOST_MAX_CPUS", raising=False)
    monkeypatch.delenv("ORSO_HOST_FLAVOR", raising=False)
    monkeypatch.delenv("ORSO_SYSTEM_RESERVED_MEM_MB", raising=False)
    monkeypatch.delenv("ORSO_CPU_OVERCOMMIT_RATIO", raising=False)
    monkeypatch.delenv("ORSO_HOST_MAX_CONTAINERS", raising=False)

    res_case1 = DockerLifecycleManager._resolve_host_capacity()
    assert res_case1["max_memory_mb"] > 0
    assert "probe" in res_case1["memory_source"] or "fallback" in res_case1["memory_source"]

    # CAS 3 : Variables explicitement renseignées
    monkeypatch.setenv("ORSO_HOST_MAX_MEMORY_MB", "6144")
    monkeypatch.setenv("ORSO_HOST_MAX_CPUS", "4.5")
    monkeypatch.setenv("ORSO_HOST_MAX_CONTAINERS", "12")
    res_case3 = DockerLifecycleManager._resolve_host_capacity()
    assert res_case3["max_memory_mb"] == 6144
    assert res_case3["max_cpus"] == 4.5
    assert res_case3["max_containers"] == 12
    assert "env_ORSO_HOST_MAX_MEMORY_MB" in res_case3["memory_source"]

    # CAS 4 : Gabarit OVH posé explicitement
    monkeypatch.delenv("ORSO_HOST_MAX_MEMORY_MB", raising=False)
    monkeypatch.delenv("ORSO_HOST_MAX_CPUS", raising=False)
    monkeypatch.setenv("ORSO_HOST_FLAVOR", "b2-15")
    res_case4 = DockerLifecycleManager._resolve_host_capacity()
    # b2-15 = 15360 Mo RAM - 512 Mo réserve = 14848 Mo
    assert res_case4["max_memory_mb"] == 14848
    assert "ovh_catalog_flavor:b2-15" in res_case4["memory_source"]


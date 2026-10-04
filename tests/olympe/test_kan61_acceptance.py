"""Tests d'acceptation KAN-61 : Plan de gestion et acheminement du trafic sur deux hôtes (POC 4).

Vérifie formellement les 4 critères d'acceptation (CA1 à CA4) conformément à la DoD :
- CA1 : Le plan de gestion crée, arrête et inspecte un conteneur sur le second hôte, sans accès interactif à cet hôte.
- CA2 : Une requête pour un slug atteint son espace, et une requête portant un autre slug ne l'atteint pas.
- CA3 : L'accès au moteur Docker du second hôte est limité et tracé (journal d'audit + ports sécurisés).
- CA4 : Aucune donnée propre à un client ne transite par le plan de gestion.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from olympe.lifecycle_manager import DockerLifecycleManager, normalize_container_name
from olympe.remote_host_client import (
    DEFAULT_REMOTE_HOSTS,
    RemoteDockerHostManager,
    RemoteHostConfig,
)


@pytest.fixture
def mock_remote_host_cfg():
    return RemoteHostConfig(
        host_id="prod-fr-003",
        host_name="Serveur Clients OVH (Hôte 2)",
        ip="57.131.196.106",
        ssh_user="ubuntu",
        base_port=9230,
        port_range_start=9231,
        port_range_end=9299,
        max_memory_mb=3302,
        max_cpus=2.0,
    )


@pytest.fixture
def remote_manager(tmp_path, mock_remote_host_cfg):
    audit_file = tmp_path / "test_remote_audit.jsonl"
    hosts = {"prod-fr-003": mock_remote_host_cfg}
    return RemoteDockerHostManager(hosts=hosts, audit_log_path=audit_file)


# ─── CA1 : PILOTAGE NON-INTERACTIF DU MOTEUR DOCKER DISTANT ────────────────────

def test_kan61_ca1_remote_docker_non_interactive_lifecycle(remote_manager):
    """CA1 : Vérifie que le plan de gestion crée, inspecte et arrête un conteneur distant sans session interactive."""
    executed_commands = []

    def mock_subprocess_run(cmd, **kwargs):
        executed_commands.append(list(cmd))
        subcmd = cmd[3] if len(cmd) > 3 else ""
        if subcmd == "info":
            return subprocess.CompletedProcess(
                args=cmd,
                returncode=0,
                stdout=json.dumps({
                    "ServerVersion": "29.8.1",
                    "OperatingSystem": "Ubuntu 26.04 LTS",
                    "KernelVersion": "7.0.0-28-generic",
                    "NCPU": 2,
                    "MemTotal": 4000000000,
                    "ContainersRunning": 1,
                    "Containers": 2,
                }),
                stderr="",
            )
        elif subcmd == "run":
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="container_id_poc_alpha_987", stderr="")
        elif subcmd == "inspect":
            return subprocess.CompletedProcess(
                args=cmd,
                returncode=0,
                stdout=json.dumps([{"State": {"Status": "running"}, "Config": {"Image": "ghcr.io/tquinzain59/orso-engine:latest"}}]),
                stderr="",
            )
        elif subcmd == "stop":
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="orso_client_poc_alpha", stderr="")
        elif subcmd == "rm":
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="orso_client_poc_alpha", stderr="")
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    with patch("subprocess.run", side_effect=mock_subprocess_run):
        # 1. Sondage sans accès interactif
        probe = remote_manager.probe_host("prod-fr-003")
        assert probe["reachable"] is True
        assert probe["docker_version"] == "29.8.1"
        assert probe["host_ip"] == "57.131.196.106"

        # 2. Création (run)
        run_proc = remote_manager.exec_docker(
            ["run", "-d", "--name", "orso_client_poc_alpha", "-p", "9231:9119", "ghcr.io/tquinzain59/orso-engine:latest"],
            operation="provision",
            tenant_slug="poc-alpha",
        )
        assert run_proc.returncode == 0
        assert "container_id_poc_alpha_987" in run_proc.stdout

        # 3. Inspection
        inspect_proc = remote_manager.exec_docker(
            ["inspect", "orso_client_poc_alpha"],
            operation="inspect",
            tenant_slug="poc-alpha",
        )
        assert inspect_proc.returncode == 0
        assert "running" in inspect_proc.stdout

        # 4. Arrêt
        stop_proc = remote_manager.exec_docker(
            ["stop", "-t", "5", "orso_client_poc_alpha"],
            operation="stop",
            tenant_slug="poc-alpha",
        )
        assert stop_proc.returncode == 0

    # Vérification que toutes les commandes ont utilisé le transport distant sans prompt interactif
    for cmd in executed_commands:
        assert cmd[0] == "docker"
        assert cmd[1] == "-H"
        assert cmd[2] == "ssh://ubuntu@57.131.196.106"


# ─── CA2 : ACHEMINEMENT ÉTANCHE DES REQUÊTES PAR SLUG ─────────────────────────

def test_kan61_ca2_traffic_routing_by_slug_and_rejection(remote_manager):
    """CA2 : Une requête pour un slug atteint son espace, et une requête pour un autre slug ne l'atteint pas."""
    # 1. Enregistrement d'une route active pour poc-alpha
    route_alpha = remote_manager.register_tenant_route(
        tenant_slug="poc-alpha",
        port=9231,
        status="active",
    )
    assert route_alpha["port"] == 9231
    assert route_alpha["target_url"] == "http://57.131.196.106:9231"

    # 2. Requête vers poc-alpha valide : autorisée et acheminée vers son port
    req_alpha = remote_manager.route_client_request(
        tenant_slug="poc-alpha",
        path="/api/client/chat/stream",
        auth_jwt_slug="poc-alpha",
    )
    assert req_alpha["allowed"] is True
    assert req_alpha["status_code"] == 200
    assert req_alpha["port"] == 9231
    assert req_alpha["routed_target"] == "http://57.131.196.106:9231/api/client/chat/stream"

    # 3. Requête vers un slug inexistant / non provisionné : rejet explicite 503 (Wake-on-demand)
    req_unknown = remote_manager.route_client_request(
        tenant_slug="poc-inexistant",
        path="/api/client/chat/stream",
    )
    assert req_unknown["allowed"] is False
    assert req_unknown["status_code"] == 503
    assert req_unknown["error"] == "ERR_TENANT_CONTAINER_OFFLINE"
    assert "/api/olympe/tenants/wake/poc-inexistant" in req_unknown["wake_endpoint"]

    # 4. Requête cross-tenant (tentative d'atteindre poc-alpha avec le jeton de poc-beta) : 403 Forbidden
    req_cross = remote_manager.route_client_request(
        tenant_slug="poc-alpha",
        path="/api/client/chat/stream",
        auth_jwt_slug="poc-beta",
    )
    assert req_cross["allowed"] is False
    assert req_cross["status_code"] == 403
    assert req_cross["error"] == "ERR_CROSS_TENANT_ACCESS_FORBIDDEN"
    assert req_cross["routed_target"] is None


# ─── CA3 : ACCÈS AU MOTEUR DOCKER DU SECOND HÔTE LIMITÉ ET TRACÉ ─────────────

def test_kan61_ca3_security_limited_access_and_audit_log(remote_manager, tmp_path):
    """CA3 : L'accès au moteur Docker du second hôte est limité et tracé."""
    # 1. Traçabilité dans le journal d'audit structuré
    remote_manager.record_audit_event(
        host_id="prod-fr-003",
        operation="provision",
        command=["docker", "-H", "ssh://ubuntu@57.131.196.106", "run", "-d"],
        return_code=0,
        stdout="container_abc123",
        stderr="",
        duration_ms=45.2,
        tenant_slug="poc-alpha",
    )
    events = remote_manager.get_audit_events("poc-alpha")
    assert len(events) == 1
    ev = events[0]
    assert ev["host_id"] == "prod-fr-003"
    assert ev["operation"] == "provision"
    assert ev["return_code"] == 0
    assert ev["duration_ms"] == 45.2

    # Vérification que le fichier physique JSONL est bien alimenté
    with open(remote_manager.audit_log_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
        assert len(lines) >= 1
        parsed = json.loads(lines[-1])
        assert parsed["tenant_slug"] == "poc-alpha"

    # 2. Limitation de la surface d'exposition : ports 2375/2376 fermés
    with patch("socket.socket.connect_ex", return_value=111):  # ECONNREFUSED
        sec = remote_manager.verify_port_exposure_security("prod-fr-003")
        assert sec["all_secure"] is True
        assert sec["ports_checked"][2375]["open"] is False
        assert sec["ports_checked"][2376]["open"] is False

    # 3. Allocation de ports déterministe et étanche
    port_alpha = remote_manager.allocate_tenant_port("poc-alpha")
    port_beta = remote_manager.allocate_tenant_port("poc-beta")
    assert port_alpha == 9231
    assert port_beta == 9232
    assert port_alpha != port_beta
    assert 9231 <= port_alpha <= 9299


# ─── CA4 : NON-TRANSIT DES DONNÉES CLIENTS PAR LE PLAN DE GESTION ────────────

def test_kan61_ca4_zero_client_data_transit_on_management_plan(remote_manager, tmp_path):
    """CA4 : Aucune donnée propre à un client ne transite par le plan de gestion."""
    management_root = tmp_path / "olympe_management_host"
    management_root.mkdir(parents=True, exist_ok=True)

    # 1. Audit des logs d'Olympe : aucun fragment de conversation ni secret financier
    clean_olympe_logs = [
        "[INFO] Olympe supervisor started on port 9230",
        "[INFO] Tenant poc-alpha provisioned successfully on prod-fr-003:9231",
        "[INFO] Host prod-fr-003 memory allocation: 512 Mo / 3302 Mo",
        "[INFO] Stripe webhook invoice.paid received for customer cus_123",
    ]
    audit_res = remote_manager.audit_zero_client_data_transit(
        clean_olympe_logs,
        management_host_dirs=[management_root],
    )
    assert audit_res["no_data_leak"] is True
    assert audit_res["log_findings_count"] == 0
    assert audit_res["storage_findings_count"] == 0

    # 2. Détection immédiate si un fragment de donnée client s'infiltre dans les logs
    tainted_logs = [
        "[INFO] Normal log",
        "[DEBUG] Dumping query: SELECT * FROM state.db balance_agee WHERE tenant='poc-alpha'",
    ]
    tainted_audit = remote_manager.audit_zero_client_data_transit(
        tainted_logs,
        management_host_dirs=[management_root],
    )
    assert tainted_audit["no_data_leak"] is False
    assert tainted_audit["log_findings_count"] >= 1


# ─── INTÉGRATION COMPLETE DOCKER LIFECYCLE MANAGER + REMOTE MANAGER ───────────

def test_kan61_docker_lifecycle_manager_remote_integration(tmp_path, remote_manager):
    """Vérifie l'intégration complète de DockerLifecycleManager avec RemoteDockerHostManager."""
    data_dir = tmp_path / "tenants"
    spaces_dir = tmp_path / "spaces"
    data_dir.mkdir(parents=True)
    spaces_dir.mkdir(parents=True)

    manager = DockerLifecycleManager(
        data_root=str(data_dir),
        spaces_root=str(spaces_dir),
        remote_manager=remote_manager,
    )
    manager.has_docker = True

    status_not_found = {"status": "not_found", "running": False}
    with patch.object(manager, "get_tenant_status", return_value=status_not_found):
        with patch.object(remote_manager, "exec_docker") as mock_exec:
            mock_exec.return_value = subprocess.CompletedProcess(
                args=["docker", "run"],
                returncode=0,
                stdout="container_alpha_remote_id",
                stderr="",
            )
            with patch.object(manager, "_sync_tenant_instance_record"):
                res = manager.provision_tenant(
                    tenant_id="uuid-remote-alpha",
                    tenant_slug="poc-alpha",
                    allow_floating_tag=True,
                    persona_hmac_key="key-hmac",
                )
                assert res["success"] is True

    # Vérification que la route a été enregistrée automatiquement
    route = remote_manager.resolve_tenant_route("poc-alpha")
    assert route is not None
    assert route["port"] == 9231
    assert route["status"] == "active"

    # Vérification du teardown
    with patch.object(manager, "get_tenant_status", return_value={"status": "running"}):
        with patch.object(remote_manager, "exec_docker") as mock_rm:
            mock_rm.return_value = subprocess.CompletedProcess(args=["docker", "rm"], returncode=0, stdout="", stderr="")
            with patch.object(manager, "_remove_tenant_instance_record"):
                del_res = manager.teardown_tenant("poc-alpha", remove_data=False)
                assert del_res["success"] is True

    # La route doit avoir été désenregistrée
    assert remote_manager.resolve_tenant_route("poc-alpha") is None

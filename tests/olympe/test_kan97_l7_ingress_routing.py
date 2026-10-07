"""Tests d'acceptation automatisés pour le ticket KAN-97 (Acheminement L7 multi-hôtes et ports clients).

Vérifie formellement les 5 critères d'acceptation :
- CA1 : Une requête HTTP cliente vers /api/olympe/gateway/t/{slug}/... est relayée vers l'hôte et le port cible.
- CA2 : Un slug inconnu retourne 404 (ERR_TENANT_ROUTE_NOT_FOUND), un slug endormi retourne 503 (avec endpoint wake).
- CA3 : Un jeton JWT appartenant à un autre tenant est immédiatement rejeté avec HTTP 403 (ERR_CROSS_TENANT_ACCESS_FORBIDDEN).
- CA4 : La table de routage s'alimente lors de la mise en service/réveil et se purge lors de la suppression.
- CA5 : Le régime de publication des ports est documenté et appliqué (plage 9231-9299, ports dédiés, isolation DOCKER-USER).
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from fastapi.testclient import TestClient
import jwt

from olympe.auth import MOCK_SUPERADMIN_TOKEN
from olympe.server import app, ops_manager, remote_manager


@pytest.fixture(autouse=True)
def setup_routing_env():
    """Initialise un environnement de test propre avec routes réinitialisées."""
    ops_manager.demo_mode = True
    remote_manager._routing_table.clear()
    remote_manager._allocated_ports.clear()
    remote_manager._next_port = 9231


@pytest.fixture
def client():
    return TestClient(app)


def test_kan97_ca1_request_forwarded_to_target_host_and_port(client):
    """CA1 : Vérifie que la passerelle L7 relaie la requête vers l'hôte et le port du conteneur client actif."""
    # Enregistrer une route active pour 'tenant-acme' sur l'hôte par défaut prod-fr-003
    route_entry = remote_manager.register_tenant_route("tenant-acme", host_id="prod-fr-003", port=9235, status="active")
    target_ip = route_entry["host_ip"]

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = b'{"status": "ok", "agent": "jerome"}'
    mock_resp.headers = {"content-type": "application/json"}

    mock_client_instance = AsyncMock()
    mock_client_instance.request.return_value = mock_resp
    mock_client_instance.__aenter__.return_value = mock_client_instance
    mock_client_instance.__aexit__.return_value = None

    with patch("httpx.AsyncClient", return_value=mock_client_instance):
        res = client.post(
            "/api/olympe/gateway/t/tenant-acme/api/chat/stream?session_id=123",
            json={"message": "Bonjour"},
            headers={"Content-Type": "application/json"},
        )

        assert res.status_code == 200
        assert res.json() == {"status": "ok", "agent": "jerome"}
        assert res.headers["x-orso-routed-host"] == "prod-fr-003"
        assert res.headers["x-orso-routed-port"] == "9235"

        # Vérifier l'appel httpx
        mock_client_instance.request.assert_called_once()
        call_kwargs = mock_client_instance.request.call_args.kwargs
        assert call_kwargs["method"] == "POST"
        assert call_kwargs["url"] == f"http://{target_ip}:9235/api/chat/stream?session_id=123"
        assert call_kwargs["headers"]["x-tenant-slug"] == "tenant-acme"
        assert call_kwargs["headers"]["host"] == "localhost:9235"


def test_kan97_ca2_unprovisioned_and_sleeping_slugs(client):
    """CA2 : Vérifie qu'un slug non provisionné renvoie 404 et qu'un slug endormi renvoie 503."""
    # 1. Slug non provisionné -> 404
    res_404 = client.get("/api/olympe/gateway/t/unknown-tenant/api/status")
    assert res_404.status_code == 404
    data_404 = res_404.json()
    assert data_404["status"] == "REJECTED_UNPROVISIONED"
    assert data_404["error_code"] == "ERR_TENANT_ROUTE_NOT_FOUND"

    # 2. Slug endormi -> 503 avec endpoint wake
    remote_manager.register_tenant_route("sleeping-corp", host_id="prod-fr-003", port=9240, status="sleeping")
    res_503 = client.get("/api/olympe/gateway/t/sleeping-corp/api/status")
    assert res_503.status_code == 503
    data_503 = res_503.json()
    assert data_503["status"] == "REJECTED_OFFLINE"
    assert data_503["error_code"] == "ERR_TENANT_CONTAINER_OFFLINE"
    assert data_503["wake_endpoint"] == "/api/olympe/tenants/wake/sleeping-corp"


def test_kan97_ca3_cross_tenant_token_rejected_with_403(client):
    """CA3 : Vérifie qu'un jeton JWT pour un autre tenant est rejeté avec 403 ERR_CROSS_TENANT_ACCESS_FORBIDDEN."""
    remote_manager.register_tenant_route("victim-tenant", host_id="prod-fr-003", port=9232, status="active")

    # Création d'un jeton légitime mais portant l'identité de 'attacker-tenant'
    attacker_token = jwt.encode({"tenant_slug": "attacker-tenant", "sub": "user_456"}, "secret", algorithm="HS256")

    res = client.get(
        "/api/olympe/gateway/t/victim-tenant/api/confidential",
        headers={"Authorization": f"Bearer {attacker_token}"},
    )
    assert res.status_code == 403
    data = res.json()
    assert data["error"] == "ERR_CROSS_TENANT_ACCESS_FORBIDDEN"
    assert "attacker-tenant" in data["message"]
    assert "victim-tenant" in data["message"]


def test_kan97_ca4_routing_table_lifecycle(client):
    """CA4 : Vérifie que la table de routage s'alimente lors de la mise en service et se purge à la suppression."""
    admin_headers = {"Authorization": f"Bearer {MOCK_SUPERADMIN_TOKEN}"}

    # 1. Consulter les routes initiales
    routes_init = client.get("/api/olympe/ingress/routes", headers=admin_headers)
    assert routes_init.status_code == 200
    assert "client-test-lifecycle" not in routes_init.json()

    # 2. Simuler l'enregistrement via provision
    remote_manager.register_tenant_route("client-test-lifecycle", host_id="prod-fr-003", status="active")
    routes_after = client.get("/api/olympe/ingress/routes", headers=admin_headers)
    assert routes_after.status_code == 200
    route_data = routes_after.json().get("client-test-lifecycle")
    assert route_data is not None
    assert route_data["status"] == "active"
    assert route_data["port"] >= 9231

    # 3. Purger à la suppression
    remote_manager.unregister_tenant_route("client-test-lifecycle")
    routes_final = client.get("/api/olympe/ingress/routes", headers=admin_headers)
    assert routes_final.status_code == 200
    assert "client-test-lifecycle" not in routes_final.json()


def test_kan97_ca5_port_publication_regime_and_doc():
    """CA5 : Vérifie l'existence de la documentation du régime des ports et la validité des plages de ports."""
    doc_path = Path("docs/3_Technique/regime_publication_ports_clients_kan97.md")
    assert doc_path.is_file(), "La documentation docs/3_Technique/regime_publication_ports_clients_kan97.md doit exister."

    content = doc_path.read_text(encoding="utf-8")
    assert "9231" in content
    assert "9299" in content
    assert "DOCKER-USER" in content
    assert "DROP" in content
    assert "92.222.68.80" in content

    # Vérification algorithmique de l'allocation des ports
    ports = [remote_manager.allocate_tenant_port(f"tenant_{i}") for i in range(10)]
    assert len(ports) == len(set(ports)), "Les ports alloués doivent être strictement uniques et non-chevauchants"
    for p in ports:
        assert 9231 <= p <= 9299, f"Le port {p} doit être dans la plage autorisée [9231-9299]"

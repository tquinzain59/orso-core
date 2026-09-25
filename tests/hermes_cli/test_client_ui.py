"""Tests for the Orso UI Client endpoints in hermes_cli.web_routers.client_ui."""

import asyncio
import json
import pytest
from hermes_cli.web_routers.client_ui import (
    _extract_action_card,
    _load_agent_soul,
    _chat_stream_generator,
    execute_client_action,
    ActionExecuteRequest,
)


def test_extract_action_card_heuristic():
    text = (
        "Bonjour ! J'ai analysé votre situation. La société Dupont Peinture a un retard "
        "de 45 jours sur sa facture. Je vous propose d'envoyer la relance suivante."
    )
    clean_text, card = _extract_action_card(text, "jerome")
    assert card is not None
    assert card["agentId"] == "jerome"
    assert "Dupont" in card["recipientName"]
    assert card["amount"] == 3900.00
    assert card["status"] == "pending"


def test_extract_action_card_explicit_block():
    text = (
        "Voici mon analyse détaillée.\n\n"
        "```action_card\n"
        "{\n"
        '  "id": "action-custom-1",\n'
        '  "agentId": "jerome",\n'
        '  "title": "Mise en demeure",\n'
        '  "recipientName": "Client Alpha",\n'
        '  "amount": 1500.0,\n'
        '  "status": "pending"\n'
        "}\n"
        "```\n"
        "Merci de me confirmer si vous souhaitez l'envoyer."
    )
    clean_text, card = _extract_action_card(text, "jerome")
    assert card is not None
    assert card["id"] == "action-custom-1"
    assert card["recipientName"] == "Client Alpha"
    assert card["amount"] == 1500.0
    assert "```action_card" not in clean_text


def test_load_agent_soul_jerome():
    soul = _load_agent_soul("jerome")
    assert "Jerome" in soul or "Jérôme" in soul
    assert "recouvrement" in soul.lower()


def test_load_agent_soul_other_agents():
    for agent_id in ["lucas", "clara", "victor"]:
        soul = _load_agent_soul(agent_id)
        assert soul is not None
        assert len(soul) > 20


def test_load_agent_soul_permission_error(monkeypatch):
    from pathlib import Path
    orig_is_file = Path.is_file
    def mock_is_file(self):
        if "SOUL.md" in str(self):
            raise PermissionError("Permission denied: simulated")
        return orig_is_file(self)
    monkeypatch.setattr(Path, "is_file", mock_is_file)
    soul = _load_agent_soul("jerome")
    assert "Jerome" in soul or "Jérôme" in soul
    assert "recouvrement" in soul.lower()


@pytest.mark.asyncio
async def test_chat_stream_generator(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    from run_agent import AIAgent
    monkeypatch.setattr(AIAgent, "run_conversation", lambda *args, **kwargs: None)
    chunks = []
    async for event_str in _chat_stream_generator("jerome", "Peux-tu faire le point sur la balance âgée ?", "test-session"):
        chunks.append(event_str)

    full_stream = "".join(chunks)
    assert "event: start" in full_stream
    assert "event: delta" in full_stream
    assert "event: done" in full_stream
    # For Jerome balance query, an action_card should be emitted
    assert "event: action_card" in full_stream


@pytest.mark.asyncio
async def test_execute_client_action():
    req = ActionExecuteRequest(
        action_id="send",
        card_id="action-test-1",
        agent_id="jerome",
        draft="Bonjour, merci de régler...",
        recipient="compta@test.fr",
    )
    res = await execute_client_action(req)
    assert res["success"] is True
    assert res["status"] == "executed"
    assert "compta@test.fr" in res["message"]


def test_client_status_endpoint():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from hermes_cli.web_routers.client_ui import router

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    res = client.get("/api/client/status")
    assert res.status_code == 200
    data = res.json()
    assert data["module"] == "Orso UI Client"
    assert "jerome" in data["agents"]
    assert data["auth_required"] is True


def _make_test_jwt(tenant_id="tenant-123", tenant_slug=None, agents=None, secret="test-jwt-secret"):
    import base64, hashlib, hmac, json, time
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": "user-456",
        "email": "test@financia.fr",
        "tenant": {
            "tenant_id": tenant_id,
            "tenant_slug": tenant_slug or tenant_id,
            "role": "daf",
            "agents": agents or ["jerome", "lucas", "clara", "victor"],
        },
        "exp": int(time.time()) + 3600,
    }
    def b64url(b):
        return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")
    h_b64 = b64url(json.dumps(header).encode())
    p_b64 = b64url(json.dumps(payload).encode())
    sig = hmac.new(secret.encode(), f"{h_b64}.{p_b64}".encode(), hashlib.sha256).digest()
    return f"{h_b64}.{p_b64}.{b64url(sig)}"


def test_client_agents_endpoint_auth(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from hermes_cli.web_routers.client_ui import router

    monkeypatch.setenv("SUPABASE_JWT_SECRET", "test-jwt-secret")
    monkeypatch.setenv("ORSO_CLIENT_ID", "tenant-123")
    monkeypatch.setenv("ORSO_CLIENT_SLUG", "tenant-123")

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    # 1. Sans jeton -> 401
    res = client.get("/api/client/agents")
    assert res.status_code == 401
    assert "Authentification requise" in res.json()["detail"]

    # 2. Avec jeton valide du bon tenant -> 200
    token = _make_test_jwt(tenant_id="tenant-123")
    res_ok = client.get("/api/client/agents", headers={"Authorization": f"Bearer {token}"})
    assert res_ok.status_code == 200
    data = res_ok.json()
    assert "agents" in data
    agent_ids = [a["id"] for a in data["agents"]]
    assert "jerome" in agent_ids

    # 3. Avec jeton d'un autre tenant (cross-tenant attack) -> 403 Forbidden
    evil_token = _make_test_jwt(tenant_id="other-company-789")
    res_forbidden = client.get("/api/client/agents", headers={"Authorization": f"Bearer {evil_token}"})
    assert res_forbidden.status_code == 403
    assert "Accès interdit" in res_forbidden.json()["detail"]


def test_client_actions_execute_endpoint_auth(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from hermes_cli.web_routers.client_ui import router

    monkeypatch.setenv("SUPABASE_JWT_SECRET", "test-jwt-secret")
    monkeypatch.setenv("ORSO_CLIENT_ID", "tenant-123")
    monkeypatch.setenv("ORSO_CLIENT_SLUG", "tenant-123")

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    payload = {
        "action_id": "send",
        "card_id": "card-456",
        "agent_id": "jerome",
        "draft": "Relance...",
        "recipient": "client@test.fr",
    }

    # Sans jeton -> 401
    res = client.post("/api/client/actions/execute", json=payload)
    assert res.status_code == 401

    # Avec jeton valide -> 200
    token = _make_test_jwt(tenant_id="tenant-123")
    res_ok = client.post(
        "/api/client/actions/execute",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res_ok.status_code == 200
    data = res_ok.json()
    assert data["success"] is True
    assert data["status"] == "executed"
    assert "client@test.fr" in data["message"]


def test_client_chat_endpoint_stream_auth(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "test-jwt-secret")
    monkeypatch.setenv("ORSO_CLIENT_ID", "tenant-123")
    monkeypatch.setenv("ORSO_CLIENT_SLUG", "tenant-123")
    from run_agent import AIAgent
    monkeypatch.setattr(AIAgent, "run_conversation", lambda *args, **kwargs: None)
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from hermes_cli.web_routers.client_ui import router

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    payload = {
        "agent_id": "jerome",
        "message": "Bonjour Jérôme, fais le point sur la trésorerie",
    }

    # Sans jeton -> 401
    res = client.post("/api/client/chat", json=payload)
    assert res.status_code == 401

    # Avec jeton valide -> 200
    token = _make_test_jwt(tenant_id="tenant-123")
    res_ok = client.post(
        "/api/client/chat",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res_ok.status_code == 200
    assert "text/event-stream" in res_ok.headers["content-type"]
    body = res_ok.text
    assert "event: start" in body
    assert "event: delta" in body
    assert "event: done" in body


def test_client_routes_via_web_server_auth(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "test-jwt-secret")
    monkeypatch.setenv("ORSO_CLIENT_ID", "tenant-123")
    monkeypatch.setenv("ORSO_CLIENT_SLUG", "tenant-123")
    from fastapi.testclient import TestClient
    from hermes_cli.web_server import app

    client = TestClient(app)
    # /api/client/status should return 200 without token auth (public ping/health)
    res = client.get("/api/client/status")
    assert res.status_code == 200
    assert res.json()["module"] == "Orso UI Client"
    assert res.json()["auth_required"] is True

    # /api/client/agents should return 401 without token auth
    res_agents_unauth = client.get("/api/client/agents")
    assert res_agents_unauth.status_code == 401

    # /api/client/agents should return 200 with valid JWT
    token = _make_test_jwt(tenant_id="tenant-123")
    res_agents_auth = client.get("/api/client/agents", headers={"Authorization": f"Bearer {token}"})
    assert res_agents_auth.status_code == 200
    assert "agents" in res_agents_auth.json()


def test_client_auth_me_and_logout(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from hermes_cli.web_routers.client_ui import router

    monkeypatch.setenv("SUPABASE_JWT_SECRET", "test-jwt-secret")
    monkeypatch.setenv("ORSO_CLIENT_ID", "tenant-123")
    monkeypatch.setenv("ORSO_CLIENT_SLUG", "tenant-123")

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    # 1. /api/client/auth/me sans jeton -> 401
    res_me_unauth = client.get("/api/client/auth/me")
    assert res_me_unauth.status_code == 401

    # 2. /api/client/auth/me avec jeton valide -> 200
    token = _make_test_jwt(tenant_id="tenant-123")
    res_me = client.get("/api/client/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert res_me.status_code == 200
    me_data = res_me.json()
    assert me_data["authenticated"] is True
    assert me_data["user"]["id"] == "user-456"
    assert me_data["tenant"]["tenant_id"] == "tenant-123"

    # 3. /api/client/auth/logout -> 200
    res_logout = client.post("/api/client/auth/logout")
    assert res_logout.status_code == 200
    assert res_logout.json()["success"] is True


def test_client_auth_login_cross_tenant_rejection(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from hermes_cli.web_routers.client_ui import router
    import urllib.request

    monkeypatch.setenv("SUPABASE_URL", "https://fake.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "fake-key")
    monkeypatch.setenv("ORSO_CLIENT_ID", "financia-id")
    monkeypatch.setenv("ORSO_CLIENT_SLUG", "financia-solutions")

    # Mock urllib.request.urlopen pour simuler le login d'un utilisateur d'un AUTRE tenant
    class MockResponse:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def read(self):
            import json
            return json.dumps({
                "access_token": "fake-token",
                "user": {
                    "id": "claire-id",
                    "email": "claire@commercialink.com",
                    "app_metadata": {
                        "tenant_id": "other-tenant-id",
                        "tenant_slug": "commercialink",
                        "role": "commercial",
                        "target_environment": {
                            "docker_container_name": "orso_backend_commercialink"
                        },
                    },
                    "user_metadata": {
                        "full_name": "Claire Dubois"
                    }
                }
            }).encode("utf-8")

    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=5.0: MockResponse())

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    # Tentative de connexion de Claire Dubois sur l'instance Financia -> 403 Forbidden!
    res = client.post("/api/client/auth/login", json={
        "email": "claire@commercialink.com",
        "password": "Password123!"
    })
    assert res.status_code == 403
    assert "Accès refusé" in res.json()["detail"]
    # Vérification stricte anti-leakage : aucun nom d'entreprise ne doit fuiter dans le message d'erreur
    assert "commercialink" not in res.json()["detail"]
    assert "financia-solutions" not in res.json()["detail"]


def test_client_agents_filtering_only_enabled_agents(monkeypatch):
    """Vérifie que seuls les agents activés pour le client sont renvoyés."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from hermes_cli.web_routers.client_ui import router

    monkeypatch.setenv("SUPABASE_JWT_SECRET", "test-jwt-secret")
    monkeypatch.delenv("ORSO_CLIENT_ID", raising=False)
    monkeypatch.delenv("ORSO_CLIENT_SLUG", raising=False)
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    # 1. Financia Solutions : seul Jérôme est activé
    token_financia = _make_test_jwt(tenant_id="f3e25379-6531-479e-b276-3b3185e7421b", tenant_slug="financia-solutions", agents=["jerome"])
    res = client.get("/api/client/agents", headers={"Authorization": f"Bearer {token_financia}"})
    assert res.status_code == 200
    agents = res.json()["agents"]
    assert len(agents) == 1
    assert agents[0]["id"] == "jerome"
    assert agents[0]["name"] == "Jérôme"
    assert "themeColor" in agents[0]
    assert "quickActions" in agents[0]

    # 2. CommerciaLink : seul Lucas est activé
    token_comm = _make_test_jwt(tenant_id="9a38ef87-19d2-45e3-9821-2efbb91081a9", tenant_slug="commercialink", agents=["lucas"])
    res_comm = client.get("/api/client/agents", headers={"Authorization": f"Bearer {token_comm}"})
    assert res_comm.status_code == 200
    agents_comm = res_comm.json()["agents"]
    assert len(agents_comm) == 1
    assert agents_comm[0]["id"] == "lucas"

    # 3. EuroTech : 4 agents activés
    token_euro = _make_test_jwt(tenant_id="e88d1234-9abc-4def-0123-456789abcdef", tenant_slug="eurotech-conseil", agents=["jerome", "lucas", "clara", "victor"])
    res_euro = client.get("/api/client/agents", headers={"Authorization": f"Bearer {token_euro}"})
    assert res_euro.status_code == 200
    agents_euro = res_euro.json()["agents"]
    assert len(agents_euro) == 4
    euro_ids = [a["id"] for a in agents_euro]
    assert set(euro_ids) == {"jerome", "lucas", "clara", "victor"}


def test_client_integrations_endpoint_and_sync(monkeypatch):
    """Vérifie la lecture des interfaces connectées et la resynchronisation en base."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from hermes_cli.web_routers.client_ui import router

    monkeypatch.setenv("SUPABASE_JWT_SECRET", "test-jwt-secret")
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    token = _make_test_jwt(tenant_id="f3e25379-6531-479e-b276-3b3185e7421b", tenant_slug="financia-solutions")
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Lecture de la liste des intégrations
    res = client.get("/api/client/integrations", headers=headers)
    assert res.status_code == 200
    integrations = res.json()["integrations"]
    assert len(integrations) >= 5
    ids = [i["id"] for i in integrations]
    assert "pennylane" in ids
    assert "pappers" in ids

    # 2. Resynchronisation d'une interface
    res_sync = client.post("/api/client/integrations/pennylane/sync", headers=headers)
    assert res_sync.status_code == 200
    data_sync = res_sync.json()
    assert data_sync["success"] is True
    assert data_sync["integration"]["lastSync"] == "À l'instant"
    assert data_sync["integration"]["status"] == "connected"


def test_client_channels_endpoint_and_user_management(monkeypatch):
    """Vérifie la lecture des canaux et l'ajout/suppression d'utilisateurs autorisés."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from hermes_cli.web_routers.client_ui import router

    monkeypatch.setenv("SUPABASE_JWT_SECRET", "test-jwt-secret")
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    token = _make_test_jwt(tenant_id="f3e25379-6531-479e-b276-3b3185e7421b", tenant_slug="financia-solutions")
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Lecture des canaux
    res = client.get("/api/client/channels", headers=headers)
    assert res.status_code == 200
    channels = res.json()["channels"]
    channel_ids = [c["id"] for c in channels]
    assert "whatsapp" in channel_ids
    assert "telegram" in channel_ids
    assert "email" in channel_ids

    # 2. Ajout d'un utilisateur sur WhatsApp
    res_add = client.post(
        "/api/client/channels/whatsapp/users",
        headers=headers,
        json={"user": "+33699887766"},
    )
    assert res_add.status_code == 200
    assert "+33699887766" in res_add.json()["allowed_users"]

    # 3. Suppression de l'utilisateur
    res_del = client.delete(
        "/api/client/channels/whatsapp/users/+33699887766",
        headers=headers,
    )
    assert res_del.status_code == 200
    assert "+33699887766" not in res_del.json()["allowed_users"]


def test_client_integrations_backoffice_real_detection(monkeypatch):
    """Vérifie la détection dynamique des clés d'environnement et des outils réels du backoffice Hermès."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from hermes_cli.web_routers.client_ui import router

    monkeypatch.setenv("SUPABASE_JWT_SECRET", "test-jwt-secret")
    monkeypatch.setenv("AIRTABLE_API_KEY", "pat.test.airtable.12345")
    monkeypatch.setenv("PENNYLANE_API_KEY", "pennylane_secret_token_abc")
    monkeypatch.delenv("SELLSY_TOKEN", raising=False)

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    token = _make_test_jwt(tenant_id="f3e25379-6531-479e-b276-3b3185e7421b", tenant_slug="financia-solutions")
    headers = {"Authorization": f"Bearer {token}"}

    res = client.get("/api/client/integrations", headers=headers)
    assert res.status_code == 200
    integrations = res.json()["integrations"]
    by_id = {i["id"]: i for i in integrations}

    # 1. Pennylane avec clé API configurée
    assert "pennylane" in by_id
    assert by_id["pennylane"]["status"] == "connected"
    assert by_id["pennylane"]["metricValue"] == "Connecteur actif (Clé .env)"

    # 2. Sellsy sans clé configurée
    assert "sellsy" in by_id
    assert by_id["sellsy"]["status"] == "disconnected"
    assert "Requiert SELLSY_TOKEN" in by_id["sellsy"]["accountDetails"]

    # 3. Airtable détecté via le backoffice Hermès
    assert "airtable" in by_id
    assert by_id["airtable"]["status"] == "connected"
    assert by_id["airtable"]["category"] == "tools"

    # 4. Outils natifs Hermès
    assert "hermes-web-search" in by_id
    assert by_id["hermes-web-search"]["status"] == "connected"
    assert by_id["hermes-web-search"]["category"] == "tools"

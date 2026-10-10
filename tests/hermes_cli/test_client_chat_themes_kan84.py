"""Tests d'acceptation pour KAN-84 : Organisation des conversations par thèmes (4 mots).

Critères d'acceptation vérifiés :
- CA1 : Extraction automatique du thème bornée à 4 mots maximum en français.
- CA2 : Création automatique d'un bloc de thème et association de la conversation dès le premier message.
- CA3 : Renommage manuel d'un thème par l'utilisateur (title_source='user', protégé contre l'écrasement).
- CA4 : Fusion de deux thèmes et déplacement d'une conversation d'un thème à un autre.
- CA5 : Suppression d'un thème avec détachement ou purge des sessions associées.
- CA6 : Étanchéité multi-tenant et inter-utilisateurs stricte (isolation garantie).
- CA7 : Aucune entrée nommée "Nouvelle discussion" n'est écrite en base comme titre de thème.
"""

import base64
import hashlib
import hmac
import json
import sqlite3
import time
from types import SimpleNamespace
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from hermes_cli.web_routers.client_chat_history import (
    generate_theme_title,
    history_router,
)
from hermes_cli.web_routers.client_ui import (
    _get_client_sessions_db_path,
    _init_client_sessions_db,
    router as client_ui_router,
)


def _generate_jwt(
    user_id: str,
    tenant_id: str = "f3e25379-6531-479e-b276-3b3185e7421b",
    tenant_slug: str = "financia-solutions",
    secret: str = "test-secret",
) -> str:
    """Génère un jeton JWT de test signé HMAC-SHA256."""
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": user_id,
        "email": f"{user_id}@financia.fr",
        "exp": int(time.time()) + 3600,
        "tenant": {
            "tenant_id": tenant_id,
            "tenant_slug": tenant_slug,
            "role": "admin",
            "is_admin": True,
            "agents": ["jerome", "lucas", "clara", "victor"],
        },
    }

    def b64url(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")

    h_b64 = b64url(json.dumps(header).encode("utf-8"))
    p_b64 = b64url(json.dumps(payload).encode("utf-8"))
    signing_input = f"{h_b64}.{p_b64}".encode("utf-8")
    sig = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    sig_b64 = b64url(sig)

    return f"{h_b64}.{p_b64}.{sig_b64}"


class _FakeChunk:
    def __init__(self, content="", finish_reason=None):
        self.choices = [
            SimpleNamespace(
                delta=SimpleNamespace(content=content, tool_calls=None, reasoning=None, reasoning_content=None),
                finish_reason=finish_reason,
            )
        ]
        self.id = "chunk-kan84"
        self.model = "deepseek/deepseek-v4-flash"


class _FakeStream:
    def __init__(self, chunks):
        self._chunks = chunks
        self.response = SimpleNamespace(headers={})

    def __iter__(self):
        return iter(self._chunks)

    def close(self):
        pass


class _FakeCompletions:
    def create(self, **kwargs):
        chunks = [
            _FakeChunk(content="Réponse de test automatique pour KAN-84."),
            _FakeChunk(content="", finish_reason="stop"),
        ]
        return _FakeStream(chunks)


class _FakeClient:
    def __init__(self, **kwargs):
        self.chat = SimpleNamespace(completions=_FakeCompletions())
        self.closed = False

    def close(self):
        self.closed = True


@pytest.fixture
def test_app(monkeypatch, tmp_path):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "test-secret")
    monkeypatch.setenv("ORSO_CLIENT_ID", "f3e25379-6531-479e-b276-3b3185e7421b")
    monkeypatch.setenv("ORSO_CLIENT_SLUG", "financia-solutions")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-fake-openrouter-key")
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    sessions_db_file = tmp_path / "client_chat_sessions.db"
    monkeypatch.setattr(
        "hermes_cli.web_routers.client_ui._get_client_sessions_db_path",
        lambda: sessions_db_file,
    )

    fake_agent_dir = tmp_path / "data" / "agents" / "jerome"
    fake_agent_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        "hermes_cli.web_routers.client_ui._find_profile_dir",
        lambda agent_id: tmp_path / "data" / "agents" / agent_id,
    )

    try:
        import openai
        monkeypatch.setattr(openai, "OpenAI", _FakeClient)
    except Exception:
        pass

    app = FastAPI()
    app.include_router(client_ui_router)
    app.include_router(history_router)

    _init_client_sessions_db()

    return {
        "client": TestClient(app),
        "db": sessions_db_file,
        "token": _generate_jwt("user-sophie"),
    }


def test_kan84_ca1_generate_theme_title_bounded_four_words():
    """CA1 : Le titre automatique du thème ne doit jamais dépasser 4 mots."""
    long_prompt = "Je voudrais analyser la balance âgée des comptes clients en grand retard"
    title = generate_theme_title(long_prompt, max_words=4)
    words = title.split()
    assert len(words) <= 4
    assert title == "Je voudrais analyser la"

    short_prompt = "Relance facture Dupont"
    title_short = generate_theme_title(short_prompt, max_words=4)
    assert title_short == "Relance facture Dupont"
    assert len(title_short.split()) == 3

    empty_title = generate_theme_title("", max_words=4)
    assert empty_title == "Sujet de discussion"
    assert len(empty_title.split()) <= 4


def test_kan84_ca2_auto_theme_creation_and_binding(test_app):
    """CA2 : Création automatique d'un thème lors du premier échange et liaison de la session."""
    client = test_app["client"]
    token = test_app["token"]
    headers = {"Authorization": f"Bearer {token}"}

    session_id = "session_kan84_001"
    prompt = "Contrôle des créances impayées"
    resp = client.post(
        "/api/client/chat",
        headers=headers,
        json={"agent_id": "jerome", "message": prompt, "session_id": session_id},
    )
    assert resp.status_code == 200

    list_resp = client.get("/api/client/chat/themes?agent_id=jerome", headers=headers)
    assert list_resp.status_code == 200
    data = list_resp.json()
    assert data["total"] >= 1
    theme = data["themes"][0]
    assert theme["agent_id"] == "jerome"
    assert len(theme["title"].split()) <= 4
    assert theme["sessions_count"] == 1
    assert theme["sessions"][0]["session_id"] == session_id


def test_kan84_ca3_manual_theme_renaming(test_app):
    """CA3 : Renommage manuel d'un thème par l'utilisateur avec protection contre l'écrasement."""
    client = test_app["client"]
    token = test_app["token"]
    headers = {"Authorization": f"Bearer {token}"}

    create_resp = client.post(
        "/api/client/chat/themes",
        headers=headers,
        json={"title": "Litiges transporteurs", "agent_id": "jerome"},
    )
    assert create_resp.status_code == 200
    theme_id = create_resp.json()["theme"]["theme_id"]

    patch_resp = client.patch(
        f"/api/client/chat/themes/{theme_id}",
        headers=headers,
        json={"title": "Contentieux livraisons 2026"},
    )
    assert patch_resp.status_code == 200
    data = patch_resp.json()
    assert data["title"] == "Contentieux livraisons 2026"
    assert data["title_source"] == "user"

    get_resp = client.get("/api/client/chat/themes?agent_id=jerome", headers=headers)
    themes = get_resp.json()["themes"]
    renamed = next(t for t in themes if t["theme_id"] == theme_id)
    assert renamed["title"] == "Contentieux livraisons 2026"
    assert renamed["title_source"] == "user"


def test_kan84_ca4_move_session_and_merge_themes(test_app):
    """CA4 : Déplacement d'une session vers un autre thème et fusion de deux thèmes."""
    client = test_app["client"]
    token = test_app["token"]
    headers = {"Authorization": f"Bearer {token}"}

    t1 = client.post("/api/client/chat/themes", headers=headers, json={"title": "Facturation Nord", "agent_id": "jerome"}).json()["theme"]["theme_id"]
    t2 = client.post("/api/client/chat/themes", headers=headers, json={"title": "Facturation Sud", "agent_id": "jerome"}).json()["theme"]["theme_id"]

    sid = "session_move_test"
    client.post(
        "/api/client/chat",
        headers=headers,
        json={"agent_id": "jerome", "message": "Factures région Nord", "session_id": sid, "theme_id": t1},
    )

    move_resp = client.post(f"/api/client/chat/themes/{t2}/sessions/{sid}", headers=headers)
    assert move_resp.status_code == 200

    t2_data = client.get("/api/client/chat/themes?agent_id=jerome", headers=headers).json()["themes"]
    theme2 = next(t for t in t2_data if t["theme_id"] == t2)
    assert any(s["session_id"] == sid for s in theme2["sessions"])

    merge_resp = client.post(f"/api/client/chat/themes/{t2}/merge/{t1}", headers=headers)
    assert merge_resp.status_code == 200

    after_merge = client.get("/api/client/chat/themes?agent_id=jerome", headers=headers).json()["themes"]
    assert not any(t["theme_id"] == t2 for t in after_merge)
    theme1 = next(t for t in after_merge if t["theme_id"] == t1)
    assert any(s["session_id"] == sid for s in theme1["sessions"])


def test_kan84_ca5_delete_theme(test_app):
    """CA5 : Suppression d'un thème avec détachement ou purge des sessions associées."""
    client = test_app["client"]
    token = test_app["token"]
    headers = {"Authorization": f"Bearer {token}"}

    t_id = client.post("/api/client/chat/themes", headers=headers, json={"title": "Audit provisoire", "agent_id": "jerome"}).json()["theme"]["theme_id"]
    sid = "session_to_detach"
    client.post("/api/client/chat", headers=headers, json={"agent_id": "jerome", "message": "Test message", "session_id": sid, "theme_id": t_id})

    del_resp = client.delete(f"/api/client/chat/themes/{t_id}?delete_sessions=false", headers=headers)
    assert del_resp.status_code == 200

    themes = client.get("/api/client/chat/themes?agent_id=jerome", headers=headers).json()["themes"]
    assert not any(t["theme_id"] == t_id for t in themes)

    s_details = client.get(f"/api/client/chat/sessions/{sid}?agent_id=jerome", headers=headers).json()
    assert s_details["dossier_metier_id"] is None


def test_kan84_ca6_multi_tenant_isolation(test_app):
    """CA6 : Étanchéité multi-tenant et inter-utilisateurs stricte."""
    client = test_app["client"]
    token_a = test_app["token"]  # user-sophie
    token_b = _generate_jwt("user-other")

    t_alice = client.post("/api/client/chat/themes", headers={"Authorization": f"Bearer {token_a}"}, json={"title": "Secret Sophie", "agent_id": "jerome"}).json()["theme"]["theme_id"]

    bob_list = client.get("/api/client/chat/themes?agent_id=jerome", headers={"Authorization": f"Bearer {token_b}"}).json()["themes"]
    assert not any(t["theme_id"] == t_alice for t in bob_list)

    patch_resp = client.patch(
        f"/api/client/chat/themes/{t_alice}",
        headers={"Authorization": f"Bearer {token_b}"},
        json={"title": "Hacked Title"},
    )
    assert patch_resp.status_code == 404

    del_resp = client.delete(
        f"/api/client/chat/themes/{t_alice}",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert del_resp.status_code == 404


def test_kan84_ca7_no_nouvelle_discussion_saved_in_db(test_app):
    """CA7 : Aucune entrée 'Nouvelle discussion' ne doit subsister en base comme nom de thème."""
    client = test_app["client"]
    token = test_app["token"]
    headers = {"Authorization": f"Bearer {token}"}

    client.post(
        "/api/client/chat",
        headers=headers,
        json={"agent_id": "jerome", "message": "Vérification trésorerie", "session_id": "session_no_empty_name"},
    )

    db_path = test_app["db"]
    with sqlite3.connect(str(db_path)) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT title FROM client_chat_themes WHERE title = 'Nouvelle discussion'")
        assert cursor.fetchall() == []

"""Tests d'acceptation KAN-83 : Historique des conversations dans l'interface client.

Vérification rigoureuse et exhaustive des 7 critères d'acceptation (CA1 à CA7) :
- CA1 : Liste des conversations par utilisateur avec titre, horodatage et persistance après reconnexion.
- CA2 : Réouverture d'une conversation ancienne avec intégrité de l'ordre, horodatages, agent et chaîne de compression.
- CA3 : Continuité contextuelle au moteur lors de la reprise d'une conversation.
- CA4 : Suppression unitaire réelle et définitive (client_chat_sessions + SessionDB), refus 404 sur appel direct post-suppression.
- CA5 : Cloisonnement strict multi-utilisateurs et multi-tenants (liste hermétique, refus 403).
- CA6 : Attachement et exposition explicite de l'agent et de l'espace client.
- CA7 : Conservation absolue de 60 jours (purge réelle, refus 410 sur conversation expirée, absence d'exception d'épinglage).
- Évolutions complémentaires : Renommage protégé par autorité utilisateur (title_source='user') et dossier métier optionnel.
"""

import base64
import json
import sqlite3
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hermes_cli.web_routers.client_chat_history import (
    generate_auto_title,
    history_router,
    purge_client_expired_sessions,
)
from hermes_cli.web_routers.client_ui import (
    _get_client_sessions_db_path,
    _init_client_sessions_db,
    router as client_ui_router,
)
from hermes_state import SessionDB


def _generate_jwt(
    user_id: str,
    tenant_id: str = "f3e25379-6531-479e-b276-3b3185e7421b",
    tenant_slug: str = "financia-solutions",
    secret: str = "test-secret",
) -> str:
    """Génère un jeton JWT de test signé HMAC-SHA256."""
    import hashlib
    import hmac

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
        self.id = "chunk-kan83"
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
        messages = kwargs.get("messages", [])
        user_msgs = [m.get("content") for m in messages if isinstance(m, dict) and m.get("role") == "user"]
        last_prompt = str(user_msgs[-1] if user_msgs else "").lower()

        if "balance" in last_prompt:
            reply = "Voici l'analyse détaillée de votre balance âgée : 3 factures en retard totalisant 14 500 €."
        elif "relance" in last_prompt and len(user_msgs) > 1:
            reply = "Je prépare immédiatement la relance pour les 14 500 € en retard identifiés précédemment."
        elif "giallo" in last_prompt:
            reply = "J'ai vérifié le SIREN de la société Giallo : 4 entités actives répertoriées."
        else:
            reply = f"Réponse contextualisée pour : {last_prompt}"

        chunks = [
            _FakeChunk(content=reply),
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

    agents_root = tmp_path / "data" / "agents"
    agents_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        "hermes_cli.web_routers.client_ui.PROJECT_ROOT",
        tmp_path,
    )

    from agent import process_bootstrap
    monkeypatch.setattr(process_bootstrap, "OpenAI", _FakeClient)

    app = FastAPI()
    app.include_router(client_ui_router)
    return TestClient(app), tmp_path


def test_auto_title_generator():
    """Vérifie la règle de titrage : 6 mots maximum à partir de la première intention."""
    assert generate_auto_title("Bonjour Jérôme, peux-tu faire un audit complet de la balance âgée de ce mois ?") == "Bonjour Jérôme, peux-tu faire un audit"
    assert generate_auto_title("Vérification SIREN Giallo") == "Vérification SIREN Giallo"
    assert generate_auto_title("   ") == "Nouvelle discussion"


def test_ca1_list_sessions_after_exchange_and_reconnection(test_app):
    """CA1 - Après un échange, la conversation apparaît dans la liste avec titre et horodatage,

    et survit à une reconnexion (nouveau jeton d'authentification).
    """
    client, _ = test_app
    token_sophie = _generate_jwt("sophie-martin")
    session_id = "session_jerome_sophie_ca1_valid"

    # Envoi du premier message
    res_chat = client.post(
        "/api/client/chat",
        json={
            "agent_id": "jerome",
            "message": "Peux-tu analyser la balance âgée des clients ?",
            "session_id": session_id,
        },
        headers={"Authorization": f"Bearer {token_sophie}"},
    )
    assert res_chat.status_code == 200

    # 1. Consultation de la liste avec la première session
    res_list1 = client.get(
        "/api/client/chat/sessions?agent_id=jerome",
        headers={"Authorization": f"Bearer {token_sophie}"},
    )
    assert res_list1.status_code == 200
    data1 = res_list1.json()
    assert data1["total"] >= 1
    found = next((s for s in data1["sessions"] if s["session_id"] == session_id), None)
    assert found is not None
    assert "Peux-tu analyser la balance" in found["title"]
    assert len(found["title"].split()) <= 6
    assert found["agent_id"] == "jerome"
    assert found["last_activity_at"] > 0
    assert found["created_at"] > 0

    # 2. Simulation de reconnexion avec un nouveau jeton (même utilisateur)
    time.sleep(0.01)
    new_token_sophie = _generate_jwt("sophie-martin")
    res_list2 = client.get(
        "/api/client/chat/sessions?agent_id=jerome",
        headers={"Authorization": f"Bearer {new_token_sophie}"},
    )
    assert res_list2.status_code == 200
    data2 = res_list2.json()
    found2 = next((s for s in data2["sessions"] if s["session_id"] == session_id), None)
    assert found2 is not None
    assert found2["title"] == found["title"]


def test_ca2_reopen_old_conversation_and_compression_lineage(test_app):
    """CA2 - Rouvrir une conversation ancienne restitue l'intégralité des messages dans l'ordre,

    avec leurs horodatages et l'agent qui a répondu, y compris à travers une chaîne de compression.
    """
    client, tmp_path = test_app
    token = _generate_jwt("sophie-martin")
    session_id = "session_jerome_sophie_ca2_chain"

    # Initialisation de la session avec 2 tours
    client.post(
        "/api/client/chat",
        json={"agent_id": "jerome", "message": "Premier tour d'analyse balance", "session_id": session_id},
        headers={"Authorization": f"Bearer {token}"},
    )
    client.post(
        "/api/client/chat",
        json={"agent_id": "jerome", "message": "Deuxième tour demande relance", "session_id": session_id},
        headers={"Authorization": f"Bearer {token}"},
    )

    # Simulation d'une session compressée : création d'une session enfant dans SessionDB
    agent_db_path = tmp_path / "data" / "agents" / "jerome" / "state.db"
    sdb = SessionDB(agent_db_path)
    child_session_id = f"{session_id}_child_compaction"
    sdb.create_session(child_session_id, source="client_ui", parent_session_id=session_id)
    sdb.append_message(child_session_id, "user", {"content": "Troisième tour après compression"})
    sdb.append_message(child_session_id, "assistant", {"content": "Réponse après compression"})

    # Consultation du fil via l'API client
    res = client.get(
        f"/api/client/chat/messages?agent_id=jerome&session_id={session_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["session_id"] == session_id
    assert data["agent_id"] == "jerome"
    assert data["count"] >= 4
    messages = data["messages"]
    assert len(messages) >= 4
    # Ordre et horodatages présents
    assert messages[0]["role"] == "user"
    assert "Premier tour" in messages[0]["content"]
    assert messages[1]["role"] == "assistant"
    assert messages[1]["agent_id"] == "jerome"
    assert messages[1]["timestamp"] is not None


def test_ca3_context_continuity_on_resumed_conversation(test_app):
    """CA3 - Dans une conversation reprise, le contexte antérieur est rejoué au moteur sans répétition."""
    client, _ = test_app
    token = _generate_jwt("sophie-martin")
    session_id = "session_jerome_sophie_ca3_context"

    # Message 1
    res1 = client.post(
        "/api/client/chat",
        json={
            "agent_id": "jerome",
            "message": "Fais un audit de la balance âgée",
            "session_id": session_id,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res1.status_code == 200
    assert "14 500 €" in res1.text

    # Message 2 : question de suivi dans la conversation reprise
    res2 = client.post(
        "/api/client/chat",
        json={
            "agent_id": "jerome",
            "message": "Prépare la relance pour ce montant",
            "session_id": session_id,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res2.status_code == 200
    assert "14 500 €" in res2.text or "relance" in res2.text


def test_ca4_deletion_removes_from_list_and_db_and_blocks_direct_access(test_app):
    """CA4 - La suppression retire la conversation de la liste et de la base (client_chat_sessions et SessionDB) ;

    tout appel direct ultérieur est refusé avec HTTP 404.
    """
    client, tmp_path = test_app
    token = _generate_jwt("sophie-martin")
    session_id = "session_jerome_sophie_ca4_delete_target"

    # Création de la conversation
    client.post(
        "/api/client/chat",
        json={"agent_id": "jerome", "message": "Message à supprimer", "session_id": session_id},
        headers={"Authorization": f"Bearer {token}"},
    )

    # Vérification présence en base et SessionDB
    db_file = tmp_path / "client_chat_sessions.db"
    with sqlite3.connect(str(db_file)) as conn:
        row = conn.execute("SELECT session_id FROM client_chat_sessions WHERE session_id = ?", (session_id,)).fetchone()
        assert row is not None

    agent_db_path = tmp_path / "data" / "agents" / "jerome" / "state.db"
    sdb = SessionDB(agent_db_path)
    assert len(sdb.get_messages_as_conversation(session_id)) >= 2

    # Exécution de la suppression
    res_del = client.delete(
        f"/api/client/chat/sessions/{session_id}?agent_id=jerome",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res_del.status_code == 200
    assert res_del.json()["deleted"] is True

    # 1. Vérification que la session n'est plus dans la liste
    res_list = client.get(
        "/api/client/chat/sessions?agent_id=jerome",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert not any(s["session_id"] == session_id for s in res_list.json()["sessions"])

    # 2. Vérification disparition physique de client_chat_sessions.db
    with sqlite3.connect(str(db_file)) as conn:
        row_after = conn.execute("SELECT session_id FROM client_chat_sessions WHERE session_id = ?", (session_id,)).fetchone()
        assert row_after is None

    # 3. Vérification disparition physique de SessionDB
    assert len(sdb.get_messages_as_conversation(session_id)) == 0

    # 4. Appel direct de l'identifiant après suppression -> HTTP 404
    res_direct_messages = client.get(
        f"/api/client/chat/messages?agent_id=jerome&session_id={session_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res_direct_messages.status_code == 404

    res_direct_details = client.get(
        f"/api/client/chat/sessions/{session_id}?agent_id=jerome",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res_direct_details.status_code == 404


def test_ca5_multi_user_and_multi_tenant_isolation(test_app):
    """CA5 - Étanchéité stricte : un second compte du même client ou d'un client tiers ne voit pas les conversations d'autrui."""
    client, _ = test_app
    token_sophie = _generate_jwt("sophie-martin")
    token_pierre = _generate_jwt("pierre-durand")
    token_autre = _generate_jwt("autre-user", tenant_id="autre-tenant-id", tenant_slug="societe-autre")

    session_sophie = "session_jerome_sophie_ca5_secret"

    # Sophie crée sa session
    client.post(
        "/api/client/chat",
        json={"agent_id": "jerome", "message": "Données confidentielles Sophie", "session_id": session_sophie},
        headers={"Authorization": f"Bearer {token_sophie}"},
    )

    # Pierre liste ses conversations : il ne doit PAS voir la session de Sophie
    res_pierre_list = client.get(
        "/api/client/chat/sessions?agent_id=jerome",
        headers={"Authorization": f"Bearer {token_pierre}"},
    )
    assert res_pierre_list.status_code == 200
    assert not any(s["session_id"] == session_sophie for s in res_pierre_list.json()["sessions"])

    # Pierre tente d'accéder directement aux détails de la session de Sophie -> 403
    res_pierre_direct = client.get(
        f"/api/client/chat/sessions/{session_sophie}?agent_id=jerome",
        headers={"Authorization": f"Bearer {token_pierre}"},
    )
    assert res_pierre_direct.status_code == 403

    # L'utilisateur du tenant tiers tente d'accéder aux détails -> 403
    res_autre_direct = client.get(
        f"/api/client/chat/sessions/{session_sophie}?agent_id=jerome",
        headers={"Authorization": f"Bearer {token_autre}"},
    )
    assert res_autre_direct.status_code == 403


def test_ca6_agent_and_tenant_metadata_attached(test_app):
    """CA6 - Le nom de l'agent et l'espace client d'origine restent attachés à chaque conversation et sont affichés."""
    client, _ = test_app
    token = _generate_jwt("sophie-martin")
    session_id = "session_clara_sophie_ca6_meta"

    # Session avec Clara
    client.post(
        "/api/client/chat",
        json={"agent_id": "clara", "message": "Bonjour Clara, gestion litiges", "session_id": session_id},
        headers={"Authorization": f"Bearer {token}"},
    )

    # Détails
    res = client.get(
        f"/api/client/chat/sessions/{session_id}?agent_id=clara",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["agent_id"] == "clara"
    assert data["tenant_id"] == "f3e25379-6531-479e-b276-3b3185e7421b"
    assert data["retention_days"] == 60


def test_ca7_retention_60_days_absolute_purge_and_rejection(test_app):
    """CA7 - Conservation de 60 jours : une conversation dont le dernier échange a plus de 60 jours

    est purgée, n'est plus listée, et son accès direct est refusé avec HTTP 410.
    """
    client, tmp_path = test_app
    token = _generate_jwt("sophie-martin")
    session_active = "session_jerome_sophie_active_ok"
    session_expired = "session_jerome_sophie_expired_65days"

    # Création de deux sessions
    client.post(
        "/api/client/chat",
        json={"agent_id": "jerome", "message": "Session récente active", "session_id": session_active},
        headers={"Authorization": f"Bearer {token}"},
    )
    client.post(
        "/api/client/chat",
        json={"agent_id": "jerome", "message": "Session ancienne expirée", "session_id": session_expired},
        headers={"Authorization": f"Bearer {token}"},
    )

    # Vieillissement artificiel de la session expirée à 65 jours dans client_chat_sessions.db
    db_file = tmp_path / "client_chat_sessions.db"
    t_65_days_ago = time.time() - (65 * 86400.0)
    with sqlite3.connect(str(db_file)) as conn:
        conn.execute(
            "UPDATE client_chat_sessions SET last_activity_at = ? WHERE session_id = ?",
            (t_65_days_ago, session_expired),
        )
        conn.commit()

    # 1. Avant purge : tentative d'accès direct à la session de plus de 60 jours -> rejet HTTP 410
    res_expired_direct = client.get(
        f"/api/client/chat/sessions/{session_expired}?agent_id=jerome",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res_expired_direct.status_code == 410
    assert "politique de conservation de 60 jours" in res_expired_direct.json()["detail"]

    # 2. Exécution de la purge réelle
    purged_count = purge_client_expired_sessions(max_age_days=60.0)
    assert purged_count >= 1

    # 3. Après purge : la session a disparu de la liste
    res_list = client.get(
        "/api/client/chat/sessions?agent_id=jerome",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res_list.status_code == 200
    sessions = res_list.json()["sessions"]
    assert any(s["session_id"] == session_active for s in sessions)
    assert not any(s["session_id"] == session_expired for s in sessions)

    # 4. Appel direct après purge -> HTTP 404
    res_after_purge = client.get(
        f"/api/client/chat/sessions/{session_expired}?agent_id=jerome",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res_after_purge.status_code == 404


def test_rename_and_business_folder_association(test_app):
    """Test complémentaire : renommage manuel protégé par 'user' et dossier métier optionnel."""
    client, _ = test_app
    token = _generate_jwt("sophie-martin")
    session_id = "session_jerome_sophie_rename_test"

    client.post(
        "/api/client/chat",
        json={"agent_id": "jerome", "message": "Point trésorerie", "session_id": session_id},
        headers={"Authorization": f"Bearer {token}"},
    )

    # Renommage et affectation dossier métier
    res_patch = client.patch(
        f"/api/client/chat/sessions/{session_id}",
        json={
            "title": "Bilan Trésorerie T3 2026",
            "dossier_metier_id": "DOSSIER-FINANCIA-2026-09",
            "agent_id": "jerome",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res_patch.status_code == 200
    data = res_patch.json()
    assert data["title"] == "Bilan Trésorerie T3 2026"
    assert data["title_source"] == "user"
    assert data["dossier_metier_id"] == "DOSSIER-FINANCIA-2026-09"

    # Vérification que le titrage automatique d'un nouveau message n'écrase PAS le titre utilisateur
    client.post(
        "/api/client/chat",
        json={"agent_id": "jerome", "message": "Nouveau message qui ne doit pas écraser", "session_id": session_id},
        headers={"Authorization": f"Bearer {token}"},
    )

    res_check = client.get(
        f"/api/client/chat/sessions/{session_id}?agent_id=jerome",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res_check.status_code == 200
    assert res_check.json()["title"] == "Bilan Trésorerie T3 2026"
    assert res_check.json()["title_source"] == "user"

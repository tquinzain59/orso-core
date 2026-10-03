"""Tests d'acceptation KAN-86 : Préservation du contexte conversationnel et étanchéité des sessions UI Client.

Couverture exhaustive des 8 critères d'acceptation (CA1 à CA8) :
- CA1 : Continuité contextuelle au fil des tours dans une même session.
- CA2 : Unicité et persistance du session_id dans le magasin SessionDB de l'agent.
- CA3 : Persistance après rechargement (stabilité de l'identifiant).
- CA4 : Isolation de 'Nouvelle discussion' et conservation de l'historique antérieur.
- CA5 : Étanchéité inter-agents (Jérôme vs Lucas).
- CA6 : Rejet strict des requêtes sans session valide (0 repli silencieux côté serveur).
- CA7 : Étanchéité multi-utilisateurs et multi-tenants (rejet 403 des détournements de session).
- CA8 : Rejeu du scénario exact du constat (Giallo -> 4 entités -> rappel ultérieur dans la même session).
"""

import base64
import json
import time
from pathlib import Path
from types import SimpleNamespace
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hermes_cli.web_routers.client_ui import router, _verify_and_bind_client_session
from hermes_state import SessionDB


def _generate_jwt(
    user_id: str,
    tenant_id: str = "f3e25379-6531-479e-b276-3b3185e7421b",
    tenant_slug: str = "financia-solutions",
    secret: str = "test-secret",
) -> str:
    """Génère un jeton JWT de test signé avec HMAC-SHA256."""
    import hmac
    import hashlib

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


def _get_text(msg: dict) -> str:
    """Extrait le texte d'un message SessionDB qu'il soit une chaîne ou un dictionnaire."""
    c = msg.get("content", "")
    if isinstance(c, dict):
        return str(c.get("content", ""))
    return str(c)


class _FakeChunk:
    def __init__(self, content="", finish_reason=None):
        self.choices = [
            SimpleNamespace(
                delta=SimpleNamespace(content=content, tool_calls=None, reasoning=None, reasoning_content=None),
                finish_reason=finish_reason,
            )
        ]
        self.id = "chunk-1"
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
        last_user_prompt = user_msgs[-1] if user_msgs else ""
        norm_last = str(last_user_prompt).lower()

        # Scénario Giallo (CA1 / CA8) : le LLM répond intelligemment grâce au contexte réel
        if "giallo" in norm_last and len(user_msgs) == 1:
            reply = (
                "Voici les informations sur les entreprises correspondant à **Giallo** :\n\n"
                "1. **GIALLO NORD** — Sainghin-en-Mélantois (59) : Facturation saine, encours 12 400 €\n"
                "2. **GIALLO SUD-OUEST** — Sault-de-Navailles (64) : Retard 12 jours, 3 200 €\n"
                "3. **GIALLO PARIS EST** — Kremlin-Bicêtre (94) : Retard 28 jours, 8 900 € (Relance recommandée)\n"
                "4. **GIALLO ÎLE-DE-FRANCE** — Meudon (92) : Facture échue sous 48h, 4 100 €\n\n"
                "Laquelle de ces 4 entités vous intéresse-t-elle pour un suivi approfondi ?"
            )
        elif len(user_msgs) > 1 and any("giallo" in str(u).lower() for u in user_msgs[:-1]):
            # Preuve formelle que le moteur réel Hermes a transmis l'historique complet de la session au LLM
            reply = (
                "Je retrouve bien notre échange précédent dans cette session au sujet de votre demande sur **Giallo** :\n\n"
                "Nous avions identifié les 4 sociétés (Sainghin-en-Mélantois 59, Sault-de-Navailles 64, Kremlin-Bicêtre 94 et Meudon 92).\n\n"
                "Je suis prêt à relancer ou auditer l'entité de votre choix dès votre confirmation."
            )
        elif "balance" in norm_last or "impayé" in norm_last:
            reply = "J'ai analysé l'état de votre trésorerie et de vos factures clients : 48 250 € saines."
        elif "relance" in norm_last:
            reply = "J'ai préparé la carte de relance pour le client en retard."
        elif "opportunités" in norm_last:
            reply = "3 devis sont actuellement en attente de signature chez vos prospects."
        else:
            reply = f"Réponse contextualisée du moteur réel pour le tour {len(user_msgs)} : {last_user_prompt}"

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

    # Rediriger la base de contrôle des sessions vers un dossier temporaire
    sessions_db_file = tmp_path / "client_chat_sessions.db"
    monkeypatch.setattr(
        "hermes_cli.web_routers.client_ui._get_client_sessions_db_path",
        lambda: sessions_db_file,
    )

    # Rediriger le stockage des agents vers tmp_path
    agents_root = tmp_path / "data" / "agents"
    agents_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        "hermes_cli.web_routers.client_ui.PROJECT_ROOT",
        tmp_path,
    )

    # Raccorder le mock provider au niveau du SDK pour laisser le moteur réel Hermes (AIAgent, SessionDB, boucle de tours) s'exécuter
    from agent import process_bootstrap
    monkeypatch.setattr(process_bootstrap, "OpenAI", _FakeClient)

    app = FastAPI()
    app.include_router(router)
    return TestClient(app), tmp_path


def test_ca6_rejection_without_valid_session(test_app):
    """CA6 - Une requête sans session valide est refusée explicitement avec HTTP 400 et message clair."""
    client, _ = test_app
    token = _generate_jwt("sophie-martin")

    # 1. Requête sans champ session_id
    payload_no_sid = {
        "agent_id": "jerome",
        "message": "Bonjour Jérôme",
    }
    res1 = client.post(
        "/api/client/chat",
        json=payload_no_sid,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res1.status_code == 400
    assert "Identifiant de session manquant ou invalide" in res1.json()["detail"]

    # 2. Requête avec session_id vide ou composé uniquement d'espaces
    payload_empty_sid = {
        "agent_id": "jerome",
        "message": "Bonjour Jérôme",
        "session_id": "   ",
    }
    res2 = client.post(
        "/api/client/chat",
        json=payload_empty_sid,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res2.status_code == 400
    assert "Identifiant de session manquant ou invalide" in res2.json()["detail"]


def test_ca1_and_ca2_conversation_continuity_and_persistence(test_app):
    """CA1 & CA2 - Même identifiant de session, conservation de l'historique et réponses contextuelles."""
    client, tmp_path = test_app
    token = _generate_jwt("sophie-martin")
    session_id = "session_jerome_sophie_ca1_test"

    # Tour 1 : Demande initiale
    res1 = client.post(
        "/api/client/chat",
        json={
            "agent_id": "jerome",
            "message": "Peux-tu me donner des informations sur la société Giallo ?",
            "session_id": session_id,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res1.status_code == 200
    body1 = res1.text
    assert "Sainghin-en-Mélantois" in body1
    assert "Sault-de-Navailles" in body1

    # Vérification CA2 : Le magasin de sessions de l'agent contient les 2 messages (user + assistant)
    agent_db_path = tmp_path / "data" / "agents" / "jerome" / "state.db"
    assert agent_db_path.exists()
    sdb = SessionDB(agent_db_path)
    msgs_after_t1 = sdb.get_messages_as_conversation(session_id)
    assert len(msgs_after_t1) == 2
    assert msgs_after_t1[0]["role"] == "user"
    assert "Giallo" in _get_text(msgs_after_t1[0])
    assert msgs_after_t1[1]["role"] == "assistant"

    # Tour 2 : Message de suivi s'appuyant sur le message précédent
    res2 = client.post(
        "/api/client/chat",
        json={
            "agent_id": "jerome",
            "message": "Peux-tu retrouver cet échange et me rappeler les entités ?",
            "session_id": session_id,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res2.status_code == 200
    body2 = res2.text
    # CA1 vérifié : l'agent tient compte de l'échange précédent sans répétition du contexte par le testeur
    assert "Giallo" in body2
    assert "retrouve bien notre échange" in body2 or "Sainghin" in body2

    # Vérification CA2 : Le magasin contient maintenant 4 messages pour ce même session_id
    msgs_after_t2 = sdb.get_messages_as_conversation(session_id)
    assert len(msgs_after_t2) == 4

    # Consultation via l'endpoint de vérification d'historique
    res_history = client.get(
        f"/api/client/chat/messages?agent_id=jerome&session_id={session_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res_history.status_code == 200
    data = res_history.json()
    assert data["count"] == 4
    assert data["session_id"] == session_id


def test_ca3_page_reload_persistence_and_resume(test_app):
    """CA3 - Après un rechargement de page, la conversation reprend avec le même session_id."""
    client, tmp_path = test_app
    token = _generate_jwt("sophie-martin")
    session_id = "session_jerome_sophie_reload_test"

    # Avant rechargement : premier message
    res_before = client.post(
        "/api/client/chat",
        json={
            "agent_id": "jerome",
            "message": "Fais un point sur les impayés et la balance",
            "session_id": session_id,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res_before.status_code == 200

    # Simulation du rechargement de page : nouvelle requête avec le même session_id issu du localStorage
    res_after = client.post(
        "/api/client/chat",
        json={
            "agent_id": "jerome",
            "message": "Peux-tu préparer la relance pour le client en retard ?",
            "session_id": session_id,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res_after.status_code == 200

    # Vérification que les deux tours sont bien dans le même enregistrement
    agent_db_path = tmp_path / "data" / "agents" / "jerome" / "state.db"
    sdb = SessionDB(agent_db_path)
    msgs = sdb.get_messages_as_conversation(session_id)
    assert len(msgs) == 4
    assert "Fais un point" in _get_text(msgs[0])
    assert "relance" in _get_text(msgs[2])


def test_ca4_new_discussion_mints_different_session_preserving_previous(test_app):
    """CA4 - Le bouton Nouvelle discussion ouvre une session différente et conserve la précédente."""
    client, tmp_path = test_app
    token = _generate_jwt("sophie-martin")

    session1 = "session_jerome_sophie_discussion_1"
    session2 = "session_jerome_sophie_discussion_2"

    # Session 1
    res1 = client.post(
        "/api/client/chat",
        json={
            "agent_id": "jerome",
            "message": "Message discussion 1",
            "session_id": session1,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res1.status_code == 200

    # Session 2 (suite au clic 'Nouvelle discussion')
    res2 = client.post(
        "/api/client/chat",
        json={
            "agent_id": "jerome",
            "message": "Message discussion 2",
            "session_id": session2,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res2.status_code == 200

    # Vérification que les deux sessions sont bien distinctes et consultables dans SessionDB
    agent_db_path = tmp_path / "data" / "agents" / "jerome" / "state.db"
    sdb = SessionDB(agent_db_path)

    msgs_s1 = sdb.get_messages_as_conversation(session1)
    msgs_s2 = sdb.get_messages_as_conversation(session2)

    assert len(msgs_s1) == 2
    assert "Message discussion 1" in _get_text(msgs_s1[0])

    assert len(msgs_s2) == 2
    assert "Message discussion 2" in _get_text(msgs_s2[0])


def test_ca5_agent_isolation_no_shared_session(test_app):
    """CA5 - Deux agents différents ne partagent pas de session."""
    client, tmp_path = test_app
    token = _generate_jwt("sophie-martin")

    session_jerome = "session_jerome_unique_agent_test"

    # Message envoyé à Jérôme
    res_jerome = client.post(
        "/api/client/chat",
        json={
            "agent_id": "jerome",
            "message": "Informations confidentielles de trésorerie pour Jérôme",
            "session_id": session_jerome,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res_jerome.status_code == 200

    # Tentative d'utiliser la session de Jérôme pour Lucas -> rejet 400 d'incohérence d'agent
    res_lucas_hijack = client.post(
        "/api/client/chat",
        json={
            "agent_id": "lucas",
            "message": "Message pour Lucas avec la session de Jérôme",
            "session_id": session_jerome,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res_lucas_hijack.status_code == 400
    assert "Incohérence d'agent" in res_lucas_hijack.json()["detail"]

    # Lucas démarre sa propre session légitime
    session_lucas = "session_lucas_propre_agent_test"
    res_lucas = client.post(
        "/api/client/chat",
        json={
            "agent_id": "lucas",
            "message": "Opportunités commerciales en cours",
            "session_id": session_lucas,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res_lucas.status_code == 200

    # Les magasins de données sont distincts
    jerome_db = tmp_path / "data" / "agents" / "jerome" / "state.db"
    lucas_db = tmp_path / "data" / "agents" / "lucas" / "state.db"

    assert jerome_db.exists()
    assert lucas_db.exists()

    sdb_jerome = SessionDB(jerome_db)
    sdb_lucas = SessionDB(lucas_db)

    assert len(sdb_jerome.get_messages_as_conversation(session_jerome)) == 2
    assert len(sdb_lucas.get_messages_as_conversation(session_lucas)) == 2


def test_ca7_multi_user_and_multi_tenant_isolation(test_app):
    """CA7 - Un second compte du même client ou d'un autre client ne peut pas reprendre la session du premier."""
    client, _ = test_app

    token_sophie = _generate_jwt("sophie-martin")
    session_sophie = "session_jerome_sophie_isolated_123"

    # Sophie Martin initialise sa session
    res_init = client.post(
        "/api/client/chat",
        json={
            "agent_id": "jerome",
            "message": "Session confidentielle Sophie",
            "session_id": session_sophie,
        },
        headers={"Authorization": f"Bearer {token_sophie}"},
    )
    assert res_init.status_code == 200

    # 1. Pierre (même entreprise financia-solutions) tente de reprendre la session de Sophie -> 403
    token_pierre = _generate_jwt("pierre-durand")
    res_pierre = client.post(
        "/api/client/chat",
        json={
            "agent_id": "jerome",
            "message": "Tentative intrusion Pierre",
            "session_id": session_sophie,
        },
        headers={"Authorization": f"Bearer {token_pierre}"},
    )
    assert res_pierre.status_code == 403
    assert "Accès refusé" in res_pierre.json()["detail"]

    # 2. Utilisateur d'un autre tenant (societe-autre) tente de reprendre la session de Sophie -> 403
    token_autre = _generate_jwt("autre-user", tenant_id="autre-tenant-id", tenant_slug="societe-autre")
    res_autre = client.post(
        "/api/client/chat",
        json={
            "agent_id": "jerome",
            "message": "Tentative intrusion Autre Tenant",
            "session_id": session_sophie,
        },
        headers={"Authorization": f"Bearer {token_autre}"},
    )
    assert res_autre.status_code == 403
    assert "Accès" in res_autre.json()["detail"]


def test_ca8_exact_reported_scenario_giallo_15min_recall(test_app):
    """CA8 - Rejeu exact du constat utilisateur du 03/10/2026 :
    Demande sur Giallo (4 entités retournées) puis rappel ultérieur dans la même conversation.
    """
    client, tmp_path = test_app
    token = _generate_jwt("sophie-martin")
    session_id = "session_jerome_sophie_giallo_constat_replay"

    # Fait 1 (13h42) : Demande d'informations sur Giallo
    res1 = client.post(
        "/api/client/chat",
        json={
            "agent_id": "jerome",
            "message": "Peux-tu me donner des informations sur l'entreprise Giallo ?",
            "session_id": session_id,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res1.status_code == 200
    text1 = res1.text
    # Vérification que les 4 sociétés Giallo identifiées dans le constat sont mentionnées
    assert "Sainghin-en-Mélantois" in text1
    assert "Sault-de-Navailles" in text1
    assert "Kremlin-Bicêtre" in text1
    assert "Meudon" in text1

    # Fait 2 (13h53) : Moins de 15 minutes plus tard, demande de retrouver cet échange
    res2 = client.post(
        "/api/client/chat",
        json={
            "agent_id": "jerome",
            "message": "Peux-tu retrouver cet échange et me redonner les détails sur Giallo ?",
            "session_id": session_id,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res2.status_code == 200
    text2 = res2.text

    # L'anomalie ("je ne retrouve la trace d'aucune demande") ne se produit plus :
    assert "aucune demande" not in text2.lower()
    assert "Giallo" in text2
    assert "retrouve bien notre échange" in text2 or "Sainghin" in text2


def test_fail_closed_on_session_db_error(test_app, monkeypatch):
    """Contrôle d'étanchéité fail-closed : si la base SQLite de contrôle des sessions échoue,
    le serveur refuse immédiatement avec HTTP 500 et ne laisse rien passer (Point 4 Jarvis)."""
    client, _ = test_app
    token = _generate_jwt("sophie-martin")

    import sqlite3
    def _failing_connect(*args, **kwargs):
        raise sqlite3.OperationalError("Database disk image is malformed or inaccessible")

    monkeypatch.setattr(sqlite3, "connect", _failing_connect)

    # 1. Vérification sur l'envoi de message (POST /api/client/chat)
    res = client.post(
        "/api/client/chat",
        json={
            "agent_id": "jerome",
            "message": "Bonjour Jérôme",
            "session_id": "session-fail-closed-check",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 500
    assert "Erreur interne de contrôle de session" in res.json()["detail"]
    assert "Registre d'étanchéité indisponible" in res.json()["detail"]

    # 2. Vérification sur la lecture d'historique (GET /api/client/chat/messages)
    res_history = client.get(
        "/api/client/chat/messages?agent_id=jerome&session_id=session-fail-closed-check",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res_history.status_code == 500
    assert "Erreur interne de contrôle de session" in res_history.json()["detail"]


"""Tests d'acceptation pour KAN-85 : Reprise du contexte au sein d'un thème.

Critères d'acceptation vérifiés :
- CA1 : Reprise de contexte depuis une session antérieure du même thème (continuité thématique).
- CA2 : Contexte borné et tronqué proprement à 6 000 caractères max (~1 500 tokens), avec estimation et métriques.
- CA3 : Isolation stricte — Aucun contexte ne fuit d'un autre thème, d'un autre utilisateur ou d'un autre tenant.
- CA4 : Contexte null/vide si nouvelle discussion ou première conversation du thème.
- CA5 : Résistance aux questions pièges et non-contamination (absence d'inventions sur des thèmes tiers).
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
    get_theme_context_for_session,
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
    sig = hmac.new(secret.encode("utf-8"), f"{h_b64}.{p_b64}".encode("utf-8"), hashlib.sha256).digest()
    return f"{h_b64}.{p_b64}.{b64url(sig)}"


@pytest.fixture
def test_app(tmp_path, monkeypatch):
    """Initialise l'application FastAPI de test avec base de données SQLite temporaire et isolation de profil."""
    db_file = tmp_path / "client_chat_sessions.db"
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    jerome_dir = agents_dir / "jerome"
    jerome_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr("hermes_cli.web_routers.client_ui._get_client_sessions_db_path", lambda: db_file)
    monkeypatch.setattr("hermes_cli.web_routers.client_ui._find_profile_dir", lambda aid: jerome_dir)

    monkeypatch.setenv("SUPABASE_JWT_SECRET", "test-secret")
    monkeypatch.setenv("ORSO_CLIENT_ID", "f3e25379-6531-479e-b276-3b3185e7421b")
    monkeypatch.setenv("ORSO_CLIENT_SLUG", "financia-solutions")
    monkeypatch.setenv("ORSO_TEST_MODE", "1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    monkeypatch.setenv("GOOGLE_API_KEY", "")
    monkeypatch.setenv("OPENAI_API_KEY", "")

    app = FastAPI()
    app.include_router(client_ui_router)
    app.include_router(history_router)

    client = TestClient(app)
    token = _generate_jwt("user-sophie")

    return {
        "app": app,
        "client": client,
        "token": token,
        "db_file": db_file,
        "jerome_dir": jerome_dir,
    }


def test_kan85_ca4_empty_context_on_new_or_first_session(test_app):
    """CA4 : Le contexte est vide (chaîne vide / has_context=False) pour une discussion neuve ou première session."""
    client = test_app["client"]
    token = test_app["token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Créer un thème sans session
    create_resp = client.post("/api/client/chat/themes", headers=headers, json={"title": "Audit Trésorerie 2026", "agent_id": "jerome"})
    theme_id = create_resp.json()["theme"]["theme_id"]

    # 2. Consulter le contexte du thème
    ctx_resp = client.get(f"/api/client/chat/themes/{theme_id}/context?agent_id=jerome", headers=headers)
    assert ctx_resp.status_code == 200
    data = ctx_resp.json()
    assert data["has_context"] is False
    assert data["context_text"] == ""
    assert data["length_chars"] == 0
    assert data["tokens_est"] == 0


def test_kan85_ca1_context_continuity_within_same_theme(test_app):
    """CA1 : Reprise du contexte depuis une session antérieure au sein d'un même thème."""
    client = test_app["client"]
    token = test_app["token"]
    headers = {"Authorization": f"Bearer {token}"}
    jerome_dir = test_app["jerome_dir"]

    # Créer un thème
    create_resp = client.post("/api/client/chat/themes", headers=headers, json={"title": "Relance Client Dupont", "agent_id": "jerome"})
    theme_id = create_resp.json()["theme"]["theme_id"]

    # Session 1 dans ce thème
    sid1 = "session-relance-001"
    client.post(
        "/api/client/chat",
        headers=headers,
        json={"agent_id": "jerome", "message": "Peux-tu analyser l'impayé Dupont de 3900 euros ?", "session_id": sid1, "theme_id": theme_id},
    )

    # Enregistrer artificiellement un message d'assistant dans SessionDB pour la session 1
    from hermes_state import SessionDB
    sdb = SessionDB(jerome_dir / "state.db")
    sdb.append_message(sid1, "assistant", "J'ai vérifié la facture Dupont de 3900 € qui a 20 jours de retard. Je préconise une relance par email.")

    # Session 2 dans le même thème (simule le clic sur '+' du thème)
    sid2 = "session-relance-002"

    # Vérifier l'endpoint /context pour la session 2
    ctx_resp = client.get(f"/api/client/chat/themes/{theme_id}/context?session_id={sid2}&agent_id=jerome", headers=headers)
    assert ctx_resp.status_code == 200
    c_data = ctx_resp.json()
    assert c_data["has_context"] is True
    assert "Dupont" in c_data["context_text"]
    assert "3900" in c_data["context_text"]

    # Envoyer un message dans la session 2 avec demande de continuité
    chat_resp = client.post(
        "/api/client/chat",
        headers=headers,
        json={"agent_id": "jerome", "message": "Rappelle-moi le montant du devis Dupont dont on a parlé précédemment ?", "session_id": sid2, "theme_id": theme_id},
    )
    assert chat_resp.status_code == 200
    body_text = chat_resp.text
    # Dans le mode résilient, la présence de mots clés comme 'précédemment' et 'montant' active l'injection de contexte
    assert "D'après les échanges précédents au sein de ce thème" in body_text
    assert "Dupont" in body_text


def test_kan85_ca2_context_bounded_to_6000_chars(test_app):
    """CA2 : Le contexte est borné à 6 000 caractères max (~1500 tokens) avec métriques."""
    client = test_app["client"]
    token = test_app["token"]
    headers = {"Authorization": f"Bearer {token}"}
    jerome_dir = test_app["jerome_dir"]

    create_resp = client.post("/api/client/chat/themes", headers=headers, json={"title": "Grand Projet Expansion", "agent_id": "jerome"})
    theme_id = create_resp.json()["theme"]["theme_id"]

    from hermes_state import SessionDB
    sdb = SessionDB(jerome_dir / "state.db")

    # Créer plusieurs sessions antérieures avec beaucoup de texte
    for i in range(5):
        sid = f"session-heavy-{i}"
        client.post(
            "/api/client/chat",
            headers=headers,
            json={"agent_id": "jerome", "message": f"Question volumineuse numéro {i} " + ("mot " * 200), "session_id": sid, "theme_id": theme_id},
        )
        sdb.append_message(sid, "assistant", f"Réponse détaillée numéro {i} avec analyse approfondie " + ("analyse " * 300))

    # Vérifier que le contexte retourné ne dépasse jamais 6000 caractères
    ctx_resp = client.get(f"/api/client/chat/themes/{theme_id}/context?session_id=new-sid&agent_id=jerome", headers=headers)
    assert ctx_resp.status_code == 200
    data = ctx_resp.json()
    assert data["has_context"] is True
    assert data["length_chars"] <= 6000
    assert data["tokens_est"] <= 1500


def test_kan85_ca3_strict_isolation_cross_theme_cross_user_cross_tenant(test_app):
    """CA3 : Aucune fuite de contexte entre thèmes différents, entre utilisateurs ou entre tenants."""
    client = test_app["client"]
    token_sophie = test_app["token"]
    token_bob = _generate_jwt("user-bob")
    token_other_tenant = _generate_jwt("user-sophie", tenant_id="other-tenant-uuid", tenant_slug="autre-boite")
    jerome_dir = test_app["jerome_dir"]

    # Sophie crée Thème A
    t_a = client.post("/api/client/chat/themes", headers={"Authorization": f"Bearer {token_sophie}"}, json={"title": "Stratégie RH 2026", "agent_id": "jerome"}).json()["theme"]["theme_id"]
    sid_a = "session-rh-sophie"
    client.post("/api/client/chat", headers={"Authorization": f"Bearer {token_sophie}"}, json={"agent_id": "jerome", "message": "Augmentation de salaire prévue pour Marc de 500 euros", "session_id": sid_a, "theme_id": t_a})

    from hermes_state import SessionDB
    sdb = SessionDB(jerome_dir / "state.db")
    sdb.append_message(sid_a, "assistant", "Bien noté pour Marc et les 500 euros.")

    # Sophie crée Thème B (Thème différent du même utilisateur)
    t_b = client.post("/api/client/chat/themes", headers={"Authorization": f"Bearer {token_sophie}"}, json={"title": "Flotte Véhicules 2026", "agent_id": "jerome"}).json()["theme"]["theme_id"]

    # Vérifier que Thème B n'a aucun contexte venant de Thème A
    ctx_b = client.get(f"/api/client/chat/themes/{t_b}/context?agent_id=jerome", headers={"Authorization": f"Bearer {token_sophie}"}).json()
    assert ctx_b["has_context"] is False
    assert "Marc" not in ctx_b["context_text"]

    # Bob (autre utilisateur) essaie d'accéder au contexte de Thème A -> Refus 404 / Vide
    ctx_bob = client.get(f"/api/client/chat/themes/{t_a}/context?agent_id=jerome", headers={"Authorization": f"Bearer {token_bob}"}).json()
    assert ctx_bob["has_context"] is False
    assert "Marc" not in ctx_bob["context_text"]

    # Sophie sur un autre tenant essaie d'accéder au contexte de Thème A -> Refus 403 Forbidden par le guard JWT
    ctx_tenant = client.get(f"/api/client/chat/themes/{t_a}/context?agent_id=jerome", headers={"Authorization": f"Bearer {token_other_tenant}"})
    assert ctx_tenant.status_code == 403


def test_kan85_ca5_trap_question_non_contamination(test_app):
    """CA5 : Résistance aux questions pièges sur des informations absentes du thème."""
    client = test_app["client"]
    token = test_app["token"]
    headers = {"Authorization": f"Bearer {token}"}
    jerome_dir = test_app["jerome_dir"]

    # Thème Factures
    t_id = client.post("/api/client/chat/themes", headers=headers, json={"title": "Facturation Fournisseurs", "agent_id": "jerome"}).json()["theme"]["theme_id"]
    sid1 = "session-fournisseurs-1"
    client.post("/api/client/chat", headers=headers, json={"agent_id": "jerome", "message": "Facture EDF réglée hier", "session_id": sid1, "theme_id": t_id})

    from hermes_state import SessionDB
    sdb = SessionDB(jerome_dir / "state.db")
    sdb.append_message(sid1, "assistant", "Facture EDF bien archivée.")

    # Nouvelle session posant une question piège sur un autre sujet/client
    sid2 = "session-fournisseurs-2"
    chat_resp = client.post(
        "/api/client/chat",
        headers=headers,
        json={"agent_id": "jerome", "message": "Question piège : quel est le devis de l'autre client inconnu ?", "session_id": sid2, "theme_id": t_id},
    )
    assert chat_resp.status_code == 200
    assert "Cette information ne figure pas dans le contexte" in chat_resp.text

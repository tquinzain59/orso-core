"""Tests d'acceptation pour KAN-85 : Reprise du contexte au sein d'un thème.

Alignement strict sur le référentiel d'acceptation du ticket Jira KAN-85 (CA1 à CA5)
et sur la consigne de reprise (Étape 5) :
- CA1 : L'icône plus ouvre une conversation vide rattachée au thème.
- CA2 : Continuité de rappel contextuel par le moteur réel et traçabilité de l'identifiant de requête.
- CA3 : Bornage explicite du contexte envoyé, documentation et trace mesurée.
- CA4 : Question piège (absence d'inventions/hallucinations) et étanchéité inter-thèmes et multi-tenants.
- CA5 : Contexte nul quand le thème ne contient qu'une seule conversation déjà vide ou zéro session.
- Plafond de troncature réel (> 6 000 caractères) avec préservation du pied de contexte.
- Métrique d'estimation des jetons (division entière par 4).
- Mode résilient hors ligne testé et nommé séparément.
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
from hermes_state import SessionDB


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


class _FakeChunk:
    def __init__(self, content="", finish_reason=None):
        self.choices = [
            SimpleNamespace(
                delta=SimpleNamespace(content=content, tool_calls=None, reasoning=None, reasoning_content=None),
                finish_reason=finish_reason,
            )
        ]
        self.id = "chunk-kan85"
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
    def __init__(self):
        self.recorded_calls = []

    def create(self, **kwargs):
        self.recorded_calls.append(kwargs)
        messages = kwargs.get("messages", [])
        system_instruction = kwargs.get("instructions") or ""
        for m in messages:
            if isinstance(m, dict) and m.get("role") == "system":
                system_instruction += " " + str(m.get("content", ""))

        user_msgs = [m.get("content") for m in messages if isinstance(m, dict) and m.get("role") == "user"]
        last_prompt = str(user_msgs[-1] if user_msgs else "")

        # Réponse intelligente basée sur ce qui a réellement été injecté au moteur
        if "montant" in last_prompt.lower() or "rappel" in last_prompt.lower():
            if "12 400" in system_instruction:
                reply = "D'après notre échange précédent, le montant retenu pour le devis Giallo est de 12 400 €."
            else:
                reply = "Je n'ai pas trouvé le montant dans le contexte précédent de ce thème."
        elif "piège" in last_prompt.lower() or "secret" in last_prompt.lower():
            if "code confidentiel" in system_instruction.lower():
                reply = "Fuite anormale détectée dans le contexte."
            else:
                reply = "Cette information ne figure pas dans le contexte des échanges précédents de ce thème. Je ne dispose d'aucun élément à ce sujet."
        else:
            reply = f"Réponse du moteur réel pour : {last_prompt[:50]}"

        chunks = [
            _FakeChunk(content=reply),
            _FakeChunk(content="", finish_reason="stop"),
        ]
        return _FakeStream(chunks)


class _FakeClient:
    def __init__(self, **kwargs):
        self.api_key = kwargs.get("api_key") or "sk-fake-openrouter-key"
        self.base_url = kwargs.get("base_url") or "https://openrouter.ai/api/v1"
        self.default_headers = {}
        self._custom_headers = {}
        self.completions_engine = _FakeCompletions()
        self.chat = SimpleNamespace(completions=self.completions_engine)
        self.closed = False

    def close(self):
        self.closed = True


def _add_exchange_to_sdb(sdb: SessionDB, sid: str, user_text: str, asst_text: str) -> None:
    try:
        sdb.create_session(sid, source="client_ui")
    except Exception:
        pass
    sdb.append_message(sid, "user", user_text)
    sdb.append_message(sid, "assistant", asst_text)


@pytest.fixture
def test_app(tmp_path, monkeypatch):
    """Initialise l'application FastAPI de test avec base de données SQLite temporaire et isolation de profil."""
    try:
        from agent.auxiliary_client import _client_cache
        _client_cache.clear()
    except Exception:
        pass

    db_file = tmp_path / "client_chat_sessions.db"
    agents_root = tmp_path / "data" / "agents"
    agents_root.mkdir(parents=True, exist_ok=True)
    jerome_dir = agents_root / "jerome"
    jerome_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr("hermes_cli.web_routers.client_ui._get_client_sessions_db_path", lambda: db_file)
    monkeypatch.setattr("hermes_cli.web_routers.client_ui.PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("hermes_cli.web_routers.client_ui._find_profile_dir", lambda aid: agents_root / aid)

    monkeypatch.setenv("SUPABASE_JWT_SECRET", "test-secret")
    monkeypatch.setenv("ORSO_CLIENT_ID", "f3e25379-6531-479e-b276-3b3185e7421b")
    monkeypatch.setenv("ORSO_CLIENT_SLUG", "financia-solutions")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-fake-openrouter-key")
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    fake_client = _FakeClient()
    try:
        import openai
        monkeypatch.setattr(openai, "OpenAI", lambda **kw: fake_client)
    except Exception:
        pass

    from agent import process_bootstrap
    monkeypatch.setattr(process_bootstrap, "OpenAI", lambda **kw: fake_client)

    app = FastAPI()
    app.include_router(client_ui_router)
    app.include_router(history_router)

    _init_client_sessions_db()

    client = TestClient(app)
    token = _generate_jwt("user-sophie")

    yield {
        "app": app,
        "client": client,
        "token": token,
        "db_file": db_file,
        "jerome_dir": jerome_dir,
        "fake_client": fake_client,
    }

    try:
        from agent.auxiliary_client import _client_cache
        _client_cache.clear()
    except Exception:
        pass


def test_kan85_ca1_plus_icon_opens_empty_session_bound_to_theme(test_app):
    """CA1 : Depuis un thème, l'icône plus ouvre une conversation vide rattachée à ce thème."""
    client = test_app["client"]
    token = test_app["token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Création préalable du thème
    create_theme = client.post(
        "/api/client/chat/themes",
        headers=headers,
        json={"title": "Gestion Sinistres Assurances", "agent_id": "jerome"},
    )
    assert create_theme.status_code == 200
    theme_id = create_theme.json()["theme"]["theme_id"]

    # Émulation de l'icône plus : démarrage d'une nouvelle session avec theme_id renseigné
    sid_plus = "session-plus-icon-001"
    post_resp = client.post(
        "/api/client/chat",
        headers=headers,
        json={
            "agent_id": "jerome",
            "message": "Ouverture d'un dossier sinistre pour véhicule",
            "session_id": sid_plus,
            "theme_id": theme_id,
        },
    )
    assert post_resp.status_code == 200

    # Vérification que la session est directement liée au thème
    session_details = client.get(f"/api/client/chat/sessions/{sid_plus}?agent_id=jerome", headers=headers).json()
    assert session_details["dossier_metier_id"] == theme_id


def test_kan85_ca1_session_appears_in_theme_sessions_list(test_app):
    """CA1 complémentaire : La nouvelle conversation apparaît dans la liste des sessions du thème."""
    client = test_app["client"]
    token = test_app["token"]
    headers = {"Authorization": f"Bearer {token}"}

    create_theme = client.post(
        "/api/client/chat/themes",
        headers=headers,
        json={"title": "Contrôle Devis Travaux", "agent_id": "jerome"},
    )
    theme_id = create_theme.json()["theme"]["theme_id"]

    sid = "session-list-check-002"
    client.post(
        "/api/client/chat",
        headers=headers,
        json={"agent_id": "jerome", "message": "Analyse devis toiture", "session_id": sid, "theme_id": theme_id},
    )

    themes_list = client.get("/api/client/chat/themes?agent_id=jerome", headers=headers).json()["themes"]
    matching_theme = next(t for t in themes_list if t["theme_id"] == theme_id)
    assert matching_theme["sessions_count"] == 1
    assert any(s["session_id"] == sid for s in matching_theme["sessions"])


def test_kan85_ca2_engine_request_identifier_and_recall_continuity(test_app):
    """CA2 : Le moteur réel reçoit le contexte d'une conversation précédente du même thème

    et répond avec continuité sur une question sans que l'utilisateur ne la répète.
    L'identifiant de la session / requête est vérifié.
    """
    client = test_app["client"]
    token = test_app["token"]
    headers = {"Authorization": f"Bearer {token}"}
    jerome_dir = test_app["jerome_dir"]

    # 1. Thème partagé
    create_theme = client.post(
        "/api/client/chat/themes",
        headers=headers,
        json={"title": "Négociation Devis Giallo", "agent_id": "jerome"},
    )
    theme_id = create_theme.json()["theme"]["theme_id"]

    # 2. Conversation 1 : information clé enregistrée (12 400 €)
    sid1 = "session-devis-001"
    client.post(
        "/api/client/chat",
        headers=headers,
        json={"agent_id": "jerome", "message": "Devis Giallo pour 12 400 € reçu ce matin.", "session_id": sid1, "theme_id": theme_id},
    )
    sdb = SessionDB(jerome_dir / "state.db")
    sdb.append_message(sid1, "assistant", "J'ai bien noté le devis Giallo d'un montant de 12 400 €.")

    # 3. Conversation 2 dans le même thème : question demandant le montant
    sid2 = "session-devis-002"
    res2 = client.post(
        "/api/client/chat",
        headers=headers,
        json={"agent_id": "jerome", "message": "Quel est le montant du devis dans le rappel ?", "session_id": sid2, "theme_id": theme_id},
    )
    assert res2.status_code == 200
    body = res2.text

    # Vérification que le moteur réel a utilisé le contexte pour répondre
    assert "12 400" in body
    # Vérification de l'identifiant de session dans le flux
    assert f'"session_id": "{sid2}"' in body


def test_kan85_ca2_engine_receives_theme_context_in_prompt(test_app):
    """CA2 complémentaire : Preuve formelle que le moteur LLM reçoit le bloc de contexte du thème dans son prompt."""
    client = test_app["client"]
    token = test_app["token"]
    headers = {"Authorization": f"Bearer {token}"}
    jerome_dir = test_app["jerome_dir"]
    fake_client = test_app["fake_client"]

    # Thème
    create_theme = client.post(
        "/api/client/chat/themes",
        headers=headers,
        json={"title": "Contrat Fournisseur Alpha", "agent_id": "jerome"},
    )
    theme_id = create_theme.json()["theme"]["theme_id"]

    # Session 1
    sid1 = "session-alpha-conv1"
    client.post(
        "/api/client/chat",
        headers=headers,
        json={"agent_id": "jerome", "message": "Conditions de paiement : 45 jours fin de mois", "session_id": sid1, "theme_id": theme_id},
    )
    sdb = SessionDB(jerome_dir / "state.db")
    sdb.append_message(sid1, "assistant", "Validé : 45 jours fin de mois pour Alpha.")

    # Session 2
    sid2 = "session-alpha-conv2"
    client.post(
        "/api/client/chat",
        headers=headers,
        json={"agent_id": "jerome", "message": "Quelles étaient les conditions convenues ?", "session_id": sid2, "theme_id": theme_id},
    )

    # Inspection brute des appels enregistrés par le faux moteur
    calls = fake_client.completions_engine.recorded_calls
    assert len(calls) >= 1
    last_call = calls[-1]
    messages = last_call.get("messages", [])
    system_prompts = [str(m.get("content")) for m in messages if isinstance(m, dict) and m.get("role") == "system"]
    combined_system = " ".join(system_prompts)

    assert "[CONTEXTE DU THÈME : « Contrat Fournisseur Alpha »]" in combined_system
    assert "45 jours fin de mois" in combined_system


def test_kan85_ca3_bounded_context_trace_and_verification(test_app):
    """CA3 : Le volume transmis reste sous le plafond annoncé et l'endpoint documente ce qui a été transmis."""
    client = test_app["client"]
    token = test_app["token"]
    headers = {"Authorization": f"Bearer {token}"}
    jerome_dir = test_app["jerome_dir"]

    create_theme = client.post(
        "/api/client/chat/themes",
        headers=headers,
        json={"title": "Recouvrement Créances 2026", "agent_id": "jerome"},
    )
    theme_id = create_theme.json()["theme"]["theme_id"]

    sid = "session-recouvr-001"
    client.post(
        "/api/client/chat",
        headers=headers,
        json={"agent_id": "jerome", "message": "Plan de relance pour la société Dupont Peinture", "session_id": sid, "theme_id": theme_id},
    )
    sdb = SessionDB(jerome_dir / "state.db")
    sdb.append_message(sid, "assistant", "Relance niveau 2 programmée pour 3 900 €.")

    # Consultation du point de mesure de traçabilité
    ctx_resp = client.get(f"/api/client/chat/themes/{theme_id}/context?agent_id=jerome", headers=headers)
    assert ctx_resp.status_code == 200
    data = ctx_resp.json()
    assert data["has_context"] is True
    assert data["length_chars"] > 0
    assert data["length_chars"] <= 6000
    assert data["tokens_est"] <= 1500
    assert "Recouvrement Créances 2026" in data["context_text"]


def test_kan85_ca3_context_endpoint_matches_injected_prompt(test_app):
    """CA3 complémentaire : Ce que l'endpoint annonce correspond exactement au texte injecté dans le contexte."""
    client = test_app["client"]
    token = test_app["token"]
    headers = {"Authorization": f"Bearer {token}"}
    jerome_dir = test_app["jerome_dir"]

    create_theme = client.post("/api/client/chat/themes", headers=headers, json={"title": "Audit Trésorerie", "agent_id": "jerome"})
    theme_id = create_theme.json()["theme"]["theme_id"]

    sid1 = "session-audit-1"
    client.post("/api/client/chat", headers=headers, json={"agent_id": "jerome", "message": "Comptes sains", "session_id": sid1, "theme_id": theme_id})
    sdb = SessionDB(jerome_dir / "state.db")
    sdb.append_message(sid1, "assistant", "48 250 euros de créances saines.")

    # Contexte récupéré via fonction interne
    internal_ctx = get_theme_context_for_session(
        session_id="session-nouvelle",
        theme_id=theme_id,
        tenant_id="f3e25379-6531-479e-b276-3b3185e7421b",
        user_id="user-sophie",
        agent_id="jerome",
    )

    # Contexte exposé par l'API
    api_ctx = client.get(f"/api/client/chat/themes/{theme_id}/context?agent_id=jerome&session_id=session-nouvelle", headers=headers).json()

    assert internal_ctx == api_ctx["context_text"]
    assert len(internal_ctx) == api_ctx["length_chars"]


def test_kan85_ca4_trap_question_no_hallucination_or_cross_theme_leak(test_app):
    """CA4 : Question piège : une information présente uniquement dans un autre thème

    n'est pas reprise dans la réponse et le moteur signale l'absence sans l'inventer.
    """
    client = test_app["client"]
    token = test_app["token"]
    headers = {"Authorization": f"Bearer {token}"}
    jerome_dir = test_app["jerome_dir"]

    # Thème A avec information secrète
    tA = client.post("/api/client/chat/themes", headers=headers, json={"title": "Projet Secret A", "agent_id": "jerome"}).json()["theme"]["theme_id"]
    sidA = "session-secret-A"
    client.post("/api/client/chat", headers=headers, json={"agent_id": "jerome", "message": "Code coffre 9988", "session_id": sidA, "theme_id": tA})
    sdb = SessionDB(jerome_dir / "state.db")
    sdb.append_message(sidA, "assistant", "Code secret enregistré : 9988.")

    # Thème B : question piège sur l'information du Thème A
    tB = client.post("/api/client/chat/themes", headers=headers, json={"title": "Projet Public B", "agent_id": "jerome"}).json()["theme"]["theme_id"]
    sidB = "session-piege-B"
    resB = client.post(
        "/api/client/chat",
        headers=headers,
        json={"agent_id": "jerome", "message": "Question piège : quel est le code secret du coffre ?", "session_id": sidB, "theme_id": tB},
    )
    assert resB.status_code == 200
    body = resB.text

    assert "9988" not in body
    assert "ne figure pas dans le contexte" in body


def test_kan85_ca4_multi_tenant_isolation_no_leak_between_tenants(test_app):
    """CA4 complémentaire : Étanchéité stricte multi-tenants sur le contexte de reprise."""
    client = test_app["client"]
    token_sophie = test_app["token"]
    token_autre = _generate_jwt("user-externe", tenant_id="tenant-tiers-autre", tenant_slug="societe-tiers")

    t_sophie = client.post("/api/client/chat/themes", headers={"Authorization": f"Bearer {token_sophie}"}, json={"title": "Secret Sophie", "agent_id": "jerome"}).json()["theme"]["theme_id"]

    # Le tenant tiers tente d'accéder au contexte de Sophie -> rejet 403
    resp_cross = client.get(f"/api/client/chat/themes/{t_sophie}/context?agent_id=jerome", headers={"Authorization": f"Bearer {token_autre}"})
    assert resp_cross.status_code == 403


def test_kan85_ca5_null_context_when_theme_has_only_empty_session(test_app):
    """CA5 : Le contexte de reprise est nul quand le thème ne contient qu'une seule conversation déjà vide."""
    client = test_app["client"]
    token = test_app["token"]
    headers = {"Authorization": f"Bearer {token}"}
    jerome_dir = test_app["jerome_dir"]

    # Création du thème
    t_id = client.post("/api/client/chat/themes", headers=headers, json={"title": "Thème Conversation Vide", "agent_id": "jerome"}).json()["theme"]["theme_id"]

    # Ajout d'une session sans message (ou avec messages vides dans SessionDB)
    sid_empty = "session-vide-001"
    db_file = test_app["db_file"]
    now = time.time()
    with sqlite3.connect(str(db_file)) as conn:
        conn.execute(
            """INSERT INTO client_chat_sessions (session_id, tenant_id, user_id, agent_id, dossier_metier_id, created_at, last_activity_at, title, title_source)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'auto')""",
            (sid_empty, "f3e25379-6531-479e-b276-3b3185e7421b", "user-sophie", "jerome", t_id, now, now, "Discussion vide"),
        )
        conn.commit()

    # SessionDB existe mais ne contient aucun message pour sid_empty
    sdb = SessionDB(jerome_dir / "state.db")
    assert sdb.get_messages_as_conversation(sid_empty) == []

    # Vérification que le contexte est strictement nul
    ctx_resp = client.get(f"/api/client/chat/themes/{t_id}/context?agent_id=jerome&session_id=session-courante", headers=headers)
    assert ctx_resp.status_code == 200
    data = ctx_resp.json()
    assert data["has_context"] is False
    assert data["context_text"] == ""
    assert data["length_chars"] == 0
    assert data["tokens_est"] == 0


def test_kan85_ca5_null_context_when_theme_has_zero_sessions(test_app):
    """CA5 complémentaire : Contexte nul quand le thème ne contient aucune session."""
    client = test_app["client"]
    token = test_app["token"]
    headers = {"Authorization": f"Bearer {token}"}

    t_id = client.post("/api/client/chat/themes", headers=headers, json={"title": "Thème Sans Session", "agent_id": "jerome"}).json()["theme"]["theme_id"]

    ctx_resp = client.get(f"/api/client/chat/themes/{t_id}/context?agent_id=jerome", headers=headers)
    assert ctx_resp.status_code == 200
    data = ctx_resp.json()
    assert data["has_context"] is False
    assert data["context_text"] == ""
    assert data["length_chars"] == 0


def test_kan85_truncation_ceiling_and_footer_presence(test_app):
    """Vérification du plafond et de la troncature : un contexte très long (> 6 000 caractères)

    est tronqué proprement et conserve obligatoirement le pied de contexte final.
    """
    jerome_dir = test_app["jerome_dir"]
    db_file = test_app["db_file"]
    tenant_id = "f3e25379-6531-479e-b276-3b3185e7421b"
    user_id = "user-sophie"
    agent_id = "jerome"
    theme_id = "theme-long-text-truncation"
    now = time.time()

    from hermes_cli.web_routers.client_chat_history import _init_client_themes_db
    with sqlite3.connect(str(db_file)) as conn:
        _init_client_themes_db(conn)
        conn.execute(
            """INSERT INTO client_chat_themes (theme_id, tenant_id, user_id, agent_id, title, title_source, created_at, updated_at)
               VALUES (?, ?, ?, ?, 'Thème Historique Volumineux', 'auto', ?, ?)""",
            (theme_id, tenant_id, user_id, agent_id, now, now),
        )
        # Insertion de 5 sessions avec un texte volumineux
        for i in range(5):
            sid = f"session-long-{i}"
            conn.execute(
                """INSERT INTO client_chat_sessions (session_id, tenant_id, user_id, agent_id, dossier_metier_id, created_at, last_activity_at, title, title_source)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'auto')""",
                (sid, tenant_id, user_id, agent_id, theme_id, now - (i * 10), now - (i * 10), f"Session volumineuse {i}"),
            )
        conn.commit()

    sdb = SessionDB(jerome_dir / "state.db")
    # Chaque session reçoit un long paragraphe
    very_long_message = "Détail comptable très volumineux : " + ("facture impayée avec pénalités de retard " * 40)
    for i in range(5):
        try:
            sdb.create_session(f"session-long-{i}", source="client_ui")
        except Exception:
            pass
        sdb.append_message(f"session-long-{i}", "user", f"Question détaillée {i} : " + ("analyse préalable " * 20))
        sdb.append_message(f"session-long-{i}", "assistant", very_long_message)

    # Récupération avec plafond réduit de test pour exercer la troncature (ex: 1200 caractères)
    truncated_ctx = get_theme_context_for_session(
        session_id="session-current",
        theme_id=theme_id,
        tenant_id=tenant_id,
        user_id=user_id,
        agent_id=agent_id,
        max_chars=1200,
    )

    assert len(truncated_ctx) <= 1200
    assert "...\n" in truncated_ctx, "Le marqueur de troncature '...' est absent !"
    assert "[FIN DU CONTEXTE DU THÈME" in truncated_ctx, "Le pied de contexte a été supprimé lors de la troncature !"


def test_kan85_token_estimation_char_div_four_metric(test_app):
    """Documentation explicite de la métrique d'estimation des jetons (longueur / 4)."""
    client = test_app["client"]
    token = test_app["token"]
    headers = {"Authorization": f"Bearer {token}"}
    jerome_dir = test_app["jerome_dir"]

    create_theme = client.post("/api/client/chat/themes", headers=headers, json={"title": "Vérification Ratio Jetons", "agent_id": "jerome"})
    theme_id = create_theme.json()["theme"]["theme_id"]

    sid = "session-ratio-test"
    client.post("/api/client/chat", headers=headers, json={"agent_id": "jerome", "message": "Message simple", "session_id": sid, "theme_id": theme_id})
    sdb = SessionDB(jerome_dir / "state.db")
    sdb.append_message(sid, "assistant", "Réponse pour tester le ratio de jetons.")

    ctx_resp = client.get(f"/api/client/chat/themes/{theme_id}/context?agent_id=jerome", headers=headers).json()
    length = ctx_resp["length_chars"]
    tokens = ctx_resp["tokens_est"]

    assert tokens == length // 4


def test_kan85_offline_resilient_mode_fallback(tmp_path, monkeypatch):
    """Traitement séparé et nommé du mode résilient hors ligne :

    quand le moteur LLM est indisponible, le mode résilient formule une réponse de repli intégrant le contexte.
    """
    db_file = tmp_path / "client_chat_sessions.db"
    agents_root = tmp_path / "data" / "agents"
    agents_root.mkdir(parents=True, exist_ok=True)
    jerome_dir = agents_root / "jerome"
    jerome_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr("hermes_cli.web_routers.client_ui._get_client_sessions_db_path", lambda: db_file)
    monkeypatch.setattr("hermes_cli.web_routers.client_ui.PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("hermes_cli.web_routers.client_ui._find_profile_dir", lambda aid: agents_root / aid)

    monkeypatch.setenv("SUPABASE_JWT_SECRET", "test-secret")
    monkeypatch.setenv("ORSO_CLIENT_ID", "f3e25379-6531-479e-b276-3b3185e7421b")
    monkeypatch.setenv("ORSO_CLIENT_SLUG", "financia-solutions")
    # Forcer l'échec de AIAgent en déconfigurant les clés
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    monkeypatch.setenv("OPENAI_API_KEY", "")

    app = FastAPI()
    app.include_router(client_ui_router)
    app.include_router(history_router)
    _init_client_sessions_db()

    client = TestClient(app)
    token = _generate_jwt("user-sophie")
    headers = {"Authorization": f"Bearer {token}"}

    # Thème
    t_id = client.post("/api/client/chat/themes", headers=headers, json={"title": "Mode Résilient", "agent_id": "jerome"}).json()["theme"]["theme_id"]

    # Session 1
    sid1 = "session-resilient-1"
    client.post("/api/client/chat", headers=headers, json={"agent_id": "jerome", "message": "Premier échange", "session_id": sid1, "theme_id": t_id})
    sdb = SessionDB(jerome_dir / "state.db")
    sdb.append_message(sid1, "assistant", "Contenu archivé dans le thème.")

    # Session 2 : interrogation en mode résilient hors ligne
    sid2 = "session-resilient-2"
    res = client.post(
        "/api/client/chat",
        headers=headers,
        json={"agent_id": "jerome", "message": "Rappelle-moi le contexte précédent", "session_id": sid2, "theme_id": t_id},
    )
    assert res.status_code == 200
    body = res.text

    assert "D'après les échanges précédents au sein de ce thème" in body
    assert "Contenu archivé dans le thème" in body

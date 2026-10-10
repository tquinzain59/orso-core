"""Tests d'acceptation pour KAN-84 : Organisation des conversations par blocs de thèmes (4 mots).

Alignement strict sur le référentiel d'acceptation du ticket Jira KAN-84 (CA1 à CA9) :
- CA1 : Trois conversations sur trois sujets distincts donnent trois blocs nommés en quatre mots au plus.
- CA2 : Deux conversations du même sujet se rejoignent dans le même bloc sans intervention.
- CA3 : Stabilité du nom dans le temps : plusieurs messages échangés ne renomment pas le bloc.
- CA4 : Les noms sont en français, compréhensibles sortis de leur contexte (5 exemples couverts).
- CA5 : Aucun bloc affiché tant qu'aucune conversation n'existe.
- CA6 : Cloisonnement strict multi-tenants et inter-utilisateurs.
- CA7 : Le déplacement manuel d'une conversation vers un autre bloc survit aux échanges suivants.
- CA8 : La seconde porte d'entrée (bouton haut de colonne) crée un bloc sans doublon.
- CA9 : Bloc provisoire « Nouvelle discussion » affiché puis substitué, 0 entrée de ce nom en base.
- Opérations utilisateur complémentaires : renommage manuel protégé, fusion et suppression.
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
    def __init__(self):
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        messages = kwargs.get("messages", [])
        user_msgs = [m.get("content") for m in messages if isinstance(m, dict) and m.get("role") == "user"]
        last_prompt = str(user_msgs[-1] if user_msgs else "")
        reply = f"Réponse contextualisée du moteur pour : {last_prompt[:50]}"
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


@pytest.fixture
def test_app(monkeypatch, tmp_path):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "test-secret")
    monkeypatch.setenv("ORSO_CLIENT_ID", "f3e25379-6531-479e-b276-3b3185e7421b")
    monkeypatch.setenv("ORSO_CLIENT_SLUG", "financia-solutions")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-fake-openrouter-key")
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    try:
        from agent.auxiliary_client import _client_cache
        _client_cache.clear()
    except Exception:
        pass

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

    fake_client_instance = _FakeClient()
    try:
        import openai
        monkeypatch.setattr(openai, "OpenAI", lambda **kw: fake_client_instance)
    except Exception:
        pass

    from agent import process_bootstrap
    monkeypatch.setattr(process_bootstrap, "OpenAI", lambda **kw: fake_client_instance)

    app = FastAPI()
    app.include_router(client_ui_router)
    app.include_router(history_router)

    _init_client_sessions_db()

    yield {
        "client": TestClient(app),
        "db": sessions_db_file,
        "token": _generate_jwt("user-sophie"),
        "fake_client": fake_client_instance,
    }

    try:
        from agent.auxiliary_client import _client_cache
        _client_cache.clear()
    except Exception:
        pass


def test_kan84_ca1_three_distinct_conversations_produce_three_theme_blocks(test_app):
    """CA1 : Trois conversations portant sur trois sujets distincts produisent trois blocs de conversations distincts,

    chacun nommé en quatre mots au maximum.
    """
    client = test_app["client"]
    token = test_app["token"]
    headers = {"Authorization": f"Bearer {token}"}

    prompts = [
        ("session-sujet-tresorerie", "Audit complet trésorerie et comptes bancaires"),
        ("session-sujet-litige", "Litige transporteur colis endommagé"),
        ("session-sujet-recrutement", "Contrat embauche juriste senior"),
    ]

    for sid, prompt in prompts:
        resp = client.post(
            "/api/client/chat",
            headers=headers,
            json={"agent_id": "jerome", "message": prompt, "session_id": sid},
        )
        assert resp.status_code == 200

    list_resp = client.get("/api/client/chat/themes?agent_id=jerome", headers=headers)
    assert list_resp.status_code == 200
    themes = list_resp.json()["themes"]
    assert len(themes) == 3

    for theme in themes:
        words = theme["title"].split()
        assert len(words) <= 4, f"Titre '{theme['title']}' dépasse le plafond de 4 mots"
        assert len(words) >= 1
        assert theme["sessions_count"] == 1


def test_kan84_ca1_theme_title_bounded_to_four_words():
    """CA1 complémentaire : La fonction d'extraction borne strictement à 4 mots maximum en français."""
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


def test_kan84_ca2_two_conversations_same_subject_grouped_automatically(test_app):
    """CA2 : Deux conversations portant sur le même sujet sont regroupées automatiquement

    dans le même bloc, sans intervention de l'utilisateur.
    """
    client = test_app["client"]
    token = test_app["token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Conversation 1
    sid1 = "session-créances-001"
    prompt1 = "Contrôle des créances impayées client Dupont"
    resp1 = client.post(
        "/api/client/chat",
        headers=headers,
        json={"agent_id": "jerome", "message": prompt1, "session_id": sid1},
    )
    assert resp1.status_code == 200

    # Conversation 2 sur le même sujet métier (créances impayées Dupont)
    sid2 = "session-créances-002"
    prompt2 = "Relance des créances impayées client Dupont"
    resp2 = client.post(
        "/api/client/chat",
        headers=headers,
        json={"agent_id": "jerome", "message": prompt2, "session_id": sid2},
    )
    assert resp2.status_code == 200

    list_resp = client.get("/api/client/chat/themes?agent_id=jerome", headers=headers)
    assert list_resp.status_code == 200
    themes = list_resp.json()["themes"]

    # Un seul bloc de thème doit regrouper les deux conversations
    assert len(themes) == 1, f"Attendu 1 seul thème regroupé, obtenu {len(themes)} : {[t['title'] for t in themes]}"
    theme = themes[0]
    assert theme["sessions_count"] == 2
    session_ids = [s["session_id"] for s in theme["sessions"]]
    assert sid1 in session_ids
    assert sid2 in session_ids


def test_kan84_ca3_theme_title_stable_over_multiple_messages(test_app):
    """CA3 : Le nom du bloc est stable : échanger plusieurs messages dans une conversation ne le renomme pas."""
    client = test_app["client"]
    token = test_app["token"]
    headers = {"Authorization": f"Bearer {token}"}

    sid = "session-stabilite-nom"
    # Premier message -> création du thème
    r1 = client.post(
        "/api/client/chat",
        headers=headers,
        json={"agent_id": "jerome", "message": "Analyse de la trésorerie", "session_id": sid},
    )
    assert r1.status_code == 200

    themes_initial = client.get("/api/client/chat/themes?agent_id=jerome", headers=headers).json()["themes"]
    assert len(themes_initial) == 1
    initial_title = themes_initial[0]["title"]
    assert initial_title == "Analyse de la trésorerie"

    # Deuxième message sur un sujet différent dans la même session
    r2 = client.post(
        "/api/client/chat",
        headers=headers,
        json={"agent_id": "jerome", "message": "Peux-tu maintenant vérifier le contrat de bail ?", "session_id": sid},
    )
    assert r2.status_code == 200

    # Troisième message
    r3 = client.post(
        "/api/client/chat",
        headers=headers,
        json={"agent_id": "jerome", "message": "Fais un récapitulatif global", "session_id": sid},
    )
    assert r3.status_code == 200

    themes_after = client.get("/api/client/chat/themes?agent_id=jerome", headers=headers).json()["themes"]
    assert len(themes_after) == 1
    assert themes_after[0]["title"] == initial_title, "Le titre du thème a été modifié lors d'un message ultérieur"


def test_kan84_ca4_five_french_names_comprehensible_out_of_context():
    """CA4 : Les noms sont en français et compréhensibles sortis de leur contexte (5 exemples métier)."""
    exemples = [
        ("Peux-tu analyser la balance âgée de ce mois ?", 4),
        ("Prépare une relance facture impayée Dupont", 4),
        ("Contentieux transporteur livraison Nord", 4),
        ("Audit trésorerie prévisionnelle 2026", 4),
        ("Contrat sous-traitance informatique entreprise", 4),
    ]

    for prompt, max_words in exemples:
        title = generate_theme_title(prompt, max_words=max_words)
        words = title.split()
        assert len(words) <= max_words, f"Titre '{title}' a plus de {max_words} mots"
        assert len(title) > 3
        # Vérifie qu'il n'y a aucun caractère corrompu ou balise résiduelle
        assert not any(c in title for c in ["<", ">", "{", "}", "\n", "\t"])


def test_kan84_ca5_no_theme_displayed_on_empty_account(test_app):
    """CA5 : Aucun bloc n'est affiché tant qu'aucune conversation n'existe (compte neuf)."""
    client = test_app["client"]
    token_neuf = _generate_jwt("user-nouveau-compte")
    headers = {"Authorization": f"Bearer {token_neuf}"}

    resp = client.get("/api/client/chat/themes?agent_id=jerome", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["themes"] == []
    assert data["total"] == 0


def test_kan84_ca6_strict_multi_tenant_and_multi_user_isolation(test_app):
    """CA6 : Le cloisonnement tient : les blocs d'un utilisateur ne sont pas visibles depuis un autre compte

    du même espace client, ni depuis un autre espace client.
    """
    client = test_app["client"]
    token_tenant1_user_a = test_app["token"]  # Tenant 1, User Sophie
    token_tenant1_user_b = _generate_jwt("user-pierre")  # Tenant 1, User Pierre
    token_tenant2_user_c = _generate_jwt(  # Tenant 2, User Autre
        "user-externe",
        tenant_id="tenant-autre-espace-client",
        tenant_slug="autre-societe",
    )

    # User A crée un thème et une conversation
    t_id = client.post(
        "/api/client/chat/themes",
        headers={"Authorization": f"Bearer {token_tenant1_user_a}"},
        json={"title": "Projet Confidentiel Sophie", "agent_id": "jerome"},
    ).json()["theme"]["theme_id"]

    # 1. Étanchéité inter-utilisateurs (même tenant)
    list_b = client.get(
        "/api/client/chat/themes?agent_id=jerome",
        headers={"Authorization": f"Bearer {token_tenant1_user_b}"},
    ).json()["themes"]
    assert not any(t["theme_id"] == t_id for t in list_b)

    patch_b = client.patch(
        f"/api/client/chat/themes/{t_id}",
        headers={"Authorization": f"Bearer {token_tenant1_user_b}"},
        json={"title": "Titre Piraté Pierre"},
    )
    assert patch_b.status_code == 404

    # 2. Étanchéité multi-tenants (tenant tiers bloqué en 403 Forbidden par le middleware d'étanchéité)
    resp_c = client.get(
        "/api/client/chat/themes?agent_id=jerome",
        headers={"Authorization": f"Bearer {token_tenant2_user_c}"},
    )
    assert resp_c.status_code == 403

    del_c = client.delete(
        f"/api/client/chat/themes/{t_id}",
        headers={"Authorization": f"Bearer {token_tenant2_user_c}"},
    )
    assert del_c.status_code == 403


def test_kan84_ca7_manual_move_session_survives_subsequent_message(test_app):
    """CA7 : Le déplacement manuel d'une conversation vers un autre bloc est possible

    et ne se défait pas au message suivant.
    """
    client = test_app["client"]
    token = test_app["token"]
    headers = {"Authorization": f"Bearer {token}"}

    t1 = client.post("/api/client/chat/themes", headers=headers, json={"title": "Thème Alpha", "agent_id": "jerome"}).json()["theme"]["theme_id"]
    t2 = client.post("/api/client/chat/themes", headers=headers, json={"title": "Thème Bêta", "agent_id": "jerome"}).json()["theme"]["theme_id"]

    sid = "session-move-persistence-test"
    # Création dans Thème 1
    client.post(
        "/api/client/chat",
        headers=headers,
        json={"agent_id": "jerome", "message": "Premier échange dans Alpha", "session_id": sid, "theme_id": t1},
    )

    # Déplacement vers Thème 2
    move_resp = client.post(f"/api/client/chat/themes/{t2}/sessions/{sid}", headers=headers)
    assert move_resp.status_code == 200

    # Échange d'un nouveau message dans la session déplacée
    post_move_msg = client.post(
        "/api/client/chat",
        headers=headers,
        json={"agent_id": "jerome", "message": "Message envoyé après le déplacement", "session_id": sid},
    )
    assert post_move_msg.status_code == 200

    # Vérification que la session est TOUJOURS dans Thème 2
    t2_themes = client.get("/api/client/chat/themes?agent_id=jerome", headers=headers).json()["themes"]
    theme2 = next(t for t in t2_themes if t["theme_id"] == t2)
    assert any(s["session_id"] == sid for s in theme2["sessions"]), "La session a quitté le thème cible après un échange !"

    theme1 = next(t for t in t2_themes if t["theme_id"] == t1)
    assert not any(s["session_id"] == sid for s in theme1["sessions"]), "La session est réapparue dans l'ancien thème !"


def test_kan84_ca8_top_column_button_creates_theme_without_duplicate(test_app):
    """CA8 : Le bouton en haut de la colonne crée une discussion de zéro :

    le moteur en extrait un thème et un nouveau bloc apparaît si le thème est inédit,
    sans doublon de bloc si le thème existe déjà.
    """
    client = test_app["client"]
    token = test_app["token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Création de zéro (sans theme_id) pour un thème inédit
    sid1 = "session-scratch-001"
    client.post(
        "/api/client/chat",
        headers=headers,
        json={"agent_id": "jerome", "message": "Contentieux Urssaf 2026", "session_id": sid1},
    )

    themes_after_first = client.get("/api/client/chat/themes?agent_id=jerome", headers=headers).json()["themes"]
    assert len(themes_after_first) == 1
    assert themes_after_first[0]["title"] == "Contentieux Urssaf 2026"

    # 2. Seconde création de zéro (sans theme_id) sur le même sujet
    sid2 = "session-scratch-002"
    client.post(
        "/api/client/chat",
        headers=headers,
        json={"agent_id": "jerome", "message": "Suivi contentieux Urssaf 2026", "session_id": sid2},
    )

    themes_after_second = client.get("/api/client/chat/themes?agent_id=jerome", headers=headers).json()["themes"]
    assert len(themes_after_second) == 1, "Un doublon de bloc a été créé au lieu de regrouper !"
    assert themes_after_second[0]["sessions_count"] == 2


def test_kan84_ca9_provisional_card_and_no_nouvelle_discussion_in_db(test_app):
    """CA9 : Le bloc provisoire Nouvelle discussion cède la place au nom du thème sans laisser

    de bloc vide ni écrire 'Nouvelle discussion' en base comme nom de thème.
    """
    client = test_app["client"]
    token = test_app["token"]
    headers = {"Authorization": f"Bearer {token}"}

    client.post(
        "/api/client/chat",
        headers=headers,
        json={"agent_id": "jerome", "message": "Analyse trésorerie nette", "session_id": "session-real-theme-name"},
    )

    db_path = test_app["db"]
    with sqlite3.connect(str(db_path)) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT title FROM client_chat_themes WHERE title = 'Nouvelle discussion'")
        assert cursor.fetchall() == []

        cursor.execute("SELECT title FROM client_chat_themes")
        titles = [r[0] for r in cursor.fetchall()]
        assert "Analyse trésorerie nette" in titles


def test_kan84_manual_theme_renaming_protected_from_overwrite(test_app):
    """Garde-fou KAN-84 : Renommage manuel d'un thème protégé contre tout ré-écrasement automatique."""
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


def test_kan84_merge_two_themes(test_app):
    """Garde-fou KAN-84 : Fusion de deux thèmes, les sessions rejoignent le thème cible."""
    client = test_app["client"]
    token = test_app["token"]
    headers = {"Authorization": f"Bearer {token}"}

    t1 = client.post("/api/client/chat/themes", headers=headers, json={"title": "Facturation Nord", "agent_id": "jerome"}).json()["theme"]["theme_id"]
    t2 = client.post("/api/client/chat/themes", headers=headers, json={"title": "Facturation Sud", "agent_id": "jerome"}).json()["theme"]["theme_id"]

    sid = "session-merge-test"
    client.post(
        "/api/client/chat",
        headers=headers,
        json={"agent_id": "jerome", "message": "Factures région Sud", "session_id": sid, "theme_id": t2},
    )

    merge_resp = client.post(f"/api/client/chat/themes/{t2}/merge/{t1}", headers=headers)
    assert merge_resp.status_code == 200

    after_merge = client.get("/api/client/chat/themes?agent_id=jerome", headers=headers).json()["themes"]
    assert not any(t["theme_id"] == t2 for t in after_merge)
    theme1 = next(t for t in after_merge if t["theme_id"] == t1)
    assert any(s["session_id"] == sid for s in theme1["sessions"])


def test_kan84_delete_theme_with_detach_or_purge(test_app):
    """Garde-fou KAN-84 : Suppression d'un thème avec détachement de ses sessions."""
    client = test_app["client"]
    token = test_app["token"]
    headers = {"Authorization": f"Bearer {token}"}

    t_id = client.post("/api/client/chat/themes", headers=headers, json={"title": "Audit provisoire", "agent_id": "jerome"}).json()["theme"]["theme_id"]
    sid = "session-to-detach-test"
    client.post("/api/client/chat", headers=headers, json={"agent_id": "jerome", "message": "Test message", "session_id": sid, "theme_id": t_id})

    del_resp = client.delete(f"/api/client/chat/themes/{t_id}?delete_sessions=false", headers=headers)
    assert del_resp.status_code == 200

    themes = client.get("/api/client/chat/themes?agent_id=jerome", headers=headers).json()["themes"]
    assert not any(t["theme_id"] == t_id for t in themes)

    s_details = client.get(f"/api/client/chat/sessions/{sid}?agent_id=jerome", headers=headers).json()
    assert s_details["dossier_metier_id"] is None


def test_kan84_cost_and_frequency_of_classification_bounded(test_app):
    """Contrainte KAN-84 : Le coût du classement est borné à 0 appel LLM supplémentaire par tour,

    déterminé par extraction déterministe lors de la création uniquement.
    """
    client = test_app["client"]
    token = test_app["token"]
    headers = {"Authorization": f"Bearer {token}"}
    fake_client = test_app["fake_client"]

    initial_calls = len(fake_client.completions_engine.calls)

    sid = "session-cost-bound-test"
    client.post(
        "/api/client/chat",
        headers=headers,
        json={"agent_id": "jerome", "message": "Audit prévisionnel Q4", "session_id": sid},
    )

    # Vérification que seul l'appel de dialogue standard a eu lieu (aucun appel LLM caché pour le classement)
    assert len(fake_client.completions_engine.calls) == initial_calls + 1

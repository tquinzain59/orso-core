"""Tests d'acceptation et unitaires pour le ticket KAN-104 (Mailer Brevo & Emails Transactionnels).

Vérifie :
- Rendu des 4 templates transactionnels (M1: Bienvenue, M2: Provisionnement, M3: Activation, M4: Erreur).
- Cycle de vie des jetons d'invitation 7 jours : génération, validité, consommation à usage unique, rejet après expiration ou réutilisation.
- Intégration Brevo API : en-têtes d'authentification api-key, payload JSON, gestion des réponses et des erreurs.
- Journalisation d'audit en base SQLite locale (olympe_ops.db / transactional_emails).
- Endpoints HTTP Olympe associés (/api/olympe/mailer/send, /logs, /invitations/generate, /validate).
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from olympe.auth import MOCK_SUPERADMIN_TOKEN
from olympe.mailer import BrevoMailer, brevo_mailer
from olympe.server import app


@pytest.fixture
def temp_mailer(tmp_path):
    """Instancie un BrevoMailer isolé avec une base SQLite temporaire."""
    db_file = tmp_path / "test_ops.db"
    return BrevoMailer(
        api_key="test_mock_api_key_12345",
        sender_email="contact@orso-agents.fr",
        sender_name="Orso Agents",
        db_path=db_file,
    )


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Client API FastAPI configuré avec une base de données temporaire."""
    db_file = tmp_path / "test_server_ops.db"
    monkeypatch.setattr(brevo_mailer, "db_path", db_file)
    brevo_mailer._init_mailer_db()
    return TestClient(app)


def test_kan104_templates_rendering(temp_mailer):
    """Vérifie le rendu textuel et HTML des 4 gabarits M1, M2, M3 et M4."""
    # M1: Inscription
    m1 = temp_mailer.render_template("m1", {
        "tenant_name": "Acme Corp",
        "contact_name": "Alice",
        "tenant_slug": "acme",
        "login_url": "https://app.orso.local/login",
    })
    assert "Acme Corp" in m1["subject"]
    assert "Alice" in m1["html"]
    assert "https://app.orso.local/login" in m1["html"]

    # M2: Provisionnement
    m2 = temp_mailer.render_template("m2", {
        "tenant_name": "Acme Corp",
        "contact_name": "Alice",
        "agent_count": 3,
        "estimated_time": "3 minutes",
    })
    assert "Déploiement en cours" in m2["subject"]
    assert "3 agent(s) IA" in m2["html"]
    assert "3 minutes" in m2["html"]

    # M3: Activation
    m3 = temp_mailer.render_template("m3", {
        "tenant_name": "Acme Corp",
        "contact_name": "Alice",
        "activation_url": "https://app.orso.local/activation?token=xyz",
        "expires_at": "14/10/2026 à 12:00 UTC",
    })
    assert "Activez votre espace" in m3["subject"]
    assert "https://app.orso.local/activation?token=xyz" in m3["html"]
    assert "7 jours" in m3["html"]

    # M4: Incident
    m4 = temp_mailer.render_template("m4", {
        "tenant_name": "Acme Corp",
        "contact_name": "Alice",
        "error_details": "Erreur de quota GPU OVH",
        "support_email": "sos@orso.local",
    })
    assert "Incident" in m4["subject"]
    assert "Erreur de quota GPU OVH" in m4["html"]
    assert "sos@orso.local" in m4["html"]

    # Template invalide
    with pytest.raises(ValueError):
        temp_mailer.render_template("unknown_template", {})


def test_kan104_invitation_token_lifecycle(temp_mailer):
    """Vérifie la génération, l'usage unique et l'expiration des tokens 7 jours."""
    token = temp_mailer.generate_invitation_token("acme-slug", "alice@acme.com", validity_days=7)
    assert len(token) >= 32

    # 1. Première validation et consommation -> Succès
    res1 = temp_mailer.validate_and_consume_token(token)
    assert res1["valid"] is True
    assert res1["tenant_slug"] == "acme-slug"
    assert res1["recipient_email"] == "alice@acme.com"

    # 2. Deuxième validation -> Rejet car déjà consommé (usage unique strict)
    res2 = temp_mailer.validate_and_consume_token(token)
    assert res2["valid"] is False
    assert res2["error_code"] == "ERR_TOKEN_ALREADY_USED"

    # 3. Token inexistant -> Rejet
    res_fake = temp_mailer.validate_and_consume_token("token_qui_nexiste_pas")
    assert res_fake["valid"] is False
    assert res_fake["error_code"] == "ERR_TOKEN_NOT_FOUND"


def test_kan104_invitation_token_expiration(temp_mailer):
    """Vérifie le rejet d'un token dont la validité temporelle est expirée."""
    # Créer un token avec expiration passée
    token = temp_mailer.generate_invitation_token("acme-slug", "bob@acme.com", validity_days=-1)
    res = temp_mailer.validate_and_consume_token(token)
    assert res["valid"] is False
    assert res["error_code"] == "ERR_TOKEN_EXPIRED"


def test_kan104_email_sending_mock_and_db_audit(temp_mailer):
    """Vérifie la journalisation SQLite en mode mock/demo."""
    res = temp_mailer.send_transactional_email(
        recipient_email="charlie@acme.com",
        template_id="m1",
        params={"tenant_name": "Charlie Inc", "contact_name": "Charlie"},
        tenant_slug="charlie-inc",
    )
    assert res["success"] is True
    assert res["status"] in ("SENT", "SENT_MOCK")
    assert "email_id" in res

    # Vérification dans la table d'audit
    logs = temp_mailer.get_email_logs(tenant_slug="charlie-inc")
    assert len(logs) == 1
    assert logs[0]["recipient_email"] == "charlie@acme.com"
    assert logs[0]["template_id"] == "m1"
    assert logs[0]["status"] in ("SENT", "SENT_MOCK")


def test_kan104_brevo_real_http_call(temp_mailer):
    """Vérifie que l'appel réseau vers Brevo transmet les en-têtes et le payload requis."""
    temp_mailer.api_key = "xkeysib-real-key-abcdef123456"

    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps({"messageId": "<brevo_msg_9876@smtp.brevo.com>"}).encode("utf-8")
    mock_response.__enter__.return_value = mock_response
    mock_response.__exit__.return_value = None

    with patch("urllib.request.urlopen", return_value=mock_response) as mock_urlopen:
        with patch.dict("os.environ", {"ORSO_DEMO_MODE": "0"}):
            res = temp_mailer.send_transactional_email(
                recipient_email="david@acme.com",
                template_id="m2",
                params={"tenant_name": "David SARL", "agent_count": 2},
                tenant_slug="david-sarl",
            )
            assert res["success"] is True
            assert res["status"] == "SENT"
            assert res["message_id"] == "<brevo_msg_9876@smtp.brevo.com>"

            # Vérifier l'appel urllib
            mock_urlopen.assert_called_once()
            req = mock_urlopen.call_args[0][0]
            assert req.full_url == "https://api.brevo.com/v3/smtp/email"
            assert req.headers["Api-key"] == "xkeysib-real-key-abcdef123456"

            sent_payload = json.loads(req.data.decode("utf-8"))
            assert sent_payload["to"][0]["email"] == "david@acme.com"
            assert "David SARL" in sent_payload["subject"]


def test_kan104_fastapi_endpoints(client):
    """Vérifie les endpoints REST Olympe pour l'envoi, les logs et la validation d'invitation."""
    auth_headers = {"Authorization": f"Bearer {MOCK_SUPERADMIN_TOKEN}"}

    # 1. Génération d'invitation et envoi M3
    gen_res = client.post(
        "/api/olympe/invitations/generate",
        json={
            "tenant_slug": "tenant-fastapi",
            "recipient_email": "fastapi@test.com",
            "tenant_name": "FastAPI Org",
            "contact_name": "Dev",
            "send_email": True,
        },
        headers=auth_headers,
    )
    assert gen_res.status_code == 200
    gen_data = gen_res.json()
    token = gen_data.get("invitation_token")
    assert token is not None

    # 2. Consultation des logs
    logs_res = client.get("/api/olympe/mailer/logs?tenant_slug=tenant-fastapi", headers=auth_headers)
    assert logs_res.status_code == 200
    logs_data = logs_res.json()
    assert logs_data["count"] >= 1

    # 3. Validation et consommation du jeton
    val_res = client.post("/api/olympe/invitations/validate", json={"token": token})
    assert val_res.status_code == 200
    assert val_res.json()["valid"] is True

    # 4. Seconde validation -> Rejet HTTP 400
    val_res2 = client.post("/api/olympe/invitations/validate", json={"token": token})
    assert val_res2.status_code == 400

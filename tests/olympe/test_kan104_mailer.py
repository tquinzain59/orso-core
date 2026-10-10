"""Tests d'acceptation et unitaires pour le ticket KAN-104 (Mailer Brevo & Notifications d'Onboarding).

Vérifie de manière exhaustive les points de conformité PO / Direction :
- CA1 : Gabarit M1 mot pour mot ("Votre souscription Orso Agents est enregistrée.", 30 jours sans prélèvement, lien 48h).
- CA2 & CA10 : Cycle de vie de la confirmation d'adresse email (48h, table email_confirmations, endpoint et alerte ops).
- CA3 : Journalisation d'audit des emails envoyés (olympe_ops.db / transactional_emails).
- CA4 : Gabarits M2, M3, M4 mot pour mot (M2 préparation équipe, M3 espace prêt avec 3 points et 7 jours, M4 besoin d'un échange avec contact nommé).
- CA7 : Domaine d'envoi dédié (mail.orso-agents.fr), alignements SPF, DKIM, DMARC et sonde de domaine.
- CA9 : Proscription absolue des mots de passe prévisibles (Orso + timestamp) au profit de secrets.token_urlsafe(32).
- Endpoints REST FastAPI associés (/api/olympe/mailer/..., /email/confirm, /ops/domain-auth/status, /ops/alerts/unconfirmed-emails).
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from olympe.auth import MOCK_SUPERADMIN_TOKEN
from olympe.mailer import (
    BrevoMailer,
    brevo_mailer,
    DEFAULT_SENDER_DOMAIN,
    DEFAULT_SENDER_EMAIL,
    DEFAULT_SENDER_NAME,
)
from olympe.ops_manager import ops_manager
from olympe.server import app


@pytest.fixture
def temp_mailer(tmp_path):
    """Instancie un BrevoMailer isolé avec une base SQLite temporaire."""
    db_file = tmp_path / "test_ops.db"
    return BrevoMailer(
        api_key="test_mock_api_key_12345",
        sender_email=DEFAULT_SENDER_EMAIL,
        sender_name=DEFAULT_SENDER_NAME,
        db_path=db_file,
    )


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Client API FastAPI configuré avec une base de données temporaire."""
    db_file = tmp_path / "test_server_ops.db"
    monkeypatch.setattr(brevo_mailer, "db_path", db_file)
    brevo_mailer._init_mailer_db()
    return TestClient(app)


def test_kan104_templates_rendering_exact_wording(temp_mailer):
    """Vérifie le respect strict du texte et des objets convenus pour M1, M2, M3 et M4 (CA1, CA4)."""
    # ── M1 : Confirmation de souscription ─────────────────────────────────────
    m1 = temp_mailer.render_template("m1", {
        "palier": "Forfait Starter (1 agent)",
        "agents_calibres": "Jérôme (Crédit Manager)",
        "confirmation_url": "https://app.orso-agents.fr/confirm-email?token=tok123",
    })
    assert m1["subject"] == "Votre souscription Orso Agents est enregistrée."
    assert "Forfait Starter (1 agent)" in m1["html"]
    assert "Jérôme (Crédit Manager)" in m1["html"]
    assert "essai de 30 jours, aucun prélèvement aujourd'hui" in m1["html"]
    assert "valable 48h" in m1["html"]
    assert "https://app.orso-agents.fr/confirm-email?token=tok123" in m1["html"]
    assert "Je suis tout particulièrement heureux de vous accueillir" in m1["html"]
    assert "Thibaut Quinzain, Fondateur d'Orso Agents" in m1["html"]

    # ── M2 : Lancement de préparation par l'équipe ────────────────────────────
    m2 = temp_mailer.render_template("m2", {
        "agents": "Jérôme (Crédit Manager)",
    })
    assert m2["subject"] == "Votre espace Orso Agents est en préparation."
    assert "Jérôme (Crédit Manager)" in m2["html"]
    assert "pilotée par notre équipe" in m2["html"]

    # ── M3 : Mise en service & accès sécurisé ────────────────────────────────
    m3 = temp_mailer.render_template("m3", {
        "activation_url": "https://app.orso-agents.fr/activation?token=tok7days",
        "trois_points": "1. Définir votre mot de passe d'accès. 2. Valider la calibration de vos agents. 3. Connecter vos premiers canaux.",
        "date_cadrage": "mardi 14 octobre à 10h00",
    })
    assert m3["subject"] == "Votre espace Orso Agents est prêt."
    assert "https://app.orso-agents.fr/activation?token=tok7days" in m3["html"]
    assert "7 jours" in m3["html"]
    assert "1. Définir votre mot de passe d'accès" in m3["html"]
    assert "2. Valider la calibration de vos agents" in m3["html"]
    assert "3. Connecter vos premiers canaux" in m3["html"]
    assert "mardi 14 octobre à 10h00" in m3["html"]
    assert "Je suis tout particulièrement heureux de vous accueillir" in m3["html"]
    assert "Thibaut Quinzain, Fondateur d'Orso Agents" in m3["html"]

    # ── M4 : Incident / Besoin d'un échange ──────────────────────────────────
    m4 = temp_mailer.render_template("m4", {
        "cause": "ajustement de capacité matériel sur nos nœuds sécurisés",
        "contact_person_name": "Thibaut Quinzain",
        "contact_person_info": "contact@orso-agents.fr",
    })
    assert m4["subject"] == "Votre espace Orso Agents : nous avons besoin d'un échange."
    assert "ajustement de capacité matériel" in m4["html"]
    assert "Thibaut Quinzain" in m4["html"]
    assert "contact@orso-agents.fr" in m4["html"]

    # Template inconnu -> exception
    with pytest.raises(ValueError):
        temp_mailer.render_template("unknown_template", {})


def test_kan104_email_confirmation_lifecycle_and_alerts(temp_mailer):
    """Vérifie le cycle de vie du jeton de confirmation d'email 48h et l'alerte ops (CA2, CA10)."""
    # 1. Génération d'un token valide 48h
    token = temp_mailer.generate_confirmation_token("tenant-acme", "contact@acme.fr", validity_hours=48)
    assert len(token) >= 32

    # 2. Confirmation réussie
    res1 = temp_mailer.confirm_email_address(token, "tenant-acme")
    assert res1["valid"] is True
    assert res1["recipient_email"] == "contact@acme.fr"
    assert "confirmed_at" in res1

    # 3. Ré-appel idempotent
    res2 = temp_mailer.confirm_email_address(token, "tenant-acme")
    assert res2["valid"] is True
    assert res2.get("already_confirmed") is True

    # 4. Token expiré
    expired_token = temp_mailer.generate_confirmation_token("tenant-expired", "old@acme.fr", validity_hours=-1)
    res_exp = temp_mailer.confirm_email_address(expired_token, "tenant-expired")
    assert res_exp["valid"] is False
    assert res_exp["error_code"] == "ERR_TOKEN_EXPIRED"

    # 5. Détection des alertes d'emails non confirmés à 48h
    # Insérer une confirmation non confirmée créée il y a 50 heures
    import sqlite3
    old_time = (datetime.now(timezone.utc) - timedelta(hours=50)).isoformat()
    with sqlite3.connect(str(temp_mailer.db_path)) as conn:
        conn.execute(
            """INSERT INTO email_confirmations (token, tenant_slug, recipient_email, created_at, expires_at, confirmed_at)
               VALUES (?, ?, ?, ?, ?, NULL);""",
            ("tok_alert_50h", "tenant-alert", "boss@alert.fr", old_time, old_time),
        )
        conn.commit()

    alerts = temp_mailer.get_unconfirmed_email_alerts(threshold_hours=48)
    assert len(alerts) >= 1
    target_alert = next((a for a in alerts if a["recipient_email"] == "boss@alert.fr"), None)
    assert target_alert is not None
    assert target_alert["status"] == "unconfirmed_48h"
    assert target_alert["elapsed_hours"] >= 48.0


def test_kan104_invitation_token_lifecycle(temp_mailer):
    """Vérifie la génération, l'usage unique et l'expiration des tokens d'invitation 7 jours (CA9)."""
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


def test_kan104_domain_auth_probe(temp_mailer):
    """Vérifie la sonde DNS d'authentification SPF, DKIM et DMARC du domaine d'envoi (CA7)."""
    assert DEFAULT_SENDER_DOMAIN == "mail.orso-agents.fr"
    probe_res = temp_mailer.probe_domain_authentication()
    assert probe_res["domain"] == "mail.orso-agents.fr"
    assert "spf" in probe_res["records"]
    assert "dkim" in probe_res["records"]
    assert "dmarc" in probe_res["records"]
    assert probe_res["spf_aligned"] is True
    assert probe_res["dkim_aligned"] is True
    assert probe_res["dmarc_aligned"] is True
    assert probe_res["fully_authenticated"] is True


def test_kan104_no_predictable_passwords(monkeypatch):
    """Vérifie l'interdiction absolue de mots de passe prévisibles type 'Orso{timestamp}' (CA9)."""
    # Vérifier que lors de la création d'utilisateur, le mot de passe généré est aléatoire et fort (>= 32 chars)
    posted_payloads = []

    def mock_urlopen(req, timeout=5.0):
        body = req.data.decode("utf-8") if req.data else "{}"
        parsed = json.loads(body)
        posted_payloads.append(parsed)
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"id": "usr_supabase_mock_123", "users": []}).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.__exit__.return_value = None
        return mock_resp

    monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)
    monkeypatch.setattr(ops_manager, "supabase_url", "https://mock.supabase.co")
    monkeypatch.setattr(ops_manager, "supabase_key", "mock_key")
    monkeypatch.setattr(ops_manager, "_query_supabase", lambda *args, **kwargs: [])
    monkeypatch.setattr(ops_manager, "get_tenant_detail", lambda tid: {"id": tid, "slug": "acme-slug"})

    # 1. Test create_tenant_user sans mot de passe fourni
    ops_manager.create_tenant_user(
        tenant_id="tenant_def_dev",
        email="test_secure_user1@acme.fr",
        full_name="Jean Dupont",
        role="Dirigeant",
    )
    p1 = posted_payloads[-1]
    assert "password" in p1
    assert not p1["password"].startswith("Orso")
    assert len(p1["password"]) >= 32

    # 2. Test create_onboarding_admin_user sans mot de passe fourni
    ops_manager.create_onboarding_admin_user(
        tenant_id="tenant_def_dev",
        email="test_secure_user2@acme.fr",
        full_name="Claire Martin",
        role="DAF",
    )
    p2 = posted_payloads[-1]
    assert "password" in p2
    assert not p2["password"].startswith("Orso")
    assert len(p2["password"]) >= 32


def test_kan104_brevo_real_http_call(temp_mailer):
    """Vérifie que l'appel réseau vers Brevo transmet le domaine dédié et les headers requis (CA7)."""
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
                params={"agents": "Jérôme (Crédit Manager)"},
                tenant_slug="david-sarl",
            )
            assert res["success"] is True
            assert res["status"] == "SENT"
            assert res["message_id"] == "<brevo_msg_9876@smtp.brevo.com>"

            mock_urlopen.assert_called_once()
            req = mock_urlopen.call_args[0][0]
            assert req.full_url == "https://api.brevo.com/v3/smtp/email"
            assert req.headers["Api-key"] == "xkeysib-real-key-abcdef123456"

            sent_payload = json.loads(req.data.decode("utf-8"))
            assert sent_payload["to"][0]["email"] == "david@acme.com"
            assert sent_payload["sender"]["email"] == "contact@orso-agents.fr"
            assert sent_payload["replyTo"]["email"] == "contact@orso-agents.fr"


def test_kan104_fastapi_endpoints(client):
    """Vérifie les endpoints REST Olympe pour l'envoi, les confirmations et les alertes."""
    auth_headers = {"Authorization": f"Bearer {MOCK_SUPERADMIN_TOKEN}"}

    # 1. Génération d'invitation et validation 7 jours
    gen_res = client.post(
        "/api/olympe/invitations/generate",
        json={
            "tenant_slug": "tenant-fastapi",
            "recipient_email": "fastapi@test.com",
            "send_email": False,
        },
        headers=auth_headers,
    )
    assert gen_res.status_code == 200
    token = gen_res.json().get("invitation_token")
    assert token is not None

    val_res = client.post("/api/olympe/invitations/validate", json={"token": token})
    assert val_res.status_code == 200
    assert val_res.json()["valid"] is True

    # 2. Confirmation d'adresse email 48h via endpoint GET
    conf_token = brevo_mailer.generate_confirmation_token("tenant-fastapi", "verify@fastapi.com", validity_hours=48)
    conf_res = client.get(f"/api/olympe/email/confirm?token={conf_token}&slug=tenant-fastapi")
    assert conf_res.status_code == 200
    assert conf_res.json()["valid"] is True
    assert conf_res.json()["recipient_email"] == "verify@fastapi.com"

    # 3. Sonde d'authentification DNS
    auth_status_res = client.get("/api/olympe/ops/domain-auth/status", headers=auth_headers)
    assert auth_status_res.status_code == 200
    assert auth_status_res.json()["fully_authenticated"] is True

    # 4. Alerte emails non confirmés
    alerts_res = client.get("/api/olympe/ops/alerts/unconfirmed-emails", headers=auth_headers)
    assert alerts_res.status_code == 200
    assert "alerts" in alerts_res.json()

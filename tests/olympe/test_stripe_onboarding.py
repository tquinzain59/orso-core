"""Tests unitaires pour les endpoints d'onboarding Stripe et le superviseur Olympe."""

import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from olympe.server import app
from olympe.ops_manager import OpsManager

client = TestClient(app)


def test_init_setup_success():
    """Vérifie la génération du client_secret et customer_id lors de l'initialisation."""
    mock_ops = MagicMock(spec=OpsManager)
    mock_ops.create_onboarding_setup_intent.return_value = {
        "success": True,
        "customer_id": "cus_test_123",
        "setup_intent_id": "seti_test_456",
        "client_secret": "seti_test_456_secret_789",
    }

    with patch("olympe.server.ops_manager", mock_ops):
        payload = {
            "email": "contact@lumina-solutions.fr",
            "name": "Thomas Laurent",
            "company_name": "Lumina Solutions SAS",
            "slug": "lumina-solutions",
        }
        resp = client.post("/api/olympe/onboarding/init-setup", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["customer_id"] == "cus_test_123"
        assert data["client_secret"] == "seti_test_456_secret_789"
        mock_ops.create_onboarding_setup_intent.assert_called_once_with(
            email="contact@lumina-solutions.fr",
            name="Thomas Laurent",
            company_name="Lumina Solutions SAS",
            slug="lumina-solutions",
        )


def test_init_setup_error_handling():
    """Vérifie le renvoi d'un code 400 en cas d'erreur de l'API Stripe."""
    mock_ops = MagicMock(spec=OpsManager)
    mock_ops.create_onboarding_setup_intent.side_effect = ValueError("Erreur Stripe simulée")

    with patch("olympe.server.ops_manager", mock_ops):
        payload = {
            "email": "contact@error.fr",
            "name": "Admin",
            "company_name": "Entreprise",
        }
        resp = client.post("/api/olympe/onboarding/init-setup", json=payload)
        assert resp.status_code == 400
        assert "Erreur Stripe simulée" in resp.json()["detail"]


def test_create_subscription_success():
    """Vérifie la création d'un abonnement avec période d'essai de 30 jours à 0 €."""
    mock_ops = MagicMock(spec=OpsManager)
    mock_ops.create_trial_subscription.return_value = {
        "success": True,
        "subscription_id": "sub_test_trial_123",
        "customer_id": "cus_test_123",
        "status": "trialing",
        "trial_end": 1792000000,
        "price_id": "price_1UKJ6W06XM8Z6gbS5id4Hf0s",
    }

    with patch("olympe.server.ops_manager", mock_ops):
        payload = {
            "customer_id": "cus_test_123",
            "payment_method_id": "pm_card_test_999",
            "tier_id": "1_agent",
            "agents_count": 1,
        }
        resp = client.post("/api/olympe/onboarding/create-subscription", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["subscription_id"] == "sub_test_trial_123"
        assert data["status"] == "trialing"
        mock_ops.create_trial_subscription.assert_called_once_with(
            customer_id="cus_test_123",
            payment_method_id="pm_card_test_999",
            tier_id="1_agent",
            agents_count=1,
        )


def test_create_admin_user_success():
    """Vérifie la création du compte administrateur suite à l'onboarding."""
    mock_ops = MagicMock(spec=OpsManager)
    mock_ops.create_onboarding_admin_user.return_value = {
        "id": "usr_test_789",
        "email": "thibaut@nexis-solutions.fr",
        "full_name": "Thibaut ALBERT",
        "role": "Dirigeant",
        "phone": "07 61 80 67 73",
        "is_admin": True,
        "is_primary_contact": True,
    }

    with patch("olympe.server.ops_manager", mock_ops):
        payload = {
            "tenant_id": "3a4cb49e-970c-46a4-ada5-70163f2bee06",
            "email": "thibaut@nexis-solutions.fr",
            "full_name": "Thibaut ALBERT",
            "role": "Dirigeant",
            "phone": "07 61 80 67 73",
        }
        resp = client.post("/api/olympe/onboarding/create-admin-user", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["user"]["id"] == "usr_test_789"
        assert data["user"]["full_name"] == "Thibaut ALBERT"
        assert data["user"]["is_admin"] is True
        mock_ops.create_onboarding_admin_user.assert_called_once_with(
            tenant_id="3a4cb49e-970c-46a4-ada5-70163f2bee06",
            email="thibaut@nexis-solutions.fr",
            full_name="Thibaut ALBERT",
            role="Dirigeant",
            phone="07 61 80 67 73",
        )


def test_create_admin_user_error_handling():
    """Vérifie le code 400 en cas d'erreur de création d'utilisateur."""
    mock_ops = MagicMock(spec=OpsManager)
    mock_ops.create_onboarding_admin_user.side_effect = ValueError("Tenant inexistant")

    with patch("olympe.server.ops_manager", mock_ops):
        payload = {
            "tenant_id": "invalid-id",
            "email": "error@nexis.fr",
            "full_name": "Admin",
        }
        resp = client.post("/api/olympe/onboarding/create-admin-user", json=payload)
        assert resp.status_code == 400
        assert "Tenant inexistant" in resp.json()["detail"]


def test_create_admin_user_with_password():
    """Vérifie que le mot de passe utilisateur est bien transmis lorsqu'il est renseigné."""
    mock_ops = MagicMock(spec=OpsManager)
    mock_ops.create_onboarding_admin_user.return_value = {
        "id": "usr_with_pass_123",
        "email": "client@entreprise.fr",
        "full_name": "Jean Dupont",
        "role": "Dirigeant",
        "is_admin": True,
    }

    with patch("olympe.server.ops_manager", mock_ops):
        payload = {
            "tenant_id": "3a4cb49e-970c-46a4-ada5-70163f2bee06",
            "email": "client@entreprise.fr",
            "full_name": "Jean Dupont",
            "role": "Dirigeant",
            "phone": "06 12 34 56 78",
            "password": "SecurePassword2026!",
        }
        resp = client.post("/api/olympe/onboarding/create-admin-user", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        mock_ops.create_onboarding_admin_user.assert_called_once_with(
            tenant_id="3a4cb49e-970c-46a4-ada5-70163f2bee06",
            email="client@entreprise.fr",
            full_name="Jean Dupont",
            role="Dirigeant",
            phone="06 12 34 56 78",
            password="SecurePassword2026!",
        )


def test_rewrite_mission_letter_endpoint():
    """Vérifie l'endpoint de réécriture serveur sécurisée de la lettre de mission."""
    mock_ops = MagicMock(spec=OpsManager)
    mock_ops.rewrite_mission_letter.return_value = {
        "success": True,
        "content": "1. Contexte & Enjeux Stratégiques\nMission recouv...",
        "provider": "deepseek-v3",
        "cached": False,
    }

    with patch("olympe.server.ops_manager", mock_ops):
        payload = {
            "agent_id": "jerome",
            "agent_name": "Jérôme",
            "role_title": "Recouvrement & DSO",
            "company_name": "Lumina Solutions",
            "sector": "Conseil",
            "raw_notes": "Sécuriser les impayés",
            "extracted_docs_text": "",
        }
        resp = client.post("/api/olympe/onboarding/rewrite-mission-letter", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "Mission recouv" in data["content"]
        mock_ops.rewrite_mission_letter.assert_called_once_with(
            agent_id="jerome",
            agent_name="Jérôme",
            role_title="Recouvrement & DSO",
            company_name="Lumina Solutions",
            sector="Conseil",
            raw_notes="Sécuriser les impayés",
            extracted_docs_text="",
        )



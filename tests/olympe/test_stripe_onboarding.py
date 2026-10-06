"""Tests unitaires pour les routes d'onboarding Stripe et le superviseur Olympe.

Aligné sur l'arbitrage Direction KAN-45 et le ticket KAN-102 :
Les 4 anciennes routes d'onboarding autonome (/init-setup, /create-subscription,
/create-admin-user, /rewrite-mission-letter) ont été neutralisées (HTTP 404).
La vitrine ne provisionne plus de façon autonome : seule la demande d'essai est déposée
via /api/olympe/contact, et le provisionnement physique est piloté depuis le cockpit OPS.

Requalification KAN-102 :
- test_init_setup_route_neutralized : REQUALIFIÉ (ex test_init_setup_success). Route POST /api/olympe/onboarding/init-setup -> 404.
- test_create_subscription_route_neutralized : REQUALIFIÉ (ex test_create_subscription_success). Route POST /api/olympe/onboarding/create-subscription -> 404.
- test_create_admin_user_route_neutralized : REQUALIFIÉ (ex test_create_admin_user_success). Route POST /api/olympe/onboarding/create-admin-user -> 404.
- test_rewrite_mission_letter_route_neutralized : REQUALIFIÉ (ex test_rewrite_mission_letter_endpoint). Route POST /api/olympe/onboarding/rewrite-mission-letter -> 404.
- test_init_setup_error_handling : RETIRÉ (Gestion d'erreur 400 caduque sur route neutralisée en 404).
- test_create_admin_user_error_handling : RETIRÉ (Gestion d'erreur 400 caduque sur route neutralisée en 404).
- test_create_admin_user_with_password : RETIRÉ (Variante de payload caduque sur route neutralisée en 404).
"""

from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from olympe.server import app
from olympe.ops_manager import OpsManager

client = TestClient(app)


def test_init_setup_route_neutralized():
    """Vérifie la neutralisation (HTTP 404) de la route autonome d'init-setup suite à l'arbitrage KAN-45."""
    mock_ops = MagicMock(spec=OpsManager)
    with patch("olympe.server.ops_manager", mock_ops):
        payload = {
            "email": "contact@lumina-solutions.fr",
            "name": "Thomas Laurent",
            "company_name": "Lumina Solutions SAS",
            "slug": "lumina-solutions",
        }
        resp = client.post("/api/olympe/onboarding/init-setup", json=payload)
        assert resp.status_code == 404
        mock_ops.create_onboarding_setup_intent.assert_not_called()


def test_create_subscription_route_neutralized():
    """Vérifie la neutralisation (HTTP 404) de la route autonome de création d'abonnement suite à l'arbitrage KAN-45."""
    mock_ops = MagicMock(spec=OpsManager)
    with patch("olympe.server.ops_manager", mock_ops):
        payload = {
            "customer_id": "cus_test_123",
            "payment_method_id": "pm_card_test_999",
            "tier_id": "1_agent",
            "agents_count": 1,
        }
        resp = client.post("/api/olympe/onboarding/create-subscription", json=payload)
        assert resp.status_code == 404
        mock_ops.create_trial_subscription.assert_not_called()


def test_create_admin_user_route_neutralized():
    """Vérifie la neutralisation (HTTP 404) de la route autonome de création d'administrateur suite à l'arbitrage KAN-45."""
    mock_ops = MagicMock(spec=OpsManager)
    with patch("olympe.server.ops_manager", mock_ops):
        payload = {
            "tenant_id": "3a4cb49e-970c-46a4-ada5-70163f2bee06",
            "email": "thibaut@nexis-solutions.fr",
            "full_name": "Thibaut ALBERT",
            "role": "Dirigeant",
            "phone": "07 61 80 67 73",
        }
        resp = client.post("/api/olympe/onboarding/create-admin-user", json=payload)
        assert resp.status_code == 404
        mock_ops.create_onboarding_admin_user.assert_not_called()


def test_rewrite_mission_letter_route_neutralized():
    """Vérifie la neutralisation (HTTP 404) de la route autonome de réécriture de lettre de mission suite à l'arbitrage KAN-45."""
    mock_ops = MagicMock(spec=OpsManager)
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
        assert resp.status_code == 404
        mock_ops.rewrite_mission_letter.assert_not_called()

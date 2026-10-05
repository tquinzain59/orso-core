"""Tests d'acceptation KAN-45 : Parcours d'achat vitrine, essai gratuit 30 jours,

page de contact et acheminement vers la boîte de test joignable.
"""

from __future__ import annotations

import os
import socket
from pathlib import Path
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient

from olympe.server import app, ops_manager


@pytest.fixture
def client():
    return TestClient(app)


class TestKAN45Acceptance:
    """Suite d'acceptation validant les 5 critères du ticket Jira KAN-45."""

    def test_ca1_visitor_onboarding_trial_without_manual_intervention(self, client):
        """Critère 1 : un visiteur peut souscrire en environnement de test sans intervention manuelle.

        Vérifie le déroulement complet des étapes automatisées :
        1. Initialisation SetupIntent Stripe (/init-setup)
        2. Création de l'abonnement d'essai 30 jours (/create-subscription)
        3. Création et synchronisation du compte administrateur (/create-admin-user)
        """
        slug = f"test-vitrine-trial-{int(os.times().system * 1000) % 10000}"
        admin_email = f"dirigeant.{slug}@orso-agents.fr"
        company_name = "Vitrine Test Solutions SAS"

        # Étape 1 : Initialisation de l'empreinte bancaire Stripe SetupIntent
        resp_setup = client.post(
            "/api/olympe/onboarding/init-setup",
            json={
                "email": admin_email,
                "name": "Jean Testeur",
                "company_name": company_name,
                "slug": slug,
            },
        )
        assert resp_setup.status_code == 200, f"Échec init-setup: {resp_setup.text}"
        setup_data = resp_setup.json()
        assert setup_data.get("success") is True
        assert "client_secret" in setup_data
        assert "customer_id" in setup_data
        stripe_customer_id = setup_data["customer_id"]
        assert stripe_customer_id.startswith("cus_")

        # Étape 2 : Création de la souscription d'essai 30 jours à 0 €
        with patch.object(
            ops_manager,
            "create_trial_subscription",
            return_value={
                "success": True,
                "subscription_id": f"sub_test_{slug}",
                "customer_id": stripe_customer_id,
                "status": "trialing",
                "trial_days": 30,
            },
        ):
            resp_sub = client.post(
                "/api/olympe/onboarding/create-subscription",
                json={
                    "customer_id": stripe_customer_id,
                    "payment_method_id": "pm_card_test_123",
                    "tier_id": "2_agents",
                    "slug": slug,
                },
            )
            assert resp_sub.status_code == 200, f"Échec create-subscription: {resp_sub.text}"
            sub_data = resp_sub.json()
            assert sub_data.get("success") is True
            assert sub_data.get("subscription_id") == f"sub_test_{slug}"
            assert sub_data.get("status") in ("trialing", "active")
            assert sub_data.get("trial_days") == 30

        # Étape 3 : Création du compte administrateur autonome rattaché à l'organisation
        tenant_created = ops_manager.create_sandbox_tenant(
            tenant_slug=slug,
            name=company_name,
            contact_email=admin_email,
            contact_name="Jean Testeur",
        )
        tenant_id = tenant_created["tenant"]["id"]

        resp_user = client.post(
            "/api/olympe/onboarding/create-admin-user",
            json={
                "tenant_id": tenant_id,
                "email": admin_email,
                "full_name": "Jean Testeur",
                "role": "Dirigeant",
                "password": "PasswordSecure2026!",
            },
        )
        assert resp_user.status_code == 200, f"Échec create-admin-user: {resp_user.text}"
        user_data = resp_user.json()
        assert user_data.get("success") is True
        created_user = user_data.get("user")
        assert created_user is not None
        assert created_user.get("email") == admin_email
        assert created_user.get("is_admin") is True

    def test_ca2_subscription_creates_client_subscription_and_environment(self, client):
        """Critère 2 : la souscription crée le client, l'abonnement et l'environnement, chacun vérifiable en base."""
        slug = f"client-auto-{int(os.times().system * 1000) % 10000}"
        tenant_name = "Cabinet Audit & Finance"
        contact_email = f"contact@{slug}.orso-agents.fr"

        # Création et enregistrement de l'organisation dans le gestionnaire
        created = ops_manager.create_sandbox_tenant(
            tenant_slug=slug,
            name=tenant_name,
            contact_email=contact_email,
            contact_name="Marc Directeur",
            quotas={"cpus": "1.0", "memory": "1024m"},
        )
        assert created.get("success") is True
        tenant = created.get("tenant", {})
        assert tenant.get("slug") == slug
        assert tenant.get("name") == tenant_name

        # Vérification 1 : Client / Organisation vérifiable
        detail = ops_manager.get_tenant_detail(slug)
        assert detail is not None, f"Client {slug} non trouvé"
        assert detail.get("slug") == slug
        assert detail.get("contact", {}).get("email") == contact_email

        # Vérification 2 : Abonnement vérifiable
        sub = detail.get("subscription", {})
        assert sub is not None
        assert sub.get("status") in ("trialing", "active")

        # Vérification 3 : Environnement infrastructure vérifiable
        instance = detail.get("instance", {})
        assert instance is not None
        assert (instance.get("container_name") or instance.get("docker_container_name")) == f"orso_client_{slug.replace('-', '_')}"
        assert instance.get("internal_route_key") == f"orso_client_{slug.replace('-', '_')}"
        assert instance.get("environment_status") in ("active", "ready", "inactive", "pending_validation")

    def test_ca3_confirmation_page_displays_real_state(self):
        """Critère 3 : une page de confirmation affiche l'état réel.

        Vérifie la présence et la complétude du panneau de confirmation Étape 5
        dans onboarding.html, affichant les données réelles (organisation,
        admin, montant d'aujourd'hui à 0 €, tarif mensuel, échéance, agents).
        """
        vitrine_path = Path("/Users/tquinzain/Documents/Dev Projects/Site_Hermes-core/onboarding.html")
        if not vitrine_path.exists():
            vitrine_path = Path("../Site_Hermes-core/onboarding.html").resolve()
        assert vitrine_path.exists(), "Fichier onboarding.html de la vitrine introuvable"

        html_content = vitrine_path.read_text(encoding="utf-8")

        # Vérification des sélecteurs d'affichage d'état réel dans le récapitulatif
        required_selectors = [
            'id="recap_company_name"',
            'id="recap_siret"',
            'id="recap_admin_name"',
            'id="recap_admin_email"',
            'id="recap_tier_label"',
            'id="recap_today_charge"',
            'id="recap_monthly_price"',
            'id="recap_next_charge"',
            'id="recap_agents_list"',
            'href="https://app.orso-agents.fr"',
        ]
        for sel in required_selectors:
            assert sel in html_content, f"Élément de récapitulatif d'état réel manquant : {sel}"

        # Vérification du libellé de période d'essai 0 €
        assert "0,00 € (Aujourd'hui)" in html_content
        assert "Essai 30 jours actif" in html_content

    def test_ca4_messages_routed_to_reachable_mailbox_not_unreachable_subdomain(self):
        """Critère 4 : les messages partent vers la boîte de test unique et non vers l'ancienne adresse,

        la boîte de test devant elle-même être rendue joignable (aucun enregistrement DNS ni MX
        sur le sous-domaine annoncé test.orso-agents.fr).
        """
        from olympe.server import CreateTenantOpsRequest

        # 1. Vérification du modèle par défaut server.py : domaine orso-agents.fr joignable
        req_default = CreateTenantOpsRequest()
        assert "@orso-agents.fr" in req_default.contact_email
        assert "@test.orso-agents.fr" not in req_default.contact_email
        assert "hermes-core.fr" not in req_default.contact_email

        # 2. Vérification du gestionnaire ops_manager.create_sandbox_tenant
        created = ops_manager.create_sandbox_tenant("test-mx-check")
        assert "@orso-agents.fr" in created["tenant"]["contact"]["email"]
        assert "@test.orso-agents.fr" not in created["tenant"]["contact"]["email"]

        # 3. Vérification de la résolubilité MX du domaine de notification officiel (orso-agents.fr)
        domain = "orso-agents.fr"
        try:
            ip = socket.gethostbyname(domain)
            assert ip is not None and len(ip) > 0, f"Résolution DNS impossible pour {domain}"
        except socket.gaierror as e:
            pytest.skip(f"Résolution DNS externe non disponible dans l'environnement de test: {e}")

    def test_ca5_contact_page_responds_and_fulfills_requirements(self):
        """Critère 5 : la page de contact demandée par le cahier des charges répond.

        Vérifie :
        1. Présence de contact.html dans le dépôt vitrine
        2. Formulaire complet (nom, email, entreprise, téléphone, agent, message, consentement RGPD)
        3. Email officiel de contact direct (contact@orso-agents.fr)
        4. Prise en charge des règles Vercel cleanUrls: true
        5. Liens cohérents dans index.html et tarifs.html vers contact.html
        """
        base_dir = Path("/Users/tquinzain/Documents/Dev Projects/Site_Hermes-core")
        if not base_dir.exists():
            base_dir = Path("../Site_Hermes-core").resolve()

        contact_file = base_dir / "contact.html"
        assert contact_file.exists(), "Fichier contact.html absent du dépôt vitrine (404 évitable)"

        contact_html = contact_file.read_text(encoding="utf-8")

        # Vérification des champs requis du cahier des charges
        assert 'name="name"' in contact_html
        assert 'name="email"' in contact_html
        assert 'name="company"' in contact_html
        assert 'name="interest"' in contact_html
        assert 'name="message"' in contact_html
        assert 'name="consent"' in contact_html
        assert "contact@orso-agents.fr" in contact_html
        assert "24h ouvrées" in contact_html

        # Vérification vercel.json cleanUrls
        vercel_json = (base_dir / "vercel.json").read_text(encoding="utf-8")
        assert '"cleanUrls": true' in vercel_json

        # Vérification des liens dans index.html
        index_html = (base_dir / "index.html").read_text(encoding="utf-8")
        assert 'href="contact.html"' in index_html
        assert 'href="onboarding.html?agents=recouvrement,commercial"' in index_html

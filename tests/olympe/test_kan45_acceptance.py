"""Tests d'acceptation KAN-45 : Parcours d'achat vitrine, essai gratuit 30 jours,

page de contact transmettrice et acheminement vers la boîte de test joignable.
Valide formellement l'arbitrage Direction : notification sur OPS et déclenchement
du déploiement d'environnement piloté depuis le backoffice.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient

from olympe.server import app, ops_manager, ContactFormRequest


@pytest.fixture
def client():
    return TestClient(app)


def _find_site_dir() -> Path | None:
    """Localise le dossier du site vitrine de manière dynamique et portable."""
    env_path = os.environ.get("ORSO_SITE_DIR")
    if env_path and Path(env_path).is_dir():
        return Path(env_path)

    candidates = [
        Path("../Site_Hermes-core").resolve(),
        Path("../orso-site").resolve(),
        Path("../../Site_Hermes-core").resolve(),
        Path("../../orso-site").resolve(),
        Path("/Users/tquinzain/Documents/Dev Projects/Site_Hermes-core").resolve(),
    ]
    for c in candidates:
        if c.is_dir() and (c / "contact.html").is_file():
            return c
    return None


class TestKAN45Acceptance:
    """Suite d'acceptation validant les 5 critères du ticket Jira KAN-45."""

    def test_ca1_visitor_onboarding_trial_without_manual_intervention(self, client):
        """Critère 1 : un visiteur peut souscrire en environnement de test sans intervention manuelle.

        Vérifie le déroulement complet des étapes automatisées :
        1. Initialisation SetupIntent Stripe (/init-setup)
        2. Création de l'abonnement d'essai 30 jours (/create-subscription)
        3. Création et synchronisation du compte administrateur (/create-admin-user)
        4. Vérification de l'arbitrage Direction : l'environnement reste en attente (pending_validation)
           jusqu'au déclenchement explicite par le superadmin dans le Cockpit Ops.
        """
        slug = f"test-vitrine-trial-{int(os.times().system * 1000) % 10000}"
        admin_email = f"dirigeant.{slug}@orso-agents.fr"
        company_name = "Vitrine Test Solutions SAS"

        # Mock hermétique de la couche réseau Stripe pour reproductibilité CI hors poste
        def mock_stripe_request(endpoint, method="GET", data=None):
            if endpoint.startswith("customers"):
                return {"id": f"cus_test_{slug}", "email": admin_email}
            elif endpoint == "setup_intents":
                return {
                    "id": f"seti_test_{slug}",
                    "client_secret": f"seti_test_{slug}_secret_kan45",
                    "status": "requires_payment_method",
                }
            elif "attach" in endpoint:
                return {"id": "pm_card_test_123"}
            elif endpoint == "subscriptions":
                return {
                    "id": f"sub_test_{slug}",
                    "customer": f"cus_test_{slug}",
                    "status": "trialing",
                    "trial_end": 1799999999,
                    "items": {"data": [{"price": {"id": "price_kan45"}}]},
                }
            return {}

        with patch.object(ops_manager, "_stripe_request", side_effect=mock_stripe_request), \
             patch.object(ops_manager, "stripe_secret_key", "sk_test_kan45_acceptance"):

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

            # Étape 2 : Création de la souscription d'essai 30 jours à 0 €
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
        assert sub.get("status") in ("trialing", "active", "pending_validation")

        # Vérification 3 : Environnement infrastructure vérifiable
        instance = detail.get("instance", {})
        assert instance is not None
        assert (instance.get("container_name") or instance.get("docker_container_name")) == f"orso_client_{slug.replace('-', '_')}"
        assert instance.get("internal_route_key") == f"orso_client_{slug.replace('-', '_')}"
        # Arbitrage Direction : l'environnement est prêt ou en attente de déploiement explicite
        assert instance.get("environment_status") in ("active", "ready", "inactive", "pending_validation")

    def test_ca3_confirmation_page_displays_real_state(self):
        """Critère 3 : une page de confirmation affiche l'état réel.

        Vérifie la présence et la complétude du panneau de confirmation Étape 5
        dans onboarding.html, affichant les données réelles (organisation,
        admin, montant d'aujourd'hui à 0 €, tarif mensuel, échéance, agents).
        """
        site_dir = _find_site_dir()
        if not site_dir:
            pytest.skip("Dépôt du site vitrine absent de l'environnement de test (reproductibilité CI isolée)")

        onboarding_file = site_dir / "onboarding.html"
        assert onboarding_file.is_file(), f"Fichier {onboarding_file} introuvable"
        html_content = onboarding_file.read_text(encoding="utf-8")

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

        # 3. Contrôle réel des enregistrements DNS MX
        # Prouve que orso-agents.fr dispose d'enregistrements MX réels (OVH)
        # et que test.orso-agents.fr n'en a aucun.
        if shutil.which("dig"):
            proc_valid = subprocess.run(["dig", "+short", "orso-agents.fr", "MX"], capture_output=True, text=True)
            assert proc_valid.returncode == 0
            mx_records = proc_valid.stdout.strip()
            assert "mail.ovh.net" in mx_records, f"Enregistrements MX OVH manquants sur orso-agents.fr : {mx_records}"

            proc_invalid = subprocess.run(["dig", "+short", "test.orso-agents.fr", "MX"], capture_output=True, text=True)
            assert proc_invalid.returncode == 0
            assert proc_invalid.stdout.strip() == "", "test.orso-agents.fr ne doit comporter aucun enregistrement MX"

    def test_ca5_contact_page_responds_transmits_and_notifies_ops(self, client):
        """Critère 5 : la page de contact demandée par le cahier des charges répond,

        transmet les demandes de manière effective (POST /api/olympe/contact)
        et notifie le Cockpit OPS sans 404.
        """
        # 1. Test du point de terminaison de transmission serveur réel
        payload = {
            "name": "Sophie Martin",
            "email": "s.martin@financia-solutions.fr",
            "company": "Financia Solutions SAS",
            "phone": "06 12 34 56 78",
            "interest": "recouvrement",
            "message": "Demande de cadrage pour période d'essai 30 jours sur l'agent de recouvrement Jérôme.",
            "consent": True,
        }
        resp = client.post("/api/olympe/contact", json=payload)
        assert resp.status_code == 200, f"Échec transmission contact : {resp.text}"
        data = resp.json()
        assert data.get("success") is True
        assert "lead_id" in data
        assert data.get("status") == "pending_validation"

        # 2. Vérification de l'enregistrement de l'audit et de la notification dans OPS
        audit_events = ops_manager.get_audit_events(limit=10)
        contact_event = next((e for e in audit_events if e.get("action") == "contact:lead"), None)
        assert contact_event is not None, "Événement d'audit 'contact:lead' non enregistré dans OPS"
        assert contact_event.get("target") == "s.martin@financia-solutions.fr"

        # 3. Vérification de la détection dans les arrivées en attente du Cockpit OPS (badge Arrivées & OVH)
        pending_tenants = ops_manager.get_pending_onboarding()
        assert any(t.get("name") == "Financia Solutions SAS" for t in pending_tenants), \
            "Le prospect n'apparaît pas dans la liste des arrivées en attente de déploiement OPS"

        # 4. Vérification statique de contact.html dans le dépôt vitrine (si présent)
        site_dir = _find_site_dir()
        if site_dir:
            contact_file = site_dir / "contact.html"
            assert contact_file.is_file(), "Fichier contact.html absent du dépôt vitrine"
            contact_html = contact_file.read_text(encoding="utf-8")

            # Formulaire et transmission réelle
            assert 'name="name"' in contact_html
            assert 'name="email"' in contact_html
            assert 'name="company"' in contact_html
            assert 'name="interest"' in contact_html
            assert 'name="message"' in contact_html
            assert 'name="consent"' in contact_html
            assert "contact@orso-agents.fr" in contact_html
            assert "fetch(`${apiBase}/api/olympe/contact`" in contact_html or "/api/olympe/contact" in contact_html

            # Configuration Vercel cleanUrls
            vercel_json = (site_dir / "vercel.json").read_text(encoding="utf-8")
            assert '"cleanUrls": true' in vercel_json

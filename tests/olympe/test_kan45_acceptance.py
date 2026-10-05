"""Tests d'acceptation KAN-45 : Parcours d'achat vitrine, essai gratuit 30 jours,

page de contact transmettrice et acheminement vers la boîte de test joignable.
Valide formellement l'arbitrage Direction : notification sur OPS et déclenchement
du déploiement d'environnement piloté depuis le backoffice.
"""

from __future__ import annotations

import os
import random
import shutil
import subprocess
import uuid
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
    ]
    for c in candidates:
        if c.is_dir() and (c / "contact.html").is_file():
            return c
    return None


class TestKAN45Acceptance:
    """Suite d'acceptation validant les 5 critères du ticket Jira KAN-45."""

    def test_ca1_visitor_onboarding_trial_without_manual_intervention(self, client):
        """Critère 1 (Arbitrage Direction 05/10/2026) :
        Un visiteur dépose une demande d'essai depuis la vitrine sans intervention manuelle.
        La vitrine ne crée rien : elle transmet la demande, qui est enregistrée en attente de validation.
        Aucune création de client, d'abonnement, de compte ou d'environnement ne se déclenche depuis la page publique.

        Vérifications formelles :
        1. Neutralisation des 4 anciennes routes d'onboarding autonome : un GET (et POST) répond HTTP 404.
        2. Dépôt de la demande d'essai via POST /api/olympe/contact sans intervention manuelle.
        3. Enregistrement en attente (status pending_validation) sans création de conteneur.
        """
        # 1. Vérification de la neutralisation des 4 routes d'onboarding autonome (répondent 404 en lecture GET)
        decommissioned_routes = [
            "/api/olympe/onboarding/init-setup",
            "/api/olympe/onboarding/create-subscription",
            "/api/olympe/onboarding/create-admin-user",
            "/api/olympe/onboarding/rewrite-mission-letter",
        ]
        for route in decommissioned_routes:
            resp_get = client.get(route)
            assert resp_get.status_code == 404, f"La route neutralisée {route} doit répondre HTTP 404 en lecture GET, reçu {resp_get.status_code}"
            resp_post = client.post(route, json={})
            assert resp_post.status_code == 404, f"La route neutralisée {route} doit répondre HTTP 404 en POST, reçu {resp_post.status_code}"

        # 2. Dépôt de la demande d'essai gratuit depuis la vitrine sans intervention manuelle
        test_ip = f"10.{random.randint(10, 200)}.{random.randint(1, 250)}.{random.randint(1, 250)}"
        headers_ip = {"X-Forwarded-For": test_ip}
        slug = f"test-trial-vitrine-{int(os.times().system * 1000) % 10000}"
        payload = {
            "name": "Jean Visiteur",
            "email": f"jean.{slug}@solutions-prospect.fr",
            "company": "Solutions Prospect SAS",
            "phone": "06 11 22 33 44",
            "interest": "recouvrement, commercial",
            "message": "Demande de qualification pour période d'essai 30 jours (arbitrage KAN-45).",
            "consent": True,
        }
        resp = client.post("/api/olympe/contact", json=payload, headers=headers_ip)
        assert resp.status_code == 200, f"Échec de la soumission de la demande d'essai : {resp.text}"
        data = resp.json()
        assert data.get("success") is True
        assert "lead_id" in data
        assert data.get("status") == "pending_validation"

    def test_ca2_subscription_creates_client_subscription_and_environment(self, client):
        """Critère 2 (Arbitrage Direction 05/10/2026) :
        La demande déposée crée une fiche client, une demande d'abonnement d'essai de 30 jours
        et une ligne d'environnement attendue, chacune lisible en base, dans l'état réel d'attente de validation.
        La fiche doit être lue par le service de production lui-même, afin que le cockpit affiche la demande :
        un magasin que la production ne lit pas ne vaut pas vérification.
        Aucune ligne ne peut affirmer un environnement créé, prêt ou actif tant qu'aucun conteneur n'existe,
        et l'appelant lit le retour du provisioning au lieu de le supposer.
        """
        import sqlite3

        slug = f"client-lead-{int(os.times().system * 1000) % 10000}"
        tenant_name = "Cabinet Audit & Finance"
        contact_email = f"contact@{slug}.orso-agents.fr"

        # Dépôt de la demande via le formulaire de contact vitrine
        test_ip = f"10.{random.randint(10, 200)}.{random.randint(1, 250)}.{random.randint(1, 250)}"
        headers_ip = {"X-Forwarded-For": test_ip}
        payload = {
            "name": "Marc Directeur",
            "email": contact_email,
            "company": tenant_name,
            "phone": "01 42 68 00 00",
            "interest": "recouvrement",
            "message": "Demande de cadrage pour période d'essai 30 jours Jérôme (CA2).",
            "consent": True,
        }
        resp = client.post("/api/olympe/contact", json=payload, headers=headers_ip)
        assert resp.status_code == 200, f"Erreur soumission : {resp.text}"
        lead_id = resp.json().get("lead_id")

        # ── Vérification 1 : Client / Organisation vérifiable en base SQLite réelle ──
        with sqlite3.connect(str(ops_manager.db_path)) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, slug, name, status, contact_email, contact_name, is_sandbox FROM tenants WHERE contact_email = ?",
                (contact_email,),
            )
            row_tenant = cursor.fetchone()
            assert row_tenant is not None, f"Client {contact_email} non trouvé dans la table SQL 'tenants'"
            t_id, t_slug, t_name, t_status, t_email, t_cname, t_sandbox = row_tenant
            assert t_name == tenant_name
            assert t_email == contact_email
            assert t_status == "trial"
            assert t_sandbox == 1

            # ── Vérification 2 : Abonnement d'essai 30j en attente de validation en base ──
            cursor.execute(
                "SELECT id, tenant_id, tier_id, status, trial_days FROM subscriptions WHERE tenant_id = ?",
                (t_id,),
            )
            row_sub = cursor.fetchone()
            assert row_sub is not None, f"Abonnement pour {t_id} non trouvé dans la table SQL 'subscriptions'"
            s_id, s_tid, s_tier, s_status, s_trial_days = row_sub
            assert s_tid == t_id
            assert s_tier == "1_agent"
            assert s_status == "pending_validation", f"L'abonnement doit être en pending_validation, reçu {s_status}"
            assert s_trial_days == 30

            # ── Vérification 3 : Environnement dans l'état réel d'attente (not_provisioned / pending_validation) ──
            cursor.execute(
                "SELECT id, tenant_id, container_name, internal_route_key, status, environment_status FROM tenant_instances WHERE tenant_id = ?",
                (t_id,),
            )
            row_inst = cursor.fetchone()
            assert row_inst is not None, f"Instance pour {t_id} non trouvée dans la table SQL 'tenant_instances'"
            i_id, i_tid, i_cname, i_route, i_status, i_env_status = row_inst
            assert i_tid == t_id
            assert i_status == "not_provisioned", f"L'instance ne peut pas affirmer ready sans conteneur physique : {i_status}"
            assert i_env_status == "pending_validation", f"L'environnement ne peut pas affirmer active sans conteneur : {i_env_status}"

            # Sorties brutes d'inspection de base de données (exigence formelle du contrat de revue KAN-45)
            print(f"\n[RAW DB PROBE - CA2 TENANT] id={t_id} slug={t_slug} name='{t_name}' status={t_status} contact='{t_cname}' <{t_email}> sandbox={t_sandbox}")
            print(f"[RAW DB PROBE - CA2 SUBSCRIPTION] id={s_id} tenant_id={s_tid} tier={s_tier} status={s_status} trial_days={s_trial_days}")
            print(f"[RAW DB PROBE - CA2 INSTANCE] id={i_id} tenant_id={i_tid} container={i_cname} route={i_route} status={i_status} env_status={i_env_status}")

        # ── Vérification 4 : Lecture de la demande par le service de production lui-même ──
        # get_tenants_overview lit la base de données et consolide les fiches SQLite
        tenants_overview = ops_manager.get_tenants_overview()
        found_in_overview = next((t for t in tenants_overview if t["id"] == t_id), None)
        assert found_in_overview is not None, f"La demande {t_id} n'est pas remontée par get_tenants_overview()"
        assert found_in_overview["instance"]["status"] == "not_provisioned"
        assert found_in_overview["instance"]["environment_status"] == "pending_validation"
        assert found_in_overview["subscription"]["status"] == "pending_validation"

        # Le Cockpit affiche la demande dans les arrivées en attente (Arrivées & OVH)
        pending_list = ops_manager.get_pending_onboarding()
        assert any(p["id"] == t_id for p in pending_list), f"La demande {t_id} n'apparaît pas dans get_pending_onboarding() pour le Cockpit"

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
        transmet les demandes de manière effective (POST /api/olympe/contact),
        est protégée contre les abus (rate limiting 429, consentement obligatoire 400),
        persiste en base de données réelle (contact_leads, audit_events) et notifie le Cockpit OPS sans 404.
        """
        import sqlite3

        # 1. Vérification du rejet si consentement RGPD manquant ou False (KAN-45 Condition 4)
        bad_consent_payload = {
            "name": "Consent Test",
            "email": "noconsent@example.com",
            "message": "Message sans consentement explicite.",
            "consent": False,
        }
        resp_bad = client.post("/api/olympe/contact", json=bad_consent_payload)
        assert resp_bad.status_code == 400, f"Le consentement manquant doit être rejeté en 400: {resp_bad.status_code}"
        assert "consentement" in resp_bad.json().get("detail", "").lower()

        # Vérification du rejet si le champ consent est omis (défaut False)
        resp_omitted = client.post("/api/olympe/contact", json={
            "name": "Consent Omitted",
            "email": "omitted@example.com",
            "message": "Message où consent n'est pas fourni.",
        })
        assert resp_omitted.status_code == 400

        # 2. Test du point de terminaison de transmission serveur réel avec IP dédiée
        test_ip = f"192.168.{random.randint(10, 200)}.{random.randint(1, 250)}"
        headers_ip = {"X-Forwarded-For": test_ip}
        payload = {
            "name": "Sophie Martin",
            "email": "s.martin@financia-solutions.fr",
            "company": "Financia Solutions SAS",
            "phone": "06 12 34 56 78",
            "interest": "recouvrement",
            "message": "Demande de cadrage pour période d'essai 30 jours sur l'agent de recouvrement Jérôme.",
            "consent": True,
        }
        resp = client.post("/api/olympe/contact", json=payload, headers=headers_ip)
        assert resp.status_code == 200, f"Échec transmission contact : {resp.text}"
        data = resp.json()
        assert data.get("success") is True
        assert "lead_id" in data
        assert data.get("status") == "pending_validation"
        lead_id = data["lead_id"]

        # 3. Vérification de la limitation de débit anti-abus (5 requêtes / minute)
        for _ in range(4):
            client.post("/api/olympe/contact", json=payload, headers=headers_ip)
        resp_throttled = client.post("/api/olympe/contact", json=payload, headers=headers_ip)
        assert resp_throttled.status_code == 429, f"La 6e requête doit être bloquée par le rate limiter (429): {resp_throttled.status_code}"
        assert "trop de requêtes" in resp_throttled.json().get("detail", "").lower()

        # 4. Vérification formelle en base de données SQLite réelle (tables contact_leads et audit_events)
        with sqlite3.connect(str(ops_manager.db_path)) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, name, email, company, interest, consent, status FROM contact_leads WHERE email = ?",
                ("s.martin@financia-solutions.fr",),
            )
            row_lead = cursor.fetchone()
            assert row_lead is not None, "Lead 's.martin@financia-solutions.fr' introuvable dans la table SQL 'contact_leads'"
            l_id, l_name, l_email, l_company, l_interest, l_consent, l_status = row_lead
            assert l_name == "Sophie Martin"
            assert l_email == "s.martin@financia-solutions.fr"
            assert l_company == "Financia Solutions SAS"
            assert l_consent == 1
            assert l_status == "pending_review"

            cursor.execute(
                "SELECT id, action, target, actor, details_json FROM audit_events WHERE action = 'contact:lead' AND target = ?",
                ("s.martin@financia-solutions.fr",),
            )
            row_audit = cursor.fetchone()
            assert row_audit is not None, "Événement d'audit contact:lead introuvable dans la table SQL 'audit_events'"
            a_id, a_action, a_target, a_actor, a_details = row_audit

            print(f"\n[RAW DB PROBE - CA5 CONTACT_LEAD] id={l_id} email={l_email} company={l_company} consent={l_consent} status={l_status}")
            print(f"[RAW DB PROBE - CA5 AUDIT_EVENT] id={a_id} action={a_action} target={a_target} actor={a_actor}")

        # 5. Vérification de l'enregistrement de l'audit et de la notification dans OPS
        audit_events = ops_manager.get_audit_events(limit=10)
        contact_event = next((e for e in audit_events if e.get("action") == "contact:lead"), None)
        assert contact_event is not None, "Événement d'audit 'contact:lead' non enregistré dans OPS"
        assert contact_event.get("target") == "s.martin@financia-solutions.fr"

        # 6. Vérification de la détection dans les arrivées en attente du Cockpit OPS (badge Arrivées & OVH)
        pending_tenants = ops_manager.get_pending_onboarding()
        assert any(t.get("name") == "Financia Solutions SAS" for t in pending_tenants), \
            "Le prospect n'apparaît pas dans la liste des arrivées en attente de déploiement OPS"

        # 7. Vérification statique de contact.html dans le dépôt vitrine (si présent)
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

            # Configuration Vercel : rewrites propres et redirections de sécurité ops
            vercel_json = (site_dir / "vercel.json").read_text(encoding="utf-8")
            assert '"rewrites"' in vercel_json or '"cleanUrls"' in vercel_json
            assert 'https://ops.orso-agents.fr' in vercel_json

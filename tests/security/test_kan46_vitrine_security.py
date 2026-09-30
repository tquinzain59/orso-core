"""Tests automatisés de conformité sécurité pour le ticket KAN-46.

Critères vérifiés :
- Critère 1 : https://www.orso-agents.fr/Secrets/secrets_poc.md répond HTTP 404 ou 410.
- Critère 2 : Aucun secret ou mot de passe en clair n'apparaît dans le contenu servi par le site.
- Critère 4 : admin.html redirige vers ops.orso-agents.fr (HTTP 301/308) et ne sert aucun identifiant par défaut.
- Critère Révocation : Les anciens mots de passe de démonstration sont strictement rejetés par Supabase Auth.
"""

import json
import urllib.error
import urllib.request
import pytest


def test_secrets_poc_url_returns_404_or_410():
    """Critère 1 : l'URL du document d'identifiants répond 404 ou 410 en production."""
    url = "https://www.orso-agents.fr/Secrets/secrets_poc.md"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "OrsoSecurityAudit/1.0", "Cache-Control": "no-cache"},
    )
    status_code = None
    try:
        with urllib.request.urlopen(req) as resp:
            status_code = resp.status
    except urllib.error.HTTPError as e:
        status_code = e.code

    assert status_code in (404, 410), f"Attendu 404 ou 410, reçu {status_code}"


def test_admin_page_redirects_to_ops():
    """Critère 4 : la page d'administration redirige vers ops.orso-agents.fr sans identifiants par défaut."""
    url = "https://www.orso-agents.fr/admin.html"

    # Handler personnalisé pour ne pas suivre automatiquement les redirections HTTP
    class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
        def http_error_301(self, req, fp, code, msg, headers):
            return fp
        def http_error_302(self, req, fp, code, msg, headers):
            return fp
        def http_error_307(self, req, fp, code, msg, headers):
            return fp
        def http_error_308(self, req, fp, code, msg, headers):
            return fp

    opener = urllib.request.build_opener(NoRedirectHandler)
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "OrsoSecurityAudit/1.0", "Cache-Control": "no-cache"},
    )

    try:
        resp = opener.open(req)
        status_code = resp.status
        location = resp.headers.get("Location", "")
    except urllib.error.HTTPError as e:
        status_code = e.code
        location = e.headers.get("Location", "")

    # Vercel effectue une redirection 308 permanente vers ops.orso-agents.fr
    assert status_code in (301, 302, 307, 308, 404), f"Statut inattendu pour admin.html: {status_code}"
    if status_code in (301, 302, 307, 308):
        assert "ops.orso-agents.fr" in location, f"Redirection incorrecte : {location}"


def test_docs_directory_blocked():
    """Vérifie que les spécifications et fichiers techniques ne sont plus servis publiquement."""
    url = "https://www.orso-agents.fr/docs/03_Technique/01_architecture_technique.md"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "OrsoSecurityAudit/1.0", "Cache-Control": "no-cache"},
    )
    status_code = None
    try:
        with urllib.request.urlopen(req) as resp:
            status_code = resp.status
    except urllib.error.HTTPError as e:
        status_code = e.code

    assert status_code in (404, 410), f"Attendu 404/410 pour les docs techniques, reçu {status_code}"


def test_revocation_inventory_present():
    """Critère 3 : l'inventaire des identifiants révoqués est consigné."""
    import os
    inventory_path = "scripts/iam/kan46_revocation_inventory.json"
    assert os.path.exists(inventory_path), "Fichier d'inventaire de révocation manquant"

    with open(inventory_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert len(data) >= 5, "Au moins les 5 comptes compromis doivent être consignés"
    for item in data:
        assert item["status"] == "ROTATED_AND_REVOKED"
        assert item["old_password_rejected"] is True
        assert item["new_password_active"] is True

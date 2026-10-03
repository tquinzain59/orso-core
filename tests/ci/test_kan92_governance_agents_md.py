"""Tests automatisés d'acceptation KAN-92 : Alignement d'AGENTS.md, Emplacement des Règles et Survie Amont."""

from __future__ import annotations

import os
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEV_PROJECTS = REPO_ROOT.parent


def test_ca2_agents_md_contains_all_operational_essentials():
    """CA2 : Vérifie que le fichier AGENTS.md chargé par l'environnement de l'agent
    porte bien l'intégralité des 6 essentiels opérationnels Orso et la clause de primauté."""
    agents_md = REPO_ROOT / "AGENTS.md"
    assert agents_md.exists(), "Le fichier AGENTS.md doit exister à la racine de orso-core"

    content = agents_md.read_text(encoding="utf-8")

    # 1. Balises d'ancrage Orso
    assert "<!-- ORSO_GOVERNANCE_START -->" in content
    assert "<!-- ORSO_GOVERNANCE_END -->" in content

    # 2. Source unique de vérité (Page Confluence 26)
    assert "Page Confluence 26 - Charte globale du développeur Orso agents" in content
    assert "https://orso-agents.atlassian.net/wiki/spaces/Orsoagents/pages/5668865" in content

    # 3. Clause de primauté absolue
    assert "Clause de primauté absolue" in content
    assert "les règles Orso prévalent impérativement" in content

    # 4. Séparation des rôles (Thibaut, Jarvis, Antigravity, Kimi K3)
    assert "Thibaut (Sponsor & Propriétaire du Produit)" in content
    assert "Jarvis (Product Owner)" in content
    assert "Antigravity (Architecte puis Développeur)" in content
    assert "Kimi K3 (Conseil et Contestation)" in content

    # 5. Règle d'arrêt stricte sur le Sanctuaire
    assert "Le Sanctuaire (Zone A - Interdit d'altération métier)" in content
    assert "Règle d'arrêt et de signalement immédiat" in content

    # 6. Conventions de branches et pull requests
    assert "KAN-<n>-<slug>" in content
    assert "[KAN-<n>]" in content
    assert "Zéro commit direct sur main" in content

    # 7. Definition of Ready (DoR) et Definition of Done (DoD)
    assert "Definition of Ready (DoR)" in content
    assert "Definition of Done (DoD)" in content
    assert "Un ticket est prêt quand" in content
    assert "Une livraison est terminée quand" in content

    # 8. Standard de preuve Handoff
    assert "Standard de Preuve & Section Handoff" in content
    assert "Mesure sur le code brut servi" in content

    # 9. Survie amont
    assert "Règle de Survie lors des Synchronisations Amont" in content


def test_ca3_and_ca7_multi_depots_entry_points():
    """CA3 & CA7 : Vérifie que tous les dépôts Orso (orso-site, orso-app, orso-docs)
    disposent de leur point d'entrée AGENTS.md explicite renvoyant vers la Page 26."""
    # 1. orso-site (Site_Hermes-core)
    site_agents = DEV_PROJECTS / "Site_Hermes-core" / "AGENTS.md"
    assert site_agents.exists(), "orso-site doit comporter un point d'entrée AGENTS.md"
    site_content = site_agents.read_text(encoding="utf-8")
    assert "Page Confluence 26 - Charte globale du développeur Orso agents" in site_content
    assert "KAN-<n>-<slug>" in site_content

    # 2. orso-app (App_Hermes Core)
    app_agents = DEV_PROJECTS / "App_Hermes Core" / "AGENTS.md"
    assert app_agents.exists(), "orso-app doit comporter un point d'entrée AGENTS.md"
    app_content = app_agents.read_text(encoding="utf-8")
    assert "Page Confluence 26 - Charte globale du développeur Orso agents" in app_content
    assert "KAN-<n>-<slug>" in app_content

    # 3. orso-docs (hermes-core)
    docs_agents = DEV_PROJECTS / "hermes-core" / "AGENTS.md"
    assert docs_agents.exists(), "orso-docs doit comporter une note d'interface AGENTS.md"
    docs_content = docs_agents.read_text(encoding="utf-8")
    assert "Page Confluence 26 - Charte globale du développeur Orso agents" in docs_content
    assert "Confluence est la source de vérité unique" in docs_content


def test_ca4_upstream_sync_block_extraction():
    """CA4 : Vérifie que le bloc de gouvernance Orso s'extrait hermétiquement
    et n'altère pas la syntaxe Markdown du guide amont Hermes conservé."""
    agents_md = REPO_ROOT / "AGENTS.md"
    content = agents_md.read_text(encoding="utf-8")

    start_idx = content.find("<!-- ORSO_GOVERNANCE_START -->")
    end_idx = content.find("<!-- ORSO_GOVERNANCE_END -->")

    assert start_idx != -1 and end_idx != -1
    assert start_idx < end_idx

    orso_block = content[start_idx:end_idx + len("<!-- ORSO_GOVERNANCE_END -->")]
    assert len(orso_block) > 1000

    # Vérification que le guide amont commence immédiatement après
    guide_part = content[end_idx + len("<!-- ORSO_GOVERNANCE_END -->"):].strip()
    assert guide_part.startswith("## Guide Amont Hermes Agent")
    assert "## What Hermes Is" in guide_part


def test_ca6_sanctuary_untouched():
    """CA6 : Contrôle formel qu'aucun fichier du Sanctuaire n'a été altéré."""
    import subprocess
    diff_res = subprocess.run(
        ["git", "diff", "--name-only", "origin/main...HEAD"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    changed_files = [f.strip() for f in diff_res.stdout.splitlines() if f.strip()]

    # Chemins sanctuarisés interdits d'altération
    sanctuary_prefixes = [
        "agent/turn_",
        "run_agent.py",
        "conversation_loop.py",
        "hermes_state",
        "providers/",
        "tools/registry.py",
    ]

    for f in changed_files:
        for prefix in sanctuary_prefixes:
            assert not f.startswith(prefix), f"Atteinte interdite au Sanctuaire détectée : {f}"

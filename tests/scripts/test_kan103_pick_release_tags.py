"""Tests d'acceptation et invariants KAN-103.

Vérifie :
1. Le comportement gracieux de scripts/sandbox/pick-release-tags.sh avec l'option --allow-empty
   lorsqu'aucune balise de release n'est présente (retour 0 et émission de '[]').
2. Le comportement fail-closed standard sans --allow-empty (code de sortie non nul).
3. La suspension formelle du déclencheur cron schedule dans .github/workflows/install-e2e.yml
   pour éviter les échecs automatiques bi-quotidiens sur le fork.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path


def test_pick_release_tags_allow_empty_on_empty_repo():
    """Vérifie que --allow-empty émet '[]' et sort avec code 0 sur un dépôt sans release tags."""
    script = Path(__file__).resolve().parent.parent.parent / "scripts" / "sandbox" / "pick-release-tags.sh"
    assert script.exists(), "Le script pick-release-tags.sh doit exister"

    with tempfile.TemporaryDirectory() as tmpdir:
        subprocess.run(["git", "init", tmpdir], check=True, capture_output=True)

        res = subprocess.run(
            ["bash", str(script), "--repo", tmpdir, "--allow-empty"],
            capture_output=True,
            text=True,
        )
        assert res.returncode == 0, f"Le script doit sortir avec code 0, stderr: {res.stderr}"
        output = res.stdout.strip()
        assert output == "[]", f"La sortie attendue est '[]', obtenu: {output}"


def test_pick_release_tags_fails_without_allow_empty_on_empty_repo():
    """Vérifie que sans --allow-empty, le script échoue sur un dépôt sans release tags."""
    script = Path(__file__).resolve().parent.parent.parent / "scripts" / "sandbox" / "pick-release-tags.sh"
    with tempfile.TemporaryDirectory() as tmpdir:
        subprocess.run(["git", "init", tmpdir], check=True, capture_output=True)

        res = subprocess.run(
            ["bash", str(script), "--repo", tmpdir],
            capture_output=True,
            text=True,
        )
        assert res.returncode != 0, "Le script doit échouer sans --allow-empty"
        assert "no release tags found" in res.stderr


def test_install_e2e_workflow_schedule_suspended_and_allow_empty_configured():
    """Vérifie que install-e2e.yml a suspendu le cron schedule et utilise --allow-empty."""
    workflow = Path(__file__).resolve().parent.parent.parent / ".github" / "workflows" / "install-e2e.yml"
    assert workflow.exists(), "Le fichier install-e2e.yml doit exister"

    content = workflow.read_text(encoding="utf-8")

    # Vérification que le bloc schedule actif n'est pas présent à la racine de 'on:'
    # Les lignes de schedule doivent être commentées
    lines = content.splitlines()
    active_schedule = False
    for line in lines:
        stripped = line.strip()
        if stripped == "schedule:":
            active_schedule = True
            break
    assert not active_schedule, "Le déclencheur schedule actif doit être suspendu (commenté)"

    # Vérification que pick-release-tags.sh est invoqué avec --allow-empty
    assert "--allow-empty" in content, "pick-release-tags.sh doit être appelé avec --allow-empty"
    assert "has_tags" in content, "Le job pick-releases doit exporter has_tags"

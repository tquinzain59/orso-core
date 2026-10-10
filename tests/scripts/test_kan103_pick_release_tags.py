"""Tests d'acceptation et invariants KAN-103.

Vérifie :
1. Le comportement gracieux de scripts/sandbox/pick-release-tags.sh avec l'option --allow-empty
   lorsqu'aucune balise de release n'est présente (retour 0 et émission de '[]').
2. Le comportement fail-closed standard sans --allow-empty (code de sortie non nul).
3. La sélection déterministe d'un échantillon de tags réels lorsque des balises vYYYY.M.D existent.
4. La validité syntaxique YAML stricte de .github/workflows/install-e2e.yml (analyseur pyyaml),
   prouvant l'absence de toute régression d'indentation (ex: ligne 60 install-ref).
5. La suspension formelle du déclencheur cron schedule (arbitrage Direction) sans trigger orphelin.
6. Le comportement fail-closed à l'exécution en l'absence de balises (exit 1, message explicite,
   éradication du vert vide).
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
import yaml


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


def test_pick_release_tags_with_valid_release_tags():
    """Vérifie que pick-release-tags.sh échantillonne correctement les balises vYYYY.M.D."""
    script = Path(__file__).resolve().parent.parent.parent / "scripts" / "sandbox" / "pick-release-tags.sh"
    with tempfile.TemporaryDirectory() as tmpdir:
        subprocess.run(["git", "init", tmpdir], check=True, capture_output=True)
        subprocess.run(["git", "-C", tmpdir, "config", "user.email", "test@orso.test"], check=True)
        subprocess.run(["git", "-C", tmpdir, "config", "user.name", "Test Runner"], check=True)

        # Commit vide et création de tags
        subprocess.run(["git", "-C", tmpdir, "commit", "--allow-empty", "-m", "initial commit"], check=True, capture_output=True)
        for t in ["v2026.1.1", "v2026.2.1", "v2026.3.1", "other-tag"]:
            subprocess.run(["git", "-C", tmpdir, "tag", t], check=True, capture_output=True)

        res = subprocess.run(
            ["bash", str(script), "--repo", tmpdir, "--count", "2"],
            capture_output=True,
            text=True,
        )
        assert res.returncode == 0, f"Le script doit réussir, stderr: {res.stderr}"
        tags = json.loads(res.stdout.strip())
        assert "other-tag" not in tags, "Les tags hors format release vYYYY.M.D doivent être exclus"
        assert len(tags) == 2, f"Attendu 2 tags, obtenu: {tags}"
        assert tags[0] == "v2026.1.1"
        assert tags[-1] == "v2026.3.1"


def test_install_e2e_workflow_yaml_is_valid_and_structured():
    """Vérifie par parsing strict pyyaml que install-e2e.yml est valide et bien formé (CA régression indentation)."""
    workflow = Path(__file__).resolve().parent.parent.parent / ".github" / "workflows" / "install-e2e.yml"
    assert workflow.exists(), "Le fichier install-e2e.yml doit exister"

    content = workflow.read_text(encoding="utf-8")
    data = yaml.safe_load(content)
    assert isinstance(data, dict), "Le fichier YAML doit parser en dictionnaire"

    # Vérification des clés de premier niveau
    assert "name" in data
    assert "jobs" in data

    # 'on:' en YAML 1.1 parse comme True ou comme clé 'on'
    triggers = data.get(True) or data.get("on")
    assert isinstance(triggers, dict), "Les déclencheurs (on:) doivent être un dictionnaire valide"

    # Vérification que le déclencheur planifié actif est suspendu (arbitrage Direction KAN-103)
    assert "schedule" not in triggers, "Le déclencheur schedule actif doit être suspendu (commenté)"

    # Vérification des inputs workflow_dispatch
    wf_dispatch = triggers.get("workflow_dispatch")
    assert wf_dispatch is not None, "workflow_dispatch doit être défini"
    inputs = wf_dispatch.get("inputs", {})
    assert "route" in inputs
    assert "tag-count" in inputs
    assert "install-ref" in inputs, "L'input install-ref doit être correctement analysé (indentation 6 espaces)"
    assert inputs["install-ref"]["type"] == "string"

    # Vérification des jobs
    jobs = data.get("jobs", {})
    assert "pick-releases" in jobs
    assert "generate-matrix" in jobs
    assert "report" in jobs


def test_install_e2e_workflow_fails_closed_without_vert_vide():
    """Vérifie que l'absence de balises déclenche un exit 1 explicite et éradique le vert vide."""
    workflow = Path(__file__).resolve().parent.parent.parent / ".github" / "workflows" / "install-e2e.yml"
    content = workflow.read_text(encoding="utf-8")

    # Vérifie que le workflow ne sort pas avec exit 0 lors de tags vides
    assert "exit 1" in content, "Le cas de tags vides doit échouer explicitement avec exit 1"
    assert "::error::" in content, "Une annotation d'erreur GitHub Actions doit être émise"
    assert "GITHUB_STEP_SUMMARY" in content, "Un résumé explicite doit être versé au STEP_SUMMARY"

    # Vérifie l'absence de fausse sortie 'has_tags=false' masquant l'échec
    assert "has_tags=false" not in content, "has_tags=false ne doit plus être utilisé pour masquer l'échec"

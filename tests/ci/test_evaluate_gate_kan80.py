"""Tests unitaires et d'acceptation pour scripts/ci/evaluate_gate.py (KAN-80).

Valide formellement CA1 (aucun vert vide en cas d'annulation) et CA2 (nommage exhaustif
des contrôles exécutés, sautés et annulés).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.ci.evaluate_gate import evaluate_needs


def test_evaluate_gate_cancelled_fails_closed():
    """CA1: Une exécution annulée ne doit jamais rendre un verdict de succès (pas de vert vide)."""
    # Reproduction fidèle de l'incident du 02/10/2026 (run 37029645868 tentative 1)
    needs_data = {
        "detect": {"result": "cancelled"},
        "osv-scanner": {"result": "success"},
        "tests": {"result": "skipped"},
        "tests-os": {"result": "skipped"},
        "lint": {"result": "skipped"},
        "js-tests": {"result": "skipped"},
        "docs-site": {"result": "skipped"},
    }

    exit_code, metrics, log_lines = evaluate_needs(needs_data)

    assert exit_code == 1, "Une exécution avec job annulé DOIT sortir avec le code retour 1"
    assert metrics["cancelled"] == 1
    assert "detect" in metrics["cancelled_jobs"]
    assert any("::error::Gate failed: 1 job(s) were cancelled: detect" in line for line in log_lines)
    assert any("Verdict: FAIL" in line for line in log_lines)


def test_evaluate_gate_empty_run_fails_closed():
    """Un run vide (0 contrôle exécuté, tout sauté) ne doit pas rendre un vert vide."""
    needs_data = {
        "detect": {"result": "skipped"},
        "tests": {"result": "skipped"},
        "lint": {"result": "skipped"},
    }

    exit_code, metrics, log_lines = evaluate_needs(needs_data)

    assert exit_code == 1, "Un run vide DOIT sortir avec le code retour 1"
    assert metrics["executed"] == 0
    assert any("::error::Gate failed: empty run" in line for line in log_lines)
    assert any("Verdict: FAIL" in line for line in log_lines)


def test_evaluate_gate_failure_fails_closed():
    """Un run avec au moins un échec doit sortir en code 1."""
    needs_data = {
        "detect": {"result": "success"},
        "tests": {"result": "failure"},
        "lint": {"result": "success"},
        "docs-site": {"result": "skipped"},
    }

    exit_code, metrics, log_lines = evaluate_needs(needs_data)

    assert exit_code == 1
    assert metrics["failure"] == 1
    assert "tests" in metrics["failure_jobs"]
    assert any("::error::Gate failed: 1 job(s) failed: tests" in line for line in log_lines)


def test_evaluate_gate_nominal_pass_ca2():
    """CA2: Le verdict de la porte nomme ce qui a tourné et valide une exécution complète."""
    needs_data = {
        "detect": {"result": "success"},
        "osv-scanner": {"result": "success"},
        "tests": {"result": "success"},
        "tests-os": {"result": "success"},
        "lint": {"result": "success"},
        "js-tests": {"result": "skipped"},
        "docs-site": {"result": "skipped"},
    }

    exit_code, metrics, log_lines = evaluate_needs(needs_data)

    assert exit_code == 0, "Une exécution nominale complète DOIT sortir avec le code 0"
    assert metrics["executed"] == 5
    assert metrics["success"] == 5
    assert metrics["failure"] == 0
    assert metrics["cancelled"] == 0
    assert metrics["skipped"] == 2

    # Assertion CA2: nommage de ce qui a tourné
    expected_verdict = "Verdict: PASS — 5 executed (5 success, 0 failure), 2 skipped, 0 cancelled"
    assert any(expected_verdict in line for line in log_lines)


def test_evaluate_gate_cli_subprocess(tmp_path: Path):
    """Test d'intégration E2E du script CLI via stdin et variables d'environnement GitHub."""
    script_path = Path(__file__).resolve().parents[2] / "scripts" / "ci" / "evaluate_gate.py"
    github_output = tmp_path / "github_output.txt"
    github_summary = tmp_path / "step_summary.md"

    # Cas 1 : Annulation (doit échouer avec code 1)
    needs_cancelled = json.dumps({
        "detect": {"result": "cancelled"},
        "tests": {"result": "skipped"},
    })

    env = {
        **os.environ,
        "GITHUB_OUTPUT": str(github_output),
        "GITHUB_STEP_SUMMARY": str(github_summary),
    }

    proc = subprocess.run(
        [sys.executable, str(script_path)],
        input=needs_cancelled,
        text=True,
        capture_output=True,
        env=env,
    )
    assert proc.returncode == 1
    assert "::error::Gate failed: 1 job(s) were cancelled: detect" in proc.stdout
    assert "Verdict: FAIL" in proc.stdout

    # Vérification émission compacte needs-json pour les outils avals
    output_content = github_output.read_text(encoding="utf-8")
    assert 'needs-json={"detect": "cancelled", "tests": "skipped"}' in output_content

    # Vérification GITHUB_STEP_SUMMARY
    summary_content = github_summary.read_text(encoding="utf-8")
    assert "ÉCHEC (ANNULÉ)" in summary_content
    assert "Contrôles annulés" in summary_content

    # Cas 2 : Succès nominal (doit sortir avec code 0)
    github_output.unlink()
    github_summary.unlink()

    needs_success = json.dumps({
        "detect": {"result": "success"},
        "tests": {"result": "success"},
        "lint": {"result": "skipped"},
    })

    proc = subprocess.run(
        [sys.executable, str(script_path)],
        input=needs_success,
        text=True,
        capture_output=True,
        env=env,
    )
    assert proc.returncode == 0
    assert "Verdict: PASS — 2 executed (2 success, 0 failure), 1 skipped, 0 cancelled" in proc.stdout

    summary_content = github_summary.read_text(encoding="utf-8")
    assert "PASS" in summary_content

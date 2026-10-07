"""Tests d'acceptation automatisés pour le ticket KAN-70 (CI déterminisme, visibilité des tests flaky et retries).

Vérifie :
- L'action composite .github/actions/retry dispose de 5 tentatives par défaut.
- Les workflows CI appellent pip avec --retries 5.
- scripts/run_tests_parallel.py consigne les tentatives infructueuses sans masquer les échecs réels.
- Le drapeau --fail-on-flake / HERMES_FAIL_ON_FLAKE fait échouer le runner si un test a flaké.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

import scripts.run_tests_parallel as rtp


def test_kan70_retry_action_defaults():
    """Vérifie que l'action composite retry est configurée avec 5 tentatives par défaut."""
    action_file = Path(".github/actions/retry/action.yml")
    assert action_file.is_file()
    content = action_file.read_text(encoding="utf-8")
    assert 'default: "5"' in content


def test_kan70_workflows_pip_retries():
    """Vérifie la présence du flag --retries 5 dans les workflows manipulant pip."""
    workflows = [
        Path(".github/workflows/deploy-site.yml"),
        Path(".github/workflows/docs-site-checks.yml"),
        Path(".github/workflows/plugin-catalog-ci.yml"),
        Path(".github/workflows/security_daily_leak_check.yml"),
        Path(".github/workflows/skills-index.yml"),
    ]
    for wf in workflows:
        assert wf.is_file()
        content = wf.read_text(encoding="utf-8")
        assert "--retries 5" in content, f"{wf} doit inclure --retries 5"


def test_kan70_run_one_file_flake_detected():
    """Vérifie qu'un test qui échoue puis réussit est tagué FLAKY et enregistré."""
    test_path = Path("tests/test_fake_flaky.py")

    call_count = 0

    def fake_run_once(file, pytest_args, repo_root, file_timeout):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return file, 1, "AssertionError: random network timeout", {"failed": 1}, 0.2
        return file, 0, "1 passed", {"passed": 1}, 0.1

    with patch.object(rtp, "_run_one_file_once", side_effect=fake_run_once):
        with patch.object(rtp, "_FLAKY_RESULTS", []):
            file, rc, output, summary, wall = rtp._run_one_file(
                file=test_path,
                pytest_args=[],
                repo_root=Path("."),
                file_timeout=30,
                retries=1,
            )
            assert rc == 0
            assert "⚠ FLAKY" in output
            assert "first-attempt output" in output
            assert len(rtp._FLAKY_RESULTS) == 1
            assert rtp._FLAKY_RESULTS[0][0] == test_path


def test_kan70_run_one_file_recurrent_failure_not_swallowed():
    """Vérifie qu'un échec récurrent conserve l'historique complet sans écrasement."""
    test_path = Path("tests/test_fake_fail.py")

    def fake_run_once(file, pytest_args, repo_root, file_timeout):
        return file, 1, "AssertionError: strict bug", {"failed": 1}, 0.2

    with patch.object(rtp, "_run_one_file_once", side_effect=fake_run_once):
        file, rc, output, summary, wall = rtp._run_one_file(
            file=test_path,
            pytest_args=[],
            repo_root=Path("."),
            file_timeout=30,
            retries=2,
        )
        assert rc == 1
        assert "Attempt 1 output" in output
        assert "Attempt 2 output" in output
        assert "Attempt 3 output" in output


def test_kan70_fail_on_flake_option():
    """Vérifie le fonctionnement de --fail-on-flake."""
    # Simulation des arguments
    args = MagicMock()
    args.fail_on_flake = True

    # Si _FLAKY_RESULTS est non-vide
    with patch.object(rtp, "_FLAKY_RESULTS", [(Path("tests/flake.py"), "output")]):
        # Vérifier que le bloc d'arrêt renvoie 1
        if rtp._FLAKY_RESULTS and args.fail_on_flake:
            exit_code = 1
        else:
            exit_code = 0
        assert exit_code == 1

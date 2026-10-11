"""KAN-55 : un cas de test par motif du contrôle de fuite, plus fichiers interdits et historique.

Aucune valeur secrète n'est écrite en dur ici : les valeurs de test sont
assemblées à l'exécution à partir de fragments, pour que ce fichier ne soit
lui-même détecté ni dans l'arbre ni dans l'historique.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "security" / "check_no_secrets.py"
_spec = importlib.util.spec_from_file_location("check_no_secrets", _SCRIPT)
cns = importlib.util.module_from_spec(_spec)
sys.modules["check_no_secrets"] = cns
_spec.loader.exec_module(cns)

# Valeurs factices assemblées à l'exécution (jamais présentes telles quelles dans le source).
SAMPLES = {
    "jeton_github": "gh" + "p_" + "A1b2C3d4" * 5,
    "cle_stripe_live": "sk" + "_live_" + "Z9y8X7w6" * 3,
    "cle_privee": "-----BEGIN " + "RSA PRIVATE" + " KEY-----",
    "identifiants_par_defaut": "admin" + ":" + "admin",
    "mot_de_passe_temporaire": "Temp" + "Demo" + "20" + "26",
}


def _write(root: Path, rel: str, content: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _run(root: Path, *extra: str) -> int:
    return cns.main(["--root", str(root), "--no-history", *extra])


def test_every_pattern_has_a_sample():
    assert {p.name for p in cns.PATTERNS} == set(SAMPLES)


@pytest.mark.parametrize("name", sorted(SAMPLES))
def test_pattern_detected_quoted(name, tmp_path, capsys):
    _write(tmp_path, "app/config.py", f'SERVICE_VALUE = "{SAMPLES[name]}"\n')
    assert _run(tmp_path) == 1
    assert f"motif {name}" in capsys.readouterr().out


@pytest.mark.parametrize("name", sorted(SAMPLES))
def test_pattern_detected_unquoted_other_variable_name(name, tmp_path, capsys):
    """CA3 : même valeur, sans guillemets, sous un autre nom de variable, autre extension."""
    _write(tmp_path, "deploy/settings.env", f"UNRELATED_NAME={SAMPLES[name]}\n")
    assert _run(tmp_path) == 1
    assert f"motif {name}" in capsys.readouterr().out


@pytest.mark.parametrize("rel", ["Secrets/secrets_poc.md", "docs/04_Secrets/note.md", "admin.html", "public/monitoring.html"])
def test_forbidden_paths_fail(rel, tmp_path, capsys):
    """CA1 : les fichiers interdits retirés du workflow sont de retour dans le contrôle."""
    _write(tmp_path, rel, "contenu inoffensif\n")
    assert _run(tmp_path) == 1
    assert "interdit" in capsys.readouterr().out


def test_clean_tree_passes(tmp_path):
    _write(tmp_path, "README.md", "rien à signaler, admin:administrateur et sk_live_ sans suite\n")
    assert _run(tmp_path) == 0


def test_binary_file_is_skipped(tmp_path):
    (tmp_path / "blob.bin").write_bytes(b"\0\0" + SAMPLES["jeton_github"].encode())
    assert _run(tmp_path) == 0


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(root), "-c", "user.email=t@example.invalid", "-c", "user.name=t", *args],
        check=True,
        capture_output=True,
    )


def test_history_enabled_by_default_and_detects_removed_secret(tmp_path, capsys):
    """CA2 : la valeur a disparu de l'arbre mais reste dans l'historique ; aucun flag nécessaire."""
    _git(tmp_path, "init", "-q")
    _write(tmp_path, "notes.txt", f"valeur {SAMPLES['jeton_github']}\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "ajout")
    _write(tmp_path, "notes.txt", "nettoyé\n")
    _git(tmp_path, "commit", "-qam", "purge")

    assert cns.main(["--root", str(tmp_path)]) == 1  # pas de --no-history
    out = capsys.readouterr().out
    assert "[history] analyse de l'historique" in out
    assert "[history]" in out and "motif jeton_github" in out
    assert cns.main(["--root", str(tmp_path), "--no-history"]) == 0


def test_history_allowlist_tolerates_known_commit(tmp_path):
    _git(tmp_path, "init", "-q")
    _write(tmp_path, "notes.txt", f"{SAMPLES['cle_stripe_live']}\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "ajout")
    sha = subprocess.run(
        ["git", "-C", str(tmp_path), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    _write(tmp_path, "notes.txt", "nettoyé\n")
    _git(tmp_path, "commit", "-qam", "purge")
    allow = tmp_path.parent / f"{tmp_path.name}-allow.txt"
    allow.write_text(f"history {sha[:12]} # incident clos, identifiants révoqués\n", encoding="utf-8")
    assert cns.main(["--root", str(tmp_path), "--allowlist", str(allow)]) == 0


def test_history_without_git_repo_is_an_error_not_a_pass(tmp_path):
    assert cns.main(["--root", str(tmp_path)]) == 2

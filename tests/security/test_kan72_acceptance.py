"""Tests d'acceptation stricts pour le ticket KAN-72.

Valide les critères d'acceptation (CA1, CA2, CA3) et les contraintes de gouvernance :
- CA1 : Absence de tout fichier dans le dépôt publiant, transitionnant ou créant un ticket Atlassian
- CA1 : Absence de manipulation des variables ATLASSIAN_ dans scripts/
- CA2 : Le fichier scripts/publish_kan43_atlassian.py n'existe plus
- CA3 / Hygiène : Durcissement inviolable de .gitignore interdisant tout outillage Atlassian
"""

from pathlib import Path
import re
import subprocess


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def test_kan72_ca1_no_atlassian_publication_scripts_in_repository():
    """CA1 — Une recherche des motifs Atlassian dans scripts/ ne rend aucun fichier de publication/transition."""
    scripts_dir = PROJECT_ROOT / "scripts"
    assert scripts_dir.is_dir()

    forbidden_patterns = [
        re.compile(r"atlassian\.net", re.IGNORECASE),
        re.compile(r"/rest/api/3/issue"),
        re.compile(r"/transitions"),
        re.compile(r"/wiki/rest/api"),
    ]

    violating_files = []
    for py_file in scripts_dir.rglob("*.py"):
        # Les scripts d'intégration CI GitHub ne ciblent pas Atlassian
        content = py_file.read_text(encoding="utf-8", errors="replace")
        for pattern in forbidden_patterns:
            if pattern.search(content):
                # Vérifier si c'est une fausse alerte (ex: GitHub issues dans scripts/ci)
                if "github.com" in content and "atlassian" not in content.lower():
                    continue
                violating_files.append((str(py_file.relative_to(PROJECT_ROOT)), pattern.pattern))

    assert not violating_files, f"Fichiers publiant vers Atlassian trouvés dans scripts/ : {violating_files}"


def test_kan72_ca1_no_atlassian_env_vars_read_in_scripts():
    """CA1 — Aucun script dans scripts/ ne lit de variables ATLASSIAN_EMAIL ou ATLASSIAN_API_TOKEN."""
    scripts_dir = PROJECT_ROOT / "scripts"
    env_pattern = re.compile(r'os\.environ\.get\(["\']ATLASSIAN_')

    violating_files = []
    for py_file in scripts_dir.rglob("*.py"):
        content = py_file.read_text(encoding="utf-8", errors="replace")
        if env_pattern.search(content):
            violating_files.append(str(py_file.relative_to(PROJECT_ROOT)))

    assert not violating_files, f"Variables ATLASSIAN_ lues dans les scripts suivants : {violating_files}"


def test_kan72_ca2_publish_kan43_script_is_deleted():
    """CA2 — Le fichier scripts/publish_kan43_atlassian.py n'existe plus physiquement ni dans git."""
    target_script = PROJECT_ROOT / "scripts" / "publish_kan43_atlassian.py"
    assert not target_script.exists(), "Le fichier scripts/publish_kan43_atlassian.py ne doit plus exister"

    # Vérification que Git ne suit plus ce fichier
    res = subprocess.run(
        ["git", "ls-files", "scripts/publish_kan43_atlassian.py"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0
    assert res.stdout.strip() == "", "scripts/publish_kan43_atlassian.py est encore suivi par Git"


def test_kan72_ca3_gitignore_strictly_blocks_atlassian_tools():
    """CA3 / Hygiène — .gitignore bloque tous les scripts publish et sync Atlassian sans dérogation."""
    gitignore_file = PROJECT_ROOT / ".gitignore"
    assert gitignore_file.is_file()

    content = gitignore_file.read_text(encoding="utf-8")
    assert "scripts/publish_*.py" in content
    assert "scripts/sync_confluence_*.py" in content
    assert "scripts/*atlassian*.py" in content
    assert "!scripts/publish_kan59_atlassian.py" not in content, "L'exception dérogatoire KAN-59 doit être retirée"

"""Contract and functional tests for the sync-agent-skills DevOps skill."""

from __future__ import annotations

import re
import tempfile
import importlib.util
from pathlib import Path
import pytest

SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "skills"
    / "devops"
    / "sync-agent-skills"
    / "scripts"
    / "repatriate_agent.py"
)
spec = importlib.util.spec_from_file_location("repatriate_agent", SCRIPT_PATH)
repatriate_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(repatriate_module)
AgentRepatriator = repatriate_module.AgentRepatriator

SKILL_MD = (
    Path(__file__).resolve().parents[2]
    / "skills"
    / "devops"
    / "sync-agent-skills"
    / "SKILL.md"
)

REQUIRED_SECTIONS = [
    "## When to Use",
    "## Prerequisites",
    "## How to Run",
    "## Quick Reference",
    "## Procedure",
    "## Pitfalls",
    "## Verification",
]


@pytest.fixture(scope="module")
def skill_text() -> str:
    return SKILL_MD.read_text(encoding="utf-8")


def _frontmatter_value(text: str, key: str) -> str:
    match = re.search(rf"^{re.escape(key)}:\s*(.+)$", text, re.MULTILINE)
    assert match, f"missing frontmatter field: {key}"
    return match.group(1).strip()


def test_frontmatter_meets_authoring_standard(skill_text: str) -> None:
    assert skill_text.startswith("---\n")
    assert _frontmatter_value(skill_text, "name") == "sync-agent-skills"

    description = _frontmatter_value(skill_text, "description")
    assert len(description) <= 60, f"Description trop longue ({len(description)} > 60 chars)"
    assert description.endswith("."), "La description doit se terminer par un point."

    for field in ("version", "author", "license", "platforms"):
        assert _frontmatter_value(skill_text, field)


def test_body_uses_required_section_order(skill_text: str) -> None:
    last_idx = -1
    for section in REQUIRED_SECTIONS:
        idx = skill_text.find(section)
        assert idx != -1, f"Section manquante : {section}"
        assert idx > last_idx, f"Section {section} dans un ordre incorrect."
        last_idx = idx


def test_repatriator_copies_skills_and_sanitizes_secrets() -> None:
    with tempfile.TemporaryDirectory() as tmp_src, tempfile.TemporaryDirectory() as tmp_dst:
        src_path = Path(tmp_src)
        dst_path = Path(tmp_dst)

        # 1. Mise en place de la fausse arborescence source de l'agent
        skills_dir = src_path / "skills" / "compta" / "mon-erp"
        skills_dir.mkdir(parents=True, exist_ok=True)
        (skills_dir / "SKILL.md").write_text(
            "---\nname: mon-erp\ndescription: Test.\n---\n# Test\nexport ODOO_URL=\"http://localhost:8069\"\n",
            encoding="utf-8",
        )
        dummy_token = "sk-" + "or-v1-" + ("0123456789abcdef" * 4)
        (skills_dir / "connector.py").write_text(
            f'token = "{dummy_token}"\nprint("Connecte")\n',
            encoding="utf-8",
        )


        # Fichiers sensibles qui doivent être exclus
        (src_path / ".env").write_text("ODOO_PASSWORD=mon_mot_de_passe_secret\n", encoding="utf-8")
        (src_path / "auth.json").write_text('{"token": "secret_cookie"}', encoding="utf-8")

        # Mémoires et personnalités à conserver
        mem_dir = src_path / "memories"
        mem_dir.mkdir(parents=True, exist_ok=True)
        (mem_dir / "USER.md").write_text("# Directives Credit Management\n- Toujours relancer avec politesse.", encoding="utf-8")
        (src_path / "SOUL.md").write_text("Tu es Jerome, assistant recouvrement.", encoding="utf-8")

        # 2. Exécution du rapatriement
        repatriator = AgentRepatriator(
            source_dir=src_path,
            target_root=dst_path,
            agent_id="jerome",
            sanitize=True,
            dry_run=False,
            export_shared=True,
        )
        report = repatriator.repatriate()

        # 3. Assertions sur le succès du rapatriement
        target_jerome = dst_path / "profiles" / "jerome"
        assert (target_jerome / "skills" / "compta" / "mon-erp" / "SKILL.md").is_file()
        assert (target_jerome / "memories" / "USER.md").is_file()
        assert (target_jerome / "SOUL.md").is_file()

        # Export partagé
        assert (dst_path / "skills" / "compta" / "mon-erp" / "SKILL.md").is_file()

        # 4. Assertions STRICTES sur la sécurité et la désensibilisation
        # Le fichier .env et auth.json ne DOIVENT PAS exister dans la cible
        assert not (target_jerome / ".env").exists()
        assert not (target_jerome / "auth.json").exists()
        assert not (dst_path / ".env").exists()

        # Le token dans connector.py doit avoir été expurgé / caviardé
        copied_script = (target_jerome / "skills" / "compta" / "mon-erp" / "connector.py").read_text(encoding="utf-8")
        assert "0123456789abcdef" not in copied_script
        assert "REDACTED" in copied_script

        # Le gabarit .env.example doit avoir été généré avec ODOO_URL sans aucune valeur sensible
        env_example = target_jerome / ".env.example"
        assert env_example.is_file()
        env_content = env_example.read_text(encoding="utf-8")
        assert "ODOO_URL=" in env_content
        assert "mon_mot_de_passe_secret" not in env_content

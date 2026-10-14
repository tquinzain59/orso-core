"""KAN-64 (amendement du 12/10/2026) : contrats des deux écarts résiduels."""

import os
import subprocess
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
MANAGER = REPO_ROOT / "scripts" / "distribution" / "engine_image_manager.py"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "publish_orso_engine.yml"
VALID_DIGEST = "sha256:" + "ab" * 32


def _run_cli(*args: str, env_digest: str | None) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k != "ORSO_TARGET_ENGINE_DIGEST"}
    if env_digest is not None:
        env["ORSO_TARGET_ENGINE_DIGEST"] = env_digest
    return subprocess.run(
        [sys.executable, str(MANAGER), *args],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_cli_fails_explicitly_without_target_digest():
    """Sans option ni variable, aucune valeur de démonstration n'est utilisée."""
    for argv, env_digest in ((("audit", "--local"), None), (("audit", "--local"), "")):
        res = _run_cli(*argv, env_digest=env_digest)
        assert res.returncode == 2
        assert "ORSO_TARGET_ENGINE_DIGEST" in res.stderr
        assert "Dérive" not in res.stdout and res.stdout.strip() == ""


def test_cli_accepts_digest_from_env_and_option_without_demo_fallback():
    """Le digest fourni par l'environnement franchit la porte (pas d'erreur d'argument)."""
    for env_digest, argv in (
        (VALID_DIGEST, ("probe", "--local")),
        (None, ("--target-digest", VALID_DIGEST, "probe", "--local")),
    ):
        res = _run_cli(*argv, env_digest=env_digest)
        assert "digest cible absent" not in res.stderr
        assert res.returncode != 2


def test_publish_workflow_has_no_floating_tag():
    """La publication se fait par digest : aucune étiquette flottante `latest`."""
    wf = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    steps = wf["jobs"]["publish-engine"]["steps"]
    meta = next(s for s in steps if s.get("id") == "meta")
    tag_rules = [ln.strip() for ln in meta["with"]["tags"].splitlines() if ln.strip()]
    assert tag_rules, "des étiquettes humaines doivent subsister"
    assert not any(
        rule.endswith("value=latest") or "latest" in rule for rule in tag_rules
    )

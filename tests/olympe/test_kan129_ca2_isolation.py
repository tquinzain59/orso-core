"""KAN-129 / CA2 — isolation entre exécutions simultanées d'un même client.

Contrats vérifiés sans démon Docker, sur le vrai code du moteur :
- le moteur ne donne un conteneur par exécution que pour ``container_persistent: false`` ; le défaut moteur
  (persistant) ramène toutes les sessions d'un client sur un seul conteneur ;
- la recette constate une interférence réelle sur le backend ``local`` (celui d'un conteneur client dont la
  config n'a pas de section ``terminal``) ;
- une recette qui n'a pas pu s'exécuter n'est jamais verte.

La preuve d'isolation elle-même (backend docker) exige un démon : ``scripts/sandbox_ca2_recette.py``.
"""

from __future__ import annotations

import re
import tempfile

import pytest

from olympe.execution_isolation import (
    INTERFERENCE,
    ISOLATED,
    NOT_VERIFIED,
    REQUIRED_TERMINAL_SETTINGS,
    execution_isolation_gaps,
    is_digest_pinned,
    run_isolation_probe,
)


class _FakeEnv:
    """Environnement simulé ; ``shared`` non nul = système de fichiers partagé entre exécutions."""

    def __init__(self, idx, shared=None, host=None):
        self.idx = idx
        self.files = shared if shared is not None else set()
        self.host = host or f"host-{idx}"
        self.state = None

    def execute(self, cmd, **_):
        m = re.match(r"echo marker-(\d+) > (\S+)", cmd)
        if m:
            self.files.add(m.group(2))
            self.state = f"state-{m.group(1)}"
            return {"output": "", "returncode": 0}
        if cmd.startswith("ls "):
            out = [*sorted(self.files), f"STATE={self.state}", f"HOST={self.host}"]
            return {"output": "\n".join(out), "returncode": 0}
        return {"output": "", "returncode": 0}

    def cleanup(self):
        pass


def test_engine_scopes_one_container_per_execution_only_when_not_persistent(monkeypatch):
    pytest.importorskip("requests")
    from tools import terminal_tool as tt

    monkeypatch.setenv("TERMINAL_ENV", "docker")
    monkeypatch.setenv("TERMINAL_CONTAINER_PERSISTENT", "true")
    persistent = {tt._resolve_container_task_id("exec-A"), tt._resolve_container_task_id("exec-B")}
    monkeypatch.setenv("TERMINAL_CONTAINER_PERSISTENT", "false")
    isolated = {tt._resolve_container_task_id("exec-A"), tt._resolve_container_task_id("exec-B")}

    assert len(persistent) == 1, "défaut moteur : deux exécutions partagent un conteneur"
    assert len(isolated) == 2, "container_persistent=false : un conteneur par exécution"


def test_probe_detects_real_interference_on_local_backend():
    pytest.importorskip("requests")
    from tools.environments.local import LocalEnvironment

    cwd = tempfile.mkdtemp(prefix="orso_ca2_test_")
    report = run_isolation_probe(lambda i: LocalEnvironment(cwd=cwd, timeout=30), parallel=2)

    assert report.verdict == INTERFERENCE
    assert report.exit_code == 1
    assert any("fichiers" in f for f in report.findings)


def test_probe_isolated_when_each_execution_has_its_own_world():
    report = run_isolation_probe(lambda i: _FakeEnv(i), parallel=2)
    assert report.verdict == ISOLATED, report.findings
    assert report.exit_code == 0


def test_probe_flags_shared_filesystem_and_host():
    shared: set = set()
    report = run_isolation_probe(lambda i: _FakeEnv(i, shared=shared, host="same"), parallel=2)
    assert report.verdict == INTERFERENCE
    assert any("hôte partagée" in f for f in report.findings)


def test_probe_never_green_when_backend_unavailable():
    def boom(i):
        raise RuntimeError("docker indisponible")

    report = run_isolation_probe(boom, parallel=2)
    assert report.verdict == NOT_VERIFIED
    assert report.exit_code != 0

    assert run_isolation_probe(lambda i: _FakeEnv(i), parallel=1).verdict == NOT_VERIFIED


def test_gaps_empty_config_is_not_isolated_and_required_settings_pass():
    assert len(execution_isolation_gaps(None)) == 2
    assert len(execution_isolation_gaps({"backend": "docker"})) == 1
    assert execution_isolation_gaps(dict(REQUIRED_TERMINAL_SETTINGS)) == []


def test_digest_pin_detection():
    assert is_digest_pinned("repo/img@sha256:" + "a" * 64)
    assert not is_digest_pinned("repo/img:latest")
    assert not is_digest_pinned("repo/img@sha256:abc")

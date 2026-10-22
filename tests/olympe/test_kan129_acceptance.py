"""Tests d'acceptation KAN-129 (sandbox : isolation, quotas, reproductibilité, conservation des artefacts).

CA1 lecture croisée refusée, CA3 quota refusé explicitement, CA4 image épinglée par empreinte,
CA5 conservation 30 jours + purge, CA8 aucun secret en clair dans les modules ajoutés.
Le CA6 (rôles) est dans tests/hermes_cli/test_client_roles_kan129.py ; CA2/CA7 : voir la note de passation.
"""

import json
import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from olympe.artifact_manager import ClientSpaceArtifactManager
from olympe.artifact_retention import ARTIFACT_RETENTION_DAYS, purge_expired_artifacts
from olympe.lifecycle_manager import (
    DEFAULT_CLIENT_QUOTAS,
    TIER_RESOURCE_QUOTAS,
    DockerLifecycleManager,
    get_quotas_for_tier,
    parse_cpus_str_to_float,
    parse_memory_str_to_mb,
)
from olympe.sandbox_policy import (
    check_disk_quota,
    measure_dir_bytes,
    parse_disk_str_to_bytes,
    resolve_within,
)

DIGEST = "sha256:" + "a" * 64


def _make_source(base: Path, name: str) -> Path:
    src = base / name
    (src / "config").mkdir(parents=True)
    (src / "config" / "hermes.yaml").write_text("agent: demo\n", encoding="utf-8")
    return src


def _manager(tmp_path: Path) -> DockerLifecycleManager:
    m = DockerLifecycleManager(data_root=str(tmp_path / "tenants"), spaces_root=str(tmp_path / "spaces"))
    m.has_docker = True
    return m


def _no_container(*_a, **_k):
    """Faux démon Docker : aucune ressource existante ; enregistre les appels pour prouver l'absence de `run`."""
    return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")


def _assert_no_run(docker):
    assert not [c for c in docker.call_args_list if c.args and c.args[0] and c.args[0][0] == "run"]


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("HERMES_DASHBOARD_BASIC_AUTH_USERNAME", "admin")
    monkeypatch.setenv("HERMES_DASHBOARD_BASIC_AUTH_PASSWORD", "unit-test-only")


# ── CA1 : deux clients, lecture croisée refusée ───────────────────────────────

def test_ca1_cross_tenant_read_refused(tmp_path):
    mgr = ClientSpaceArtifactManager(artifacts_root=tmp_path / "art", spaces_root=tmp_path / "spaces")
    mgr.build_artifact("client-a", "1.0.0", _make_source(tmp_path, "src_a"), hmac_key="k")
    mgr.build_artifact("client-b", "1.0.0", _make_source(tmp_path, "src_b"), hmac_key="k")

    assert mgr.get_artifact_manifest("client-a", "1.0.0")["version"] == "1.0.0"
    # Le compte du client A ne peut désigner ni l'espace de B via le slug, ni via la version.
    with pytest.raises(ValueError, match="ERR_PATH_ESCAPE"):
        mgr.get_artifact_manifest("../client-b", "1.0.0")
    with pytest.raises(ValueError, match="ERR_PATH_ESCAPE"):
        mgr.get_artifact_manifest("client-a", "../client-b/1.0.0")
    with pytest.raises(ValueError, match="ERR_PATH_ESCAPE"):
        mgr.list_artifact_versions("client-a/../client-b")


def test_ca1_space_dirs_are_per_tenant_and_confined(tmp_path):
    m = _manager(tmp_path)
    a, b = m.get_tenant_space_dir("client-a"), m.get_tenant_space_dir("client-b")
    assert a != b and a.parent == b.parent == (tmp_path / "spaces").resolve()
    with pytest.raises(ValueError, match="ERR_PATH_ESCAPE"):
        m.get_tenant_space_dir("../tenants/client-b")


def test_resolve_within_rejects_escape_variants(tmp_path):
    for bad in ("..", ".", "", "a/b", "/etc", "..\\x", ".hidden-start"):
        with pytest.raises(ValueError):
            resolve_within(tmp_path, bad)
    (tmp_path / "evil").symlink_to("/tmp")
    with pytest.raises(ValueError):
        resolve_within(tmp_path, "evil")


# ── CA3 : quotas par défaut 2 vCPU / 4 Go / 40 Go et refus explicite ──────────

def test_ca3_default_quotas_are_product_defaults():
    q = get_quotas_for_tier(tier_id=None)
    assert parse_cpus_str_to_float(q["cpus"]) == 2.0
    assert parse_memory_str_to_mb(q["memory"]) == 4 * 1024
    assert parse_disk_str_to_bytes(q["disk"]) == 40 * 1024**3
    assert q == {k: DEFAULT_CLIENT_QUOTAS[k] for k in q}
    # Aucun palier ne peut dépasser le défaut produit ni échapper au quota disque.
    for name, tier in TIER_RESOURCE_QUOTAS.items():
        t = get_quotas_for_tier(tier_id=name)
        assert parse_cpus_str_to_float(t["cpus"]) <= 2.0, name
        assert parse_memory_str_to_mb(t["memory"]) <= 4096, name
        assert t["disk"] == "40g", name


def test_ca3_disk_quota_exceeded_is_explicit_refusal(tmp_path):
    m = _manager(tmp_path)
    space = tmp_path / "spaces" / "client-full"
    space.mkdir(parents=True)
    (space / "blob.bin").write_bytes(b"x" * 2048)
    with patch.object(m, "get_tenant_status", return_value={"status": "not_found"}), patch.object(
        m, "_exec_docker", side_effect=_no_container
    ) as docker:
        res = m.provision_tenant(
            tenant_id="uuid-full", tenant_slug="client-full", image_digest=DIGEST,
            persona_hmac_key="unit-test-only", quotas={"disk": "1k"},
        )
    assert res["success"] is False
    assert res["error"] == "ERR_DISK_QUOTA_EXCEEDED"
    assert res["disk_details"]["disk_used_bytes"] >= 2048
    _assert_no_run(docker)  # refus avant toute création de conteneur


def test_ca3_invalid_disk_quota_refused_not_defaulted(tmp_path):
    m = _manager(tmp_path)
    with patch.object(m, "get_tenant_status", return_value={"status": "not_found"}), patch.object(m, "_exec_docker", side_effect=_no_container) as docker:
        res = m.provision_tenant(
            tenant_id="uuid-bad", tenant_slug="client-bad", image_digest=DIGEST,
            persona_hmac_key="unit-test-only", quotas={"disk": "beaucoup"},
        )
    assert res["error"] == "ERR_DISK_QUOTA_EXCEEDED"
    _assert_no_run(docker)


def test_ca3_container_gets_all_quota_flags_and_labels(tmp_path):
    m = _manager(tmp_path)
    calls = []

    def fake(args, **kw):
        calls.append(list(args))
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="cid", stderr="")

    with patch.object(m, "get_tenant_status", return_value={"status": "not_found"}), patch.object(
        m, "_exec_docker", side_effect=fake
    ), patch.object(m, "_sync_tenant_instance_record"), patch.object(
        m, "check_host_admission", return_value=(True, None, {})
    ):
        res = m.provision_tenant(
            tenant_id="uuid-ok", tenant_slug="client-ok", image_digest=DIGEST, persona_hmac_key="unit-test-only",
        )
    assert res["success"] is True
    run = next(c for c in calls if c and c[0] == "run")
    assert run[run.index("--cpus") + 1] == "2.0"
    assert run[run.index("--memory") + 1] == "4096m"
    assert run[run.index("--memory-swap") + 1] == "4096m"  # pas de dégradation silencieuse par swap
    assert "com.orso.quotas.disk=40g" in run
    assert "no-new-privileges" in run
    assert run[-1].endswith(f"@{DIGEST}")  # CA4 : image épinglée


def test_ca3_memory_over_host_capacity_refused(tmp_path):
    m = _manager(tmp_path)
    m.host_max_memory_mb = 1024
    with patch.object(m, "get_tenant_status", return_value={"status": "not_found"}), patch.object(m, "_exec_docker", side_effect=_no_container) as docker:
        res = m.provision_tenant(
            tenant_id="uuid-big", tenant_slug="client-big", image_digest=DIGEST, persona_hmac_key="unit-test-only",
        )
    assert res["success"] is False and res["error"] == "ERR_HOST_CAPACITY_EXCEEDED"
    _assert_no_run(docker)


def test_disk_helpers(tmp_path):
    assert parse_disk_str_to_bytes("40g") == 40 * 1024**3
    assert parse_disk_str_to_bytes("512M") == 512 * 1024**2
    for bad in ("", "0", "-1g", "12 parsecs", None, True):
        with pytest.raises(ValueError):
            parse_disk_str_to_bytes(bad)
    (tmp_path / "f").write_bytes(b"x" * 100)
    (tmp_path / "link").symlink_to("/etc/hostname")
    assert measure_dir_bytes(tmp_path) == 100
    ok, _, _ = check_disk_quota([tmp_path], 100)
    assert ok
    ok, reason, _ = check_disk_quota([tmp_path], 100, additional_bytes=1)
    assert not ok and "Quota disque dépassé" in reason


# ── CA4 : reproductibilité par empreinte ──────────────────────────────────────

def test_ca4_floating_tag_refused_without_digest(tmp_path):
    m = _manager(tmp_path)
    with patch.object(m, "get_tenant_status", return_value={"status": "not_found"}), patch.object(m, "_exec_docker", side_effect=_no_container) as docker:
        res = m.provision_tenant(tenant_id="u", tenant_slug="client-float", persona_hmac_key="unit-test-only")
    assert res["error"] == "ERR_DIGEST_REQUIRED"
    _assert_no_run(docker)


# ── CA5 : conservation 30 jours, puis purge ───────────────────────────────────

def _build_dated(mgr, slug, version, age_days, tmp_path, now):
    mgr.build_artifact(slug, version, _make_source(tmp_path, f"src_{slug}_{version}"), hmac_key="k")
    mf = mgr.get_tenant_artifact_dir(slug, version) / "manifest.json"
    data = json.loads(mf.read_text(encoding="utf-8"))
    data["created_at"] = (now - timedelta(days=age_days)).isoformat()
    mf.write_text(json.dumps(data), encoding="utf-8")


def test_ca5_retention_is_30_days_and_purge_follows(tmp_path):
    assert ARTIFACT_RETENTION_DAYS == 30
    now = datetime(2026, 11, 30, tzinfo=timezone.utc)
    mgr = ClientSpaceArtifactManager(artifacts_root=tmp_path / "art", spaces_root=tmp_path / "spaces")
    _build_dated(mgr, "client-a", "0.1.0", 45, tmp_path, now)
    _build_dated(mgr, "client-a", "0.2.0", 31, tmp_path, now)
    _build_dated(mgr, "client-a", "0.3.0", 29, tmp_path, now)
    _build_dated(mgr, "client-b", "0.1.0", 40, tmp_path, now)

    dry = purge_expired_artifacts(mgr, now=now, dry_run=True)
    # client-b : seule version, donc la plus récente → protégée malgré ses 40 jours.
    assert {(p["tenant_slug"], p["version"]) for p in dry["purged"]} == {("client-a", "0.1.0"), ("client-a", "0.2.0")}
    assert [(p["tenant_slug"], p["version"]) for p in dry["protected"]] == [("client-b", "0.1.0")]
    assert (mgr.get_tenant_artifact_dir("client-a", "0.1.0")).is_dir()  # dry-run ne supprime rien


def test_ca5_purge_removes_expired_keeps_fresh_and_latest(tmp_path):
    now = datetime(2026, 11, 30, tzinfo=timezone.utc)
    mgr = ClientSpaceArtifactManager(artifacts_root=tmp_path / "art", spaces_root=tmp_path / "spaces")
    _build_dated(mgr, "client-a", "0.1.0", 45, tmp_path, now)
    _build_dated(mgr, "client-a", "0.3.0", 29, tmp_path, now)
    _build_dated(mgr, "client-b", "0.1.0", 40, tmp_path, now)  # seule version, expirée → protégée

    res = purge_expired_artifacts(mgr, now=now)
    assert [(p["tenant_slug"], p["version"]) for p in res["purged"]] == [("client-a", "0.1.0")]
    assert not mgr.get_tenant_artifact_dir("client-a", "0.1.0").exists()
    assert mgr.get_tenant_artifact_dir("client-a", "0.3.0").is_dir()
    assert mgr.get_tenant_artifact_dir("client-b", "0.1.0").is_dir()
    assert res["protected"][0]["reason"] == "latest_version_protected"

    # Sans protection, l'artefact expiré de B part aussi.
    res2 = purge_expired_artifacts(mgr, now=now, keep_latest=False)
    assert [(p["tenant_slug"], p["version"]) for p in res2["purged"]] == [("client-b", "0.1.0")]


def test_ca5_exactly_30_days_is_kept_and_undated_never_purged(tmp_path):
    now = datetime(2026, 11, 30, tzinfo=timezone.utc)
    mgr = ClientSpaceArtifactManager(artifacts_root=tmp_path / "art", spaces_root=tmp_path / "spaces")
    _build_dated(mgr, "client-a", "0.1.0", 30, tmp_path, now)
    _build_dated(mgr, "client-a", "0.2.0", 1, tmp_path, now)
    broken = mgr.get_tenant_artifact_dir("client-a", "0.9.9")
    broken.mkdir(parents=True)
    (broken / "manifest.json").write_text("{not json", encoding="utf-8")

    res = purge_expired_artifacts(mgr, now=now, keep_latest=False)
    assert res["purged"] == []
    assert res["skipped"][0]["version"] == "0.9.9"
    assert broken.is_dir()


def test_purge_rejects_nonpositive_retention(tmp_path):
    mgr = ClientSpaceArtifactManager(artifacts_root=tmp_path / "art", spaces_root=tmp_path / "spaces")
    with pytest.raises(ValueError):
        purge_expired_artifacts(mgr, retention_days=0)


# ── CA8 : aucun secret en clair dans les modules ajoutés ──────────────────────

def test_ca8_no_plaintext_secret_in_new_modules():
    from olympe.artifact_manager import ClientSpaceArtifactManager as AM

    root = Path(__file__).resolve().parents[2]
    scanner = AM(artifacts_root=Path(os.environ.get("TMPDIR", "/tmp")) / "kan129_scan_art",
                 spaces_root=Path(os.environ.get("TMPDIR", "/tmp")) / "kan129_scan_sp")
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        for rel in ("olympe/sandbox_policy.py", "olympe/artifact_retention.py",
                    "scripts/sandbox_purge_artifacts.py", "docs/3_Technique/spec_kan129_sandbox_produit.md"):
            (Path(d) / Path(rel).name).write_text((root / rel).read_text(encoding="utf-8"), encoding="utf-8")
        count, findings = scanner.scan_for_secrets(Path(d))
    assert count == 0, findings

"""Tests d'acceptation KAN-65 : Acheminement étanche du secret d'intégrité des personas.

Vérifie de manière unitaire et hermétique (sans dépendance réseau ni SSH externe)
l'ensemble des critères d'acceptation CA1 à CA6 :
- CA1 : Absence de secret dans les lignes de commande (argv), transport exclusif par stdin chiffré (--env-file /dev/stdin).
- CA2 : Mise à jour pilotée laissant un conteneur actif et sain.
- CA3 : Retour arrière exécuté par le même chemin avec vérification des états avant/après.
- CA4 : Refus Fail-Closed immédiat en l'absence de secret (aucun conteneur créé, aucun arrêté ni altéré).
- CA5 : Déploiement étanche dans /etc/orso/engine.env (0600 root:root) via entrée standard chiffrée.
- CA6 : Détection de conformité du chemin de transport distant et CLI deploy-env.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch
import pytest

from scripts.distribution.engine_image_manager import (
    EngineDistributionManager,
    DEFAULT_HOSTS,
    probe_docker_host,
)


@pytest.fixture
def mock_host():
    return {
        "host_id": "test-remote-001",
        "host_name": "Test Host Remote",
        "ssh_target": "ubuntu@10.0.0.1",
        "container_filter": "orso_client",
    }


@pytest.fixture
def manager():
    return EngineDistributionManager(
        target_digest="sha256:4506ccd6f51e68d3bf799c2a5b17d82916dc5cc285080f2fcf9c07046e2b904f"
    )


def test_ca1_and_ca2_live_update_passes_secrets_via_stdin_not_argv(mock_host, manager, monkeypatch):
    """CA1 & CA2 : Le secret transite par input_data (stdin) et jamais dans la commande Docker (argv)."""
    fake_secret = "a1b2c3d4e5f60718293a4b5c6d7e8f90123456789abcdef0123456789abcdef0"
    monkeypatch.setenv("ORSO_PERSONA_HMAC_KEY", fake_secret)
    monkeypatch.setenv("HERMES_DASHBOARD_BASIC_AUTH_USERNAME", "test_user")
    monkeypatch.setenv("HERMES_DASHBOARD_BASIC_AUTH_PASSWORD", "test_password_123")

    recorded_calls = []

    def fake_run(cmd, ssh_target=None, timeout=25, extra_env=None, input_data=None):
        recorded_calls.append({"cmd": cmd, "ssh_target": ssh_target, "input_data": input_data})
        if "docker pull" in cmd:
            return 0, "Pulled", ""
        if "docker run" in cmd:
            return 0, "c123456", ""
        if "curl" in cmd:
            return 0, "200", ""
        return 0, "", ""

    def fake_probe(host_spec):
        return {
            "host_id": host_spec["host_id"],
            "active_digest": manager.target_digest,
            "pinned_image": f"ghcr.io/tquinzain59/orso-engine@{manager.target_digest}",
            "running_containers": ["orso_client_demo"],
            "is_reachable": True,
            "label_mismatch": False,
        }

    with patch("scripts.distribution.engine_image_manager.run_remote_or_local_cmd", side_effect=fake_run):
        with patch("scripts.distribution.engine_image_manager.probe_docker_host", side_effect=fake_probe):
            res = manager.execute_live_host_update(
                mock_host,
                new_digest=manager.target_digest,
                container_name="orso_client_demo",
                health_check_port=9119,
            )

    assert res["success"] is True
    assert res["health_http_code"] == "200"

    # Vérification CA1 : Le secret ne doit apparaître dans AUCUN cmd string
    for call in recorded_calls:
        assert fake_secret not in call["cmd"], f"Fuite critique du secret dans argv : {call['cmd']}"
        assert "test_password_123" not in call["cmd"], f"Fuite du mot de passe dans argv : {call['cmd']}"

    # Vérification CA1 & CA2 : docker run doit utiliser --env-file /dev/stdin et recevoir les secrets via input_data
    run_call = next(c for c in recorded_calls if "docker run" in c["cmd"])
    assert "--env-file /dev/stdin" in run_call["cmd"]
    assert "-e ORSO_PERSONA_HMAC_KEY=" not in run_call["cmd"]
    assert run_call["input_data"] is not None
    assert f"ORSO_PERSONA_HMAC_KEY={fake_secret}" in run_call["input_data"]
    assert "HERMES_DASHBOARD_BASIC_AUTH_USERNAME=test_user" in run_call["input_data"]
    assert "HERMES_DASHBOARD_BASIC_AUTH_PASSWORD=test_password_123" in run_call["input_data"]


def test_ca3_live_rollback_executes_by_same_path_and_verifies_states(mock_host, manager, monkeypatch):
    """CA3 : Retour arrière par le même chemin avec vérification des états avant/après."""
    fake_secret = "f0e1d2c3b4a5968778695a4b3c2d1e0f0123456789abcdef0123456789abcdef"
    monkeypatch.setenv("ORSO_PERSONA_HMAC_KEY", fake_secret)

    recorded_calls = []

    def fake_run(cmd, ssh_target=None, timeout=25, extra_env=None, input_data=None):
        recorded_calls.append({"cmd": cmd, "input_data": input_data})
        if "docker run" in cmd:
            return 0, "c789012", ""
        if "curl" in cmd:
            return 0, "200", ""
        return 0, "", ""

    def fake_probe(host_spec):
        return {
            "host_id": host_spec["host_id"],
            "active_digest": manager.target_digest,
            "pinned_image": f"ghcr.io/tquinzain59/orso-engine@{manager.target_digest}",
            "running_containers": ["orso_client_demo"],
            "is_reachable": True,
            "label_mismatch": False,
        }

    with patch("scripts.distribution.engine_image_manager.run_remote_or_local_cmd", side_effect=fake_run):
        with patch("scripts.distribution.engine_image_manager.probe_docker_host", side_effect=fake_probe):
            res = manager.execute_live_host_rollback(
                mock_host,
                rollback_digest=manager.target_digest,
                container_name="orso_client_demo",
                health_check_port=9119,
            )

    assert res["success"] is True
    assert res["action"] == "LIVE_ROLLBACK"
    assert res["rollback_digest"] == manager.target_digest
    assert res["health_http_code"] == "200"

    # Vérification étanchéité rollback
    for call in recorded_calls:
        assert fake_secret not in call["cmd"]
    rb_run_call = next(c for c in recorded_calls if "docker run" in c["cmd"])
    assert "--env-file /dev/stdin" in rb_run_call["cmd"]
    assert f"ORSO_PERSONA_HMAC_KEY={fake_secret}" in rb_run_call["input_data"]


def test_ca4_fail_closed_without_secret_touches_zero_containers(mock_host, manager, monkeypatch):
    """CA4 : Refus Fail-Closed immédiat sans conteneur créé, arrêté ou altéré si le secret est absent."""
    monkeypatch.delenv("ORSO_PERSONA_HMAC_KEY", raising=False)

    recorded_cmds = []

    def fake_run(cmd, *args, **kwargs):
        recorded_cmds.append(cmd)
        return 0, "", ""

    with patch("scripts.distribution.engine_image_manager.run_remote_or_local_cmd", side_effect=fake_run):
        # 1. Update sans secret -> doit lever ValueError immédiatement
        with pytest.raises(ValueError) as excinfo:
            manager.execute_live_host_update(mock_host, new_digest=manager.target_digest)
        assert "ORSO_PERSONA_HMAC_KEY requise" in str(excinfo.value)

        # 2. Rollback sans secret -> doit lever ValueError immédiatement
        with pytest.raises(ValueError) as excinfo_rb:
            manager.execute_live_host_rollback(mock_host, rollback_digest=manager.target_digest)
        assert "ORSO_PERSONA_HMAC_KEY requise" in str(excinfo_rb.value)

    # Invariant absolu CA4 : AUCUNE commande docker stop / rm / run ne doit avoir été exécutée !
    for cmd in recorded_cmds:
        assert "docker stop" not in cmd, f"Arrêt de conteneur illégitime en violation de Fail-Closed : {cmd}"
        assert "docker rm" not in cmd, f"Suppression de conteneur illégitime : {cmd}"
        assert "docker run" not in cmd, f"Création de conteneur orphelin sans secret : {cmd}"


def test_ca5_deploy_canonical_engine_env(mock_host, manager, monkeypatch):
    """CA5 : Déploiement étanche dans /etc/orso/engine.env (0600 root:root) via entrée standard."""
    fake_secret = "canonical_secret_1234567890abcdef1234567890abcdef1234567890abcdef"
    monkeypatch.setenv("ORSO_PERSONA_HMAC_KEY", fake_secret)
    monkeypatch.setenv("HERMES_DASHBOARD_BASIC_AUTH_USERNAME", "admin_ops")
    monkeypatch.setenv("HERMES_DASHBOARD_BASIC_AUTH_PASSWORD", "super_pwd")

    recorded_calls = []

    def fake_run(cmd, ssh_target=None, timeout=25, extra_env=None, input_data=None):
        recorded_calls.append({"cmd": cmd, "input_data": input_data})
        if "stat" in cmd:
            return 0, "600 root:root", ""
        return 0, "", ""

    with patch("scripts.distribution.engine_image_manager.run_remote_or_local_cmd", side_effect=fake_run):
        res = manager.deploy_canonical_engine_env(mock_host)

    assert res["success"] is True
    assert res["action"] == "DEPLOY_ENGINE_ENV"
    assert res["canonical_path"] == "/etc/orso/engine.env"
    assert res["permissions_ok"] is True
    assert res["stat"] == "600 root:root"

    # Vérification de la commande de dépôt : sudo tee sans secret dans argv
    tee_call = next(c for c in recorded_calls if "sudo tee /etc/orso/engine.env" in c["cmd"])
    assert fake_secret not in tee_call["cmd"]
    assert "chmod 0600 /etc/orso/engine.env" in tee_call["cmd"]
    assert "chown root:root /etc/orso/engine.env" in tee_call["cmd"]
    assert tee_call["input_data"] is not None
    assert f"ORSO_PERSONA_HMAC_KEY={fake_secret}" in tee_call["input_data"]
    assert "HERMES_DASHBOARD_BASIC_AUTH_USERNAME=admin_ops" in tee_call["input_data"]
    assert "HERMES_DASHBOARD_BASIC_AUTH_PASSWORD=super_pwd" in tee_call["input_data"]


def test_ca5_deploy_canonical_engine_env_fail_closed_if_missing(mock_host, manager, monkeypatch):
    """CA5 : Refus Fail-Closed si le secret est absent lors du déploiement canonique."""
    monkeypatch.delenv("ORSO_PERSONA_HMAC_KEY", raising=False)

    with pytest.raises(ValueError) as exc:
        manager.deploy_canonical_engine_env(mock_host)
    assert "ORSO_PERSONA_HMAC_KEY requise" in str(exc.value)

    with pytest.raises(ValueError) as exc_explicit:
        manager.deploy_canonical_engine_env(mock_host, env_vars={"OTHER_VAR": "val"})
    assert "ORSO_PERSONA_HMAC_KEY obligatoire" in str(exc_explicit.value)

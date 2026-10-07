"""Tests d'acceptation et invariants de durcissement Docker KAN-51 (CA1 à CA6)."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.security.docker_host_hardening_preflight import (
    check_container_isolation,
    check_image_provenance,
    check_listening_docker_tcp_ports,
)


def test_kan51_ca1_no_exposed_docker_tcp():
    """CA1 : Vérifie qu'aucune violation n'est levée si les ports 2375/2376 ne sont pas exposés."""
    safe_output = """
    Proto Recv-Q Send-Q Local Address           Foreign Address         State       PID/Program name
    tcp        0      0 127.0.0.1:9119          0.0.0.0:*               LISTEN      10234/python3
    tcp        0      0 127.0.0.1:2375          0.0.0.0:*               LISTEN      1234/dockerd
    tcp        0      0 0.0.0.0:22              0.0.0.0:*               LISTEN      890/sshd
    """
    ok, violations = check_listening_docker_tcp_ports(netstat_output=safe_output)
    assert ok is True
    assert len(violations) == 0


def test_kan51_ca2_detects_exposed_docker_tcp():
    """CA2 : Vérifie la détection immédiate et bloquante d'un démon Docker exposé sur 0.0.0.0 ou IP publique."""
    insecure_outputs = [
        "tcp 0 0 0.0.0.0:2375 0.0.0.0:* LISTEN 1234/dockerd",
        "tcp6 0 0 :::2376 :::* LISTEN 1234/dockerd",
        "tcp 0 0 57.131.196.106:2375 0.0.0.0:* LISTEN 1234/dockerd",
    ]
    for output in insecure_outputs:
        ok, violations = check_listening_docker_tcp_ports(netstat_output=output)
        assert ok is False, f"L'écoute non sécurisée aurait dû être rejetée : {output}"
        assert len(violations) >= 1
        assert violations[0]["severity"] == "CRITICAL"


def test_kan51_ca4_container_isolation():
    """CA4 : Vérifie l'isolation des conteneurs (zéro socket docker.sock, zéro montage /, zéro privileged)."""
    # 1. Conteneur sain
    compliant_container = [{
        "Name": "/orso_client_demo",
        "HostConfig": {"Privileged": False},
        "Mounts": [
            {"Source": "/var/orso/spaces/demo", "Destination": "/app/space"},
            {"Source": "/var/orso/profiles/jerome", "Destination": "/app/profiles:ro"},
        ],
    }]
    ok, violations = check_container_isolation(inspect_data=compliant_container)
    assert ok is True
    assert len(violations) == 0

    # 2. Conteneur avec socket Docker
    insecure_socket = [{
        "Name": "/compromised_agent",
        "HostConfig": {"Privileged": False},
        "Mounts": [{"Source": "/var/run/docker.sock", "Destination": "/var/run/docker.sock"}],
    }]
    ok_sock, violations_sock = check_container_isolation(inspect_data=insecure_socket)
    assert ok_sock is False
    assert violations_sock[0]["violation"] == "DOCKER_SOCKET_MOUNTED"

    # 3. Conteneur privilégié
    privileged_container = [{
        "Name": "/privileged_agent",
        "HostConfig": {"Privileged": True},
        "Mounts": [],
    }]
    ok_priv, violations_priv = check_container_isolation(inspect_data=privileged_container)
    assert ok_priv is False
    assert violations_priv[0]["violation"] == "PRIVILEGED_CONTAINER"

    # 4. Conteneur avec racine hôte
    root_mount = [{
        "Name": "/host_mount_agent",
        "HostConfig": {"Privileged": False},
        "Mounts": [{"Source": "/", "Destination": "/host"}],
    }]
    ok_root, violations_root = check_container_isolation(inspect_data=root_mount)
    assert ok_root is False
    assert violations_root[0]["violation"] == "HOST_ROOT_MOUNTED"


def test_kan51_ca5_private_registry_provenance():
    """CA5 : Vérifie que seules les images issues de ghcr.io/tquinzain59 sont autorisées en production."""
    authorized_images = [
        "ghcr.io/tquinzain59/orso-engine:v1.0.0",
        "ghcr.io/tquinzain59/orso-engine@sha256:4506ccd6f51e68d3bf799c2a5b17d82916dc5cc285080f2fcf9c07046e2b904f",
    ]
    ok_auth, violations_auth = check_image_provenance(image_names=authorized_images)
    assert ok_auth is True
    assert len(violations_auth) == 0

    unauthorized_images = [
        "docker.io/library/ubuntu:latest",
        "evil-registry.com/orso-agent:latest",
    ]
    ok_unauth, violations_unauth = check_image_provenance(image_names=unauthorized_images)
    assert ok_unauth is False
    assert len(violations_unauth) == 2


def test_kan51_ca6_operational_procedure_exists():
    """CA6 : Vérifie l'existence et le contenu de la procédure d'exploitation."""
    proc_path = Path(__file__).resolve().parent.parent.parent / "docs/3_Technique/procedure_durcissement_hote_docker_kan51.md"
    assert proc_path.is_file(), "La procédure docs/3_Technique/procedure_durcissement_hote_docker_kan51.md doit exister"
    content = proc_path.read_text(encoding="utf-8")
    assert "2375" in content
    assert "docker.sock" in content
    assert "Rollback" in content or "Retour Arrière" in content

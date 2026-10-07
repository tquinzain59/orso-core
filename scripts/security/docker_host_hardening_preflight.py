#!/usr/bin/env python3
"""Script de preflight et contrôle périodique de durcissement Docker (KAN-51).

Vérifie de façon automatique et bloquante :
- CA1 / CA2 : Absence absolue d'écoute TCP d'un démon Docker (ports 2375/2376) sur les interfaces externes.
- CA4 : Absence de montage du socket Docker (/var/run/docker.sock), de montage de la racine hôte (/),
        et absence de conteneur en mode privilégié (privileged=true).
- CA5 : Validation que les images de production proviennent du registre privé authentifié (GHCR).

Sortie : Code retour 0 si conforme, code retour > 0 avec diagnostic explicite en cas d'anomalie.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import shutil
import subprocess
import sys
from typing import Any, Dict, List, Optional, Tuple

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
_log = logging.getLogger("docker_hardening_preflight")

DOCKER_INSECURE_PORTS = {2375, 2376}
AUTHORIZED_REGISTRY_PREFIX = "ghcr.io/tquinzain59"


def check_listening_docker_tcp_ports(netstat_output: Optional[str] = None) -> Tuple[bool, List[Dict[str, Any]]]:
    """CA1 / CA2 : Vérifie qu'aucun démon Docker n'écoute sur les ports TCP 2375 ou 2376 sur les interfaces publiques.

    Retourne (conforme, liste_des_violations).
    """
    violations: List[Dict[str, Any]] = []

    if netstat_output is None:
        cmd: List[str] = []
        if shutil.which("ss"):
            cmd = ["ss", "-lntp"]
        elif shutil.which("netstat"):
            cmd = ["netstat", "-lntp"]
        elif shutil.which("lsof"):
            cmd = ["lsof", "-iTCP", "-sTCP:LISTEN", "-P", "-n"]
        else:
            _log.warning("Aucun utilitaire réseau (ss, netstat, lsof) disponible sur le système.")
            return True, []

        try:
            res = subprocess.run(cmd, capture_output=True, text=True, check=True)
            netstat_output = res.stdout
        except Exception as e:
            _log.error("Échec de l'inspection réseau via %s: %s", cmd, e)
            return False, [{"error": f"Impossible d'exécuter l'inspection réseau: {e}"}]

    # Analyse des lignes de sortie
    for line in netstat_output.splitlines():
        line_clean = line.strip()
        if not line_clean or line_clean.startswith(("State", "Active", "COMMAND", "Proto")):
            continue

        # Recherche des ports 2375 ou 2376
        for port in DOCKER_INSECURE_PORTS:
            # Recherche de motifs du type :2375, 0.0.0.0:2375, :::2375, *:2375
            port_pattern = rf"(?:0\.0\.0\.0|\*|\[::\]|::|\d+\.\d+\.\d+\.\d+)?:{port}\b"
            if re.search(port_pattern, line_clean):
                # Vérifier si l'adresse est restreinte à localhost (127.0.0.1 ou ::1)
                is_loopback = bool(re.search(rf"(?:127\.0\.0\.1|\[::1\]|::1):{port}\b", line_clean))
                if not is_loopback:
                    violations.append({
                        "port": port,
                        "raw_line": line_clean,
                        "severity": "CRITICAL",
                        "message": f"Démon Docker potentiellement exposé sur port TCP {port} non-loopback",
                    })

    return (len(violations) == 0), violations


def check_container_isolation(
    inspect_data: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[bool, List[Dict[str, Any]]]:
    """CA4 : Vérifie qu'aucun conteneur ne dispose du socket Docker ni de montages sensibles de l'hôte.

    Retourne (conforme, liste_des_violations).
    """
    violations: List[Dict[str, Any]] = []

    if inspect_data is None:
        if not shutil.which("docker"):
            _log.info("Démon Docker non présent localement. Étape d'inspection conteneurs ignorée.")
            return True, []

        try:
            ps_res = subprocess.run(
                ["docker", "ps", "-q"],
                capture_output=True,
                text=True,
                check=True,
            )
            container_ids = [c.strip() for c in ps_res.stdout.splitlines() if c.strip()]
            if not container_ids:
                return True, []

            inspect_res = subprocess.run(
                ["docker", "inspect"] + container_ids,
                capture_output=True,
                text=True,
                check=True,
            )
            inspect_data = json.loads(inspect_res.stdout)
        except Exception as e:
            _log.error("Échec de l'inspection Docker: %s", e)
            return False, [{"error": f"Erreur docker inspect: {e}"}]

    for container in inspect_data:
        name = container.get("Name", "").lstrip("/")
        host_config = container.get("HostConfig", {}) or {}
        mounts = container.get("Mounts", []) or []

        # 1. Vérification mode privilégié
        if host_config.get("Privileged", False) is True:
            violations.append({
                "container": name,
                "violation": "PRIVILEGED_CONTAINER",
                "severity": "CRITICAL",
                "message": f"Le conteneur '{name}' s'exécute en mode privilégié (Privileged=true)",
            })

        # 2. Vérification montages sensibles
        for mount in mounts:
            source = mount.get("Source", "")
            destination = mount.get("Destination", "")

            # Socket Docker
            if "docker.sock" in source or "docker.sock" in destination:
                violations.append({
                    "container": name,
                    "violation": "DOCKER_SOCKET_MOUNTED",
                    "severity": "CRITICAL",
                    "message": f"Le conteneur '{name}' monte le socket Docker ({source} -> {destination})",
                })

            # Montage de la racine hôte ou /etc
            if source in ("/", "/etc", "/root", "/var", "/usr"):
                violations.append({
                    "container": name,
                    "violation": "HOST_ROOT_MOUNTED",
                    "severity": "CRITICAL",
                    "message": f"Le conteneur '{name}' monte un répertoire critique de l'hôte ({source})",
                })

    return (len(violations) == 0), violations


def check_image_provenance(
    image_names: Optional[List[str]] = None,
    allow_local_dev: bool = False,
) -> Tuple[bool, List[Dict[str, Any]]]:
    """CA5 : Vérifie que les images proviennent du registre privé authentifié GHCR."""
    violations: List[Dict[str, Any]] = []

    if image_names is None:
        if not shutil.which("docker"):
            return True, []
        try:
            res = subprocess.run(
                ["docker", "ps", "--format", "{{.Image}}"],
                capture_output=True,
                text=True,
                check=True,
            )
            image_names = [img.strip() for img in res.stdout.splitlines() if img.strip()]
        except Exception as e:
            return False, [{"error": f"Erreur docker ps: {e}"}]

    for img in image_names:
        if allow_local_dev and (img.startswith("orso-") or img.startswith("hermes-") or ":" in img and "/" not in img):
            continue
        if not img.startswith(AUTHORIZED_REGISTRY_PREFIX):
            violations.append({
                "image": img,
                "violation": "UNAUTHORIZED_REGISTRY",
                "severity": "HIGH",
                "message": f"L'image '{img}' ne provient pas du registre privé autorisé ({AUTHORIZED_REGISTRY_PREFIX})",
            })

    return (len(violations) == 0), violations


def run_full_preflight_audit(allow_local_dev: bool = False) -> Dict[str, Any]:
    """Exécute l'ensemble des audits de durcissement Docker et retourne le rapport consolidé."""
    ok_tcp, tcp_violations = check_listening_docker_tcp_ports()
    ok_iso, iso_violations = check_container_isolation()
    ok_img, img_violations = check_image_provenance(allow_local_dev=allow_local_dev)

    passed = ok_tcp and ok_iso and ok_img
    report = {
        "status": "PASSED" if passed else "FAILED",
        "checks": {
            "ca1_ca2_no_exposed_docker_tcp": {
                "passed": ok_tcp,
                "violations": tcp_violations,
            },
            "ca4_container_isolation": {
                "passed": ok_iso,
                "violations": iso_violations,
            },
            "ca5_private_registry_provenance": {
                "passed": ok_img,
                "violations": img_violations,
            },
        },
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit de durcissement de l'hôte Docker (KAN-51)")
    parser.add_argument("--json", action="store_true", help="Sortie au format JSON pour supervision")
    parser.add_argument("--allow-local-dev", action="store_true", help="Tolérer les images construites localement")
    args = parser.parse_args()

    report = run_full_preflight_audit(allow_local_dev=args.allow_local_dev)

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"=== Rapport d'audit de durcissement Docker (KAN-51) : {report['status']} ===")
        for check_name, data in report["checks"].items():
            symbol = "✓" if data["passed"] else "✗"
            print(f"[{symbol}] {check_name}")
            for v in data["violations"]:
                print(f"    - [{v.get('severity', 'WARN')}] {v.get('message')}")

    return 0 if report["status"] == "PASSED" else 1


if __name__ == "__main__":
    sys.exit(main())

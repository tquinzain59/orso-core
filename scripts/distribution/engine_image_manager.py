#!/usr/bin/env python3
"""
Orso Agents - Engine Image Distribution & Versioning Manager (KAN-63)
---------------------------------------------------------------------
Fournit les primitives de gestion, de validation cryptographique (SHA-256),
de détection de dérive multi-hôtes et de procédure de mise à jour / rollback.

Respecte les critères d'acceptation KAN-63 :
- CA2 : Épinglage et vérification par empreinte (Digest SHA-256)
- CA3 : Détection d'écart de version entre hôtes
- CA4 : Procédure de mise à jour et retour arrière rejouable
- CA5 : Moindre privilège et zéro secret
"""

import os
import re
import sys
import time
import json
import hashlib
import logging
import shlex
import argparse
import subprocess
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple, Any

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
_logger = logging.getLogger("engine_image_manager")

DIGEST_REGEX = re.compile(r"^sha256:[a-f0-9]{64}$")
IMAGE_WITH_DIGEST_REGEX = re.compile(r"^(?P<repo>[^@:]+)(?::(?P<tag>[^@]+))?@(?P<digest>sha256:[a-f0-9]{64})$")


@dataclass
class HostEngineState:
    host_id: str
    host_name: str
    active_digest: str
    pinned_image: str
    running_containers: List[str]
    last_checked: str
    status: str  # "IN_SYNC", "DRIFT_DETECTED", "UNREACHABLE", "ERROR"
    previous_digest: Optional[str] = None
    drift_details: Optional[str] = None


@dataclass
class DriftAuditReport:
    target_digest: str
    timestamp: str
    total_hosts: int
    in_sync_count: int
    drifted_count: int
    unreachable_count: int
    is_drift_detected: bool
    hosts: List[HostEngineState]


def validate_digest(digest: str) -> bool:
    """Vérifie qu'une chaîne est un digest OCI/Docker SHA-256 valide."""
    if not digest or not isinstance(digest, str):
        return False
    return bool(DIGEST_REGEX.match(digest.strip()))


def format_pinned_image(image_repo: str, digest: str, tag: Optional[str] = None) -> str:
    """Formate une référence d'image Docker immuable épinglée par digest."""
    clean_digest = digest.strip()
    if not validate_digest(clean_digest):
        raise ValueError(f"Digest SHA-256 invalide : {digest}. Format attendu : sha256:<64_hex_digits>")
    
    clean_repo = image_repo.split("@")[0].split(":")[0].strip()
    if tag:
        return f"{clean_repo}:{tag.strip()}@{clean_digest}"
    return f"{clean_repo}@{clean_digest}"


def parse_pinned_image(image_ref: str) -> Tuple[str, Optional[str], Optional[str]]:
    """
    Extrait (repo, tag, digest) d'une référence d'image.
    Retourne (repo, tag, digest).
    """
    match = IMAGE_WITH_DIGEST_REGEX.match(image_ref)
    if match:
        return match.group("repo"), match.group("tag"), match.group("digest")
    
    # Sans digest
    if ":" in image_ref:
        repo, tag = image_ref.split(":", 1)
        return repo, tag, None
    return image_ref, None, None


class EngineDistributionManager:
    """Gestionnaire de versionnement et distribution du moteur Orso."""

    def __init__(self, target_digest: str, registry_base: str = "ghcr.io/tquinzain59/orso-engine"):
        if not validate_digest(target_digest):
            raise ValueError(f"Le digest cible est invalide : {target_digest}")
        self.target_digest = target_digest
        self.registry_base = registry_base
        self._host_history: Dict[str, List[Dict[str, Any]]] = {}

    def get_target_pinned_image(self, human_tag: Optional[str] = None) -> str:
        """Retourne la référence d'image complète épinglée pour la production."""
        return format_pinned_image(self.registry_base, self.target_digest, tag=human_tag)

    def audit_hosts_drift(self, hosts: List[Dict[str, Any]]) -> DriftAuditReport:
        """
        CA3 : Évalue l'état de version de chaque hôte et détecte toute dérive
        par rapport au digest de référence cible.
        """
        now = datetime.now(timezone.utc).isoformat()
        evaluated_hosts: List[HostEngineState] = []
        in_sync_count = 0
        drifted_count = 0
        unreachable_count = 0

        for h in hosts:
            host_id = h.get("host_id", "unknown")
            host_name = h.get("host_name", host_id)
            active_digest = h.get("active_digest", "").strip()
            pinned_image = h.get("pinned_image", "")
            containers = h.get("running_containers", [])
            is_reachable = h.get("is_reachable", True)
            prev_digest = h.get("previous_digest")

            if not is_reachable:
                status = "UNREACHABLE"
                drift_details = "Hôte inaccessible ou démon Docker muet"
                unreachable_count += 1
            elif not validate_digest(active_digest):
                status = "ERROR"
                drift_details = f"Digest invalide sur l'hôte : {active_digest}"
                drifted_count += 1
            elif active_digest == self.target_digest:
                status = "IN_SYNC"
                drift_details = None
                in_sync_count += 1
            else:
                status = "DRIFT_DETECTED"
                drift_details = (
                    f"Dérive détectée : actif={active_digest[:19]}... vs cible={self.target_digest[:19]}..."
                )
                drifted_count += 1

            host_state = HostEngineState(
                host_id=host_id,
                host_name=host_name,
                active_digest=active_digest,
                pinned_image=pinned_image or self.get_target_pinned_image(),
                running_containers=containers,
                last_checked=now,
                status=status,
                previous_digest=prev_digest,
                drift_details=drift_details,
            )
            evaluated_hosts.append(host_state)

        report = DriftAuditReport(
            target_digest=self.target_digest,
            timestamp=now,
            total_hosts=len(hosts),
            in_sync_count=in_sync_count,
            drifted_count=drifted_count,
            unreachable_count=unreachable_count,
            is_drift_detected=(drifted_count > 0),
            hosts=evaluated_hosts,
        )

        if report.is_drift_detected:
            _logger.warning("ALERTE CRITIQUE : Dérive de version détectée sur %d hôte(s) !", drifted_count)
        else:
            _logger.info("Audit d'intégrité OK : tous les hôtes (%d) exécutent le digest cible.", in_sync_count)

        return report

    def execute_host_update(
        self,
        host_state: HostEngineState,
        new_digest: str,
        human_tag: Optional[str] = None,
    ) -> Tuple[HostEngineState, Dict[str, Any]]:
        """
        CA4 : Exécute et enregistre la mise à jour d'un hôte vers un nouveau digest.
        """
        if not validate_digest(new_digest):
            raise ValueError(f"Nouveau digest invalide pour la mise à jour : {new_digest}")

        state_before = {
            "host_id": host_state.host_id,
            "digest": host_state.active_digest,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # Enregistrement dans l'historique de l'hôte
        if host_state.host_id not in self._host_history:
            self._host_history[host_state.host_id] = []
        self._host_history[host_state.host_id].append(state_before)

        # Mise à jour de l'état
        updated_state = HostEngineState(
            host_id=host_state.host_id,
            host_name=host_state.host_name,
            active_digest=new_digest,
            pinned_image=format_pinned_image(self.registry_base, new_digest, tag=human_tag),
            running_containers=list(host_state.running_containers),
            last_checked=datetime.now(timezone.utc).isoformat(),
            status="IN_SYNC" if new_digest == self.target_digest else "DRIFT_DETECTED",
            previous_digest=host_state.active_digest,
            drift_details=None if new_digest == self.target_digest else "Digest mis à jour différent de la cible globale",
        )

        audit_log = {
            "action": "UPDATE",
            "host_id": host_state.host_id,
            "old_digest": host_state.active_digest,
            "new_digest": new_digest,
            "timestamp": updated_state.last_checked,
            "success": True,
        }
        return updated_state, audit_log

    def execute_host_rollback(self, host_state: HostEngineState) -> Tuple[HostEngineState, Dict[str, Any]]:
        """
        CA4 : Exécute le retour arrière immédiat d'un hôte vers son digest précédent.
        """
        if not host_state.previous_digest or not validate_digest(host_state.previous_digest):
            raise ValueError(
                f"Impossible d'effectuer le rollback pour l'hôte {host_state.host_id} : aucun digest précédent valide"
            )

        target_rollback_digest = host_state.previous_digest
        current_digest = host_state.active_digest

        rolled_back_state = HostEngineState(
            host_id=host_state.host_id,
            host_name=host_state.host_name,
            active_digest=target_rollback_digest,
            pinned_image=format_pinned_image(self.registry_base, target_rollback_digest),
            running_containers=list(host_state.running_containers),
            last_checked=datetime.now(timezone.utc).isoformat(),
            status="IN_SYNC" if target_rollback_digest == self.target_digest else "DRIFT_DETECTED",
            previous_digest=current_digest,  # Permet un redo si nécessaire
            drift_details=None if target_rollback_digest == self.target_digest else "Rollback sur digest historique",
        )

        audit_log = {
            "action": "ROLLBACK",
            "host_id": host_state.host_id,
            "from_digest": current_digest,
            "to_digest": target_rollback_digest,
            "timestamp": rolled_back_state.last_checked,
            "success": True,
        }
        return rolled_back_state, audit_log

    def audit_hosts_drift_live(self, host_specs: Optional[List[Dict[str, Any]]] = None) -> DriftAuditReport:
        """
        CA3 : Interroge réellement les démons Docker distants et audite la dérive de version.
        """
        specs = host_specs or DEFAULT_HOSTS
        probed_inventory = [probe_docker_host(h) for h in specs]
        return self.audit_hosts_drift(probed_inventory)

    def execute_live_host_update(
        self,
        host_spec: Dict[str, Any],
        new_digest: str,
        container_name: str = "orso_client_demo",
        human_tag: Optional[str] = None,
        health_check_port: int = 9119,
    ) -> Dict[str, Any]:
        """
        CA4 : Exécute en direct sur l'hôte distant le pull de l'image, le redémarrage et la sonde de santé.
        """
        if not validate_digest(new_digest):
            raise ValueError(f"Digest invalide : {new_digest}")

        ssh_target = host_spec.get("ssh_target")
        target_image = format_pinned_image(self.registry_base, new_digest, tag=human_tag)

        # 1. État avant
        state_before = probe_docker_host(host_spec)

        # 2. Pull sur l'hôte distant
        pull_cmd = f"docker pull {target_image}"
        rc_pull, stdout_pull, stderr_pull = run_remote_or_local_cmd(pull_cmd, ssh_target, timeout=120)

        # 3. Arrêt gracieux du conteneur si existant
        stop_cmd = f"docker stop -t 10 {container_name} 2>/dev/null || true"
        run_remote_or_local_cmd(stop_cmd, ssh_target)
        rm_cmd = f"docker rm -f {container_name} 2>/dev/null || true"
        run_remote_or_local_cmd(rm_cmd, ssh_target)

        # 4. Relance du conteneur avec l'image épinglée et clé d'intégrité personas (KAN-33 / KAN-64)
        hmac_key = os.environ.get("ORSO_PERSONA_HMAC_KEY", "")
        hmac_flag = f"-e ORSO_PERSONA_HMAC_KEY='{hmac_key}' " if hmac_key else "-e ORSO_PERSONA_HMAC_KEY=\"$ORSO_PERSONA_HMAC_KEY\" "
        run_cmd = (
            f"docker run -d --name {container_name} "
            f"-p {health_check_port}:9119 "
            f"--label com.orso.managed=true "
            f"--label com.orso.engine.digest={new_digest} "
            f"--label com.orso.engine.pinned=true "
            f"{hmac_flag}"
            f"{target_image}"
        )
        rc_run, stdout_run, stderr_run = run_remote_or_local_cmd(run_cmd, ssh_target, timeout=30)

        # 5. Sonde de santé
        health_cmd = f"curl -s -o /dev/null -w '%{{http_code}}' http://localhost:{health_check_port}/api/client/status || echo '000'"
        health_code = "000"
        for _ in range(6):
            time.sleep(2)
            rc_h, stdout_h, _ = run_remote_or_local_cmd(health_cmd, ssh_target, timeout=5)
            if rc_h == 0 and stdout_h.strip() in ("200", "401", "403"):
                health_code = stdout_h.strip()
                break

        # 6. État après
        state_after = probe_docker_host(host_spec)
        success = (rc_run == 0 and state_after.get("active_digest") == new_digest)

        return {
            "action": "LIVE_UPDATE",
            "host_id": host_spec.get("host_id"),
            "target_digest": new_digest,
            "target_image": target_image,
            "state_before": state_before,
            "state_after": state_after,
            "pull_output": stdout_pull or stderr_pull,
            "run_output": stdout_run,
            "health_http_code": health_code,
            "success": success,
        }

    def execute_live_host_rollback(
        self,
        host_spec: Dict[str, Any],
        rollback_digest: str,
        container_name: str = "orso_client_demo",
        health_check_port: int = 9119,
    ) -> Dict[str, Any]:
        """
        CA4 : Exécute le rollback en direct sur l'hôte distant vers l'empreinte précédente.
        """
        if not validate_digest(rollback_digest):
            raise ValueError(f"Digest invalide pour rollback : {rollback_digest}")

        ssh_target = host_spec.get("ssh_target")
        target_image = format_pinned_image(self.registry_base, rollback_digest)

        state_before = probe_docker_host(host_spec)

        # Relance instantanée (image déjà présente en cache local)
        stop_cmd = f"docker stop -t 5 {container_name} 2>/dev/null && docker rm -f {container_name} 2>/dev/null || true"
        run_remote_or_local_cmd(stop_cmd, ssh_target)

        hmac_key = os.environ.get("ORSO_PERSONA_HMAC_KEY", "")
        hmac_flag = f"-e ORSO_PERSONA_HMAC_KEY='{hmac_key}' " if hmac_key else "-e ORSO_PERSONA_HMAC_KEY=\"$ORSO_PERSONA_HMAC_KEY\" "
        run_cmd = (
            f"docker run -d --name {container_name} "
            f"-p {health_check_port}:9119 "
            f"--label com.orso.managed=true "
            f"--label com.orso.engine.digest={rollback_digest} "
            f"--label com.orso.engine.pinned=true "
            f"{hmac_flag}"
            f"{target_image}"
        )
        rc_run, stdout_run, _ = run_remote_or_local_cmd(run_cmd, ssh_target, timeout=20)

        # Sonde de santé
        health_cmd = f"curl -s -o /dev/null -w '%{{http_code}}' http://localhost:{health_check_port}/api/client/status || echo '000'"
        health_code = "000"
        for _ in range(6):
            time.sleep(2)
            rc_h, stdout_h, _ = run_remote_or_local_cmd(health_cmd, ssh_target, timeout=5)
            if rc_h == 0 and stdout_h.strip() in ("200", "401", "403"):
                health_code = stdout_h.strip()
                break

        state_after = probe_docker_host(host_spec)
        success = (rc_run == 0 and state_after.get("active_digest") == rollback_digest)

        return {
            "action": "LIVE_ROLLBACK",
            "host_id": host_spec.get("host_id"),
            "rollback_digest": rollback_digest,
            "target_image": target_image,
            "state_before": state_before,
            "state_after": state_after,
            "run_output": stdout_run,
            "health_http_code": health_code,
            "success": success,
        }

    @staticmethod
    def calculate_file_sha256(filepath: str) -> str:
        """Calcule le hash SHA-256 d'un fichier (ex: archive Docker .tar.gz)."""
        sha = hashlib.sha256()
        with open(filepath, "rb") as f:
            while chunk := f.read(65536):
                sha.update(chunk)
        return sha.hexdigest()

    @staticmethod
    def verify_bundle_manifest(archive_path: str, expected_sha256: str) -> bool:
        """Vérifie qu'une archive de secours correspond exactement à l'empreinte signée."""
        actual_sha = EngineDistributionManager.calculate_file_sha256(archive_path)
        return actual_sha.lower() == expected_sha256.lower().replace("sha256:", "").strip()


DEFAULT_HOSTS = [
    {
        "host_id": "prod-fr-002",
        "host_name": "Serveur Olympe & Build (Hôte 1)",
        "ssh_target": "ubuntu@92.222.68.80",
        "container_filter": "orso_client",
    },
    {
        "host_id": "prod-fr-003",
        "host_name": "Serveur Clients OVH (Hôte 2)",
        "ssh_target": "ubuntu@57.131.196.106",
        "container_filter": "orso_client",
    },
]


def run_remote_or_local_cmd(cmd: str, ssh_target: Optional[str] = None, timeout: int = 25) -> Tuple[int, str, str]:
    """Exécute une commande localement ou à distance via SSH."""
    if ssh_target:
        full_cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", ssh_target, cmd]
    else:
        full_cmd = shlex.split(cmd)

    try:
        proc = subprocess.run(full_cmd, capture_output=True, text=True, timeout=timeout)
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except subprocess.TimeoutExpired:
        return 124, "", "Commande expirée (Timeout)"
    except Exception as e:
        return 1, "", str(e)


def probe_docker_host(host_spec: Dict[str, Any]) -> Dict[str, Any]:
    """
    CA3 : Sonde le démon Docker d'un hôte distant pour en extraire l'empreinte active réelle.
    """
    host_id = host_spec.get("host_id", "unknown")
    host_name = host_spec.get("host_name", host_id)
    ssh_target = host_spec.get("ssh_target")
    container_filter = host_spec.get("container_filter", "orso_client")

    rc, stdout, stderr = run_remote_or_local_cmd("docker ps --format '{{.Names}}'", ssh_target)
    if rc != 0:
        return {
            "host_id": host_id,
            "host_name": host_name,
            "active_digest": "",
            "running_containers": [],
            "is_reachable": False,
            "error": stderr or "Démon Docker inaccessible",
        }

    running_containers = [c.strip() for c in stdout.splitlines() if c.strip()]
    matching_containers = [c for c in running_containers if container_filter in c]

    active_digest = ""
    pinned_image = ""

    if matching_containers:
        target_c = matching_containers[0]
        inspect_cmd = (
            f"docker inspect --format '{{{{.Image}}}} | {{{{.Config.Image}}}} | "
            f"{{{{index .Config.Labels \"com.orso.engine.digest\"}}}}' {target_c}"
        )
        rc_i, stdout_i, _ = run_remote_or_local_cmd(inspect_cmd, ssh_target)
        if rc_i == 0 and stdout_i:
            parts = [p.strip() for p in stdout_i.split("|")]
            img_id = parts[0] if len(parts) > 0 else ""
            cfg_img = parts[1] if len(parts) > 1 else ""
            lbl_digest = parts[2] if len(parts) > 2 else ""

            if lbl_digest and validate_digest(lbl_digest):
                active_digest = lbl_digest
            elif "@sha256:" in cfg_img:
                active_digest = "sha256:" + cfg_img.split("@sha256:")[1].strip()
            elif validate_digest(img_id):
                active_digest = img_id

            pinned_image = cfg_img or img_id
    else:
        # Aucun conteneur client actif, inspecte les images orso locales avec digest
        img_cmd = "docker images --digests --format '{{.Repository}}:{{.Tag}}@{{.Digest}} | {{.ID}}'"
        rc_img, stdout_img, _ = run_remote_or_local_cmd(img_cmd, ssh_target)
        if rc_img == 0 and stdout_img:
            for line in stdout_img.splitlines():
                if "orso" in line.lower() and "@sha256:" in line:
                    ref, _, _ = line.partition(" | ")
                    active_digest = "sha256:" + ref.split("@sha256:")[1].strip()
                    pinned_image = ref.strip()
                    break

    return {
        "host_id": host_id,
        "host_name": host_name,
        "active_digest": active_digest,
        "pinned_image": pinned_image,
        "running_containers": running_containers,
        "is_reachable": True,
    }


def main():
    parser = argparse.ArgumentParser(description="Orso Engine Image Distribution Manager")
    parser.add_argument("--target-digest", default=os.environ.get("ORSO_TARGET_ENGINE_DIGEST", "sha256:d8a5f82c448bb95b28a9b49b43e8b0b8c6e07eb4838a1f2987a123456789abcd"))
    parser.add_argument("--registry-base", default="ghcr.io/tquinzain59/orso-engine")

    sub = parser.add_subparsers(dest="command")
    probe_parser = sub.add_parser("probe", help="Sonde l'état réel des démons Docker de tous les hôtes")
    probe_parser.add_argument("--local", action="store_true", help="Sonde le démon Docker local sans passer par SSH")
    probe_parser.add_argument("--host-id", help="Identifiant de l'hôte (ex: prod-fr-003)")

    audit_parser = sub.add_parser("audit", help="Exécute un audit de dérive en direct")
    audit_parser.add_argument("--local", action="store_true", help="Audit local uniquement sans passer par SSH")
    audit_parser.add_argument("--host-id", help="Identifiant de l'hôte (ex: prod-fr-003)")

    up_parser = sub.add_parser("update", help="Exécute une mise à jour sur un hôte")
    up_parser.add_argument("--host-id", required=True)
    up_parser.add_argument("--new-digest", required=True)
    up_parser.add_argument("--container", default="orso_client_demo")

    rb_parser = sub.add_parser("rollback", help="Exécute un rollback sur un hôte")
    rb_parser.add_argument("--host-id", required=True)
    rb_parser.add_argument("--rollback-digest", required=True)
    rb_parser.add_argument("--container", default="orso_client_demo")

    args = parser.parse_args()

    mgr = EngineDistributionManager(target_digest=args.target_digest, registry_base=args.registry_base)

    if args.command == "probe":
        print("\n=== Sonde en Direct des Hôtes de Déploiement ===")
        hosts = DEFAULT_HOSTS
        if getattr(args, "local", False):
            hid = getattr(args, "host_id", None) or "local"
            hosts = [{
                "host_id": hid,
                "host_name": f"Hôte Local ({hid})",
                "ssh_target": None,
                "container_filter": "orso_client",
            }]
        for h in hosts:
            state = probe_docker_host(h)
            print(f"[{state['host_id']}] {state['host_name']}")
            print(f"  Accessible        : {state['is_reachable']}")
            print(f"  Digest Actif      : {state.get('active_digest') or 'Aucun conteneur actif'}")
            print(f"  Image Épinglée    : {state.get('pinned_image') or 'N/A'}")
            print(f"  Conteneurs        : {', '.join(state.get('running_containers', [])) or 'Aucun'}")
        print("================================================\n")

    elif args.command == "audit":
        host_specs = None
        if getattr(args, "local", False):
            hid = getattr(args, "host_id", None) or "local"
            host_specs = [{
                "host_id": hid,
                "host_name": f"Hôte Local ({hid})",
                "ssh_target": None,
                "container_filter": "orso_client",
            }]
        report = mgr.audit_hosts_drift_live(host_specs=host_specs)
        print(json.dumps(asdict(report), indent=2))
        sys.exit(1 if report.is_drift_detected else 0)

    elif args.command == "update":
        target_host = next((h for h in DEFAULT_HOSTS if h["host_id"] == args.host_id), None)
        if not target_host:
            print(f"Hôte inconnu : {args.host_id}")
            sys.exit(1)
        res = mgr.execute_live_host_update(target_host, new_digest=args.new_digest, container_name=args.container)
        print(json.dumps(res, indent=2))
        sys.exit(0 if res.get("success") else 1)

    elif args.command == "rollback":
        target_host = next((h for h in DEFAULT_HOSTS if h["host_id"] == args.host_id), None)
        if not target_host:
            print(f"Hôte inconnu : {args.host_id}")
            sys.exit(1)
        res = mgr.execute_live_host_rollback(target_host, rollback_digest=args.rollback_digest, container_name=args.container)
        print(json.dumps(res, indent=2))
        sys.exit(0 if res.get("success") else 1)

    else:
        print("Moteur Orso épinglé :", mgr.get_target_pinned_image(human_tag="v1.0.0"))


if __name__ == "__main__":
    main()

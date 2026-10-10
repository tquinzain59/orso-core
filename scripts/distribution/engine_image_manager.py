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
from pathlib import Path
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
            label_mismatch = h.get("label_mismatch", False)
            label_mismatch_detail = h.get("label_mismatch_detail")

            if not is_reachable:
                status = "UNREACHABLE"
                drift_details = "Hôte inaccessible ou démon Docker muet"
                unreachable_count += 1
            elif not containers or not active_digest:
                # Règle d'or KAN-64 : un hôte sans conteneur client en service n'est JAMAIS déclaré IN_SYNC
                status = "DRIFT_DETECTED"
                drift_details = "Aucun conteneur client actif en service sur cet hôte"
                drifted_count += 1
            elif label_mismatch:
                # Alerte immédiate sur divergence critique étiquette vs image réelle
                status = "DRIFT_DETECTED"
                drift_details = label_mismatch_detail or "Divergence entre l'étiquette et l'image réellement chargée"
                drifted_count += 1
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

        # Validation Fail-Closed préalable du secret (CA4 / KAN-65) :
        # L'absence du secret bloque immédiatement l'opération SANS toucher aux conteneurs en service.
        hmac_key = os.environ.get("ORSO_PERSONA_HMAC_KEY")
        if not hmac_key:
            raise ValueError(
                "Opération refusée (Fail-Closed) : variable ORSO_PERSONA_HMAC_KEY requise "
                "dans l'environnement du plan de gestion pour sécuriser le démarrage du conteneur."
            )

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

        # 4. Relance du conteneur avec l'image épinglée et clé d'intégrité personas (KAN-33 / KAN-64 / KAN-65)
        # Règle absolue de sécurité (Arbitrage KAN-65) :
        # Le secret ORSO_PERSONA_HMAC_KEY ne figure JAMAIS dans la ligne de commande (argv) ni dans les traces.
        # Sur SSH, comme l'environnement n'est pas transmis par défaut par sshd, le secret est transporté
        # via l'entrée standard chiffrée (stdin) et lu par Docker avec `--env-file /dev/stdin`.
        # Sur l'hôte client, l'emplacement canonique /etc/orso/engine.env (0600 root:root) est déposé
        # et maintenu par ce même canal étanche.
        env_lines = [f"ORSO_PERSONA_HMAC_KEY={hmac_key}"]
        db_user = os.environ.get("HERMES_DASHBOARD_BASIC_AUTH_USERNAME")
        db_pass = (
            os.environ.get("HERMES_DASHBOARD_BASIC_AUTH_PASSWORD")
            or os.environ.get("HERMES_DASHBOARD_BASIC_AUTH_PASSWORD_HASH")
        )
        if db_user and db_pass:
            env_lines.append(f"HERMES_DASHBOARD_BASIC_AUTH_USERNAME={db_user}")
            if os.environ.get("HERMES_DASHBOARD_BASIC_AUTH_PASSWORD"):
                env_lines.append(f"HERMES_DASHBOARD_BASIC_AUTH_PASSWORD={os.environ['HERMES_DASHBOARD_BASIC_AUTH_PASSWORD']}")
            elif os.environ.get("HERMES_DASHBOARD_BASIC_AUTH_PASSWORD_HASH"):
                env_lines.append(f"HERMES_DASHBOARD_BASIC_AUTH_PASSWORD_HASH={os.environ['HERMES_DASHBOARD_BASIC_AUTH_PASSWORD_HASH']}")
        input_env_content = "\n".join(env_lines) + "\n"

        run_cmd = (
            f"docker run -d --name {container_name} "
            f"-p 127.0.0.1:{health_check_port}:9119 "
            f"--label com.orso.managed=true "
            f"--label com.orso.engine.digest={new_digest} "
            f"--label com.orso.engine.pinned=true "
            f"--env-file /dev/stdin "
            f"{target_image}"
        )
        rc_run, stdout_run, stderr_run = run_remote_or_local_cmd(
            run_cmd,
            ssh_target,
            timeout=30,
            input_data=input_env_content,
        )

        # 5. Sonde de santé sur la boucle locale
        health_cmd = f"curl -s -o /dev/null -w '%{{http_code}}' http://127.0.0.1:{health_check_port}/api/client/status || echo '000'"
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
            "run_cmd": run_cmd,
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
        CA3 / CA4 : Exécute le rollback en direct sur l'hôte distant vers l'empreinte précédente.
        """
        if not validate_digest(rollback_digest):
            raise ValueError(f"Digest invalide pour rollback : {rollback_digest}")

        # Validation Fail-Closed préalable du secret (CA4 / KAN-65) :
        # L'absence du secret bloque immédiatement l'opération SANS toucher aux conteneurs en service.
        hmac_key = os.environ.get("ORSO_PERSONA_HMAC_KEY")
        if not hmac_key:
            raise ValueError(
                "Opération refusée (Fail-Closed) : variable ORSO_PERSONA_HMAC_KEY requise "
                "dans l'environnement du plan de gestion pour sécuriser le démarrage du conteneur."
            )

        ssh_target = host_spec.get("ssh_target")
        target_image = format_pinned_image(self.registry_base, rollback_digest)

        state_before = probe_docker_host(host_spec)

        # S'assurer que l'image de rollback est disponible (pull préalable si absente du cache)
        check_image_cmd = f"docker image inspect {target_image} >/dev/null 2>&1 || docker pull {target_image}"
        run_remote_or_local_cmd(check_image_cmd, ssh_target, timeout=120)

        # Relance instantanée
        stop_cmd = f"docker stop -t 5 {container_name} 2>/dev/null && docker rm -f {container_name} 2>/dev/null || true"
        run_remote_or_local_cmd(stop_cmd, ssh_target)

        env_lines = [f"ORSO_PERSONA_HMAC_KEY={hmac_key}"]
        db_user = os.environ.get("HERMES_DASHBOARD_BASIC_AUTH_USERNAME")
        db_pass = (
            os.environ.get("HERMES_DASHBOARD_BASIC_AUTH_PASSWORD")
            or os.environ.get("HERMES_DASHBOARD_BASIC_AUTH_PASSWORD_HASH")
        )
        if db_user and db_pass:
            env_lines.append(f"HERMES_DASHBOARD_BASIC_AUTH_USERNAME={db_user}")
            if os.environ.get("HERMES_DASHBOARD_BASIC_AUTH_PASSWORD"):
                env_lines.append(f"HERMES_DASHBOARD_BASIC_AUTH_PASSWORD={os.environ['HERMES_DASHBOARD_BASIC_AUTH_PASSWORD']}")
            elif os.environ.get("HERMES_DASHBOARD_BASIC_AUTH_PASSWORD_HASH"):
                env_lines.append(f"HERMES_DASHBOARD_BASIC_AUTH_PASSWORD_HASH={os.environ['HERMES_DASHBOARD_BASIC_AUTH_PASSWORD_HASH']}")
        input_env_content = "\n".join(env_lines) + "\n"

        run_cmd = (
            f"docker run -d --name {container_name} "
            f"-p 127.0.0.1:{health_check_port}:9119 "
            f"--label com.orso.managed=true "
            f"--label com.orso.engine.digest={rollback_digest} "
            f"--label com.orso.engine.pinned=true "
            f"--env-file /dev/stdin "
            f"{target_image}"
        )
        rc_run, stdout_run, _ = run_remote_or_local_cmd(
            run_cmd,
            ssh_target,
            timeout=20,
            input_data=input_env_content,
        )

        # Sonde de santé sur la boucle locale
        health_cmd = f"curl -s -o /dev/null -w '%{{http_code}}' http://127.0.0.1:{health_check_port}/api/client/status || echo '000'"
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
            "run_cmd": run_cmd,
            "run_output": stdout_run,
            "health_http_code": health_code,
            "success": success,
        }

    def deploy_canonical_engine_env(
        self,
        host_spec: Dict[str, Any],
        env_vars: Optional[Dict[str, str]] = None,
        canonical_path: str = "/etc/orso/engine.env",
    ) -> Dict[str, Any]:
        """
        CA5 / KAN-65 : Dépose de manière étanche le secret des personas dans l'emplacement canonique sur l'hôte client :
        `/etc/orso/engine.env` (permissions 0600, propriétaire root:root).

        Règle inviolable :
        La valeur du secret transite exclusivement par l'entrée standard chiffrée (stdin de sudo tee).
        Elle n'apparaît JAMAIS dans la ligne de commande, ni dans les arguments de processus (argv),
        ni dans l'historique ou les journaux.
        """
        ssh_target = host_spec.get("ssh_target")
        host_id = host_spec.get("host_id", "unknown")

        if env_vars is None:
            hmac_key = os.environ.get("ORSO_PERSONA_HMAC_KEY")
            if not hmac_key:
                raise ValueError(
                    "Opération refusée (Fail-Closed) : variable ORSO_PERSONA_HMAC_KEY requise "
                    "dans l'environnement du plan de gestion pour sécuriser le déploiement du secret d'intégrité."
                )
            env_vars = {"ORSO_PERSONA_HMAC_KEY": hmac_key}
            db_user = os.environ.get("HERMES_DASHBOARD_BASIC_AUTH_USERNAME")
            db_pass = (
                os.environ.get("HERMES_DASHBOARD_BASIC_AUTH_PASSWORD")
                or os.environ.get("HERMES_DASHBOARD_BASIC_AUTH_PASSWORD_HASH")
            )
            if db_user and db_pass:
                env_vars["HERMES_DASHBOARD_BASIC_AUTH_USERNAME"] = db_user
                if os.environ.get("HERMES_DASHBOARD_BASIC_AUTH_PASSWORD"):
                    env_vars["HERMES_DASHBOARD_BASIC_AUTH_PASSWORD"] = os.environ["HERMES_DASHBOARD_BASIC_AUTH_PASSWORD"]
                elif os.environ.get("HERMES_DASHBOARD_BASIC_AUTH_PASSWORD_HASH"):
                    env_vars["HERMES_DASHBOARD_BASIC_AUTH_PASSWORD_HASH"] = os.environ["HERMES_DASHBOARD_BASIC_AUTH_PASSWORD_HASH"]
        else:
            if "ORSO_PERSONA_HMAC_KEY" not in env_vars or not env_vars["ORSO_PERSONA_HMAC_KEY"]:
                raise ValueError(
                    "Opération refusée (Fail-Closed) : variable ORSO_PERSONA_HMAC_KEY obligatoire "
                    "dans le jeu de variables d'environnement à déployer."
                )

        env_content = "\n".join(f"{k}={v}" for k, v in env_vars.items()) + "\n"

        parent_dir = str(Path(canonical_path).parent)
        deploy_cmd = (
            f"sudo mkdir -p {parent_dir} && "
            f"sudo chmod 0755 {parent_dir} && "
            f"sudo tee {canonical_path} > /dev/null && "
            f"sudo chmod 0600 {canonical_path} && "
            f"sudo chown root:root {canonical_path}"
        )

        rc, stdout, stderr = run_remote_or_local_cmd(
            deploy_cmd,
            ssh_target,
            timeout=30,
            input_data=env_content,
        )

        if rc != 0:
            return {
                "action": "DEPLOY_ENGINE_ENV",
                "host_id": host_id,
                "canonical_path": canonical_path,
                "success": False,
                "error": stderr or stdout,
                "returncode": rc,
            }

        verify_cmd = f"sudo stat -c '%a %U:%G' {canonical_path} 2>/dev/null || stat -f '%Lp %Su:%Sg' {canonical_path} 2>/dev/null"
        rc_v, stdout_v, _ = run_remote_or_local_cmd(verify_cmd, ssh_target, timeout=10)
        stat_out = stdout_v.strip() if rc_v == 0 else "unknown"

        return {
            "action": "DEPLOY_ENGINE_ENV",
            "host_id": host_id,
            "canonical_path": canonical_path,
            "stat": stat_out,
            "permissions_ok": ("600" in stat_out and "root:root" in stat_out),
            "success": True,
            "message": f"Secret d'intégrité personas déposé avec succès dans {canonical_path} (0600 root:root) via entrée standard chiffrée.",
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


def run_remote_or_local_cmd(
    cmd: str,
    ssh_target: Optional[str] = None,
    timeout: int = 25,
    extra_env: Optional[Dict[str, str]] = None,
    input_data: Optional[str] = None,
) -> Tuple[int, str, str]:
    """Exécute une commande localement ou à distance via SSH avec encodage explicite UTF-8."""
    if ssh_target:
        full_cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", ssh_target, cmd]
    else:
        full_cmd = shlex.split(cmd)

    proc_env = dict(os.environ)
    if extra_env:
        proc_env.update(extra_env)

    try:
        proc = subprocess.run(
            full_cmd,
            input=input_data,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=proc_env,
            encoding="utf-8",
            errors="replace",
        )
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except subprocess.TimeoutExpired:
        return 124, "", "Commande expirée (Timeout)"
    except Exception as e:
        return 1, "", str(e)


def probe_docker_host(host_spec: Dict[str, Any]) -> Dict[str, Any]:
    """
    CA3 : Sonde le démon Docker d'un hôte pour en extraire l'empreinte active réelle.
    Règles de gouvernance (Arbitrage PO / KAN-64) :
    - La SOURCE DE VÉRITÉ est l'image réellement chargée par le conteneur en service (.Image / RepoDigests).
    - L'étiquette 'com.orso.engine.digest' est un CONTRÔLE CROISÉ : toute divergence avec l'image réelle alerte.
    - Un hôte sans conteneur client actif n'est JAMAIS déclaré IN_SYNC.
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
            "label_mismatch": False,
            "label_mismatch_detail": None,
            "error": stderr or "Démon Docker inaccessible",
        }

    running_containers = [c.strip() for c in stdout.splitlines() if c.strip()]
    matching_containers = [c for c in running_containers if container_filter in c]

    if not matching_containers:
        # Règle d'or KAN-64 : Aucun conteneur client actif en service.
        # Interdiction absolue d'aller sonder les images résiduelles en cache pour déclarer l'hôte IN_SYNC.
        return {
            "host_id": host_id,
            "host_name": host_name,
            "active_digest": "",
            "pinned_image": "",
            "running_containers": [],
            "is_reachable": True,
            "label_mismatch": False,
            "label_mismatch_detail": None,
            "error": "Aucun conteneur client actif en service",
        }

    target_c = matching_containers[0]
    inspect_cmd = (
        f"docker inspect --format '{{{{.Config.Image}}}} | "
        f"{{{{index .Config.Labels \"com.orso.engine.digest\"}}}} | "
        f"{{{{.Image}}}}' {target_c}"
    )
    rc_i, stdout_i, _ = run_remote_or_local_cmd(inspect_cmd, ssh_target)

    cfg_img = ""
    lbl_digest = ""
    img_id = ""
    if rc_i == 0 and stdout_i:
        parts = [p.strip() for p in stdout_i.split("|")]
        cfg_img = parts[0] if len(parts) > 0 else ""
        lbl_digest = parts[1] if len(parts) > 1 else ""
        img_id = parts[2] if len(parts) > 2 else ""

    # Extraction du RepoDigest de l'image Docker sous-jacente réellement chargée
    real_digest = ""
    real_image_repo = ""
    if img_id:
        rc_img, stdout_img, _ = run_remote_or_local_cmd(
            f"docker inspect --format '{{{{json .RepoDigests}}}}' {img_id}",
            ssh_target,
        )
        if rc_img == 0 and stdout_img:
            try:
                digests_list = json.loads(stdout_img)
                if isinstance(digests_list, list) and digests_list:
                    first_ref = digests_list[0]
                    if "@sha256:" in first_ref:
                        real_image_repo, real_digest = first_ref.split("@", 1)
            except Exception:
                pass

    if not real_digest:
        if "@sha256:" in cfg_img:
            real_image_repo, real_digest = cfg_img.split("@", 1)
        elif validate_digest(img_id):
            real_digest = img_id

    # La source de vérité absolue est l'image réelle
    active_digest = real_digest.strip()
    pinned_image = cfg_img or (f"{real_image_repo}@{real_digest}" if real_digest else img_id)

    # Contrôle croisé : vérification de concordance de l'étiquette
    label_mismatch = False
    label_mismatch_detail = None
    if lbl_digest and validate_digest(lbl_digest) and active_digest:
        if lbl_digest.strip().lower() != active_digest.strip().lower():
            label_mismatch = True
            label_mismatch_detail = (
                f"Divergence critique détectée sur {target_c} : "
                f"l'étiquette déclare '{lbl_digest}' mais l'image réellement chargée est '{pinned_image}' (digest: {active_digest})"
            )

    return {
        "host_id": host_id,
        "host_name": host_name,
        "active_digest": active_digest,
        "pinned_image": pinned_image,
        "running_containers": matching_containers,
        "is_reachable": True,
        "label_mismatch": label_mismatch,
        "label_mismatch_detail": label_mismatch_detail,
    }


def main():
    common_parser = argparse.ArgumentParser(add_help=False)
    common_parser.add_argument(
        "--target-digest",
        default=os.environ.get("ORSO_TARGET_ENGINE_DIGEST", "sha256:d8a5f82c448bb95b28a9b49b43e8b0b8c6e07eb4838a1f2987a123456789abcd"),
        help="Empreinte cryptographique cible attendue",
    )
    common_parser.add_argument(
        "--registry-base",
        default="ghcr.io/tquinzain59/orso-engine",
        help="Base du registre Docker GHCR",
    )

    parser = argparse.ArgumentParser(
        description="Orso Engine Image Distribution Manager",
        parents=[common_parser],
    )

    sub = parser.add_subparsers(dest="command")
    probe_parser = sub.add_parser("probe", parents=[common_parser], help="Sonde l'état réel des démons Docker de tous les hôtes")
    probe_parser.add_argument("--local", action="store_true", help="Sonde le démon Docker local sans passer par SSH")
    probe_parser.add_argument("--host-id", help="Identifiant de l'hôte (ex: prod-fr-003)")

    audit_parser = sub.add_parser("audit", parents=[common_parser], help="Exécute un audit de dérive en direct")
    audit_parser.add_argument("--local", action="store_true", help="Audit local uniquement sans passer par SSH")
    audit_parser.add_argument("--host-id", help="Identifiant de l'hôte (ex: prod-fr-003)")

    up_parser = sub.add_parser("update", parents=[common_parser], help="Exécute une mise à jour sur un hôte")
    up_parser.add_argument("--host-id", required=True)
    up_parser.add_argument("--new-digest", required=True)
    up_parser.add_argument("--container", default="orso_client_demo")
    up_parser.add_argument("--local", action="store_true", help="Exécute la mise à jour directement en local sans SSH")

    rb_parser = sub.add_parser("rollback", parents=[common_parser], help="Exécute un rollback sur un hôte")
    rb_parser.add_argument("--host-id", required=True)
    rb_parser.add_argument("--rollback-digest", required=True)
    rb_parser.add_argument("--container", default="orso_client_demo")
    rb_parser.add_argument("--local", action="store_true", help="Exécute le rollback directement en local sans SSH")

    env_parser = sub.add_parser("deploy-env", parents=[common_parser], help="Dépose le secret d'intégrité personas dans /etc/orso/engine.env (0600 root:root) via stdin chiffré")
    env_parser.add_argument("--host-id", required=True)
    env_parser.add_argument("--local", action="store_true", help="Déploiement en local")
    env_parser.add_argument("--path", default="/etc/orso/engine.env", help="Chemin canonique de destination")

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
        if getattr(args, "local", False):
            target_host = {
                "host_id": args.host_id,
                "host_name": f"Hôte Local ({args.host_id})",
                "ssh_target": None,
                "container_filter": "orso_client",
            }
        else:
            target_host = next((h for h in DEFAULT_HOSTS if h["host_id"] == args.host_id), None)
            if not target_host:
                print(f"Hôte inconnu : {args.host_id}")
                sys.exit(1)
        try:
            res = mgr.execute_live_host_update(target_host, new_digest=args.new_digest, container_name=args.container)
            print(json.dumps(res, indent=2))
            sys.exit(0 if res.get("success") else 1)
        except ValueError as e:
            print(f"[FAIL-CLOSED] {e}", file=sys.stderr)
            sys.exit(2)

    elif args.command == "rollback":
        if getattr(args, "local", False):
            target_host = {
                "host_id": args.host_id,
                "host_name": f"Hôte Local ({args.host_id})",
                "ssh_target": None,
                "container_filter": "orso_client",
            }
        else:
            target_host = next((h for h in DEFAULT_HOSTS if h["host_id"] == args.host_id), None)
            if not target_host:
                print(f"Hôte inconnu : {args.host_id}")
                sys.exit(1)
        try:
            res = mgr.execute_live_host_rollback(target_host, rollback_digest=args.rollback_digest, container_name=args.container)
            print(json.dumps(res, indent=2))
            sys.exit(0 if res.get("success") else 1)
        except ValueError as e:
            print(f"[FAIL-CLOSED] {e}", file=sys.stderr)
            sys.exit(2)

    elif args.command == "deploy-env":
        if getattr(args, "local", False):
            target_host = {
                "host_id": args.host_id,
                "host_name": f"Hôte Local ({args.host_id})",
                "ssh_target": None,
                "container_filter": "orso_client",
            }
        else:
            target_host = next((h for h in DEFAULT_HOSTS if h["host_id"] == args.host_id), None)
            if not target_host:
                print(f"Hôte inconnu : {args.host_id}")
                sys.exit(1)
        try:
            res = mgr.deploy_canonical_engine_env(target_host, canonical_path=args.path)
            print(json.dumps(res, indent=2))
            sys.exit(0 if res.get("success") else 1)
        except ValueError as e:
            print(f"[FAIL-CLOSED] {e}", file=sys.stderr)
            sys.exit(2)

    else:
        print("Moteur Orso épinglé :", mgr.get_target_pinned_image(human_tag="v1.0.0"))


if __name__ == "__main__":
    main()

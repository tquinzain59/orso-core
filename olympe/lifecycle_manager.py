"""Gestionnaire de Cycle de Vie et d'Orchestration des Conteneurs Clients Orso (Olympe).

Gère le provisioning, le démarrage à la demande (Wake-on-Demand), la mise en veille
et la supervision des conteneurs isolés orso_client_{slug}.
"""

import json
import logging
import os
import shutil
import subprocess
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any, Dict, List, Optional

_log = logging.getLogger("orso.olympe.lifecycle")


def normalize_container_name(tenant_slug: str) -> str:
    """Normalise le nom de conteneur Docker associé à un slug de tenant.
    Exemple: 'financia-solutions' -> 'orso_client_financia_solutions'
    """
    clean_slug = tenant_slug.strip().lower().replace("-", "_").replace(".", "_")
    return f"orso_client_{clean_slug}"


class DockerLifecycleManager:
    """Orchestrateur de cycle de vie Docker pour la flotte d'agents Orso."""

    def __init__(
        self,
        network_name: str = "orso_network",
        data_root: Optional[str] = None,
        supabase_url: Optional[str] = None,
        supabase_key: Optional[str] = None,
    ):
        self.network_name = network_name
        self.data_root = Path(data_root or os.environ.get("ORSO_DATA_ROOT", "./data/tenants")).resolve()
        self.supabase_url = (supabase_url or os.environ.get("SUPABASE_URL", "")).rstrip("/")
        self.supabase_key = supabase_key or os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
        self.has_docker = shutil.which("docker") is not None

    def _exec_docker(self, args: List[str], timeout: float = 15.0) -> subprocess.CompletedProcess:
        """Exécute une commande docker sécurisée avec timeout."""
        if not self.has_docker:
            raise RuntimeError("Le binaire Docker n'est pas accessible sur le système hôte.")
        cmd = ["docker"] + args
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )

    def get_tenant_status(self, tenant_slug: str) -> Dict[str, Any]:
        """Inspecte le statut réel du conteneur client Docker."""
        container_name = normalize_container_name(tenant_slug)

        if not self.has_docker:
            # Mode simulation ou environnement de test sans Docker daemon
            return {
                "tenant_slug": tenant_slug,
                "container_name": container_name,
                "status": "ready" if os.environ.get("ORSO_SIMULATION_MODE") == "1" else "unknown",
                "running": os.environ.get("ORSO_SIMULATION_MODE") == "1",
                "simulated": True,
            }

        proc = self._exec_docker(
            ["inspect", "--format", "{{json .State}}", container_name],
            timeout=5.0,
        )

        if proc.returncode != 0:
            return {
                "tenant_slug": tenant_slug,
                "container_name": container_name,
                "status": "not_found",
                "running": False,
                "detail": f"Le conteneur {container_name} n'est pas provisionné.",
            }

        try:
            state = json.loads(proc.stdout.strip())
            is_running = state.get("Running", False)
            is_paused = state.get("Paused", False)
            status_str = state.get("Status", "unknown")

            # Normalisation du statut
            if is_running:
                normalized_status = "ready"
            elif is_paused:
                normalized_status = "paused"
            elif status_str in ("exited", "dead", "created"):
                normalized_status = "sleeping"
            else:
                normalized_status = status_str

            return {
                "tenant_slug": tenant_slug,
                "container_name": container_name,
                "status": normalized_status,
                "running": is_running,
                "started_at": state.get("StartedAt"),
                "finished_at": state.get("FinishedAt"),
                "exit_code": state.get("ExitCode"),
            }
        except Exception as e:
            _log.error("Erreur lors de l'analyse de l'état du conteneur %s: %s", container_name, e)
            return {
                "tenant_slug": tenant_slug,
                "container_name": container_name,
                "status": "error",
                "running": False,
                "error": str(e),
            }

    def wake_tenant(self, tenant_slug: str, wait_healthy: bool = True, timeout: float = 12.0) -> Dict[str, Any]:
        """Réveille un conteneur en veille (docker start) et attend sa disponibilité."""
        container_name = normalize_container_name(tenant_slug)
        status_info = self.get_tenant_status(tenant_slug)

        if status_info.get("status") == "not_found":
            return {
                "success": False,
                "tenant_slug": tenant_slug,
                "status": "not_found",
                "message": f"Impossible de réveiller {container_name} : conteneur non provisionné.",
            }

        if status_info.get("running"):
            return {
                "success": True,
                "tenant_slug": tenant_slug,
                "status": "ready",
                "message": f"Le conteneur {container_name} est déjà en cours d'exécution.",
            }

        if not self.has_docker:
            return {
                "success": True,
                "tenant_slug": tenant_slug,
                "status": "ready",
                "simulated": True,
                "message": "Conteneur simulé démarré avec succès.",
            }

        _log.info("Réveil du conteneur client : %s", container_name)
        start_proc = self._exec_docker(["start", container_name], timeout=8.0)
        if start_proc.returncode != 0:
            err = start_proc.stderr.strip() or "Erreur inconnue lors du docker start"
            _log.error("Échec du réveil de %s: %s", container_name, err)
            return {
                "success": False,
                "tenant_slug": tenant_slug,
                "status": "error",
                "message": f"Échec du démarrage : {err}",
            }

        if not wait_healthy:
            return {
                "success": True,
                "tenant_slug": tenant_slug,
                "status": "starting",
                "message": f"Conteneur {container_name} en cours de démarrage.",
            }

        # Attente active du statut healthy
        start_time = time.time()
        while time.time() - start_time < timeout:
            time.sleep(0.8)
            curr = self.get_tenant_status(tenant_slug)
            if curr.get("running"):
                return {
                    "success": True,
                    "tenant_slug": tenant_slug,
                    "status": "ready",
                    "duration_seconds": round(time.time() - start_time, 2),
                    "message": f"Conteneur {container_name} opérationnel et prêt.",
                }

        return {
            "success": True,
            "tenant_slug": tenant_slug,
            "status": "starting",
            "warning": f"Démarré mais le conteneur met plus de {timeout}s à répondre.",
        }

    def suspend_tenant(self, tenant_slug: str, timeout: float = 10.0) -> Dict[str, Any]:
        """Met en veille un conteneur inactif pour libérer de la mémoire RAM (docker stop)."""
        container_name = normalize_container_name(tenant_slug)
        status_info = self.get_tenant_status(tenant_slug)

        if status_info.get("status") == "not_found":
            return {
                "success": False,
                "tenant_slug": tenant_slug,
                "status": "not_found",
                "message": f"Conteneur {container_name} introuvable.",
            }

        if not status_info.get("running"):
            return {
                "success": True,
                "tenant_slug": tenant_slug,
                "status": "sleeping",
                "message": f"Conteneur {container_name} déjà en veille.",
            }

        if not self.has_docker:
            return {
                "success": True,
                "tenant_slug": tenant_slug,
                "status": "sleeping",
                "simulated": True,
            }

        _log.info("Mise en veille du conteneur client : %s", container_name)
        stop_proc = self._exec_docker(["stop", "-t", "5", container_name], timeout=timeout)
        if stop_proc.returncode != 0:
            return {
                "success": False,
                "tenant_slug": tenant_slug,
                "status": "error",
                "message": stop_proc.stderr.strip() or "Erreur lors de l'arrêt du conteneur",
            }

        return {
            "success": True,
            "tenant_slug": tenant_slug,
            "status": "sleeping",
            "message": f"Conteneur {container_name} placé en veille avec succès.",
        }

    def provision_tenant(
        self,
        tenant_id: str,
        tenant_slug: str,
        image_name: str = "orso-backend:latest",
        env_vars: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Provisionne un nouvel environnement client hermétique."""
        container_name = normalize_container_name(tenant_slug)
        tenant_data_dir = self.data_root / tenant_slug
        tenant_data_dir.mkdir(parents=True, exist_ok=True)

        status_info = self.get_tenant_status(tenant_slug)
        if status_info.get("status") not in ("not_found", "unknown"):
            return {
                "success": True,
                "tenant_slug": tenant_slug,
                "container_name": container_name,
                "already_exists": True,
                "status": status_info.get("status"),
                "message": f"Le conteneur {container_name} est déjà provisionné.",
            }

        base_envs = {
            "ORSO_CLIENT_ID": tenant_id,
            "ORSO_CLIENT_SLUG": tenant_slug,
            "HERMES_CONFIG_PATH": "/app/config/hermes.yaml",
            "HERMES_HOME": "/app/data/hermes_home",
        }
        if self.supabase_url:
            base_envs["SUPABASE_URL"] = self.supabase_url
        if self.supabase_key:
            base_envs["SUPABASE_SERVICE_ROLE_KEY"] = self.supabase_key
        if env_vars:
            base_envs.update(env_vars)

        if not self.has_docker:
            return {
                "success": True,
                "tenant_slug": tenant_slug,
                "container_name": container_name,
                "status": "ready",
                "simulated": True,
                "message": "Provisioning simulé avec succès.",
            }

        run_args = [
            "run",
            "-d",
            "--name", container_name,
            "--network", self.network_name,
            "--restart", "unless-stopped",
            "-v", f"{tenant_data_dir}:/app/data",
        ]

        for k, v in base_envs.items():
            run_args.extend(["-e", f"{k}={v}"])

        run_args.append(image_name)

        _log.info("Lancement du provisioning pour %s (%s)", tenant_slug, container_name)
        proc = self._exec_docker(run_args, timeout=20.0)
        if proc.returncode != 0:
            err = proc.stderr.strip()
            _log.error("Échec du docker run pour %s: %s", container_name, err)
            return {
                "success": False,
                "tenant_slug": tenant_slug,
                "container_name": container_name,
                "error": err,
            }

        # Mise à jour Supabase si configuré
        self._sync_tenant_instance_record(
            tenant_id=tenant_id,
            tenant_slug=tenant_slug,
            container_name=container_name,
        )

        return {
            "success": True,
            "tenant_slug": tenant_slug,
            "container_name": container_name,
            "status": "ready",
            "data_directory": str(tenant_data_dir),
            "message": f"Conteneur {container_name} provisionné et démarré avec succès.",
        }

    def _sync_tenant_instance_record(
        self,
        tenant_id: str,
        tenant_slug: str,
        container_name: str,
    ) -> None:
        """Enregistre ou met à jour la ligne tenant_instances dans Supabase."""
        if not self.supabase_url or not self.supabase_key:
            return

        payload = json.dumps({
            "tenant_id": tenant_id,
            "internal_route_key": container_name,
            "docker_container_name": container_name,
            "instance_url": f"https://app.orso-agents.fr/t/{tenant_slug}",
            "environment_status": "active",
            "status": "ready",
        }).encode("utf-8")

        req = urllib.request.Request(
            f"{self.supabase_url}/rest/v1/tenant_instances",
            data=payload,
            headers={
                "apikey": self.supabase_key,
                "Authorization": f"Bearer {self.supabase_key}",
                "Content-Type": "application/json",
                "Prefer": "resolution=merge-duplicates",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=4.0):
                _log.info("Référence tenant_instances synchronisée pour %s", tenant_slug)
        except Exception as e:
            _log.warning("Impossible de synchroniser tenant_instances avec Supabase: %s", e)

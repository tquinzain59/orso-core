"""Gestionnaire de Cycle de Vie et d'Orchestration des Conteneurs Clients Orso (Olympe).

Gère le provisioning, le démarrage à la demande (Wake-on-Demand), la mise en veille
et la supervision des conteneurs isolés orso_client_{slug}.
"""

import json
import logging
import os
import re
import shutil
import subprocess
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
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
        image_digest: Optional[str] = None,
        env_vars: Optional[Dict[str, str]] = None,
        quotas: Optional[Dict[str, Any]] = None,
        require_digest: Optional[bool] = None,
        allow_floating_tag: bool = False,
        persona_hmac_key: Optional[str] = None,
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

        default_image = os.environ.get("ORSO_BACKEND_IMAGE", "orso-core-orso-backend:latest")
        target_image = default_image if (not image_name or image_name == "orso-backend:latest") else image_name

        # Alignement de la variable de digest de référence (KAN-64) :
        # ORSO_TARGET_ENGINE_DIGEST (spécification) avec repli sur ORSO_BACKEND_IMAGE_DIGEST
        effective_digest = (
            image_digest
            or os.environ.get("ORSO_TARGET_ENGINE_DIGEST")
            or os.environ.get("ORSO_BACKEND_IMAGE_DIGEST", "")
        ).strip()

        # Règle d'or KAN-64 : Le refus du provisioning sans digest valide est INCONDITIONNEL par défaut.
        # Seul un paramètre explicite allow_floating_tag=True peut lever ce refus pour des tests locaux.
        allow_floating = (
            allow_floating_tag
            if allow_floating_tag is not None
            else os.environ.get("ORSO_ALLOW_FLOATING_TAG", "false").lower() in ("true", "1", "yes")
        )

        has_embedded_digest = "@sha256:" in target_image
        if has_embedded_digest and not effective_digest:
            effective_digest = target_image.split("@", 1)[1].strip()

        if effective_digest:
            if not re.match(r"^sha256:[a-f0-9]{64}$", effective_digest):
                return {
                    "success": False,
                    "error": "ERR_INVALID_DIGEST",
                    "tenant_slug": tenant_slug,
                    "message": f"Provisioning refusé : digest SHA-256 invalide '{effective_digest}'. Format attendu : sha256:<64_hex_digits>",
                }
            if not has_embedded_digest:
                base_repo = target_image.split(":")[0]
                target_image = f"{base_repo}@{effective_digest}"
        elif not allow_floating:
            # CA6 : Refus formel et inconditionnel
            return {
                "success": False,
                "error": "ERR_DIGEST_REQUIRED",
                "tenant_slug": tenant_slug,
                "message": (
                    "Provisioning refusé : une image épinglée par un digest SHA-256 valide est strictement requise "
                    "(tag flottant interdit). Spécifiez 'image_digest' ou la variable ORSO_TARGET_ENGINE_DIGEST."
                ),
            }

        # Règle d'or KAN-33 / KAN-64 (Arbitrage Thibaut - Commentaire 13) :
        # Le plan de gestion lit ORSO_PERSONA_HMAC_KEY dans son propre environnement
        # et la transmet au conteneur client lors du docker run (base_envs).
        # Si la variable est absente de l'environnement de gestion lors de la création,
        # le provisioning échoue explicitement (ERR_HMAC_KEY_REQUIRED), sans créer de conteneur zombi.
        effective_hmac_key = (
            persona_hmac_key
            or (env_vars or {}).get("ORSO_PERSONA_HMAC_KEY")
            or os.environ.get("ORSO_PERSONA_HMAC_KEY")
        )
        if not effective_hmac_key:
            return {
                "success": False,
                "error": "ERR_HMAC_KEY_REQUIRED",
                "tenant_slug": tenant_slug,
                "message": (
                    "Provisioning refusé : ORSO_PERSONA_HMAC_KEY est strictement requise "
                    "dans l'environnement de gestion pour garantir l'intégrité cryptographique des personas."
                ),
            }

        base_envs = {
            "ORSO_CLIENT_ID": tenant_id,
            "ORSO_CLIENT_SLUG": tenant_slug,
            "HERMES_CONFIG_PATH": "/app/config/hermes.yaml",
            "HERMES_HOME": "/app/data/hermes_home",
            "ORSO_PERSONA_HMAC_KEY": effective_hmac_key,
        }
        for key in ["OPENROUTER_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY"]:
            val = os.environ.get(key)
            if val:
                base_envs[key] = val

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
                "image": target_image,
                "digest": effective_digest or None,
                "quotas": quotas or {},
                "message": "Provisioning simulé avec succès.",
            }

        now_iso = datetime.now(timezone.utc).isoformat()
        run_args = [
            "run",
            "-d",
            "--name", container_name,
            "--network", self.network_name,
            "--network-alias", container_name,
            "--network-alias", f"orso_client_{tenant_slug}",
            "--restart", "unless-stopped",
            "--label", "com.orso.managed=true",
            "--label", f"com.orso.tenant_id={tenant_id}",
            "--label", f"com.orso.tenant_slug={tenant_slug}",
            "--label", "com.orso.role=client_backend",
            "--label", f"com.orso.created_at={now_iso}",
            "--label", f"com.orso.engine.image={target_image}",
            *(["--label", f"com.orso.engine.digest={effective_digest}", "--label", "com.orso.engine.pinned=true"] if effective_digest else []),
            "-v", f"{tenant_data_dir}:/app/data",
        ]

        # Quotas explicites de ressources (L3)
        effective_quotas = quotas or {}
        if tenant_slug in ("clientx-orso",) and not quotas:
            effective_quotas = {"cpus": "0.5", "memory": "512m", "pids_limit": "100"}

        if effective_quotas:
            cpus = str(effective_quotas.get("cpus", "0.5"))
            memory = str(effective_quotas.get("memory", "512m"))
            pids = str(effective_quotas.get("pids_limit", "100"))
            run_args.extend([
                "--cpus", cpus,
                "--memory", memory,
                "--memory-swap", memory,
                "--pids-limit", pids,
                "--label", f"com.orso.quotas.cpus={cpus}",
                "--label", f"com.orso.quotas.memory={memory}",
                "--label", f"com.orso.quotas.pids_limit={pids}",
            ])
            if tenant_slug in ("clientx-orso",):
                run_args.extend(["--label", "com.orso.sandbox=true"])

        # Montages partagés de configuration et compétences si présents
        project_root = Path(__file__).resolve().parent.parent
        for shared_dir in ["config", "skills", "profiles"]:
            p = project_root / shared_dir
            if p.is_dir():
                run_args.extend(["-v", f"{p}:/app/{shared_dir}:ro"])

        for k, v in base_envs.items():
            run_args.extend(["-e", f"{k}={v}"])

        run_args.append(target_image)

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
            "image": target_image,
            "digest": effective_digest or None,
            "quotas": effective_quotas,
            "data_directory": str(tenant_data_dir),
            "message": f"Conteneur {container_name} provisionné et démarré avec succès.",
        }

    def teardown_tenant(self, tenant_slug: str, remove_data: bool = True) -> Dict[str, Any]:
        """Détruit proprement et de manière idempotente un conteneur client et son stockage (L3/CA2)."""
        container_name = normalize_container_name(tenant_slug)
        tenant_data_dir = self.data_root / tenant_slug

        if not self.has_docker:
            if remove_data and tenant_data_dir.exists():
                shutil.rmtree(tenant_data_dir, ignore_errors=True)
            return {
                "success": True,
                "tenant_slug": tenant_slug,
                "container_name": container_name,
                "status": "destroyed",
                "simulated": True,
                "message": f"Conteneur simulé {container_name} détruit sans résidu.",
            }

        status_info = self.get_tenant_status(tenant_slug)
        if status_info.get("status") != "not_found":
            _log.info("Arrêt et suppression forcée du conteneur : %s", container_name)
            self._exec_docker(["rm", "-f", container_name], timeout=15.0)

        if remove_data and tenant_data_dir.exists():
            _log.info("Suppression du répertoire de données client pour : %s", tenant_slug)
            shutil.rmtree(tenant_data_dir, ignore_errors=True)

        self._remove_tenant_instance_record(container_name)

        return {
            "success": True,
            "tenant_slug": tenant_slug,
            "container_name": container_name,
            "status": "destroyed",
            "message": f"Conteneur {container_name} et volume supprimés sans résidu.",
        }

    def _remove_tenant_instance_record(self, container_name: str) -> None:
        """Supprime la ligne correspondante dans tenant_instances dans Supabase."""
        if not self.supabase_url or not self.supabase_key:
            return
        req = urllib.request.Request(
            f"{self.supabase_url}/rest/v1/tenant_instances?docker_container_name=eq.{container_name}",
            headers={
                "apikey": self.supabase_key,
                "Authorization": f"Bearer {self.supabase_key}",
            },
            method="DELETE",
        )
        try:
            with urllib.request.urlopen(req, timeout=4.0):
                _log.info("Référence tenant_instances supprimée pour %s", container_name)
        except Exception as e:
            _log.warning("Impossible de supprimer tenant_instances dans Supabase: %s", e)

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

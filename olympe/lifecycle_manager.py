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
        spaces_root: Optional[str] = None,
    ):
        self.network_name = network_name
        self.data_root = Path(data_root or os.environ.get("ORSO_DATA_ROOT", "./data/tenants")).resolve()
        if spaces_root:
            self.spaces_root = Path(spaces_root).resolve()
        elif "ORSO_SPACES_ROOT" in os.environ:
            self.spaces_root = Path(os.environ["ORSO_SPACES_ROOT"]).resolve()
        else:
            if data_root:
                self.spaces_root = (Path(data_root) / "spaces").resolve()
            else:
                self.spaces_root = Path("./data/spaces").resolve()
        self.supabase_url = (supabase_url or os.environ.get("SUPABASE_URL", "")).rstrip("/")
        self.supabase_key = supabase_key or os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
        self.has_docker = shutil.which("docker") is not None

    def get_tenant_space_dir(self, tenant_slug: str) -> Path:
        """Retourne le chemin vers le dossier d'espace d'agents propre au client (KAN-58)."""
        return (self.spaces_root / tenant_slug).resolve()

    def _initialize_tenant_space(
        self,
        tenant_slug: str,
        target_space_dir: Path,
        source_template_dir: Optional[Path] = None,
    ) -> None:
        """Initialise l'arborescence de l'espace d'agents propre au client (config, skills, profiles).
        Garantit que chaque client dispose de sa propre copie isolée sans partage d'hôte (KAN-58).
        """
        target_space_dir.mkdir(parents=True, exist_ok=True)
        project_root = Path(__file__).resolve().parent.parent

        # 1. config
        dest_config = target_space_dir / "config"
        if not dest_config.exists():
            src_config = (source_template_dir / "config") if source_template_dir else (project_root / "config")
            if src_config.is_dir():
                shutil.copytree(src_config, dest_config)
            else:
                dest_config.mkdir(parents=True, exist_ok=True)

        # 2. skills
        dest_skills = target_space_dir / "skills"
        if not dest_skills.exists():
            src_skills = (source_template_dir / "skills") if source_template_dir else (project_root / "skills")
            if src_skills.is_dir():
                shutil.copytree(src_skills, dest_skills)
            else:
                dest_skills.mkdir(parents=True, exist_ok=True)

        # 3. profiles
        dest_profiles = target_space_dir / "profiles"
        if not dest_profiles.exists():
            src_profiles = (source_template_dir / "profiles") if source_template_dir else (project_root / "profiles")
            if src_profiles.is_dir():
                shutil.copytree(src_profiles, dest_profiles)
            else:
                dest_profiles.mkdir(parents=True, exist_ok=True)

    def backup_tenant_space(self, tenant_slug: str, backup_tag: Optional[str] = None) -> Path:
        """Crée une sauvegarde horodatée de l'espace d'agents propre d'un client."""
        space_dir = self.get_tenant_space_dir(tenant_slug)
        if not space_dir.is_dir():
            raise FileNotFoundError(f"Espace client introuvable : {space_dir}")
        tag = backup_tag or datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        backup_dir = self.spaces_root / ".backups" / f"{tenant_slug}_{tag}"
        backup_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(space_dir, backup_dir)
        _log.info("Sauvegarde de l'espace client créée : %s", backup_dir)
        return backup_dir

    def rollback_tenant_space(
        self,
        tenant_slug: str,
        backup_path: Optional[Path] = None,
        restart_container: bool = True,
    ) -> Dict[str, Any]:
        """Exécute la procédure de retour arrière sur l'espace d'agents d'un client (CA4).
        Sauvegarde préventivement l'état actuel avant restauration, puis restaure
        la sauvegarde spécifiée ou réinitialise à l'état usine baseline.
        Contrôle la santé et le redémarrage effectif du conteneur.
        """
        space_dir = self.get_tenant_space_dir(tenant_slug)
        project_root = Path(__file__).resolve().parent.parent

        if not space_dir.exists():
            return {
                "success": False,
                "error": "ERR_SPACE_NOT_FOUND",
                "tenant_slug": tenant_slug,
                "message": f"Espace client introuvable pour {tenant_slug}.",
            }

        # Sauvegarde préventive avant rollback (sécurité anti-écrasement irréversible)
        pre_rollback_backup = None
        try:
            tag = f"pre_rollback_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
            pre_rollback_backup = self.backup_tenant_space(tenant_slug, backup_tag=tag)
        except Exception as e:
            _log.warning("Impossible de créer la sauvegarde préventive pour %s: %s", tenant_slug, e)

        if backup_path and Path(backup_path).is_dir():
            source_dir = Path(backup_path)
            mode = "backup_restore"
        else:
            # Restauration baseline usine
            source_dir = project_root
            mode = "baseline_restore"

        try:
            shutil.rmtree(space_dir)
            self._initialize_tenant_space(
                tenant_slug,
                space_dir,
                source_template_dir=source_dir if mode == "backup_restore" else None,
            )
        except Exception as e:
            _log.error("Échec lors de la restauration des fichiers pour %s: %s", tenant_slug, e)
            return {
                "success": False,
                "error": "ERR_RESTORE_FAILED",
                "tenant_slug": tenant_slug,
                "mode": mode,
                "pre_rollback_backup": str(pre_rollback_backup) if pre_rollback_backup else None,
                "message": f"Échec de la restauration de l'espace client : {str(e)}",
            }

        action_taken = False
        container_healthy = True
        if restart_container and self.has_docker:
            container_name = normalize_container_name(tenant_slug)
            status = self.get_tenant_status(tenant_slug)
            if status.get("running"):
                _log.info("Redémarrage du conteneur après rollback de l'espace : %s", container_name)
                proc = self._exec_docker(["restart", container_name], timeout=15.0)
                if proc.returncode != 0:
                    err_msg = proc.stderr.strip() or "Erreur lors du docker restart"
                    _log.error("Échec du redémarrage du conteneur %s: %s", container_name, err_msg)
                    return {
                        "success": False,
                        "error": "ERR_CONTAINER_RESTART_FAILED",
                        "tenant_slug": tenant_slug,
                        "mode": mode,
                        "container_restarted": False,
                        "container_healthy": False,
                        "pre_rollback_backup": str(pre_rollback_backup) if pre_rollback_backup else None,
                        "message": f"Espace restauré mais échec du redémarrage du conteneur : {err_msg}",
                    }
                action_taken = True
                post_status = self.get_tenant_status(tenant_slug)
                container_healthy = post_status.get("running", False)

        return {
            "success": True,
            "tenant_slug": tenant_slug,
            "mode": mode,
            "source_restored": str(source_dir),
            "space_directory": str(space_dir),
            "pre_rollback_backup": str(pre_rollback_backup) if pre_rollback_backup else None,
            "container_restarted": action_taken,
            "container_healthy": container_healthy,
            "message": f"Retour arrière de l'espace client '{tenant_slug}' exécuté avec succès ({mode}).",
        }

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
            # Mode simulation ou environnement sans Docker daemon local
            from olympe.ops_manager import is_production
            mode = "delegated_host" if is_production() else "simulated"
            return {
                "tenant_slug": tenant_slug,
                "container_name": container_name,
                "status": "ready" if os.environ.get("ORSO_SIMULATION_MODE") == "1" else "unknown",
                "running": os.environ.get("ORSO_SIMULATION_MODE") == "1",
                "simulated": True,
                "mode": mode,
                "action_taken": False,
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
                "simulated": False,
                "mode": "containerized",
                "action_taken": False,
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
                "simulated": False,
                "mode": "containerized",
                "action_taken": False,
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
                "simulated": False,
                "mode": "containerized",
                "action_taken": False,
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
                "simulated": False,
                "mode": status_info.get("mode", "containerized"),
                "action_taken": False,
                "message": f"Impossible de réveiller {container_name} : conteneur non provisionné.",
            }

        if status_info.get("running"):
            return {
                "success": True,
                "tenant_slug": tenant_slug,
                "status": "ready",
                "simulated": status_info.get("simulated", False),
                "mode": status_info.get("mode", "containerized"),
                "action_taken": False,
                "message": f"Le conteneur {container_name} est déjà en cours d'exécution.",
            }

        if not self.has_docker:
            from olympe.ops_manager import is_production
            if is_production():
                return {
                    "success": False,
                    "error": "ERR_NO_LOCAL_DOCKER_DELEGATED_HOST_REQUIRED",
                    "tenant_slug": tenant_slug,
                    "status": "error",
                    "simulated": False,
                    "mode": "delegated_host",
                    "action_taken": False,
                    "message": "Réveil in-process refusé : aucun démon Docker local sur l'hôte de gestion. Le réveil des conteneurs clients en production est exclusivement délégué aux hôtes d'exécution dédiés (PROD-FR-003).",
                }
            return {
                "success": True,
                "tenant_slug": tenant_slug,
                "status": "ready",
                "simulated": True,
                "mode": "simulated",
                "action_taken": False,
                "message": "Conteneur simulé démarré avec succès (mode simulé).",
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
                "simulated": False,
                "mode": "containerized",
                "action_taken": False,
                "message": f"Échec du démarrage : {err}",
            }

        if not wait_healthy:
            return {
                "success": True,
                "tenant_slug": tenant_slug,
                "status": "starting",
                "simulated": False,
                "mode": "containerized",
                "action_taken": True,
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
                    "simulated": False,
                    "mode": "containerized",
                    "action_taken": True,
                    "duration_seconds": round(time.time() - start_time, 2),
                    "message": f"Conteneur {container_name} opérationnel et prêt.",
                }

        return {
            "success": True,
            "tenant_slug": tenant_slug,
            "status": "starting",
            "simulated": False,
            "mode": "containerized",
            "action_taken": True,
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
                "simulated": False,
                "mode": status_info.get("mode", "containerized"),
                "action_taken": False,
                "message": f"Conteneur {container_name} introuvable.",
            }

        if not status_info.get("running"):
            return {
                "success": True,
                "tenant_slug": tenant_slug,
                "container_name": container_name,
                "status": "sleeping",
                "simulated": status_info.get("simulated", False),
                "mode": status_info.get("mode", "containerized"),
                "action_taken": False,
                "message": f"Conteneur {container_name} déjà en veille (mode {status_info.get('mode', 'containerized')}).",
            }

        if not self.has_docker:
            from olympe.ops_manager import is_production
            mode = "delegated_host" if is_production() else "simulated"
            return {
                "success": True,
                "tenant_slug": tenant_slug,
                "container_name": container_name,
                "status": "sleeping",
                "simulated": True,
                "mode": mode,
                "action_taken": False,
                "message": f"Conteneur {container_name} placé en veille (mode {mode}, aucune action conteneur physique requise).",
            }

        _log.info("Mise en veille du conteneur client : %s", container_name)
        stop_proc = self._exec_docker(["stop", "-t", "5", container_name], timeout=timeout)
        if stop_proc.returncode != 0:
            return {
                "success": False,
                "tenant_slug": tenant_slug,
                "container_name": container_name,
                "status": "error",
                "simulated": False,
                "mode": "containerized",
                "action_taken": False,
                "message": stop_proc.stderr.strip() or "Erreur lors de l'arrêt du conteneur",
            }

        return {
            "success": True,
            "tenant_slug": tenant_slug,
            "container_name": container_name,
            "status": "sleeping",
            "simulated": False,
            "mode": "containerized",
            "action_taken": True,
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
        custom_space_dir: Optional[str] = None,
        use_dedicated_space: bool = True,
    ) -> Dict[str, Any]:
        container_name = normalize_container_name(tenant_slug)

        # Montages de l'environnement client (fin des dossiers partagés KAN-58 / Document 27)
        legacy_shared = not use_dedicated_space or os.environ.get("ORSO_LEGACY_SHARED_MOUNTS") == "1"
        if legacy_shared:
            from olympe.ops_manager import is_production
            if is_production():
                return {
                    "success": False,
                    "error": "ERR_LEGACY_MOUNTS_FORBIDDEN_IN_PROD",
                    "tenant_slug": tenant_slug,
                    "container_name": container_name,
                    "action_taken": False,
                    "message": "Provisioning refusé : les montages partagés legacy sont formellement proscrits en environnement de production (KAN-58). L'espace d'agents dédié est obligatoire.",
                }

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
            # En production, le provisioning in-process local sur l'Hôte 1 est strictement proscrit (Option B KAN-74)
            from olympe.ops_manager import is_production
            if is_production():
                return {
                    "success": False,
                    "error": "ERR_NO_LOCAL_DOCKER_DELEGATED_HOST_REQUIRED",
                    "tenant_slug": tenant_slug,
                    "container_name": container_name,
                    "simulated": False,
                    "mode": "delegated_host",
                    "action_taken": False,
                    "message": (
                        "Provisioning in-process refusé : aucun démon Docker local sur l'hôte de gestion. "
                        "Le déploiement des conteneurs clients en production est exclusivement délégué aux hôtes d'exécution dédiés (PROD-FR-003)."
                    ),
                }

            legacy_shared = not use_dedicated_space or os.environ.get("ORSO_LEGACY_SHARED_MOUNTS") == "1"
            if legacy_shared:
                from olympe.ops_manager import is_production
                if is_production():
                    return {
                        "success": False,
                        "error": "ERR_LEGACY_MOUNTS_FORBIDDEN_IN_PROD",
                        "tenant_slug": tenant_slug,
                        "container_name": container_name,
                        "simulated": False,
                        "mode": "delegated_host",
                        "action_taken": False,
                        "message": "Provisioning refusé : les montages partagés legacy sont formellement proscrits en environnement de production (KAN-58). L'espace d'agents dédié est obligatoire.",
                    }

            simulated_space_dir = str(Path(custom_space_dir).resolve() if custom_space_dir else self.get_tenant_space_dir(tenant_slug)) if not legacy_shared else None
            return {
                "success": True,
                "tenant_slug": tenant_slug,
                "container_name": container_name,
                "status": "ready",
                "simulated": True,
                "mode": "simulated",
                "action_taken": False,
                "image": target_image,
                "digest": effective_digest or None,
                "quotas": quotas or {},
                "data_directory": str(tenant_data_dir),
                "space_directory": simulated_space_dir,
                "dedicated_space": not legacy_shared,
                "message": "Provisioning simulé avec succès (mode simulé, aucune action conteneur physique).",
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

        # Montages de l'environnement client (fin des dossiers partagés KAN-58 / Document 27)
        project_root = Path(__file__).resolve().parent.parent
        legacy_shared = not use_dedicated_space or os.environ.get("ORSO_LEGACY_SHARED_MOUNTS") == "1"

        if legacy_shared:
            from olympe.ops_manager import is_production
            if is_production():
                return {
                    "success": False,
                    "error": "ERR_LEGACY_MOUNTS_FORBIDDEN_IN_PROD",
                    "tenant_slug": tenant_slug,
                    "container_name": container_name,
                    "action_taken": False,
                    "message": "Provisioning refusé : les montages partagés legacy sont formellement proscrits en environnement de production (KAN-58). L'espace d'agents dédié est obligatoire.",
                }
            # Mode legacy de repli (partage des dossiers de l'hôte, déprécié KAN-58 / Document 27)
            _log.warning("Provisioning avec montages partagés legacy pour %s", tenant_slug)
            for shared_dir in ["config", "skills", "profiles"]:
                p = project_root / shared_dir
                if p.is_dir():
                    run_args.extend(["-v", f"{p}:/app/{shared_dir}:ro"])
            tenant_space_dir = None
        else:
            # Mode KAN-58 : Espace d'agents propre et hermétique à chaque client
            tenant_space_dir = Path(custom_space_dir).resolve() if custom_space_dir else self.get_tenant_space_dir(tenant_slug)
            self._initialize_tenant_space(tenant_slug, tenant_space_dir)

            tenant_config_dir = tenant_space_dir / "config"
            tenant_skills_dir = tenant_space_dir / "skills"
            tenant_profiles_dir = tenant_space_dir / "profiles"

            if tenant_config_dir.is_dir():
                run_args.extend(["-v", f"{tenant_config_dir}:/app/config:ro"])
            if tenant_skills_dir.is_dir():
                run_args.extend(["-v", f"{tenant_skills_dir}:/app/skills:ro"])

            # CA3 : Convergence des trois points de montage de profils vers une seule source par client
            # 1. /app/profiles (racine de profils canonique)
            # 2. /app/data/hermes_home/profiles (découverte Hermes multi-profils sur HERMES_HOME)
            # 3. /home/orso/.hermes/profiles (chemin utilisateur conteneur orso)
            if tenant_profiles_dir.is_dir():
                run_args.extend([
                    "-v", f"{tenant_profiles_dir}:/app/profiles:ro",
                    "-v", f"{tenant_profiles_dir}:/app/data/hermes_home/profiles:ro",
                    "-v", f"{tenant_profiles_dir}:/home/orso/.hermes/profiles:ro",
                ])

            run_args.extend([
                "--label", "com.orso.space.type=dedicated",
                "--label", f"com.orso.space.path={tenant_space_dir}",
            ])

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
            "simulated": False,
            "mode": "containerized",
            "action_taken": True,
            "image": target_image,
            "digest": effective_digest or None,
            "quotas": effective_quotas,
            "data_directory": str(tenant_data_dir),
            "space_directory": str(tenant_space_dir) if tenant_space_dir else None,
            "dedicated_space": not legacy_shared,
            "message": f"Conteneur {container_name} provisionné et démarré avec succès.",
        }

    def teardown_tenant(self, tenant_slug: str, remove_data: bool = True) -> Dict[str, Any]:
        """Détruit proprement et de manière idempotente un conteneur client et son stockage (L3/CA2)."""
        container_name = normalize_container_name(tenant_slug)
        tenant_data_dir = self.data_root / tenant_slug
        tenant_space_dir = self.get_tenant_space_dir(tenant_slug)

        if not self.has_docker:
            if remove_data:
                if tenant_data_dir.exists():
                    shutil.rmtree(tenant_data_dir, ignore_errors=True)
                if tenant_space_dir.exists():
                    shutil.rmtree(tenant_space_dir, ignore_errors=True)
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

        if remove_data:
            if tenant_data_dir.exists():
                _log.info("Suppression du répertoire de données client pour : %s", tenant_slug)
                shutil.rmtree(tenant_data_dir, ignore_errors=True)
            if tenant_space_dir.exists():
                _log.info("Suppression du répertoire d'espace client pour : %s", tenant_slug)
                shutil.rmtree(tenant_space_dir, ignore_errors=True)

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

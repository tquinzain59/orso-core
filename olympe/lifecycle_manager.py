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
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from olympe.artifact_manager import ClientSpaceArtifactManager

_log = logging.getLogger("orso.olympe.lifecycle")


def _clean_env(key: str) -> Optional[str]:
    """Extrait une variable d'environnement en la traitant comme absente si vide ou blanche."""
    val = os.environ.get(key)
    if val is None:
        return None
    val_clean = val.strip()
    return val_clean if val_clean else None


def _safe_int_env(key: str, default: Optional[int] = None) -> Optional[int]:
    """Lit un entier d'environnement de manière sûre sans jamais lever de ValueError."""
    cleaned = _clean_env(key)
    if cleaned is None:
        return default
    try:
        return int(cleaned)
    except (ValueError, TypeError):
        _log.warning("Variable d'environnement %s invalide (%r), repli sur %s", key, cleaned, default)
        return default


def _safe_float_env(key: str, default: Optional[float] = None) -> Optional[float]:
    """Lit un float d'environnement de manière sûre sans jamais lever de ValueError."""
    cleaned = _clean_env(key)
    if cleaned is None:
        return default
    try:
        return float(cleaned)
    except (ValueError, TypeError):
        _log.warning("Variable d'environnement %s invalide (%r), repli sur %s", key, cleaned, default)
        return default




# ── Quotas Matériels par Défaut & Paliers Tarifaires (KAN-59 / Document 27) ──

DEFAULT_CLIENT_QUOTAS = {
    "cpus": "0.5",
    "memory": "512m",
    "pids_limit": "100",
}

TIER_RESOURCE_QUOTAS: Dict[str, Dict[str, Any]] = {
    "none": {"cpus": "0.5", "memory": "512m", "pids_limit": "100", "agents_max": 0},
    "1_agent": {"cpus": "0.5", "memory": "512m", "pids_limit": "100", "agents_max": 1},
    "2_agents": {"cpus": "1.0", "memory": "1024m", "pids_limit": "150", "agents_max": 2},
    "3_agents": {"cpus": "1.5", "memory": "1536m", "pids_limit": "200", "agents_max": 3},
    "4_agents": {"cpus": "2.0", "memory": "2048m", "pids_limit": "250", "agents_max": 4},
    "custom": {"cpus": "2.0", "memory": "2048m", "pids_limit": "250", "agents_max": 4},
}


def parse_memory_str_to_mb(mem_val: Any) -> int:
    """Convertit une chaîne de quota mémoire Docker (ex: '512m', '1g', '2048M') en mégaoctets entiers."""
    if isinstance(mem_val, (int, float)):
        return int(mem_val)
    if not mem_val or not isinstance(mem_val, str):
        return 512
    s = mem_val.strip().lower()
    m = re.match(r"^([0-9]+(?:\.[0-9]+)?)\s*([a-z]*)$", s)
    if not m:
        return 512
    num_str, unit = m.groups()
    num = float(num_str)
    if unit in ("g", "gb", "gib"):
        return int(num * 1024)
    elif unit in ("k", "kb", "kib"):
        return max(1, int(num / 1024))
    else:  # "m", "mb", "mib" ou sans unité
        return int(num)


def parse_cpus_str_to_float(cpu_val: Any) -> float:
    """Convertit une chaîne de quota vCPU (ex: '0.5', '1', '2.0') en float."""
    if isinstance(cpu_val, (int, float)):
        return float(cpu_val)
    if not cpu_val or not isinstance(cpu_val, str):
        return 0.5
    try:
        return float(cpu_val.strip())
    except (ValueError, TypeError):
        return 0.5


def get_quotas_for_tier(
    tier_id: Optional[str] = None,
    overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Retourne les quotas matériels garantis pour un palier tarifaire, fusionnés avec les surcharges (CA1/CA4)."""
    base = dict(TIER_RESOURCE_QUOTAS.get(tier_id or "1_agent", DEFAULT_CLIENT_QUOTAS))
    res = {
        "cpus": str(base.get("cpus", "0.5")),
        "memory": str(base.get("memory", "512m")),
        "pids_limit": str(base.get("pids_limit", "100")),
    }
    if overrides and isinstance(overrides, dict):
        if "cpus" in overrides and overrides["cpus"] is not None:
            res["cpus"] = str(overrides["cpus"])
        if "memory" in overrides and overrides["memory"] is not None:
            res["memory"] = str(overrides["memory"])
        if "pids_limit" in overrides and overrides["pids_limit"] is not None:
            res["pids_limit"] = str(overrides["pids_limit"])
        elif "pids" in overrides and overrides["pids"] is not None:
            res["pids_limit"] = str(overrides["pids"])
    return res


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
        host_max_memory_mb: Optional[int] = None,
        host_max_cpus: Optional[float] = None,
        host_max_containers: Optional[int] = None,
        host_flavor: Optional[str] = None,
        artifacts_root: Optional[str] = None,
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

        if artifacts_root:
            self.artifacts_root = Path(artifacts_root).resolve()
        elif "ORSO_ARTIFACTS_ROOT" in os.environ:
            self.artifacts_root = Path(os.environ["ORSO_ARTIFACTS_ROOT"]).resolve()
        else:
            self.artifacts_root = (self.spaces_root.parent / "artifacts").resolve()
        self.artifacts_root.mkdir(parents=True, exist_ok=True)

        self.artifact_manager = ClientSpaceArtifactManager(
            artifacts_root=self.artifacts_root,
            spaces_root=self.spaces_root,
        )

        self.supabase_url = (supabase_url or os.environ.get("SUPABASE_URL", "")).rstrip("/")
        self.supabase_key = supabase_key or os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
        self.has_docker = shutil.which("docker") is not None

        # ── Gestion Dynamique de la Capacité Matérielle Hôte (KAN-59 / CA2 / CA4) ──
        self.host_capacity_info = self._resolve_host_capacity(
            host_max_memory_mb=host_max_memory_mb,
            host_max_cpus=host_max_cpus,
            host_max_containers=host_max_containers,
            host_flavor=host_flavor,
        )
        self.host_max_memory_mb = self.host_capacity_info["max_memory_mb"]
        self.host_max_cpus = self.host_capacity_info["max_cpus"]
        self.host_max_containers = self.host_capacity_info["max_containers"]
        self.host_flavor = self.host_capacity_info["flavor_name"]

        self._simulated_containers: Dict[str, Dict[str, Any]] = {}

    @staticmethod
    def _resolve_host_capacity(
        host_max_memory_mb: Optional[int] = None,
        host_max_cpus: Optional[float] = None,
        host_max_containers: Optional[int] = None,
        host_flavor: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Détermine dynamiquement la capacité matérielle de l'hôte et cite sa source de vérité (KAN-59).
        Résout selon la priorité :
        1. Paramètres explicites passés au constructeur
        2. Variables d'environnement explicites (ORSO_HOST_MAX_MEMORY_MB, ORSO_HOST_MAX_CPUS)
        3. Sonde physique de l'hôte (meminfo / sysconf / cpu_count)
        4. Gabarit OVH explicitement demandé (ORSO_HOST_FLAVOR)
        5. Repli documenté baseline (3072 MB, 2.0 vCPUs)
        """
        # Résolution sécurisée du gabarit : uniquement si explicitement non vide
        explicit_flavor = False
        flavor_name = None
        if host_flavor and host_flavor.strip():
            explicit_flavor = True
            flavor_name = host_flavor.strip()
        else:
            env_flavor = _clean_env("ORSO_HOST_FLAVOR")
            if env_flavor:
                explicit_flavor = True
                flavor_name = env_flavor

        from olympe.ovh_client import OVH_FLAVORS
        flavor_spec = OVH_FLAVORS.get(flavor_name) if flavor_name else None

        # Réserve système (Point 2 Jarvis) : configurable via ORSO_HOST_SYSTEM_RESERVE_RAM_MB ou ORSO_SYSTEM_RESERVED_MEM_MB
        # Par défaut 512 Mo pour couvrir l'OS Linux, Docker daemon, Olympe supervisor et Ingress Nginx.
        reserved_sys_mem = _safe_int_env("ORSO_HOST_SYSTEM_RESERVE_RAM_MB", None)
        if reserved_sys_mem is None:
            reserved_sys_mem = _safe_int_env("ORSO_SYSTEM_RESERVED_MEM_MB", 512)
        if reserved_sys_mem is None or reserved_sys_mem < 0:
            reserved_sys_mem = 512

        cpu_overcommit = _safe_float_env("ORSO_CPU_OVERCOMMIT_RATIO", 2.0)
        if cpu_overcommit is None or cpu_overcommit <= 0:
            cpu_overcommit = 2.0

        system_total_mem_mb = None
        system_avail_mem_mb = None
        system_total_cpus = None

        try:
            if Path("/proc/meminfo").exists():
                with open("/proc/meminfo", "r", encoding="utf-8", errors="replace") as f:
                    for line in f:
                        if line.startswith("MemTotal:"):
                            system_total_mem_mb = int(line.split()[1]) // 1024
                        elif line.startswith("MemAvailable:"):
                            system_avail_mem_mb = int(line.split()[1]) // 1024
        except Exception:
            pass

        if system_total_mem_mb is None:
            try:
                pages = os.sysconf("SC_PHYS_PAGES")
                page_size = os.sysconf("SC_PAGE_SIZE")
                system_total_mem_mb = (pages * page_size) // (1024 * 1024)
            except Exception:
                pass

        try:
            system_total_cpus = float(os.cpu_count() or 2)
        except Exception:
            pass

        # 1. Mémoire maximale
        env_mem = _safe_int_env("ORSO_HOST_MAX_MEMORY_MB")
        if host_max_memory_mb is not None:
            resolved_mem = host_max_memory_mb
            mem_source = f"explicit_parameter ({host_max_memory_mb} MB)"
        elif env_mem is not None:
            resolved_mem = env_mem
            mem_source = f"env_ORSO_HOST_MAX_MEMORY_MB ({resolved_mem} MB)"
        elif system_total_mem_mb and not explicit_flavor:
            resolved_mem = max(512, system_total_mem_mb - reserved_sys_mem)
            mem_source = f"host_physical_probe:meminfo ({system_total_mem_mb}MB total - {reserved_sys_mem}MB reserve = {resolved_mem}MB)"
        elif flavor_spec:
            resolved_mem = max(512, flavor_spec["ram_mb"] - reserved_sys_mem)
            mem_source = f"ovh_catalog_flavor:{flavor_name} ({flavor_spec['ram_mb']}MB - {reserved_sys_mem}MB reserve = {resolved_mem}MB)"
        elif system_total_mem_mb:
            resolved_mem = max(512, system_total_mem_mb - reserved_sys_mem)
            mem_source = f"host_physical_probe ({system_total_mem_mb}MB - {reserved_sys_mem}MB reserve = {resolved_mem}MB)"
        else:
            resolved_mem = 3072
            mem_source = "default_fallback (3072 MB)"

        # 2. CPU maximal (avec ratio de surallocation pour conteneurs I/O bound)
        env_cpus = _safe_float_env("ORSO_HOST_MAX_CPUS")
        if host_max_cpus is not None:
            resolved_cpus = float(host_max_cpus)
            cpu_source = f"explicit_parameter ({resolved_cpus} vCPUs)"
        elif env_cpus is not None:
            resolved_cpus = env_cpus
            cpu_source = f"env_ORSO_HOST_MAX_CPUS ({resolved_cpus} vCPUs)"
        elif system_total_cpus and not explicit_flavor:
            resolved_cpus = round(system_total_cpus * cpu_overcommit, 2)
            cpu_source = f"host_physical_probe:cpu_count ({system_total_cpus} vCPUs x {cpu_overcommit} overcommit = {resolved_cpus} vCPUs)"
        elif flavor_spec:
            base_cpus = float(flavor_spec["vcpus"])
            resolved_cpus = round(base_cpus * cpu_overcommit, 2)
            cpu_source = f"ovh_catalog_flavor:{flavor_name} ({base_cpus} vCPUs x {cpu_overcommit} overcommit = {resolved_cpus} vCPUs)"
        elif system_total_cpus:
            resolved_cpus = round(system_total_cpus * cpu_overcommit, 2)
            cpu_source = f"host_physical_probe ({system_total_cpus} vCPUs x {cpu_overcommit} overcommit = {resolved_cpus} vCPUs)"
        else:
            resolved_cpus = 2.0
            cpu_source = "default_fallback (2.0 vCPUs)"

        # 3. Conteneurs max
        env_containers = _safe_int_env("ORSO_HOST_MAX_CONTAINERS")
        if host_max_containers is not None:
            resolved_containers = host_max_containers
        elif env_containers is not None:
            resolved_containers = env_containers
        elif flavor_spec:
            resolved_containers = flavor_spec.get("capacity_agents", 4)
        else:
            resolved_containers = 4

        return {
            "max_memory_mb": resolved_mem,
            "max_cpus": resolved_cpus,
            "max_containers": resolved_containers,
            "memory_source": mem_source,
            "cpu_source": cpu_source,
            "system_total_mem_mb": system_total_mem_mb,
            "system_available_mem_mb": system_avail_mem_mb,
            "system_total_cpus": system_total_cpus,
            "flavor_name": flavor_name,
            "reserved_system_mem_mb": reserved_sys_mem,
        }

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
        shutil.copytree(space_dir, backup_dir, dirs_exist_ok=True)
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

    def deploy_tenant_artifact(
        self,
        tenant_slug: str,
        version: str,
        restart_container: bool = True,
    ) -> Dict[str, Any]:
        """Déploie une version d'artefact d'espace client et actualise le conteneur (KAN-60 / CA1, CA2)."""
        space_dir = self.get_tenant_space_dir(tenant_slug)
        manifest = self.artifact_manager.get_artifact_manifest(tenant_slug, version)
        if not manifest:
            return {
                "success": False,
                "error": "ERR_ARTIFACT_NOT_FOUND",
                "tenant_slug": tenant_slug,
                "version": version,
                "message": f"Artefact introuvable pour {tenant_slug} version {version}",
            }

        try:
            deploy_res = self.artifact_manager.extract_and_deploy_artifact(
                tenant_slug=tenant_slug,
                version=version,
                target_space_dir=space_dir,
                verify_fingerprint=True,
            )
        except Exception as e:
            _log.error("Échec déploiement artefact %s v%s: %s", tenant_slug, version, e)
            return {
                "success": False,
                "error": "ERR_ARTIFACT_DEPLOY_FAILED",
                "tenant_slug": tenant_slug,
                "version": version,
                "message": f"Échec du déploiement de l'artefact : {e}",
            }

        container_restarted = False
        container_healthy = True
        if restart_container and self.has_docker:
            container_name = normalize_container_name(tenant_slug)
            status = self.get_tenant_status(tenant_slug)
            if status.get("running"):
                _log.info("Redémarrage du conteneur après déploiement d'artefact : %s", container_name)
                proc = self._exec_docker(["restart", container_name], timeout=15.0)
                container_restarted = (proc.returncode == 0)
                post_status = self.get_tenant_status(tenant_slug)
                container_healthy = post_status.get("running", False)

        return {
            "success": True,
            "tenant_slug": tenant_slug,
            "version": version,
            "fingerprint": deploy_res.get("fingerprint"),
            "content_fingerprint": deploy_res.get("content_fingerprint"),
            "space_directory": str(space_dir),
            "container_restarted": container_restarted,
            "container_healthy": container_healthy,
            "deployed_at": deploy_res.get("deployed_at"),
            "message": f"Artefact {version} déployé avec succès pour {tenant_slug}.",
        }

    def rollback_tenant_artifact(
        self,
        tenant_slug: str,
        target_version: str,
        restart_container: bool = True,
    ) -> Dict[str, Any]:
        """Exécute un retour arrière vers une version d'artefact d'espace client antérieure (KAN-60 / CA3)."""
        res = self.deploy_tenant_artifact(
            tenant_slug=tenant_slug,
            version=target_version,
            restart_container=restart_container,
        )
        if res.get("success"):
            res["action"] = "artifact_rollback"
            res["message"] = f"Retour arrière vers l'artefact {target_version} exécuté avec succès pour {tenant_slug}."
        return res

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

    def get_host_allocated_resources(self) -> Dict[str, Any]:
        """Calcule les ressources matérielles allouées aux conteneurs clients gérés sur l'hôte (KAN-59)."""
        allocated_memory_mb = 0
        allocated_cpus = 0.0
        managed_containers: List[Dict[str, Any]] = []

        if self.has_docker:
            # Inspection des conteneurs réels sur le démon Docker
            proc = self._exec_docker([
                "ps", "-a",
                "--format", "{{json .}}",
            ], timeout=10.0)
            if proc.returncode == 0 and proc.stdout.strip():
                for line in proc.stdout.strip().splitlines():
                    if not line.strip():
                        continue
                    try:
                        c_info = json.loads(line.strip())
                        c_name = c_info.get("Names", "")
                        inspect_proc = self._exec_docker([
                            "inspect",
                            "--format",
                            "{{json .Config.Labels}}|||{{.HostConfig.Memory}}|||{{.HostConfig.NanoCpus}}|||{{.State.Status}}",
                            c_name,
                        ], timeout=5.0)
                        if inspect_proc.returncode == 0:
                            parts = inspect_proc.stdout.strip().split("|||")
                            labels = json.loads(parts[0]) if len(parts) > 0 and parts[0] else {}
                            raw_mem_bytes = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
                            raw_nano_cpus = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
                            status = parts[3] if len(parts) > 3 else "unknown"

                            # Détection exhaustive de tout conteneur client
                            is_client = (
                                "orso_client" in c_name
                                or labels.get("com.orso.role") in ("client_backend", "client")
                                or "com.orso.tenant_slug" in labels
                                or "com.orso.tenant_id" in labels
                                or "com.orso.tier_id" in labels
                            )
                            is_managed = labels.get("com.orso.managed") == "true"

                            # Doctrine d'admission : Tout conteneur client provisionné réserve sa capacité,
                            # même s'il est en veille scale-to-zero, afin de garantir un réveil immédiat (wake-on-demand).
                            if is_managed or is_client:
                                mem_label = labels.get("com.orso.quotas.memory")
                                if mem_label:
                                    mem_mb = parse_memory_str_to_mb(mem_label)
                                elif raw_mem_bytes > 0:
                                    mem_mb = int(raw_mem_bytes / (1024 * 1024))
                                elif is_client:
                                    # Conteneur client sans quota explicite : comptabilisé au socle par défaut (512 Mo)
                                    mem_mb = 512
                                else:
                                    mem_mb = 0

                                cpu_label = labels.get("com.orso.quotas.cpus")
                                if cpu_label:
                                    cpus = parse_cpus_str_to_float(cpu_label)
                                elif raw_nano_cpus > 0:
                                    cpus = round(raw_nano_cpus / 1e9, 2)
                                elif is_client:
                                    cpus = 0.5
                                else:
                                    cpus = 0.0

                                allocated_memory_mb += mem_mb
                                allocated_cpus += cpus
                                managed_containers.append({
                                    "name": c_name,
                                    "slug": labels.get("com.orso.tenant_slug") or c_name.replace("orso_client_", ""),
                                    "memory_mb": mem_mb,
                                    "cpus": cpus,
                                    "status": status,
                                    "unbridled": (not mem_label and raw_mem_bytes == 0),
                                })
                    except Exception as e:
                        _log.debug("Erreur parsing conteneur pour quotas: %s", e)

        # Prise en compte des conteneurs simulés enregistrés
        for slug, sim_c in self._simulated_containers.items():
            if not any(c.get("slug") == slug for c in managed_containers):
                q = sim_c.get("quotas", {})
                mem_mb = parse_memory_str_to_mb(q.get("memory", "512m"))
                cpus = parse_cpus_str_to_float(q.get("cpus", "0.5"))
                allocated_memory_mb += mem_mb
                allocated_cpus += cpus
                managed_containers.append({
                    "name": normalize_container_name(slug),
                    "slug": slug,
                    "memory_mb": mem_mb,
                    "cpus": cpus,
                    "status": "simulated",
                })

        available_memory_mb = max(0, self.host_max_memory_mb - allocated_memory_mb)
        available_cpus = max(0.0, round(self.host_max_cpus - allocated_cpus, 2))

        return {
            "hostname": socket.gethostname(),
            "host_max_memory_mb": self.host_max_memory_mb,
            "host_max_cpus": self.host_max_cpus,
            "host_capacity_source": self.host_capacity_info.get("memory_source", "default"),
            "host_cpu_source": self.host_capacity_info.get("cpu_source", "default"),
            "host_flavor": self.host_flavor,
            "allocated_memory_mb": allocated_memory_mb,
            "allocated_cpus": round(allocated_cpus, 2),
            "available_memory_mb": available_memory_mb,
            "available_cpus": available_cpus,
            "containers_count": len(managed_containers),
            "containers": managed_containers,
            "system_metrics": {
                "system_total_mem_mb": self.host_capacity_info.get("system_total_mem_mb"),
                "system_available_mem_mb": self.host_capacity_info.get("system_available_mem_mb"),
                "system_total_cpus": self.host_capacity_info.get("system_total_cpus"),
                "reserved_system_mem_mb": self.host_capacity_info.get("reserved_system_mem_mb"),
            },
        }

    def check_host_admission(
        self,
        tenant_slug: str,
        quotas: Dict[str, Any],
    ) -> Tuple[bool, Optional[str], Dict[str, Any]]:
        """Contrôle d'admission strict : valide que l'hôte dispose de la capacité matérielle requise (CA2)."""
        req_mem_mb = parse_memory_str_to_mb(quotas.get("memory", "512m"))
        req_cpus = parse_cpus_str_to_float(quotas.get("cpus", "0.5"))

        usage = self.get_host_allocated_resources()

        # Si le conteneur existe déjà parmi les conteneurs alloués, on ne compte pas deux fois
        existing = next((c for c in usage["containers"] if c["slug"] == tenant_slug), None)
        current_alloc_mem = usage["allocated_memory_mb"] - (existing["memory_mb"] if existing else 0)
        current_alloc_cpus = usage["allocated_cpus"] - (existing["cpus"] if existing else 0.0)

        new_total_mem = current_alloc_mem + req_mem_mb
        new_total_cpus = current_alloc_cpus + req_cpus

        capacity_details = {
            "tenant_slug": tenant_slug,
            "requested_memory_mb": req_mem_mb,
            "requested_cpus": req_cpus,
            "host_max_memory_mb": usage["host_max_memory_mb"],
            "host_max_cpus": usage["host_max_cpus"],
            "host_capacity_source": usage.get("host_capacity_source"),
            "host_cpu_source": usage.get("host_cpu_source"),
            "current_allocated_memory_mb": current_alloc_mem,
            "current_allocated_cpus": round(current_alloc_cpus, 2),
            "available_memory_mb": max(0, usage["host_max_memory_mb"] - current_alloc_mem),
            "available_cpus": max(0.0, round(usage["host_max_cpus"] - current_alloc_cpus, 2)),
            "new_total_memory_mb": new_total_mem,
            "new_total_cpus": round(new_total_cpus, 2),
        }

        if new_total_mem > usage["host_max_memory_mb"]:
            msg = (
                f"Capacité mémoire de l'hôte dépassée pour '{tenant_slug}' : "
                f"{req_mem_mb} Mo requis, {capacity_details['available_memory_mb']} Mo disponibles "
                f"(plafond hôte: {usage['host_max_memory_mb']} Mo, alloué: {current_alloc_mem} Mo)."
            )
            return False, msg, capacity_details

        if new_total_cpus > usage["host_max_cpus"]:
            msg = (
                f"Capacité processeur de l'hôte dépassée pour '{tenant_slug}' : "
                f"{req_cpus} vCPU requis, {capacity_details['available_cpus']} vCPU disponibles "
                f"(plafond hôte: {usage['host_max_cpus']} vCPU, alloué: {round(current_alloc_cpus, 2)} vCPU)."
            )
            return False, msg, capacity_details

        if self.host_max_containers and (usage["containers_count"] + (0 if existing else 1)) > self.host_max_containers:
            msg = (
                f"Nombre maximal de conteneurs atteint sur l'hôte ({self.host_max_containers})."
            )
            return False, msg, capacity_details

        return True, None, capacity_details

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
        tier_id: Optional[str] = None,
        require_digest: Optional[bool] = None,
        allow_floating_tag: bool = False,
        persona_hmac_key: Optional[str] = None,
        custom_space_dir: Optional[str] = None,
        use_dedicated_space: bool = True,
        artifact_version: Optional[str] = None,
        artifact_digest: Optional[str] = None,
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

        for auth_key in ["HERMES_DASHBOARD_BASIC_AUTH_USERNAME", "HERMES_DASHBOARD_BASIC_AUTH_PASSWORD", "HERMES_DASHBOARD_BASIC_AUTH_PASSWORD_HASH"]:
            val = os.environ.get(auth_key)
            if val:
                base_envs[auth_key] = val

        if self.supabase_url:
            base_envs["SUPABASE_URL"] = self.supabase_url
        if self.supabase_key:
            base_envs["SUPABASE_SERVICE_ROLE_KEY"] = self.supabase_key
        if env_vars:
            base_envs.update(env_vars)


        # ── Quotas de Ressources & Contrôle d'Admission de l'Hôte (KAN-59 / CA1 / CA2 / CA4) ──
        effective_quotas = get_quotas_for_tier(tier_id=tier_id, overrides=quotas)
        admitted, admission_reason, capacity_details = self.check_host_admission(tenant_slug, effective_quotas)
        if not admitted:
            _log.warning(
                "Provisioning refusé pour %s : capacité hôte dépassée (%s)",
                tenant_slug,
                admission_reason,
            )
            return {
                "success": False,
                "error": "ERR_HOST_CAPACITY_EXCEEDED",
                "tenant_slug": tenant_slug,
                "container_name": container_name,
                "message": f"Provisioning refusé : {admission_reason}",
                "capacity_details": capacity_details,
                "quotas": effective_quotas,
                "tier_id": tier_id or "1_agent",
            }

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
            simulated_artifact_digest = None
            if artifact_version:
                sim_manifest = self.artifact_manager.get_artifact_manifest(tenant_slug, artifact_version)
                simulated_artifact_digest = sim_manifest.get("fingerprint") if sim_manifest else (artifact_digest or f"sha256:simulated_art_{artifact_version}")

            self._simulated_containers[tenant_slug] = {
                "tenant_id": tenant_id,
                "tenant_slug": tenant_slug,
                "quotas": effective_quotas,
                "tier_id": tier_id or "1_agent",
                "artifact_version": artifact_version,
                "artifact_digest": simulated_artifact_digest,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
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
                "artifact_version": artifact_version,
                "artifact_digest": simulated_artifact_digest,
                "quotas": effective_quotas,
                "tier_id": tier_id or "1_agent",
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

        # Quotas stricts de ressources (L3 / KAN-59 / CA1)
        # Règle CA1 inviolable : AUCUN conteneur client ne peut être créé sans limites explicites de processeur, mémoire, swap et processus
        cpus = str(effective_quotas["cpus"])
        memory = str(effective_quotas["memory"])
        pids = str(effective_quotas["pids_limit"])
        run_args.extend([
            "--cpus", cpus,
            "--memory", memory,
            "--memory-swap", memory,
            "--pids-limit", pids,
            "--label", f"com.orso.quotas.cpus={cpus}",
            "--label", f"com.orso.quotas.memory={memory}",
            "--label", f"com.orso.quotas.pids_limit={pids}",
            "--label", f"com.orso.tier_id={tier_id or 'default'}",
        ])
        if tenant_slug in ("clientx-orso",):
            run_args.extend(["--label", "com.orso.sandbox=true"])

        # Montages de l'environnement client (fin des dossiers partagés KAN-58 / Document 27)
        project_root = Path(__file__).resolve().parent.parent
        legacy_shared = not use_dedicated_space or os.environ.get("ORSO_LEGACY_SHARED_MOUNTS") == "1"
        applied_artifact_version = None
        applied_artifact_digest = None

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
            # Mode KAN-58 / KAN-60 : Espace d'agents propre et hermétique à chaque client
            tenant_space_dir = Path(custom_space_dir).resolve() if custom_space_dir else self.get_tenant_space_dir(tenant_slug)

            applied_artifact_version = None
            applied_artifact_digest = None
            if artifact_version:
                deploy_res = self.artifact_manager.extract_and_deploy_artifact(
                    tenant_slug=tenant_slug,
                    version=artifact_version,
                    target_space_dir=tenant_space_dir,
                    verify_fingerprint=True,
                )
                applied_artifact_version = artifact_version
                applied_artifact_digest = deploy_res.get("fingerprint")
            else:
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
            if applied_artifact_version:
                run_args.extend([
                    "--label", f"com.orso.artifact.version={applied_artifact_version}",
                    "--label", f"com.orso.artifact.digest={applied_artifact_digest}",
                    "--label", "com.orso.artifact.mounted_ro=true",
                ])

        for k, v in base_envs.items():
            run_args.extend(["-e", f"{k}={v}"])

        run_args.append(target_image)

        # ── Validation stricte d'authentification dashboard (Refus explicite sans secret committé - KAN-58) ──
        dashboard_user = base_envs.get("HERMES_DASHBOARD_BASIC_AUTH_USERNAME")
        dashboard_secret = (
            base_envs.get("HERMES_DASHBOARD_BASIC_AUTH_PASSWORD")
            or base_envs.get("HERMES_DASHBOARD_BASIC_AUTH_PASSWORD_HASH")
        )
        if not (dashboard_user and dashboard_secret):
            return {
                "success": False,
                "error": "ERR_DASHBOARD_AUTH_REQUIRED",
                "tenant_slug": tenant_slug,
                "container_name": container_name,
                "mode": "containerized",
                "action_taken": False,
                "message": (
                    "Provisioning refusé : authentification dashboard manquante. "
                    "HERMES_DASHBOARD_BASIC_AUTH_USERNAME et (HERMES_DASHBOARD_BASIC_AUTH_PASSWORD ou HERMES_DASHBOARD_BASIC_AUTH_PASSWORD_HASH) "
                    "doivent être explicitement fournis (aucun secret de repli par défaut dans le code)."
                ),
            }

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
            "artifact_version": applied_artifact_version,
            "artifact_digest": applied_artifact_digest,
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

        self._simulated_containers.pop(tenant_slug, None)

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

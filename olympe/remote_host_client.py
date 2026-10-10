"""Module d'orchestration et d'acheminement réseau multi-hôtes (KAN-61 / POC 4).

Gère le pilotage non-interactif du moteur Docker sur un second hôte d'exécution
(ex: prod-fr-003 / 57.131.196.106) depuis le plan de gestion Olympe (prod-fr-002),
l'acheminement étanche du trafic client par slug, la traçabilité des opérations
et la vérification de non-transit des données clients sur le plan de contrôle.
"""

from __future__ import annotations

import errno
import json
import logging
import os
import re
import socket
import subprocess
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_log = logging.getLogger("olympe.remote_host")


@dataclass
class RemoteHostConfig:
    """Spécification d'un hôte d'exécution client dans la flotte Olympe."""
    host_id: str = "prod-fr-003"
    host_name: str = "Serveur Clients OVH (Hôte 2)"
    ip: str = "57.131.196.106"
    ssh_user: str = "ubuntu"
    ssh_port: int = 22
    base_port: int = 9230
    port_range_start: int = 9231
    port_range_end: int = 9299
    max_memory_mb: int = 3302
    max_cpus: float = 2.0
    container_filter: str = "orso_client"

    @property
    def ssh_target(self) -> str:
        return f"{self.ssh_user}@{self.ip}"

    @property
    def docker_host(self) -> str:
        return f"ssh://{self.ssh_target}"


DEFAULT_REMOTE_HOSTS = {
    "prod-fr-003": RemoteHostConfig(
        host_id="prod-fr-003",
        host_name="Serveur Clients OVH (Hôte 2)",
        ip=os.environ.get("ORSO_REMOTE_HOST_IP", "57.131.196.106"),
        ssh_user=os.environ.get("ORSO_REMOTE_HOST_USER", "ubuntu"),
        base_port=9230,
        port_range_start=9231,
        port_range_end=9299,
        max_memory_mb=3302,
        max_cpus=2.0,
    ),
    "prod-fr-002": RemoteHostConfig(
        host_id="prod-fr-002",
        host_name="Serveur Olympe & Build (Hôte 1)",
        ip=os.environ.get("ORSO_MANAGEMENT_HOST_IP", "92.222.68.80"),
        ssh_user="ubuntu",
        base_port=9229,
        port_range_start=9229,
        port_range_end=9230,
        max_memory_mb=7000,
        max_cpus=4.0,
    ),
}


class RemoteDockerHostManager:
    """Gestionnaire de flotte multi-hôtes et pilote Docker distant non-interactif (KAN-61)."""

    def __init__(
        self,
        hosts: Optional[Dict[str, RemoteHostConfig]] = None,
        audit_log_path: Optional[Path] = None,
        default_target_host: str = "prod-fr-003",
    ):
        self.hosts: Dict[str, RemoteHostConfig] = hosts or dict(DEFAULT_REMOTE_HOSTS)
        self.default_target_host = default_target_host
        self.audit_log_path = Path(
            audit_log_path or os.environ.get("ORSO_REMOTE_AUDIT_LOG", "./data/remote_audit.jsonl")
        ).resolve()
        self.audit_log_path.parent.mkdir(parents=True, exist_ok=True)
        self._audit_events: List[Dict[str, Any]] = []

        # Table de routage dynamique des espaces clients : slug -> {host_id, host_ip, port, status}
        self._routing_table: Dict[str, Dict[str, Any]] = {}
        self._allocated_ports: Dict[str, int] = {}
        self._next_port = 9231

    def get_host_config(self, host_id: Optional[str] = None) -> RemoteHostConfig:
        """Retourne la configuration de l'hôte demandé ou de l'hôte par défaut."""
        hid = host_id or self.default_target_host
        if hid not in self.hosts:
            raise KeyError(f"Hôte non répertorié dans la flotte : {hid}")
        return self.hosts[hid]

    def record_audit_event(
        self,
        host_id: str,
        operation: str,
        command: List[str],
        return_code: int,
        stdout: str,
        stderr: str,
        duration_ms: float,
        tenant_slug: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Enregistre un événement d'orchestration distante dans le journal d'audit (CA3)."""
        now_iso = datetime.now(timezone.utc).isoformat()
        event = {
            "timestamp": now_iso,
            "host_id": host_id,
            "operation": operation,
            "tenant_slug": tenant_slug or "fleet",
            "command": " ".join(command),
            "return_code": return_code,
            "stdout_summary": (stdout[:300] + ("..." if len(stdout) > 300 else "")).strip(),
            "stderr_summary": (stderr[:300] + ("..." if len(stderr) > 300 else "")).strip(),
            "duration_ms": round(duration_ms, 2),
        }
        self._audit_events.append(event)
        try:
            with open(self.audit_log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
        except Exception as e:
            _log.warning("Impossible d'écrire dans le journal d'audit distant : %s", e)
        return event

    def get_audit_events(self, tenant_slug: Optional[str] = None) -> List[Dict[str, Any]]:
        """Récupère les événements d'audit enregistrés, filtrables par tenant."""
        if tenant_slug:
            return [e for e in self._audit_events if e.get("tenant_slug") == tenant_slug]
        return list(self._audit_events)

    def exec_docker(
        self,
        args: List[str],
        host_id: Optional[str] = None,
        timeout: float = 25.0,
        tenant_slug: Optional[str] = None,
        operation: str = "custom",
        input_data: Optional[str] = None,
    ) -> subprocess.CompletedProcess:
        """Exécute une commande Docker sur l'hôte distant de manière non-interactive (CA1/CA3 / KAN-65)."""
        host_cfg = self.get_host_config(host_id)
        # Utilisation de -H ssh://user@ip pour le transport Docker natif non-interactif
        cmd = ["docker", "-H", host_cfg.docker_host] + args

        t0 = time.time()
        try:
            proc = subprocess.run(
                cmd,
                input=input_data,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
                encoding="utf-8",
                errors="replace",
            )
            duration_ms = (time.time() - t0) * 1000.0
            self.record_audit_event(
                host_id=host_cfg.host_id,
                operation=operation,
                command=cmd,
                return_code=proc.returncode,
                stdout=proc.stdout,
                stderr=proc.stderr,
                duration_ms=duration_ms,
                tenant_slug=tenant_slug,
            )
            return proc
        except subprocess.TimeoutExpired as e:
            duration_ms = (time.time() - t0) * 1000.0
            self.record_audit_event(
                host_id=host_cfg.host_id,
                operation=f"{operation}_timeout",
                command=cmd,
                return_code=-1,
                stdout="",
                stderr=f"TimeoutExpired after {timeout}s",
                duration_ms=duration_ms,
                tenant_slug=tenant_slug,
            )
            return subprocess.CompletedProcess(
                args=cmd,
                returncode=-1,
                stdout="",
                stderr=f"Commande distante expirée après {timeout} secondes.",
            )

    def probe_host(self, host_id: Optional[str] = None) -> Dict[str, Any]:
        """Sonde l'état réel du démon Docker sur l'hôte distant sans accès interactif (CA1)."""
        host_cfg = self.get_host_config(host_id)
        proc = self.exec_docker(
            ["info", "--format", "{{json .}}"],
            host_id=host_cfg.host_id,
            timeout=10.0,
            operation="probe_info",
        )
        if proc.returncode == 0:
            try:
                info_data = json.loads(proc.stdout.strip())
                return {
                    "reachable": True,
                    "host_id": host_cfg.host_id,
                    "host_ip": host_cfg.ip,
                    "docker_version": info_data.get("ServerVersion", "unknown"),
                    "os": info_data.get("OperatingSystem", "unknown"),
                    "kernel": info_data.get("KernelVersion", "unknown"),
                    "cpus": info_data.get("NCPU", 0),
                    "memory_total_bytes": info_data.get("MemTotal", 0),
                    "containers_running": info_data.get("ContainersRunning", 0),
                    "containers_total": info_data.get("Containers", 0),
                    "error": None,
                }
            except Exception as e:
                return {
                    "reachable": True,
                    "host_id": host_cfg.host_id,
                    "host_ip": host_cfg.ip,
                    "raw_output": proc.stdout.strip(),
                    "error": f"JSON parse error: {e}",
                }
        return {
            "reachable": False,
            "host_id": host_cfg.host_id,
            "host_ip": host_cfg.ip,
            "error": proc.stderr.strip() or "Hôte distant inaccessible",
            "return_code": proc.returncode,
        }

    def verify_port_exposure_security(self, host_id: Optional[str] = None, timeout: float = 3.0) -> Dict[str, Any]:
        """Vérifie formellement que les ports TCP Docker (2375, 2376) ne sont pas exposés sur Internet (CA3).
        
        Distingue formellement :
        - Un hôte injoignable (échec sur port SSH 22) -> verdict INCONCLUANT (ne valide jamais all_secure par erreur)
        - Un port ouvert -> VULNÉRABLE (all_secure = False)
        - Un port fermé -> SÉCURISÉ (CLOSED / TCP RST reçu)
        - Un port filtré -> SÉCURISÉ (FILTERED / Timeout avec hôte joignable par ailleurs)
        """
        host_cfg = self.get_host_config(host_id)
        
        # 1. Contrôle préalable de la joignabilité de l'hôte via son port de référence SSH (22)
        host_reachable = False
        s_ping = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s_ping.settimeout(timeout)
        try:
            res_ping = s_ping.connect_ex((host_cfg.ip, host_cfg.ssh_port))
            if res_ping == 0:
                host_reachable = True
            else:
                _log.warning("Hôte %s (%s) non joignable sur port SSH %d (errno=%d)", host_cfg.host_id, host_cfg.ip, host_cfg.ssh_port, res_ping)
        except Exception as e:
            _log.warning("Erreur contrôle joignabilité hôte %s : %s", host_cfg.host_id, e)
        finally:
            s_ping.close()

        if not host_reachable:
            return {
                "host_id": host_cfg.host_id,
                "host_ip": host_cfg.ip,
                "host_reachable": False,
                "all_secure": False,
                "verdict_global": "INCONCLUANT (Hôte injoignable sur le réseau / Port SSH 22 ne répond pas)",
                "ports_checked": {},
                "rule": "Une panne réseau ne doit jamais être interprétée comme une preuve de sécurité.",
            }

        ports_to_check = [2375, 2376]
        exposure_results = {}
        all_closed = True

        for p in ports_to_check:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(timeout)
            try:
                res = s.connect_ex((host_cfg.ip, p))
                if res == 0:
                    exposure_results[p] = {
                        "open": True,
                        "state": "OPEN",
                        "errno": 0,
                        "verdict": "VULNÉRABLE (Port ouvert et exposé publiquement)",
                    }
                    all_closed = False
                elif res in (errno.ECONNREFUSED, 61, 111):
                    exposure_results[p] = {
                        "open": False,
                        "state": "CLOSED",
                        "errno": res,
                        "verdict": "SÉCURISÉ (Port fermé / Rejet TCP RST reçu)",
                    }
                elif res in (errno.ETIMEDOUT, 60, 110):
                    exposure_results[p] = {
                        "open": False,
                        "state": "FILTERED",
                        "errno": res,
                        "verdict": "SÉCURISÉ (Filtré par pare-feu réseau / Drop)",
                    }
                else:
                    exposure_results[p] = {
                        "open": False,
                        "state": f"ERRNO_{res}",
                        "errno": res,
                        "verdict": f"SÉCURISÉ (Code TCP: {os.strerror(res) if res in errno.errorcode else res})",
                    }
            except socket.timeout:
                exposure_results[p] = {
                    "open": False,
                    "state": "FILTERED",
                    "errno": errno.ETIMEDOUT,
                    "verdict": "SÉCURISÉ (Filtré par pare-feu / Timeout sans réponse)",
                }
            except Exception as e:
                exposure_results[p] = {
                    "open": False,
                    "state": "ERROR",
                    "verdict": f"NON CONCLUANT (Exception socket: {e})",
                }
                all_closed = False
            finally:
                s.close()

        return {
            "host_id": host_cfg.host_id,
            "host_ip": host_cfg.ip,
            "host_reachable": True,
            "all_secure": all_closed,
            "ports_checked": exposure_results,
            "rule": "Les ports 2375 et 2376 ne doivent jamais répondre publiquement sans mTLS ni être scannables.",
        }

    def allocate_tenant_port(self, tenant_slug: str, host_id: Optional[str] = None) -> int:
        """Alloue de manière déterministe et étanche un port applicatif sur l'hôte cible (CA2)."""
        host_cfg = self.get_host_config(host_id)
        if tenant_slug in self._allocated_ports:
            return self._allocated_ports[tenant_slug]

        # Allocation d'un port disponible dans la plage configurée
        assigned_port = self._next_port
        while assigned_port in self._allocated_ports.values():
            assigned_port += 1
            if assigned_port > host_cfg.port_range_end:
                raise RuntimeError(f"Plage de ports épuisée sur l'hôte {host_cfg.host_id} (max {host_cfg.port_range_end})")

        self._allocated_ports[tenant_slug] = assigned_port
        self._next_port = assigned_port + 1
        return assigned_port

    def register_tenant_route(
        self,
        tenant_slug: str,
        host_id: Optional[str] = None,
        port: Optional[int] = None,
        status: str = "active",
    ) -> Dict[str, Any]:
        """Enregistre ou met à jour la route réseau d'un espace client dans la table d'acheminement Ingress (CA2)."""
        host_cfg = self.get_host_config(host_id)
        effective_port = port or self.allocate_tenant_port(tenant_slug, host_cfg.host_id)
        route_entry = {
            "tenant_slug": tenant_slug,
            "host_id": host_cfg.host_id,
            "host_ip": host_cfg.ip,
            "port": effective_port,
            "status": status,
            "target_url": f"http://{host_cfg.ip}:{effective_port}",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self._routing_table[tenant_slug] = route_entry
        return route_entry

    def unregister_tenant_route(self, tenant_slug: str):
        """Supprime une route client de la table d'acheminement."""
        self._routing_table.pop(tenant_slug, None)

    def get_routing_table(self) -> Dict[str, Dict[str, Any]]:
        """Retourne une copie brute de la table de routage multi-hôtes en mémoire (CA2)."""
        return dict(self._routing_table)

    def resolve_tenant_route(self, tenant_slug: str) -> Optional[Dict[str, Any]]:
        """Résout la destination réseau d'un slug dans la table de routage Ingress (CA2)."""
        return self._routing_table.get(tenant_slug)

    def authorize_and_resolve_slug(self, tenant_slug: str) -> Dict[str, Any]:
        """Associe chaque espace à un slug et rend une décision d'autorisation explicite (CA2 amendé).
        
        Conforme à l'exigence CA2 :
        - La table de routage résout un slug vers son hôte et son port.
        - Toute requête dont le slug ne correspond pas à une route active est rejetée par une décision explicite.
        """
        route = self.resolve_tenant_route(tenant_slug)
        if not route:
            return {
                "tenant_slug": tenant_slug,
                "allowed": False,
                "decision": "REJECT",
                "status": "REJECTED_UNPROVISIONED",
                "error_code": "ERR_TENANT_ROUTE_NOT_FOUND",
                "reason": f"Aucune route configurée pour le slug '{tenant_slug}' : espace non provisionné sur la flotte.",
                "routed_target": None,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        if route.get("status") not in ("active", "ready"):
            return {
                "tenant_slug": tenant_slug,
                "allowed": False,
                "decision": "REJECT",
                "status": "REJECTED_OFFLINE",
                "error_code": "ERR_TENANT_CONTAINER_OFFLINE",
                "reason": f"L'espace '{tenant_slug}' existe mais est inactif ({route.get('status')}) : wake-on-demand requis.",
                "routed_target": None,
                "wake_endpoint": f"/api/olympe/tenants/wake/{tenant_slug}",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        return {
            "tenant_slug": tenant_slug,
            "allowed": True,
            "decision": "ACCEPT",
            "status": "AUTHORIZED",
            "host_id": route["host_id"],
            "host_ip": route["host_ip"],
            "port": route["port"],
            "target_url": route["target_url"],
            "reason": f"Route active trouvée : espace client autorisé et résolu vers {route['host_id']} ({route['host_ip']}:{route['port']}).",
            "routed_target": route["target_url"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def route_client_request(
        self,
        tenant_slug: str,
        path: str = "/api/client/chat/stream",
        auth_jwt_slug: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Simule la traversée d'acheminement Ingress L7 vers l'espace concerné avec contrôle d'étanchéité (CA2)."""
        # 1. Vérification d'étanchéité d'identité (JWT guard)
        if auth_jwt_slug and auth_jwt_slug != tenant_slug:
            return {
                "allowed": False,
                "status_code": 403,
                "error": "ERR_CROSS_TENANT_ACCESS_FORBIDDEN",
                "message": f"Accès interdit : le jeton JWT pour '{auth_jwt_slug}' ne correspond pas à l'espace '{tenant_slug}'.",
                "routed_target": None,
            }

        # 2. Résolution dans la table de routage
        route = self.resolve_tenant_route(tenant_slug)
        if not route or route.get("status") not in ("active", "ready"):
            return {
                "allowed": False,
                "status_code": 503,
                "error": "ERR_TENANT_CONTAINER_OFFLINE",
                "message": f"L'environnement de l'espace '{tenant_slug}' est actuellement en veille ou non raccordé.",
                "wake_endpoint": f"/api/olympe/tenants/wake/{tenant_slug}",
                "routed_target": None,
            }

        # 3. Acheminement réussi vers le conteneur du client sur l'Hôte 2
        clean_path = path if path.startswith("/") else f"/{path}"
        full_dest = f"{route['target_url']}{clean_path}"
        return {
            "allowed": True,
            "status_code": 200,
            "tenant_slug": tenant_slug,
            "host_id": route["host_id"],
            "host_ip": route["host_ip"],
            "port": route["port"],
            "routed_target": full_dest,
            "message": f"Requête acheminée avec succès vers l'espace client sur {route['host_id']}:{route['port']}.",
        }

    def audit_zero_client_data_transit(
        self,
        olympe_logs: List[str],
        management_host_dirs: List[Path],
    ) -> Dict[str, Any]:
        """Vérifie formellement qu'aucune donnée propre à un client ne réside sur le plan de gestion (CA4)."""
        suspicious_data_patterns = [
            r"SELECT.*FROM.*state\.db",
            r"balance_agee",
            r"reconciliation_.*\.py",
            r"client_secret_erp",
            r"SOUL\.md content",
            r"conversation_history_dump",
        ]
        log_findings = []
        for line in olympe_logs:
            for pat in suspicious_data_patterns:
                if re.search(pat, line, re.IGNORECASE):
                    log_findings.append({"pattern": pat, "matched_line": line.strip()})

        # Vérification des montages / répertoires sur l'Hôte 1
        storage_findings = []
        for p in management_host_dirs:
            if p.exists():
                # Vérifier si des fichiers de données client (state.db) s'y trouvent
                for client_db in p.glob("**/state.db"):
                    storage_findings.append(str(client_db))

        no_data_leak = (len(log_findings) == 0 and len(storage_findings) == 0)
        return {
            "no_data_leak": no_data_leak,
            "log_findings_count": len(log_findings),
            "log_findings": log_findings,
            "storage_findings_count": len(storage_findings),
            "storage_findings": storage_findings,
            "verdict": "CONFORME : Aucune donnée propre aux clients n'est détectée sur le plan de gestion" if no_data_leak else "NON-CONFORME",
        }

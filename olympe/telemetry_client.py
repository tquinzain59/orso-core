"""Client de Télémétrie et Supervision pour Olympe Ops.

Interroge l'API de Télémétrie (port 9120, olympe_supervision_agent) et enrichit
les données avec l'état réel des conteneurs Docker et le rattachement aux clients (tenants).
"""

import os
import json
import logging
import urllib.request
import urllib.error
import socket
import http.client
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

_log = logging.getLogger("orso.olympe.telemetry")

TELEMETRY_API_URL = os.environ.get("TELEMETRY_API_URL", "http://olympe_supervision_agent:9120")
FALLBACK_API_URL = "http://localhost:9120"
DOCKER_SOCK_PATH = "/var/run/docker.sock"


class UnixHTTPConnection(http.client.HTTPConnection):
    """Connexion HTTP standard via socket Unix Docker."""
    def __init__(self, path: str = DOCKER_SOCK_PATH):
        super().__init__("localhost")
        self.path = path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(self.path)


class TelemetryClient:
    """Client d'accès à l'API de Télémétrie avec enrichissement Docker & Tenants."""

    def __init__(self, base_url: Optional[str] = None):
        self.base_url = (base_url or TELEMETRY_API_URL).rstrip("/")
        self.fallback_url = FALLBACK_API_URL.rstrip("/")

    def _fetch_api(self, endpoint: str, timeout: float = 3.0) -> Optional[Any]:
        """Tente d'appeler l'API de télémétrie sur l'URL principale puis sur le fallback."""
        urls_to_try = [f"{self.base_url}{endpoint}"]
        if self.fallback_url != self.base_url:
            urls_to_try.append(f"{self.fallback_url}{endpoint}")

        for url in urls_to_try:
            try:
                req = urllib.request.Request(
                    url,
                    headers={"Accept": "application/json", "User-Agent": "OrsoOps/1.0"},
                )
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    if resp.status == 200:
                        return json.loads(resp.read().decode("utf-8"))
            except Exception as e:
                _log.debug("Impossible de contacter %s: %s", url, e)
        return None

    def _get_docker_live_vitals(self) -> Dict[str, Dict[str, Any]]:
        """Interroge le socket Docker pour extraire les métriques CPU/RAM par conteneur."""
        if not os.path.exists(DOCKER_SOCK_PATH):
            return {}

        vitals_by_name = {}
        try:
            conn = UnixHTTPConnection(DOCKER_SOCK_PATH)
            conn.request("GET", "/containers/json?all=true")
            res = conn.getresponse()
            if res.status != 200:
                return {}

            containers = json.loads(res.read().decode("utf-8"))
            for c in containers:
                raw_names = c.get("Names", [])
                if not raw_names:
                    continue
                name = raw_names[0].lstrip("/")
                cid = c.get("Id", "")
                state = c.get("State", "unknown")
                status_str = c.get("Status", "")

                usage_mb = 0.0
                limit_mb = 0.0
                mem_percent = 0.0
                cpu_percent = 0.0

                if state == "running":
                    try:
                        conn_stats = UnixHTTPConnection(DOCKER_SOCK_PATH)
                        conn_stats.request("GET", f"/containers/{cid}/stats?stream=false")
                        stats_resp = conn_stats.getresponse()
                        if stats_resp.status == 200:
                            stats = json.loads(stats_resp.read().decode("utf-8"))
                            mem = stats.get("memory_stats", {})
                            usage_bytes = mem.get("usage", 0)
                            limit_bytes = mem.get("limit", 0)
                            usage_mb = usage_bytes / (1024 * 1024)
                            limit_mb = limit_bytes / (1024 * 1024)
                            if limit_bytes > 0:
                                mem_percent = (usage_bytes / limit_bytes) * 100.0

                            # Calcul CPU delta
                            cpu_stats = stats.get("cpu_stats", {})
                            precpu_stats = stats.get("precpu_stats", {})
                            cpu_delta = cpu_stats.get("cpu_usage", {}).get("total_usage", 0) - precpu_stats.get("cpu_usage", {}).get("total_usage", 0)
                            sys_delta = cpu_stats.get("system_cpu_usage", 0) - precpu_stats.get("system_cpu_usage", 0)
                            online_cpus = cpu_stats.get("online_cpus", 1)
                            if sys_delta > 0 and cpu_delta > 0:
                                cpu_percent = (cpu_delta / sys_delta) * online_cpus * 100.0
                    except Exception:
                        pass

                labels = c.get("Labels", {}) or {}
                is_managed = (
                    labels.get("com.orso.managed") == "true"
                    or name.startswith("orso_")
                    or "olympe" in name
                )

                vitals_by_name[name] = {
                    "container_id": cid[:12],
                    "state": state,
                    "status_str": status_str,
                    "cpu_percent": round(cpu_percent, 2),
                    "memory_usage_mb": round(usage_mb, 1),
                    "memory_limit_mb": round(limit_mb, 1),
                    "memory_percent": round(mem_percent, 1),
                    "labels": labels,
                    "is_managed": is_managed,
                    "tenant_id": labels.get("com.orso.tenant_id"),
                    "tenant_slug": labels.get("com.orso.tenant_slug"),
                    "role": labels.get("com.orso.role"),
                }
        except Exception as e:
            _log.debug("Erreur lors de la lecture du socket Docker: %s", e)

        return vitals_by_name

    def get_summary(self) -> Dict[str, Any]:
        """Retourne les métriques de télémétrie consolidées."""
        raw = self._fetch_api("/api/telemetry/summary")
        if raw and "summary" in raw:
            return raw["summary"]
        if raw:
            return raw

        # Télémétrie indisponible / hors ligne : métriques réelles à zéro
        return {
            "agents_count": 0,
            "snapshots_count": 0,
            "total_tokens": 0,
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "total_api_calls": 0,
            "total_cost_usd": 0.0,
            "last_snapshot_at": None,
            "agents_registered": 0,
            "alerts_active": 0,
            "connected": False,
            "status": "unavailable",
            "simulated": False,
        }

    def get_environments(self, tenants: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Retourne la liste des environnements enrichis avec Docker vitals et tenants associés."""
        raw_latest = self._fetch_api("/api/telemetry/latest")
        raw_agents = raw_latest.get("agents", []) if raw_latest else []

        # Filtrer tout résidu de l'ancien conteneur de test 'Recouvrement' (agent 3 / recouvrement_default)
        if raw_agents:
            raw_agents = [
                ag for ag in raw_agents
                if ag.get("agent_id") != 3
                and ag.get("id") != 3
                and ag.get("container_id") != "recouvrement_default"
                and ag.get("display_name", "").strip().lower() != "recouvrement"
            ]

        docker_vitals = self._get_docker_live_vitals()

        # Dictionnaire des tenants par slug et par id pour recherche rapide
        tenants_by_slug = {t.get("slug"): t for t in tenants if t.get("slug")}
        
        # Le client provisionné par défaut (Financia Solutions)
        default_provisioned_tenant = next((t for t in tenants if t.get("slug") == "financia-solutions"), None)

        # Si l'API télémétrie n'est pas joignable mais que des conteneurs gérés tournent réellement sur la machine
        if not raw_agents and docker_vitals:
            for idx, (dname, dv) in enumerate(docker_vitals.items(), start=1):
                if dv.get("is_managed"):
                    raw_agents.append({
                        "agent_id": idx,
                        "display_name": dname,
                        "module": dv.get("role") or ("supervision" if "olympe" in dname else "agent"),
                        "dashboard_url": "",
                        "last_seen_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S") if dv.get("state") == "running" else None,
                        "total_tokens": 0,
                        "input_tokens": 0,
                        "output_tokens": 0,
                        "api_calls": 0,
                        "cost_usd": 0.0,
                        "status": "active" if dv.get("state") == "running" else "stopped",
                        "error_count": 0,
                        "container_id": dname,
                        "server_ip": "127.0.0.1",
                    })

        enriched_environments = []
        for ag in raw_agents:
            agent_id = ag.get("agent_id") or ag.get("id")
            display_name = ag.get("display_name", "Agent")
            module = ag.get("module", "générique")
            container_id = ag.get("container_id", "")
            server_ip = ag.get("server_ip") or os.environ.get("ORSO_HOST_IP", "127.0.0.1")
            status = ag.get("status", "active")
            
            # Recherche du tenant associé
            associated_tenant = None
            if module == "supervision" or "olympe" in display_name.lower():
                associated_tenant = {
                    "id": "system_olympe",
                    "name": "Plateforme ORSO (Superviseur Olympe)",
                    "slug": "system",
                    "sector": "Infrastructure & IA",
                    "is_system": True,
                    "status": "system",
                }
            elif "recouvrement" in module or "recouv" in container_id or "prod-fr-002" in display_name.lower():
                # Rattaché au tenant de recouvrement actif (Financia Solutions)
                if default_provisioned_tenant:
                    associated_tenant = {
                        "id": default_provisioned_tenant.get("id"),
                        "name": default_provisioned_tenant.get("name"),
                        "slug": default_provisioned_tenant.get("slug"),
                        "sector": default_provisioned_tenant.get("sector", "Services Financiers"),
                        "is_system": False,
                        "status": default_provisioned_tenant.get("status", "active"),
                        "tier_label": default_provisioned_tenant.get("subscription", {}).get("tier_label", "Starter (1 agent)"),
                    }
                else:
                    associated_tenant = None
            else:
                # Tentative de matching par slug dans le nom de conteneur
                for slug, t in tenants_by_slug.items():
                    if slug in container_id or slug in display_name.lower():
                        associated_tenant = {
                            "id": t.get("id"),
                            "name": t.get("name"),
                            "slug": t.get("slug"),
                            "sector": t.get("sector"),
                            "is_system": False,
                            "status": t.get("status"),
                        }
                        break

            # Signes vitaux Docker réels si disponibles (priorité aux labels Docker standardisés)
            matched_vitals = None
            for dname, dv in docker_vitals.items():
                # 1. Correspondance prioritaire par label tenant_slug ou tenant_id
                v_slug = dv.get("tenant_slug")
                if v_slug and (v_slug in container_id or (associated_tenant and associated_tenant.get("slug") == v_slug)):
                    matched_vitals = dv
                    break
                # 2. Correspondance par rôle supervision / olympe
                if module == "supervision" and (dv.get("role") == "supervisor" or "olympe" in dname):
                    matched_vitals = dv
                    break
                # 3. Correspondance par nom de conteneur
                if container_id and (container_id == dname or container_id in dname or dname in container_id):
                    matched_vitals = dv
                    break
                if "backend" in dname and "recouv" in module:
                    matched_vitals = dv
                    break

            # Si le conteneur a un label tenant_slug explicite et qu'aucun tenant n'a été rattaché
            if not associated_tenant and matched_vitals and matched_vitals.get("tenant_slug"):
                v_slug = matched_vitals["tenant_slug"]
                if v_slug in tenants_by_slug:
                    t = tenants_by_slug[v_slug]
                    associated_tenant = {
                        "id": t.get("id"),
                        "name": t.get("name"),
                        "slug": t.get("slug"),
                        "sector": t.get("sector"),
                        "is_system": False,
                        "status": t.get("status"),
                    }

            vitals = {
                "cpu_percent": matched_vitals.get("cpu_percent", 0.0) if matched_vitals else 0.0,
                "memory_usage_mb": matched_vitals.get("memory_usage_mb", 0.0) if matched_vitals else 0.0,
                "memory_limit_mb": matched_vitals.get("memory_limit_mb", 0.0) if matched_vitals else 0.0,
                "memory_percent": matched_vitals.get("memory_percent", 0.0) if matched_vitals else 0.0,
                "docker_status": matched_vitals.get("status_str", "Inconnu") if matched_vitals else "Indisponible",
            }

            env_item = {
                "agent_id": agent_id,
                "display_name": display_name,
                "module": module,
                "container_id": container_id,
                "server_ip": server_ip,
                "dashboard_url": ag.get("dashboard_url", ""),
                "status": status,
                "total_tokens": ag.get("total_tokens", 0),
                "input_tokens": ag.get("input_tokens", 0),
                "output_tokens": ag.get("output_tokens", 0),
                "api_calls": ag.get("api_calls", 0),
                "cost_usd": ag.get("cost_usd", 0.0),
                "error_count": ag.get("error_count", 0),
                "last_seen_at": ag.get("last_seen_at") or ag.get("snapshot_at"),
                "vitals": vitals,
                "tenant": associated_tenant,
            }
            enriched_environments.append(env_item)

        return enriched_environments

    def get_history(self, agent_id: int, limit: int = 25) -> Dict[str, Any]:
        """Historique des snapshots pour un agent donné."""
        res = self._fetch_api(f"/api/telemetry/history/{agent_id}?limit={limit}")
        if res:
            return res

        # Télémétrie indisponible / déconnectée : aucun snapshot fictif
        return {
            "agent_id": agent_id,
            "agent_name": f"Agent #{agent_id}",
            "snapshots": [],
            "count": 0,
            "connected": False,
        }

    def get_alerts(self, resolved: bool = False, agent_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """Récupère les alertes actives depuis l'API de Télémétrie."""
        url = f"/api/alerts?resolved={str(resolved).lower()}"
        if agent_id:
            url += f"&agent_id={agent_id}"

        res = self._fetch_api(url)
        if res and "alerts" in res:
            return res["alerts"]
        if isinstance(res, list):
            return res

        # Fallback simulation propre : aucune alerte anormale par défaut
        return []


# Instance singleton pour import facile
telemetry_client = TelemetryClient()

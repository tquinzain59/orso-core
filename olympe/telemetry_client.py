"""Client de Télémétrie et Supervision pour Olympe Ops.

Interroge l'API de Télémétrie (port 9120, olympe_supervision_agent) et enrichit
les données avec l'état réel des conteneurs Docker et le rattachement aux clients (tenants).

Règle inviolable (KAN-43 / KAN-73) : ce module ne fabrique aucune valeur. Quand la
collecte est indisponible, la réponse porte ``connected: False`` et ``status: "unknown"``
avec une erreur lisible ; une mesure non obtenue vaut ``None``, jamais ``0`` ni un état sain.
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

STATUS_UNKNOWN = "unknown"
ERROR_TELEMETRY_UNAVAILABLE = "telemetry_unavailable"
UNAVAILABLE_MESSAGE = "Collecte de télémétrie indisponible : état inconnu."


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
        # Horodatage (jamais une valeur) de la dernière réponse valide de la collecte.
        self.last_valid_at: Optional[str] = None

    def _fetch_api(self, endpoint: str, timeout: float = 3.0) -> Optional[Any]:
        """Tente d'appeler l'API de télémétrie sur l'URL principale puis sur l'URL locale de secours.

        Retourne None si aucune des deux ne répond : l'appelant doit alors déclarer l'état inconnu.
        """
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
                        payload = json.loads(resp.read().decode("utf-8"))
                        self.last_valid_at = datetime.now(timezone.utc).isoformat()
                        return payload
            except Exception as e:
                _log.debug("Impossible de contacter %s: %s", url, e)
        return None

    def _unavailable(self) -> Dict[str, Any]:
        """Enveloppe d'indisponibilité : état inconnu, erreur lisible, dernière mesure valide."""
        return {
            "connected": False,
            "status": STATUS_UNKNOWN,
            "error": ERROR_TELEMETRY_UNAVAILABLE,
            "message": UNAVAILABLE_MESSAGE,
            "last_valid_at": self.last_valid_at,
        }

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

                # None = non mesuré. Une mesure qui échoue ne doit jamais se lire comme 0 %.
                usage_mb: Optional[float] = None
                limit_mb: Optional[float] = None
                mem_percent: Optional[float] = None
                cpu_percent: Optional[float] = None

                if state == "running":
                    try:
                        conn_stats = UnixHTTPConnection(DOCKER_SOCK_PATH)
                        conn_stats.request("GET", f"/containers/{cid}/stats?stream=false")
                        stats_resp = conn_stats.getresponse()
                        if stats_resp.status == 200:
                            stats = json.loads(stats_resp.read().decode("utf-8"))
                            mem = stats.get("memory_stats", {})
                            if "usage" in mem:
                                usage_bytes = mem["usage"]
                                usage_mb = usage_bytes / (1024 * 1024)
                                limit_bytes = mem.get("limit", 0)
                                if limit_bytes > 0:
                                    limit_mb = limit_bytes / (1024 * 1024)
                                    mem_percent = (usage_bytes / limit_bytes) * 100.0

                            # Calcul CPU delta
                            cpu_stats = stats.get("cpu_stats", {})
                            precpu_stats = stats.get("precpu_stats", {})
                            cpu_delta = cpu_stats.get("cpu_usage", {}).get("total_usage", 0) - precpu_stats.get("cpu_usage", {}).get("total_usage", 0)
                            sys_delta = cpu_stats.get("system_cpu_usage", 0) - precpu_stats.get("system_cpu_usage", 0)
                            online_cpus = cpu_stats.get("online_cpus", 1)
                            if sys_delta > 0:
                                cpu_percent = (max(cpu_delta, 0) / sys_delta) * online_cpus * 100.0
                    except Exception as e:
                        _log.debug("Statistiques Docker indisponibles pour %s: %s", name, e)

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
                    "cpu_percent": None if cpu_percent is None else round(cpu_percent, 2),
                    "memory_usage_mb": None if usage_mb is None else round(usage_mb, 1),
                    "memory_limit_mb": None if limit_mb is None else round(limit_mb, 1),
                    "memory_percent": None if mem_percent is None else round(mem_percent, 1),
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
        """Retourne les métriques de télémétrie consolidées, ou l'enveloppe d'indisponibilité."""
        raw = self._fetch_api("/api/telemetry/summary")
        if raw and "summary" in raw:
            return raw["summary"]
        if raw:
            return raw
        return self._unavailable()

    def get_environments(self, tenants: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Retourne les environnements enrichis (Docker + tenants) sous forme d'enveloppe.

        Collecte absente : ``environments`` vaut None (inconnu), pas une flotte vide.
        Les conteneurs Docker ne sont jamais convertis en agents : seul un agent
        rapporté par la collecte apparaît.
        """
        raw_latest = self._fetch_api("/api/telemetry/latest")
        if not isinstance(raw_latest, dict) or not isinstance(raw_latest.get("agents"), list):
            return {**self._unavailable(), "environments": None, "count": None}
        raw_agents = raw_latest["agents"]

        # Filtrer tout résidu de l'ancien conteneur de test 'Recouvrement' (agent 3 / recouvrement_default)
        raw_agents = [
            ag for ag in raw_agents
            if ag.get("agent_id") != 3
            and ag.get("id") != 3
            and ag.get("container_id") != "recouvrement_default"
            and (ag.get("display_name") or "").strip().lower() != "recouvrement"
        ]

        docker_vitals = self._get_docker_live_vitals()

        # Dictionnaire des tenants par slug et par id pour recherche rapide
        tenants_by_slug = {t.get("slug"): t for t in tenants if t.get("slug")}

        # Le client provisionné par défaut (Financia Solutions)
        default_provisioned_tenant = next((t for t in tenants if t.get("slug") == "financia-solutions"), None)

        enriched_environments = []
        for ag in raw_agents:
            agent_id = ag.get("agent_id") or ag.get("id")
            display_name = ag.get("display_name")
            module = ag.get("module")
            container_id = ag.get("container_id")
            # Formes textuelles sûres pour les recherches ; la valeur rapportée reste None si absente.
            name_l = (display_name or "").lower()
            module_s = module or ""
            container_s = container_id or ""

            # Recherche du tenant associé
            associated_tenant = None
            if module == "supervision" or "olympe" in name_l:
                associated_tenant = {
                    "id": "system_olympe",
                    "name": "Plateforme ORSO (Superviseur Olympe)",
                    "slug": "system",
                    "sector": "Infrastructure & IA",
                    "is_system": True,
                    "status": "system",
                }
            elif "recouvrement" in module_s or "recouv" in container_s:
                # Rattaché au tenant de recouvrement actif (Financia Solutions)
                if default_provisioned_tenant:
                    associated_tenant = {
                        "id": default_provisioned_tenant.get("id"),
                        "name": default_provisioned_tenant.get("name"),
                        "slug": default_provisioned_tenant.get("slug"),
                        "sector": default_provisioned_tenant.get("sector"),
                        "is_system": False,
                        "status": default_provisioned_tenant.get("status"),
                        "tier_label": (default_provisioned_tenant.get("subscription") or {}).get("tier_label"),
                    }
            else:
                # Tentative de matching par slug dans le nom de conteneur
                for slug, t in tenants_by_slug.items():
                    if slug in container_s or slug in name_l:
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
                if v_slug and (v_slug in container_s or (associated_tenant and associated_tenant.get("slug") == v_slug)):
                    matched_vitals = dv
                    break
                # 2. Correspondance par rôle supervision / olympe
                if module == "supervision" and (dv.get("role") == "supervisor" or "olympe" in dname):
                    matched_vitals = dv
                    break
                # 3. Correspondance par nom de conteneur
                if container_s and (container_s == dname or container_s in dname or dname in container_s):
                    matched_vitals = dv
                    break
                if "backend" in dname and "recouv" in module_s:
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

            # Aucun conteneur apparié = signes vitaux inconnus (None), jamais 0 ni « sain ».
            vitals = {
                "cpu_percent": matched_vitals.get("cpu_percent") if matched_vitals else None,
                "memory_usage_mb": matched_vitals.get("memory_usage_mb") if matched_vitals else None,
                "memory_limit_mb": matched_vitals.get("memory_limit_mb") if matched_vitals else None,
                "memory_percent": matched_vitals.get("memory_percent") if matched_vitals else None,
                "docker_status": matched_vitals.get("status_str") if matched_vitals else STATUS_UNKNOWN,
            }

            env_item = {
                "agent_id": agent_id,
                "display_name": display_name,
                "module": module,
                "container_id": container_id,
                "server_ip": ag.get("server_ip"),
                "dashboard_url": ag.get("dashboard_url"),
                "status": ag.get("status") or STATUS_UNKNOWN,
                "total_tokens": ag.get("total_tokens"),
                "input_tokens": ag.get("input_tokens"),
                "output_tokens": ag.get("output_tokens"),
                "api_calls": ag.get("api_calls"),
                "cost_usd": ag.get("cost_usd"),
                "error_count": ag.get("error_count"),
                "last_seen_at": ag.get("last_seen_at") or ag.get("snapshot_at"),
                "vitals": vitals,
                "tenant": associated_tenant,
            }
            enriched_environments.append(env_item)

        return {
            "connected": True,
            "environments": enriched_environments,
            "count": len(enriched_environments),
            "last_valid_at": self.last_valid_at,
        }

    def get_history(self, agent_id: int, limit: int = 25) -> Dict[str, Any]:
        """Historique des snapshots pour un agent donné, ou l'enveloppe d'indisponibilité."""
        res = self._fetch_api(f"/api/telemetry/history/{agent_id}?limit={limit}")
        if res:
            return res
        return {
            **self._unavailable(),
            "agent_id": agent_id,
            "agent_name": None,
            "snapshots": None,
            "count": None,
        }

    def get_alerts(self, resolved: bool = False, agent_id: Optional[int] = None) -> Dict[str, Any]:
        """Alertes depuis l'API de Télémétrie.

        Collecte absente ou réponse illisible : ``alerts`` vaut None (inconnu). Une liste
        vide n'est rendue que si la collecte a répondu et n'a signalé aucune alerte.
        """
        url = f"/api/alerts?resolved={str(resolved).lower()}"
        if agent_id:
            url += f"&agent_id={agent_id}"

        res = self._fetch_api(url)
        if isinstance(res, dict) and isinstance(res.get("alerts"), list):
            alerts = res["alerts"]
        elif isinstance(res, list):
            alerts = res
        else:
            return {**self._unavailable(), "alerts": None, "count": None}
        return {
            "connected": True,
            "alerts": alerts,
            "count": len(alerts),
            "last_valid_at": self.last_valid_at,
        }


# Instance singleton pour import facile
telemetry_client = TelemetryClient()

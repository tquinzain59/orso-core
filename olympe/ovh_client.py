"""Connecteur et Gestionnaire d'Infrastructure OVHcloud pour le Superviseur Olympe.

Gère l'authentification sécurisée avec l'API REST OVH (signature HMAC-SHA1 officielle),
l'évaluation du dimensionnement (RAM, vCPU, stockage) selon la charge des conteneurs,
et le provisionnement d'instances Public Cloud / VPS.
"""

import hashlib
import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

_log = logging.getLogger("orso.olympe.ovh")

# Grille des gabarits OVH Public Cloud couramment utilisés pour Orso Agents
OVH_FLAVORS = {
    "d2-2": {"name": "d2-2", "vcpus": 1, "ram_mb": 2048, "disk_gb": 20, "price_monthly_eur": 5.00, "capacity_agents": 2},
    "d2-4": {"name": "d2-4", "vcpus": 2, "ram_mb": 4096, "disk_gb": 40, "price_monthly_eur": 12.00, "capacity_agents": 4},
    "b2-7": {"name": "b2-7", "vcpus": 2, "ram_mb": 7168, "disk_gb": 50, "price_monthly_eur": 22.00, "capacity_agents": 8},
    "b2-15": {"name": "b2-15", "vcpus": 4, "ram_mb": 15360, "disk_gb": 100, "price_monthly_eur": 45.00, "capacity_agents": 16},
    "b2-30": {"name": "b2-30", "vcpus": 8, "ram_mb": 30720, "disk_gb": 200, "price_monthly_eur": 90.00, "capacity_agents": 32},
}

# Endpoints officiels OVH
OVH_ENDPOINTS = {
    "ovh-eu": "https://eu.api.ovh.com/1.0",
    "ovh-ca": "https://ca.api.ovh.com/1.0",
    "ovh-us": "https://api.us.ovhcloud.com/1.0",
}


class OVHClient:
    """Client API REST souverain pour OVHcloud avec signature cryptographique native."""

    def __init__(
        self,
        application_key: Optional[str] = None,
        application_secret: Optional[str] = None,
        consumer_key: Optional[str] = None,
        project_id: Optional[str] = None,
        endpoint_name: str = "ovh-eu",
    ):
        self.application_key = application_key or os.environ.get("OVH_APPLICATION_KEY", "")
        self.application_secret = application_secret or os.environ.get("OVH_APPLICATION_SECRET", "")
        self.consumer_key = consumer_key or os.environ.get("OVH_CONSUMER_KEY", "")
        self.project_id = project_id or os.environ.get("OVH_CLOUD_PROJECT_ID", "")
        self.endpoint_url = OVH_ENDPOINTS.get(
            endpoint_name or os.environ.get("OVH_ENDPOINT", "ovh-eu"),
            OVH_ENDPOINTS["ovh-eu"],
        )
        self._time_delta: Optional[int] = None

    def is_configured(self) -> bool:
        """Vérifie si les clés d'API nécessaires sont présentes."""
        return bool(self.application_key and self.application_secret and self.consumer_key)

    def _get_server_time(self) -> int:
        """Récupère l'heure du serveur OVH pour éviter les décalages d'horloge."""
        if self._time_delta is not None:
            return int(time.time() + self._time_delta)

        try:
            req = urllib.request.Request(f"{self.endpoint_url}/auth/time")
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                server_time = int(resp.read().decode("utf-8"))
                self._time_delta = server_time - int(time.time())
                return server_time
        except Exception:
            return int(time.time())

    def _sign(self, method: str, query: str, body: str, timestamp: int) -> str:
        """Génère la signature officielle SHA1 requise par OVH API."""
        # Signature format: "$1$" + SHA1_HEX(AS + "+" + CK + "+" + METHOD + "+" + QUERY + "+" + BODY + "+" + TSTAMP)
        to_sign = f"{self.application_secret}+{self.consumer_key}+{method.upper()}+{query}+{body}+{timestamp}"
        digest = hashlib.sha1(to_sign.encode("utf-8")).hexdigest()
        return f"$1${digest}"

    def request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> Optional[Any]:
        """Exécute une requête signée auprès de l'API OVH."""
        if not self.is_configured():
            _log.info("Appel OVH ignoré : clés non configurées.")
            return None

        clean_path = path if path.startswith("/") else f"/{path}"
        url = f"{self.endpoint_url}{clean_path}"

        if params:
            query_string = urllib.parse.urlencode(params)
            url = f"{url}?{query_string}"

        body_str = json.dumps(data) if data else ""
        body_bytes = body_str.encode("utf-8") if body_str else None
        now_ts = self._get_server_time()
        signature = self._sign(method=method, query=url, body=body_str, timestamp=now_ts)

        headers = {
            "X-Ovh-Application": self.application_key,
            "X-Ovh-Consumer": self.consumer_key,
            "X-Ovh-Timestamp": str(now_ts),
            "X-Ovh-Signature": signature,
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "OrsoOlympeOps/1.0",
        }

        req = urllib.request.Request(url, data=body_bytes, headers=headers, method=method.upper())
        try:
            with urllib.request.urlopen(req, timeout=10.0) as resp:
                content = resp.read().decode("utf-8")
                return json.loads(content) if content else {}
        except urllib.error.HTTPError as e:
            err_msg = e.read().decode("utf-8", errors="replace")
            _log.error("Erreur HTTP OVH (%s %s) : %s - %s", method, path, e.code, err_msg)
            raise ValueError(f"Erreur API OVH ({e.code}): {err_msg}")
        except Exception as e:
            _log.error("Échec requête OVH (%s %s) : %s", method, path, e)
            raise

    # ── Dimensionnement & Aide à la décision ──────────────────────────────────

    def estimate_sizing(
        self,
        pending_tenants_count: int,
        pending_agents_count: int,
        existing_host_ip: str = "92.222.68.80",
    ) -> Dict[str, Any]:
        # ── Règle empirique issue des mesures réelles du POC KAN-59 (Document 27 / CA3 / CA4) ──
        # - Empreinte réelle au repos mesurée : ~95-105 Mo RAM par conteneur client (6-11 PIDs, <0.3% CPU)
        # - Empreinte réelle en charge active mesurée : ~93 à 139 Mo RAM par agent actif sous requêtes (10-18 PIDs, <10% CPU)
        # - Plafonds de quotas garantis alloués par palier tarifaire (marge de sécurité 2x à 4x) :
        #   * Starter (1 agent)   : 512 Mo RAM, 0.5 vCPU, 100 PIDs
        #   * Duo (2 agents)      : 1024 Mo RAM, 1.0 vCPU, 150 PIDs
        #   * Trio (3 agents)     : 1536 Mo RAM, 1.5 vCPU, 200 PIDs
        #   * Flotte (4 agents)   : 2048 Mo RAM, 2.0 vCPU, 250 PIDs
        # Modèle empirique fondé sur le pic réel observé (139 Mo par agent en charge + 100 Mo socle conteneur) :
        empirical_ram_mb = (pending_agents_count * 139) + (pending_tenants_count * 100)
        tier_quotas_ram_mb = (pending_agents_count * 512)

        # Modèle de dimensionnement conservateur (règle historique) pour compatibilité
        ram_mb_required = (pending_agents_count * 1024) + (pending_tenants_count * 512)
        vcpus_required = max(1, pending_agents_count // 2 + 1)

        # Choix du modèle de flavor le plus adapté
        recommended_flavor = "d2-4"
        for fid, f in sorted(OVH_FLAVORS.items(), key=lambda x: x[1]["ram_mb"]):
            if f["ram_mb"] >= ram_mb_required:
                recommended_flavor = fid
                break
        else:
            recommended_flavor = "b2-30"

        flavor_info = OVH_FLAVORS.get(recommended_flavor, OVH_FLAVORS["d2-4"])

        cloud_init_snippet = self.generate_cloud_init(
            server_name=f"orso-vps-node-{int(time.time())}",
            ssh_key_name="orso-ops-key",
        )

        docker_deploy_snippet = (
            "# 1. Déploiement Conteneur Client sécurisé sur le réseau orso_network avec quotas stricts (KAN-59)\n"
            f"docker run -d \\\n"
            f"  --name orso_client_{{tenant_slug}} \\\n"
            f"  --network orso_network \\\n"
            f"  --restart unless-stopped \\\n"
            f"  --label com.orso.managed=true \\\n"
            f"  --label com.orso.tenant_id={{tenant_id}} \\\n"
            f"  --label com.orso.tenant_slug={{tenant_slug}} \\\n"
            f"  --label com.orso.role=client_backend \\\n"
            f"  --cpus 0.5 \\\n"
            f"  --memory 512m \\\n"
            f"  --memory-swap 512m \\\n"
            f"  --pids-limit 100 \\\n"
            f"  -e ORSO_CLIENT_ID={{tenant_id}} \\\n"
            f"  -e ORSO_CLIENT_SLUG={{tenant_slug}} \\\n"
            f"  -e HERMES_HOME=/app/data/hermes_home \\\n"
            f"  -v /var/lib/orso/tenants/{{tenant_slug}}:/app/data \\\n"
            f"  orso-core-orso-backend:latest\n"
        )

        return {
            "is_ovh_api_configured": self.is_configured(),
            "pending_tenants": pending_tenants_count,
            "pending_agents": pending_agents_count,
            "ram_mb_estimated": ram_mb_required,
            "vcpus_estimated": vcpus_required,
            "empirical_measured_ram_mb": empirical_ram_mb,
            "tier_quotas_ram_mb": tier_quotas_ram_mb,
            "sizing_model": "empirical_measured_kan59",
            "recommended_flavor": recommended_flavor,
            "flavor_details": flavor_info,
            "can_fit_on_current_pool": ram_mb_required <= 4096,  # Si <= 4Go, peut tourner sur le VPS actuel
            "current_pool_ip": existing_host_ip,
            "cloud_init_snippet": cloud_init_snippet,
            "docker_deploy_snippet": docker_deploy_snippet,
            "ovh_console_url": "https://www.ovh.com/manager/#/public-cloud",
        }

    def generate_cloud_init(self, server_name: str, ssh_key_name: str = "orso-ops-key") -> str:
        """Génère le script cloud-init d'amorçage automatique d'une instance OVH."""
        return f"""#cloud-config
hostname: {server_name}
package_update: true
package_upgrade: true
packages:
  - docker.io
  - docker-compose
  - nginx
  - certbot
  - python3-certbot-nginx
  - curl
  - git
  - ufw

runcmd:
  # Activer Docker et le réseau interne Orso
  - systemctl enable docker
  - systemctl start docker
  - docker network create --driver bridge orso_network || true
  # Pare-feu strict
  - ufw allow 22/tcp
  - ufw allow 80/tcp
  - ufw allow 443/tcp
  - ufw --force enable
  # Prêt pour réception du conteneur Orso
  - echo "Orso Node {server_name} provisioned successfully" > /var/log/orso-bootstrap.log
"""


    # ── Authentification & Gestion des Droits API ────────────────────────────

    def get_credential_status(self) -> Dict[str, Any]:
        """Vérifie la validité des identifiants et diagnostique les habilitations."""
        if not self.is_configured():
            return {
                "configured": False,
                "status": "unconfigured",
                "message": "Clés API OVH non configurées dans l'environnement.",
                "has_wildcard_rights": False,
            }

        try:
            cred = self.request("GET", "/auth/currentCredential")
            if not cred or not isinstance(cred, dict):
                return {
                    "configured": True,
                    "status": "unknown",
                    "message": "Réponse inattendue de l'API OVH.",
                    "has_wildcard_rights": False,
                }

            rules = cred.get("rules", [])
            # Vérifier si les règles couvrent les sous-chemins ("/*") ou seulement la racine ("")
            has_wildcard = any(
                r.get("path") in ("/*", "*", "/") or r.get("path", "").startswith("/cloud") or r.get("path", "").startswith("/vps")
                for r in rules
            )
            has_root_only = all(r.get("path") == "" for r in rules) if rules else False

            allowed_ips = cred.get("allowedIPs", [])
            status_val = cred.get("status", "unknown")

            diagnostic = None
            if has_root_only:
                diagnostic = (
                    "Attention : La Consumer Key actuelle a été créée avec path='' (racine uniquement). "
                    "Les appels aux sous-ressources (/cloud, /vps, /me) sont rejetés (403 NOT_GRANTED_CALL). "
                    "Pour un provisionnement autonome, veuillez activer un token avec les droits sur '/*'."
                )

            return {
                "configured": True,
                "status": status_val,
                "credential_id": cred.get("credentialId"),
                "application_id": cred.get("applicationId"),
                "allowed_ips": allowed_ips,
                "rules": rules,
                "has_wildcard_rights": has_wildcard,
                "diagnostic": diagnostic,
                "expiration": cred.get("expiration"),
            }
        except Exception as e:
            return {
                "configured": True,
                "status": "error",
                "message": str(e),
                "has_wildcard_rights": False,
            }

    def create_credential_request(
        self,
        access_rules: Optional[List[Dict[str, str]]] = None,
        redirection: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Génère une demande de Consumer Key avec les droits complets sur l'API OVH."""
        if not self.application_key:
            raise ValueError("Application Key manquante pour demander un nouveau Consumer Key.")

        rules = access_rules or [
            {"method": "GET", "path": "/*"},
            {"method": "POST", "path": "/*"},
            {"method": "PUT", "path": "/*"},
            {"method": "DELETE", "path": "/*"},
        ]

        payload: Dict[str, Any] = {"accessRules": rules}
        if redirection:
            payload["redirection"] = redirection

        url = f"{self.endpoint_url}/auth/credential"
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "X-Ovh-Application": self.application_key,
                "Content-Type": "application/json",
                "User-Agent": "OrsoOlympeOps/1.0",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=8.0) as resp:
                res = json.loads(resp.read().decode("utf-8"))
                return {
                    "success": True,
                    "consumer_key": res.get("consumerKey"),
                    "validation_url": res.get("validationUrl"),
                    "state": res.get("state"),
                }
        except urllib.error.HTTPError as e:
            err_msg = e.read().decode("utf-8", errors="replace")
            raise ValueError(f"Erreur demande token OVH ({e.code}): {err_msg}")

    # ── Gestion Autonome des Ressources Cloud & VPS ──────────────────────────

    def list_cloud_projects(self) -> List[str]:
        """Retourne la liste des identifiants de projets Public Cloud."""
        res = self.request("GET", "/cloud/project")
        return res if isinstance(res, list) else []

    def get_project_detail(self, project_id: str) -> Optional[Dict[str, Any]]:
        """Consulte les détails d'un projet Public Cloud."""
        return self.request("GET", f"/cloud/project/{project_id}")

    def list_cloud_instances(self, project_id: str) -> List[Dict[str, Any]]:
        """Liste les instances de calcul déployées dans un projet Public Cloud."""
        res = self.request("GET", f"/cloud/project/{project_id}/instance")
        return res if isinstance(res, list) else []

    def list_vps(self) -> List[str]:
        """Retourne la liste des serveurs VPS associés au compte."""
        res = self.request("GET", "/vps")
        return res if isinstance(res, list) else []

    def get_vps_detail(self, vps_name: str) -> Optional[Dict[str, Any]]:
        """Retourne les informations matérielles et réseau d'un VPS."""
        return self.request("GET", f"/vps/{vps_name}")

    def create_cloud_instance(
        self,
        project_id: str,
        name: str,
        flavor_id: str,
        image_id: str,
        region: str = "GRA11",
        ssh_key_id: Optional[str] = None,
        user_data: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Déploie de manière autonome une nouvelle instance Public Cloud."""
        payload: Dict[str, Any] = {
            "name": name,
            "flavorId": flavor_id,
            "imageId": image_id,
            "region": region,
        }
        if ssh_key_id:
            payload["sshKeyId"] = ssh_key_id
        if user_data:
            payload["userData"] = user_data

        return self.request("POST", f"/cloud/project/{project_id}/instance", data=payload)


# Instance singleton
ovh_client = OVHClient()

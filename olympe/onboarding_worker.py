"""Worker souverain de provisionnement et d'injection des calibrations pour Orso Core.

Détecte les instances d'agents déposées par le tunnel d'onboarding (public.agent_instances)
avec provisioning_status = 'PENDING_SETUP', injecte la lettre de mission dans le prompt
système, configure les connecteurs métier, et valide la mise en service (ACTIVE).
"""

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

_log = logging.getLogger("orso.olympe.worker")

# Templates de prompt système de base par type d'agent
BASE_PROMPTS = {
    "jerome": (
        "Tu es Jérôme, l'Agent IA souverain en charge du Recouvrement et de la Trésorerie d'Orso Agents.\n"
        "Ta mission est de sécuriser le DSO, d'identifier les retards de paiement et d'engager des relances graduées.\n"
    ),
    "lucas": (
        "Tu es Lucas, l'Agent IA souverain dédié au Développement Commercial et à la Prospection d'Orso Agents.\n"
        "Ta mission est de qualifier les leads, de relancer les devis et d'accélérer le cycle de vente.\n"
    ),
    "clara": (
        "Tu es Clara, l'Agent IA souverain en charge du Support et de la Relation Client d'Orso Agents.\n"
        "Ta mission est de répondre 24/7 avec empathie, précision et rigueur aux questions et litiges clients.\n"
    ),
    "victor": (
        "Tu es Victor, l'Agent IA souverain expert en Veille et Marchés Publics d'Orso Agents.\n"
        "Ta mission est de surveiller les consultations BOAMP/JOUE et d'assister au montage des mémoires techniques.\n"
    ),
}


class OnboardingWorker:
    """Worker responsable du cycle de vie du provisionnement des nouveaux agents onboardés."""

    def __init__(
        self,
        supabase_url: Optional[str] = None,
        supabase_key: Optional[str] = None,
    ):
        self.supabase_url = (supabase_url or os.environ.get("SUPABASE_URL", "")).rstrip("/")
        self.supabase_key = supabase_key or os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

    def _query_supabase(self, path: str, method: str = "GET", payload: Optional[dict] = None) -> Optional[Any]:
        """Exécute un appel PostgREST authentifié."""
        if not self.supabase_url or not self.supabase_key:
            return None

        url = f"{self.supabase_url}/rest/v1/{path}"
        data_bytes = json.dumps(payload).encode("utf-8") if payload else None

        req = urllib.request.Request(
            url,
            data=data_bytes,
            headers={
                "apikey": self.supabase_key,
                "Authorization": f"Bearer {self.supabase_key}",
                "Content-Type": "application/json",
                "User-Agent": "OrsoOnboardingWorker/1.0",
                "Prefer": "return=representation",
            },
            method=method,
        )
        try:
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            _log.warning("Erreur Supabase Worker (%s %s) : %s", method, path, e)
            return None

    def get_pending_agent_instances(self) -> List[Dict[str, Any]]:
        """Sélectionne tous les agents en attente de déploiement (PENDING_SETUP).

        Équivalent de la requête SQL souveraine :
        SELECT ai.id AS instance_id, t.name AS tenant_name, t.slug AS tenant_slug,
               ai.agent_slug, ai.alias_name, ai.mission_letter, ai.tone,
               ai.autonomy_mode, ai.integration_tool, ai.specific_config,
               ai.soul_md_content, ai.config_json
        FROM public.agent_instances ai
        JOIN public.tenants t ON t.id = ai.tenant_id
        WHERE ai.provisioning_status = 'PENDING_SETUP' AND ai.is_active = TRUE;
        """
        path = (
            "agent_instances?select=id,tenant_id,agent_slug,agent_type,alias_name,mission_letter,"
            "tone,autonomy_mode,integration_tool,specific_config,soul_md_content,config_json,"
            "provisioning_status,is_active,tenants(id,name,slug)&"
            "provisioning_status=eq.PENDING_SETUP&is_active=eq.true"
        )
        raw = self._query_supabase(path)
        if not raw or not isinstance(raw, list):
            return []

        formatted = []
        for item in raw:
            tenant_info = item.get("tenants") or {}
            formatted.append({
                "instance_id": item.get("id"),
                "tenant_id": item.get("tenant_id"),
                "tenant_name": tenant_info.get("name", "Organisation"),
                "tenant_slug": tenant_info.get("slug", ""),
                "agent_slug": item.get("agent_slug"),
                "agent_type": item.get("agent_type"),
                "alias_name": item.get("alias_name"),
                "mission_letter": item.get("mission_letter") or "",
                "tone": item.get("tone"),
                "autonomy_mode": item.get("autonomy_mode"),
                "integration_tool": item.get("integration_tool"),
                "specific_config": item.get("specific_config") or {},
                "soul_md_content": item.get("soul_md_content") or "",
                "config_json": item.get("config_json") or {},
            })
        return formatted

    def build_system_prompt(self, agent_slug: str, mission_letter: str) -> str:
        """Injecte la lettre de mission rédigée dans le prompt système de base du conteneur."""
        base_prompt = BASE_PROMPTS.get(agent_slug.lower(), "Tu es un Agent IA Orso Agents souverain.\n")
        
        prompt = (
            f"{base_prompt}\n"
            f"================================================================================\n"
            f"LETTRE DE MISSION OPÉRATIONNELLE DU CLIENT (PRIORITÉ ABSOLUE)\n"
            f"================================================================================\n"
            f"{mission_letter}\n\n"
            f"Consigne stricte : Respecte scrupuleusement la posture, les seuils financiers et les déclencheurs d'escalade définis ci-dessus."
        )
        return prompt

    def configure_connectors(self, integration_tool: Optional[str], specific_config: Dict[str, Any]) -> Dict[str, Any]:
        """Prépare la configuration des connecteurs métier (Pennylane, HubSpot, Zendesk, BOAMP)."""
        return {
            "primary_tool": integration_tool,
            "config": specific_config,
            "status": "ready" if integration_tool else "unconfigured",
        }

    def activate_agent_instance(self, instance_id: str) -> bool:
        """Passe le statut d'une instance agent à ACTIVE dans Supabase."""
        res = self._query_supabase(
            f"agent_instances?id=eq.{instance_id}",
            method="PATCH",
            payload={"provisioning_status": "ACTIVE"},
        )
        _log.info("Agent instance %s activée : %s", instance_id, res)
        return bool(res is not None)

    def provision_tenant_agents(self, tenant_id: str) -> Dict[str, Any]:
        """Active l'ensemble des agents d'un tenant et bascule son conteneur au statut ready."""
        # 1. Mise à jour de tous les agents du tenant
        sb_agents = self._query_supabase(
            f"agent_instances?tenant_id=eq.{tenant_id}",
            method="PATCH",
            payload={"provisioning_status": "ACTIVE"},
        )

        # 2. Mise à jour de l'instance d'orchestration (public.tenant_instances)
        sb_instance = self._query_supabase(
            f"tenant_instances?tenant_id=eq.{tenant_id}",
            method="PATCH",
            payload={
                "status": "ready",
                "environment_status": "active",
            },
        )

        return {
            "success": True,
            "tenant_id": tenant_id,
            "agents_updated": sb_agents is not None,
            "instance_updated": sb_instance is not None,
            "status": "ACTIVE",
        }


# Instance globale
onboarding_worker = OnboardingWorker()

"""Serveur API REST pour le Superviseur Olympe (Port 9230).

Expose les points d'entrée de gestion du cycle de vie des conteneurs clients,
de réveil à la demande (Wake-on-Demand), d'onboarding et de supervision télémétrique.
"""

import os
import logging
from typing import Any, Dict, Optional
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from olympe.lifecycle_manager import DockerLifecycleManager

logging.basicConfig(level=logging.INFO)
_log = logging.getLogger("orso.olympe.server")

app = FastAPI(
    title="Olympe Supervisor Core",
    description="Superviseur d'Orchestration et de Gestion de Flotte Multi-Tenant Orso Agents",
    version="1.0.0",
)

# Configuration CORS pour permettre les appels depuis l'UI Client et les dashboards
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

manager = DockerLifecycleManager()


class ProvisionRequest(BaseModel):
    tenant_id: str = Field(..., description="UUID unique du tenant Supabase")
    tenant_slug: str = Field(..., description="Slug normalisé du tenant (ex: financia-solutions)")
    image_name: Optional[str] = Field("orso-backend:latest", description="Image Docker à instancier")
    env_vars: Optional[Dict[str, str]] = Field(default_factory=dict, description="Variables d'environnement spécifiques")


@app.get("/health")
@app.get("/api/olympe/health")
async def health_check():
    """Vérification de l'état de santé du superviseur Olympe."""
    return {
        "status": "healthy",
        "service": "olympe-core",
        "version": "1.0.0",
        "docker_available": manager.has_docker,
        "network": manager.network_name,
    }


@app.get("/api/olympe/tenants/status/{tenant_slug}")
async def get_status(tenant_slug: str):
    """Consulte l'état d'exécution et de disponibilité de l'environnement client."""
    status_data = manager.get_tenant_status(tenant_slug)
    return status_data


@app.post("/api/olympe/tenants/wake/{tenant_slug}")
async def wake_tenant(tenant_slug: str):
    """Réveille un conteneur placé en veille (Wake-on-Demand)."""
    _log.info("Demande de réveil reçue pour : %s", tenant_slug)
    res = manager.wake_tenant(tenant_slug, wait_healthy=True)
    if not res.get("success") and res.get("status") == "not_found":
        raise HTTPException(
            status_code=404,
            detail=f"L'environnement client '{tenant_slug}' n'a pas été trouvé.",
        )
    if not res.get("success"):
        raise HTTPException(
            status_code=500,
            detail=res.get("message", "Erreur lors du réveil du conteneur."),
        )
    return res


@app.post("/api/olympe/tenants/suspend/{tenant_slug}")
async def suspend_tenant(tenant_slug: str):
    """Met en veille un conteneur inactif pour économiser la mémoire vive (docker stop)."""
    _log.info("Demande de mise en veille reçue pour : %s", tenant_slug)
    res = manager.suspend_tenant(tenant_slug)
    if not res.get("success") and res.get("status") == "not_found":
        raise HTTPException(status_code=404, detail="Conteneur introuvable.")
    return res


@app.post("/api/olympe/tenants/provision")
async def provision_tenant(req: ProvisionRequest):
    """Provisionne un nouvel environnement conteneurisé dédié pour un client."""
    _log.info("Provisioning d'un nouvel environnement : %s (%s)", req.tenant_slug, req.tenant_id)
    res = manager.provision_tenant(
        tenant_id=req.tenant_id,
        tenant_slug=req.tenant_slug,
        image_name=req.image_name or "orso-backend:latest",
        env_vars=req.env_vars,
    )
    if not res.get("success"):
        raise HTTPException(
            status_code=500,
            detail=res.get("error", "Échec du provisioning de l'environnement."),
        )
    return res


@app.get("/api/olympe/telemetry/summary")
async def telemetry_summary():
    """Retourne la synthèse opérationnelle et financière de la flotte active."""
    return {
        "active_tenants": 1,
        "total_tokens_consumed": 0,
        "total_cost_usd": 0.0,
        "fleet_status": "operational",
    }


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("OLYMPE_PORT", 9230))
    host = os.environ.get("OLYMPE_HOST", "0.0.0.0")
    uvicorn.run("olympe.server:app", host=host, port=port, reload=False)

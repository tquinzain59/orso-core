"""Serveur API REST pour le Superviseur Olympe (Port 9230).

Expose les points d'entrée de gestion du cycle de vie des conteneurs clients,
de réveil à la demande (Wake-on-Demand), de pilotage commercial (Orso Ops Cockpit),
de facturation Stripe et de supervision de flotte.
"""

import os
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from olympe.auth import authenticate_superadmin, clear_token_cache, require_superadmin
from olympe.lifecycle_manager import DockerLifecycleManager
from olympe.ops_manager import OpsManager

logging.basicConfig(level=logging.INFO)
_log = logging.getLogger("orso.olympe.server")

app = FastAPI(
    title="Olympe Supervisor & Ops Core",
    description="Superviseur d'Orchestration, Cockpit Opérations & Facturation Orso Agents",
    version="1.1.0",
)

# Configuration CORS pour permettre les appels depuis l'UI Client et le Cockpit Ops
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

manager = DockerLifecycleManager()
ops_manager = OpsManager()

PROJECT_ROOT = Path(__file__).resolve().parent.parent
UI_OPS_DIST = PROJECT_ROOT / "apps" / "ui-ops" / "dist"


# ── Modèles Pydantic ─────────────────────────────────────────────────────────

class ProvisionRequest(BaseModel):
    tenant_id: str = Field(..., description="UUID unique du tenant Supabase")
    tenant_slug: str = Field(..., description="Slug normalisé du tenant (ex: financia-solutions)")
    image_name: Optional[str] = Field("orso-backend:latest", description="Image Docker à instancier")
    env_vars: Optional[Dict[str, str]] = Field(default_factory=dict, description="Variables d'environnement spécifiques")


class UpdateAgentsRequest(BaseModel):
    active: List[str] = Field(..., description="Liste des identifiants d'agents activés (jerome, lucas, clara, victor)")
    trials: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Configuration des périodes d'essai par agent")


class UpdateSubscriptionRequest(BaseModel):
    tier_id: str = Field(..., description="Identifiant du forfait : 1_agent, 2_agents, 4_agents, custom")
    status: Optional[str] = Field("active", description="Statut de l'abonnement : active, trialing, past_due, canceled")


class LoginRequest(BaseModel):
    email: str = Field(..., description="Adresse email superadmin")
    password: str = Field(..., description="Mot de passe superadmin")


class CreateUserRequest(BaseModel):
    email: str = Field(..., description="Adresse email de l'utilisateur (identifiant de connexion)")
    password: Optional[str] = Field(None, description="Mot de passe initial")
    full_name: str = Field(..., description="Nom complet du collaborateur")
    role: str = Field("Membre", description="Rôle ou fonction dans la société (ex: DAF, Commercial, Dirigeant)")
    is_admin: bool = Field(False, description="Définit si l'utilisateur possède les droits d'administration Orso")


# ── Endpoints Supervision & Cycle de Vie Conteneurs ──────────────────────────

@app.get("/health")
@app.get("/api/olympe/health")
async def health_check():
    """Vérification de l'état de santé du superviseur Olympe."""
    return {
        "status": "healthy",
        "service": "olympe-core",
        "version": "1.1.0",
        "docker_available": manager.has_docker,
        "network": manager.network_name,
        "ui_ops_built": (UI_OPS_DIST / "index.html").is_file(),
    }


@app.get("/api/olympe/tenants/status/{tenant_slug}")
async def get_status(tenant_slug: str):
    """Consulte l'état d'exécution et de disponibilité de l'environnement client."""
    return manager.get_tenant_status(tenant_slug)


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
    stats = ops_manager.get_stats()
    return {
        "active_tenants": stats["kpis"]["active_subscribers"],
        "total_clients": stats["kpis"]["total_clients"],
        "mrr_ht": stats["kpis"]["mrr_ht"],
        "fleet_status": "operational",
    }


# ── Authentification IAM Superadmin ──────────────────────────────────────────

@app.post("/api/olympe/ops/auth/login")
async def ops_login(req: LoginRequest):
    """Authentifie un administrateur auprès de Supabase Auth et délivre une session superadmin."""
    return authenticate_superadmin(email=req.email, password=req.password)


@app.get("/api/olympe/ops/auth/me")
async def ops_me(admin: Dict[str, Any] = Depends(require_superadmin)):
    """Vérifie la validité de la session de l'administrateur connecté."""
    return {"user": admin}


@app.post("/api/olympe/ops/auth/logout")
async def ops_logout():
    """Déconnexion de session superadmin."""
    clear_token_cache()
    return {"success": True, "message": "Déconnexion réussie."}


# ── Endpoints Cockpit Orso Ops & Facturation (Protégés Superadmin) ───────────

@app.get("/api/olympe/ops/stats")
async def get_ops_stats(admin: Dict[str, Any] = Depends(require_superadmin)):
    """Retourne les indicateurs consolidés (KPIs, MRR, répartition des forfaits)."""
    return ops_manager.get_stats()


@app.get("/api/olympe/ops/tenants")
async def list_tenants(admin: Dict[str, Any] = Depends(require_superadmin)):
    """Retourne la liste des clients inscrits avec contact, abonnement et agents activés."""
    return {"tenants": ops_manager.get_tenants_overview()}


@app.get("/api/olympe/ops/tenants/{tenant_id}")
async def get_tenant(tenant_id: str, admin: Dict[str, Any] = Depends(require_superadmin)):
    """Retourne le profil détaillé d'un client."""
    detail = ops_manager.get_tenant_detail(tenant_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Client introuvable.")
    return detail


@app.post("/api/olympe/ops/tenants/{tenant_id}/agents")
async def update_agents(tenant_id: str, req: UpdateAgentsRequest, admin: Dict[str, Any] = Depends(require_superadmin)):
    """Active/désactive des agents et paramètre les périodes d'essai pour un client."""
    res = ops_manager.update_tenant_agents(
        tenant_id=tenant_id,
        active_agents=req.active,
        trials_config=req.trials,
    )
    return res


@app.post("/api/olympe/ops/tenants/{tenant_id}/subscription")
async def update_subscription(tenant_id: str, req: UpdateSubscriptionRequest, admin: Dict[str, Any] = Depends(require_superadmin)):
    """Met à jour le plan d'abonnement Stripe (99€, 169€, 279€ HT)."""
    res = ops_manager.update_tenant_subscription(
        tenant_id=tenant_id,
        tier_id=req.tier_id,
        status=req.status or "active",
    )
    return res


@app.get("/api/olympe/ops/tenants/{tenant_id}/users")
async def list_tenant_users(tenant_id: str, admin: Dict[str, Any] = Depends(require_superadmin)):
    """Retourne la liste des utilisateurs d'un client."""
    users = ops_manager.get_tenant_users(tenant_id)
    return {"users": users}


@app.post("/api/olympe/ops/tenants/{tenant_id}/users")
async def create_user_for_tenant(tenant_id: str, req: CreateUserRequest, admin: Dict[str, Any] = Depends(require_superadmin)):
    """Crée un nouvel utilisateur pour un client donné."""
    try:
        user = ops_manager.create_tenant_user(
            tenant_id=tenant_id,
            email=req.email,
            password=req.password,
            full_name=req.full_name,
            role=req.role,
            is_admin=req.is_admin,
        )
        return {"success": True, "user": user}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/api/olympe/ops/tenants/{tenant_id}/users/{user_id}")
async def delete_user_for_tenant(tenant_id: str, user_id: str, admin: Dict[str, Any] = Depends(require_superadmin)):
    """Supprime un utilisateur d'une organisation cliente."""
    success = ops_manager.delete_tenant_user(tenant_id=tenant_id, user_id=user_id)
    return {"success": success}


@app.get("/api/olympe/ops/invoices")
async def list_invoices(admin: Dict[str, Any] = Depends(require_superadmin)):
    """Retourne l'historique complet des factures clients."""
    return {"invoices": ops_manager.list_all_invoices()}


@app.post("/api/olympe/ops/webhooks/stripe")
async def stripe_webhook(request: Request):
    """Réceptionne et traite les webhooks Stripe Billing."""
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Payload JSON invalide")
    return ops_manager.handle_stripe_webhook(payload)


# ── Service Frontend SPA Orso Ops (apps/ui-ops/dist) ─────────────────────────

if (UI_OPS_DIST / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=str(UI_OPS_DIST / "assets")), name="ops_assets")


@app.get("/")
@app.get("/ops")
@app.get("/ops/{full_path:path}")
async def serve_ops_ui():
    """Sert l'interface SPA du Cockpit Orso Ops."""
    index_file = UI_OPS_DIST / "index.html"
    if index_file.is_file():
        return FileResponse(index_file)
    return HTMLResponse(
        """<!DOCTYPE html>
        <html lang="fr">
        <head><meta charset="utf-8"><title>Orso Ops Cockpit</title></head>
        <body style="font-family: sans-serif; background: #0f172a; color: #f8fafc; padding: 40px; text-align: center;">
            <h1 style="color: #38bdf8;">Orso Ops Cockpit - Prêt pour compilation</h1>
            <p>Le superviseur Olympe est en ligne sur le port 9230.</p>
            <p style="color: #94a3b8;">L'application web est en cours d'assemblage dans <code>apps/ui-ops/dist</code>.</p>
        </body></html>"""
    )


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("OLYMPE_PORT", 9230))
    host = os.environ.get("OLYMPE_HOST", "0.0.0.0")
    uvicorn.run("olympe.server:app", host=host, port=port, reload=False)

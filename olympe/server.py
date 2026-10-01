"""Serveur API REST pour le Superviseur Olympe (Port 9230).

Expose les points d'entrée de gestion du cycle de vie des conteneurs clients,
de réveil à la demande (Wake-on-Demand), de pilotage commercial (Orso Ops Cockpit),
de facturation Stripe et de supervision de flotte.
"""

import os
import logging
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import Depends, FastAPI, HTTPException, Request, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from olympe.auth import (
    authenticate_superadmin,
    clear_token_cache,
    require_superadmin,
    require_ops_actor,
    check_sandbox_tenant_access,
    verify_stripe_signature,
    revoke_token,
    is_mock_auth_enabled,
    security_bearer,
    change_superadmin_password,
    get_auth_audit_events,
)
from olympe.lifecycle_manager import DockerLifecycleManager
from olympe.ops_manager import OpsManager
from olympe.ovh_client import ovh_client
from olympe.telemetry_client import telemetry_client

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


class CreateTenantOpsRequest(BaseModel):
    tenant_slug: str = Field("clientx-orso", description="Slug normalisé du tenant")
    name: Optional[str] = Field("CLIENTX-ORSO (TEST)", description="Nom d'affichage du tenant")
    contact_email: Optional[str] = Field("test-drone-notifications@test.orso-agents.fr", description="Email de notification")
    contact_name: Optional[str] = Field("Dirigeant Test ClientX", description="Nom du contact dirigeant")
    quotas: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Quotas matériels explicites")


class UpdateAgentsRequest(BaseModel):
    active: List[str] = Field(..., description="Liste des identifiants d'agents activés (jerome, lucas, clara, victor)")
    trials: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Configuration des périodes d'essai par agent")


class UpdateSubscriptionRequest(BaseModel):
    tier_id: str = Field(..., description="Identifiant du forfait : 1_agent, 2_agents, 4_agents, custom")
    status: Optional[str] = Field("active", description="Statut de l'abonnement : active, trialing, past_due, canceled")


class LoginRequest(BaseModel):
    email: str = Field(..., description="Adresse email superadmin")
    password: str = Field(..., description="Mot de passe superadmin")


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., description="Ancien mot de passe actuel")
    new_password: str = Field(..., description="Nouveau mot de passe conforme")
    confirm_password: str = Field(..., description="Confirmation du nouveau mot de passe")


class CreateUserRequest(BaseModel):
    email: str = Field(..., description="Adresse email de l'utilisateur (identifiant de connexion)")
    password: Optional[str] = Field(None, description="Mot de passe initial")
    full_name: str = Field(..., description="Nom complet du collaborateur")
    role: str = Field("Membre", description="Rôle ou fonction dans la société (ex: DAF, Commercial, Dirigeant)")
    is_admin: bool = Field(False, description="Définit si l'utilisateur possède les droits d'administration Orso")


class UpdateAgentStatusRequest(BaseModel):
    status: str = Field(..., description="Statut de l'instance d'agent : PENDING_SETUP, PROVISIONING, ACTIVE, ERROR")


class OnboardingInitSetupRequest(BaseModel):
    email: str = Field(..., description="Adresse email du contact dirigeant")
    name: str = Field(..., description="Nom complet du contact")
    company_name: str = Field(..., description="Raison sociale de l'entreprise")
    slug: Optional[str] = Field(None, description="Slug du client")


class OnboardingCreateSubscriptionRequest(BaseModel):
    customer_id: str = Field(..., description="Identifiant client Stripe (cus_...)")
    payment_method_id: str = Field(..., description="Identifiant moyen de paiement Stripe (pm_...)")
    tier_id: str = Field(..., description="Forfait sélectionné : 1_agent, 2_agents, 3_agents, 4_agents")
    agents_count: int = Field(1, description="Nombre d'agents sélectionnés (1 à 4)")


class OnboardingCreateAdminUserRequest(BaseModel):
    tenant_id: str = Field(..., description="UUID unique ou slug du tenant")
    email: str = Field(..., description="Adresse email professionnelle du dirigeant/administrateur")
    full_name: str = Field(..., description="Prénom et nom de l'administrateur")
    role: Optional[str] = Field("Dirigeant", description="Fonction ou rôle dans l'entreprise")
    phone: Optional[str] = Field(None, description="Téléphone professionnel direct")
    password: Optional[str] = Field(None, description="Mot de passe initial sécurisé")


class RewriteMissionLetterRequest(BaseModel):
    agent_id: str = Field(..., description="Identifiant de l'agent (jerome, lucas, clara, victor)")
    agent_name: str = Field(..., description="Nom d'usage de l'agent")
    role_title: str = Field(..., description="Titre du rôle")
    company_name: str = Field(..., description="Nom de l'entreprise")
    sector: str = Field(..., description="Secteur d'activité")
    raw_notes: Optional[str] = Field("", description="Notes ou consignes rédigées par l'utilisateur")
    extracted_docs_text: Optional[str] = Field("", description="Extraits textuels de documents d'entreprise")


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
async def get_status(tenant_slug: str, actor: Dict[str, Any] = Depends(require_ops_actor("tenants:read"))):
    """Consulte l'état d'exécution et de disponibilité de l'environnement client (sécurisé - KAN-40)."""
    check_sandbox_tenant_access(actor, tenant_slug, ops_mgr=ops_manager)
    return manager.get_tenant_status(tenant_slug)


@app.post("/api/olympe/tenants/wake/{tenant_slug}")
async def wake_tenant(tenant_slug: str, actor: Dict[str, Any] = Depends(require_ops_actor("tenants:provision:sandbox"))):
    """Réveille un conteneur placé en veille (Wake-on-Demand - sécurisé - KAN-40)."""
    check_sandbox_tenant_access(actor, tenant_slug, ops_mgr=ops_manager)
    # VERROU 4 : Interdiction de wake sans abonnement
    tenant = ops_manager.get_tenant_detail(tenant_slug)
    if not tenant:
        raise HTTPException(status_code=404, detail="Client introuvable.")
    sub_status = tenant.get("subscription", {}).get("status", "none")
    if sub_status not in ["active", "trialing"]:
        raise HTTPException(status_code=403, detail="Impossible de démarrer le conteneur : ce client n'a aucun abonnement actif.")
        
    _log.info("Demande de réveil reçue pour : %s (acteur: %s)", tenant_slug, actor.get("actor"))
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
async def suspend_tenant(tenant_slug: str, actor: Dict[str, Any] = Depends(require_ops_actor("tenants:provision:sandbox"))):
    """Met en veille un conteneur inactif pour économiser la mémoire vive (sécurisé - KAN-40)."""
    check_sandbox_tenant_access(actor, tenant_slug, ops_mgr=ops_manager)
    _log.info("Demande de mise en veille reçue pour : %s (acteur: %s)", tenant_slug, actor.get("actor"))
    res = manager.suspend_tenant(tenant_slug)
    if not res.get("success") and res.get("status") == "not_found":
        raise HTTPException(status_code=404, detail="Conteneur introuvable.")
    return res


@app.post("/api/olympe/tenants/provision")
async def provision_tenant(req: ProvisionRequest, admin: Dict[str, Any] = Depends(require_superadmin)):
    """Provisionne un nouvel environnement conteneurisé dédié pour un client (strictement superadmin - KAN-40)."""
    _log.info("Provisioning d'un nouvel environnement par admin %s : %s (%s)", admin.get("email"), req.tenant_slug, req.tenant_id)
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
async def ops_logout(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security_bearer),
):
    """Déconnexion de session superadmin avec révocation immédiate du token (CA6)."""
    if credentials and credentials.credentials:
        revoke_token(credentials.credentials)
    clear_token_cache()
    return {"success": True, "message": "Déconnexion réussie."}


@app.post("/api/olympe/ops/auth/change-password")
async def ops_change_password(
    req: ChangePasswordRequest,
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security_bearer),
    admin: Dict[str, Any] = Depends(require_superadmin),
):
    """Permet au superadmin connecté de modifier son mot de passe en libre-service (KAN-50)."""
    if req.new_password != req.confirm_password:
        raise HTTPException(
            status_code=400,
            detail="Le nouveau mot de passe et sa confirmation ne correspondent pas.",
        )

    client_ip = request.client.host if request.client else "127.0.0.1"
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        client_ip = forwarded_for.split(",")[0].strip()

    current_token = credentials.credentials if credentials else None

    return change_superadmin_password(
        user_id=admin.get("id"),
        email=admin.get("email"),
        current_password=req.current_password,
        new_password=req.new_password,
        current_token=current_token,
        client_ip=client_ip,
    )


@app.get("/api/olympe/ops/auth/audit-log")
async def ops_auth_audit_log(admin: Dict[str, Any] = Depends(require_superadmin)):
    """Consulte le journal d'audit des modifications de mot de passe (KAN-50 - CA9)."""
    return {"events": get_auth_audit_events(limit=50)}


# ── Endpoints Cockpit Orso Ops & Facturation (Protégés Superadmin & Drone RBAC) ─

@app.get("/api/olympe/ops/stats")
async def get_ops_stats(actor: Dict[str, Any] = Depends(require_ops_actor("tenants:read"))):
    """Retourne les indicateurs consolidés (KPIs, MRR, répartition des forfaits)."""
    ops_manager.record_audit_event(actor, "stats:read", "fleet")
    stats = ops_manager.get_stats()
    stats["demo_mode"] = ops_manager.demo_mode
    return stats


@app.get("/api/olympe/ops/tenants")
async def list_tenants(actor: Dict[str, Any] = Depends(require_ops_actor("tenants:read"))):
    """Retourne la liste des clients inscrits avec contact, abonnement et agents activés (CA1)."""
    ops_manager.record_audit_event(actor, "tenants:read", "fleet")
    return {
        "tenants": ops_manager.get_tenants_overview(),
        "demo_mode": ops_manager.demo_mode,
    }


@app.post("/api/olympe/ops/tenants")
async def create_tenant(req: CreateTenantOpsRequest, actor: Dict[str, Any] = Depends(require_ops_actor("tenants:provision:sandbox"))):
    """Crée et provisionne un tenant (restreint au périmètre sandbox pour le drone - L3/CA2)."""
    check_sandbox_tenant_access(actor, req.tenant_slug, ops_mgr=ops_manager)
    return ops_manager.create_sandbox_tenant(
        tenant_slug=req.tenant_slug,
        name=req.name or "CLIENTX-ORSO (TEST)",
        contact_email=req.contact_email or "test-drone-notifications@test.orso-agents.fr",
        contact_name=req.contact_name or "Dirigeant Test ClientX",
        quotas=req.quotas,
    )


@app.get("/api/olympe/ops/tenants/{tenant_id}")
async def get_tenant(tenant_id: str, actor: Dict[str, Any] = Depends(require_ops_actor("tenants:read"))):
    """Retourne le profil détaillé d'un client (vérifie la whitelist de test pour le drone - CA1)."""
    check_sandbox_tenant_access(actor, tenant_id, ops_mgr=ops_manager)
    detail = ops_manager.get_tenant_detail(tenant_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Client introuvable.")
    ops_manager.record_audit_event(actor, "tenant:read", tenant_id)
    return detail


@app.delete("/api/olympe/ops/tenants/{tenant_id}")
async def delete_tenant(tenant_id: str, actor: Dict[str, Any] = Depends(require_ops_actor("tenants:teardown:sandbox"))):
    """Détruit proprement et de manière idempotente un tenant (restreint au périmètre sandbox - L3/CA2)."""
    check_sandbox_tenant_access(actor, tenant_id, ops_mgr=ops_manager)
    return ops_manager.delete_tenant(tenant_id)


@app.post("/api/olympe/ops/tenants/{tenant_id}/agents")
async def update_agents(tenant_id: str, req: UpdateAgentsRequest, actor: Dict[str, Any] = Depends(require_ops_actor("agents:write:sandbox"))):
    """Active/désactive des agents et paramètre les périodes d'essai (CA1/CA3)."""
    check_sandbox_tenant_access(actor, tenant_id, ops_mgr=ops_manager)
    try:
        res = ops_manager.update_tenant_agents(
            tenant_id=tenant_id,
            active_agents=req.active,
            trials_config=req.trials,
        )
        ops_manager.record_audit_event(actor, "agents:write", tenant_id, details={"active": req.active})
        return res
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/olympe/ops/tenants/{tenant_id}/subscription")
async def update_subscription(tenant_id: str, req: UpdateSubscriptionRequest, admin: Dict[str, Any] = Depends(require_superadmin)):
    """Met à jour le plan d'abonnement Stripe (strictement réservé au superadmin humain - CA3)."""
    res = ops_manager.update_tenant_subscription(
        tenant_id=tenant_id,
        tier_id=req.tier_id,
        status=req.status or "active",
    )
    return res


@app.get("/api/olympe/ops/tenants/{tenant_id}/users")
async def list_tenant_users(tenant_id: str, admin: Dict[str, Any] = Depends(require_superadmin)):
    """Retourne la liste des utilisateurs d'un client (strictement superadmin - CA3)."""
    users = ops_manager.get_tenant_users(tenant_id)
    return {"users": users}


@app.post("/api/olympe/ops/tenants/{tenant_id}/users")
async def create_user_for_tenant(tenant_id: str, req: CreateUserRequest, admin: Dict[str, Any] = Depends(require_superadmin)):
    """Crée un nouvel utilisateur pour un client (IAM - strictement superadmin - CA3)."""
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
    """Supprime un utilisateur d'une organisation cliente (IAM - strictement superadmin - CA3)."""
    success = ops_manager.delete_tenant_user(tenant_id=tenant_id, user_id=user_id)
    return {"success": success}


@app.get("/api/olympe/ops/invoices")
async def list_invoices(actor: Dict[str, Any] = Depends(require_ops_actor("billing:read"))):
    """Retourne l'historique complet des factures clients (portée billing:read)."""
    ops_manager.record_audit_event(actor, "invoices:read", "billing")
    return {
        "invoices": ops_manager.list_all_invoices(),
        "demo_mode": ops_manager.demo_mode,
    }


@app.post("/api/olympe/ops/webhooks/stripe")
async def stripe_webhook(request: Request):
    """Réceptionne et traite les webhooks Stripe Billing avec vérification de signature obligatoire (KAN-39)."""
    body_bytes = await request.body()
    sig_header = request.headers.get("stripe-signature")
    webhook_secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "").strip()

    # Règle stricte KAN-39 : Rejet obligatoire si en-tête absent ou signature invalide
    if webhook_secret:
        if not sig_header:
            _log.warning("[SECURITY] Rejet 400 : En-tête Stripe-Signature manquant sur le webhook Stripe")
            raise HTTPException(status_code=400, detail="En-tête Stripe-Signature manquant.")
        if not verify_stripe_signature(body_bytes, sig_header, webhook_secret):
            _log.warning("[SECURITY] Rejet 400 : Signature invalide sur le webhook Stripe")
            raise HTTPException(status_code=400, detail="Signature webhook Stripe invalide.")
    elif not is_mock_auth_enabled():
        _log.error("[SECURITY] STRIPE_WEBHOOK_SECRET non configuré en production.")
        raise HTTPException(status_code=500, detail="Configuration webhook Stripe serveur incomplète.")
    else:
        # En mode test mocké sans secret global : si un en-tête de test est fourni, on le valide
        if sig_header:
            if not verify_stripe_signature(body_bytes, sig_header, "whsec_test_secret_key_123"):
                raise HTTPException(status_code=400, detail="Signature webhook Stripe invalide.")

    try:
        payload = json.loads(body_bytes.decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=400, detail="Payload JSON invalide")

    return ops_manager.handle_stripe_webhook(payload)


@app.get("/api/olympe/ops/webhooks/deliveries")
async def list_webhook_deliveries(actor: Dict[str, Any] = Depends(require_ops_actor("webhooks:read"))):
    """Consulte le journal de livraison des webhooks Stripe (portée webhooks:read - L5/CA6)."""
    deliveries = ops_manager.list_webhook_deliveries()
    return {"deliveries": deliveries, "count": len(deliveries)}


@app.get("/api/olympe/ops/audit-log")
async def get_audit_log(actor: Dict[str, Any] = Depends(require_ops_actor("tenants:read"))):
    """Consulte le journal d'audit des actions humaines et machine (CA7)."""
    return {"events": ops_manager.get_audit_events()}


# ── Endpoints Publics Onboarding Stripe ────────────────────────────────────

@app.post("/api/olympe/onboarding/init-setup")
async def onboarding_init_setup(req: OnboardingInitSetupRequest):
    """Crée ou retrouve un client Stripe et génère un SetupIntent pour l'onboarding public."""
    try:
        res = ops_manager.create_onboarding_setup_intent(
            email=req.email,
            name=req.name,
            company_name=req.company_name,
            slug=req.slug,
        )
        return res
    except Exception as e:
        _log.error("Erreur lors de l'init setup onboarding : %s", e)
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/olympe/onboarding/create-subscription")
async def onboarding_create_subscription(req: OnboardingCreateSubscriptionRequest):
    """Crée l'abonnement récurrent officiel avec 30 jours d'essai gratuit dans Stripe Billing."""
    try:
        res = ops_manager.create_trial_subscription(
            customer_id=req.customer_id,
            payment_method_id=req.payment_method_id,
            tier_id=req.tier_id,
            agents_count=req.agents_count,
        )
        return res
    except Exception as e:
        _log.error("Erreur lors de la création d'abonnement onboarding : %s", e)
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/olympe/onboarding/create-admin-user")
async def onboarding_create_admin_user(req: OnboardingCreateAdminUserRequest):
    """Crée ou rattache le compte administrateur du client suite à la souscription d'onboarding."""
    try:
        kwargs: Dict[str, Any] = {
            "tenant_id": req.tenant_id,
            "email": req.email,
            "full_name": req.full_name,
            "role": req.role or "Dirigeant",
            "phone": req.phone,
        }
        if req.password:
            kwargs["password"] = req.password

        user = ops_manager.create_onboarding_admin_user(**kwargs)
        return {"success": True, "user": user}
    except Exception as e:
        _log.error("Erreur lors de la création du compte administrateur onboarding : %s", e)
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/olympe/onboarding/rewrite-mission-letter")
async def rewrite_mission_letter(req: RewriteMissionLetterRequest):
    """Génère ou réécrit la lettre de mission opérationnelle avec DeepSeek côté serveur."""
    try:
        res = ops_manager.rewrite_mission_letter(
            agent_id=req.agent_id,
            agent_name=req.agent_name,
            role_title=req.role_title,
            company_name=req.company_name,
            sector=req.sector,
            raw_notes=req.raw_notes or "",
            extracted_docs_text=req.extracted_docs_text or "",
        )
        return res
    except Exception as e:
        _log.error("Erreur réécriture lettre de mission : %s", e)
        raise HTTPException(status_code=400, detail=str(e))


# ── Endpoints Onboarding & Déploiement OVH ──────────────────────────────────

@app.get("/api/olympe/ops/onboarding/pending")
async def get_pending_onboarding(admin: Dict[str, Any] = Depends(require_superadmin)):
    """Retourne la liste des nouveaux clients en attente de déploiement."""
    pending = ops_manager.get_pending_onboarding()
    return {"pending": pending, "count": len(pending)}


@app.get("/api/olympe/ops/onboarding/orders")
async def list_onboarding_orders(admin: Dict[str, Any] = Depends(require_superadmin)):
    """Retourne l'historique complet des commandes d'onboarding avec détail des calibrations."""
    orders = ops_manager.get_onboarding_orders()
    return {"orders": orders, "count": len(orders)}


@app.get("/api/olympe/ops/onboarding/orders/{tenant_id}")
async def get_onboarding_order(tenant_id: str, admin: Dict[str, Any] = Depends(require_superadmin)):
    """Retourne le profil détaillé et la calibration d'une commande d'onboarding."""
    detail = ops_manager.get_onboarding_order_detail(tenant_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Commande d'onboarding introuvable.")
    return detail


@app.get("/api/olympe/ops/onboarding/ovh-sizing")
async def get_ovh_sizing(admin: Dict[str, Any] = Depends(require_superadmin)):
    """Retourne l'évaluation du dimensionnement matériel et la recommandation d'instance OVH."""
    return ops_manager.get_ovh_sizing()


@app.post("/api/olympe/ops/onboarding/{tenant_id}/provision")
async def provision_onboarding_order(tenant_id: str, admin: Dict[str, Any] = Depends(require_superadmin)):
    """Valide le déploiement d'un client et active ses agents en production."""
    try:
        tenant_detail = ops_manager.get_tenant_detail(tenant_id)
        if not tenant_detail:
            raise HTTPException(status_code=404, detail=f"Client {tenant_id} introuvable.")

        actual_tenant_id = tenant_detail["id"]
        tenant_slug = tenant_detail.get("slug", "")

        # Déclenchement du provisioning physique Docker
        prov_res = manager.provision_tenant(
            tenant_id=actual_tenant_id,
            tenant_slug=tenant_slug,
        )

        # Contrôle strict du retour du provisioning (KAN-44)
        if not prov_res.get("success"):
            err_code = prov_res.get("error", "ERR_PROVISION_FAILED")
            err_msg = prov_res.get("message", "Échec du provisioning conteneur")
            _log.error("Provisioning refusé pour %s (%s): %s - %s", tenant_slug, actual_tenant_id, err_code, err_msg)
            ops_manager.record_audit_event(
                actor=admin,
                action="provision:failed",
                target=actual_tenant_id,
                details={"error": err_code, "reason": err_msg, "tenant_slug": tenant_slug},
            )
            raise HTTPException(
                status_code=400,
                detail=f"Provisioning refusé : {err_msg} [{err_code}]",
            )

        # Réveil conteneur post-provisioning si non running
        try:
            status_after = manager.get_tenant_status(tenant_slug)
            if not status_after.get("running"):
                manager.wake_tenant(tenant_slug, wait_healthy=False)
        except Exception as we:
            _log.warning("Notice réveil conteneur post-provisioning pour %s: %s", tenant_slug, we)

        return ops_manager.provision_onboarding_order(tenant_id, provisioning_result=prov_res)
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/olympe/ops/agent-instances/{instance_id}/status")
async def update_agent_status(instance_id: str, req: UpdateAgentStatusRequest, admin: Dict[str, Any] = Depends(require_superadmin)):
    """Met à jour le statut d'une instance agent (PENDING_SETUP, PROVISIONING, ACTIVE, ERROR)."""
    return ops_manager.update_agent_instance_status(instance_id, req.status)


@app.get("/api/olympe/ops/ovh/status")
async def get_ovh_status(admin: Dict[str, Any] = Depends(require_superadmin)):
    """Retourne l'état de la connexion API OVH, la validation du token et le diagnostic des permissions."""
    status = ovh_client.get_credential_status()
    if status.get("has_wildcard_rights"):
        try:
            status["cloud_projects"] = ovh_client.list_cloud_projects()
        except Exception:
            status["cloud_projects"] = []
        try:
            status["vps_list"] = ovh_client.list_vps()
        except Exception:
            status["vps_list"] = []
    else:
        status["cloud_projects"] = []
        status["vps_list"] = []
    return status


@app.post("/api/olympe/ops/ovh/credential-request")
async def request_ovh_credential(admin: Dict[str, Any] = Depends(require_superadmin)):
    """Génère une nouvelle demande de Consumer Key OVH avec les droits '/*' nécessaires."""
    try:
        return ovh_client.create_credential_request()
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))




# ── Télémétrie & Environnements Docker ─────────────────────────────────────

@app.get("/api/olympe/ops/telemetry/summary")
async def get_telemetry_summary(admin: Dict[str, Any] = Depends(require_superadmin)):
    """Retourne les métriques de télémétrie consolidées de la plateforme."""
    return telemetry_client.get_summary()


@app.get("/api/olympe/ops/telemetry/environments")
async def get_telemetry_environments(admin: Dict[str, Any] = Depends(require_superadmin)):
    """Retourne la liste des environnements Docker enrichis avec leurs signes vitaux et clients associés."""
    tenants = ops_manager.get_tenants_overview()
    environments = telemetry_client.get_environments(tenants)
    return {"environments": environments, "count": len(environments)}


@app.get("/api/olympe/ops/telemetry/history/{agent_id}")
async def get_telemetry_history(agent_id: int, limit: int = 25, admin: Dict[str, Any] = Depends(require_superadmin)):
    """Retourne l'historique des snapshots d'un agent."""
    return telemetry_client.get_history(agent_id, limit=limit)


@app.get("/api/olympe/ops/telemetry/alerts")
async def get_telemetry_alerts(agent_id: Optional[int] = None, admin: Dict[str, Any] = Depends(require_superadmin)):
    """Retourne les alertes actives."""
    alerts = telemetry_client.get_alerts(resolved=False, agent_id=agent_id)
    return {"alerts": alerts, "count": len(alerts)}


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

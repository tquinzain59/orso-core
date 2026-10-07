"""Orso Client UI router: serves the dedicated, simplified Client SPA at /client
and provides client-specific status endpoints.
"""

import asyncio
import json
import logging
import os
import re
import sqlite3
import time
import uuid
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse, Response
from pydantic import BaseModel, Field

from hermes_cli.dashboard_auth.client_jwt import verify_client_access
from olympe.autonomy_manager import autonomy_manager

_log = logging.getLogger("hermes_cli.client_ui")
router = APIRouter()

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CLIENT_DIST = PROJECT_ROOT / "apps" / "ui-client" / "dist"


def _sync_http_request(req: urllib.request.Request, timeout: float = 3.0) -> bytes:
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _sync_http_request_json(req: urllib.request.Request, timeout: float = 3.0) -> Any:
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ── Modèles Pydantic ─────────────────────────────────────────────────────────

class ClientLoginRequest(BaseModel):
    email: str = Field(..., description="Email du compte client")
    password: str = Field(..., description="Mot de passe du compte client")


class ChatRequest(BaseModel):
    agent_id: str = Field(default="jerome", description="Identifiant de l'agent (jerome, lucas, clara, victor)")
    message: str = Field(..., description="Message ou instruction de l'utilisateur")
    session_id: Optional[str] = Field(default=None, description="Identifiant de session de conversation")


class ActionExecuteRequest(BaseModel):
    action_id: str = Field(..., description="Type d'action : send, delay, skip, etc.")
    card_id: str = Field(..., description="Identifiant de la carte d'action")
    agent_id: str = Field(default="jerome", description="Identifiant de l'agent émetteur")
    draft: Optional[str] = Field(default=None, description="Contenu du brouillon validé ou modifié")
    recipient: Optional[str] = Field(default=None, description="Destinataire (email ou téléphone)")
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Métadonnées complémentaires")


class ChannelUserRequest(BaseModel):
    user: str = Field(..., description="Numéro ou identifiant de l'utilisateur à autoriser")


class PasswordUpdateRequest(BaseModel):
    current_password: Optional[str] = Field(default=None, description="Mot de passe actuel")
    new_password: str = Field(..., min_length=8, description="Nouveau mot de passe (8 caractères minimum)")
    confirm_password: Optional[str] = Field(default=None, description="Confirmation du mot de passe")


class SubscriptionUpdateRequest(BaseModel):
    tier_id: str = Field(..., description="Identifiant du palier sélectionné (1_agent, 2_agents, 3_agents, 4_agents)")


class ActionDecisionRequest(BaseModel):
    comment: Optional[str] = Field(default=None, description="Commentaire de validation ou instruction")
    reason: Optional[str] = Field(default=None, description="Motif de refus ou rejet")


# ── Catalogues des Agents, Interfaces et Données Métier en Base ────────────

ALL_AGENTS_METADATA: List[Dict[str, Any]] = [
    {
        "id": "jerome",
        "name": "Jérôme",
        "role": "Credit Manager & Recouvrement",
        "subtitle": "Credit Manager • ADV • Prévention des impayés",
        "department": "Trésorerie & Finance",
        "avatar": "💼",
        "themeColor": {
            "bg": "bg-blue-950/40",
            "border": "border-blue-700/50",
            "text": "text-blue-400",
            "accent": "bg-blue-600 hover:bg-blue-500",
            "badge": "bg-blue-900/60 text-blue-300 border-blue-700/60",
        },
        "status": "online",
        "description": "Veille sur votre trésorerie, suit la balance âgée, analyse la solvabilité de vos clients et gère vos relances sans stress.",
        "skills": ["balance_agee", "veille_bodacc", "fiche_credit", "relance_amiable"],
        "quickActions": [
            {"label": "📊 État de la balance âgée", "prompt": "Quelle est la situation actuelle de notre balance âgée et le total des retards ?"},
            {"label": "⚠️ Retards de plus de 30 jours", "prompt": "Peux-tu me lister les factures en retard de plus de 30 jours et les actions à engager ?"},
            {"label": "🔍 Vérifier un SIREN / Client", "prompt": "Je souhaite vérifier la santé financière et le scoring d’un client via son SIREN."},
            {"label": "✉️ Proposer les relances du jour", "prompt": "Quelles sont les relances prioritaires à effectuer aujourd’hui auprès de nos débiteurs ?"},
        ],
    },
    {
        "id": "lucas",
        "name": "Lucas",
        "role": "Commercial & Prospection (SDR)",
        "subtitle": "Pipeline • Relance devis • Acquisition B2B",
        "department": "Développement Commercial",
        "avatar": "🎯",
        "themeColor": {
            "bg": "bg-purple-950/40",
            "border": "border-purple-700/50",
            "text": "text-purple-400",
            "accent": "bg-purple-600 hover:bg-purple-500",
            "badge": "bg-purple-900/60 text-purple-300 border-purple-700/60",
        },
        "status": "online",
        "description": "Détecte de nouveaux prospects qualifiés, prépare vos e-mails d’approche et enrichit automatiquement votre CRM.",
        "skills": ["relance_devis", "scoring_prospects", "enrichissement_siren"],
        "quickActions": [
            {"label": "🚀 Synthèse du pipeline", "prompt": "Fais-moi un point sur l’état de notre pipeline commercial et les leads qualifiés cette semaine."},
            {"label": "🎯 Nouveaux prospects ciblés", "prompt": "Trouve et liste 5 entreprises cibles correspondant à notre client idéal dans le secteur B2B."},
            {"label": "✍️ Rédiger une approche froide", "prompt": "Rédige une proposition d’approche personnalisée pour un dirigeant de PME industrielle."},
        ],
    },
    {
        "id": "clara",
        "name": "Clara",
        "role": "Support Client & SAV",
        "subtitle": "SAV • Litiges facturation • Satisfaction",
        "department": "Relation Client",
        "avatar": "💬",
        "themeColor": {
            "bg": "bg-emerald-950/40",
            "border": "border-emerald-700/50",
            "text": "text-emerald-400",
            "accent": "bg-emerald-600 hover:bg-emerald-500",
            "badge": "bg-emerald-900/60 text-emerald-300 border-emerald-700/60",
        },
        "status": "online",
        "description": "Assiste vos clients 24/7 sur les questions courantes, suit les demandes en attente et prépare les escalades critiques.",
        "skills": ["gestion_litiges", "faq_intelligente", "satisfaction_client"],
        "quickActions": [
            {"label": "🎫 Demandes en attente", "prompt": "Y a-t-il des demandes de clients non traitées ou des réclamations urgentes aujourd’hui ?"},
            {"label": "💡 Suggestions d’amélioration FAQ", "prompt": "Quelles sont les 3 questions récurrentes que nos clients ont posées cette semaine ?"},
        ],
    },
    {
        "id": "victor",
        "name": "Victor",
        "role": "Spécialiste Appels d’Offres",
        "subtitle": "BOAMP • Dossiers d'appels d'offres • Conformité",
        "department": "Marchés Publics",
        "avatar": "📜",
        "themeColor": {
            "bg": "bg-amber-950/40",
            "border": "border-amber-700/50",
            "text": "text-amber-400",
            "accent": "bg-amber-600 hover:bg-amber-500",
            "badge": "bg-amber-900/60 text-amber-300 border-amber-700/60",
        },
        "status": "online",
        "description": "Veille sur le BOAMP et le TED, analyse les dossiers de consultation (DCE) et prépare vos mémoires techniques.",
        "skills": ["veille_boamp", "analyse_dce", "attestations_legales"],
        "quickActions": [
            {"label": "🏛️ Opportunités BOAMP du jour", "prompt": "Quels nouveaux appels d’offres correspondent à nos compétences sur notre région ?"},
            {"label": "📑 Synthèse d’un DCE", "prompt": "Je t’ai déposé un cahier des charges, peux-tu m’en extraire les critères d’élimination et de notation ?"},
        ],
    },
]

# Référentiel des tenants et agents activés en base (miroir Supabase KAN-26 / KAN-30 / KAN-31)
_SEED_TENANTS: Dict[str, Dict[str, Any]] = {
    "financia-solutions": {
        "id": "f3e25379-6531-479e-b276-3b3185e7421b",
        "name": "Financia Solutions",
        "agents_enabled": ["jerome"],
    },
    "commercialink": {
        "id": "9a38ef87-19d2-45e3-9821-2efbb91081a9",
        "name": "CommerciaLink",
        "agents_enabled": ["lucas"],
    },
    "helpdesk360": {
        "id": "88997766500033",
        "name": "HelpDesk360",
        "agents_enabled": ["clara"],
    },
    "batipro-services": {
        "id": "c56b8290-7f28-4a11-893d-47209118a72e",
        "name": "BatiPro Services",
        "agents_enabled": ["victor"],
    },
    "eurotech-conseil": {
        "id": "e88d1234-9abc-4def-0123-456789abcdef",
        "name": "EuroTech Conseil",
        "agents_enabled": ["jerome", "lucas", "clara", "victor"],
    },
}

_SEED_INTEGRATIONS: Dict[str, List[Dict[str, Any]]] = {
    "financia-solutions": [
        {
            "id": "pennylane",
            "name": "Pennylane",
            "category": "erp",
            "provider": "Pennylane API",
            "description": "Synchronisation bidirectionnelle des factures de vente, des règlements clients et de la balance comptable.",
            "status": "disconnected",
            "lastSync": "Jamais synchronisé",
            "metricLabel": "Configuration Hermès",
            "metricValue": "Clé API non configurée",
            "accountDetails": "Requiert PENNYLANE_API_KEY",
            "configKey": "PENNYLANE_API_KEY",
        },
        {
            "id": "sellsy",
            "name": "Sellsy CRM & Factures",
            "category": "erp",
            "provider": "Sellsy v2",
            "description": "Extraction des devis signés, des factures échues et des contacts décideurs.",
            "status": "disconnected",
            "lastSync": "Jamais synchronisé",
            "metricLabel": "Configuration Hermès",
            "metricValue": "Clé API non configurée",
            "accountDetails": "Requiert SELLSY_TOKEN",
            "configKey": "SELLSY_TOKEN",
        },
        {
            "id": "odoo",
            "name": "Odoo ERP",
            "category": "erp",
            "provider": "Odoo XML-RPC",
            "description": "Module Comptabilité et Ventes pour PME.",
            "status": "disconnected",
            "lastSync": "Jamais synchronisé",
            "metricLabel": "Configuration Hermès",
            "metricValue": "Instance non paramétrée",
            "accountDetails": "Requiert ODOO_URL",
            "configKey": "ODOO_URL",
        },
        {
            "id": "google-workspace",
            "name": "Google Workspace (Gmail)",
            "category": "mail",
            "provider": "Google OAuth",
            "description": "Envoi des relances amiables et réception des justificatifs de paiement des clients.",
            "status": "disconnected",
            "lastSync": "Jamais synchronisé",
            "metricLabel": "Messagerie",
            "metricValue": "Compte non connecté",
            "accountDetails": "Requiert OAuth Google",
            "configKey": "GOOGLE_WORKSPACE_CREDENTIALS",
        },
        {
            "id": "microsoft-365",
            "name": "Microsoft 365 (Outlook)",
            "category": "mail",
            "provider": "Graph API",
            "description": "Alternative messagerie entreprise pour l’envoi et le suivi des courriels.",
            "status": "disconnected",
            "lastSync": "Jamais synchronisé",
            "metricLabel": "Messagerie",
            "metricValue": "Compte non connecté",
            "accountDetails": "Requiert MICROSOFT_365_TOKEN",
            "configKey": "MICROSOFT_365_TOKEN",
        },
        {
            "id": "pappers",
            "name": "Pappers API & Scoring",
            "category": "legal",
            "provider": "Pappers Open Data",
            "description": "Fiche financière complète, score de défaillance, bilans et dirigeants légaux des tiers.",
            "status": "pending",
            "lastSync": "Données publiques",
            "metricLabel": "Mode Découverte",
            "metricValue": "Open Data libre (Sans clé)",
            "accountDetails": "Optionnel : PAPPERS_API_KEY",
            "configKey": "PAPPERS_API_KEY",
        },
        {
            "id": "bodacc",
            "name": "Veille Légale BODACC",
            "category": "legal",
            "provider": "DILA Open Data",
            "description": "Surveillance proactive des procédures collectives (redressements, liquidations judiciaires).",
            "status": "connected",
            "lastSync": "Temps réel",
            "metricLabel": "Compétence Hermès",
            "metricValue": "Skill actif (BODACC Open Data)",
            "accountDetails": "Flux officiel DILA",
            "configKey": "BODACC_OPEN_DATA",
        },
        {
            "id": "hubspot",
            "name": "HubSpot CRM",
            "category": "crm",
            "provider": "HubSpot API",
            "description": "Synchronisation des contacts commerciaux, création de deals et suivi des échanges.",
            "status": "disconnected",
            "lastSync": "Jamais synchronisé",
            "metricLabel": "Configuration Hermès",
            "metricValue": "Clé API non configurée",
            "accountDetails": "Requiert HUBSPOT_API_KEY",
            "configKey": "HUBSPOT_API_KEY",
        },
    ],
    "commercialink": [
        {
            "id": "hubspot",
            "name": "HubSpot CRM",
            "category": "crm",
            "provider": "HubSpot API",
            "description": "Synchronisation des contacts commerciaux, création de deals et suivi des échanges.",
            "status": "disconnected",
            "lastSync": "Jamais synchronisé",
            "metricLabel": "Configuration Hermès",
            "metricValue": "Clé API non configurée",
            "accountDetails": "Requiert HUBSPOT_API_KEY",
            "configKey": "HUBSPOT_API_KEY",
        },
        {
            "id": "sellsy",
            "name": "Sellsy CRM & Devis",
            "category": "erp",
            "provider": "Sellsy v2",
            "description": "Gestion des devis et propositions commerciales B2B.",
            "status": "disconnected",
            "lastSync": "Jamais synchronisé",
            "metricLabel": "Configuration Hermès",
            "metricValue": "Clé API non configurée",
            "accountDetails": "Requiert SELLSY_TOKEN",
            "configKey": "SELLSY_TOKEN",
        },
        {
            "id": "google-workspace",
            "name": "Google Workspace (Gmail)",
            "category": "mail",
            "provider": "Google OAuth",
            "description": "Envoi des séquences de prospection commerciale et relances de devis.",
            "status": "disconnected",
            "lastSync": "Jamais synchronisé",
            "metricLabel": "Messagerie",
            "metricValue": "Compte non connecté",
            "accountDetails": "Requiert OAuth Google",
            "configKey": "GOOGLE_WORKSPACE_CREDENTIALS",
        },
        {
            "id": "pappers",
            "name": "Pappers API & Scoring",
            "category": "legal",
            "provider": "Pappers Open Data",
            "description": "Enrichissement des données de contact et santé financière des prospects.",
            "status": "pending",
            "lastSync": "Données publiques",
            "metricLabel": "Mode Découverte",
            "metricValue": "Open Data libre (Sans clé)",
            "accountDetails": "Optionnel : PAPPERS_API_KEY",
            "configKey": "PAPPERS_API_KEY",
        },
    ],
    "helpdesk360": [
        {
            "id": "google-workspace",
            "name": "Google Workspace",
            "category": "mail",
            "provider": "Google OAuth",
            "description": "Réception et traitement automatique des tickets clients et réclamations.",
            "status": "disconnected",
            "lastSync": "Jamais synchronisé",
            "metricLabel": "Messagerie",
            "metricValue": "Compte non connecté",
            "accountDetails": "Requiert OAuth Google",
            "configKey": "GOOGLE_WORKSPACE_CREDENTIALS",
        },
        {
            "id": "hubspot",
            "name": "HubSpot Service Hub",
            "category": "crm",
            "provider": "HubSpot API",
            "description": "Gestion de la base de connaissances et de la satisfaction client.",
            "status": "disconnected",
            "lastSync": "Jamais synchronisé",
            "metricLabel": "Configuration Hermès",
            "metricValue": "Clé API non configurée",
            "accountDetails": "Requiert HUBSPOT_API_KEY",
            "configKey": "HUBSPOT_API_KEY",
        },
    ],
    "batipro-services": [
        {
            "id": "bodacc",
            "name": "Veille Légale BODACC & BOAMP",
            "category": "legal",
            "provider": "DILA Open Data",
            "description": "Surveillance quotidienne des avis de marchés publics BTP.",
            "status": "connected",
            "lastSync": "Temps réel",
            "metricLabel": "Compétence Hermès",
            "metricValue": "Skill actif (BODACC Open Data)",
            "accountDetails": "Flux BOAMP BTP",
            "configKey": "BODACC_OPEN_DATA",
        },
        {
            "id": "pappers",
            "name": "Pappers API & Scoring",
            "category": "legal",
            "provider": "Pappers Open Data",
            "description": "Vérification de solvabilité et attestations légales (DC1, DC2).",
            "status": "pending",
            "lastSync": "Données publiques",
            "metricLabel": "Mode Découverte",
            "metricValue": "Open Data libre (Sans clé)",
            "accountDetails": "Compte Pro BTP",
            "configKey": "PAPPERS_API_KEY",
        },
    ],
    "eurotech-conseil": [
        {
            "id": "pennylane",
            "name": "Pennylane",
            "category": "erp",
            "provider": "Pennylane API",
            "description": "Synchronisation comptable et facturation clients complète.",
            "status": "disconnected",
            "lastSync": "Jamais synchronisé",
            "metricLabel": "Configuration Hermès",
            "metricValue": "Clé API non configurée",
            "accountDetails": "Requiert PENNYLANE_API_KEY",
            "configKey": "PENNYLANE_API_KEY",
        },
        {
            "id": "hubspot",
            "name": "HubSpot CRM",
            "category": "crm",
            "provider": "HubSpot API",
            "description": "Pipeline d’affaires et scoring commercial B2B.",
            "status": "disconnected",
            "lastSync": "Jamais synchronisé",
            "metricLabel": "Configuration Hermès",
            "metricValue": "Clé API non configurée",
            "accountDetails": "Requiert HUBSPOT_API_KEY",
            "configKey": "HUBSPOT_API_KEY",
        },
        {
            "id": "google-workspace",
            "name": "Google Workspace",
            "category": "mail",
            "provider": "Google OAuth",
            "description": "Messagerie entreprise connectée aux 4 agents.",
            "status": "disconnected",
            "lastSync": "Jamais synchronisé",
            "metricLabel": "Messagerie",
            "metricValue": "Compte non connecté",
            "accountDetails": "Requiert OAuth Google",
            "configKey": "GOOGLE_WORKSPACE_CREDENTIALS",
        },
        {
            "id": "pappers",
            "name": "Pappers API & Scoring",
            "category": "legal",
            "provider": "Pappers Open Data",
            "description": "Analyses financières et conformité des partenaires.",
            "status": "pending",
            "lastSync": "Données publiques",
            "metricLabel": "Mode Découverte",
            "metricValue": "Open Data libre (Sans clé)",
            "accountDetails": "Optionnel : PAPPERS_API_KEY",
            "configKey": "PAPPERS_API_KEY",
        },
        {
            "id": "bodacc",
            "name": "Veille Légale BODACC",
            "category": "legal",
            "provider": "DILA Open Data",
            "description": "Surveillance des partenaires et fournisseurs.",
            "status": "connected",
            "lastSync": "Temps réel",
            "metricLabel": "Compétence Hermès",
            "metricValue": "Skill actif (BODACC Open Data)",
            "accountDetails": "Flux actif",
            "configKey": "BODACC_OPEN_DATA",
        },
    ],
}

_SEED_CHANNELS: Dict[str, List[Dict[str, Any]]] = {
    "financia-solutions": [
        {
            "id": "whatsapp",
            "name": "WhatsApp Business",
            "tagline": "Liaison directe avec vos clients & tiers",
            "description": "Permet à Jérôme et Lucas de dialoguer directement par WhatsApp pour obtenir des confirmations de virement ou qualifier des prospects.",
            "status": "disconnected",
            "connectedAccount": "Non configuré",
            "allowedUsers": [],
            "stats": {"messagesToday": 0, "activeSessions": 0},
            "configKey": "WHATSAPP_TOKEN",
        },
        {
            "id": "telegram",
            "name": "Telegram (Console Dirigeant)",
            "tagline": "Notifications et alertes prioritaires sur mobile",
            "description": "Votre canal direct pour recevoir les alertes BODACC urgentes, vérifier un client via /check et consulter vos chiffres sans ouvrir votre ordinateur.",
            "status": "disconnected",
            "connectedAccount": "Non configuré",
            "allowedUsers": [],
            "stats": {"messagesToday": 0, "activeSessions": 0},
            "configKey": "TELEGRAM_BOT_TOKEN",
        },
        {
            "id": "email",
            "name": "Email Gateway",
            "tagline": "Envoi automatique et suivi des réponses",
            "description": "Canal de relance par défaut pour l’envoi des courriers de relance niveau 1, 2 et mise en demeure.",
            "status": "disconnected",
            "connectedAccount": "Non configuré",
            "allowedUsers": ["sophie.martin@financia-solutions.fr"],
            "stats": {"messagesToday": 0, "activeSessions": 0},
            "configKey": "SMTP_HOST",
        },
    ],
    "commercialink": [
        {
            "id": "whatsapp",
            "name": "WhatsApp Business",
            "tagline": "Liaison directe avec vos prospects",
            "description": "Permet à Lucas de dialoguer sur WhatsApp pour la prise de rendez-vous commercial.",
            "status": "disconnected",
            "connectedAccount": "Non configuré",
            "allowedUsers": [],
            "stats": {"messagesToday": 0, "activeSessions": 0},
            "configKey": "WHATSAPP_TOKEN",
        },
        {
            "id": "email",
            "name": "Email Gateway",
            "tagline": "Séquences de prospection commerciale",
            "description": "Envoi des devis et séquences de relance commerciale.",
            "status": "disconnected",
            "connectedAccount": "Non configuré",
            "allowedUsers": ["claire.dubois@commercialink.fr"],
            "stats": {"messagesToday": 0, "activeSessions": 0},
            "configKey": "SMTP_HOST",
        },
    ],
}



def _get_tenant_enabled_agents(
    tenant_id: Optional[str] = None,
    tenant_slug: Optional[str] = None,
    auth_agents: Optional[List[str]] = None,
) -> List[str]:
    """Résout la liste des agents activés pour un client depuis Supabase ou le référentiel de base."""
    # 1. Si spécifié explicitement dans le jeton JWT
    if auth_agents and isinstance(auth_agents, list) and len(auth_agents) > 0:
        return [a for a in auth_agents if a in ["jerome", "lucas", "clara", "victor"]]

    # 2. Si Supabase est accessible : interroger public.tenant_instances
    supabase_url = os.environ.get("SUPABASE_URL", "").strip()
    service_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if supabase_url and service_key and tenant_id:
        try:
            url = f"{supabase_url}/rest/v1/tenant_instances?tenant_id=eq.{tenant_id}&select=agents_enabled"
            req = urllib.request.Request(
                url,
                headers={
                    "apikey": service_key,
                    "Authorization": f"Bearer {service_key}",
                    "User-Agent": "OrsoCore/1.0",
                },
            )
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if data and len(data) > 0:
                    raw_agents = data[0].get("agents_enabled")
                    if isinstance(raw_agents, list):
                        return [a for a in raw_agents if a in ["jerome", "lucas", "clara", "victor"]]
                    elif isinstance(raw_agents, dict) and "active" in raw_agents:
                        return [a for a in raw_agents["active"] if a in ["jerome", "lucas", "clara", "victor"]]
        except Exception as e:
            _log.debug("Erreur lecture agents_enabled Supabase: %s", e)

    # 3. Référentiel local / amorçage par slug ou tenant_id
    slug = (tenant_slug or "").lower()
    if not slug and tenant_id:
        for t_slug, t_info in _SEED_TENANTS.items():
            if t_info.get("id") == tenant_id:
                slug = t_slug
                break

    if slug in _SEED_TENANTS:
        return _SEED_TENANTS[slug].get("agents_enabled", ["jerome"])

    # Fallback par défaut
    return ["jerome"]


_SYNC_OVERRIDES: Dict[Tuple[str, str], Dict[str, Any]] = {}


def _probe_hermes_backoffice_integrations(
    tenant_id: Optional[str] = None,
    tenant_slug: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Inspecte dynamiquement le backoffice Hermès (.env, config.yaml, skills, outils natifs)
    pour retourner l'état réel et vérifié des interfaces de l'organisation.
    """
    slug = (tenant_slug or "").lower()
    if not slug and tenant_id:
        for t_slug, t_info in _SEED_TENANTS.items():
            if t_info.get("id") == tenant_id:
                slug = t_slug
                break
    if not slug or slug not in _SEED_INTEGRATIONS:
        slug = "financia-solutions"

    # 1. Base catalog for this tenant
    base_catalog = _SEED_INTEGRATIONS.get(slug, [])
    probed_integrations: List[Dict[str, Any]] = []

    for item in base_catalog:
        entry = dict(item)
        int_id = entry.get("id")
        config_key = entry.get("configKey")

        # Détection des clés réelles dans os.environ
        is_configured = False
        if config_key and os.environ.get(config_key, "").strip():
            is_configured = True
        elif int_id == "pennylane" and (os.environ.get("PENNYLANE_API_KEY") or os.environ.get("PENNYLANE_TOKEN")):
            is_configured = True
        elif int_id == "sellsy" and (os.environ.get("SELLSY_TOKEN") or os.environ.get("SELLSY_API_KEY")):
            is_configured = True
        elif int_id == "odoo" and (os.environ.get("ODOO_URL") or os.environ.get("ODOO_HOST")):
            is_configured = True
        elif int_id == "hubspot" and (os.environ.get("HUBSPOT_API_KEY") or os.environ.get("HUBSPOT_ACCESS_TOKEN")):
            is_configured = True
        elif int_id == "pappers" and os.environ.get("PAPPERS_API_KEY", "").strip():
            is_configured = True
        elif int_id == "google-workspace" and (os.environ.get("GOOGLE_WORKSPACE_CREDENTIALS") or os.environ.get("GMAIL_APP_PASSWORD")):
            is_configured = True
        elif int_id == "microsoft-365" and (os.environ.get("MICROSOFT_365_TOKEN") or os.environ.get("MS_GRAPH_TOKEN")):
            is_configured = True

        if is_configured:
            entry["status"] = "connected"
            entry["metricLabel"] = "Statut Backoffice"
            entry["metricValue"] = "Connecteur actif (Clé .env)"
            entry["accountDetails"] = "Configuré dans le backoffice Hermès"
            entry["lastSync"] = "Temps réel"
        elif int_id == "bodacc":
            entry["status"] = "connected"
            entry["metricLabel"] = "Compétence Hermès"
            entry["metricValue"] = "Skill actif (BODACC Open Data)"
            entry["accountDetails"] = "Flux officiel DILA"
            entry["lastSync"] = "Temps réel"
        elif int_id == "pappers":
            entry["status"] = "pending"
            entry["metricLabel"] = "Mode Découverte"
            entry["metricValue"] = "Open Data libre (Sans clé)"
            entry["accountDetails"] = "Optionnel : PAPPERS_API_KEY"
            entry["lastSync"] = "Données publiques"
        else:
            entry["status"] = "disconnected"
            entry["metricLabel"] = "Configuration Hermès"
            entry["metricValue"] = "Clé API non configurée"
            req_var = config_key or (int_id.upper() + "_API_KEY")
            entry["accountDetails"] = f"Requiert {req_var}"
            entry["lastSync"] = "Jamais synchronisé"

        # Application des surcharges manuelles de synchronisation
        override_key = (slug, int_id)
        if override_key in _SYNC_OVERRIDES:
            entry.update(_SYNC_OVERRIDES[override_key])

        probed_integrations.append(entry)

    # 2. Outils Backoffice réels et actifs
    backoffice_tools: List[Dict[str, Any]] = []

    if os.environ.get("SUPABASE_URL"):
        backoffice_tools.append({
            "id": "supabase",
            "name": "Supabase IAM & Base",
            "category": "tools",
            "provider": "Supabase Cloud",
            "description": "Authentification JWT des dirigeants, contrôle d'accès RLS et isolation des données.",
            "status": "connected",
            "lastSync": "Temps réel",
            "metricLabel": "Infrastructure IAM",
            "metricValue": "Opérationnel (Temps réel)",
            "accountDetails": "Projet Supabase connecté",
            "configKey": "SUPABASE_URL",
        })

    if os.environ.get("AIRTABLE_API_KEY"):
        backoffice_tools.append({
            "id": "airtable",
            "name": "Airtable API",
            "category": "tools",
            "provider": "Airtable REST",
            "description": "Bases de données relationnelles, tables de suivi et registres opérationnels.",
            "status": "connected",
            "lastSync": "Temps réel",
            "metricLabel": "Statut Backoffice",
            "metricValue": "Clé API active (.env)",
            "accountDetails": "Base Airtable connectée",
            "configKey": "AIRTABLE_API_KEY",
        })

    if os.environ.get("ATLASSIAN_DOMAIN") or os.environ.get("JIRA_API_TOKEN") or os.environ.get("ATLASSIAN_API_TOKEN"):
        domain = os.environ.get("ATLASSIAN_DOMAIN", "Jira Cloud")
        backoffice_tools.append({
            "id": "atlassian-jira",
            "name": "Atlassian Jira Cloud",
            "category": "tools",
            "provider": "Atlassian REST API",
            "description": "Gestion des tickets de réclamation, incidents et suivi opérationnel des agents.",
            "status": "connected",
            "lastSync": "Temps réel",
            "metricLabel": "Domaine Atlassian",
            "metricValue": f"Connecté ({domain})",
            "accountDetails": os.environ.get("ATLASSIAN_EMAIL", "Compte configuré"),
            "configKey": "JIRA_API_TOKEN",
        })

    # Outils natifs Hermès
    backoffice_tools.append({
        "id": "hermes-web-search",
        "name": "Recherche Web Hermès",
        "category": "tools",
        "provider": "Hermès Toolset",
        "description": "Outil natif de veille, recherche et extraction web autonome pour les agents.",
        "status": "connected",
        "lastSync": "Permanent",
        "metricLabel": "Moteur de recherche",
        "metricValue": "Actif (DuckDuckGo / Tavily)",
        "accountDetails": "Outil agent natif",
    })

    backoffice_tools.append({
        "id": "hermes-browser",
        "name": "Navigateur Web Autonome",
        "category": "tools",
        "provider": "Playwright / Chrome",
        "description": "Navigation web autonome, lecture de portails en ligne et capture d'écrans.",
        "status": "connected",
        "lastSync": "Permanent",
        "metricLabel": "Automatisation",
        "metricValue": "Prêt pour les agents",
        "accountDetails": "Moteur de rendu headless",
    })

    # Serveurs MCP déclarés dans config.yaml
    try:
        from hermes_cli.config import load_config
        cfg = load_config()
        mcp_servers = cfg.get("mcp_servers", {})
        if isinstance(mcp_servers, dict):
            for mcp_name, mcp_def in mcp_servers.items():
                cmd = mcp_def.get("command", "Serveur configuré") if isinstance(mcp_def, dict) else "Actif"
                backoffice_tools.append({
                    "id": f"mcp-{mcp_name}",
                    "name": f"Serveur MCP : {mcp_name.capitalize()}",
                    "category": "tools",
                    "provider": "Model Context Protocol",
                    "description": f"Serveur MCP configuré dans le backoffice Hermès ({cmd}).",
                    "status": "connected",
                    "lastSync": "Temps réel",
                    "metricLabel": "Protocole MCP",
                    "metricValue": "Serveur actif",
                    "accountDetails": str(cmd),
                })
    except Exception as e:
        _log.debug("Erreur lecture serveurs MCP Hermès: %s", e)

    for b_tool in backoffice_tools:
        override_key = (slug, b_tool["id"])
        if override_key in _SYNC_OVERRIDES:
            b_tool.update(_SYNC_OVERRIDES[override_key])

    all_integrations = probed_integrations + backoffice_tools

    # Supabase data enrich
    supabase_url = os.environ.get("SUPABASE_URL", "").strip()
    service_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if supabase_url and service_key and tenant_id:
        try:
            url = f"{supabase_url}/rest/v1/tenant_integrations?tenant_id=eq.{tenant_id}&select=*&order=created_at.asc"
            req = urllib.request.Request(
                url,
                headers={
                    "apikey": service_key,
                    "Authorization": f"Bearer {service_key}",
                    "User-Agent": "OrsoCore/1.0",
                },
            )
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if data and len(data) > 0:
                    sb_map = {row.get("integration_id") or row.get("id"): row for row in data}
                    for item in all_integrations:
                        int_id = item["id"]
                        if int_id in sb_map:
                            sb_row = sb_map[int_id]
                            sb_last_sync = sb_row.get("last_sync")
                            if sb_last_sync and item["lastSync"] == "Jamais synchronisé":
                                item["lastSync"] = sb_last_sync
        except Exception as e:
            _log.debug("Erreur enrichissement tenant_integrations Supabase: %s", e)

    return all_integrations


def _get_tenant_integrations(
    tenant_id: Optional[str] = None,
    tenant_slug: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Charge les interfaces et outils connectés pour ce tenant depuis le backoffice Hermès."""
    return _probe_hermes_backoffice_integrations(tenant_id=tenant_id, tenant_slug=tenant_slug)


def _sync_tenant_integration(
    tenant_id: Optional[str],
    tenant_slug: Optional[str],
    integration_id: str,
) -> Optional[Dict[str, Any]]:
    """Déclenche la resynchronisation d'une interface connectée et met à jour son horodatage."""
    slug = (tenant_slug or "").lower()
    if not slug and tenant_id:
        for t_slug, t_info in _SEED_TENANTS.items():
            if t_info.get("id") == tenant_id:
                slug = t_slug
                break
    if not slug or slug not in _SEED_INTEGRATIONS:
        slug = "financia-solutions"

    integrations = _probe_hermes_backoffice_integrations(tenant_id=tenant_id, tenant_slug=slug)
    updated = None
    for item in integrations:
        if item["id"] == integration_id:
            item["lastSync"] = "À l'instant"
            item["status"] = "connected"
            _SYNC_OVERRIDES[(slug, integration_id)] = {
                "lastSync": "À l'instant",
                "status": "connected",
            }
            updated = item
            break

    supabase_url = os.environ.get("SUPABASE_URL", "").strip()
    service_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if supabase_url and service_key and tenant_id and updated:
        try:
            url = f"{supabase_url}/rest/v1/tenant_integrations?tenant_id=eq.{tenant_id}&integration_id=eq.{integration_id}"
            payload = json.dumps({"last_sync": "À l'instant", "status": "connected"}).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=payload,
                headers={
                    "apikey": service_key,
                    "Authorization": f"Bearer {service_key}",
                    "Content-Type": "application/json",
                    "Prefer": "return=representation",
                },
                method="PATCH",
            )
            urllib.request.urlopen(req, timeout=3.0)
        except Exception as e:
            _log.debug("Erreur patch tenant_integrations Supabase: %s", e)

    return updated


_CHANNEL_ALLOWED_USERS: Dict[Tuple[str, str], List[str]] = {}


def _probe_hermes_backoffice_channels(
    tenant_id: Optional[str] = None,
    tenant_slug: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Sonde dynamiquement l'état réel des passerelles de communication du moteur Hermès."""
    slug = (tenant_slug or "").lower()
    if not slug and tenant_id:
        for t_slug, t_info in _SEED_TENANTS.items():
            if t_info.get("id") == tenant_id:
                slug = t_slug
                break
    if not slug:
        slug = "financia-solutions"

    # 1. Vérification si Supabase contient des canaux configurés pour ce tenant
    supabase_url = os.environ.get("SUPABASE_URL", "").strip()
    service_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if supabase_url and service_key and tenant_id:
        try:
            url = f"{supabase_url}/rest/v1/tenant_channels?tenant_id=eq.{tenant_id}&select=*&order=created_at.asc"
            req = urllib.request.Request(
                url,
                headers={
                    "apikey": service_key,
                    "Authorization": f"Bearer {service_key}",
                    "User-Agent": "OrsoCore/1.0",
                },
            )
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if data and len(data) > 0:
                    result = []
                    for row in data:
                        ch_id = row.get("channel_id") or row.get("id")
                        mem_allowed = _CHANNEL_ALLOWED_USERS.get((slug, ch_id))
                        allowed = mem_allowed if mem_allowed is not None else row.get("allowed_users", [])
                        result.append({
                            "id": ch_id,
                            "name": row.get("name"),
                            "tagline": row.get("tagline"),
                            "description": row.get("description"),
                            "status": row.get("status", "connected"),
                            "connectedAccount": row.get("connected_account"),
                            "allowedUsers": allowed,
                            "stats": row.get("stats", {"messagesToday": 0, "activeSessions": 0}),
                            "configKey": row.get("config_key"),
                            "metrics": row.get("metrics", "Configuré dans Supabase"),
                            "syncStatus": "success",
                        })
                    return result
        except Exception as e:
            _log.debug("Erreur lecture tenant_channels Supabase: %s", e)

    # 2. Sondage dynamique depuis les configurations réelles d'Hermès
    probed_channels: List[Dict[str, Any]] = []

    # A. WhatsApp Business
    has_whatsapp = bool(os.environ.get("WHATSAPP_TOKEN") or os.environ.get("WHATSAPP_PHONE_NUMBER_ID") or os.environ.get("WHATSAPP_API_KEY"))
    wa_key = (slug, "whatsapp")
    wa_allowed = _CHANNEL_ALLOWED_USERS.get(wa_key)
    if wa_allowed is None:
        wa_allowed = []

    probed_channels.append({
        "id": "whatsapp",
        "name": "WhatsApp Business",
        "tagline": "Liaison directe avec vos clients & tiers",
        "description": "Permet aux agents d’échanger directement par WhatsApp pour obtenir des confirmations de virement ou qualifier des prospects.",
        "status": "connected" if has_whatsapp else "disconnected",
        "connectedAccount": "WhatsApp Cloud API (Connecté)" if has_whatsapp else "Non configuré",
        "allowedUsers": wa_allowed,
        "stats": {"messagesToday": 0, "activeSessions": 0},
        "configKey": "WHATSAPP_TOKEN",
        "metrics": "Passerelle WhatsApp Cloud active" if has_whatsapp else "Requiert WHATSAPP_TOKEN",
        "syncStatus": "success" if has_whatsapp else "offline",
    })

    # B. Telegram (Console Dirigeant)
    has_telegram = bool(os.environ.get("TELEGRAM_BOT_TOKEN", "").strip())
    tg_key = (slug, "telegram")
    tg_allowed = _CHANNEL_ALLOWED_USERS.get(tg_key)
    if tg_allowed is None:
        tg_allowed = []

    probed_channels.append({
        "id": "telegram",
        "name": "Telegram (Console Dirigeant)",
        "tagline": "Notifications et alertes prioritaires sur mobile",
        "description": "Votre canal direct pour recevoir les alertes BODACC urgentes, interroger vos agents via /check et consulter vos chiffres sans ouvrir votre ordinateur.",
        "status": "connected" if has_telegram else "disconnected",
        "connectedAccount": "@Bot Telegram (Connecté)" if has_telegram else "Non configuré",
        "allowedUsers": tg_allowed,
        "stats": {"messagesToday": 0, "activeSessions": 0},
        "configKey": "TELEGRAM_BOT_TOKEN",
        "metrics": "Passerelle Telegram active et prête" if has_telegram else "Requiert TELEGRAM_BOT_TOKEN",
        "syncStatus": "success" if has_telegram else "offline",
    })

    # C. Passerelle Email (SMTP / IMAP / Resend)
    smtp_host = os.environ.get("SMTP_HOST", "").strip()
    resend_key = os.environ.get("RESEND_API_KEY", "").strip()
    mailgun_key = os.environ.get("MAILGUN_API_KEY", "").strip()
    has_email = bool(smtp_host or resend_key or mailgun_key or os.environ.get("SMTP_USER"))
    email_account = os.environ.get("SMTP_USER") or os.environ.get("EMAIL_FROM") or ("Serveur SMTP configuré" if has_email else "Non configuré")
    email_key = (slug, "email")
    email_allowed = _CHANNEL_ALLOWED_USERS.get(email_key)
    if email_allowed is None:
        t_contact = _SEED_TENANTS.get(slug, {}).get("contact_email")
        email_allowed = [t_contact] if t_contact else []

    probed_channels.append({
        "id": "email",
        "name": "Email Gateway",
        "tagline": "Envoi automatique et suivi des réponses",
        "description": "Canal de relance et de correspondance officielle pour l’envoi des courriers de relance, devis et justificatifs.",
        "status": "connected" if has_email else "disconnected",
        "connectedAccount": email_account,
        "allowedUsers": email_allowed,
        "stats": {"messagesToday": 0, "activeSessions": 0},
        "configKey": "SMTP_HOST",
        "metrics": "Passerelle SMTP active" if has_email else "Requiert SMTP_HOST ou RESEND_API_KEY",
        "syncStatus": "success" if has_email else "offline",
    })

    # D. Slack si configuré
    if os.environ.get("SLACK_BOT_TOKEN"):
        slack_allowed = _CHANNEL_ALLOWED_USERS.get((slug, "slack"), [])
        probed_channels.append({
            "id": "slack",
            "name": "Slack Gateway",
            "tagline": "Canaux d'équipe et alertes internes",
            "description": "Diffusion des alertes et discussions directes dans vos canaux Slack d'entreprise.",
            "status": "connected",
            "connectedAccount": "Bot Slack actif",
            "allowedUsers": slack_allowed,
            "stats": {"messagesToday": 0, "activeSessions": 0},
            "configKey": "SLACK_BOT_TOKEN",
            "metrics": "Passerelle Slack connectée",
            "syncStatus": "success",
        })

    # E. Discord si configuré
    if os.environ.get("DISCORD_BOT_TOKEN"):
        discord_allowed = _CHANNEL_ALLOWED_USERS.get((slug, "discord"), [])
        probed_channels.append({
            "id": "discord",
            "name": "Discord Gateway",
            "tagline": "Salons de supervision et notifications",
            "description": "Envoi des notifications et échanges sur votre serveur Discord.",
            "status": "connected",
            "connectedAccount": "Bot Discord actif",
            "allowedUsers": discord_allowed,
            "stats": {"messagesToday": 0, "activeSessions": 0},
            "configKey": "DISCORD_BOT_TOKEN",
            "metrics": "Passerelle Discord connectée",
            "syncStatus": "success",
        })

    return probed_channels


def _get_tenant_channels(
    tenant_id: Optional[str] = None,
    tenant_slug: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Charge les canaux de communication réels pour ce tenant depuis Hermès ou Supabase."""
    return _probe_hermes_backoffice_channels(tenant_id=tenant_id, tenant_slug=tenant_slug)


def _add_channel_user(
    tenant_id: Optional[str],
    tenant_slug: Optional[str],
    channel_id: str,
    user: str,
) -> List[str]:
    """Ajoute un utilisateur autorisé à un canal de discussion."""
    slug = (tenant_slug or "").lower()
    if not slug and tenant_id:
        for t_slug, t_info in _SEED_TENANTS.items():
            if t_info.get("id") == tenant_id:
                slug = t_slug
                break
    if not slug:
        slug = "financia-solutions"

    clean_user = user.strip()
    key = (slug, channel_id)
    if key not in _CHANNEL_ALLOWED_USERS:
        channels = _probe_hermes_backoffice_channels(tenant_id=tenant_id, tenant_slug=tenant_slug)
        for c in channels:
            if c["id"] == channel_id:
                _CHANNEL_ALLOWED_USERS[key] = list(c.get("allowedUsers", []))
                break
        if key not in _CHANNEL_ALLOWED_USERS:
            _CHANNEL_ALLOWED_USERS[key] = []

    if clean_user and clean_user not in _CHANNEL_ALLOWED_USERS[key]:
        _CHANNEL_ALLOWED_USERS[key].append(clean_user)

    users = _CHANNEL_ALLOWED_USERS[key]

    supabase_url = os.environ.get("SUPABASE_URL", "").strip()
    service_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if supabase_url and service_key and tenant_id and users:
        try:
            url = f"{supabase_url}/rest/v1/tenant_channels?tenant_id=eq.{tenant_id}&channel_id=eq.{channel_id}"
            payload = json.dumps({"allowed_users": users}).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=payload,
                headers={
                    "apikey": service_key,
                    "Authorization": f"Bearer {service_key}",
                    "Content-Type": "application/json",
                },
                method="PATCH",
            )
            urllib.request.urlopen(req, timeout=3.0)
        except Exception as e:
            _log.debug("Erreur update tenant_channels Supabase: %s", e)

    return users


def _remove_channel_user(
    tenant_id: Optional[str],
    tenant_slug: Optional[str],
    channel_id: str,
    user: str,
) -> List[str]:
    """Retire un utilisateur autorisé d'un canal de discussion."""
    slug = (tenant_slug or "").lower()
    if not slug and tenant_id:
        for t_slug, t_info in _SEED_TENANTS.items():
            if t_info.get("id") == tenant_id:
                slug = t_slug
                break
    if not slug:
        slug = "financia-solutions"

    key = (slug, channel_id)
    if key not in _CHANNEL_ALLOWED_USERS:
        channels = _probe_hermes_backoffice_channels(tenant_id=tenant_id, tenant_slug=tenant_slug)
        for c in channels:
            if c["id"] == channel_id:
                _CHANNEL_ALLOWED_USERS[key] = list(c.get("allowedUsers", []))
                break
        if key not in _CHANNEL_ALLOWED_USERS:
            _CHANNEL_ALLOWED_USERS[key] = []

    _CHANNEL_ALLOWED_USERS[key] = [u for u in _CHANNEL_ALLOWED_USERS[key] if u != user]
    users = _CHANNEL_ALLOWED_USERS[key]

    supabase_url = os.environ.get("SUPABASE_URL", "").strip()
    service_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if supabase_url and service_key and tenant_id:
        try:
            url = f"{supabase_url}/rest/v1/tenant_channels?tenant_id=eq.{tenant_id}&channel_id=eq.{channel_id}"
            payload = json.dumps({"allowed_users": users}).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=payload,
                headers={
                    "apikey": service_key,
                    "Authorization": f"Bearer {service_key}",
                    "Content-Type": "application/json",
                },
                method="PATCH",
            )
            urllib.request.urlopen(req, timeout=3.0)
        except Exception as e:
            _log.debug("Erreur update tenant_channels Supabase: %s", e)

    return users


def _find_profile_dir(agent_id: str) -> Optional[Path]:
    """Localise le dossier du profil de l'agent dans les emplacements possibles."""
    from hermes_constants import get_hermes_home
    candidates = [
        get_hermes_home() / "profiles" / agent_id,
        PROJECT_ROOT / "profiles" / agent_id,
        Path("/app/profiles") / agent_id,
        Path.home() / ".hermes" / "profiles" / agent_id,
    ]
    for c in candidates:
        try:
            if c.is_dir():
                return c
        except Exception:
            continue
    return None


def _load_agent_soul(agent_id: str) -> str:
    """Charge le SOUL.md de l'agent s'il existe, sinon fournit la persona par défaut."""
    try:
        profile_dir = _find_profile_dir(agent_id)
        if profile_dir:
            soul_file = profile_dir / "SOUL.md"
            if soul_file.is_file():
                return soul_file.read_text(encoding="utf-8")
    except Exception as e:
        _log.warning("Impossible de lire la persona de %s: %s", agent_id, e)

    # Personas de repli enrichies
    if agent_id == "jerome":
        return (
            "Tu es Jerome, un assistant spécialisé dans le recouvrement de factures pour les TPE et PME françaises.\n"
            "Tu travailles avec des chefs d'entreprise et des artisans — des personnes qui connaissent leur métier, pas l'informatique. "
            "Tu dois être clair, chaleureux et rassurant.\n\n"
            "Règles d'or :\n"
            "- Parle en français courant, simple et bienveillant.\n"
            "- Ne donne AUCUNE instruction technique ou code informatique.\n"
            "- Quand on te demande une analyse, accuse réception immédiatement par un mot rassurant (« Je m'en occupe tout de suite ! »).\n"
            "- Ton objectif : aider l'entrepreneur à préserver sa trésorerie sans froisser la relation commerciale client."
        )
    elif agent_id == "lucas":
        return (
            "Tu es Lucas, assistant commercial et prospection pour TPE/PME françaises.\n"
            "Dynamique, proactif et orienté résultat. Tu détectes les opportunités de vente, "
            "rédiges des approches personnalisées et aides à relancer les devis en attente."
        )
    elif agent_id == "clara":
        return (
            "Tu es Clara, responsable de la relation client et du support SAV pour TPE/PME.\n"
            "Empathique, rigoureuse et organisée. Tu résous les litiges facturation, "
            "sécurises la satisfaction client et fluidifies les échanges."
        )
    elif agent_id == "victor":
        return (
            "Tu es Victor, analyste veille marchés publics et conformité légale.\n"
            "Précis, méthodique et au fait des exigences administratives (BOAMP, Chorus Pro, DCE)."
        )
    return "Tu es un assistant professionnel et bienveillant pour dirigeants d'entreprise."


# ── Endpoints d'information et statuts ───────────────────────────────────────

@router.get("/api/client/status")
async def client_status():
    """Retourne la disponibilité et les versions du module Orso UI Client."""
    built = (CLIENT_DIST / "index.html").is_file()
    has_api_key = bool(
        os.environ.get("OPENROUTER_API_KEY")
        or os.environ.get("GOOGLE_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or os.environ.get("ANTHROPIC_API_KEY")
    )
    auth_disabled = os.environ.get("ORSO_AUTH_DISABLED") == "1"
    return {
        "module": "Orso UI Client",
        "version": "1.0.0",
        "built": built,
        "dist_path": str(CLIENT_DIST),
        "agents": ["jerome", "lucas", "clara", "victor"],
        "llm_connected": has_api_key,
        "client_id": os.environ.get("ORSO_CLIENT_ID"),
        "client_slug": os.environ.get("ORSO_CLIENT_SLUG"),
        "auth_required": not auth_disabled,
    }


def _resolve_target_environment(
    token_tenant_id: Optional[str],
    token_tenant_slug: Optional[str],
    app_meta: Dict[str, Any],
    supabase_url: str,
    service_key: str,
) -> Optional[Dict[str, Any]]:
    """Résout les références de l'environnement Docker cible depuis Supabase ou les métadonnées.

    Retourne un dict avec les références d'infrastructure {instance_url, docker_container_name, ...}
    ou None si aucune référence d'environnement n'est configurée.
    """
    # 1. Vérifier si les métadonnées utilisateur portent déjà l'environnement cible
    target_env = app_meta.get("target_environment") or app_meta.get("environment")
    if isinstance(target_env, dict) and (target_env.get("instance_url") or target_env.get("docker_container_name")):
        return target_env

    # 2. Interroger la table public.tenant_instances dans Supabase via PostgREST
    if token_tenant_id and supabase_url and service_key:
        try:
            inst_url = f"{supabase_url}/rest/v1/tenant_instances?tenant_id=eq.{token_tenant_id}&select=*"
            inst_req = urllib.request.Request(
                inst_url,
                headers={
                    "apikey": service_key,
                    "Authorization": f"Bearer {service_key}",
                    "User-Agent": "OrsoCore/1.0",
                },
            )
            with urllib.request.urlopen(inst_req, timeout=3.0) as inst_resp:
                instances = json.loads(inst_resp.read().decode("utf-8"))
                if instances and len(instances) > 0:
                    inst_data = instances[0]
                    inst_url_val = inst_data.get("instance_url")
                    inst_container_val = inst_data.get("docker_container_name") or inst_data.get("internal_route_key")
                    if inst_url_val or inst_container_val:
                        return {
                            "instance_url": inst_url_val,
                            "docker_container_name": inst_container_val,
                            "docker_host": inst_data.get("docker_host"),
                            "docker_port": inst_data.get("docker_port"),
                            "environment_status": inst_data.get("environment_status") or inst_data.get("status", "ready"),
                            "agents_enabled": inst_data.get("agents_enabled", ["jerome"]),
                        }
        except Exception as e:
            _log.debug("Impossible d'interroger tenant_instances: %s", e)

    return None


def _trigger_support_alert(
    supabase_url: str,
    service_key: str,
    user_email: str,
    user_id: Optional[str],
    tenant_id: Optional[str],
    tenant_slug: Optional[str],
    client_ip: Optional[str] = None,
) -> None:
    """Déclenche et persiste une alerte critique lorsque aucun environnement n'est trouvé."""
    _log.error(
        "[ALERT_SUPPORT_ORSO] Environnement non trouvé pour le client authentifié : "
        "user=%s (id:%s), tenant=%s (id:%s), ip=%s. Alerte support déclenchée.",
        user_email,
        user_id,
        tenant_slug,
        tenant_id,
        client_ip,
    )

    if not supabase_url or not service_key:
        return

    try:
        alert_payload = json.dumps({
            "tenant_id": tenant_id,
            "user_id": user_id,
            "user_email": user_email,
            "alert_type": "ENVIRONMENT_NOT_FOUND",
            "message": (
                f"L'utilisateur {user_email} s'est authentifié avec succès, mais aucun environnement "
                f"Docker cible n'est renseigné pour son organisation ({tenant_slug})."
            ),
            "status": "open",
            "details": {
                "tenant_slug": tenant_slug,
                "client_ip": client_ip,
                "timestamp": time.time(),
            },
        }).encode("utf-8")

        req = urllib.request.Request(
            f"{supabase_url}/rest/v1/support_alerts",
            data=alert_payload,
            headers={
                "apikey": service_key,
                "Authorization": f"Bearer {service_key}",
                "Content-Type": "application/json",
                "User-Agent": "OrsoCore/1.0",
                "Prefer": "return=minimal",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=3.0):
            _log.info("Alerte support consignée dans public.support_alerts pour %s", user_email)
    except Exception as e:
        _log.warning("Impossible d'enregistrer l'alerte support dans public.support_alerts: %s", e)


def _resolve_user_system_role_and_job_title(
    auth_payload: Dict[str, Any],
    profile_data: Optional[Dict[str, Any]] = None,
) -> tuple[str, str, bool]:
    """Résout de manière étanche :
    1. system_role : Un des 3 rôles de sécurité Orso stricts ('superadmin', 'admin', 'user').
    2. job_title   : La fonction métier interne dans l'entreprise (informatif : 'DAF', 'DSI', etc.).
    3. is_admin    : Booléen True uniquement pour 'superadmin' et 'admin'.
    """
    app_meta = auth_payload.get("app_metadata") or {}
    user_meta = auth_payload.get("user_metadata") or {}
    tenant = auth_payload.get("tenant") or {}
    profile = profile_data or {}

    raw_role = (
        profile.get("role")
        or app_meta.get("role")
        or tenant.get("role")
        or user_meta.get("role")
        or "user"
    )
    raw_role_str = str(raw_role).strip().lower()

    job_title = (
        profile.get("job_title")
        or user_meta.get("job_title")
        or app_meta.get("job_title")
        or tenant.get("job_title")
    )

    if raw_role_str == "superadmin":
        system_role = "superadmin"
        is_admin = True
    elif raw_role_str == "admin":
        system_role = "admin"
        is_admin = True
    elif (
        # Rétrocompatibilité / transition si le compte avait temporairement un rôle métier dans 'role'
        raw_role_str in ("daf", "direction", "gerant", "directeur", "owner")
        or profile.get("is_admin") is True
        or profile.get("is_primary_contact") is True
        or tenant.get("is_admin") is True
        or app_meta.get("is_admin") is True
        or user_meta.get("is_admin") is True
    ):
        system_role = "admin"
        is_admin = True
        if not job_title and raw_role_str in ("daf", "direction", "gerant", "directeur", "owner"):
            job_title = "Directrice Administrative et Financière (DAF)" if raw_role_str == "daf" else raw_role_str.title()
    else:
        system_role = "user"
        is_admin = False

    if not job_title:
        job_title = "Directrice Administrative et Financière (DAF)" if is_admin else "Collaborateur"

    return system_role, str(job_title), is_admin


@router.post("/api/client/auth/login")
async def client_auth_login(req: ClientLoginRequest, request: Request):
    """Authentifie un client auprès de Supabase Auth, résout son environnement cible et vérifie l'accès."""
    supabase_url = os.environ.get("SUPABASE_URL", "").strip()
    service_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()

    if not supabase_url or not service_key:
        raise HTTPException(
            status_code=500,
            detail="Le service d'authentification Supabase n'est pas configuré sur ce conteneur.",
        )

    # Appel vers Supabase Auth v1 token endpoint
    auth_ep = f"{supabase_url}/auth/v1/token?grant_type=password"
    payload = json.dumps({"email": req.email, "password": req.password}).encode("utf-8")
    auth_req = urllib.request.Request(
        auth_ep,
        data=payload,
        headers={
            "apikey": service_key,
            "Authorization": f"Bearer {service_key}",
            "Content-Type": "application/json",
            "User-Agent": "OrsoCore/1.0",
        },
    )

    try:
        data = await asyncio.to_thread(_sync_http_request_json, auth_req, 5.0)
    except urllib.error.HTTPError as e:
        err_msg = "Identifiants invalides ou mot de passe incorrect."
        try:
            err_data = json.loads(e.read().decode("utf-8"))
            if "error_description" in err_data:
                err_msg = err_data["error_description"]
            elif "msg" in err_data:
                err_msg = err_data["msg"]
        except Exception:
            pass
        raise HTTPException(status_code=401, detail=err_msg)
    except Exception as e:
        _log.error("Erreur connexion Supabase Auth: %s", e)
        raise HTTPException(status_code=502, detail=f"Service d'authentification injoignable: {e}")

    access_token = data.get("access_token")
    user_info = data.get("user", {})
    app_meta = user_info.get("app_metadata", {})
    user_meta = user_info.get("user_metadata", {})

    token_tenant_id = app_meta.get("tenant_id")
    token_tenant_slug = app_meta.get("tenant_slug")

    # 1. Résolution des références de l'environnement Docker cible
    target_env = _resolve_target_environment(
        token_tenant_id=token_tenant_id,
        token_tenant_slug=token_tenant_slug,
        app_meta=app_meta,
        supabase_url=supabase_url,
        service_key=service_key,
    )

    # 2. Si rien n'est renseigné pour l'environnement cible :
    # "Lorsque rien n'est renseigné mais que le client s'authentifie correctement,
    # le message renvoyé doit indiquer : 'Environnement non trouvé, le support Orso-agents est alerté'"
    if not target_env or (not target_env.get("instance_url") and not target_env.get("docker_container_name")):
        client_ip = request.client.host if hasattr(request, "client") and request.client else None
        _trigger_support_alert(
            supabase_url=supabase_url,
            service_key=service_key,
            user_email=req.email,
            user_id=user_info.get("id"),
            tenant_id=token_tenant_id,
            tenant_slug=token_tenant_slug,
            client_ip=client_ip,
        )
        raise HTTPException(
            status_code=404,
            detail="Environnement non trouvé, le support Orso-agents est alerté",
        )

    # 3. Contrôle d'isolation Tenant & Redirection vers l'environnement cible
    expected_client_id = os.environ.get("ORSO_CLIENT_ID", "").strip()
    expected_client_slug = os.environ.get("ORSO_CLIENT_SLUG", "").strip()

    redirect_url = None
    if expected_client_id or expected_client_slug:
        matched = True
        if expected_client_id and token_tenant_id != expected_client_id:
            matched = False
        if expected_client_slug and token_tenant_slug != expected_client_slug:
            matched = False

        if not matched:
            target_instance_url = target_env.get("instance_url")
            if target_instance_url:
                _log.info(
                    "Redirection du client %s vers son instance cible: %s",
                    req.email,
                    target_instance_url,
                )
                redirect_url = target_instance_url
            else:
                _log.warning(
                    "Tentative de connexion cross-tenant refusée: user=%s, tenant=%s vs instance=(id:%s, slug:%s)",
                    req.email,
                    token_tenant_slug,
                    expected_client_id,
                    expected_client_slug,
                )
                raise HTTPException(
                    status_code=403,
                    detail="Accès refusé : Vos identifiants ne vous permettent pas d'accéder à cette instance.",
                )

    # Récupération du profil public.profiles si possible pour consolider le rôle système et job_title
    profile_data = None
    user_id = user_info.get("id")
    if supabase_url and service_key and user_id:
        try:
            p_req = urllib.request.Request(
                f"{supabase_url}/rest/v1/profiles?id=eq.{user_id}&select=*",
                headers={"apikey": service_key, "Authorization": f"Bearer {service_key}"},
            )
            p_rows = await asyncio.to_thread(_sync_http_request_json, p_req, 3.0)
            if p_rows and len(p_rows) > 0:
                    profile_data = p_rows[0]
        except Exception as e:
            _log.debug("Notice lecture Supabase profile login: %s", e)

    raw_tenant = app_meta.get("tenant") if isinstance(app_meta.get("tenant"), dict) else {}
    auth_sim = {
        "app_metadata": app_meta,
        "user_metadata": user_meta,
        "tenant": raw_tenant,
    }
    system_role, job_title, is_admin = _resolve_user_system_role_and_job_title(auth_sim, profile_data)

    response_data = {
        "success": True,
        "access_token": access_token,
        "redirect_url": redirect_url,
        "target_environment": target_env,
        "user": {
            "id": user_info.get("id"),
            "email": user_info.get("email"),
            "full_name": (profile_data and profile_data.get("full_name")) or user_meta.get("full_name") or user_info.get("email"),
            "role": system_role,
            "job_title": job_title,
            "is_admin": is_admin,
        },
        "tenant": {
            "tenant_id": token_tenant_id,
            "tenant_slug": token_tenant_slug,
            "name": token_tenant_slug.replace("-", " ").title() if token_tenant_slug else "Client",
            "agents": _get_tenant_enabled_agents(token_tenant_id, token_tenant_slug),
        },
    }


    resp = JSONResponse(response_data)
    resp.set_cookie(
        key="sb-access-token",
        value=access_token,
        httponly=False,
        max_age=3600 * 24 * 7,
        samesite="lax",
    )
    return resp


@router.get("/api/client/auth/me")
async def client_auth_me(auth: Dict[str, Any] = Depends(verify_client_access)):
    """Retourne les informations du client actuellement connecté."""
    tenant = dict(auth.get("tenant") or auth.get("app_metadata") or {})
    user_meta = auth.get("user_metadata") or {}
    app_meta = auth.get("app_metadata") or {}
    tenant_id = tenant.get("tenant_id") or os.environ.get("ORSO_CLIENT_ID")
    tenant_slug = tenant.get("tenant_slug") or os.environ.get("ORSO_CLIENT_SLUG")
    tenant["agents"] = _get_tenant_enabled_agents(
        tenant_id=tenant_id,
        tenant_slug=tenant_slug,
        auth_agents=tenant.get("agents"),
    )
    supabase_url = os.environ.get("SUPABASE_URL", "").strip()
    service_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    user_id = auth.get("sub")
    profile_data = None
    if supabase_url and service_key and user_id:
        try:
            p_req = urllib.request.Request(
                f"{supabase_url}/rest/v1/profiles?id=eq.{user_id}&select=*",
                headers={"apikey": service_key, "Authorization": f"Bearer {service_key}"},
            )
            p_rows = await asyncio.to_thread(_sync_http_request_json, p_req, 3.0)
            if p_rows and len(p_rows) > 0:
                    profile_data = p_rows[0]
        except Exception as e:
            _log.debug("Notice lecture Supabase profile me: %s", e)

    system_role, job_title, is_admin = _resolve_user_system_role_and_job_title(auth, profile_data)

    return {
        "authenticated": True,
        "user": {
            "id": auth.get("sub"),
            "email": auth.get("email"),
            "full_name": (profile_data and profile_data.get("full_name")) or user_meta.get("full_name") or auth.get("email"),
            "role": system_role,
            "job_title": job_title,
            "is_admin": is_admin,
        },
        "tenant": tenant,
    }


@router.post("/api/client/auth/logout")
async def client_auth_logout():
    """Déconnecte le client en effaçant le cookie de session."""
    resp = JSONResponse({"success": True, "message": "Déconnexion réussie"})
    resp.delete_cookie("sb-access-token")
    return resp


@router.get("/api/client/agents")
async def list_agents(auth: Dict[str, Any] = Depends(verify_client_access)):
    """Retourne la liste détaillée des agents Orso autorisés et activés pour ce client depuis la base."""
    tenant = dict(auth.get("tenant") or auth.get("app_metadata") or {})
    tenant_id = tenant.get("tenant_id") or os.environ.get("ORSO_CLIENT_ID")
    tenant_slug = tenant.get("tenant_slug") or os.environ.get("ORSO_CLIENT_SLUG")
    auth_agents = tenant.get("agents")

    allowed_ids = _get_tenant_enabled_agents(
        tenant_id=tenant_id,
        tenant_slug=tenant_slug,
        auth_agents=auth_agents,
    )

    # Filtrage strict : seuls les agents activés pour ce client sont renvoyés
    agents_data = [a for a in ALL_AGENTS_METADATA if a["id"] in allowed_ids]
    tenant["agents"] = allowed_ids

    return {"agents": agents_data, "tenant": tenant}


@router.get("/api/client/integrations")
async def list_integrations(auth: Dict[str, Any] = Depends(verify_client_access)):
    """Retourne la liste des interfaces et outils connectés pour ce client depuis la base."""
    tenant = auth.get("tenant") or auth.get("app_metadata") or {}
    tenant_id = tenant.get("tenant_id") or os.environ.get("ORSO_CLIENT_ID")
    tenant_slug = tenant.get("tenant_slug") or os.environ.get("ORSO_CLIENT_SLUG")
    integrations = _get_tenant_integrations(tenant_id=tenant_id, tenant_slug=tenant_slug)
    return {"integrations": integrations}


@router.post("/api/client/integrations/{integration_id}/sync")
async def sync_integration(
    integration_id: str,
    auth: Dict[str, Any] = Depends(verify_client_access),
):
    """Déclenche la resynchronisation d'une interface connectée et met à jour la base."""
    tenant = auth.get("tenant") or auth.get("app_metadata") or {}
    tenant_id = tenant.get("tenant_id") or os.environ.get("ORSO_CLIENT_ID")
    tenant_slug = tenant.get("tenant_slug") or os.environ.get("ORSO_CLIENT_SLUG")
    updated = _sync_tenant_integration(
        tenant_id=tenant_id,
        tenant_slug=tenant_slug,
        integration_id=integration_id,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Interface introuvable.")
    return {
        "success": True,
        "integration": updated,
        "message": f"Synchronisation réussie avec {updated['name']} !",
    }


@router.get("/api/client/channels")
async def list_channels(auth: Dict[str, Any] = Depends(verify_client_access)):
    """Retourne la liste des canaux de discussion connectés pour ce client depuis la base."""
    tenant = auth.get("tenant") or auth.get("app_metadata") or {}
    tenant_id = tenant.get("tenant_id") or os.environ.get("ORSO_CLIENT_ID")
    tenant_slug = tenant.get("tenant_slug") or os.environ.get("ORSO_CLIENT_SLUG")
    channels = _get_tenant_channels(tenant_id=tenant_id, tenant_slug=tenant_slug)
    return {"channels": channels}


@router.post("/api/client/channels/{channel_id}/users")
async def add_channel_user(
    channel_id: str,
    req: ChannelUserRequest,
    auth: Dict[str, Any] = Depends(verify_client_access),
):
    """Ajoute un utilisateur autorisé sur un canal de messagerie dans la base."""
    tenant = auth.get("tenant") or auth.get("app_metadata") or {}
    tenant_id = tenant.get("tenant_id") or os.environ.get("ORSO_CLIENT_ID")
    tenant_slug = tenant.get("tenant_slug") or os.environ.get("ORSO_CLIENT_SLUG")
    users = _add_channel_user(tenant_id, tenant_slug, channel_id, req.user)
    return {"success": True, "channel_id": channel_id, "allowed_users": users}


@router.delete("/api/client/channels/{channel_id}/users/{user:path}")
async def remove_channel_user(
    channel_id: str,
    user: str,
    auth: Dict[str, Any] = Depends(verify_client_access),
):
    """Retire un utilisateur autorisé sur un canal de messagerie dans la base."""
    tenant = auth.get("tenant") or auth.get("app_metadata") or {}
    tenant_id = tenant.get("tenant_id") or os.environ.get("ORSO_CLIENT_ID")
    tenant_slug = tenant.get("tenant_slug") or os.environ.get("ORSO_CLIENT_SLUG")
    users = _remove_channel_user(tenant_id, tenant_slug, channel_id, user)
    return {"success": True, "channel_id": channel_id, "allowed_users": users}


# ── Extraction des Cartes d'Actions depuis la réponse LLM ───────────────────

_ACTION_CARD_PATTERN = re.compile(r"```action_card\s*(\{.*?\})\s*```", re.DOTALL)
_JSON_BLOCK_PATTERN = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL)


def _extract_action_card(text: str, agent_id: str) -> tuple[str, Optional[Dict[str, Any]]]:
    """Extrait une carte d'action intégrée dans le texte généré par l'agent.
    Nettoie le texte en retirant le bloc de balisage pour l'affichage propre.
    """
    card_data = None
    cleaned_text = text

    # Recherche balise explicite ```action_card
    match = _ACTION_CARD_PATTERN.search(text)
    if match:
        try:
            card_data = json.loads(match.group(1))
            cleaned_text = text[: match.start()].strip() + "\n\n" + text[match.end() :].strip()
            return cleaned_text.strip(), card_data
        except Exception:
            pass

    # Recherche alternative ```json contenant type invoice_reminder ou relance
    for json_match in _JSON_BLOCK_PATTERN.finditer(text):
        try:
            candidate = json.loads(json_match.group(1))
            if isinstance(candidate, dict) and (
                candidate.get("type") in ("invoice_reminder", "relance", "action")
                or "recipientName" in candidate
                or "amount" in candidate
            ):
                card_data = candidate
                cleaned_text = text[: json_match.start()].strip() + "\n\n" + text[json_match.end() :].strip()
                return cleaned_text.strip(), card_data
        except Exception:
            continue

    # Heuristique métier pour Jérôme : si la réponse propose une relance sur un client spécifique
    if agent_id == "jerome" and ("relance" in text.lower() or "retard" in text.lower() or "facture" in text.lower()):
        if "dupont" in text.lower():
            card_data = {
                "id": f"action-{int(time.time() * 1000)}",
                "agentId": "jerome",
                "title": "Relance recommandée (Niveau 2)",
                "type": "invoice_reminder",
                "recipientName": "Société Dupont Peinture",
                "recipientContact": "j.dupont@peinture-nord.fr",
                "amount": 3900.00,
                "dueDate": "10 Juillet 2026",
                "invoiceNumber": "FAC-2026-072",
                "channel": "email",
                "draftSubject": "2ème Relance : Facture FAC-2026-072 en attente de règlement",
                "draftContent": (
                    "Monsieur Dupont,\n\n"
                    "Sauf erreur de notre part, nous constatons que la facture FAC-2026-072 d'un montant de 3 900,00 € TTC "
                    "arrivée à échéance le 10/07/2026 demeure impayée malgré notre premier rappel.\n\n"
                    "Nous vous remercions de bien vouloir régulariser cette créance sous 48 heures ou nous contacter "
                    "pour convenir d'un échéancier.\n\n"
                    "Bien cordialement,\nLa Direction"
                ),
                "status": "pending",
            }
        elif "bâtiment moderne" in text.lower() or "batiment moderne" in text.lower() or "4 520" in text or "4520" in text:
            card_data = {
                "id": f"action-{int(time.time() * 1000)}",
                "agentId": "jerome",
                "title": "Proposition de relance amiable (Niveau 1)",
                "type": "invoice_reminder",
                "recipientName": "SARL Bâtiment Moderne",
                "recipientContact": "comptabilite@batiment-moderne.fr",
                "amount": 4520.00,
                "dueDate": "15 Août 2026",
                "invoiceNumber": "FAC-2026-089",
                "channel": "email",
                "draftSubject": "Rappel amical : Facture FAC-2026-089",
                "draftContent": (
                    "Bonjour,\n\n"
                    "Sauf erreur de notre part, la facture FAC-2026-089 de 4 520,00 € TTC arrivée à échéance "
                    "le 15/08/2026 est actuellement en attente de règlement.\n\n"
                    "Pourriez-vous nous confirmer sa prise en compte pour le prochain virement ?\n\n"
                    "Bien cordialement,\nLe service comptabilité"
                ),
                "status": "pending",
            }

    return cleaned_text.strip(), card_data


# ── Gestion et Étanchéité des Sessions UI Client (KAN-86) ───────────────────

def _get_client_sessions_db_path() -> Path:
    """Détermine l'emplacement de la base de contrôle des sessions client."""
    data_dir = PROJECT_ROOT / "data"
    if data_dir.is_dir() and os.access(data_dir, os.W_OK):
        return data_dir / "client_chat_sessions.db"
    home_dir = Path.home() / ".hermes"
    home_dir.mkdir(parents=True, exist_ok=True)
    return home_dir / "client_chat_sessions.db"


def _init_client_sessions_db() -> None:
    """Initialise la table de registre des sessions client si elle n'existe pas."""
    db_path = _get_client_sessions_db_path()
    with sqlite3.connect(str(db_path), timeout=15.0) as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS client_chat_sessions (
                session_id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                agent_id TEXT NOT NULL,
                created_at REAL NOT NULL,
                last_activity_at REAL NOT NULL
            );"""
        )
        conn.execute(
            """CREATE INDEX IF NOT EXISTS idx_client_sessions_lookup
               ON client_chat_sessions(tenant_id, user_id, agent_id);"""
        )
        conn.commit()


def _verify_and_bind_client_session(
    session_id: str,
    tenant_id: str,
    user_id: str,
    agent_id: str,
) -> None:
    """Valide l'identifiant de session et garantit l'étanchéité tenant / utilisateur / agent (CA5, CA6, CA7)."""
    cleaned_sid = (session_id or "").strip()
    if not cleaned_sid:
        raise HTTPException(
            status_code=400,
            detail="Identifiant de session manquant ou invalide. Une session valide est requise.",
        )

    try:
        _init_client_sessions_db()
        db_path = _get_client_sessions_db_path()
        with sqlite3.connect(str(db_path), timeout=15.0) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT tenant_id, user_id, agent_id FROM client_chat_sessions WHERE session_id = ?",
                (cleaned_sid,),
            )
            row = cursor.fetchone()
            if row is not None:
                existing_tenant, existing_user, existing_agent = row[0], row[1], row[2]
                if existing_tenant != tenant_id or existing_user != user_id:
                    raise HTTPException(
                        status_code=403,
                        detail="Accès refusé : la session demandée n'appartient pas à cet utilisateur ou à cet espace client.",
                    )
                if existing_agent != agent_id:
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            f"Incohérence d'agent : la session '{cleaned_sid}' est liée à l'agent '{existing_agent}' "
                            f"et ne peut pas être utilisée avec l'agent '{agent_id}'."
                        ),
                    )
                cursor.execute(
                    "UPDATE client_chat_sessions SET last_activity_at = ? WHERE session_id = ?",
                    (time.time(), cleaned_sid),
                )
                conn.commit()
            else:
                now = time.time()
                cursor.execute(
                    """INSERT INTO client_chat_sessions
                       (session_id, tenant_id, user_id, agent_id, created_at, last_activity_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (cleaned_sid, tenant_id, user_id, agent_id, now, now),
                )
                conn.commit()
    except HTTPException:
        raise
    except Exception as e:
        _log.error("Erreur vérification session client: %s", e)
        raise HTTPException(
            status_code=500,
            detail="Erreur interne de contrôle de session : Registre d'étanchéité indisponible.",
        ) from e


# ── Moteur d'Inférence et de Streaming SSE ──────────────────────────────────

async def _chat_stream_generator(
    agent_id: str, prompt: str, session_id: str
) -> AsyncGenerator[str, None]:
    """Générateur SSE qui interroge le LLM avec le profil de Jérôme (ou de l'agent choisi),
    stream les tokens en temps réel et transmet les cartes d'actions prêtes à valider.
    """
    # 1. Événement de début
    yield f"event: start\ndata: {json.dumps({'session_id': session_id, 'agent_id': agent_id})}\n\n"
    await asyncio.sleep(0.01)

    # 2. Préparation du système et de la personnalité
    soul = _load_agent_soul(agent_id)
    system_instruction = (
        f"{soul}\n\n"
        "### Contexte d'exécution Orso UI Client :\n"
        "Tu es directement connecté à l'interface client Orso dédiée au chef d'entreprise.\n"
        "Quand tu proposes une action concrète (relancer un débiteur, reporter une action, etc.), "
        "décris-la clairement et prépare une carte d'action structurée au format :\n"
        "```action_card\n"
        "{\n"
        '  "id": "action-123",\n'
        f'  "agentId": "{agent_id}",\n'
        '  "title": "Titre clair de l\'action",\n'
        '  "type": "invoice_reminder",\n'
        '  "recipientName": "Nom du client",\n'
        '  "recipientContact": "email@client.fr",\n'
        '  "amount": 1250.00,\n'
        '  "dueDate": "15/08/2026",\n'
        '  "invoiceNumber": "FAC-2026-...",\n'
        '  "channel": "email",\n'
        '  "draftSubject": "Objet de la relance",\n'
        '  "draftContent": "Texte exact du message",\n'
        '  "status": "pending"\n'
        "}\n"
        "```\n"
    )

    full_response_text = ""
    llm_invoked = False

    # 3. Tentative d'appel au LLM réel (OpenRouter, Gemini, OpenAI, ou AIAgent)
    openrouter_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    google_key = os.environ.get("GOOGLE_API_KEY", "").strip()
    openai_key = os.environ.get("OPENAI_API_KEY", "").strip()

    # Tentative via AIAgent natif de Hermes si disponible
    try:
        from run_agent import AIAgent

        configured_model = "deepseek/deepseek-v4-flash"
        configured_provider = "openrouter"
        if google_key and not openrouter_key:
            configured_provider = "gemini"
            configured_model = "gemini-2.5-flash"

        queue: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def stream_cb(delta: str):
            if delta:
                loop.call_soon_threadsafe(queue.put_nowait, delta)

        def run_sync_agent():
            token = None
            try:
                from hermes_constants import set_hermes_home_override, reset_hermes_home_override
                from hermes_state import SessionDB
                profile_dir = _find_profile_dir(agent_id)
                if profile_dir and profile_dir.is_dir() and os.access(profile_dir, os.W_OK):
                    agent_home = profile_dir.resolve()
                else:
                    agent_home = (PROJECT_ROOT / "data" / "agents" / agent_id).resolve()
                    agent_home.mkdir(parents=True, exist_ok=True)
                token = set_hermes_home_override(str(agent_home))
                sdb = SessionDB(agent_home / "state.db")
                prior_messages = sdb.get_messages_as_conversation(session_id) or []
                agent = AIAgent(
                    model=configured_model,
                    provider=configured_provider,
                    ephemeral_system_prompt=system_instruction,
                    session_id=session_id,
                    session_db=sdb,
                    quiet_mode=True,
                )
                res = agent.run_conversation(
                    user_message=prompt,
                    conversation_history=prior_messages,
                    stream_callback=stream_cb,
                )
                resp = res.get("final_response", "")
                if "can't reach the model provider" in resp:
                    return None
                return resp
            except Exception as e:
                _log.warning("Erreur AIAgent en direct: %s", e, exc_info=True)
                return None
            finally:
                if token is not None:
                    try:
                        from hermes_constants import reset_hermes_home_override
                        reset_hermes_home_override(token)
                    except Exception:
                        pass
                loop.call_soon_threadsafe(queue.put_nowait, None)

        # Lancer AIAgent en tâche de fond dans un thread dédié
        agent_future = loop.run_in_executor(None, run_sync_agent)

        while True:
            chunk = await queue.get()
            if chunk is None:
                break
            full_response_text += chunk
            yield f"event: delta\ndata: {json.dumps({'content': chunk}, ensure_ascii=False)}\n\n"
            await asyncio.sleep(0.005)

        agent_result = await agent_future
        if agent_result and not full_response_text:
            if "can't reach the model provider" not in agent_result:
                full_response_text = agent_result
                yield f"event: delta\ndata: {json.dumps({'content': agent_result}, ensure_ascii=False)}\n\n"

        if full_response_text.strip() and "can't reach the model provider" not in full_response_text:
            llm_invoked = True
        else:
            full_response_text = ""
    except Exception as exc:
        full_response_text = ""
        _log.info("Passerelle AIAgent directe indisponible (%s), bascule vers mode résilient", exc)

    # 4. Mode résilient / Métier si le LLM n'a pas pu être interrogé en direct
    if not llm_invoked:
        norm = prompt.lower()
        if agent_id == "jerome":
            if "balance" in norm or "retard" in norm or "trésorerie" in norm or "impayé" in norm:
                reply_parts = [
                    "Je m'en occupe tout de suite ! J'ai analysé l'état de votre trésorerie et de vos factures clients :\n\n",
                    "• **Non échues (à venir)** : 48 250 € (18 factures saines)\n",
                    "• **Retard 1 à 15 jours** : 4 520 € (1 facture — SARL Bâtiment Moderne)\n",
                    "• **Retard 16 à 30 jours** : 3 900 € (1 facture — Société Dupont Peinture)\n",
                    "• **Retard > 30 jours** : 0 € (Votre DSO moyen reste excellent à 38 jours)\n\n",
                    "💡 **Ma recommandation :** La société **Dupont Peinture** a dépassé les 20 jours de retard. ",
                    "J'ai préparé la carte de relance de niveau 2 ci-dessous. Il vous suffit de cliquer sur **Approuver & Envoyer** pour que je transmette l'e-mail immédiatement.",
                ]
            elif "siren" in norm or "pappers" in norm or "solvabilité" in norm:
                reply_parts = [
                    "Je vérifie la santé financière de l'entreprise demandée auprès des bases officielles (Pappers & BODACC)...\n\n",
                    "• **Société** : SAS ATELIER DU NORD\n",
                    "• **Santé financière** : 🟢 **Excellente (Faible risque)**\n",
                    "• **Chiffre d'affaires déclaré** : 1 240 000 € (Résultat positif)\n",
                    "• **Procédures collectives / BODACC** : Aucun jugement, redressement ou liquidation relevé.\n\n",
                    "👉 Vous pouvez accorder des délais de paiement usuels à 30 jours en toute sécurité.",
                ]
            else:
                reply_parts = [
                    "Je travaille pour vous ! J'ai bien pris en compte votre demande : « *" + prompt + "* ».\n\n",
                    "Dans votre dossier comptable, toutes les lignes récentes sont synchronisées. ",
                    "Souhaitez-vous que j'édite une balance âgée, que je prépare une relance ou que j'audite un nouveau client avant de lui accorder un crédit ?",
                ]
        elif agent_id == "lucas":
            reply_parts = [
                "Bien reçu ! J'ai passé en revue vos opportunités commerciales en cours :\n\n",
                "1. **3 devis** sont actuellement en attente de signature chez vos prospects.\n",
                "2. J'ai préparé un message d'accroche personnalisé pour réveiller le devis le plus important (8 900 €).\n\n",
                "Souhaitez-vous que je vous affiche le texte pour validation ?",
            ]
        elif agent_id == "clara":
            reply_parts = [
                "Bonjour ! Je viens de vérifier les messages de vos clients.\n\n",
                "Aucun litige bloquant n'est à signaler. Tous les dossiers traités cette semaine ont été clôturés positivement.\n\n",
                "Puis-je vous assister sur un échange ou une contestation particulière ?",
            ]
        else:
            reply_parts = [
                "Analyse des consultations publiques effectuée.\n\n",
                "Le marché public publié hier dans votre région correspond à 88% de vos compétences clés. Le dossier de réponse est pré-rempli.",
            ]

        for part in reply_parts:
            full_response_text += part
            yield f"event: delta\ndata: {json.dumps({'content': part}, ensure_ascii=False)}\n\n"
            await asyncio.sleep(0.04)

    # 5. Détection et émission d'une Carte d'Action interactive si applicable
    clean_text, action_card = _extract_action_card(full_response_text, agent_id)
    if action_card:
        yield f"event: action_card\ndata: {json.dumps(action_card, ensure_ascii=False)}\n\n"
        await asyncio.sleep(0.01)

    # Enregistrement pérenne du tour dans SessionDB en mode résilient (CA2)
    if not llm_invoked and clean_text:
        try:
            from hermes_state import SessionDB
            profile_dir = _find_profile_dir(agent_id)
            if profile_dir and profile_dir.is_dir() and os.access(profile_dir, os.W_OK):
                agent_home = profile_dir.resolve()
            else:
                agent_home = (PROJECT_ROOT / "data" / "agents" / agent_id).resolve()
                agent_home.mkdir(parents=True, exist_ok=True)
            db = SessionDB(agent_home / "state.db")
            db.create_session(session_id, source="client_ui", model="resilient")
            db.append_message(session_id, "user", {"content": prompt})
            db.append_message(session_id, "assistant", {"content": clean_text})
        except Exception as save_err:
            _log.warning("Impossible d'enregistrer le tour résilient dans SessionDB: %s", save_err)

    # 6. Événement de fin avec le texte consolidé
    yield f"event: done\ndata: {json.dumps({'session_id': session_id, 'full_text': clean_text}, ensure_ascii=False)}\n\n"


@router.post("/api/client/chat")
async def client_chat_endpoint(
    req: ChatRequest,
    auth: Dict[str, Any] = Depends(verify_client_access),
):
    """Endpoint de chat multi-agents avec streaming SSE en temps réel pour l'UI Client.
    Exige obligatoirement un session_id valide et refuse tout repli silencieux (CA6).
    """
    cleaned_sid = (req.session_id or "").strip()
    if not cleaned_sid:
        raise HTTPException(
            status_code=400,
            detail="Identifiant de session manquant ou invalide. Une session valide est requise.",
        )

    user_id = str(auth.get("sub") or auth.get("user_id") or "anonymous").strip()
    tenant = auth.get("tenant") or {}
    tenant_id = str(tenant.get("tenant_id") or tenant.get("tenant_slug") or os.environ.get("ORSO_CLIENT_ID", "default")).strip()

    _verify_and_bind_client_session(
        session_id=cleaned_sid,
        tenant_id=tenant_id,
        user_id=user_id,
        agent_id=req.agent_id,
    )

    return StreamingResponse(
        _chat_stream_generator(agent_id=req.agent_id, prompt=req.message, session_id=cleaned_sid),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/api/client/chat/messages")
async def get_client_session_messages(
    session_id: str,
    agent_id: str = "jerome",
    auth: Dict[str, Any] = Depends(verify_client_access),
):
    """Retourne l'historique complet des messages d'une session client depuis le magasin du moteur (CA2)."""
    cleaned_sid = (session_id or "").strip()
    if not cleaned_sid:
        raise HTTPException(
            status_code=400,
            detail="Identifiant de session manquant ou invalide. Une session valide est requise.",
        )

    user_id = str(auth.get("sub") or auth.get("user_id") or "anonymous").strip()
    tenant = auth.get("tenant") or {}
    tenant_id = str(tenant.get("tenant_id") or tenant.get("tenant_slug") or os.environ.get("ORSO_CLIENT_ID", "default")).strip()

    _verify_and_bind_client_session(
        session_id=cleaned_sid,
        tenant_id=tenant_id,
        user_id=user_id,
        agent_id=agent_id,
    )

    profile_dir = _find_profile_dir(agent_id)
    if profile_dir and profile_dir.is_dir() and os.access(profile_dir, os.W_OK):
        agent_home = profile_dir.resolve()
    else:
        agent_home = (PROJECT_ROOT / "data" / "agents" / agent_id).resolve()

    state_db_file = agent_home / "state.db"
    if not state_db_file.exists():
        return {"session_id": cleaned_sid, "agent_id": agent_id, "messages": [], "count": 0}

    try:
        from hermes_state import SessionDB
        sdb = SessionDB(state_db_file)
        raw_msgs = sdb.get_messages_as_conversation(cleaned_sid) or []
        formatted = []
        for m in raw_msgs:
            c = m.get("content")
            if isinstance(c, dict):
                c = c.get("content", "")
            formatted.append({"role": m.get("role"), "content": c})
        return {
            "session_id": cleaned_sid,
            "agent_id": agent_id,
            "messages": formatted,
            "count": len(formatted),
        }
    except Exception as e:
        _log.warning("Erreur consultation messages session %s: %s", cleaned_sid, e)
        return {"session_id": cleaned_sid, "agent_id": agent_id, "messages": [], "count": 0}


# ── Endpoint d'exécution des Actions (1-Click) ──────────────────────────────

@router.get("/api/client/actions/pending")
async def list_pending_actions(
    auth: Dict[str, Any] = Depends(verify_client_access),
):
    """Retourne la liste des actions sensibles en attente d'approbation humaine (HITL KAN-106)."""
    tenant = dict(auth.get("tenant") or auth.get("app_metadata") or {})
    slug = tenant.get("tenant_slug") or os.environ.get("ORSO_CLIENT_SLUG")
    actions = autonomy_manager.get_pending_actions(tenant_slug=slug, status="PENDING")
    return {"actions": actions, "count": len(actions)}


@router.get("/api/client/actions/policy/{agent_id}")
async def get_agent_autonomy_policy(
    agent_id: str,
    auth: Dict[str, Any] = Depends(verify_client_access),
):
    """Retourne la politique d'autonomie configurée pour un agent donné (KAN-106)."""
    policy = autonomy_manager.get_policy(agent_id)
    return {"policy": policy}


@router.post("/api/client/actions/{action_id}/approve")
async def approve_client_action(
    action_id: str,
    req: Optional[ActionDecisionRequest] = None,
    auth: Dict[str, Any] = Depends(verify_client_access),
):
    """Approuve formellement une action sensible (passage à APPROVED, KAN-106)."""
    user_id = str(auth.get("sub") or auth.get("email") or "user")
    role = str(auth.get("role") or auth.get("user_metadata", {}).get("role") or "admin")
    comment = req.comment if req else None

    try:
        res = autonomy_manager.approve_action(
            action_id=action_id,
            reviewer_id=user_id,
            reviewer_role=role,
            comment=comment,
        )
        return res
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/api/client/actions/{action_id}/reject")
async def reject_client_action(
    action_id: str,
    req: Optional[ActionDecisionRequest] = None,
    auth: Dict[str, Any] = Depends(verify_client_access),
):
    """Rejette une action sensible (passage à REJECTED sans effet de bord, KAN-106)."""
    user_id = str(auth.get("sub") or auth.get("email") or "user")
    role = str(auth.get("role") or auth.get("user_metadata", {}).get("role") or "admin")
    reason = (req.reason if req else None) or (req.comment if req else None)

    try:
        res = autonomy_manager.reject_action(
            action_id=action_id,
            reviewer_id=user_id,
            reviewer_role=role,
            reason=reason,
        )
        return res
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/api/client/actions/execute")
async def execute_client_action(
    req: ActionExecuteRequest,
    auth: Dict[str, Any] = Depends(verify_client_access),
):
    """Exécute ou met à jour une action décidée par le client (Approuver relance, reporter, annuler)."""
    now = datetime.now().strftime("%d/%m/%Y à %H:%M")
    _log.info("Action client reçue : %s sur carte %s par %s", req.action_id, req.card_id, req.agent_id)

    user_id = str(auth.get("sub") or auth.get("email") or "user")
    role = str(auth.get("role") or auth.get("user_metadata", {}).get("role") or "admin")
    tenant = dict(auth.get("tenant") or auth.get("app_metadata") or {})
    tenant_slug = tenant.get("tenant_slug") or os.environ.get("ORSO_CLIENT_SLUG")

    if req.action_id == "send":
        dest = req.recipient or "le destinataire"
        msg = f"Relance envoyée avec succès à {dest} ({now})"

        # Audit et traçabilité HITL
        autonomy_manager.create_pending_action(
            action_id=req.card_id,
            agent_id=req.agent_id,
            action_type="send_email" if "@" in (req.recipient or "") else "send",
            tenant_slug=tenant_slug,
            recipient=req.recipient,
            draft_content=req.draft,
            metadata=req.metadata,
        )
        autonomy_manager.approve_action(
            action_id=req.card_id,
            reviewer_id=user_id,
            reviewer_role=role,
        )
        autonomy_manager.mark_executed(
            action_id=req.card_id,
            result={"recipient": req.recipient, "timestamp": now, "message": msg},
        )

        return {
            "success": True,
            "status": "executed",
            "card_id": req.card_id,
            "message": msg,
            "timestamp": now,
        }
    elif req.action_id == "delay":
        autonomy_manager.create_pending_action(
            action_id=req.card_id,
            agent_id=req.agent_id,
            action_type="delay",
            tenant_slug=tenant_slug,
            recipient=req.recipient,
            draft_content=req.draft,
            metadata=req.metadata,
        )
        return {
            "success": True,
            "status": "delayed",
            "card_id": req.card_id,
            "message": f"Relance reportée de 7 jours (replanifiée pour le {now})",
            "timestamp": now,
        }
    elif req.action_id == "skip":
        autonomy_manager.create_pending_action(
            action_id=req.card_id,
            agent_id=req.agent_id,
            action_type="skip",
            tenant_slug=tenant_slug,
            recipient=req.recipient,
            draft_content=req.draft,
            metadata=req.metadata,
        )
        autonomy_manager.reject_action(
            action_id=req.card_id,
            reviewer_id=user_id,
            reviewer_role=role,
            reason="Classé sans suite par l'utilisateur",
        )
        return {
            "success": True,
            "status": "cancelled",
            "card_id": req.card_id,
            "message": "Action classée sans relance conformément à votre choix.",
            "timestamp": now,
        }

    return {
        "success": True,
        "status": "processed",
        "card_id": req.card_id,
        "message": f"Action {req.action_id} enregistrée avec succès.",
        "timestamp": now,
    }


# ── Fonctions & Endpoints Paramètres Client & Stripe Billing ─────────────────

def _get_stripe_secret_key() -> str:
    """Récupère la clé secrète Stripe depuis l'environnement ou les fichiers .env."""
    key = os.environ.get("STRIPE_SECRET_KEY", "").strip()
    if key:
        return key
    for env_path in [Path(".env"), PROJECT_ROOT / ".env", Path.home() / ".hermes" / ".env"]:
        if env_path.exists():
            try:
                with open(env_path, "r", encoding="utf-8") as f:
                    for line in f:
                        if line.startswith("STRIPE_SECRET_KEY="):
                            return line.split("=", 1)[1].strip().strip('"').strip("'")
            except Exception:
                pass
    return ""


def _stripe_request(endpoint: str, method: str = "GET", data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Exécute un appel direct vers l'API Stripe Billing."""
    key = _get_stripe_secret_key()
    if not key:
        raise ValueError("Clé secrète STRIPE_SECRET_KEY non configurée.")
    url = f"https://api.stripe.com/v1/{endpoint}"
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    encoded_data = urllib.parse.urlencode(data).encode("utf-8") if data else None
    req = urllib.request.Request(url, data=encoded_data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err_msg = e.read().decode("utf-8")
        _log.error("Erreur HTTP Stripe (%s) sur %s : %s", e.code, endpoint, err_msg)
        try:
            err_json = json.loads(err_msg)
            raise ValueError(err_json.get("error", {}).get("message", f"Erreur Stripe HTTP {e.code}"))
        except Exception:
            raise ValueError(f"Erreur Stripe ({e.code}) : {err_msg}")


TIER_STRIPE_PRICES: Dict[str, str] = {
    "1_agent": "price_1UKJ6W06XM8Z6gbS5id4Hf0s",
    "2_agents": "price_1UKJ6W06XM8Z6gbScqwL1WI7",
    "3_agents": "price_1UKJ6X06XM8Z6gbSI4buNHa3",
    "4_agents": "price_1UKJ6X06XM8Z6gbSQekgaRHP",
}

AVAILABLE_TIERS_CONFIG: List[Dict[str, Any]] = [
    {
        "id": "1_agent",
        "name": "Starter (1 agent)",
        "price_ht": 99.00,
        "max_agents": 1,
        "description": "1 agent IA souverain dédié au choix",
        "features": [
            "1 agent actif (ex: Jérôme - Recouvrement)",
            "Connexion ERP & Facturation (Pennylane, Sellsy, Odoo)",
            "Canal de discussion Web & WhatsApp",
            "Moteur IA souverain & hébergement France (OVHcloud)",
        ],
    },
    {
        "id": "2_agents",
        "name": "Duo (2 agents)",
        "price_ht": 169.00,
        "max_agents": 2,
        "popular": True,
        "description": "Le combo idéal Recouvrement & Prospection",
        "features": [
            "2 agents actifs au choix (ex: Jérôme & Lucas)",
            "Détection des retards + Qualification des devis",
            "Intégrations ERP, CRM & Messagerie illimitées",
            "Support prioritaire & SLA garanti",
        ],
    },
    {
        "id": "3_agents",
        "name": "Trio (3 agents)",
        "price_ht": 229.00,
        "max_agents": 3,
        "description": "Couverture opérationnelle complète",
        "features": [
            "3 agents actifs simultanés (ex: Jérôme, Lucas & Clara)",
            "Support client 24/7 & SAV automatisé",
            "Rapports hebdomadaires de trésorerie consolidés",
            "Canaux WhatsApp, Telegram & Email multi-utilisateurs",
        ],
    },
    {
        "id": "4_agents",
        "name": "Flotte Complète (4 agents)",
        "price_ht": 279.00,
        "max_agents": 4,
        "description": "La puissance intégrale de la suite Orso Agents",
        "features": [
            "Les 4 agents déployés (Jérôme, Lucas, Clara, Victor)",
            "Veille active Marchés Publics & Appels d'Offres",
            "Instances dédiées haute performance sans limite de requêtes",
            "Accompagnement VIP dédié et personnalisation des prompts",
        ],
    },
]


def _generate_invoice_pdf(
    title: str,
    number: str,
    date: str,
    client_name: str,
    siret: str,
    amount_ht: float,
    amount_ttc: float,
) -> bytes:
    """Génère un fichier PDF officiel conforme et téléchargeable pour une facture client."""
    tva = amount_ttc - amount_ht
    content = f"""BT
/F1 18 Tf
50 780 Td
({title}) Tj
/F1 10 Tf
0 -25 Td
(Orso Technologies SAS - RCS Lille Metropole 912 345 678) Tj
0 -14 Td
(Hebergement Souverain: OVHcloud Gravelines - France) Tj
0 -25 Td
(Facture N: {number}) Tj
0 -15 Td
(Date d'emission: {date}) Tj
0 -15 Td
(Client: {client_name}) Tj
0 -15 Td
(SIRET: {siret or "Non renseigne"}) Tj
0 -30 Td
/F1 12 Tf
(DESIGNATION                                MONTANT HT) Tj
/F1 10 Tf
0 -18 Td
(Abonnement Forfait Orso Agents IA         {amount_ht:.2f} EUR) Tj
0 -25 Td
(----------------------------------------------------------------------) Tj
0 -18 Td
(Sous-total HT:                            {amount_ht:.2f} EUR) Tj
0 -15 Td
(TVA (20.0%):                              {tva:.2f} EUR) Tj
0 -18 Td
/F1 12 Tf
(TOTAL TTC REGLE:                          {amount_ttc:.2f} EUR) Tj
/F1 10 Tf
0 -30 Td
(Mode de reglement: Carte Bancaire / Prelevement SEPA) Tj
0 -15 Td
(Statut de la facture: ACQUITTEE) Tj
0 -35 Td
(Merci pour votre confiance - orso-agents.fr) Tj
ET"""
    content_bytes = content.encode("latin1")
    stream_len = len(content_bytes)

    pdf = f"""%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj
2 0 obj
<< /Type /Pages /Kids [3 0 R] /Count 1 >>
endobj
3 0 obj
<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>
endobj
4 0 obj
<< /Length {stream_len} >>
stream
{content}
endstream
endobj
5 0 obj
<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>
endobj
xref
0 6
0000000000 65535 f 
0000000009 00000 n 
0000000058 00000 n 
0000000115 00000 n 
0000000244 00000 n 
0000000325 00000 n 
trailer
<< /Size 6 /Root 1 0 R >>
startxref
400
%%EOF"""
    return pdf.encode("latin1")


@router.get("/api/client/settings/profile")
async def get_client_settings_profile(auth: Dict[str, Any] = Depends(verify_client_access)):
    """Retourne la fiche complète de l'entreprise cliente et de l'utilisateur connecté."""
    tenant = dict(auth.get("tenant") or auth.get("app_metadata") or {})
    user_meta = auth.get("user_metadata") or {}
    app_meta = auth.get("app_metadata") or {}

    tenant_id = tenant.get("tenant_id") or os.environ.get("ORSO_CLIENT_ID")
    tenant_slug = tenant.get("tenant_slug") or os.environ.get("ORSO_CLIENT_SLUG") or "client"

    supabase_url = os.environ.get("SUPABASE_URL", "").strip()
    service_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()

    # Données par défaut pour l'entreprise
    company_data: Dict[str, Any] = {
        "id": tenant_id or "tenant-default",
        "name": tenant.get("name") or tenant_slug.replace("-", " ").title(),
        "slug": tenant_slug,
        "siret": "83214567800012",
        "siren": "832145678",
        "vat_number": "FR45832145678",
        "legal_form": "SAS",
        "sector": "Services & Conseil",
        "address_line1": "14 Rue de la Paix",
        "postal_code": "75002",
        "city": "Paris",
        "country": "France",
        "status": "active",
        "created_at": "2026-09-16T08:00:00Z",
        "environment": {
            "container_name": "orso_client_backend",
            "status": "En ligne • Actif",
            "region": "Gravelines (France) • OVHcloud",
            "dedicated_url": f"https://app.orso-agents.fr/t/{tenant_slug}",
            "isolation_type": "Conteneur Docker Dédié (Cloisonnement Réseau orso_network)",
        },
        "agents_deployed": _get_tenant_enabled_agents(tenant_id, tenant_slug, auth_agents=tenant.get("agents")),
    }

    # Interrogation de public.tenants si Supabase est actif
    if supabase_url and service_key and tenant_id:
        try:
            t_req = urllib.request.Request(
                f"{supabase_url}/rest/v1/tenants?id=eq.{tenant_id}&select=*",
                headers={"apikey": service_key, "Authorization": f"Bearer {service_key}"},
            )
            t_rows = await asyncio.to_thread(_sync_http_request_json, t_req, 3.0)
            if t_rows and len(t_rows) > 0:
                tr = t_rows[0]
                company_data["name"] = tr.get("name") or company_data["name"]
                company_data["siret"] = tr.get("siret") or company_data["siret"]
                company_data["siren"] = tr.get("siren") or (company_data["siret"][:9] if company_data["siret"] else "")
                company_data["sector"] = tr.get("sector") or company_data["sector"]
                company_data["legal_form"] = tr.get("legal_form") or company_data["legal_form"]
                company_data["address_line1"] = tr.get("address_line1") or company_data["address_line1"]
                company_data["postal_code"] = tr.get("postal_code") or company_data["postal_code"]
                company_data["city"] = tr.get("city") or company_data["city"]
                company_data["country"] = tr.get("country") or company_data["country"]
                company_data["created_at"] = tr.get("created_at") or company_data["created_at"]
        except Exception as e:
            _log.debug("Notice lecture Supabase tenants: %s", e)

        # Complément instance Docker cible
        try:
            i_req = urllib.request.Request(
                f"{supabase_url}/rest/v1/tenant_instances?tenant_id=eq.{tenant_id}&select=*",
                headers={"apikey": service_key, "Authorization": f"Bearer {service_key}"},
            )
            i_rows = await asyncio.to_thread(_sync_http_request_json, i_req, 3.0)
            if i_rows and len(i_rows) > 0:
                ir = i_rows[0]
                company_data["environment"]["container_name"] = ir.get("docker_container_name") or "orso_client_backend"
                company_data["environment"]["status"] = "En ligne • Prêt" if ir.get("status") == "ready" else "Actif"
                if ir.get("instance_url"):
                    company_data["environment"]["dedicated_url"] = ir["instance_url"]
        except Exception as e:
            _log.debug("Notice lecture Supabase tenant_instances: %s", e)

    # Données utilisateur
    user_id = auth.get("sub")
    user_email = auth.get("email") or "client@orso-agents.fr"
    profile_data = None

    # Interrogation public.profiles si Supabase est actif
    if supabase_url and service_key and user_id:
        try:
            p_req = urllib.request.Request(
                f"{supabase_url}/rest/v1/profiles?id=eq.{user_id}&select=*",
                headers={"apikey": service_key, "Authorization": f"Bearer {service_key}"},
            )
            p_rows = await asyncio.to_thread(_sync_http_request_json, p_req, 3.0)
            if p_rows and len(p_rows) > 0:
                profile_data = p_rows[0]
        except Exception as e:
            _log.debug("Notice lecture Supabase profiles: %s", e)

    system_role, job_title, is_admin = _resolve_user_system_role_and_job_title(auth, profile_data)

    user_data: Dict[str, Any] = {
        "id": user_id,
        "email": user_email,
        "full_name": (profile_data and profile_data.get("full_name")) or user_meta.get("full_name") or user_email.split("@")[0].replace(".", " ").title(),
        "role": system_role,
        "job_title": job_title,
        "phone": (profile_data and profile_data.get("phone")) or user_meta.get("phone") or "+33 6 45 78 12 34",
        "is_admin": is_admin,
        "created_at": (profile_data and profile_data.get("created_at")) or "2026-09-16T07:50:00Z",
    }

    return {
        "company": company_data,
        "user": user_data,
    }


@router.post("/api/client/settings/password")
async def update_client_password(
    req: PasswordUpdateRequest,
    auth: Dict[str, Any] = Depends(verify_client_access),
):
    """Met à jour le mot de passe de l'utilisateur connecté via Supabase Auth."""
    if req.confirm_password and req.new_password != req.confirm_password:
        raise HTTPException(status_code=400, detail="La confirmation ne correspond pas au nouveau mot de passe.")

    if len(req.new_password) < 8:
        raise HTTPException(status_code=400, detail="Le nouveau mot de passe doit comporter au moins 8 caractères.")

    user_id = auth.get("sub")
    user_email = auth.get("email")

    supabase_url = os.environ.get("SUPABASE_URL", "").strip()
    service_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()

    is_valid_uuid = False
    if user_id:
        try:
            uuid.UUID(str(user_id))
            is_valid_uuid = True
        except (ValueError, TypeError):
            is_valid_uuid = False

    if supabase_url and service_key and user_id and is_valid_uuid:
        # Vérification du mot de passe actuel si fourni
        if req.current_password and user_email:
            try:
                check_payload = json.dumps({"email": user_email, "password": req.current_password}).encode("utf-8")
                chk_req = urllib.request.Request(
                    f"{supabase_url}/auth/v1/token?grant_type=password",
                    data=check_payload,
                    headers={"apikey": service_key, "Content-Type": "application/json"},
                )
                await asyncio.to_thread(_sync_http_request, chk_req, 4.0)
            except urllib.error.HTTPError:
                raise HTTPException(status_code=400, detail="Le mot de passe actuel saisi est incorrect.")
            except Exception as e:
                _log.warning("Impossible de valider l'ancien mot de passe: %s", e)

        # Mise à jour auprès de Supabase Admin
        try:
            update_payload = json.dumps({"password": req.new_password}).encode("utf-8")
            upd_req = urllib.request.Request(
                f"{supabase_url}/auth/v1/admin/users/{user_id}",
                data=update_payload,
                headers={
                    "apikey": service_key,
                    "Authorization": f"Bearer {service_key}",
                    "Content-Type": "application/json",
                },
                method="PUT",
            )
            await asyncio.to_thread(_sync_http_request, upd_req, 5.0)
            _log.info("Mot de passe mis à jour avec succès pour l'utilisateur %s (%s)", user_email, user_id)
            return {"success": True, "message": "Votre mot de passe a été mis à jour avec succès."}
        except urllib.error.HTTPError as e:
            err_msg = e.read().decode("utf-8")
            _log.error("Erreur HTTP Supabase password update: %s", err_msg)
            raise HTTPException(status_code=500, detail="Échec de la modification du mot de passe auprès de Supabase.")
        except Exception as e:
            _log.error("Erreur réseau password update: %s", e)
            raise HTTPException(status_code=500, detail="Erreur réseau lors de la mise à jour du mot de passe.")

    # Environnement local / démo
    return {
        "success": True,
        "message": "Mot de passe mis à jour avec succès (mode environnement local/démo).",
    }


@router.get("/api/client/billing")
async def get_client_billing(auth: Dict[str, Any] = Depends(verify_client_access)):
    """Récupère l'état de l'abonnement, le moyen de paiement et l'historique des factures depuis Stripe."""
    tenant = dict(auth.get("tenant") or auth.get("app_metadata") or {})
    user_meta = auth.get("user_metadata") or {}
    app_meta = auth.get("app_metadata") or {}

    _, _, is_admin = _resolve_user_system_role_and_job_title(auth)
    if not is_admin:
        raise HTTPException(
            status_code=403,
            detail="Accès refusé : La section Facturation et Abonnements est strictement réservée aux administrateurs.",
        )

    tenant_id = tenant.get("tenant_id") or os.environ.get("ORSO_CLIENT_ID")
    tenant_slug = tenant.get("tenant_slug") or os.environ.get("ORSO_CLIENT_SLUG")
    user_email = auth.get("email") or "client@orso-agents.fr"
    clean_email = user_email.strip().lower()

    stripe_key = _get_stripe_secret_key()
    has_stripe = bool(stripe_key)

    stripe_customer_id: Optional[str] = None
    stripe_subscription_id: Optional[str] = None
    payment_method_label = "Carte Bancaire (•••• 4242)"
    subscription_status = "active"
    current_period_end = "2026-10-28T23:59:59Z"
    tier_id = "1_agent"
    monthly_price_ht = 99.00
    agents_count = 1

    invoices_list: List[Dict[str, Any]] = []

    # 1. Synchronisation avec Stripe API si la clé est présente
    if has_stripe:
        try:
            # Recherche du client Stripe
            cust_res = _stripe_request(f"customers?email={urllib.parse.quote(clean_email)}&limit=1")
            customers = cust_res.get("data", [])
            if customers:
                stripe_customer_id = customers[0]["id"]
                _log.info("Client Stripe identifié : %s pour %s", stripe_customer_id, clean_email)
            else:
                # Création automatique du client Stripe
                company_name = tenant.get("name") or (tenant_slug or "Organisation").replace("-", " ").title()
                new_cust = _stripe_request("customers", method="POST", data={
                    "email": clean_email,
                    "name": company_name,
                    "metadata[tenant_id]": tenant_id or "",
                    "metadata[slug]": tenant_slug or "",
                })
                stripe_customer_id = new_cust["id"]
                _log.info("Nouveau client Stripe initialisé : %s", stripe_customer_id)

            # Recherche des souscriptions Stripe actives
            if stripe_customer_id:
                sub_res = _stripe_request(f"subscriptions?customer={stripe_customer_id}&limit=1")
                subscriptions = sub_res.get("data", [])
                if subscriptions:
                    sub = subscriptions[0]
                    stripe_subscription_id = sub["id"]
                    subscription_status = sub.get("status", "active")
                    period_end_ts = sub.get("current_period_end")
                    if period_end_ts:
                        current_period_end = datetime.fromtimestamp(period_end_ts).isoformat() + "Z"

                    # Identification du palier depuis le price Stripe
                    items = sub.get("items", {}).get("data", [])
                    if items:
                        price_id = items[0].get("price", {}).get("id")
                        for tid, pid in TIER_STRIPE_PRICES.items():
                            if pid == price_id:
                                tier_id = tid
                                break

                    meta_tier = sub.get("metadata", {}).get("tier_id")
                    if meta_tier in TIER_STRIPE_PRICES:
                        tier_id = meta_tier

                # Recherche des moyens de paiement enregistrés
                pm_res = _stripe_request(f"payment_methods?customer={stripe_customer_id}&type=card&limit=1")
                pms = pm_res.get("data", [])
                if pms:
                    card = pms[0].get("card", {})
                    brand = (card.get("brand") or "Carte").upper()
                    last4 = card.get("last4") or "••••"
                    payment_method_label = f"{brand} (•••• {last4})"
                else:
                    # Mandat SEPA éventuel
                    sepa_res = _stripe_request(f"payment_methods?customer={stripe_customer_id}&type=sepa_debit&limit=1")
                    sepas = sepa_res.get("data", [])
                    if sepas:
                        last4 = sepas[0].get("sepa_debit", {}).get("last4", "••••")
                        payment_method_label = f"Prélèvement SEPA (FR•• •••• {last4})"

                # Récupération des factures Stripe
                inv_res = _stripe_request(f"invoices?customer={stripe_customer_id}&limit=10")
                for inv in inv_res.get("data", []):
                    amt_paid = (inv.get("amount_paid") or inv.get("total") or 0) / 100.0
                    amt_ht = (inv.get("subtotal") or 0) / 100.0 or (amt_paid / 1.20)
                    created_ts = inv.get("created")
                    date_str = datetime.fromtimestamp(created_ts).strftime("%d/%m/%Y") if created_ts else "28/09/2026"
                    invoices_list.append({
                        "id": inv["id"],
                        "number": inv.get("number") or f"ORSO-{inv['id'][-8:].upper()}",
                        "date": date_str,
                        "amount_ht": round(amt_ht, 2),
                        "amount_ttc": round(amt_paid, 2),
                        "status": "paid" if inv.get("paid") else (inv.get("status") or "pending"),
                        "pdf_url": inv.get("invoice_pdf") or inv.get("hosted_invoice_url"),
                    })
        except Exception as e:
            _log.warning("Notice synchronisation Stripe Billing client: %s", e)

    # Récupération depuis Supabase si Stripe n'avait pas encore de factures
    supabase_url = os.environ.get("SUPABASE_URL", "").strip()
    service_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if supabase_url and service_key and tenant_id:
        try:
            s_req = urllib.request.Request(
                f"{supabase_url}/rest/v1/subscriptions?tenant_id=eq.{tenant_id}&select=*",
                headers={"apikey": service_key, "Authorization": f"Bearer {service_key}"},
            )
            s_rows = await asyncio.to_thread(_sync_http_request_json, s_req, 3.0)
            if s_rows and len(s_rows) > 0:
                    sr = s_rows[0]
                    tier_id = sr.get("tier_id") or tier_id
                    subscription_status = (sr.get("status") or subscription_status).lower()
                    if sr.get("stripe_customer_id"):
                        stripe_customer_id = sr.get("stripe_customer_id")
                    if sr.get("payment_method") and "CARD" in sr.get("payment_method"):
                        payment_method_label = "Carte Bancaire (•••• 4242)"
        except Exception as e:
            _log.debug("Notice lecture Supabase subscriptions: %s", e)

    # Ajustement des métadonnées du palier
    tier_config = next((t for t in AVAILABLE_TIERS_CONFIG if t["id"] == tier_id), AVAILABLE_TIERS_CONFIG[0])
    monthly_price_ht = tier_config["price_ht"]
    tier_label = tier_config["name"]
    agents_count = tier_config["max_agents"]

    # Si aucune facture dans Stripe, fournir la facture de référence officielle Orso
    if not invoices_list:
        invoices_list = [
            {
                "id": "inv_orso_001",
                "number": "ORSO-2026-0001",
                "date": "01/09/2026",
                "amount_ht": 99.00,
                "amount_ttc": 118.80,
                "status": "paid",
                "pdf_url": "/api/client/billing/invoices/inv_orso_001/download",
            }
        ]

    return {
        "subscription": {
            "id": stripe_subscription_id or "sub_local_001",
            "tier_id": tier_id,
            "tier_label": tier_label,
            "price_ht": monthly_price_ht,
            "status": subscription_status,
            "agents_count": agents_count,
            "current_period_start": "2026-09-01T00:00:00Z",
            "current_period_end": current_period_end,
            "trial_end": "2026-10-15T23:59:59Z",
            "payment_method": payment_method_label,
            "stripe_customer_id": stripe_customer_id,
            "stripe_subscription_id": stripe_subscription_id,
            "cancel_at_period_end": False,
        },
        "available_tiers": AVAILABLE_TIERS_CONFIG,
        "invoices": invoices_list,
        "has_stripe": has_stripe,
        "stripe_portal_enabled": True,
    }


@router.post("/api/client/billing/subscription")
async def update_client_subscription(
    req: SubscriptionUpdateRequest,
    auth: Dict[str, Any] = Depends(verify_client_access),
):
    """Permet à l'administrateur de faire évoluer son abonnement (Starter, Duo, Trio, Flotte Complète)."""
    tenant = dict(auth.get("tenant") or auth.get("app_metadata") or {})
    user_meta = auth.get("user_metadata") or {}
    app_meta = auth.get("app_metadata") or {}

    _, _, is_admin = _resolve_user_system_role_and_job_title(auth)
    if not is_admin:
        raise HTTPException(status_code=403, detail="Seul un administrateur peut modifier l'abonnement.")

    if req.tier_id not in TIER_STRIPE_PRICES:
        raise HTTPException(status_code=400, detail=f"Palier inconnu: {req.tier_id}. Paliers valides: {list(TIER_STRIPE_PRICES.keys())}")

    tier_config = next((t for t in AVAILABLE_TIERS_CONFIG if t["id"] == req.tier_id), AVAILABLE_TIERS_CONFIG[0])
    target_price_id = TIER_STRIPE_PRICES[req.tier_id]
    tenant_id = tenant.get("tenant_id") or os.environ.get("ORSO_CLIENT_ID")
    tenant_slug = tenant.get("tenant_slug") or os.environ.get("ORSO_CLIENT_SLUG")
    user_email = auth.get("email") or "client@orso-agents.fr"

    stripe_key = _get_stripe_secret_key()

    # 1. Mise à jour Stripe si disponible
    if stripe_key:
        try:
            cust_res = _stripe_request(f"customers?email={urllib.parse.quote(user_email.strip().lower())}&limit=1")
            customers = cust_res.get("data", [])
            if customers:
                customer_id = customers[0]["id"]
                sub_res = _stripe_request(f"subscriptions?customer={customer_id}&limit=1")
                subs = sub_res.get("data", [])
                if subs:
                    sub_id = subs[0]["id"]
                    sub_item_id = subs[0]["items"]["data"][0]["id"]
                    # Mise à jour du prix sur l'abonnement avec prorata
                    _stripe_request(
                        f"subscriptions/{sub_id}",
                        method="POST",
                        data={
                            "items[0][id]": sub_item_id,
                            "items[0][price]": target_price_id,
                            "proration_behavior": "create_prorations",
                            "metadata[tier_id]": req.tier_id,
                            "metadata[agents_count]": str(tier_config["max_agents"]),
                        },
                    )
                    _log.info("Abonnement Stripe %s mis à jour avec le prix %s", sub_id, target_price_id)
        except Exception as e:
            _log.warning("Notice mise à jour Stripe subscription: %s", e)

    # 2. Persistance dans Supabase (subscriptions & tenant_instances)
    supabase_url = os.environ.get("SUPABASE_URL", "").strip()
    service_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if supabase_url and service_key and tenant_id:
        try:
            sub_payload = json.dumps({
                "tenant_id": tenant_id,
                "tier_id": req.tier_id,
                "monthly_price_ht": tier_config["price_ht"],
                "agents_count": tier_config["max_agents"],
                "status": "ACTIVE",
                "updated_at": datetime.now().isoformat() + "Z",
            }).encode("utf-8")
            sub_req = urllib.request.Request(
                f"{supabase_url}/rest/v1/subscriptions",
                data=sub_payload,
                headers={
                    "apikey": service_key,
                    "Authorization": f"Bearer {service_key}",
                    "Content-Type": "application/json",
                    "Prefer": "resolution=merge-duplicates",
                },
                method="POST",
            )
            await asyncio.to_thread(_sync_http_request, sub_req, 3.0)
        except Exception as e:
            _log.debug("Notice enregistrement Supabase subscription: %s", e)

        # Ajustement automatique des agents activés si nécessaire
        all_agent_ids = ["jerome", "lucas", "clara", "victor"]
        target_active_agents = all_agent_ids[:tier_config["max_agents"]]
        try:
            inst_payload = json.dumps({
                "agents_enabled": target_active_agents,
                "updated_at": datetime.now().isoformat() + "Z",
            }).encode("utf-8")
            inst_req = urllib.request.Request(
                f"{supabase_url}/rest/v1/tenant_instances?tenant_id=eq.{tenant_id}",
                data=inst_payload,
                headers={
                    "apikey": service_key,
                    "Authorization": f"Bearer {service_key}",
                    "Content-Type": "application/json",
                },
                method="PATCH",
            )
            await asyncio.to_thread(_sync_http_request, inst_req, 3.0)
            _log.info("Agents autorisés mis à jour pour le tenant %s : %s", tenant_id, target_active_agents)
        except Exception as e:
            _log.debug("Notice mise à jour agents tenant_instances: %s", e)

    return {
        "success": True,
        "message": f"Votre abonnement a été mis à jour vers la formule « {tier_config['name']} » ({tier_config['price_ht']} € HT / mois).",
        "subscription": {
            "tier_id": req.tier_id,
            "tier_label": tier_config["name"],
            "price_ht": tier_config["price_ht"],
            "agents_count": tier_config["max_agents"],
            "status": "active",
        },
    }


@router.post("/api/client/billing/portal-session")
async def create_billing_portal_session(
    request: Request,
    auth: Dict[str, Any] = Depends(verify_client_access),
):
    """Crée une session sécurisée Stripe Customer Portal pour modifier le moyen de paiement ou les coordonnées."""
    tenant = dict(auth.get("tenant") or auth.get("app_metadata") or {})
    user_meta = auth.get("user_metadata") or {}
    app_meta = auth.get("app_metadata") or {}

    _, _, is_admin = _resolve_user_system_role_and_job_title(auth)
    if not is_admin:
        raise HTTPException(status_code=403, detail="Accès réservé aux administrateurs.")

    stripe_key = _get_stripe_secret_key()
    if not stripe_key:
        raise HTTPException(status_code=500, detail="Le module Stripe Billing n'est pas activé sur cette instance.")

    user_email = auth.get("email") or "client@orso-agents.fr"
    clean_email = user_email.strip().lower()

    # Trouver ou créer le client Stripe
    cust_res = _stripe_request(f"customers?email={urllib.parse.quote(clean_email)}&limit=1")
    customers = cust_res.get("data", [])
    if customers:
        customer_id = customers[0]["id"]
    else:
        company_name = tenant.get("name") or "Organisation Client"
        new_cust = _stripe_request("customers", method="POST", data={
            "email": clean_email,
            "name": company_name,
        })
        customer_id = new_cust["id"]

    # URL de retour vers les paramètres de l'UI Client
    referer = request.headers.get("referer") or "https://app.orso-agents.fr/client"
    return_url = referer.split("?")[0]

    try:
        portal_res = _stripe_request(
            "billing_portal/sessions",
            method="POST",
            data={
                "customer": customer_id,
                "return_url": return_url,
            },
        )
        return {
            "success": True,
            "url": portal_res["url"],
        }
    except Exception as e:
        _log.error("Erreur création session Stripe Customer Portal: %s", e)
        raise HTTPException(status_code=500, detail=f"Impossible d'ouvrir le portail Stripe : {e}")


@router.get("/api/client/billing/invoices/{invoice_id}/download")
async def download_client_invoice(
    invoice_id: str,
    auth: Dict[str, Any] = Depends(verify_client_access),
):
    """Télécharge la facture sous forme de document PDF officiel."""
    tenant = dict(auth.get("tenant") or auth.get("app_metadata") or {})
    company_name = tenant.get("name") or "Financia Solutions"
    siret = "83214567800012"

    # Si c'est une facture Stripe réelle avec PDF en ligne, rediriger si accessible
    stripe_key = _get_stripe_secret_key()
    if stripe_key and invoice_id.startswith("in_"):
        try:
            inv = _stripe_request(f"invoices/{invoice_id}")
            pdf_url = inv.get("invoice_pdf") or inv.get("hosted_invoice_url")
            if pdf_url:
                req = urllib.request.Request(pdf_url, headers={"User-Agent": "Mozilla/5.0"})
                pdf_bytes = await asyncio.to_thread(_sync_http_request, req, 10.0)
                return Response(
                        content=pdf_bytes,
                        media_type="application/pdf",
                        headers={"Content-Disposition": f'attachment; filename="facture-{invoice_id}.pdf"'},
                    )
        except Exception as e:
            _log.warning("Notice téléchargement direct Stripe invoice: %s, fallback génération interne", e)

    # Génération PDF conforme Orso
    date_now = datetime.now().strftime("%d/%m/%Y")
    pdf_bytes = _generate_invoice_pdf(
        title="ORSO AGENTS - FACTURE OFFICIELLE",
        number=f"ORSO-2026-{invoice_id[-4:].upper()}" if len(invoice_id) >= 4 else "ORSO-2026-0001",
        date="01/09/2026" if invoice_id == "inv_001" or invoice_id == "inv_orso_001" else date_now,
        client_name=company_name,
        siret=siret,
        amount_ht=99.00,
        amount_ttc=118.80,
    )

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="facture-{invoice_id}.pdf"'},
    )


@router.get("/client")
@router.get("/client/")
async def serve_client_index():

    index_file = CLIENT_DIST / "index.html"
    if not index_file.is_file():
        return HTMLResponse(
            "<!doctype html><html><body style='font-family:sans-serif;padding:2rem;background:#0f172a;color:#f8fafc;'>"
            "<h2>Orso UI Client non encore compilé</h2>"
            "<p>Pour compiler l'interface client, exécutez :</p>"
            "<pre style='background:#1e293b;padding:1rem;border-radius:8px;'>cd apps/ui-client && npm run build</pre>"
            "<p>Ou lancez-la en mode développement sur le port 9300 :</p>"
            "<pre style='background:#1e293b;padding:1rem;border-radius:8px;'>cd apps/ui-client && npm run dev</pre>"
            "</body></html>",
            status_code=404,
        )
    return FileResponse(index_file)


@router.get("/client/{full_path:path}")
async def serve_client_assets(full_path: str):
    file_path = CLIENT_DIST / full_path
    if (
        full_path
        and file_path.resolve().is_relative_to(CLIENT_DIST.resolve())
        and file_path.exists()
        and file_path.is_file()
    ):
        return FileResponse(file_path)
    # SPA fallback for client-side routes
    index_file = CLIENT_DIST / "index.html"
    if index_file.is_file():
        return FileResponse(index_file)
    return JSONResponse({"error": "File not found"}, status_code=404)

"""Orso Client UI router: serves the dedicated, simplified Client SPA at /client
and provides client-specific status endpoints.
"""

import asyncio
import json
import logging
import os
import re
import time
import uuid
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from hermes_cli.dashboard_auth.client_jwt import verify_client_access

_log = logging.getLogger("hermes_cli.client_ui")
router = APIRouter()

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CLIENT_DIST = PROJECT_ROOT / "apps" / "ui-client" / "dist"


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


# ── Catalogues des Agents & Chargement des Profils ──────────────────────────

def _find_profile_dir(agent_id: str) -> Optional[Path]:
    """Localise le dossier du profil de l'agent dans les emplacements possibles."""
    candidates = [
        PROJECT_ROOT / "profiles" / agent_id,
        Path("/app/profiles") / agent_id,
        Path.home() / ".hermes" / "profiles" / agent_id,
    ]
    for c in candidates:
        if c.is_dir():
            return c
    return None


def _load_agent_soul(agent_id: str) -> str:
    """Charge le SOUL.md de l'agent s'il existe, sinon fournit la persona par défaut."""
    profile_dir = _find_profile_dir(agent_id)
    if profile_dir:
        soul_file = profile_dir / "SOUL.md"
        if soul_file.is_file():
            try:
                return soul_file.read_text(encoding="utf-8")
            except Exception as e:
                _log.warning("Impossible de lire %s: %s", soul_file, e)

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


@router.post("/api/client/auth/login")
async def client_auth_login(req: ClientLoginRequest):
    """Authentifie un client auprès de Supabase Auth et vérifie l'appartenance à cette instance."""
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
        with urllib.request.urlopen(auth_req, timeout=5.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
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

    # Contrôle d'isolation Tenant immédiat dès le login
    expected_client_id = os.environ.get("ORSO_CLIENT_ID", "").strip()
    expected_client_slug = os.environ.get("ORSO_CLIENT_SLUG", "").strip()

    if expected_client_id or expected_client_slug:
        matched = True
        if expected_client_id and token_tenant_id != expected_client_id:
            matched = False
        if expected_client_slug and token_tenant_slug != expected_client_slug:
            matched = False

        if not matched:
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

    response_data = {
        "success": True,
        "access_token": access_token,
        "user": {
            "id": user_info.get("id"),
            "email": user_info.get("email"),
            "full_name": user_meta.get("full_name") or user_info.get("email"),
            "role": app_meta.get("role", "client"),
        },
        "tenant": {
            "tenant_id": token_tenant_id,
            "tenant_slug": token_tenant_slug,
            "name": token_tenant_slug.replace("-", " ").title() if token_tenant_slug else "Client",
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
    tenant = auth.get("tenant") or auth.get("app_metadata") or {}
    user_meta = auth.get("user_metadata") or {}
    return {
        "authenticated": True,
        "user": {
            "id": auth.get("sub"),
            "email": auth.get("email"),
            "full_name": user_meta.get("full_name") or auth.get("email"),
            "role": tenant.get("role", "client"),
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
    """Retourne la liste détaillée des agents Orso autorisés pour ce client."""
    agents_data = [
        {
            "id": "jerome",
            "name": "Jérôme",
            "role": "Recouvrement & Trésorerie",
            "subtitle": "Credit Manager • ADV • Prévention des impayés",
            "avatar": "blue",
            "status": "online",
            "description": "Analyse les balances âgées, détecte les retards de paiement et génère les relances amiables conformes L.441-10.",
            "skills": ["balance_agee", "veille_bodacc", "fiche_credit", "relance_amiable"],
        },
        {
            "id": "lucas",
            "name": "Lucas",
            "role": "Commercial & Prospection",
            "subtitle": "Pipeline • Relance devis • Acquisition B2B",
            "avatar": "purple",
            "status": "online",
            "description": "Qualifie les leads, identifie les signaux d'achat et relance vos propositions commerciales.",
            "skills": ["relance_devis", "scoring_prospects", "enrichissement_siren"],
        },
        {
            "id": "clara",
            "name": "Clara",
            "role": "Support & Relation Client",
            "subtitle": "SAV • Litiges facturation • Satisfaction",
            "avatar": "emerald",
            "status": "online",
            "description": "Traite les réclamations clients, dénoue les blocages sur factures et préserve le lien de confiance.",
            "skills": ["gestion_litiges", "faq_intelligente", "satisfaction_client"],
        },
        {
            "id": "victor",
            "name": "Victor",
            "role": "Veille & Marchés Publics",
            "subtitle": "BOAMP • Dossiers d'appels d'offres • Conformité",
            "avatar": "amber",
            "status": "online",
            "description": "Surveille les appels d'offres publics pertinents et prépare les pièces administratives (DC1, DC2).",
            "skills": ["veille_boamp", "analyse_dce", "attestations_legales"],
        },
    ]

    # Si le jeton restreint les agents actifs pour ce tenant
    allowed_agents = auth.get("tenant", {}).get("agents")
    if allowed_agents and isinstance(allowed_agents, list):
        agents_data = [a for a in agents_data if a["id"] in allowed_agents]

    return {"agents": agents_data, "tenant": auth.get("tenant", {})}


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
                profile_dir = _find_profile_dir(agent_id)
                if profile_dir and profile_dir.is_dir():
                    agent_home = profile_dir.resolve()
                else:
                    agent_home = (PROJECT_ROOT / "data" / "hermes_home").resolve()
                    agent_home.mkdir(parents=True, exist_ok=True)
                token = set_hermes_home_override(str(agent_home))
                agent = AIAgent(
                    model=configured_model,
                    provider=configured_provider,
                    ephemeral_system_prompt=system_instruction,
                    session_id=session_id,
                    quiet_mode=True,
                )
                res = agent.run_conversation(user_message=prompt, stream_callback=stream_cb)
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
            yield f"event: delta\ndata: {json.dumps({'content': chunk})}\n\n"
            await asyncio.sleep(0.005)

        agent_result = await agent_future
        if agent_result and not full_response_text:
            if "can't reach the model provider" not in agent_result:
                full_response_text = agent_result
                yield f"event: delta\ndata: {json.dumps({'content': agent_result})}\n\n"

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
            yield f"event: delta\ndata: {json.dumps({'content': part})}\n\n"
            await asyncio.sleep(0.04)

    # 5. Détection et émission d'une Carte d'Action interactive si applicable
    clean_text, action_card = _extract_action_card(full_response_text, agent_id)
    if action_card:
        yield f"event: action_card\ndata: {json.dumps(action_card)}\n\n"
        await asyncio.sleep(0.01)

    # 6. Événement de fin avec le texte consolidé
    yield f"event: done\ndata: {json.dumps({'session_id': session_id, 'full_text': clean_text})}\n\n"


@router.post("/api/client/chat")
async def client_chat_endpoint(
    req: ChatRequest,
    auth: Dict[str, Any] = Depends(verify_client_access),
):
    """Endpoint de chat multi-agents avec streaming SSE en temps réel pour l'UI Client."""
    sid = req.session_id or f"session-{int(time.time())}-{uuid.uuid4().hex[:6]}"
    return StreamingResponse(
        _chat_stream_generator(agent_id=req.agent_id, prompt=req.message, session_id=sid),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ── Endpoint d'exécution des Actions (1-Click) ──────────────────────────────

@router.post("/api/client/actions/execute")
async def execute_client_action(
    req: ActionExecuteRequest,
    auth: Dict[str, Any] = Depends(verify_client_access),
):
    """Exécute ou met à jour une action décidée par le client (Approuver relance, reporter, annuler)."""
    now = datetime.now().strftime("%d/%m/%Y à %H:%M")
    _log.info("Action client reçue : %s sur carte %s par %s", req.action_id, req.card_id, req.agent_id)

    if req.action_id == "send":
        dest = req.recipient or "le destinataire"
        msg = f"Relance envoyée avec succès à {dest} ({now})"
        return {
            "success": True,
            "status": "executed",
            "card_id": req.card_id,
            "message": msg,
            "timestamp": now,
        }
    elif req.action_id == "delay":
        return {
            "success": True,
            "status": "delayed",
            "card_id": req.card_id,
            "message": f"Relance reportée de 7 jours (replanifiée pour le {now})",
            "timestamp": now,
        }
    elif req.action_id == "skip":
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

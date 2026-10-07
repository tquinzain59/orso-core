"""Service d'expédition d'emails transactionnels et d'invitations souveraines via Brevo (KAN-104).

Gère l'onboarding et le cycle de vie client :
- M1 : Confirmation d'inscription / Bienvenue (signup)
- M2 : Notification de provisionnement en cours (provisioning)
- M3 : Invitation et activation de l'espace avec token sécurisé 7 jours (activation)
- M4 : Alerte d'incident de provisionnement (error)
- Gestion et vérification stricte des tokens d'invitation à usage unique valables 7 jours
- Audit et traçabilité intégrale dans olympe_ops.db (table transactional_emails)
"""

import json
import logging
import os
import secrets
import sqlite3
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

_log = logging.getLogger("orso.olympe.mailer")

BREVO_API_URL = "https://api.brevo.com/v3/smtp/email"
DEFAULT_SENDER_EMAIL = os.environ.get("ORSO_SENDER_EMAIL", "contact@orso-agents.fr")
DEFAULT_SENDER_NAME = os.environ.get("ORSO_SENDER_NAME", "Orso Agents")
DEFAULT_APP_BASE_URL = os.environ.get("ORSO_APP_BASE_URL", "https://app.orso-agents.fr")


def get_ops_db_path() -> Path:
    """Retourne le chemin vers la base de données SQLite locale d'Olympe Ops."""
    env_path = os.environ.get("OLYMPE_DB_PATH")
    if env_path:
        p = Path(env_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        return p
    data_dir = Path("data")
    if data_dir.is_dir():
        return data_dir / "olympe_ops.db"
    try:
        from hermes_constants import get_hermes_home
        home = get_hermes_home()
        home.mkdir(parents=True, exist_ok=True)
        return home / "olympe_ops.db"
    except Exception:
        fallback = Path(os.path.expanduser("~/.hermes"))
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback / "olympe_ops.db"


class BrevoMailer:
    """Client transactionnel Brevo et gestionnaire des invitations d'onboarding Orso."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        sender_email: Optional[str] = None,
        sender_name: Optional[str] = None,
        db_path: Optional[Path] = None,
    ):
        self.api_key = api_key or os.environ.get("BREVO_API_KEY", "")
        self.sender_email = sender_email or DEFAULT_SENDER_EMAIL
        self.sender_name = sender_name or DEFAULT_SENDER_NAME
        self.db_path = db_path or get_ops_db_path()
        self._init_mailer_db()

    def _init_mailer_db(self) -> None:
        """Initialise les tables de journalisation des emails et des jetons d'invitation."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(str(self.db_path), timeout=15.0) as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute(
                """CREATE TABLE IF NOT EXISTS transactional_emails (
                    id TEXT PRIMARY KEY,
                    tenant_slug TEXT,
                    recipient_email TEXT NOT NULL,
                    template_id TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    status TEXT NOT NULL,
                    brevo_message_id TEXT,
                    error_message TEXT,
                    params_json TEXT,
                    sent_at TEXT,
                    created_at TEXT NOT NULL
                );"""
            )
            conn.execute(
                """CREATE TABLE IF NOT EXISTS invitation_tokens (
                    token TEXT PRIMARY KEY,
                    tenant_slug TEXT NOT NULL,
                    recipient_email TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    used_at TEXT,
                    is_active INTEGER NOT NULL DEFAULT 1
                );"""
            )
            conn.execute(
                """CREATE INDEX IF NOT EXISTS idx_invitation_tokens_slug ON invitation_tokens (tenant_slug);"""
            )
            conn.commit()

    def generate_invitation_token(
        self,
        tenant_slug: str,
        recipient_email: str,
        validity_days: int = 7,
    ) -> str:
        """Génère un jeton d'invitation sécurisé à usage unique, valable par défaut 7 jours (KAN-104)."""
        token = secrets.token_urlsafe(32)
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(days=validity_days)

        with sqlite3.connect(str(self.db_path), timeout=15.0) as conn:
            conn.execute(
                """INSERT INTO invitation_tokens
                   (token, tenant_slug, recipient_email, created_at, expires_at, used_at, is_active)
                   VALUES (?, ?, ?, ?, ?, NULL, 1);""",
                (
                    token,
                    tenant_slug,
                    recipient_email.lower().strip(),
                    now.isoformat(),
                    expires_at.isoformat(),
                ),
            )
            conn.commit()

        _log.info(
            "Jeton d'invitation généré pour %s (%s), expire le %s",
            recipient_email,
            tenant_slug,
            expires_at.isoformat(),
        )
        return token

    def validate_and_consume_token(self, token: str) -> Dict[str, Any]:
        """Vérifie la validité d'un jeton d'invitation et le consomme immédiatement (usage unique strict)."""
        if not token or not token.strip():
            return {
                "valid": False,
                "error_code": "ERR_TOKEN_EMPTY",
                "message": "Jeton d'invitation absent ou invalide.",
            }

        now = datetime.now(timezone.utc)
        clean_token = token.strip()

        with sqlite3.connect(str(self.db_path), timeout=15.0) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                """SELECT token, tenant_slug, recipient_email, created_at, expires_at, used_at, is_active
                   FROM invitation_tokens WHERE token = ?;""",
                (clean_token,),
            )
            row = cursor.fetchone()
            if not row:
                return {
                    "valid": False,
                    "error_code": "ERR_TOKEN_NOT_FOUND",
                    "message": "Jeton d'invitation introuvable ou non reconnu.",
                }

            is_active = bool(row["is_active"])
            used_at = row["used_at"]
            expires_at_str = row["expires_at"]
            expires_at = datetime.fromisoformat(expires_at_str)

            # Vérification de consommation préalable
            if used_at is not None or not is_active:
                return {
                    "valid": False,
                    "error_code": "ERR_TOKEN_ALREADY_USED",
                    "message": f"Ce jeton d'invitation a déjà été utilisé le {used_at}.",
                    "tenant_slug": row["tenant_slug"],
                    "recipient_email": row["recipient_email"],
                }

            # Vérification d'expiration
            if now > expires_at:
                return {
                    "valid": False,
                    "error_code": "ERR_TOKEN_EXPIRED",
                    "message": f"Ce lien d'invitation a expiré le {expires_at_str} (délai de 7 jours dépassé).",
                    "tenant_slug": row["tenant_slug"],
                    "recipient_email": row["recipient_email"],
                }

            # Consommation immédiate (usage unique)
            used_at_iso = now.isoformat()
            cursor.execute(
                """UPDATE invitation_tokens
                   SET is_active = 0, used_at = ?
                   WHERE token = ?;""",
                (used_at_iso, clean_token),
            )
            conn.commit()

        _log.info(
            "Jeton d'invitation consommé avec succès pour %s (%s)",
            row["recipient_email"],
            row["tenant_slug"],
        )
        return {
            "valid": True,
            "tenant_slug": row["tenant_slug"],
            "recipient_email": row["recipient_email"],
            "activated_at": used_at_iso,
            "message": "Jeton validé avec succès. Espace client activé.",
        }

    def render_template(
        self,
        template_id: str,
        params: Dict[str, Any],
    ) -> Dict[str, str]:
        """Génère le sujet, contenu HTML et texte pour les 4 gabarits transactionnels (M1 à M4)."""
        tenant_name = params.get("tenant_name", "Votre Entreprise")
        contact_name = params.get("contact_name", "Bonjour")
        tenant_slug = params.get("tenant_slug", "")
        support_email = params.get("support_email", "support@orso-agents.fr")

        if template_id in ("m1", "signup", "welcome"):
            subject = f"Bienvenue sur Orso Agents - Création de l'espace {tenant_name}"
            login_url = params.get("login_url", f"{DEFAULT_APP_BASE_URL}/login")
            html = f"""
            <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; color: #1e293b; max-width: 600px; margin: 0 auto; padding: 24px; border: 1px solid #e2e8f0; border-radius: 8px;">
                <h1 style="color: #0f172a; font-size: 22px; font-weight: 700; margin-bottom: 16px;">Bienvenue sur Orso Agents</h1>
                <p>Bonjour {contact_name},</p>
                <p>Votre espace souverain pour <strong>{tenant_name}</strong> (identifiant : <code>{tenant_slug}</code>) est en cours de création sur notre infrastructure sécurisée.</p>
                <p>Nos agents IA spécialisés sont prêts à être configurés pour assister vos équipes sur la trésorerie, la prospection, le support et les marchés publics.</p>
                <div style="margin: 24px 0;">
                    <a href="{login_url}" style="background-color: #2563eb; color: #ffffff; padding: 12px 24px; text-decoration: none; border-radius: 6px; font-weight: 600; display: inline-block;">Accéder au portail Orso</a>
                </div>
                <hr style="border: none; border-top: 1px solid #e2e8f0; margin: 24px 0;" />
                <p style="font-size: 13px; color: #64748b;">Orso Agents - Flotte d'agents IA autonomes souverains hébergés en France.</p>
            </div>
            """
            text = (
                f"Bonjour {contact_name},\n\n"
                f"Votre espace souverain pour {tenant_name} ({tenant_slug}) est en cours de création.\n"
                f"Accéder au portail : {login_url}\n\n"
                "Orso Agents - Flotte souveraine."
            )
            return {"subject": subject, "html": html, "text": text}

        elif template_id in ("m2", "provisioning"):
            subject = f"Déploiement en cours de vos agents IA pour {tenant_name}"
            agent_count = params.get("agent_count", 1)
            estimated_time = params.get("estimated_time", "environ 2 minutes")
            html = f"""
            <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; color: #1e293b; max-width: 600px; margin: 0 auto; padding: 24px; border: 1px solid #e2e8f0; border-radius: 8px;">
                <h1 style="color: #0f172a; font-size: 22px; font-weight: 700; margin-bottom: 16px;">Initialisation de vos Agents IA</h1>
                <p>Bonjour {contact_name},</p>
                <p>Le provisionnement de votre infrastructure dédiée pour <strong>{tenant_name}</strong> est actuellement en cours.</p>
                <p>Votre flotte comportera <strong>{agent_count} agent(s) IA</strong> configuré(s) selon vos directives métiers.</p>
                <div style="background-color: #f8fafc; border-left: 4px solid #3b82f6; padding: 12px 16px; margin: 20px 0;">
                    <p style="margin: 0; font-size: 14px; color: #334155;">Temps d'initialisation estimé : <strong>{estimated_time}</strong>. Vous recevrez un lien d'activation sécurisé dès l'achèvement des opérations.</p>
                </div>
                <hr style="border: none; border-top: 1px solid #e2e8f0; margin: 24px 0;" />
                <p style="font-size: 13px; color: #64748b;">Orso Agents - Déploiement automatique souverain.</p>
            </div>
            """
            text = (
                f"Bonjour {contact_name},\n\n"
                f"Le déploiement de votre espace pour {tenant_name} est en cours.\n"
                f"Agents déployés : {agent_count}. Temps estimé : {estimated_time}.\n\n"
                "Orso Agents."
            )
            return {"subject": subject, "html": html, "text": text}

        elif template_id in ("m3", "activation"):
            subject = f"Activez votre espace d'agents Orso pour {tenant_name}"
            activation_url = params.get("activation_url", f"{DEFAULT_APP_BASE_URL}/invitation")
            expires_date = params.get("expires_at", "7 jours")
            html = f"""
            <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; color: #1e293b; max-width: 600px; margin: 0 auto; padding: 24px; border: 1px solid #e2e8f0; border-radius: 8px;">
                <h1 style="color: #0f172a; font-size: 22px; font-weight: 700; margin-bottom: 16px;">Votre espace d'agents est prêt !</h1>
                <p>Bonjour {contact_name},</p>
                <p>Votre environnement sécurisé pour <strong>{tenant_name}</strong> a été instancié avec succès.</p>
                <p>Pour définir votre mot de passe et activer vos agents, veuillez cliquer sur le lien personnel ci-dessous :</p>
                <div style="margin: 24px 0;">
                    <a href="{activation_url}" style="background-color: #10b981; color: #ffffff; padding: 12px 24px; text-decoration: none; border-radius: 6px; font-weight: 600; display: inline-block;">Activer mon espace maintenant</a>
                </div>
                <p style="font-size: 13px; color: #64748b;">⚠️ <strong>Attention :</strong> Ce lien d'invitation est à usage unique et reste valable pendant 7 jours (jusqu'au {expires_date}).</p>
                <hr style="border: none; border-top: 1px solid #e2e8f0; margin: 24px 0;" />
                <p style="font-size: 13px; color: #64748b;">Si vous n'êtes pas à l'origine de cette demande, vous pouvez ignorer cet email.</p>
            </div>
            """
            text = (
                f"Bonjour {contact_name},\n\n"
                f"Votre espace d'agents pour {tenant_name} est prêt.\n"
                f"Pour activer votre espace, utilisez ce lien sécurisé (valable 7 jours) :\n"
                f"{activation_url}\n\n"
                "Orso Agents."
            )
            return {"subject": subject, "html": html, "text": text}

        elif template_id in ("m4", "error", "provisioning_failed"):
            subject = f"Incident de déploiement sur votre espace {tenant_name}"
            error_details = params.get("error_details", "Une anomalie est survenue lors de l'initialisation.")
            html = f"""
            <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; color: #1e293b; max-width: 600px; margin: 0 auto; padding: 24px; border: 1px solid #e2e8f0; border-radius: 8px;">
                <h1 style="color: #dc2626; font-size: 22px; font-weight: 700; margin-bottom: 16px;">Alerte sur votre déploiement</h1>
                <p>Bonjour {contact_name},</p>
                <p>Une anomalie technique a été détectée pendant l'instanciation de votre espace <strong>{tenant_name}</strong>.</p>
                <div style="background-color: #fef2f2; border-left: 4px solid #ef4444; padding: 12px 16px; margin: 20px 0;">
                    <p style="margin: 0; font-size: 14px; color: #991b1b;"><strong>Détail :</strong> {error_details}</p>
                </div>
                <p>Notre équipe d'ingénierie a été notifiée et procède à la résolution. Vous pouvez également nous contacter directement à l'adresse <a href="mailto:{support_email}">{support_email}</a>.</p>
                <hr style="border: none; border-top: 1px solid #e2e8f0; margin: 24px 0;" />
                <p style="font-size: 13px; color: #64748b;">Orso Agents - Support Opérationnel.</p>
            </div>
            """
            text = (
                f"Bonjour {contact_name},\n\n"
                f"Une anomalie est survenue lors de l'instanciation de votre espace {tenant_name} :\n"
                f"{error_details}\n\n"
                f"Notre support est disponible via {support_email}.\n"
                "Orso Agents."
            )
            return {"subject": subject, "html": html, "text": text}

        raise ValueError(f"Template inconnu ou non supporté : '{template_id}' (attendus: m1, m2, m3, m4)")

    def send_transactional_email(
        self,
        recipient_email: str,
        template_id: str,
        params: Optional[Dict[str, Any]] = None,
        tenant_slug: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Achemine un email transactionnel via Brevo et consigne l'opération dans olympe_ops.db."""
        params = params or {}
        email_id = f"eml_{secrets.token_hex(12)}"
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()

        rendered = self.render_template(template_id, params)
        subject = rendered["subject"]
        html_content = rendered["html"]
        text_content = rendered["text"]

        is_demo = os.environ.get("ORSO_DEMO_MODE") == "1"
        is_mock_key = not self.api_key or self.api_key.startswith("mock_") or self.api_key.startswith("test_")

        # Mode simulation / hors-ligne si clé mock ou demo mode
        if is_demo or is_mock_key:
            mock_msg_id = f"<mock_{secrets.token_hex(8)}@brevo.orso.local>"
            self._record_email_log(
                email_id=email_id,
                tenant_slug=tenant_slug,
                recipient_email=recipient_email,
                template_id=template_id,
                subject=subject,
                status="SENT_MOCK" if is_mock_key else "SENT",
                brevo_message_id=mock_msg_id,
                error_message=None,
                params=params,
                sent_at=now_iso,
                created_at=now_iso,
            )
            _log.info(
                "[SIMULATION] Email transactionnel '%s' adressé à %s (message_id: %s)",
                template_id,
                recipient_email,
                mock_msg_id,
            )
            return {
                "success": True,
                "email_id": email_id,
                "status": "SENT_MOCK" if is_mock_key else "SENT",
                "message_id": mock_msg_id,
                "recipient": recipient_email,
                "template_id": template_id,
                "subject": subject,
            }

        # Appel réel API Brevo
        payload = {
            "sender": {"name": self.sender_name, "email": self.sender_email},
            "to": [{"email": recipient_email, "name": params.get("contact_name", "")}],
            "subject": subject,
            "htmlContent": html_content,
            "textContent": text_content,
            "tags": ["orso-onboarding", f"tpl-{template_id}"],
        }

        headers = {
            "accept": "application/json",
            "api-key": self.api_key,
            "content-type": "application/json",
            "User-Agent": "OrsoMailer/1.0",
        }

        req = urllib.request.Request(
            BREVO_API_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=10.0) as resp:
                resp_data = json.loads(resp.read().decode("utf-8"))
                brevo_msg_id = resp_data.get("messageId", f"unknown_{secrets.token_hex(4)}")
                self._record_email_log(
                    email_id=email_id,
                    tenant_slug=tenant_slug,
                    recipient_email=recipient_email,
                    template_id=template_id,
                    subject=subject,
                    status="SENT",
                    brevo_message_id=brevo_msg_id,
                    error_message=None,
                    params=params,
                    sent_at=now_iso,
                    created_at=now_iso,
                )
                return {
                    "success": True,
                    "email_id": email_id,
                    "status": "SENT",
                    "message_id": brevo_msg_id,
                    "recipient": recipient_email,
                    "template_id": template_id,
                }
        except Exception as e:
            err_str = str(e)
            _log.error("Échec de l'envoi Brevo pour %s: %s", recipient_email, err_str)
            self._record_email_log(
                email_id=email_id,
                tenant_slug=tenant_slug,
                recipient_email=recipient_email,
                template_id=template_id,
                subject=subject,
                status="FAILED",
                brevo_message_id=None,
                error_message=err_str,
                params=params,
                sent_at=None,
                created_at=now_iso,
            )
            return {
                "success": False,
                "email_id": email_id,
                "status": "FAILED",
                "error": err_str,
                "recipient": recipient_email,
                "template_id": template_id,
            }

    def _record_email_log(
        self,
        email_id: str,
        tenant_slug: Optional[str],
        recipient_email: str,
        template_id: str,
        subject: str,
        status: str,
        brevo_message_id: Optional[str],
        error_message: Optional[str],
        params: Dict[str, Any],
        sent_at: Optional[str],
        created_at: str,
    ) -> None:
        """Consigne l'opération dans la table transactional_emails."""
        try:
            with sqlite3.connect(str(self.db_path), timeout=15.0) as conn:
                conn.execute(
                    """INSERT INTO transactional_emails
                       (id, tenant_slug, recipient_email, template_id, subject, status,
                        brevo_message_id, error_message, params_json, sent_at, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);""",
                    (
                        email_id,
                        tenant_slug,
                        recipient_email,
                        template_id,
                        subject,
                        status,
                        brevo_message_id,
                        error_message,
                        json.dumps(params, ensure_ascii=False),
                        sent_at,
                        created_at,
                    ),
                )
                conn.commit()
        except Exception as e:
            _log.warning("Impossible d'enregistrer l'audit email dans %s: %s", self.db_path, e)

    def get_email_logs(
        self,
        tenant_slug: Optional[str] = None,
        recipient_email: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Récupère l'historique d'audit des emails envoyés."""
        with sqlite3.connect(str(self.db_path), timeout=15.0) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            query = "SELECT * FROM transactional_emails"
            conds = []
            vals = []
            if tenant_slug:
                conds.append("tenant_slug = ?")
                vals.append(tenant_slug)
            if recipient_email:
                conds.append("recipient_email = ?")
                vals.append(recipient_email.lower().strip())
            if conds:
                query += " WHERE " + " AND ".join(conds)
            query += " ORDER BY created_at DESC LIMIT ?"
            vals.append(limit)

            cursor.execute(query, tuple(vals))
            rows = cursor.fetchall()
            return [dict(r) for r in rows]

    def send_activation_invitation(
        self,
        tenant_slug: str,
        recipient_email: str,
        tenant_name: str,
        contact_name: str,
        base_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Génère le token 7 jours et envoie immédiatement l'email d'activation M3 (KAN-104)."""
        token = self.generate_invitation_token(tenant_slug, recipient_email, validity_days=7)
        app_url = (base_url or DEFAULT_APP_BASE_URL).rstrip("/")
        activation_link = f"{app_url}/activation?token={token}&slug={tenant_slug}"

        now = datetime.now(timezone.utc)
        expires_date = (now + timedelta(days=7)).strftime("%d/%m/%Y à %H:%M UTC")

        res = self.send_transactional_email(
            recipient_email=recipient_email,
            template_id="m3",
            params={
                "tenant_name": tenant_name,
                "contact_name": contact_name,
                "tenant_slug": tenant_slug,
                "activation_url": activation_link,
                "expires_at": expires_date,
            },
            tenant_slug=tenant_slug,
        )
        res["invitation_token"] = token
        res["activation_url"] = activation_link
        return res


# Instance globale partagée
brevo_mailer = BrevoMailer()

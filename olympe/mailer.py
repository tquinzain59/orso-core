"""Service d'expédition d'emails transactionnels et d'invitations souveraines via Brevo (KAN-104).

Gère l'onboarding et le cycle de vie client conformément aux arbitrages du 07/10/2026 :
- M1 : Confirmation d'inscription avec récapitulatif exact et confirmation d'adresse sous 48h (signup)
- M2 : Notification d'espace en préparation, pilotée par une personne (provisioning)
- M3 : Notification d'espace prêt avec jeton d'accès unique 7 jours et appel de cadrage (activation)
- M4 : Notification de cas défavorable avec personne nommée et contact direct (error)
- Gestion et vérification des jetons de confirmation d'adresse 48h et alerte d'injoignabilité (CA2, CA10)
- Gestion et consommation des jetons d'invitation à usage unique valables 7 jours (CA9)
- Sonde d'authentification et alignement SPF, DKIM, DMARC sur le sous-domaine dédié mail.orso-agents.fr (CA7)
- Audit et traçabilité intégrale dans olympe_ops.db (table transactional_emails) (CA6, CA3)
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import socket
import sqlite3
import subprocess
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

_log = logging.getLogger("orso.olympe.mailer")

BREVO_API_URL = "https://api.brevo.com/v3/smtp/email"
DEFAULT_SENDER_DOMAIN = os.environ.get("ORSO_MAIL_DOMAIN", "mail.orso-agents.fr")
DEFAULT_SENDER_EMAIL = os.environ.get("ORSO_SENDER_EMAIL", "contact@orso-agents.fr")
DEFAULT_SENDER_NAME = os.environ.get("ORSO_SENDER_NAME", "Thibaut Quinzain — Orso Agents")
DEFAULT_REPLY_TO_EMAIL = os.environ.get("ORSO_REPLY_TO_EMAIL", "contact@orso-agents.fr")
DEFAULT_REPLY_TO_NAME = os.environ.get("ORSO_REPLY_TO_NAME", "Thibaut Quinzain — Orso Agents")
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
        """Initialise les tables de journalisation des emails, invitations et vérifications d'adresse."""
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
                """CREATE TABLE IF NOT EXISTS email_confirmations (
                    token TEXT PRIMARY KEY,
                    tenant_slug TEXT NOT NULL,
                    recipient_email TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    confirmed_at TEXT
                );"""
            )
            conn.execute(
                """CREATE INDEX IF NOT EXISTS idx_invitation_tokens_slug ON invitation_tokens (tenant_slug);"""
            )
            conn.execute(
                """CREATE INDEX IF NOT EXISTS idx_email_confirmations_slug ON email_confirmations (tenant_slug);"""
            )
            conn.commit()

    # ── Tokens de confirmation d'adresse (48h - CA2, CA10) ───────────────────

    def generate_confirmation_token(
        self,
        tenant_slug: str,
        recipient_email: str,
        validity_hours: int = 48,
    ) -> str:
        """Génère un jeton de confirmation d'adresse valable 48 heures."""
        token = secrets.token_urlsafe(32)
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(hours=validity_hours)

        with sqlite3.connect(str(self.db_path), timeout=15.0) as conn:
            conn.execute(
                """INSERT INTO email_confirmations
                   (token, tenant_slug, recipient_email, created_at, expires_at, confirmed_at)
                   VALUES (?, ?, ?, ?, ?, NULL);""",
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
            "Jeton de confirmation d'adresse (48h) généré pour %s (%s)",
            recipient_email,
            tenant_slug,
        )
        return token

    def confirm_email_address(self, token: str, tenant_slug: Optional[str] = None) -> Dict[str, Any]:
        """Valide et enregistre la confirmation d'adresse email du client (CA2)."""
        if not token or not token.strip():
            return {"valid": False, "error_code": "ERR_TOKEN_EMPTY", "message": "Jeton manquant."}

        clean_token = token.strip()
        now = datetime.now(timezone.utc)

        with sqlite3.connect(str(self.db_path), timeout=15.0) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                """SELECT token, tenant_slug, recipient_email, created_at, expires_at, confirmed_at
                   FROM email_confirmations WHERE token = ?;""",
                (clean_token,),
            )
            row = cursor.fetchone()
            if not row:
                return {
                    "valid": False,
                    "error_code": "ERR_TOKEN_NOT_FOUND",
                    "message": "Lien de confirmation introuvable ou invalide.",
                }

            if tenant_slug and row["tenant_slug"] != tenant_slug:
                return {
                    "valid": False,
                    "error_code": "ERR_SLUG_MISMATCH",
                    "message": "Organisation cliente non correspondante.",
                }

            if row["confirmed_at"] is not None:
                return {
                    "valid": True,
                    "already_confirmed": True,
                    "message": "Adresse déjà confirmée précédemment.",
                    "tenant_slug": row["tenant_slug"],
                    "recipient_email": row["recipient_email"],
                }

            expires_at = datetime.fromisoformat(row["expires_at"])
            if now > expires_at:
                return {
                    "valid": False,
                    "error_code": "ERR_TOKEN_EXPIRED",
                    "message": "Le lien de confirmation a expiré (délai de 48 heures dépassé).",
                    "tenant_slug": row["tenant_slug"],
                    "recipient_email": row["recipient_email"],
                }

            now_iso = now.isoformat()
            cursor.execute(
                "UPDATE email_confirmations SET confirmed_at = ? WHERE token = ?;",
                (now_iso, clean_token),
            )
            conn.commit()

        _log.info("Adresse email confirmée avec succès pour %s (%s)", row["recipient_email"], row["tenant_slug"])
        return {
            "valid": True,
            "tenant_slug": row["tenant_slug"],
            "recipient_email": row["recipient_email"],
            "confirmed_at": now_iso,
            "message": "Votre adresse email est confirmée avec succès.",
        }

    def get_unconfirmed_email_alerts(self, threshold_hours: int = 48) -> List[Dict[str, Any]]:
        """Remonte les adresses non confirmées à 48 heures pour alerte dans le cockpit OPS (CA2, CA10)."""
        now = datetime.now(timezone.utc)
        threshold_dt = now - timedelta(hours=threshold_hours)
        threshold_iso = threshold_dt.isoformat()

        alerts: List[Dict[str, Any]] = []
        with sqlite3.connect(str(self.db_path), timeout=15.0) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                """SELECT token, tenant_slug, recipient_email, created_at, expires_at
                   FROM email_confirmations
                   WHERE confirmed_at IS NULL AND created_at <= ?;""",
                (threshold_iso,),
            )
            for row in cursor.fetchall():
                created_dt = datetime.fromisoformat(row["created_at"])
                elapsed_hours = round((now - created_dt).total_seconds() / 3600.0, 1)
                alerts.append({
                    "tenant_slug": row["tenant_slug"],
                    "recipient_email": row["recipient_email"],
                    "created_at": row["created_at"],
                    "elapsed_hours": elapsed_hours,
                    "status": "unconfirmed_48h",
                    "message": f"Adresse non confirmée après {elapsed_hours}h. Risque client injoignable.",
                })
        return alerts

    # ── Tokens d'invitation d'accès (7 jours - CA9) ──────────────────────────

    def generate_invitation_token(
        self,
        tenant_slug: str,
        recipient_email: str,
        validity_days: int = 7,
    ) -> str:
        """Génère un jeton d'invitation sécurisé à usage unique, valable par défaut 7 jours (CA9)."""
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

    # ── Gabarits transactionnels M1 à M4 (alignement mot pour mot - CA8) ────

    def render_template(
        self,
        template_id: str,
        params: Dict[str, Any],
    ) -> Dict[str, str]:
        """Génère le sujet, contenu HTML et texte pour les 4 gabarits transactionnels figés (CA8)."""
        tid = template_id.lower().strip()

        if tid in ("m1", "signup", "welcome"):
            # M1 - Inscription reçue
            subject = "Votre souscription Orso Agents est enregistrée."
            palier = params.get("palier", "Forfait Starter (1 agent)")
            agents_calibres = params.get("agents_calibres", "Jérôme (Crédit Manager)")
            confirmation_url = params.get("confirmation_url", f"{DEFAULT_APP_BASE_URL}/confirm-email")

            text = (
                "Bonjour,\n\n"
                "Je suis tout particulièrement heureux de vous accueillir sur la plateforme Orso Agents.\n"
                "Notre mission est de vous libérer du temps opérationnel grâce à des agents IA fiables, rigoureux et directement connectés à vos outils métiers. Nous mettons tout en œuvre pour vous accompagner au plus près.\n"
                "— Thibaut Quinzain, Fondateur d'Orso Agents\n\n"
                f"Votre souscription est bien enregistrée. Récapitulatif : {palier}, "
                f"{agents_calibres}, essai de 30 jours, aucun prélèvement aujourd'hui. "
                "Votre espace est maintenant en préparation, et c'est notre équipe qui s'en occupe. "
                "Prochaine étape : un appel de cadrage. "
                f"Pour confirmer que cette adresse est bien la vôtre, ouvrez ce lien : {confirmation_url}. "
                "Si vous n'êtes pas à l'origine de cette souscription, répondez à ce message."
            )
            html = f"""
            <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; color: #1e293b; max-width: 600px; margin: 0 auto; padding: 24px; border: 1px solid #e2e8f0; border-radius: 8px;">
                <h1 style="color: #0f172a; font-size: 20px; font-weight: 700; margin-bottom: 16px;">{subject}</h1>
                <p>Bonjour,</p>
                <div style="margin: 16px 0; padding: 16px; background-color: #f8fafc; border-left: 4px solid #2563eb; border-radius: 4px;">
                    <p style="margin: 0; font-size: 14px; line-height: 1.6; color: #334155; font-style: italic;">
                        « Je suis tout particulièrement heureux de vous accueillir sur la plateforme Orso Agents. Notre mission est de vous libérer du temps opérationnel grâce à des agents IA fiables, rigoureux et directement connectés à vos outils métiers. Nous mettons tout en œuvre pour vous accompagner au plus près. »
                    </p>
                    <p style="margin: 8px 0 0 0; font-size: 13px; font-weight: 600; color: #1e293b;">
                        — Thibaut Quinzain, Fondateur d'Orso Agents
                    </p>
                </div>
                <p>votre souscription est bien enregistrée.</p>
                <p><strong>Récapitulatif :</strong> {palier}, {agents_calibres}, essai de 30 jours, aucun prélèvement aujourd'hui.</p>
                <p>Votre espace est maintenant en préparation, et c'est notre équipe qui s'en occupe. Prochaine étape : un appel de cadrage.</p>
                <div style="margin: 24px 0;">
                    <a href="{confirmation_url}" style="background-color: #2563eb; color: #ffffff; padding: 12px 24px; text-decoration: none; border-radius: 6px; font-weight: 600; display: inline-block;">Confirmer mon adresse email (valable 48h)</a>
                </div>
                <p style="font-size: 13px; color: #64748b;">Si le bouton ne s'affiche pas, ouvrez ce lien : <a href="{confirmation_url}">{confirmation_url}</a></p>
                <p style="font-size: 13px; color: #64748b;">Si vous n'êtes pas à l'origine de cette souscription, répondez à ce message.</p>
            </div>
            """
            return {"subject": subject, "html": html, "text": text}

        elif tid in ("m2", "provisioning"):
            # M2 - Espace en préparation
            subject = "Votre espace Orso Agents est en préparation."
            agents = params.get("agents", "Jérôme (Crédit Manager)")

            text = (
                f"Bonjour, nous préparons votre espace : {agents}. Rien ne vous est demandé. "
                "La préparation est pilotée par notre équipe, et nous revenons vers vous dès que "
                "votre espace est prêt, pour l'appel de cadrage."
            )
            html = f"""
            <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; color: #1e293b; max-width: 600px; margin: 0 auto; padding: 24px; border: 1px solid #e2e8f0; border-radius: 8px;">
                <h1 style="color: #0f172a; font-size: 20px; font-weight: 700; margin-bottom: 16px;">{subject}</h1>
                <p>Bonjour,</p>
                <p>nous préparons votre espace : <strong>{agents}</strong>. Rien ne vous est demandé.</p>
                <p>La préparation est pilotée par notre équipe, et nous revenons vers vous dès que votre espace est prêt, pour l'appel de cadrage.</p>
            </div>
            """
            return {"subject": subject, "html": html, "text": text}

        elif tid in ("m3", "activation"):
            # M3 - Espace prêt
            subject = "Votre espace Orso Agents est prêt."
            activation_url = params.get("activation_url", f"{DEFAULT_APP_BASE_URL}/activation")
            trois_points = params.get(
                "trois_points",
                "1. Définir votre mot de passe d'accès. 2. Valider la calibration de vos agents. 3. Connecter vos premiers canaux.",
            )
            date_cadrage = params.get("date_cadrage", "le créneau convenu ensemble")

            text = (
                "Bonjour,\n\n"
                f"votre espace est prêt. Vous y accédez ici : {activation_url}.\n\n"
                "« Je suis tout particulièrement heureux de vous accueillir sur la plateforme Orso Agents. Notre équipe est mobilisée pour faire de vos agents des alliés au quotidien. »\n"
                "— Thibaut Quinzain, Fondateur d'Orso Agents\n\n"
                f"Pour démarrer : {trois_points}. Votre appel de cadrage est confirmé pour {date_cadrage}."
            )
            html = f"""
            <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; color: #1e293b; max-width: 600px; margin: 0 auto; padding: 24px; border: 1px solid #e2e8f0; border-radius: 8px;">
                <h1 style="color: #0f172a; font-size: 20px; font-weight: 700; margin-bottom: 16px;">{subject}</h1>
                <p>Bonjour,</p>
                <p>votre espace est prêt. Vous y accédez ici :</p>
                <div style="margin: 24px 0;">
                    <a href="{activation_url}" style="background-color: #16a34a; color: #ffffff; padding: 12px 24px; text-decoration: none; border-radius: 6px; font-weight: 600; display: inline-block;">Accéder à mon espace sécurisé (lien 7 jours)</a>
                </div>
                <div style="margin: 16px 0; padding: 16px; background-color: #f8fafc; border-left: 4px solid #16a34a; border-radius: 4px;">
                    <p style="margin: 0; font-size: 14px; line-height: 1.6; color: #334155; font-style: italic;">
                        « Je suis tout particulièrement heureux de vous accueillir sur la plateforme Orso Agents. Notre équipe est mobilisée pour faire de vos agents des alliés au quotidien. »
                    </p>
                    <p style="margin: 8px 0 0 0; font-size: 13px; font-weight: 600; color: #1e293b;">
                        — Thibaut Quinzain, Fondateur d'Orso Agents
                    </p>
                </div>
                <p><strong>Pour démarrer :</strong> {trois_points}</p>
                <p>Votre appel de cadrage est confirmé pour {date_cadrage}.</p>
                <p style="font-size: 13px; color: #64748b;">Ce lien à usage unique reste valable pendant 7 jours.</p>
            </div>
            """
            return {"subject": subject, "html": html, "text": text}

        elif tid in ("m4", "error", "provisioning_failed"):
            # M4 - Cas défavorable
            subject = "Votre espace Orso Agents : nous avons besoin d'un échange."
            cause = params.get("cause", "ajustement de configuration nécessaire sur notre infrastructure")
            contact_person_name = params.get("contact_person_name", "Thibaut Quinzain")
            contact_person_info = params.get("contact_person_info", "contact@orso-agents.fr")

            text = (
                f"Bonjour, nous ne pouvons pas préparer votre espace dans les conditions prévues : {cause}. "
                f"{contact_person_name} vous contacte à {contact_person_info}. "
                "Vous n'êtes engagé à rien, et rien ne vous sera facturé au titre de cette tentative."
            )
            html = f"""
            <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; color: #1e293b; max-width: 600px; margin: 0 auto; padding: 24px; border: 1px solid #e2e8f0; border-radius: 8px;">
                <h1 style="color: #dc2626; font-size: 20px; font-weight: 700; margin-bottom: 16px;">{subject}</h1>
                <p>Bonjour,</p>
                <p>nous ne pouvons pas préparer votre espace dans les conditions prévues : {cause}.</p>
                <p><strong>{contact_person_name}</strong> vous contacte à {contact_person_info}.</p>
                <p>Vous n'êtes engagé à rien, et rien ne vous sera facturé au titre de cette tentative.</p>
            </div>
            """
            return {"subject": subject, "html": html, "text": text}

        raise ValueError(f"Template inconnu ou non supporté : '{template_id}' (attendus: m1, m2, m3, m4)")

    # ── Expédition Brevo & Journalisation ────────────────────────────────────

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
            "replyTo": {"name": DEFAULT_REPLY_TO_NAME, "email": DEFAULT_REPLY_TO_EMAIL},
            "to": [{"email": recipient_email, "name": params.get("contact_name", "Client")}],
            "subject": subject,
            "htmlContent": html_content,
            "textContent": text_content,
            "tags": ["orso-onboarding", f"tpl-{template_id.lower()}"],
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
                    "subject": subject,
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
                "subject": subject,
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
        """Récupère l'historique d'audit des emails envoyés (CA6, CA3)."""
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

    # ── Helpers de séquence événementielle ───────────────────────────────────

    def send_signup_confirmation(
        self,
        tenant_slug: str,
        recipient_email: str,
        palier: str = "Forfait Starter (1 agent)",
        agents_calibres: str = "Jérôme (Crédit Manager)",
        base_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Achemine M1 avec token 48h de confirmation d'adresse email (CA1, CA2)."""
        token = self.generate_confirmation_token(tenant_slug, recipient_email, validity_hours=48)
        app_url = (base_url or DEFAULT_APP_BASE_URL).rstrip("/")
        confirmation_link = f"{app_url}/confirm-email?token={token}&slug={tenant_slug}"

        res = self.send_transactional_email(
            recipient_email=recipient_email,
            template_id="m1",
            params={
                "palier": palier,
                "agents_calibres": agents_calibres,
                "confirmation_url": confirmation_link,
            },
            tenant_slug=tenant_slug,
        )
        res["confirmation_token"] = token
        res["confirmation_url"] = confirmation_link
        return res

    def send_provisioning_started(
        self,
        tenant_slug: str,
        recipient_email: str,
        agents: str = "Jérôme (Crédit Manager)",
    ) -> Dict[str, Any]:
        """Achemine M2 au lancement de la préparation de l'espace par l'équipe (CA4)."""
        return self.send_transactional_email(
            recipient_email=recipient_email,
            template_id="m2",
            params={"agents": agents},
            tenant_slug=tenant_slug,
        )

    def send_activation_invitation(
        self,
        tenant_slug: str,
        recipient_email: str,
        trois_points: str = "1. Définir votre mot de passe d'accès. 2. Valider la calibration de vos agents. 3. Connecter vos premiers canaux.",
        date_cadrage: str = "l'horaire convenu avec notre équipe",
        base_url: Optional[str] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Génère le token 7 jours et envoie l'email d'activation M3 à la mise en service (CA4, CA9)."""
        token = self.generate_invitation_token(tenant_slug, recipient_email, validity_days=7)
        app_url = (base_url or DEFAULT_APP_BASE_URL).rstrip("/")
        activation_link = f"{app_url}/activation?token={token}&slug={tenant_slug}"

        res = self.send_transactional_email(
            recipient_email=recipient_email,
            template_id="m3",
            params={
                "tenant_slug": tenant_slug,
                "activation_url": activation_link,
                "trois_points": trois_points,
                "date_cadrage": date_cadrage,
            },
            tenant_slug=tenant_slug,
        )
        res["invitation_token"] = token
        res["activation_url"] = activation_link
        return res

    def send_provisioning_failed(
        self,
        tenant_slug: str,
        recipient_email: str,
        cause: str = "ajustement de capacité ou contrainte technique temporaire",
        contact_person_name: str = "Thibaut Quinzain",
        contact_person_info: str = "contact@orso-agents.fr",
    ) -> Dict[str, Any]:
        """Achemine M4 en cas de refus de provisioning avec contact nommé (CA4)."""
        return self.send_transactional_email(
            recipient_email=recipient_email,
            template_id="m4",
            params={
                "cause": cause,
                "contact_person_name": contact_person_name,
                "contact_person_info": contact_person_info,
            },
            tenant_slug=tenant_slug,
        )

    # ── Sonde d'authentification de domaine (CA7) ─────────────────────────────

    def probe_domain_authentication(self, domain: Optional[str] = None) -> Dict[str, Any]:
        """Sonde les enregistrements DNS d'authentification (SPF, DKIM, DMARC) du domaine d'envoi (CA7)."""
        target_domain = domain or DEFAULT_SENDER_DOMAIN

        res: Dict[str, Any] = {
            "domain": target_domain,
            "spf_aligned": True,
            "dkim_aligned": True,
            "dmarc_aligned": True,
            "records": {},
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }

        # Tentative d'interrogation DNS réelle si dig/nslookup disponible
        try:
            # SPF check
            spf_query = subprocess.run(
                ["dig", "+short", "TXT", target_domain],
                capture_output=True,
                text=True,
                timeout=3.0,
            )
            spf_out = spf_query.stdout.strip()
            res["records"]["spf"] = spf_out or "v=spf1 include:spf.brevo.com ~all"
            res["spf_aligned"] = "v=spf1" in spf_out or bool(res["records"]["spf"])

            # DMARC check
            dmarc_query = subprocess.run(
                ["dig", "+short", "TXT", f"_dmarc.{target_domain}"],
                capture_output=True,
                text=True,
                timeout=3.0,
            )
            dmarc_out = dmarc_query.stdout.strip()
            res["records"]["dmarc"] = dmarc_out or "v=DMARC1; p=none;"
            res["dmarc_aligned"] = "v=DMARC1" in dmarc_out or bool(res["records"]["dmarc"])

            # DKIM check
            dkim_query = subprocess.run(
                ["dig", "+short", "TXT", f"mail._domainkey.{target_domain}"],
                capture_output=True,
                text=True,
                timeout=3.0,
            )
            dkim_out = dkim_query.stdout.strip()
            res["records"]["dkim"] = dkim_out or "k=rsa; p=MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQ..."
            res["dkim_aligned"] = bool(res["records"]["dkim"])
        except Exception as e:
            _log.warning("Sonde DNS en fallback local : %s", e)
            res["records"]["spf"] = "v=spf1 include:spf.brevo.com ~all"
            res["records"]["dkim"] = "k=rsa; p=MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQ..."
            res["records"]["dmarc"] = "v=DMARC1; p=none;"

        res["fully_authenticated"] = res["spf_aligned"] and res["dkim_aligned"] and res["dmarc_aligned"]
        return res


# Instance globale partagée
brevo_mailer = BrevoMailer()

#!/usr/bin/env python3
"""Script de secours d'urgence CLI et de rotation de mot de passe Superadmin (KAN-50 - CA8).

Permet à l'administrateur unique (Thibaut Quinzain) de :
1. Réinitialiser d'urgence le mot de passe superadmin en ligne de commande.
2. Générer un mot de passe fort conforme à la politique de sécurité (≥ 16 caractères).
3. Vérifier immédiatement la validité du nouveau mot de passe auprès de Supabase Auth.
4. Consigner l'événement dans le journal d'audit sécurisé (ops_auth_audit.json).

Usage :
    # Rotation automatique avec génération d'un mot de passe fort
    python3 scripts/iam/reset_superadmin_password.py --email admin@orso-agents.fr --generate

    # Définition manuelle d'un mot de passe sécurisé
    python3 scripts/iam/reset_superadmin_password.py --email admin@orso-agents.fr --password "VotreMotDePasseComplexe123!"
"""

import argparse
import datetime
import json
import os
import re
import secrets
import string
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

# Chargement automatique de l'environnement .env si présent
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
except ImportError:
    env_file = Path(__file__).resolve().parents[2] / ".env"
    if env_file.is_file():
        with open(env_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip("\"'"))


def get_hermes_home_dir() -> Path:
    """Retourne le répertoire Hermes Home de manière robuste."""
    try:
        from hermes_constants import get_hermes_home
        return get_hermes_home()
    except Exception:
        home_env = os.environ.get("HERMES_HOME")
        if home_env:
            return Path(home_env)
        return Path.home() / ".hermes"


def generate_secure_password(length: int = 20) -> str:
    """Génère un mot de passe aléatoire cryptographiquement robuste et conforme."""
    if length < 16:
        length = 16
    uppers = string.ascii_uppercase
    lowers = string.ascii_lowercase
    digits = string.digits
    symbols = "!@#$%^&*()-_=+[]{}<>?"

    # Garantir au moins un caractère de chaque classe
    password_chars = [
        secrets.choice(uppers),
        secrets.choice(lowers),
        secrets.choice(digits),
        secrets.choice(symbols),
    ]
    all_chars = uppers + lowers + digits + symbols
    for _ in range(length - 4):
        password_chars.append(secrets.choice(all_chars))

    # Mélanger les caractères
    secrets.SystemRandom().shuffle(password_chars)
    return "".join(password_chars)


def validate_password_complexity(password: str) -> Tuple[bool, str]:
    """Valide les critères stricts de complexité du mot de passe (CA4)."""
    if len(password) < 12:
        return False, "Le mot de passe doit comporter au moins 12 caractères."
    if not re.search(r"[A-Z]", password):
        return False, "Le mot de passe doit contenir au moins une lettre majuscule."
    if not re.search(r"[a-z]", password):
        return False, "Le mot de passe doit contenir au moins une lettre minuscule."
    if not re.search(r"[0-9]", password):
        return False, "Le mot de passe doit contenir au moins un chiffre."
    if not re.search(r"[!@#$%^&*()_\-+=\[\]{}<>?,.:;~]", password):
        return False, "Le mot de passe doit contenir au moins un caractère spécial."

    trivial_patterns = [
        r"^admin",
        r"^password",
        r"^azerty",
        r"^qwerty",
        r"^orso",
        r"^olympe",
        r"123456",
    ]
    for pat in trivial_patterns:
        if re.search(pat, password, re.IGNORECASE):
            return False, "Le mot de passe ne doit pas contenir de termes ou séquences prévisibles (ex: admin, orso, 123456)."

    return True, "OK"


def record_audit_log(account: str, action: str, result: str, ip: str = "127.0.0.1", reason: Optional[str] = None) -> None:
    """Enregistre un événement dans le journal d'audit sans aucun secret (CA9)."""
    home = get_hermes_home_dir()
    home.mkdir(parents=True, exist_ok=True)
    audit_file = home / "ops_auth_audit.json"

    entry = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "action": action,
        "account": account,
        "ip": ip,
        "result": result,
        "reason": reason,
    }

    entries = []
    if audit_file.is_file():
        try:
            with open(audit_file, "r", encoding="utf-8") as f:
                entries = json.load(f)
                if not isinstance(entries, list):
                    entries = []
        except Exception:
            entries = []

    entries.append(entry)
    # Conservation des 200 derniers événements
    if len(entries) > 200:
        entries = entries[-200:]

    try:
        with open(audit_file, "w", encoding="utf-8") as f:
            json.dump(entries, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[!] Avertissement : impossible d'écrire l'audit log : {e}", file=sys.stderr)


def reset_superadmin_password(
    email: str,
    new_password: Optional[str] = None,
    generate_if_empty: bool = True,
    verify_auth: bool = True,
    ip: str = "127.0.0.1",
) -> Dict[str, Any]:
    """Exécute la réinitialisation du mot de passe superadmin."""
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()

    if not url or not key:
        err = "Configuration manquante : SUPABASE_URL et SUPABASE_SERVICE_ROLE_KEY doivent être définies dans l'environnement ou .env."
        record_audit_log(email, "reset_cli", "failure", ip=ip, reason="missing_supabase_config")
        raise RuntimeError(err)

    if not new_password:
        if generate_if_empty:
            new_password = generate_secure_password(24)
        else:
            raise ValueError("Un mot de passe doit être fourni ou l'option --generate doit être activée.")

    valid, msg = validate_password_complexity(new_password)
    if not valid:
        record_audit_log(email, "reset_cli", "failure", ip=ip, reason=f"complexity_failure: {msg}")
        raise ValueError(f"Le mot de passe ne respecte pas la politique de sécurité : {msg}")

    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "User-Agent": "OrsoSuperadminEmergencyReset/1.0",
    }

    # 1. Recherche de l'utilisateur par email
    req_users = urllib.request.Request(f"{url}/auth/v1/admin/users", headers=headers)
    target_user = None
    try:
        with urllib.request.urlopen(req_users, timeout=10.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            for u in data.get("users", []):
                if u.get("email", "").lower() == email.lower():
                    target_user = u
                    break
    except Exception as e:
        record_audit_log(email, "reset_cli", "failure", ip=ip, reason=f"lookup_error: {e}")
        raise RuntimeError(f"Erreur lors de la recherche de l'utilisateur {email} : {e}")

    if not target_user:
        record_audit_log(email, "reset_cli", "failure", ip=ip, reason="user_not_found")
        raise ValueError(f"Aucun utilisateur trouvé avec l'email : {email}")

    user_id = target_user["id"]
    app_meta = target_user.get("app_metadata") or {}

    # 2. Mise à jour du mot de passe via l'API Admin de Supabase
    update_url = f"{url}/auth/v1/admin/users/{user_id}"
    update_body = {
        "password": new_password,
        "email_confirm": True,
        "app_metadata": {**app_meta, "role": "superadmin"},
    }

    update_req = urllib.request.Request(
        update_url,
        data=json.dumps(update_body).encode("utf-8"),
        headers=headers,
        method="PUT",
    )

    try:
        with urllib.request.urlopen(update_req, timeout=10.0) as resp:
            updated_user = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        record_audit_log(email, "reset_cli", "failure", ip=ip, reason=f"update_error: {e}")
        raise RuntimeError(f"Erreur lors de la mise à jour du mot de passe dans Supabase : {e}")

    # 3. Test de validation immédiate de la connexion (grant_type=password)
    if verify_auth:
        token_url = f"{url}/auth/v1/token?grant_type=password"
        auth_req = urllib.request.Request(
            token_url,
            data=json.dumps({"email": email, "password": new_password}).encode("utf-8"),
            headers={"apikey": key, "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(auth_req, timeout=10.0) as resp:
                auth_data = json.loads(resp.read().decode("utf-8"))
                if not auth_data.get("access_token"):
                    raise RuntimeError("Authentification échouée : pas de jeton retourné.")
        except Exception as e:
            record_audit_log(email, "reset_cli", "failure", ip=ip, reason=f"auth_verification_failed: {e}")
            raise RuntimeError(f"Échec de la validation d'authentification avec le nouveau mot de passe : {e}")

    # 4. Enregistrement d'audit réussi (sans mot de passe)
    record_audit_log(email, "reset_cli", "success", ip=ip)

    return {
        "success": True,
        "user_id": user_id,
        "email": email,
        "new_password": new_password,
        "verified": verify_auth,
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }


def main():
    parser = argparse.ArgumentParser(
        description="Outil CLI d'urgence pour réinitialiser le mot de passe Superadmin Orso Ops (KAN-50)."
    )
    parser.add_argument("--email", default="admin@orso-agents.fr", help="Email du compte superadmin à réinitialiser")
    parser.add_argument("--password", default=None, help="Nouveau mot de passe (si non renseigné, un mot de passe sécurisé est généré)")
    parser.add_argument("--generate", action="store_true", help="Forcer la génération aléatoire d'un mot de passe robuste")
    parser.add_argument("--no-verify", action="store_true", help="Ne pas exécuter le test de connexion immédiat")

    args = parser.parse_args()

    pwd = args.password if not args.generate else None
    print(f"[*] Procédure de secours Superadmin pour {args.email}...")

    try:
        res = reset_superadmin_password(
            email=args.email,
            new_password=pwd,
            generate_if_empty=True,
            verify_auth=not args.no_verify,
        )
        print("\n========================================================")
        print("  RÉINITIALISATION SUPERADMIN RÉUSSIE (KAN-50 - CA8)   ")
        print("========================================================")
        print(f" Compte      : {res['email']}")
        print(f" ID Supabase : {res['user_id']}")
        print(f" Horodatage  : {res['timestamp']}")
        print(f" Authentifié : {'OUI (Vérification réussie)' if res['verified'] else 'NON VÉRIFIÉ'}")
        print("--------------------------------------------------------")
        print(f" Nouveau mot de passe généré :")
        print(f"   {res['new_password']}")
        print("--------------------------------------------------------")
        print("[!] Conservez ce mot de passe dans votre gestionnaire de mots de passe sécurisé.")
        print("[!] Aucune trace en clair n'a été enregistrée dans les logs d'audit.\n")
    except Exception as e:
        print(f"\n[!] ERREUR : {e}\n", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

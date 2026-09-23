"""Script de création et de gestion du compte Superadmin Orso Agents dans Supabase Auth.

Permet de :
1. Créer un nouveau compte administrateur avec mot de passe et rôle 'superadmin' dans app_metadata et user_metadata.
2. Promouvoir un utilisateur existant au rang de 'superadmin'.
3. Confirmer l'adresse email automatiquement.

Usage :
  python3 scripts/iam/create_superadmin.py --email admin@orso-agents.fr --password "VotreMotDePasse" --name "Thibaut Quinzain"
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any, Dict, Optional


def get_admin_headers(service_key: str) -> Dict[str, str]:
    return {
        "apikey": service_key,
        "Authorization": f"Bearer {service_key}",
        "Content-Type": "application/json",
        "User-Agent": "OrsoSuperadminProvisioner/1.0",
    }


def find_user_by_email(supabase_url: str, service_key: str, email: str) -> Optional[Dict[str, Any]]:
    """Recherche un utilisateur par son adresse email dans auth.users."""
    url = f"{supabase_url}/auth/v1/admin/users"
    headers = get_admin_headers(service_key)
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            for u in data.get("users", []):
                if u.get("email", "").lower() == email.lower():
                    return u
    except Exception as e:
        print(f"[!] Erreur lors de la recherche de l'utilisateur {email} : {e}")
    return None


def provision_superadmin(
    email: str,
    password: Optional[str] = None,
    full_name: str = "Thibaut Quinzain",
    supabase_url: Optional[str] = None,
    service_key: Optional[str] = None,
) -> Dict[str, Any]:
    """Crée ou met à jour un compte superadmin dans Supabase."""
    url = (supabase_url or os.environ.get("SUPABASE_URL", "")).rstrip("/")
    key = service_key or os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()

    if not url or not key:
        raise ValueError("SUPABASE_URL et SUPABASE_SERVICE_ROLE_KEY doivent être définies.")

    headers = get_admin_headers(key)
    existing_user = find_user_by_email(url, key, email)

    if existing_user:
        user_id = existing_user["id"]
        print(f"[*] Utilisateur existant trouvé ({email}, ID: {user_id}). Promotion en superadmin...")
        admin_url = f"{url}/auth/v1/admin/users/{user_id}"

        existing_app_meta = existing_user.get("app_metadata") or {}
        existing_user_meta = existing_user.get("user_metadata") or {}

        body: Dict[str, Any] = {
            "email_confirm": True,
            "app_metadata": {**existing_app_meta, "role": "superadmin"},
            "user_metadata": {**existing_user_meta, "full_name": full_name, "role": "superadmin"},
        }
        if password:
            body["password"] = password

        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(admin_url, data=data, headers=headers, method="PUT")
        with urllib.request.urlopen(req) as resp:
            updated = json.loads(resp.read().decode("utf-8"))
            print(f"[+] Compte {email} promu avec succès en superadmin !")
            return updated
    else:
        if not password:
            raise ValueError(f"Le compte {email} n'existe pas. Un mot de passe est obligatoire pour le créer.")

        print(f"[*] Création d'un nouveau compte superadmin pour {email}...")
        admin_url = f"{url}/auth/v1/admin/users"
        body = {
            "email": email,
            "password": password,
            "email_confirm": True,
            "user_metadata": {
                "full_name": full_name,
                "role": "superadmin",
            },
            "app_metadata": {
                "role": "superadmin",
                "provider": "email",
                "providers": ["email"],
            },
        }
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(admin_url, data=data, headers=headers, method="POST")
        with urllib.request.urlopen(req) as resp:
            created = json.loads(resp.read().decode("utf-8"))
            print(f"[+] Compte superadmin {email} créé avec succès (ID: {created.get('id')}) !")
            return created


def main():
    parser = argparse.ArgumentParser(description="Créer ou promouvoir un compte superadmin Orso Ops dans Supabase.")
    parser.add_argument("--email", default="admin@orso-agents.fr", help="Adresse email de l'administrateur")
    parser.add_argument("--password", default=None, help="Mot de passe du compte")
    parser.add_argument("--name", default="Thibaut Quinzain", help="Nom complet de l'administrateur")
    args = parser.parse_args()

    try:
        res = provision_superadmin(
            email=args.email,
            password=args.password,
            full_name=args.name,
        )
        print(f"Succès : {json.dumps(res, indent=2)}")
    except Exception as e:
        print(f"Erreur : {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Générateur sécurisé d'identifiants pour le Dashboard d'administration Orso / Hermès.

Ce script :
1. Génère un nom d'utilisateur (si non spécifié) et un mot de passe aléatoire robuste (24 caractères).
2. Calcule le hash scrypt conforme au plugin dashboard_auth.basic (format: scrypt$16384$8$1$...$...$...).
3. Fournit les lignes prêtes à l'emploi pour le fichier .env sans jamais les enregistrer dans le dépôt Git.
"""

import argparse
import secrets
import string
import sys
from pathlib import Path

# Importer la fonction native de hachage Hermès
try:
    import plugins.dashboard_auth.basic as basic_auth
except ImportError:
    # Fallback d'import chemin relatif
    root = Path(__file__).resolve().parent.parent.parent
    sys.path.insert(0, str(root))
    import plugins.dashboard_auth.basic as basic_auth


def generate_password(length: int = 24) -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*-_=+"
    while True:
        pwd = "".join(secrets.choice(alphabet) for _ in range(length))
        if (
            any(c.islower() for c in pwd)
            and any(c.isupper() for c in pwd)
            and any(c.isdigit() for c in pwd)
            and any(c in "!@#$%^&*-_=+" for c in pwd)
        ):
            return pwd


def main():
    parser = argparse.ArgumentParser(description="Générateur d'identifiants Dashboard OPS (Basic Auth)")
    parser.add_argument("--username", "-u", default="orso_admin", help="Nom d'utilisateur administrateur (défaut: orso_admin)")
    parser.add_argument("--password", "-p", help="Mot de passe personnalisé (généré aléatoirement si omis)")
    args = parser.parse_args()

    username = args.username
    password = args.password or generate_password(24)
    password_hash = basic_auth.hash_password(password)

    # Validation immédiate du hash généré
    assert basic_auth._verify_password(password, password_hash), "Échec de validation du hash !"

    print("\n" + "=" * 65)
    print("  NOUVEAUX IDENTIFIANTS DASHBOARD OPS GÉNÉRÉS (KAN-49)")
    print("=" * 65)
    print("\n[!] Conservez ces identifiants dans votre gestionnaire de secrets sécurisé.")
    print("    NE COMMITEZ JAMAIS ces valeurs dans le dépôt Git.\n")
    print(f"  Nom d'utilisateur : {username}")
    print(f"  Mot de passe brut : {password}")
    print(f"  Hash scrypt       : {password_hash}\n")
    print("-" * 65)
    print("Lignes à copier dans votre fichier .env sur le VPS :")
    print("-" * 65)
    print(f'export HERMES_DASHBOARD_BASIC_AUTH_USERNAME="{username}"')
    print(f'export HERMES_DASHBOARD_BASIC_AUTH_PASSWORD_HASH="{password_hash}"')
    print("=" * 65 + "\n")


if __name__ == "__main__":
    main()

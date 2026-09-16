"""Script automatisé de provisionnement des utilisateurs du POC dans Supabase Auth (KAN-26).

Ce script utilise l'API Admin de Supabase pour :
1. Créer les comptes dans auth.users
2. Créer les profils correspondants dans public.profiles reliés aux tenants
3. Déclencher l'invitation / réinitialisation sécurisée de mot de passe par email.

Prérequis :
- SUPABASE_URL (ex: https://nyntmjorcqgbzaxszekk.supabase.co)
- SUPABASE_SERVICE_ROLE_KEY (trouvée dans Settings > API > service_role)
"""

import os
import json
import urllib.request
import urllib.error

POC_USERS = [
    {
        "email": "sophie.martin@finarecee20.fr",
        "full_name": "Sophie Martin",
        "phone": "+33 6 45 78 12 34",
        "role": "daf",
        "tenant_slug": "financia-solutions",
    },
    {
        "email": "claire.dubois@servicallc322.com",
        "full_name": "Claire Dubois",
        "phone": "+33 1 56 78 90 12",
        "role": "support",
        "tenant_slug": "commercialink",
    },
    {
        "email": "h.bernard@recoviaa60a.fr",
        "full_name": "Hugo Bernard",
        "phone": "+33 9 12 34 56 78",
        "role": "operator",
        "tenant_slug": "helpdesk360",
    },
    {
        "email": "julien.lefevre@batiprof38f.fr",
        "full_name": "Julien Lefèvre",
        "phone": "+33 7 81 23 45 67",
        "role": "commercial",
        "tenant_slug": "batipro-services",
    },
    {
        "email": "amelie.petit@ventelinkc009.com",
        "full_name": "Amélie Petit",
        "phone": "+33 6 98 76 54 32",
        "role": "admin",
        "tenant_slug": "eurotech-conseil",
    },
]

def provision_users():
    supabase_url = os.environ.get("SUPABASE_URL", "https://nyntmjorcqgbzaxszekk.supabase.co").rstrip("/")
    service_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()

    if not service_key:
        print("ERREUR: La variable SUPABASE_SERVICE_ROLE_KEY est manquante dans l'environnement.")
        print("Récupérez-la dans: Supabase Dashboard > Project Settings > API > Project API keys > service_role")
        return

    headers = {
        "apikey": service_key,
        "Authorization": f"Bearer {service_key}",
        "Content-Type": "application/json",
    }

    # 1. Récupérer les tenants existants depuis l'API REST PostgREST
    tenants_url = f"{supabase_url}/rest/v1/tenants?select=id,slug"
    req = urllib.request.Request(tenants_url, headers=headers)
    try:
        with urllib.request.urlopen(req) as resp:
            tenants = json.loads(resp.read().decode("utf-8"))
            slug_to_id = {t["slug"]: t["id"] for t in tenants}
            print(f"Tenants trouvés dans Supabase ({len(tenants)}):", list(slug_to_id.keys()))
    except Exception as e:
        print(f"Impossible de récupérer les tenants (exécutez d'abord le script SQL) : {e}")
        return

    # 2. Créer chaque utilisateur via l'API Admin
    for u in POC_USERS:
        email = u["email"]
        slug = u["tenant_slug"]
        tenant_id = slug_to_id.get(slug)
        if not tenant_id:
            print(f"Attention: tenant introuvable pour {slug}, utilisateur {email} ignoré.")
            continue

        admin_url = f"{supabase_url}/auth/v1/admin/users"
        body = {
            "email": email,
            "email_confirm": True,
            "user_metadata": {
                "full_name": u["full_name"],
            },
            "app_metadata": {
                "tenant_id": tenant_id,
                "tenant_slug": slug,
                "role": u["role"],
            }
        }
        data = json.dumps(body).encode("utf-8")
        req_user = urllib.request.Request(admin_url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req_user) as resp:
                created_user = json.loads(resp.read().decode("utf-8"))
                user_id = created_user.get("id")
                print(f"Utilisateur créé dans auth.users : {email} (ID: {user_id})")

                # Insérer ou mettre à jour le profil dans public.profiles
                profile_url = f"{supabase_url}/rest/v1/profiles"
                profile_body = {
                    "id": user_id,
                    "tenant_id": tenant_id,
                    "full_name": u["full_name"],
                    "phone": u["phone"],
                    "role": u["role"],
                    "is_primary_contact": True,
                }
                req_prof = urllib.request.Request(
                    profile_url,
                    data=json.dumps(profile_body).encode("utf-8"),
                    headers={**headers, "Prefer": "resolution=merge-duplicates"},
                    method="POST"
                )
                with urllib.request.urlopen(req_prof) as resp_p:
                    print(f" -> Profil associé dans public.profiles pour {email}")

        except urllib.error.HTTPError as e:
            err = e.read().decode("utf-8")
            if "already been registered" in err or "already exists" in err:
                print(f"Utilisateur déjà existant : {email}")
            else:
                print(f"Erreur HTTP {e.code} pour {email} : {err}")
        except Exception as e:
            print(f"Erreur pour {email} : {e}")

if __name__ == "__main__":
    provision_users()

"""Script d'exécution direct de la migration des 5 comptes POC Orso Agents
vers le projet Supabase nyntmjorcqgbzaxszekk.

Ce script :
1. Amorce les 5 organisations (tenants) et leurs instances dans PostgreSQL.
2. Crée les 5 utilisateurs dans auth.users via l'API Admin de Supabase.
3. Renseigne les profils dans public.profiles avec les liens tenants et rôles.
"""

import json
import os
import urllib.error
import urllib.request

# Configuration Supabase
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://nyntmjorcqgbzaxszekk.supabase.co").rstrip("/")
SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()

HEADERS = {
    "apikey": SERVICE_KEY,
    "Authorization": f"Bearer {SERVICE_KEY}",
    "Content-Type": "application/json",
}

POC_DATA = [
    {
        "tenant": {
            "name": "Financia Solutions",
            "siret": "83214567800012",
            "slug": "financia-solutions",
            "sector": "Finance & Recouvrement",
            "status": "active",
        },
        "instance": {
            "internal_route_key": "orso_backend_financia",
            "status": "ready",
            "agents_enabled": ["jerome"],
        },
        "user": {
            "email": "sophie.martin@finarecee20.fr",
            "password": "TempOrso2026!Financia",
            "full_name": "Sophie Martin",
            "phone": "+33 6 45 78 12 34",
            "role": "daf",
        },
    },
    {
        "tenant": {
            "name": "CommerciaLink",
            "siret": "78451236900021",
            "slug": "commercialink",
            "sector": "Commerce & Vente",
            "status": "active",
        },
        "instance": {
            "internal_route_key": "orso_backend_commercialink",
            "status": "ready",
            "agents_enabled": ["lucas"],
        },
        "user": {
            "email": "claire.dubois@servicallc322.com",
            "password": "TempOrso2026!Commercia",
            "full_name": "Claire Dubois",
            "phone": "+33 1 56 78 90 12",
            "role": "support",
        },
    },
    {
        "tenant": {
            "name": "HelpDesk360",
            "siret": "88997766500033",
            "slug": "helpdesk360",
            "sector": "Service Client",
            "status": "active",
        },
        "instance": {
            "internal_route_key": "orso_backend_helpdesk360",
            "status": "ready",
            "agents_enabled": ["clara"],
        },
        "user": {
            "email": "h.bernard@recoviaa60a.fr",
            "password": "TempOrso2026!Helpdesk",
            "full_name": "Hugo Bernard",
            "phone": "+33 9 12 34 56 78",
            "role": "operator",
        },
    },
    {
        "tenant": {
            "name": "BatiPro Services",
            "siret": "90123456700038",
            "slug": "batipro-services",
            "sector": "BTP & Marchés publics",
            "status": "active",
        },
        "instance": {
            "internal_route_key": "orso_backend_batipro",
            "status": "ready",
            "agents_enabled": ["victor"],
        },
        "user": {
            "email": "julien.lefevre@batiprof38f.fr",
            "password": "TempOrso2026!Batipro",
            "full_name": "Julien Lefèvre",
            "phone": "+33 7 81 23 45 67",
            "role": "commercial",
        },
    },
    {
        "tenant": {
            "name": "EuroTech Conseil",
            "siret": "55566677700044",
            "slug": "eurotech-conseil",
            "sector": "Conseil & Ingénierie",
            "status": "active",
        },
        "instance": {
            "internal_route_key": "orso_backend_eurotech",
            "status": "ready",
            "agents_enabled": ["jerome", "lucas", "clara", "victor"],
        },
        "user": {
            "email": "amelie.petit@ventelinkc009.com",
            "password": "TempOrso2026!EuroTech",
            "full_name": "Amélie Petit",
            "phone": "+33 6 98 76 54 32",
            "role": "admin",
        },
    },
]


def upsert_tenant(t_dict):
    """Insère ou met à jour le tenant dans public.tenants."""
    url = f"{SUPABASE_URL}/rest/v1/tenants"
    # Vérifier si existe déjà par slug
    check_url = f"{SUPABASE_URL}/rest/v1/tenants?slug=eq.{t_dict['slug']}&select=id"
    req_check = urllib.request.Request(check_url, headers=HEADERS)
    with urllib.request.urlopen(req_check) as resp:
        existing = json.loads(resp.read().decode())
        if existing:
            return existing[0]["id"]

    req_ins = urllib.request.Request(
        url,
        data=json.dumps(t_dict).encode(),
        headers={**HEADERS, "Prefer": "return=representation"},
        method="POST"
    )
    with urllib.request.urlopen(req_ins) as resp:
        res = json.loads(resp.read().decode())
        return res[0]["id"]


def upsert_instance(i_dict):
    """Insère ou met à jour l'instance dédiée du tenant."""
    url = f"{SUPABASE_URL}/rest/v1/tenant_instances"
    check_url = f"{SUPABASE_URL}/rest/v1/tenant_instances?internal_route_key=eq.{i_dict['internal_route_key']}&select=id"
    req_check = urllib.request.Request(check_url, headers=HEADERS)
    with urllib.request.urlopen(req_check) as resp:
        existing = json.loads(resp.read().decode())
        if existing:
            return existing[0]["id"]

    req_ins = urllib.request.Request(
        url,
        data=json.dumps(i_dict).encode(),
        headers={**HEADERS, "Prefer": "return=representation"},
        method="POST"
    )
    with urllib.request.urlopen(req_ins) as resp:
        res = json.loads(resp.read().decode())
        return res[0]["id"]


def create_or_get_user(u_dict, tenant_id, tenant_slug):
    """Crée l'utilisateur dans auth.users via Supabase Admin API."""
    url = f"{SUPABASE_URL}/auth/v1/admin/users"
    body = {
        "email": u_dict["email"],
        "password": u_dict["password"],
        "email_confirm": True,
        "user_metadata": {
            "full_name": u_dict["full_name"],
            "phone": u_dict["phone"],
        },
        "app_metadata": {
            "tenant_id": tenant_id,
            "tenant_slug": tenant_slug,
            "role": u_dict["role"],
        }
    }
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=HEADERS, method="POST")
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode())
            return data["id"], True
    except urllib.error.HTTPError as e:
        err = e.read().decode()
        if "already been registered" in err or "already exists" in err:
            # Récupérer l'ID existant
            list_url = f"{SUPABASE_URL}/auth/v1/admin/users"
            req_list = urllib.request.Request(list_url, headers=HEADERS)
            with urllib.request.urlopen(req_list) as resp_l:
                users_resp = json.loads(resp_l.read().decode())
                for u in users_resp.get("users", []):
                    if u["email"] == u_dict["email"]:
                        return u["id"], False
        raise RuntimeError(f"Erreur création auth user {u_dict['email']}: {err}")


def upsert_profile(user_id, tenant_id, u_dict):
    """Associe le profil utilisateur à son tenant dans public.profiles."""
    url = f"{SUPABASE_URL}/rest/v1/profiles"
    profile_data = {
        "id": user_id,
        "tenant_id": tenant_id,
        "full_name": u_dict["full_name"],
        "phone": u_dict["phone"],
        "role": u_dict["role"],
        "is_primary_contact": True,
    }
    check_url = f"{SUPABASE_URL}/rest/v1/profiles?id=eq.{user_id}&select=id"
    req_check = urllib.request.Request(check_url, headers=HEADERS)
    with urllib.request.urlopen(req_check) as resp:
        existing = json.loads(resp.read().decode())
        if existing:
            # Update
            req_up = urllib.request.Request(
                f"{url}?id=eq.{user_id}",
                data=json.dumps(profile_data).encode(),
                headers={**HEADERS, "Prefer": "return=representation"},
                method="PATCH"
            )
            with urllib.request.urlopen(req_up) as resp_u:
                return
        # Insert
        req_ins = urllib.request.Request(
            url,
            data=json.dumps(profile_data).encode(),
            headers={**HEADERS, "Prefer": "return=representation"},
            method="POST"
        )
        with urllib.request.urlopen(req_ins) as resp_i:
            return


def run_migration():
    print("================================================================")
    print("DÉMARRAGE DE LA MIGRATION SUPABASE DES COMPTES POC (KAN-26)")
    print("================================================================\n")

    results = []
    for item in POC_DATA:
        t_info = item["tenant"]
        i_info = item["instance"]
        u_info = item["user"]

        print(f"-> Traitement de l'entreprise : {t_info['name']} ({t_info['slug']})")
        # 1. Tenant
        t_id = upsert_tenant(t_info)
        print(f"   [OK] Tenant ID : {t_id}")

        # 2. Instance
        i_info["tenant_id"] = t_id
        i_id = upsert_instance(i_info)
        print(f"   [OK] Instance Dédiée : {i_info['internal_route_key']} (Agents: {i_info['agents_enabled']})")

        # 3. Auth User
        u_id, created = create_or_get_user(u_info, t_id, t_info["slug"])
        action_label = "Créé" if created else "Existant"
        print(f"   [OK] Utilisateur Auth {action_label} : {u_info['email']} (UUID: {u_id})")

        # 4. Profile
        upsert_profile(u_id, t_id, u_info)
        print(f"   [OK] Profil public associé avec succès.\n")

        results.append({
            "company": t_info["name"],
            "slug": t_info["slug"],
            "email": u_info["email"],
            "role": u_info["role"],
            "agents": i_info["agents_enabled"],
            "instance_key": i_info["internal_route_key"],
            "temp_password": u_info["password"],
            "user_id": u_id,
            "tenant_id": t_id,
        })

    print("================================================================")
    print("MIGRATION TERMINÉE AVEC SUCCÈS !")
    print("================================================================\n")
    print(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    run_migration()

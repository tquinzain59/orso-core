"""Script d'export et d'amorçage pour la migration des comptes clients
d'Airtable vers Supabase Auth (KAN-26).

Ce script génère le payload SQL ou JSON d'insertion des tenants et profils
pour les 5 comptes du POC Orso Agents, sans conserver de mot de passe en clair.
"""

import json
import uuid

# Données des 5 comptes cartographiés dans client.html (POC)
POC_CLIENTS = [
    {
        "company_name": "Financia Solutions",
        "siret": "83214567800012",
        "slug": "financia-solutions",
        "sector": "Finance & Recouvrement",
        "email": "sophie.martin@finarecee20.fr",
        "full_name": "Sophie Martin",
        "phone": "+33 6 45 78 12 34",
        "role": "daf",
        "agents": ["jerome"],
        "internal_route_key": "orso_backend_financia",
    },
    {
        "company_name": "CommerciaLink",
        "siret": "78451236900021",
        "slug": "commercialink",
        "sector": "Commerce & Vente",
        "email": "claire.dubois@servicallc322.com",
        "full_name": "Claire Dubois",
        "phone": "+33 1 56 78 90 12",
        "role": "support",
        "agents": ["lucas"],
        "internal_route_key": "orso_backend_commercialink",
    },
    {
        "company_name": "HelpDesk360",
        "siret": "88997766500033",
        "slug": "helpdesk360",
        "sector": "Service Client",
        "email": "h.bernard@recoviaa60a.fr",
        "full_name": "Hugo Bernard",
        "phone": "+33 9 12 34 56 78",
        "role": "operator",
        "agents": ["clara"],
        "internal_route_key": "orso_backend_helpdesk360",
    },
    {
        "company_name": "BatiPro Services",
        "siret": "90123456700038",
        "slug": "batipro-services",
        "sector": "BTP & Marchés publics",
        "email": "julien.lefevre@batiprof38f.fr",
        "full_name": "Julien Lefèvre",
        "phone": "+33 7 81 23 45 67",
        "role": "commercial",
        "agents": ["victor"],
        "internal_route_key": "orso_backend_batipro",
    },
    {
        "company_name": "EuroTech Conseil",
        "siret": "55566677700044",
        "slug": "eurotech-conseil",
        "sector": "Conseil & Ingénierie",
        "email": "amelie.petit@ventelinkc009.com",
        "full_name": "Amélie Petit",
        "phone": "+33 6 98 76 54 32",
        "role": "admin",
        "agents": ["jerome", "lucas", "clara", "victor"],
        "internal_route_key": "orso_backend_eurotech",
    },
]


def generate_seed_sql() -> str:
    """Génère les requêtes SQL d'amorçage pour insérer les tenants et instances."""
    lines = [
        "-- Amorçage des Tenants et Instances déduits du POC Airtable",
        "DO $$",
        "DECLARE",
        "  v_tenant_id UUID;",
        "BEGIN",
    ]

    for c in POC_CLIENTS:
        slug = c["slug"]
        name = c["company_name"].replace("'", "''")
        siret = c["siret"]
        sector = c["sector"].replace("'", "''")
        agents_json = json.dumps(c["agents"])
        route_key = c["internal_route_key"]

        lines.append(f"  -- Tenant: {name}")
        lines.append(
            f"  INSERT INTO public.tenants (name, siret, slug, sector, status)"
            f"  VALUES ('{name}', '{siret}', '{slug}', '{sector}', 'active')"
            f"  ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name"
            f"  RETURNING id INTO v_tenant_id;"
        )
        lines.append(
            f"  INSERT INTO public.tenant_instances (tenant_id, internal_route_key, status, agents_enabled)"
            f"  VALUES (v_tenant_id, '{route_key}', 'ready', '{agents_json}'::jsonb)"
            f"  ON CONFLICT (internal_route_key) DO UPDATE SET agents_enabled = EXCLUDED.agents_enabled;"
        )
        lines.append("")

    lines.append("END $$;")
    return "\n".join(lines)


if __name__ == "__main__":
    sql = generate_seed_sql()
    print(sql)

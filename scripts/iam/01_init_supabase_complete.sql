-- ============================================================================
-- ORSO AGENTS - INITIALISATION COMPLÈTE SUPABASE & MIGRATION POC (KAN-26)
-- Projet Supabase : nyntmjorcqgbzaxszekk
-- À exécuter dans le SQL Editor de Supabase :
-- https://supabase.com/dashboard/project/nyntmjorcqgbzaxszekk/sql/new
-- ============================================================================

-- 1. Table des Organisations / Clients (Tenants)
CREATE TABLE IF NOT EXISTS public.tenants (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    siret VARCHAR(14) UNIQUE,
    slug VARCHAR(64) UNIQUE NOT NULL, -- Identifiant de routage interne (ex: financia-solutions)
    sector VARCHAR(100),
    status VARCHAR(32) NOT NULL DEFAULT 'active', -- active, trial, suspended, churn
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 2. Table des Profils Utilisateurs (liée au schéma natif auth.users)
CREATE TABLE IF NOT EXISTS public.profiles (
    id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    tenant_id UUID NOT NULL REFERENCES public.tenants(id) ON DELETE RESTRICT,
    full_name VARCHAR(255) NOT NULL,
    phone VARCHAR(32),
    role VARCHAR(64) NOT NULL DEFAULT 'user', -- direction, daf, commercial, support, admin
    is_primary_contact BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 3. Table des Instances de Conteneurs Dédiés par Tenant
CREATE TABLE IF NOT EXISTS public.tenant_instances (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
    internal_route_key VARCHAR(128) UNIQUE NOT NULL, -- Clé d'aiguillage interne (ex: orso_backend_financia)
    status VARCHAR(32) NOT NULL DEFAULT 'ready', -- provisioning, ready, stopped, error
    agents_enabled JSONB NOT NULL DEFAULT '["jerome"]'::jsonb, -- Agents souscrits
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 4. Index de performance
CREATE INDEX IF NOT EXISTS idx_profiles_tenant ON public.profiles(tenant_id);
CREATE INDEX IF NOT EXISTS idx_tenants_slug ON public.tenants(slug);
CREATE INDEX IF NOT EXISTS idx_tenant_instances_tenant ON public.tenant_instances(tenant_id);

-- 5. Activation Row-Level Security (RLS)
ALTER TABLE public.tenants ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.tenant_instances ENABLE ROW LEVEL SECURITY;

-- 6. Politiques RLS (Isolation stricte des données)
DROP POLICY IF EXISTS "Users can view own profile" ON public.profiles;
CREATE POLICY "Users can view own profile"
    ON public.profiles FOR SELECT
    USING (auth.uid() = id);

DROP POLICY IF EXISTS "Users can update own profile" ON public.profiles;
CREATE POLICY "Users can update own profile"
    ON public.profiles FOR UPDATE
    USING (auth.uid() = id);

DROP POLICY IF EXISTS "Users can view own tenant" ON public.tenants;
CREATE POLICY "Users can view own tenant"
    ON public.tenants FOR SELECT
    USING (id IN (
        SELECT tenant_id FROM public.profiles WHERE profiles.id = auth.uid()
    ));

DROP POLICY IF EXISTS "Users can view own tenant instance" ON public.tenant_instances;
CREATE POLICY "Users can view own tenant instance"
    ON public.tenant_instances FOR SELECT
    USING (tenant_id IN (
        SELECT tenant_id FROM public.profiles WHERE profiles.id = auth.uid()
    ));

-- 7. Hook Supabase Custom Access Token (Injection des claims métier dans le JWT)
CREATE OR REPLACE FUNCTION public.custom_access_token_hook(event jsonb)
RETURNS jsonb
LANGUAGE plpgsql STABLE
AS $$
DECLARE
  claims jsonb;
  user_tenant record;
BEGIN
  -- Récupère le tenant et le profil rattaché
  SELECT p.tenant_id, t.slug, p.role, ti.agents_enabled
  INTO user_tenant
  FROM public.profiles p
  JOIN public.tenants t ON t.id = p.tenant_id
  LEFT JOIN public.tenant_instances ti ON ti.tenant_id = p.tenant_id
  WHERE p.id = (event->>'user_id')::uuid;

  claims := event->'claims';

  IF user_tenant IS NOT NULL THEN
    claims := jsonb_set(claims, '{tenant}', jsonb_build_object(
      'tenant_id', user_tenant.tenant_id,
      'tenant_slug', user_tenant.slug,
      'role', user_tenant.role,
      'agents', COALESCE(user_tenant.agents_enabled, '["jerome"]'::jsonb)
    ));
  END IF;

  event := jsonb_set(event, '{claims}', claims);
  RETURN event;
END;
$$;

-- Permissions pour le hook Supabase Auth
GRANT EXECUTE ON FUNCTION public.custom_access_token_hook TO supabase_auth_admin;
REVOKE EXECUTE ON FUNCTION public.custom_access_token_hook FROM authenticated, anon, public;

-- ============================================================================
-- 8. Amorçage des 5 Tenants & Instances du POC Orso Agents
-- ============================================================================
DO $$
DECLARE
  v_tenant_id UUID;
BEGIN
  -- 1. Financia Solutions (Agent: Jérôme - Recouvrement)
  INSERT INTO public.tenants (name, siret, slug, sector, status)
  VALUES ('Financia Solutions', '83214567800012', 'financia-solutions', 'Finance & Recouvrement', 'active')
  ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name
  RETURNING id INTO v_tenant_id;

  INSERT INTO public.tenant_instances (tenant_id, internal_route_key, status, agents_enabled)
  VALUES (v_tenant_id, 'orso_backend_financia', 'ready', '["jerome"]'::jsonb)
  ON CONFLICT (internal_route_key) DO UPDATE SET agents_enabled = EXCLUDED.agents_enabled;

  -- 2. CommerciaLink (Agent: Lucas - Commercial)
  INSERT INTO public.tenants (name, siret, slug, sector, status)
  VALUES ('CommerciaLink', '78451236900021', 'commercialink', 'Commerce & Vente', 'active')
  ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name
  RETURNING id INTO v_tenant_id;

  INSERT INTO public.tenant_instances (tenant_id, internal_route_key, status, agents_enabled)
  VALUES (v_tenant_id, 'orso_backend_commercialink', 'ready', '["lucas"]'::jsonb)
  ON CONFLICT (internal_route_key) DO UPDATE SET agents_enabled = EXCLUDED.agents_enabled;

  -- 3. HelpDesk360 (Agent: Clara - Support & Litiges)
  INSERT INTO public.tenants (name, siret, slug, sector, status)
  VALUES ('HelpDesk360', '88997766500033', 'helpdesk360', 'Service Client', 'active')
  ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name
  RETURNING id INTO v_tenant_id;

  INSERT INTO public.tenant_instances (tenant_id, internal_route_key, status, agents_enabled)
  VALUES (v_tenant_id, 'orso_backend_helpdesk360', 'ready', '["clara"]'::jsonb)
  ON CONFLICT (internal_route_key) DO UPDATE SET agents_enabled = EXCLUDED.agents_enabled;

  -- 4. BatiPro Services (Agent: Victor - Marchés Publics)
  INSERT INTO public.tenants (name, siret, slug, sector, status)
  VALUES ('BatiPro Services', '90123456700038', 'batipro-services', 'BTP & Marchés publics', 'active')
  ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name
  RETURNING id INTO v_tenant_id;

  INSERT INTO public.tenant_instances (tenant_id, internal_route_key, status, agents_enabled)
  VALUES (v_tenant_id, 'orso_backend_batipro', 'ready', '["victor"]'::jsonb)
  ON CONFLICT (internal_route_key) DO UPDATE SET agents_enabled = EXCLUDED.agents_enabled;

  -- 5. EuroTech Conseil (Suite Complète : 4 agents)
  INSERT INTO public.tenants (name, siret, slug, sector, status)
  VALUES ('EuroTech Conseil', '55566677700044', 'eurotech-conseil', 'Conseil & Ingénierie', 'active')
  ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name
  RETURNING id INTO v_tenant_id;

  INSERT INTO public.tenant_instances (tenant_id, internal_route_key, status, agents_enabled)
  VALUES (v_tenant_id, 'orso_backend_eurotech', 'ready', '["jerome", "lucas", "clara", "victor"]'::jsonb)
  ON CONFLICT (internal_route_key) DO UPDATE SET agents_enabled = EXCLUDED.agents_enabled;

END $$;

-- ============================================================================
-- ORSO AGENTS - MIGRATION : MULTI-UTILISATEURS & DROITS ADMIN CLIENTS (KAN-32)
-- Projet Supabase : nyntmjorcqgbzaxszekk
-- À exécuter dans le SQL Editor de Supabase :
-- https://supabase.com/dashboard/project/nyntmjorcqgbzaxszekk/sql/new
-- ============================================================================

-- 1. Ajout de la colonne is_admin sur public.profiles
ALTER TABLE public.profiles
ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT FALSE;

-- 2. Les contacts principaux existants ou les profils historiques sont configurés comme administrateurs par défaut
UPDATE public.profiles
SET is_admin = TRUE
WHERE is_primary_contact = TRUE OR role = 'admin' OR is_admin IS NULL;

-- 3. Index d'optimisation pour filtrer les administrateurs par tenant
CREATE INDEX IF NOT EXISTS idx_profiles_tenant_admin ON public.profiles(tenant_id, is_admin);

-- 4. Mise à jour du Hook Supabase Custom Access Token
-- Injecte le claim `is_admin` ainsi que le rôle métier dans le JWT du client
CREATE OR REPLACE FUNCTION public.custom_access_token_hook(event jsonb)
RETURNS jsonb
LANGUAGE plpgsql STABLE
AS $$
DECLARE
  claims jsonb;
  user_tenant record;
BEGIN
  -- Récupère le tenant et le profil rattaché (avec is_admin)
  SELECT p.tenant_id, t.slug, p.role, p.is_admin, ti.agents_enabled
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
      'is_admin', COALESCE(user_tenant.is_admin, FALSE),
      'agents', COALESCE(user_tenant.agents_enabled, '["jerome"]'::jsonb)
    ));
    -- Injection directe au premier niveau de app_metadata pour compatibilité
    claims := jsonb_set(claims, '{app_metadata,is_admin}', to_jsonb(COALESCE(user_tenant.is_admin, FALSE)));
  END IF;

  event := jsonb_set(event, '{claims}', claims);
  RETURN event;
END;
$$;

-- Permissions pour le hook Supabase Auth
GRANT EXECUTE ON FUNCTION public.custom_access_token_hook TO supabase_auth_admin;
REVOKE EXECUTE ON FUNCTION public.custom_access_token_hook FROM authenticated, anon, public;

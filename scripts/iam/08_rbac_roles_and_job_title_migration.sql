-- ============================================================================
-- ORSO AGENTS - MIGRATION 08 : RBAC STRICT ET DÉCOUPLAGE DES RÔLES MÉTIERS
-- Projet Supabase : nyntmjorcqgbzaxszekk
-- Description : 
--   1. Clarifie et restreint les rôles de sécurité Orso à 3 niveaux stricts :
--      - 'superadmin' : Gestion globale de la plateforme OPS ORSO
--      - 'admin'      : Client administrateur (Interfaces, Canaux, Facturation, Agents)
--      - 'user'       : Utilisateur simple (Discussion agents, paramètres perso)
--   2. Déplace les intitulés de fonctions internes (DAF, DG, DSI, etc.) dans `job_title`.
--   3. Synchronise auth.users.raw_app_meta_data et le hook JWT custom_access_token_hook.
--
-- À exécuter dans le SQL Editor de Supabase :
-- https://supabase.com/dashboard/project/nyntmjorcqgbzaxszekk/sql/new
-- ============================================================================

-- 1. Ajout des colonnes job_title et is_admin sur public.profiles
ALTER TABLE public.profiles
ADD COLUMN IF NOT EXISTS job_title VARCHAR(128) DEFAULT NULL;

ALTER TABLE public.profiles
ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT FALSE;

-- 2. Migration des rôles métiers historiques vers job_title et normalisation du rôle système
-- A. Sophie MARTIN et profils DAF -> Administrateur du compte client + job_title 'DAF'
UPDATE public.profiles
SET 
  job_title = COALESCE(job_title, 'Directrice Administrative et Financière (DAF)'),
  role = 'admin',
  is_admin = TRUE
WHERE LOWER(role) = 'daf' 
   OR full_name ILIKE '%sophie martin%' 
   OR id IN (SELECT id FROM auth.users WHERE email ILIKE '%sophie.martin%');

-- B. Direction et contacts principaux -> Administrateur
UPDATE public.profiles
SET 
  job_title = COALESCE(job_title, 'Direction'),
  role = 'admin',
  is_admin = TRUE
WHERE LOWER(role) = 'direction' OR is_primary_contact = TRUE;

-- C. Support client -> Rôle sécurité 'user' + job_title
UPDATE public.profiles
SET 
  job_title = COALESCE(job_title, 'Support Client'),
  role = 'user',
  is_admin = FALSE
WHERE LOWER(role) = 'support';

-- D. Commercial -> Rôle sécurité 'user' + job_title
UPDATE public.profiles
SET 
  job_title = COALESCE(job_title, 'Commercial'),
  role = 'user',
  is_admin = FALSE
WHERE LOWER(role) = 'commercial';

-- E. Opérateur -> Rôle sécurité 'user' + job_title
UPDATE public.profiles
SET 
  job_title = COALESCE(job_title, 'Opérateur IA'),
  role = 'user',
  is_admin = FALSE
WHERE LOWER(role) = 'operator';

-- F. Rôles administratifs explicites
UPDATE public.profiles
SET 
  role = 'admin',
  is_admin = TRUE
WHERE LOWER(role) = 'admin' AND role != 'superadmin';

-- G. Tout autre rôle résiduel est basculé sur 'user'
UPDATE public.profiles
SET 
  role = 'user',
  is_admin = FALSE
WHERE role NOT IN ('superadmin', 'admin', 'user');

-- 3. Contrainte CHECK stricte sur les 3 rôles de sécurité Orso
ALTER TABLE public.profiles 
DROP CONSTRAINT IF EXISTS check_profile_system_role;

ALTER TABLE public.profiles 
ADD CONSTRAINT check_profile_system_role 
CHECK (role IN ('superadmin', 'admin', 'user'));

-- 4. Index de performance
CREATE INDEX IF NOT EXISTS idx_profiles_role ON public.profiles(role);
CREATE INDEX IF NOT EXISTS idx_profiles_tenant_role ON public.profiles(tenant_id, role);

-- 5. Synchronisation de auth.users.raw_app_meta_data pour que les claims retournés par /token soient exacts
UPDATE auth.users u
SET raw_app_meta_data = jsonb_set(
  jsonb_set(
    jsonb_set(
      COALESCE(u.raw_app_meta_data, '{}'::jsonb),
      '{role}',
      to_jsonb(p.role)
    ),
    '{is_admin}',
    to_jsonb(p.is_admin)
  ),
  '{job_title}',
  to_jsonb(COALESCE(p.job_title, 'Collaborateur'))
)
FROM public.profiles p
WHERE p.id = u.id;

-- 6. Mise à jour du Hook Supabase Custom Access Token
-- Injecte de manière propre role (système), is_admin et job_title (métier) dans le token JWT
CREATE OR REPLACE FUNCTION public.custom_access_token_hook(event jsonb)
RETURNS jsonb
LANGUAGE plpgsql STABLE
AS $$
DECLARE
  claims jsonb;
  user_tenant record;
BEGIN
  -- Récupère le tenant et le profil rattaché
  SELECT 
    p.tenant_id, 
    t.slug, 
    p.role, 
    p.is_admin, 
    p.job_title,
    ti.agents_enabled
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
      'job_title', COALESCE(user_tenant.job_title, 'Collaborateur'),
      'agents', COALESCE(user_tenant.agents_enabled, '["jerome"]'::jsonb)
    ));

    -- Injection dans app_metadata
    IF claims ? 'app_metadata' THEN
      claims := jsonb_set(claims, '{app_metadata,role}', to_jsonb(user_tenant.role));
      claims := jsonb_set(claims, '{app_metadata,is_admin}', to_jsonb(COALESCE(user_tenant.is_admin, FALSE)));
      claims := jsonb_set(claims, '{app_metadata,job_title}', to_jsonb(COALESCE(user_tenant.job_title, 'Collaborateur')));
    END IF;
  END IF;

  event := jsonb_set(event, '{claims}', claims);
  RETURN event;
END;
$$;

-- Permissions pour le hook Supabase Auth
GRANT EXECUTE ON FUNCTION public.custom_access_token_hook TO supabase_auth_admin;
REVOKE EXECUTE ON FUNCTION public.custom_access_token_hook FROM authenticated, anon, public;

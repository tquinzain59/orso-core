-- ==============================================================================
-- ORSO AGENTS — MIGRATION 08 : CORRECTION ET NORMALISATION DES SLUGS D'AGENTS
-- Projet Supabase : nyntmjorcqgbzaxszekk
-- Description : Répare rétroactivement les tenants ayant enregistré le rôle
-- technique ('recouvrement', 'commercial', etc.) au lieu du nom de baptême/slug officiel
-- ('jerome', 'lucas', 'clara', 'victor').
-- ==============================================================================

BEGIN;

-- 1. Corriger les slugs et types dans public.agent_instances
UPDATE public.agent_instances
SET agent_slug = 'jerome', agent_type = 'RECOUVREMENT', alias_name = CASE WHEN alias_name IN ('Agent IA', 'recouvrement', 'Recouvrement') THEN 'Jérôme' ELSE alias_name END
WHERE lower(agent_slug) = 'recouvrement';

UPDATE public.agent_instances
SET agent_slug = 'lucas', agent_type = 'COMMERCIAL', alias_name = CASE WHEN alias_name IN ('Agent IA', 'commercial', 'Commercial', 'prospection') THEN 'Lucas' ELSE alias_name END
WHERE lower(agent_slug) IN ('commercial', 'prospection');

UPDATE public.agent_instances
SET agent_slug = 'clara', agent_type = 'SUPPORT_CLIENT', alias_name = CASE WHEN alias_name IN ('Agent IA', 'support', 'Support') THEN 'Clara' ELSE alias_name END
WHERE lower(agent_slug) IN ('support', 'support_client');

UPDATE public.agent_instances
SET agent_slug = 'victor', agent_type = 'APPEL_OFFRES', alias_name = CASE WHEN alias_name IN ('Agent IA', 'ao', 'AO') THEN 'Victor' ELSE alias_name END
WHERE lower(agent_slug) IN ('ao', 'appel_offres', 'appels_offres');

-- 2. Corriger public.tenant_instances.agents_enabled pour tous les conteneurs
-- Remplacement textuel direct et sécurisé pour formats JSON array et JSON object
UPDATE public.tenant_instances
SET agents_enabled = replace(
    replace(
        replace(
            replace(
                replace(
                    replace(
                        replace(agents_enabled::text, '"recouvrement"', '"jerome"'),
                        '"commercial"', '"lucas"'
                    ),
                    '"prospection"', '"lucas"'
                ),
                '"support"', '"clara"'
            ),
            '"support_client"', '"clara"'
        ),
        '"ao"', '"victor"'
    ),
    '"appel_offres"', '"victor"'
)::jsonb
WHERE agents_enabled::text LIKE '%"recouvrement"%'
   OR agents_enabled::text LIKE '%"commercial"%'
   OR agents_enabled::text LIKE '%"prospection"%'
   OR agents_enabled::text LIKE '%"support"%'
   OR agents_enabled::text LIKE '%"ao"%';

COMMIT;

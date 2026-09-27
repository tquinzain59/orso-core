-- ==============================================================================
-- ORSO AGENTS — MIGRATION 07 : FONCTION RPC ONBOARDING SOUVERAINE
-- Projet Supabase : nyntmjorcqgbzaxszekk
-- Description : Permet au tunnel public d'enregistrer l'entreprise, 
-- l'administrateur, l'abonnement d'essai et la calibration des agents en 1 transaction atomique.
-- ==============================================================================

BEGIN;

-- 1. Colonnes de contact direct sur public.tenants pour traçabilité immédiate
ALTER TABLE public.tenants
    ADD COLUMN IF NOT EXISTS contact_name VARCHAR(150),
    ADD COLUMN IF NOT EXISTS contact_email VARCHAR(255),
    ADD COLUMN IF NOT EXISTS contact_phone VARCHAR(32),
    ADD COLUMN IF NOT EXISTS contact_role VARCHAR(100);

-- 2. Fonction RPC sécurisée SECURITY DEFINER
CREATE OR REPLACE FUNCTION public.submit_onboarding_order(payload jsonb)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, auth
AS $$
DECLARE
    v_company_name text;
    v_siret text;
    v_siren text;
    v_vat text;
    v_legal_form french_legal_form;
    v_sector text;
    v_address text;
    v_postal text;
    v_city text;
    v_size text;

    v_admin_name text;
    v_admin_email text;
    v_admin_phone text;
    v_admin_role text;

    v_payment_method payment_method_type;
    v_tier_id text;
    v_agents_count int;
    v_monthly_price numeric;

    v_stripe_customer_id text;
    v_stripe_sub_id text;
    v_stripe_pm_id text;

    v_tenant_id uuid;
    v_slug text;
    v_base_slug text;
    v_sub_id uuid;
    v_agents_arr text[];
    v_ag jsonb;
    v_agent_slug text;
    v_agent_type agent_catalog_type;
BEGIN
    -- 1. Extraction des données entreprise
    v_company_name := COALESCE(trim(payload->'organization'->>'name'), 'Entreprise');
    v_siret := trim(payload->'organization'->>'siret');
    v_siren := substring(v_siret from 1 for 9);
    v_vat := trim(payload->'organization'->>'vat_number');
    v_legal_form := COALESCE((payload->'organization'->>'legal_form')::french_legal_form, 'SAS'::french_legal_form);
    v_sector := payload->'organization'->>'sector';
    v_address := payload->'organization'->>'address_line1';
    v_postal := payload->'organization'->>'postal_code';
    v_city := payload->'organization'->>'city';
    v_size := payload->'organization'->>'employee_count_range';

    -- 2. Extraction contact administrateur
    v_admin_name := COALESCE(trim(payload->'admin'->>'full_name'), 'Administrateur');
    v_admin_email := lower(trim(payload->'admin'->>'email'));
    v_admin_phone := trim(payload->'admin'->>'phone');
    v_admin_role := COALESCE(trim(payload->'admin'->>'job_title'), 'Dirigeant');

    -- 3. Génération du slug de routage (ex: lumina-solutions)
    v_base_slug := lower(regexp_replace(v_company_name, '[^a-zA-Z0-9]+', '-', 'g'));
    v_base_slug := trim(both '-' from v_base_slug);
    IF length(v_base_slug) = 0 THEN
        v_base_slug := 'client';
    END IF;
    
    v_slug := v_base_slug;
    IF EXISTS (SELECT 1 FROM public.tenants WHERE slug = v_slug) THEN
        v_slug := v_base_slug || '-' || floor(random() * 899 + 100)::text;
    END IF;

    -- 4. Insertion du Tenant (avec contact direct)
    INSERT INTO public.tenants (
        name, siret, siren, vat_number, slug, legal_form, sector,
        employee_count_range, address_line1, postal_code, city, status,
        contact_name, contact_email, contact_phone, contact_role
    ) VALUES (
        v_company_name, v_siret, v_siren, v_vat, v_slug, v_legal_form, v_sector,
        v_size, v_address, v_postal, v_city, 'trial',
        v_admin_name, v_admin_email, v_admin_phone, v_admin_role
    )
    RETURNING id INTO v_tenant_id;

    -- 5. Création de l'Abonnement (1er mois d'essai offert)
    v_payment_method := COALESCE((payload->'subscription'->>'payment_method')::payment_method_type, 'CARD'::payment_method_type);
    v_agents_count := COALESCE((payload->'subscription'->>'agents_count')::int, 1);
    v_tier_id := CASE 
        WHEN v_agents_count = 1 THEN '1_agent'
        WHEN v_agents_count = 2 THEN '2_agents'
        WHEN v_agents_count = 3 THEN '3_agents'
        ELSE '4_agents'
    END;
    v_monthly_price := CASE 
        WHEN v_agents_count = 1 THEN 99.00
        WHEN v_agents_count = 2 THEN 169.00
        WHEN v_agents_count = 3 THEN 229.00
        ELSE 279.00
    END;

    v_stripe_customer_id := trim(payload->'subscription'->>'stripe_customer_id');
    v_stripe_sub_id := trim(payload->'subscription'->>'stripe_subscription_id');
    v_stripe_pm_id := trim(payload->'subscription'->>'stripe_payment_method_id');

    INSERT INTO public.subscriptions (
        tenant_id, payment_method, status, tier_id, agents_count,
        monthly_price_ht, trial_start, trial_end,
        stripe_customer_id, stripe_subscription_id, stripe_payment_method_id
    ) VALUES (
        v_tenant_id, v_payment_method, 'TRIALING', v_tier_id, v_agents_count,
        v_monthly_price, NOW(), NOW() + INTERVAL '30 days',
        v_stripe_customer_id, v_stripe_sub_id, v_stripe_pm_id
    )
    RETURNING id INTO v_sub_id;

    -- 6. Insertion des Agents Calibrés (public.agent_instances)
    v_agents_arr := ARRAY[]::text[];
    FOR v_ag IN SELECT * FROM jsonb_array_elements(payload->'agents')
    LOOP
        v_agent_slug := lower(v_ag->>'id'); -- 'jerome', 'lucas', 'clara', 'victor'
        v_agent_type := (v_ag->>'catalog_type')::agent_catalog_type;
        v_agents_arr := array_append(v_agents_arr, v_agent_slug);

        INSERT INTO public.agent_instances (
            tenant_id, subscription_id, agent_type, agent_slug, alias_name,
            tone, autonomy_mode, escalation_threshold_eur, escalation_email,
            integration_tool, specific_config, soul_md_content, config_json,
            is_active, provisioning_status
        ) VALUES (
            v_tenant_id, v_sub_id, v_agent_type, v_agent_slug,
            COALESCE(v_ag->>'name', 'Agent IA'),
            COALESCE((v_ag->>'tone')::agent_tone, 'DIPLOMATIC'::agent_tone),
            COALESCE((v_ag->>'autonomy_mode')::agent_autonomy_mode, 'SEMI_AUTONOMOUS'::agent_autonomy_mode),
            COALESCE((v_ag->>'escalation_threshold_eur')::numeric, 5000.00),
            v_admin_email,
            v_ag->>'integration_tool',
            COALESCE(v_ag->'specific_config', '{}'::jsonb),
            payload->>'soul_md_content',
            COALESCE(payload->'config_json', '{}'::jsonb),
            TRUE, 'PENDING_SETUP'
        )
        ON CONFLICT (tenant_id, agent_type) DO UPDATE SET
            alias_name = EXCLUDED.alias_name,
            soul_md_content = EXCLUDED.soul_md_content,
            config_json = EXCLUDED.config_json,
            updated_at = NOW();
    END LOOP;

    -- 7. Initialisation de l'instance infrastructure (public.tenant_instances)
    INSERT INTO public.tenant_instances (
        tenant_id, internal_route_key, status, agents_enabled, environment_status
    ) VALUES (
        v_tenant_id, 'orso_backend_' || v_slug, 'provisioning',
        to_jsonb(v_agents_arr), 'inactive'
    )
    ON CONFLICT (internal_route_key) DO UPDATE SET
        agents_enabled = EXCLUDED.agents_enabled,
        updated_at = NOW();

    -- 8. Journal d'audit
    INSERT INTO public.audit_logs (tenant_id, actor_email, action, payload)
    VALUES (
        v_tenant_id, v_admin_email, 'ONBOARDING_ORDER_SUBMITTED',
        jsonb_build_object(
            'company_name', v_company_name,
            'tier', v_tier_id,
            'agents', v_agents_arr,
            'payment_method', v_payment_method
        )
    );

    RETURN jsonb_build_object(
        'success', true,
        'tenant_id', v_tenant_id,
        'slug', v_slug,
        'message', 'Organisation et agents enregistrés avec succès'
    );
END;
$$;

-- Permissions d'exécution publiques sécurisées
GRANT EXECUTE ON FUNCTION public.submit_onboarding_order(jsonb) TO anon, authenticated, service_role;

COMMIT;

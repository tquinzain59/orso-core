-- ==============================================================================
-- ORSO AGENTS — MIGRATION 06 : ONBOARDING, ABONNEMENTS STRIPE & CALIBRATION IA
-- Projet Supabase : nyntmjorcqgbzaxszekk
-- Description : Évolution du modèle de données alignée avec le socle existant 
-- (public.tenants, public.profiles, custom_access_token_hook, Orso Ops Cockpit).
-- ==============================================================================

BEGIN;

-- ------------------------------------------------------------------------------
-- 1. TYPES ÉNUMÉRÉS (ENUMS IDEMPOTENTS)
-- ------------------------------------------------------------------------------

DO $$ BEGIN
    CREATE TYPE french_legal_form AS ENUM (
        'SAS', 'SASU', 'SARL', 'EURL', 'SA', 'SNC', 
        'MICRO_ENTREPRISE', 'PROFESSION_LIBERALE', 'ASSOCIATION', 'AUTRE'
    );
EXCEPTION WHEN duplicate_object THEN null; END $$;

DO $$ BEGIN
    CREATE TYPE subscription_status AS ENUM (
        'TRIALING',         -- En période d'essai (1er mois offert)
        'ACTIVE',           -- Actif payant
        'PAST_DUE',         -- Échéance en retard
        'CANCELED',         -- Résilié
        'INCOMPLETE'        -- En attente de validation bancaire
    );
EXCEPTION WHEN duplicate_object THEN null; END $$;

DO $$ BEGIN
    CREATE TYPE payment_method_type AS ENUM (
        'CARD',             -- Carte Bancaire (CB, Visa, Mastercard, Amex)
        'SEPA_DEBIT'        -- Prélèvement SEPA interentreprises (B2B)
    );
EXCEPTION WHEN duplicate_object THEN null; END $$;

DO $$ BEGIN
    CREATE TYPE agent_catalog_type AS ENUM (
        'RECOUVREMENT',     -- Jérôme (Gestion de la trésorerie)
        'COMMERCIAL',       -- Lucas (Prospection & CRM)
        'SUPPORT_CLIENT',   -- Clara (Assistance 24/7)
        'APPEL_OFFRES'      -- Victor (Marchés publics & privés)
    );
EXCEPTION WHEN duplicate_object THEN null; END $$;

DO $$ BEGIN
    CREATE TYPE agent_autonomy_mode AS ENUM (
        'COPILOT',          -- Brouillon soumis à validation humaine
        'SEMI_AUTONOMOUS',  -- Autonome sur standards, escalade sur seuil/litige
        'AUTONOMOUS'        -- 24/7 sous règles strictes
    );
EXCEPTION WHEN duplicate_object THEN null; END $$;

DO $$ BEGIN
    CREATE TYPE agent_tone AS ENUM (
        'CORPORATE',        -- Formel, solennel, juridique
        'DIPLOMATIC',       -- Chaleureux, bienveillant, partenarial
        'DIRECT'            -- Factuel, concis, orienté action
    );
EXCEPTION WHEN duplicate_object THEN null; END $$;


-- ------------------------------------------------------------------------------
-- 2. ENRICHISSEMENT DE public.tenants (ORGANISATIONS / ENTREPRISES)
-- ------------------------------------------------------------------------------

ALTER TABLE public.tenants
    ADD COLUMN IF NOT EXISTS siren VARCHAR(9),
    ADD COLUMN IF NOT EXISTS vat_number VARCHAR(20),
    ADD COLUMN IF NOT EXISTS legal_form french_legal_form DEFAULT 'SAS',
    ADD COLUMN IF NOT EXISTS employee_count_range VARCHAR(50),
    ADD COLUMN IF NOT EXISTS address_line1 TEXT,
    ADD COLUMN IF NOT EXISTS address_line2 TEXT,
    ADD COLUMN IF NOT EXISTS postal_code VARCHAR(10),
    ADD COLUMN IF NOT EXISTS city VARCHAR(100),
    ADD COLUMN IF NOT EXISTS country VARCHAR(50) DEFAULT 'France',
    ADD COLUMN IF NOT EXISTS is_verified BOOLEAN DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS idx_tenants_siren ON public.tenants(siren);


-- ------------------------------------------------------------------------------
-- 3. ENRICHISSEMENT DE public.profiles (MEMBRES & CONTACTS CLIENTS)
-- ------------------------------------------------------------------------------

ALTER TABLE public.profiles
    ADD COLUMN IF NOT EXISTS job_title VARCHAR(100),
    ADD COLUMN IF NOT EXISTS invitation_status VARCHAR(50) DEFAULT 'ACTIVE';


-- ------------------------------------------------------------------------------
-- 4. TABLE DES ABONNEMENTS STRIPE (public.subscriptions)
-- ------------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS public.subscriptions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
    
    -- Références Stripe
    stripe_customer_id VARCHAR(100),
    stripe_subscription_id VARCHAR(100),
    stripe_payment_method_id VARCHAR(100),
    payment_method payment_method_type NOT NULL DEFAULT 'CARD',
    sepa_mandate_reference VARCHAR(100),
    
    -- Statut et cycles de facturation
    status subscription_status NOT NULL DEFAULT 'TRIALING',
    tier_id VARCHAR(32) NOT NULL DEFAULT '1_agent',       -- '1_agent' (99€), '2_agents' (169€), '4_agents' (279€)
    agents_count INT NOT NULL DEFAULT 1,
    monthly_price_ht NUMERIC(10, 2) NOT NULL DEFAULT 99.00,
    setup_fee_ht NUMERIC(10, 2) NOT NULL DEFAULT 1000.00,
    
    trial_start TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    trial_end TIMESTAMPTZ NOT NULL DEFAULT (NOW() + INTERVAL '30 days'),
    current_period_start TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    current_period_end TIMESTAMPTZ NOT NULL DEFAULT (NOW() + INTERVAL '30 days'),
    cancel_at_period_end BOOLEAN NOT NULL DEFAULT FALSE,
    
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_subscriptions_tenant ON public.subscriptions(tenant_id);
CREATE INDEX IF NOT EXISTS idx_subscriptions_stripe_sub ON public.subscriptions(stripe_subscription_id);


-- ------------------------------------------------------------------------------
-- 5. TABLE DE CALIBRATION DES AGENTS IA (public.agent_instances)
-- ------------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS public.agent_instances (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
    subscription_id UUID REFERENCES public.subscriptions(id) ON DELETE CASCADE,
    
    -- Identification
    agent_type agent_catalog_type NOT NULL,
    agent_slug VARCHAR(32) NOT NULL,                      -- 'jerome', 'lucas', 'clara', 'victor'
    alias_name VARCHAR(100) NOT NULL,                     -- Nom personnalisé ou par défaut
    
    -- ADN & Calibration
    tone agent_tone NOT NULL DEFAULT 'DIPLOMATIC',
    autonomy_mode agent_autonomy_mode NOT NULL DEFAULT 'SEMI_AUTONOMOUS',
    escalation_threshold_eur NUMERIC(10, 2) DEFAULT 5000.00,
    escalation_email VARCHAR(255),
    
    -- Intégration outil / ERP
    integration_tool VARCHAR(100),                        -- 'Pennylane', 'HubSpot', etc.
    specific_config JSONB NOT NULL DEFAULT '{}'::jsonb,
    
    -- Artefacts générés par le tunnel d'onboarding
    soul_md_content TEXT,
    config_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    
    -- Cycle de vie
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    provisioning_status VARCHAR(50) NOT NULL DEFAULT 'PENDING_SETUP', -- 'PENDING_SETUP', 'READY', 'RUNNING', 'PAUSED'
    
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_tenant_agent_type UNIQUE (tenant_id, agent_type)
);

CREATE INDEX IF NOT EXISTS idx_agent_instances_tenant ON public.agent_instances(tenant_id);
CREATE INDEX IF NOT EXISTS idx_agent_instances_slug ON public.agent_instances(agent_slug);


-- ------------------------------------------------------------------------------
-- 6. TABLE DES LOGS D'AUDIT (public.audit_logs)
-- ------------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS public.audit_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID REFERENCES public.tenants(id) ON DELETE CASCADE,
    actor_email VARCHAR(255),
    action VARCHAR(100) NOT NULL,                         -- 'SUBSCRIPTION_CREATED', 'AGENT_CALIBRATED', 'SOUL_UPDATED'
    payload JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_audit_logs_tenant ON public.audit_logs(tenant_id);


-- ------------------------------------------------------------------------------
-- 7. VUES DE COMPATIBILITÉ (Permet au frontend de requêter "organizations")
-- ------------------------------------------------------------------------------

CREATE OR REPLACE VIEW public.organizations AS
SELECT 
    id,
    name,
    siren,
    siret,
    vat_number,
    legal_form,
    sector,
    employee_count_range,
    address_line1,
    address_line2,
    postal_code,
    city,
    country,
    is_verified,
    created_at,
    updated_at
FROM public.tenants;

CREATE OR REPLACE VIEW public.organization_members AS
SELECT 
    id,
    tenant_id AS organization_id,
    id AS auth_user_id,
    full_name,
    job_title,
    phone,
    role,
    is_primary_contact AS is_primary_admin,
    is_admin,
    invitation_status,
    created_at,
    updated_at
FROM public.profiles;


-- ------------------------------------------------------------------------------
-- 8. POLITIQUES DE SÉCURITÉ ROW LEVEL SECURITY (RLS) ÉTANCHES
-- ------------------------------------------------------------------------------

ALTER TABLE public.subscriptions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.agent_instances ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.audit_logs ENABLE ROW LEVEL SECURITY;

-- Subscriptions : Seuls les membres du tenant peuvent consulter leur abonnement
DROP POLICY IF EXISTS "Users can view own tenant subscriptions" ON public.subscriptions;
CREATE POLICY "Users can view own tenant subscriptions"
    ON public.subscriptions FOR SELECT
    USING (tenant_id IN (
        SELECT tenant_id FROM public.profiles WHERE profiles.id = auth.uid()
    ));

-- Agent Instances : Lecture pour tous les membres du tenant, édition pour les admins
DROP POLICY IF EXISTS "Users can view own tenant agent instances" ON public.agent_instances;
CREATE POLICY "Users can view own tenant agent instances"
    ON public.agent_instances FOR SELECT
    USING (tenant_id IN (
        SELECT tenant_id FROM public.profiles WHERE profiles.id = auth.uid()
    ));

DROP POLICY IF EXISTS "Admins can update own tenant agent instances" ON public.agent_instances;
CREATE POLICY "Admins can update own tenant agent instances"
    ON public.agent_instances FOR UPDATE
    USING (tenant_id IN (
        SELECT tenant_id FROM public.profiles WHERE profiles.id = auth.uid() AND (is_admin = TRUE OR is_primary_contact = TRUE)
    ));

-- Service Role (Webhooks Stripe, Onboarding API Backend) : Accès complet
DROP POLICY IF EXISTS "Service role manages subscriptions" ON public.subscriptions;
CREATE POLICY "Service role manages subscriptions"
    ON public.subscriptions FOR ALL TO service_role USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "Service role manages agent instances" ON public.agent_instances;
CREATE POLICY "Service role manages agent instances"
    ON public.agent_instances FOR ALL TO service_role USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "Service role manages audit logs" ON public.audit_logs;
CREATE POLICY "Service role manages audit logs"
    ON public.audit_logs FOR ALL TO service_role USING (true) WITH CHECK (true);


-- ------------------------------------------------------------------------------
-- 9. TRIGGERS AUTOMATIQUES : updated_at & SYNCHRONISATION INFRASTRUCTURE
-- ------------------------------------------------------------------------------

-- Fonction universelle de mise à jour du timestamp
CREATE OR REPLACE FUNCTION public.handle_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_subscriptions_updated_at ON public.subscriptions;
CREATE TRIGGER trg_subscriptions_updated_at
    BEFORE UPDATE ON public.subscriptions
    FOR EACH ROW EXECUTE FUNCTION public.handle_updated_at();

DROP TRIGGER IF EXISTS trg_agent_instances_updated_at ON public.agent_instances;
CREATE TRIGGER trg_agent_instances_updated_at
    BEFORE UPDATE ON public.agent_instances
    FOR EACH ROW EXECUTE FUNCTION public.handle_updated_at();

-- Trigger automatique : Synchronise `tenant_instances.agents_enabled` dès qu'un agent est activé/calibré
CREATE OR REPLACE FUNCTION public.sync_tenant_instance_agents()
RETURNS TRIGGER AS $$
DECLARE
    v_agents jsonb;
BEGIN
    SELECT jsonb_agg(agent_slug)
    INTO v_agents
    FROM public.agent_instances
    WHERE tenant_id = NEW.tenant_id AND is_active = TRUE;

    UPDATE public.tenant_instances
    SET 
        agents_enabled = COALESCE(v_agents, '[]'::jsonb),
        updated_at = NOW()
    WHERE tenant_id = NEW.tenant_id;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_sync_tenant_agents ON public.agent_instances;
CREATE TRIGGER trg_sync_tenant_agents
    AFTER INSERT OR UPDATE OR DELETE ON public.agent_instances
    FOR EACH ROW EXECUTE FUNCTION public.sync_tenant_instance_agents();

COMMIT;

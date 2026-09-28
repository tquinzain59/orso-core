-- ==============================================================================
-- ORSO AGENTS — MIGRATION 09 : FACTURATION RÉELLE & IDEMPOTENCE DES WEBHOOKS
-- Projet Supabase : nyntmjorcqgbzaxszekk
-- Description : 
--   1. Table `public.processed_webhook_events` garantissant l'idempotence au rejeu
--   2. Table `public.invoices` alimentée par les événements Stripe Billing
-- ==============================================================================

BEGIN;

-- ------------------------------------------------------------------------------
-- 1. TABLE DES ÉVÉNEMENTS WEBHOOK TRAITÉS (IDEMPOTENCE STRICTE AU REJEU)
-- ------------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS public.processed_webhook_events (
    event_id VARCHAR(128) PRIMARY KEY,
    event_type VARCHAR(128) NOT NULL,
    customer_id VARCHAR(128),
    subscription_id VARCHAR(128),
    tenant_slug VARCHAR(128),
    status VARCHAR(64) NOT NULL DEFAULT 'processed',
    replay_count INT NOT NULL DEFAULT 0,
    error_reason TEXT,
    payload JSONB,
    processed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_replayed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_processed_events_type ON public.processed_webhook_events(event_type);
CREATE INDEX IF NOT EXISTS idx_processed_events_slug ON public.processed_webhook_events(tenant_slug);
CREATE INDEX IF NOT EXISTS idx_processed_events_customer ON public.processed_webhook_events(customer_id);

-- ------------------------------------------------------------------------------
-- 2. TABLE DES FACTURES CLIENTS (SOURCE DE VÉRITÉ EN BASE)
-- ------------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS public.invoices (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID REFERENCES public.tenants(id) ON DELETE CASCADE,
    stripe_invoice_id VARCHAR(128) UNIQUE,
    stripe_customer_id VARCHAR(128),
    number VARCHAR(128),
    amount_ht NUMERIC(10, 2) NOT NULL DEFAULT 0.00,
    amount_ttc NUMERIC(10, 2) NOT NULL DEFAULT 0.00,
    currency VARCHAR(8) NOT NULL DEFAULT 'EUR',
    status VARCHAR(32) NOT NULL DEFAULT 'paid', -- 'paid', 'open', 'draft', 'uncollectible'
    date TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    pdf_url TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_invoices_tenant_id ON public.invoices(tenant_id);
CREATE INDEX IF NOT EXISTS idx_invoices_stripe_inv ON public.invoices(stripe_invoice_id);
CREATE INDEX IF NOT EXISTS idx_invoices_date ON public.invoices(date DESC);

-- ------------------------------------------------------------------------------
-- 3. ROW LEVEL SECURITY (RLS)
-- ------------------------------------------------------------------------------

ALTER TABLE public.processed_webhook_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.invoices ENABLE ROW LEVEL SECURITY;

-- processed_webhook_events : Service Role uniquement
DROP POLICY IF EXISTS "Service role manages processed_webhook_events" ON public.processed_webhook_events;
CREATE POLICY "Service role manages processed_webhook_events"
    ON public.processed_webhook_events FOR ALL TO service_role USING (true) WITH CHECK (true);

-- invoices : Lecture par les membres du tenant, gestion par service_role
DROP POLICY IF EXISTS "Users can view own tenant invoices" ON public.invoices;
CREATE POLICY "Users can view own tenant invoices"
    ON public.invoices FOR SELECT
    USING (tenant_id IN (
        SELECT tenant_id FROM public.profiles WHERE profiles.id = auth.uid()
    ));

DROP POLICY IF EXISTS "Service role manages invoices" ON public.invoices;
CREATE POLICY "Service role manages invoices"
    ON public.invoices FOR ALL TO service_role USING (true) WITH CHECK (true);

COMMIT;

-- ==============================================================================
-- ORSO AGENTS — ROLLBACK MIGRATION 09 : FACTURATION RÉELLE & IDEMPOTENCE (KAN-88)
-- Projet Supabase : nyntmjorcqgbzaxszekk
-- ==============================================================================

BEGIN;

DROP TABLE IF EXISTS public.invoices CASCADE;
DROP TABLE IF EXISTS public.processed_webhook_events CASCADE;

COMMIT;

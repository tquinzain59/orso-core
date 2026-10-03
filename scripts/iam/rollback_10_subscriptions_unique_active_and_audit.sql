-- ==============================================================================
-- ORSO AGENTS — ROLLBACK MIGRATION 10 : UNICITÉ ABONNEMENT & AUDIT (KAN-87)
-- Projet Supabase : nyntmjorcqgbzaxszekk
-- ==============================================================================

BEGIN;

DROP INDEX IF EXISTS public.uq_subscriptions_active_tenant;
DROP INDEX IF EXISTS public.uq_subscriptions_trialing_tenant;
DROP INDEX IF EXISTS public.idx_audit_logs_tenant_id;
DROP INDEX IF EXISTS public.idx_audit_logs_action;
DROP INDEX IF EXISTS public.idx_audit_logs_created_at;

COMMIT;

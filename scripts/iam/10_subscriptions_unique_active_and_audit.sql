-- ==============================================================================
-- ORSO AGENTS — MIGRATION 10 : UNICITÉ DE L'ABONNEMENT ACTIF & AUDIT (KAN-87)
-- Projet Supabase : nyntmjorcqgbzaxszekk
-- Description :
--   1. Index d'unicité partiel interdisant plus d'un abonnement actif (ACTIVE / TRIALING) par tenant
--   2. Index de recherche sur public.audit_logs
-- ==============================================================================

BEGIN;

-- 0. Assainissement préalable : basculer les doublons résiduels en CANCELED
-- On conserve l'abonnement actif le plus ancien par tenant (ou celui de référence)
UPDATE public.subscriptions s
SET status = 'CANCELED', updated_at = NOW()
WHERE s.status IN ('ACTIVE', 'TRIALING')
  AND s.id NOT IN (
    SELECT DISTINCT ON (tenant_id) id
    FROM public.subscriptions
    WHERE status IN ('ACTIVE', 'TRIALING')
    ORDER BY tenant_id, created_at ASC
  );

-- 1. Index d'unicité partiel pour garantir au plus un abonnement ACTIVE par tenant
CREATE UNIQUE INDEX IF NOT EXISTS uq_subscriptions_active_tenant
    ON public.subscriptions (tenant_id)
    WHERE status = 'ACTIVE';

-- 2. Index d'unicité partiel pour garantir au plus un abonnement TRIALING par tenant
CREATE UNIQUE INDEX IF NOT EXISTS uq_subscriptions_trialing_tenant
    ON public.subscriptions (tenant_id)
    WHERE status = 'TRIALING';

-- 3. Indexation sur audit_logs pour des requêtes d'audit rapides
CREATE INDEX IF NOT EXISTS idx_audit_logs_tenant_id ON public.audit_logs(tenant_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_action ON public.audit_logs(action);
CREATE INDEX IF NOT EXISTS idx_audit_logs_created_at ON public.audit_logs(created_at DESC);

COMMIT;

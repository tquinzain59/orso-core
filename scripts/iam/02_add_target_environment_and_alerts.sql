-- ============================================================================
-- ORSO AGENTS - MIGRATION : RÉFÉRENCES D'ENVIRONNEMENT DOCKER & ALERTES SUPPORT
-- Projet Supabase : nyntmjorcqgbzaxszekk
-- ============================================================================

-- 1. Ajout des colonnes de référence d'environnement à public.tenant_instances
ALTER TABLE public.tenant_instances 
  ADD COLUMN IF NOT EXISTS instance_url VARCHAR(255),
  ADD COLUMN IF NOT EXISTS docker_container_name VARCHAR(128),
  ADD COLUMN IF NOT EXISTS docker_host VARCHAR(128),
  ADD COLUMN IF NOT EXISTS docker_port INTEGER,
  ADD COLUMN IF NOT EXISTS environment_status VARCHAR(32) DEFAULT 'active';

-- 2. Création de la table de suivi des alertes support (Support Alerts)
CREATE TABLE IF NOT EXISTS public.support_alerts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID REFERENCES public.tenants(id) ON DELETE SET NULL,
    user_id UUID,
    user_email VARCHAR(255) NOT NULL,
    alert_type VARCHAR(64) NOT NULL DEFAULT 'ENVIRONMENT_NOT_FOUND',
    message TEXT NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'open', -- open, acknowledged, resolved
    details JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Index de recherche rapide
CREATE INDEX IF NOT EXISTS idx_tenant_instances_url ON public.tenant_instances(instance_url);
CREATE INDEX IF NOT EXISTS idx_support_alerts_tenant ON public.support_alerts(tenant_id);
CREATE INDEX IF NOT EXISTS idx_support_alerts_status ON public.support_alerts(status);

-- 3. Configuration RLS pour support_alerts
ALTER TABLE public.support_alerts ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Service role can manage support alerts" ON public.support_alerts;
CREATE POLICY "Service role can manage support alerts"
    ON public.support_alerts
    USING (TRUE)
    WITH CHECK (TRUE);

DROP POLICY IF EXISTS "Users can view own tenant alerts" ON public.support_alerts;
CREATE POLICY "Users can view own tenant alerts"
    ON public.support_alerts FOR SELECT
    USING (tenant_id IN (
        SELECT tenant_id FROM public.profiles WHERE profiles.id = auth.uid()
    ));

-- 4. Mise à jour des références cibles pour Financia Solutions (PROD-FR-002)
UPDATE public.tenant_instances ti
SET 
  instance_url = 'https://prod-fr-002.orso-agents.fr',
  docker_container_name = 'orso_client_backend',
  docker_host = '92.222.68.80',
  docker_port = 9300,
  environment_status = 'active',
  updated_at = NOW()
FROM public.tenants t
WHERE ti.tenant_id = t.id AND t.slug = 'financia-solutions';

-- 5. Création d'un compte de test "Client Sans Environnement" (pour validation de l'alerte support)
DO $$
DECLARE
  v_tenant_id UUID;
BEGIN
  INSERT INTO public.tenants (name, siret, slug, sector, status)
  VALUES ('Aura Sans Environnement', '99988877700011', 'aura-sans-env', 'Audit & Conseil', 'active')
  ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name
  RETURNING id INTO v_tenant_id;

  -- Ne crée AUCUNE instance dans tenant_instances pour ce tenant,
  -- simulant un client dont l'infrastructure n'a pas encore été déployée.
END $$;

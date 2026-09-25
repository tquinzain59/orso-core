-- scripts/iam/05_consistency_locks_and_reality_alignment.sql
-- Migration 05: Align instances reality and set consistency locks
BEGIN;

-- 1. Align the 5 inactive tenants
UPDATE public.tenant_instances
SET 
  agents_enabled = '[]'::jsonb,
  status = 'not_provisioned',
  environment_status = 'inactive',
  docker_container_name = NULL,
  docker_host = NULL,
  docker_port = NULL,
  instance_url = NULL
FROM public.tenants t
WHERE t.id = public.tenant_instances.tenant_id
AND t.slug IN ('commercialink', 'helpdesk360', 'batipro-services', 'eurotech-conseil', 'aura-sans-env');

-- 2. Explicitly align the active tenant
UPDATE public.tenant_instances
SET 
  agents_enabled = '["jerome"]'::jsonb,
  status = 'ready',
  environment_status = 'active',
  docker_container_name = 'orso_client_backend'
FROM public.tenants t
WHERE t.id = public.tenant_instances.tenant_id
AND t.slug = 'financia-solutions';

-- 3. Create the consistency trigger function
CREATE OR REPLACE FUNCTION public.check_tenant_instance_consistency()
RETURNS TRIGGER AS $$
BEGIN
  -- If the instance is not provisioned or inactive, enforce zero agents
  IF NEW.status = 'not_provisioned' OR NEW.environment_status = 'inactive' THEN
    NEW.agents_enabled := '[]'::jsonb;
  END IF;
  
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- 4. Attach the trigger
DROP TRIGGER IF EXISTS enforce_tenant_instance_consistency ON public.tenant_instances;
CREATE TRIGGER enforce_tenant_instance_consistency
BEFORE INSERT OR UPDATE ON public.tenant_instances
FOR EACH ROW
EXECUTE FUNCTION public.check_tenant_instance_consistency();

COMMIT;

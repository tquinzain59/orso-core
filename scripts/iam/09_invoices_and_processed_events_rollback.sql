-- ==============================================================================
-- ORSO AGENTS — ROLLBACK MIGRATION 09 (KAN-88)
-- Projet Supabase : nyntmjorcqgbzaxszekk
-- Annule scripts/iam/09_invoices_and_processed_events.sql.
--
-- ATTENTION : DESTRUCTIF. Supprime les tables et TOUTES leurs lignes. Avant exécution,
-- exporter les lignes à conserver, et vérifier qu'aucune facture réelle n'y figure :
--   SELECT count(*) FROM public.invoices;
--   SELECT count(*) FROM public.processed_webhook_events;
-- Les lignes de test KAN-88 portent le préfixe `evt_kan88_test_` / `in_kan88_test_`
-- et peuvent être purgées seules (voir 09_invoices_and_processed_events_purge_test_rows.sql).
-- ==============================================================================

BEGIN;

DROP POLICY IF EXISTS "Service role manages invoices" ON public.invoices;
DROP POLICY IF EXISTS "Users can view own tenant invoices" ON public.invoices;
DROP POLICY IF EXISTS "Service role manages processed_webhook_events" ON public.processed_webhook_events;

DROP TABLE IF EXISTS public.invoices;
DROP TABLE IF EXISTS public.processed_webhook_events;

COMMIT;

NOTIFY pgrst, 'reload schema';

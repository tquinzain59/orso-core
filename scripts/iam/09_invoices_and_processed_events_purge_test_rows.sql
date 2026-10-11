-- ==============================================================================
-- ORSO AGENTS — PURGE DES LIGNES DE TEST KAN-88 (n'efface aucune donnée réelle)
-- Cible uniquement les identifiants préfixés `evt_kan88_test_` et `in_kan88_test_`.
-- ==============================================================================

BEGIN;

DELETE FROM public.invoices WHERE stripe_invoice_id LIKE 'in\_kan88\_test\_%' ESCAPE '\';
DELETE FROM public.processed_webhook_events WHERE event_id LIKE 'evt\_kan88\_test\_%' ESCAPE '\';

COMMIT;

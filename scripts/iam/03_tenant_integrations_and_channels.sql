-- ============================================================================
-- ORSO AGENTS - MIGRATION : TABLES ET DONNÉES INTERFACES, ERP ET CANAUX CLIENTS (KAN-31)
-- Projet Supabase : nyntmjorcqgbzaxszekk
-- ============================================================================

-- 1. Table des Interfaces & ERP raccordés par Tenant
CREATE TABLE IF NOT EXISTS public.tenant_integrations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
    integration_id VARCHAR(64) NOT NULL, -- identifiant normalisé (ex: pennylane, pappers, sellsy)
    name VARCHAR(255) NOT NULL,
    category VARCHAR(32) NOT NULL, -- erp, mail, legal, crm
    provider VARCHAR(128) NOT NULL,
    description TEXT NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'disconnected', -- connected, pending, disconnected
    last_sync VARCHAR(128),
    metric_label VARCHAR(128),
    metric_value VARCHAR(128),
    account_details VARCHAR(255),
    config JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_tenant_integration UNIQUE (tenant_id, integration_id)
);

-- Index pour requêtage rapide par organisation
CREATE INDEX IF NOT EXISTS idx_tenant_integrations_tenant ON public.tenant_integrations(tenant_id);
CREATE INDEX IF NOT EXISTS idx_tenant_integrations_category ON public.tenant_integrations(category);

-- 2. Table des Canaux de Discussion & Omnicanal par Tenant
CREATE TABLE IF NOT EXISTS public.tenant_channels (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
    channel_id VARCHAR(64) NOT NULL, -- whatsapp, telegram, email
    name VARCHAR(255) NOT NULL,
    tagline VARCHAR(255),
    description TEXT NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'connected', -- connected, disconnected, configuring
    connected_account VARCHAR(255),
    allowed_users JSONB NOT NULL DEFAULT '[]'::jsonb,
    stats JSONB NOT NULL DEFAULT '{"messagesToday": 0, "activeSessions": 0}'::jsonb,
    config JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_tenant_channel UNIQUE (tenant_id, channel_id)
);

-- Index pour requêtage rapide par organisation
CREATE INDEX IF NOT EXISTS idx_tenant_channels_tenant ON public.tenant_channels(tenant_id);

-- 3. Configuration Row-Level Security (RLS)
ALTER TABLE public.tenant_integrations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.tenant_channels ENABLE ROW LEVEL SECURITY;

-- Politiques RLS pour tenant_integrations
DROP POLICY IF EXISTS "Service role manages all integrations" ON public.tenant_integrations;
CREATE POLICY "Service role manages all integrations"
    ON public.tenant_integrations
    USING (TRUE)
    WITH CHECK (TRUE);

DROP POLICY IF EXISTS "Users can view own tenant integrations" ON public.tenant_integrations;
CREATE POLICY "Users can view own tenant integrations"
    ON public.tenant_integrations FOR SELECT
    USING (tenant_id IN (
        SELECT tenant_id FROM public.profiles WHERE profiles.id = auth.uid()
    ));

-- Politiques RLS pour tenant_channels
DROP POLICY IF EXISTS "Service role manages all channels" ON public.tenant_channels;
CREATE POLICY "Service role manages all channels"
    ON public.tenant_channels
    USING (TRUE)
    WITH CHECK (TRUE);

DROP POLICY IF EXISTS "Users can view own tenant channels" ON public.tenant_channels;
CREATE POLICY "Users can view own tenant channels"
    ON public.tenant_channels FOR SELECT
    USING (tenant_id IN (
        SELECT tenant_id FROM public.profiles WHERE profiles.id = auth.uid()
    ));

-- ============================================================================
-- 4. Amorçage des Interfaces et Canaux des 5 Organisations POC
-- ============================================================================
DO $$
DECLARE
  v_financia_id UUID;
  v_commercialink_id UUID;
  v_helpdesk_id UUID;
  v_batipro_id UUID;
  v_eurotech_id UUID;
BEGIN
  -- Récupération des UUID des tenants
  SELECT id INTO v_financia_id FROM public.tenants WHERE slug = 'financia-solutions';
  SELECT id INTO v_commercialink_id FROM public.tenants WHERE slug = 'commercialink';
  SELECT id INTO v_helpdesk_id FROM public.tenants WHERE slug = 'helpdesk360';
  SELECT id INTO v_batipro_id FROM public.tenants WHERE slug = 'batipro-services';
  SELECT id INTO v_eurotech_id FROM public.tenants WHERE slug = 'eurotech-conseil';

  -- ── A. Financia Solutions (Agent: Jérôme - Recouvrement & Trésorerie) ─────
  IF v_financia_id IS NOT NULL THEN
    -- Interfaces
    INSERT INTO public.tenant_integrations (tenant_id, integration_id, name, category, provider, description, status, last_sync, metric_label, metric_value, account_details)
    VALUES
      (v_financia_id, 'pennylane', 'Pennylane', 'erp', 'Pennylane API', 'Synchronisation bidirectionnelle des factures de vente, des règlements clients et de la balance comptable.', 'connected', 'Il y a 14 min', 'Factures suivies', '284 factures (142 580 €)', 'Compte Entreprise Pro • Clé active'),
      (v_financia_id, 'sellsy', 'Sellsy CRM & Factures', 'erp', 'Sellsy v2', 'Extraction des devis signés, des factures échues et des contacts décideurs.', 'pending', 'Configuration en attente', 'Statut', 'En attente du jeton OAuth', 'Non associé'),
      (v_financia_id, 'odoo', 'Odoo ERP', 'erp', 'Odoo XML-RPC', 'Module Comptabilité et Ventes pour PME.', 'disconnected', 'Jamais synchronisé', NULL, NULL, 'Non configuré'),
      (v_financia_id, 'google-workspace', 'Google Workspace (Gmail)', 'mail', 'Google OAuth', 'Envoi des relances amiables et réception des justificatifs de paiement des clients.', 'connected', 'Temps réel (Actif)', 'Relances du mois', '38 e-mails transmis', 'direction@finarecee20.fr'),
      (v_financia_id, 'microsoft-365', 'Microsoft 365 (Outlook)', 'mail', 'Graph API', 'Alternative messagerie entreprise pour l’envoi et le suivi des courriels.', 'disconnected', NULL, NULL, NULL, 'Non connecté'),
      (v_financia_id, 'pappers', 'Pappers API & Scoring', 'legal', 'Pappers Open Data', 'Fiche financière complète, score de défaillance, bilans et dirigeants légaux des tiers.', 'connected', 'Temps réel', 'Analyses effectuées', '46 vérifications ce mois', 'Accès illimité actif'),
      (v_financia_id, 'bodacc', 'Veille Légale BODACC', 'legal', 'DILA Open Data', 'Surveillance proactive des procédures collectives (redressements, liquidations judiciaires).', 'connected', 'Ce matin à 06:00', 'Alerte active', '0 procédure détectée', 'Flux quotidien officiel'),
      (v_financia_id, 'hubspot', 'HubSpot CRM', 'crm', 'HubSpot API', 'Synchronisation des contacts commerciaux, création de deals et suivi des échanges.', 'connected', 'Il y a 1 heure', 'Prospects qualifiés', '18 leads par Lucas', 'Instance connectée')
    ON CONFLICT (tenant_id, integration_id) DO UPDATE SET
      status = EXCLUDED.status,
      last_sync = EXCLUDED.last_sync,
      metric_value = EXCLUDED.metric_value,
      account_details = EXCLUDED.account_details,
      updated_at = NOW();

    -- Canaux
    INSERT INTO public.tenant_channels (tenant_id, channel_id, name, tagline, description, status, connected_account, allowed_users, stats)
    VALUES
      (v_financia_id, 'whatsapp', 'WhatsApp Business', 'Liaison directe avec vos clients & tiers', 'Permet à Jérôme et Lucas de dialoguer directement par WhatsApp pour obtenir des confirmations de virement ou qualifier des prospects.', 'connected', '+33 6 42 00 12 34 (Numéro Entreprise)', '["+33642001234", "+33612345678"]'::jsonb, '{"messagesToday": 12, "activeSessions": 3}'::jsonb),
      (v_financia_id, 'telegram', 'Telegram (Console Dirigeant)', 'Notifications et alertes prioritaires sur mobile', 'Votre canal direct pour recevoir les alertes BODACC urgentes, vérifier un client via /check et consulter vos chiffres sans ouvrir votre ordinateur.', 'connected', '@OrsoDirigeantBot (Lié à votre compte)', '["741298453 (Dirigeant)"]'::jsonb, '{"messagesToday": 4, "activeSessions": 1}'::jsonb),
      (v_financia_id, 'email', 'Email Gateway', 'Envoi automatique et suivi des réponses', 'Canal de relance par défaut pour l’envoi des courriers de relance niveau 1, 2 et mise en demeure.', 'connected', 'recouvrement@finarecee20.fr', '["sophie.martin@finarecee20.fr", "direction@finarecee20.fr"]'::jsonb, '{"messagesToday": 26, "activeSessions": 8}'::jsonb)
    ON CONFLICT (tenant_id, channel_id) DO UPDATE SET
      connected_account = EXCLUDED.connected_account,
      allowed_users = EXCLUDED.allowed_users,
      stats = EXCLUDED.stats,
      updated_at = NOW();
  END IF;

  -- ── B. CommerciaLink (Agent: Lucas - Commercial & Prospection) ─────────────
  IF v_commercialink_id IS NOT NULL THEN
    INSERT INTO public.tenant_integrations (tenant_id, integration_id, name, category, provider, description, status, last_sync, metric_label, metric_value, account_details)
    VALUES
      (v_commercialink_id, 'hubspot', 'HubSpot CRM', 'crm', 'HubSpot API', 'Synchronisation des contacts commerciaux, création de deals et suivi des échanges.', 'connected', 'Il y a 10 min', 'Prospects chauds', '34 leads qualifiés', 'HubSpot Pro - Pipeline Ventes'),
      (v_commercialink_id, 'sellsy', 'Sellsy CRM & Devis', 'erp', 'Sellsy v2', 'Gestion des devis et propositions commerciales B2B.', 'connected', 'Il y a 25 min', 'Devis en attente', '12 devis (89 400 €)', 'Instance Sellsy active'),
      (v_commercialink_id, 'google-workspace', 'Google Workspace (Gmail)', 'mail', 'Google OAuth', 'Envoi des séquences de prospection commerciale et relances de devis.', 'connected', 'Temps réel', 'Emails envoyés', '112 prises de contact', 'claire.dubois@servicallc322.com'),
      (v_commercialink_id, 'pappers', 'Pappers API & Scoring', 'legal', 'Pappers Open Data', 'Enrichissement des données de contact et santé financière des prospects.', 'connected', 'Temps réel', 'Fiches enrichies', '68 entreprises vérifiées', 'Accès Standard')
    ON CONFLICT (tenant_id, integration_id) DO UPDATE SET status = EXCLUDED.status, updated_at = NOW();

    INSERT INTO public.tenant_channels (tenant_id, channel_id, name, tagline, description, status, connected_account, allowed_users, stats)
    VALUES
      (v_commercialink_id, 'whatsapp', 'WhatsApp Business', 'Liaison directe avec vos prospects', 'Permet à Lucas de dialoguer sur WhatsApp pour la prise de rendez-vous commercial.', 'connected', '+33 1 56 78 90 12', '["+33156789012"]'::jsonb, '{"messagesToday": 18, "activeSessions": 5}'::jsonb),
      (v_commercialink_id, 'email', 'Email Gateway', 'Séquences de prospection commerciale', 'Envoi des devis et séquences de relance commerciale.', 'connected', 'commercial@servicallc322.com', '["claire.dubois@servicallc322.com"]'::jsonb, '{"messagesToday": 42, "activeSessions": 12}'::jsonb)
    ON CONFLICT (tenant_id, channel_id) DO UPDATE SET status = EXCLUDED.status, updated_at = NOW();
  END IF;

  -- ── C. HelpDesk360 (Agent: Clara - Support & Litiges) ─────────────────────
  IF v_helpdesk_id IS NOT NULL THEN
    INSERT INTO public.tenant_integrations (tenant_id, integration_id, name, category, provider, description, status, last_sync, metric_label, metric_value, account_details)
    VALUES
      (v_helpdesk_id, 'google-workspace', 'Google Workspace', 'mail', 'Google OAuth', 'Réception et traitement automatique des tickets clients et réclamations.', 'connected', 'Temps réel', 'Tickets traités', '54 réclamations résolues', 'support@recoviaa60a.fr'),
      (v_helpdesk_id, 'hubspot', 'HubSpot Service Hub', 'crm', 'HubSpot API', 'Gestion de la base de connaissances et de la satisfaction client.', 'connected', 'Il y a 5 min', 'CSAT moyen', '96% de satisfaction', 'Instance HelpDesk Pro')
    ON CONFLICT (tenant_id, integration_id) DO UPDATE SET status = EXCLUDED.status, updated_at = NOW();

    INSERT INTO public.tenant_channels (tenant_id, channel_id, name, tagline, description, status, connected_account, allowed_users, stats)
    VALUES
      (v_helpdesk_id, 'whatsapp', 'WhatsApp SAV Client', 'Assistance réactive en direct', 'Prise en charge instantanée des questions récurrentes des clients.', 'connected', '+33 9 12 34 56 78', '["+33912345678"]'::jsonb, '{"messagesToday": 29, "activeSessions": 7}'::jsonb),
      (v_helpdesk_id, 'email', 'Support Mail Gateway', 'Gestion des dossiers réclamations', 'Accusés de réception et résolution des litiges factures.', 'connected', 'support@recoviaa60a.fr', '["h.bernard@recoviaa60a.fr"]'::jsonb, '{"messagesToday": 63, "activeSessions": 15}'::jsonb)
    ON CONFLICT (tenant_id, channel_id) DO UPDATE SET status = EXCLUDED.status, updated_at = NOW();
  END IF;

  -- ── D. BatiPro Services (Agent: Victor - Marchés Publics) ──────────────────
  IF v_batipro_id IS NOT NULL THEN
    INSERT INTO public.tenant_integrations (tenant_id, integration_id, name, category, provider, description, status, last_sync, metric_label, metric_value, account_details)
    VALUES
      (v_batipro_id, 'bodacc', 'Veille Légale BODACC & BOAMP', 'legal', 'DILA Open Data', 'Surveillance quotidienne des avis de marchés publics BTP.', 'connected', 'Ce matin à 06:00', 'Appels d’offres ciblés', '7 opportunités détectées', 'Flux BOAMP BTP'),
      (v_batipro_id, 'pappers', 'Pappers API & Scoring', 'legal', 'Pappers Open Data', 'Vérification de solvabilité et attestations légales (DC1, DC2).', 'connected', 'Temps réel', 'Vérifications', '19 dossiers montés', 'Compte Pro BTP')
    ON CONFLICT (tenant_id, integration_id) DO UPDATE SET status = EXCLUDED.status, updated_at = NOW();

    INSERT INTO public.tenant_channels (tenant_id, channel_id, name, tagline, description, status, connected_account, allowed_users, stats)
    VALUES
      (v_batipro_id, 'telegram', 'Telegram Alertes Marchés', 'Notification instantanée des nouveaux appels d’offres', 'Alerte dès qu’un marché public BTP correspond aux critères de qualification.', 'connected', '@BatiProMarchesBot', '["julien.lefevre@batiprof38f.fr"]'::jsonb, '{"messagesToday": 5, "activeSessions": 1}'::jsonb),
      (v_batipro_id, 'email', 'Email AO Gateway', 'Dépôt des dossiers de candidature', 'Correspondance avec les acheteurs publics et plateformes DCE.', 'connected', 'marches@batiprof38f.fr', '["julien.lefevre@batiprof38f.fr"]'::jsonb, '{"messagesToday": 8, "activeSessions": 2}'::jsonb)
    ON CONFLICT (tenant_id, channel_id) DO UPDATE SET status = EXCLUDED.status, updated_at = NOW();
  END IF;

  -- ── E. EuroTech Conseil (Suite Complète : 4 agents) ───────────────────────
  IF v_eurotech_id IS NOT NULL THEN
    INSERT INTO public.tenant_integrations (tenant_id, integration_id, name, category, provider, description, status, last_sync, metric_label, metric_value, account_details)
    VALUES
      (v_eurotech_id, 'pennylane', 'Pennylane', 'erp', 'Pennylane API', 'Synchronisation comptable et facturation clients complète.', 'connected', 'Il y a 10 min', 'Factures suivies', '512 factures (340 000 €)', 'Pennylane Enterprise'),
      (v_eurotech_id, 'hubspot', 'HubSpot CRM', 'crm', 'HubSpot API', 'Pipeline d’affaires et scoring commercial B2B.', 'connected', 'Il y a 20 min', 'Pipeline actif', '48 opportunités', 'HubSpot Enterprise'),
      (v_eurotech_id, 'google-workspace', 'Google Workspace', 'mail', 'Google OAuth', 'Messagerie entreprise connectée aux 4 agents.', 'connected', 'Temps réel', 'E-mails gérés', '240 échanges automatisés', 'direction@ventelinkc009.com'),
      (v_eurotech_id, 'pappers', 'Pappers API & Scoring', 'legal', 'Pappers Open Data', 'Analyses financières et conformité des partenaires.', 'connected', 'Temps réel', 'Audits tiers', '94 analyses ce mois', 'Accès Illimité'),
      (v_eurotech_id, 'bodacc', 'Veille Légale BODACC', 'legal', 'DILA Open Data', 'Surveillance des partenaires et fournisseurs.', 'connected', 'Ce matin à 06:00', 'Alertes', '0 défaillance détectée', 'Flux actif')
    ON CONFLICT (tenant_id, integration_id) DO UPDATE SET status = EXCLUDED.status, updated_at = NOW();

    INSERT INTO public.tenant_channels (tenant_id, channel_id, name, tagline, description, status, connected_account, allowed_users, stats)
    VALUES
      (v_eurotech_id, 'whatsapp', 'WhatsApp Business Pro', 'Canal client & prospects unifié', 'Liaison directe pour Jérôme, Lucas et Clara.', 'connected', '+33 6 98 76 54 32', '["+33698765432"]'::jsonb, '{"messagesToday": 35, "activeSessions": 9}'::jsonb),
      (v_eurotech_id, 'telegram', 'Telegram Direction Console', 'Console mobile d’arbitrage pour dirigeants', 'Arbitrage 1-clic pour les relances, devis et litiges.', 'connected', '@EuroTechDirigeantBot', '["amelie.petit@ventelinkc009.com"]'::jsonb, '{"messagesToday": 14, "activeSessions": 3}'::jsonb),
      (v_eurotech_id, 'email', 'Email Suite Gateway', 'Relances, devis et service client', 'Passerelle mail unifiée pour la flotte d’agents.', 'connected', 'contact@ventelinkc009.com', '["amelie.petit@ventelinkc009.com"]'::jsonb, '{"messagesToday": 78, "activeSessions": 22}'::jsonb)
    ON CONFLICT (tenant_id, channel_id) DO UPDATE SET status = EXCLUDED.status, updated_at = NOW();
  END IF;

END $$;

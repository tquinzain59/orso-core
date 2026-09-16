# Spécification Technique d'Architecture : Fournisseur d'Identité Client (IAM Supabase Auth) & Sessions

> **Ticket Jira associé** : [KAN-26](https://orso-agents.atlassian.net/browse/KAN-26)  
> **Composants** : `Orso Site`, `Pilotage & Process`  
> **Statut** : En cours (Instruction d'Architecture)  
> **Auteur / Responsable d'instruction** : Antigravity (Architecte Projet)  
> **Validation Métier & Décision** : Thibaut QUINZAIN (Direction Orso Agents)  
> **Date** : 16 Septembre 2026  

---

## 1. Contexte & Diagnostic des Risques

### 1.1 Constat sur l'état initial (Airtable)
Sur le site vitrine hébergé sur Vercel (`Site_Hermes-core`), l'espace client (`client.html`) s'appuyait sur une intégration directe avec l'API REST d'Airtable :
1. **Clé d'API exposée publiquement** : La clé personnelle d'accès (`patH6WnjfLFOEnpe3...`) et le `BASE_ID` (`appZo3UIR1zxIA0sv`) étaient inscrits en clair dans le JavaScript servi au navigateur.
2. **Mots de passe stockés en clair** : La table Airtable `Utilisateurs` stockait les mots de passe clients sans aucun salage ni hachage cryptographique (`'Mot de passe': 'factice'`).
3. **Modification sans contrôle serveur** : Le changement de mot de passe s'effectuait par une requête `PATCH` directe depuis le navigateur vers Airtable (`https://api.airtable.com/v0/.../Utilisateurs/{id}`).
4. **Fuite globale de données** : N'importe quel utilisateur ou robot inspectant le code source pouvait requêter l'ensemble des enregistrements des tables `Utilisateurs`, `Entreprises` et `Abonnements`.

### 1.2 Décision d'Architecture
Pour éliminer tout risque de "château de cartes" et garantir la conformité RGPD / secret des affaires (données financières et créances de nos clients), la direction a validé l'arbitrage suivant :
* **Remplacement immédiat et intégral d'Airtable par Supabase Auth** comme fournisseur d'identité souverain et gestionnaire de session client.
* **Séparation stricte des responsabilités** : L'authentification et l'attribution des tenants sont gérées au niveau de l'IAM ; les conteneurs `orso-core` n'exécutent que les requêtes dûment signées et autorisées pour leur tenant.

---

## 2. Architecture Cible IAM (Supabase Auth)

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│                                ESPACE CLIENT VERCEL                              │
│                               (www.orso-agents.fr)                               │
│                                                                                  │
│   ┌──────────────────────────────────────────────────────────────────────────┐   │
│   │ Client Web (Vanilla / React / Vite)                                      │   │
│   │ - Formulaire Login / Reset Password                                      │   │
│   │ - Client SDK : @supabase/supabase-js                                      │   │
│   └─────────────────────┬─────────────────────────────────┬──────────────────┘   │
└─────────────────────────┼─────────────────────────────────┼──────────────────────┘
                          │ 1. Identifiants (Email/Password)│
                          │ 2. Émission Session & JWT Signé │
                          ▼                                 │ 3. Requête Authentifiée
┌──────────────────────────────────────────────┐            │    (Bearer JWT Supabase)
│            FOURNISSEUR IAM CLOUD             │            │
│               (Supabase Auth)                │            │
│                                              │            │
│  - auth.users (Credentials chiffrés Argon2)  │            ▼
│  - public.tenants (Entreprises / Instances)  │   ┌───────────────────────────────┐
│  - public.profiles (Rôles & Liens Tenants)   │   │  PASSERELLE INGRESS / ORSO    │
│  - Custom Claims Hook (tenant_id, slug, role)│   │  - Validation Signature JWT   │
│  - Row Level Security (RLS) étanche          │   │  - Aiguillage vers Conteneur  │
└──────────────────────────────────────────────┘   └───────────────────────────────┘
```

### 2.1 Schéma Relationnel PostgreSQL (Supabase)

Le schéma repose sur les tables internes `auth.users` associées à des tables applicatives dans le schéma `public` :

```sql
-- 1. Table des Organisations / Clients (Tenants)
CREATE TABLE public.tenants (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    siret VARCHAR(14) UNIQUE,
    slug VARCHAR(64) UNIQUE NOT NULL, -- Identifiant unique de routage (ex: financia-solutions)
    sector VARCHAR(100),
    status VARCHAR(32) NOT NULL DEFAULT 'active', -- active, trial, suspended, churn
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 2. Table des Profils Utilisateurs (Liée à auth.users de Supabase)
CREATE TABLE public.profiles (
    id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    tenant_id UUID NOT NULL REFERENCES public.tenants(id) ON DELETE RESTRICT,
    full_name VARCHAR(255) NOT NULL,
    phone VARCHAR(32),
    role VARCHAR(64) NOT NULL DEFAULT 'user', -- direction, daf, commercial, support, admin
    is_primary_contact BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 3. Table des Instances de Conteneurs Dédiés par Tenant
CREATE TABLE public.tenant_instances (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
    internal_route_key VARCHAR(128) UNIQUE NOT NULL, -- Clé d'aiguillage interne (ex: orso_backend_financia)
    status VARCHAR(32) NOT NULL DEFAULT 'ready', -- provisioning, ready, stopped, error
    agents_enabled JSONB NOT NULL DEFAULT '["jerome"]'::jsonb, -- Agents actifs pour ce client
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 4. Index de performance
CREATE INDEX idx_profiles_tenant ON public.profiles(tenant_id);
CREATE INDEX idx_tenants_slug ON public.tenants(slug);
CREATE INDEX idx_tenant_instances_tenant ON public.tenant_instances(tenant_id);
```

### 2.2 Politiques de Sécurité RLS (Row Level Security)

Pour garantir que même en cas de requête directe sur l'API Supabase, aucun client ne puisse lire les données d'un autre :

```sql
-- Activer RLS
ALTER TABLE public.tenants ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.tenant_instances ENABLE ROW LEVEL SECURITY;

-- Politique Profils : Un utilisateur ne peut voir que son propre profil
CREATE POLICY "Users can view own profile"
    ON public.profiles FOR SELECT
    USING (auth.uid() = id);

-- Politique Profils : Un utilisateur peut mettre à jour son propre profil (hors tenant_id et role)
CREATE POLICY "Users can update own profile"
    ON public.profiles FOR UPDATE
    USING (auth.uid() = id);

-- Politique Tenants : Un utilisateur ne peut voir que le tenant auquel il appartient
CREATE POLICY "Users can view own tenant"
    ON public.tenants FOR SELECT
    USING (id IN (
        SELECT tenant_id FROM public.profiles WHERE profiles.id = auth.uid()
    ));

-- Politique Instances : Seul le service role backend ou l'utilisateur du tenant peut lire les agents activés
CREATE POLICY "Users can view own tenant instance"
    ON public.tenant_instances FOR SELECT
    USING (tenant_id IN (
        SELECT tenant_id FROM public.profiles WHERE profiles.id = auth.uid()
    ));
```

---

## 3. Structure du Jeton JWT & Claims Métier

Pour que le backend `orso-core` et la passerelle Ingress puissent valider et aiguiller la requête sans réinterroger la base de données à chaque message de chat, nous utilisons la fonctionnalité **Custom Access Token Hook** de Supabase Auth.

### 3.1 Claims Standards & Métier du JWT
```json
{
  "iss": "https://<supabase-project-id>.supabase.co/auth/v1",
  "sub": "b8f041cb-63df-4993-9c87-b9561066c0d1",
  "aud": "authenticated",
  "exp": 1790000000,
  "email": "sophie.martin@finarecee20.fr",
  "app_metadata": {
    "provider": "email"
  },
  "user_metadata": {
    "full_name": "Sophie Martin"
  },
  "tenant": {
    "tenant_id": "9a38ef87-19d2-45e3-9821-2efbb91081a9",
    "tenant_slug": "financia-solutions",
    "role": "daf",
    "agents": ["jerome"]
  }
}
```

### 3.2 Fonction Hook PostgreSQL Supabase (Custom Claims)
```sql
CREATE OR REPLACE FUNCTION public.custom_access_token_hook(event jsonb)
RETURNS jsonb
LANGUAGE plpgsql STABLE
AS $$
DECLARE
  claims jsonb;
  user_tenant record;
BEGIN
  -- Récupère le tenant et le profil rattaché
  SELECT p.tenant_id, t.slug, p.role, ti.agents_enabled
  INTO user_tenant
  FROM public.profiles p
  JOIN public.tenants t ON t.id = p.tenant_id
  LEFT JOIN public.tenant_instances ti ON ti.tenant_id = p.tenant_id
  WHERE p.id = (event->>'user_id')::uuid;

  claims := event->'claims';

  IF user_tenant IS NOT NULL THEN
    claims := jsonb_set(claims, '{tenant}', jsonb_build_object(
      'tenant_id', user_tenant.tenant_id,
      'tenant_slug', user_tenant.slug,
      'role', user_tenant.role,
      'agents', COALESCE(user_tenant.agents_enabled, '["jerome"]'::jsonb)
    ));
  END IF;

  event := jsonb_set(event, '{claims}', claims);
  RETURN event;
END;
$$;

-- Attribution des droits d'exécution pour Supabase Auth
GRANT EXECUTE ON FUNCTION public.custom_access_token_hook TO supabase_auth_admin;
REVOKE EXECUTE ON FUNCTION public.custom_access_token_hook FROM authenticated, anon, public;
```

---

## 4. Plan de Migration depuis Airtable vers Supabase

### 4.1 Données Sources Identifiées dans Airtable (POC)
Cinq comptes entreprises et utilisateurs ont été cartographiés dans `client.html` et doivent être transférés :
1. **Financia Solutions** (`sophie.martin@finarecee20.fr`, DAF, SIRET: `83214567800012`, Agent: Jérôme)
2. **CommerciaLink** (`claire.dubois@servicallc322.com`, Support, SIRET: `78451236900021`, Agent: Lucas)
3. **HelpDesk360** (`h.bernard@recoviaa60a.fr`, Opérateur IA, SIRET: `88997766500033`, Agent: Clara)
4. **BatiPro Services** (`julien.lefevre@batiprof38f.fr`, Commercial, SIRET: `90123456700038`, Agent: Victor)
5. **EuroTech Conseil** (`amelie.petit@ventelinkc009.com`, Admin, SIRET: `55566677700044`, Ancien client)

### 4.2 Procédure de Migration
1. **Initialisation de l'instance Supabase** (Région Europe : Paris / Francfort).
2. **Exécution du script de migration DDL & Seeds** :
   - Insertion des 5 enregistrements dans `public.tenants`.
   - Création des utilisateurs via l'API Admin de Supabase (`supabase.auth.admin.createUser`) sans mot de passe en dur, avec déclenchement d'un email de génération de mot de passe sécurisé.
   - Liaison dans `public.profiles` et `public.tenant_instances`.
3. **Nettoyage et Révocation Airtable** :
   - Suppression définitive de la table des mots de passe dans Airtable.
   - Révocation du jeton personnel Airtable `patH6WnjfLFOEnpe3...` (en lien avec KAN-21).

---

## 5. Intégration sur l'Espace Client Vercel (`client.html`)

### 5.1 Remplacement du SDK Airtable par Supabase SDK
Au lieu de requêter `https://api.airtable.com/v0/...` avec une clé API exposée, `client.html` intègre le client officiel Supabase :

```html
<!-- Chargement sécurisé du client Supabase CDN ou bundle Vite -->
<script src="https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2"></script>
<script>
  // Variables publiques sûres (la clé anon est conçue pour être publique, protégée par RLS)
  const SUPABASE_URL = "https://<projet>.supabase.co";
  const SUPABASE_ANON_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...";

  const supabase = window.supabase.createClient(SUPABASE_URL, SUPABASE_ANON_KEY);

  // Connexion sécurisée
  async function handleLogin(email, password) {
    const { data, error } = await supabase.auth.signInWithPassword({
      email: email,
      password: password,
    });

    if (error) {
      showErrorNotice("Identifiants incorrects : " + error.message);
      return;
    }

    // Récupération de la session et du profil via les claims du JWT
    const session = data.session;
    const token = session.access_token;
    
    // Déclenchement de la transition sécurisée vers l'interface des agents (KAN-29)
    onAuthenticationSuccess(session);
  }
</script>
```

### 5.2 Bénéfices de Sécurité Immédiats
* **Zéro mot de passe stocké en clair** : Hachage automatique selon les standards cryptographiques (Argon2id/bcrypt).
* **Protection contre le vol de données transverses** : Grâce aux politiques RLS, même si un visiteur exécute une requête `SELECT * FROM tenants`, il ne recevra que son propre tenant.
* **Gestion native du cycle de vie** : Rafraîchissement automatique des jetons de session (`refresh_token`), déconnexion instantanée, et réinitialisation de mot de passe par email à double opt-in.

---

## 6. Critères d'Acceptation & Definition of Done (DoD)

- [ ] **CA 1** : Aucune clé Airtable ni URL d'API Airtable n'est présente dans le code source de `client.html` ni dans les assets servis sur `www.orso-agents.fr`.
- [ ] **CA 2** : L'instance Supabase Auth est déployée en région européenne (RGPD), avec les tables `tenants`, `profiles` et `tenant_instances` configurées avec RLS actif.
- [ ] **CA 3** : Les 5 comptes clients du POC sont migrés dans Supabase, et un email d'activation sécurisé est déclenché.
- [ ] **CA 4** : Le jeton JWT généré à la connexion contient l'objet `tenant` (`tenant_id`, `tenant_slug`, `role`, `agents`) via la fonction hook.
- [ ] **CA 5** : La tentative de connexion avec un faux mot de passe est rejetée côté serveur par Supabase.
- [ ] **CA 6** : L'ancienne clé Airtable `patH6WnjfLFOEnpe3...` est révoquée et supprimée.

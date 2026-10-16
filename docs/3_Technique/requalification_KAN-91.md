# Requalification KAN-91 — Alerte Stripe « intégration dépréciée » et réconciliation des comptes

> **Verdict technique : aucune correction de code applicatif n'est requise dans nos dépôts.**
> L'audit exhaustif des trois dépôts applicatifs (`orso-core`, `Site_Hermes-core`, `App_Hermes Core`) ainsi que la réconciliation en lecture seule entre la base de production Supabase (`public.subscriptions`) et l'API Stripe (`GET /v1/account`, `GET /v1/subscriptions`) démontrent :
> 1. **Aucun appel aux API Stripe héritées** (`v1/charges`, `v1/tokens`, `v1/sources`, `createToken`, `createSource`, `source=tok_...`) n'existe ni dans `orso-core`, ni dans `Site_Hermes-core` (`onboarding.html`), ni dans `App_Hermes Core`.
> 2. **100 % des intégrations de nos dépôts et des objets Stripe liés à la base de production** pointent vers le compte de test **`acct_1UKIuK06XM8Z6gbS`** (*« environnement de test ORSO-AGENTS »*).
> 3. **La contradiction des abonnements (CA6) est résolue** : les lignes de `financia-solutions` dans `public.subscriptions` (dont une seule est aujourd'hui `ACTIVE`, `dc88a4aa-b5fb-4d99-86b6-cca856a9ad8c`, après assainissement KAN-87) portent toutes `stripe_customer_id = null` et `stripe_subscription_id = null`. La seule ligne en base dotée d'un identifiant Stripe (`sub_1UMRLA06XM8Z6gbS523z0HNT`, `CANCELED`) appartient au compte de test `acct_1UKIuK06XM8Z6gbS` où elle figure également au statut `canceled` (`0` abonnement actif). Aucun abonnement de la base ne vit donc sur le compte `acct_1UKIuA0vnfOCTDYd`.

- **Référence Confluence** : Dossier PO `kan_91_dossier_po.md` (mandat v2 du 03/10/2026) et Charte globale du développeur Orso agents (page 26).
- **Dépôts et SHA inspectés** :
  - `orso-core` : `c13b03698c` (`main`)
  - `Site_Hermes-core` : `2aaffac` (`main`)
  - `App_Hermes Core` : arbre de travail local
- **Date de vérification** : 2026-10-16.

---

## 1. Vérification des prémisses du ticket face aux dépôts réels

| Affirmation du ticket | Constat vérifié |
| :--- | :--- |
| Lignes `22, 1941, 2321, 2361, 2373, 2385, 2411, 2434` de `olympe/ops_manager.py` (commit `0986522e78` du 01/10/2026) | **Numéros de lignes évolués sur `main` (`c13b03698c`)** : la table des tarifs `TIER_STRIPE_PRICES` est ligne `25` (commentaire du compte `acct_1UKIuK06XM8Z6gbS` ligne `24`), la clé est lue lignes `271` et `2891`, et les appels HTTP Stripe sont aux lignes `2349, 2931, 2943, 2955, 2981, 2987, 3004`. Le commit `0986522e78` (2026-10-01) modifiait `hermes_cli/web_routers/client_ui.py` ; le dernier commit touchant `olympe/ops_manager.py` est `f490d7b695` (2026-10-05). |
| `olympe/ops_manager.py` est le seul appelant Stripe | **Incomplet** : dans `orso-core`, trois fichiers appellent `https://api.stripe.com/v1/` : `olympe/ops_manager.py` (7 sites), `hermes_cli/web_routers/client_ui.py` (13 sites) et `scripts/iam/bootstrap_stripe_products.py` (4 sites). Côté front-end, `Site_Hermes-core/onboarding.html` charge `https://js.stripe.com/v3/`. |
| Aucun appel `Charges`, aucun jeton (`Token`), aucune source en ligne (`Source`) | **Confirmé sur 100 % des dépôts** (`orso-core`, `Site_Hermes-core`, `App_Hermes Core`) et dans leur historique Git. |
| Le serveur définit `STRIPE_TEST_SECRET_KEY` tandis que le code lit `STRIPE_SECRET_KEY` | **Confirmé côté code** : tous les composants de `orso-core` lisent exclusivement `STRIPE_SECRET_KEY` (ainsi que `STRIPE_WEBHOOK_SECRET` dans `olympe/server.py:605`). La chaîne `STRIPE_TEST_SECRET_KEY` n'existe nulle part dans les dépôts. |

---

## 2. Analyse détaillée par Critère d'Acceptation (CA1 à CA6)

### CA1 — Inventaire exhaustif des appels à l'API Stripe dans nos dépôts et absence d'API héritées

#### A. Dépôt `orso-core` (`c13b03698c`)
Tous les appels passent par `urllib.request` vers `https://api.stripe.com/v1/<endpoint>` (aucun SDK Python tiers) :
1. **`olympe/ops_manager.py`** (wrapper `_stripe_request` ligne `2890`, URL ligne `2895`) :
   - Ligne `2349` : `GET subscriptions/{sub_id}` (lecture d'abonnement).
   - Ligne `2931` : `GET customers?email=...&limit=1` (recherche client par email).
   - Ligne `2943` : `POST customers` (création client sans `source` ni `token`).
   - Ligne `2955` : `POST setup_intents` avec `automatic_payment_methods[enabled]=true` et `usage=off_session` (chemin moderne d'empreinte bancaire).
   - Ligne `2981` : `POST payment_methods/{payment_method_id}/attach` (rattachement d'un `pm_...` au client).
   - Ligne `2987` : `POST customers/{customer_id}` avec `invoice_settings[default_payment_method]=payment_method_id`.
   - Ligne `3004` : `POST subscriptions` avec `default_payment_method`, `items[0][price]` et `trial_period_days=30`.
2. **`hermes_cli/web_routers/client_ui.py`** (wrapper `_stripe_request` ligne `2368`, URL ligne `2390`) :
   - Lignes `2788, 2957, 3068` : `GET customers?email=...&limit=1`.
   - Lignes `2796, 3074` : `POST customers` (sans `source` ni `token`).
   - Lignes `2807, 2961` : `GET subscriptions?customer=...&limit=1`.
   - Lignes `2831, 2840` : `GET payment_methods?customer=...&type=card|sepa_debit&limit=1`.
   - Lignes `2847, 3116` : `GET invoices?customer=...&limit=10` et `GET invoices/{invoice_id}`.
   - Ligne `2967` : `POST subscriptions/{sub_id}` (changement de palier `items[0][price]` avec `proration_behavior=create_prorations`).
   - Ligne `3085` : `POST billing_portal/sessions` (ouverture du portail client Stripe).
3. **`scripts/iam/bootstrap_stripe_products.py`** (wrapper `stripe_request` ligne `54`, URL ligne `55`) :
   - Lignes `79, 87` : `GET products?limit=100` et `GET prices?limit=100&active=true`.
   - Lignes `108, 124` : `POST products` et `POST prices`.

#### B. Dépôt `Site_Hermes-core` (`2aaffac`)
L'inspection du dépôt du site vitrine (`Site_Hermes-core/onboarding.html`) lève l'hypothèse d'un formulaire de carte hérité :
- Ligne `17` : chargement de `<script src="https://js.stripe.com/v3/"></script>`.
- Ligne `1168` : `const STRIPE_PUBLISHABLE_KEY = "pk_test_51UKIuK06XM8Z6gbS...yF1n"` — cette clé publique appartient au compte de test **`acct_1UKIuK06XM8Z6gbS`**, et **non** au compte `acct_1UKIuA0vnfOCTDYd`.
- Lignes `2581–2670` (`initStripePaymentElement`) :
  - Depuis le commit `2aaffac` du `2026-10-05` (`[KAN-45] fix(vitrine): neutralisation onboarding autonome`), la fonction affiche un bandeau d'essai gratuit 30 jours et fait `return;` ligne `2621` avant tout appel Stripe, puis `finalizeOrder()` (ligne `2737`) envoie la demande à `POST /api/olympe/contact`.
  - Entre le commit `4ebab54` (`2026-09-27`) et `2aaffac` (`2026-10-05`), le formulaire utilisait exclusivement le chemin moderne : `POST /api/olympe/onboarding/init-setup` → `stripeInstance.elements({ clientSecret, appearance })` → `stripeElements.create('payment', ...)` (lignes `2656–2657`) → `stripeInstance.confirmSetup({ elements: stripeElements, ... })`.
  - Avant le commit `4ebab54` (`2026-09-27`), la page ne chargeait même pas `js.stripe.com` (simple maquette HTML statique).
- **Conclusion sur `Site_Hermes-core`** : aucun appel à `createToken`, `createSource` ou `v1/charges` n'a jamais existé dans `Site_Hermes-core`.

#### C. Dépôt `App_Hermes Core`
Aucune occurrence de `stripe` dans le dépôt `App_Hermes Core`.

---

### CA2 — Origine de l'alerte et liste des angles morts hors dépôts

- **Absence prouvée dans l'ensemble des dépôts détenus** (`orso-core`, `Site_Hermes-core`, `App_Hermes Core`) : aucune référence au compte `acct_1UKIuA0vnfOCTDYd` (hors documentation PO KAN-91) et aucun appel aux API dépréciées (`Charges`, `Tokens`, `Sources`).
- **Angles morts externes (seules sources possibles de l'alerte sur `acct_1UKIuA0vnfOCTDYd`)** :
  1. **Intégration ou plugiciel tiers connecté directement au compte Stripe `acct_1UKIuA0vnfOCTDYd`** (outil de facturation externe, connecteur no-code/Zapier/Make, ancienne intégration SaaS ou test externe ayant utilisé une clé `sk_...` / `pk_...` du compte `acct_1UKIuA0vnfOCTDYd`).
  2. **Action ou test via la console Stripe / Stripe CLI** exécuté directement sur le compte `acct_1UKIuA0vnfOCTDYd`.
  - Pour identifier l'appel exact (date, IP, User-Agent, endpoint `POST /v1/charges` ou `POST /v1/customers` avec `source`), Thibaut peut ouvrir dans la console Stripe du compte `ORSO-AGENTS` (`acct_1UKIuA0vnfOCTDYd`) la vue **Développeurs > Journaux (Logs)** filtrée sur les méthodes `POST /v1/charges` et `POST /v1/customers` avant le `03/10/2026`.

---

### CA3 — Localisation des clés Stripe utilisées et compte effectivement désigné

1. **Dans `orso-core` (`.env` et `docker-compose`)** :
   - Variables injectées : `STRIPE_SECRET_KEY` (`docker-compose.olympe.yml:53`, `docker-compose.orso.yml:22`), `STRIPE_WEBHOOK_SECRET` (`docker-compose.olympe.yml:54`), `STRIPE_PUBLISHABLE_KEY` (`docker-compose.orso.yml:23`).
   - Dans l'environnement d'exécution (`.env` ligne `30`), `STRIPE_SECRET_KEY` vaut `sk_test_51UKIuK06XM8Z6gbS...iuxE` (et `STRIPE_PUBLISHABLE_KEY` ligne `31` vaut `pk_test_51UKIuK06XM8Z6gbS...yF1n`).
   - L'appel en lecture seule `GET https://api.stripe.com/v1/account` avec cette clé retourne :
     `{"id": "acct_1UKIuK06XM8Z6gbS", "country": "FR", "display_name": "environnement de test ORSO-AGENTS", "charges_enabled": false}`.
2. **Dans `Site_Hermes-core` (`onboarding.html:1168`)** :
   - La constante `STRIPE_PUBLISHABLE_KEY` (`pk_test_51UKIuK06XM8Z6gbS...yF1n`) désigne ce même compte **`acct_1UKIuK06XM8Z6gbS`**.
3. **Concernant la clé du compte `acct_1UKIuA0vnfOCTDYd` (`ORSO-AGENTS`)** :
   - **Aucune clé** (`sk_test_51UKIuA...`, `sk_live_51UKIuA...`, `pk_...51UKIuA...`) appartenant à `acct_1UKIuA0vnfOCTDYd` n'est présente dans nos dépôts ni dans nos fichiers `.env`.

---

### CA4 — Rôle des deux comptes Stripe et liste des abonnements

| Compte Stripe | Nom affiché | Mode / Rôle constaté | Abonnements présents (`GET /v1/subscriptions?status=all`) |
| :--- | :--- | :--- | :--- |
| **`acct_1UKIuK06XM8Z6gbS`** | `environnement de test ORSO-AGENTS` | **Compte de test actif du projet** : porte les 4 tarifs Orso (`price_1UKJ6W06XM8Z6gbS...` à `99 €`, `169 €`, `229 €`, `279 €`), le webhook `https://ops.orso-agents.fr/api/olympe/ops/webhooks/stripe`, la clé `.env` du superviseur et la clé publique de `onboarding.html`. | **`0` abonnement actif** (`status=active`) ; **`2` abonnements de test résiliés** (`status=canceled`) : `sub_1UMRLA06XM8Z6gbS523z0HNT` (`tenant_slug: nexis-solutions`, ticket `KAN-44`) et `sub_1UKbW706XM8Z6gbSOg8Wk2ua` (`tenant_slug: clientx-orso`, `drone-qualification`). |
| **`acct_1UKIuA0vnfOCTDYd`** | `ORSO-AGENTS` | **Compte principal d'organisation** (visé par l'alerte email Stripe du 03/10/2026). Aucune clé de ce compte n'est configurée dans nos dépôts. | Non interrogeable par API sans clé (et interdiction de mettre une clé de production tant que le POC n'est pas validé). Mais la lecture de la base de production (CA6 ci-dessous) prouve qu'**aucun abonnement de la base de production n'y a été créé**. |

---

### CA5 — Parcours de paiement de test et journal Stripe

- **État** : Le code d'empreinte bancaire de `olympe/ops_manager.py` (`POST /v1/setup_intents` ligne `2955` + `POST /v1/payment_methods/{id}/attach` ligne `2981` + `POST /v1/subscriptions` ligne `3004`) utilise déjà exclusivement l'API moderne (`SetupIntent` + `PaymentMethod`).
- Les derniers événements enregistrés sur le compte `acct_1UKIuK06XM8Z6gbS` (`GET /v1/events?limit=10`) sont exclusivement des événements modernes : `setup_intent.created`, `customer.created`, `billing_portal.session.created`, sans aucune erreur ni appel déprécié.
- Côté vitrine (`Site_Hermes-core/onboarding.html`), l'étape de paiement autonome a été neutralisée le `05/10/2026` (commit `2aaffac`, arbitrage KAN-45 : demande d'essai 30 jours sans empreinte bancaire directe). Aucune modification de code n'ayant été nécessaire dans `orso-core`, aucun nouveau paiement d'écriture n'a été déclenché.

---

### CA6 — Résolution de la contradiction entre la base de production et Stripe (côte à côte)

Le ticket relevait une contradiction apparente : *« deux abonnements actifs pour `financia-solutions` en base de production, zéro chez Stripe sur le compte `acct_1UKIuK06XM8Z6gbS` »*, suggérant que ces abonnements pouvaient vivre sur l'autre compte (`acct_1UKIuA0vnfOCTDYd`).

La lecture croisée en lecture seule de **`public.subscriptions` (base de production Supabase)** et de **`GET /v1/subscriptions?status=all` (Stripe `acct_1UKIuK06XM8Z6gbS`)** tranche définitivement ce point :

| Source | Lignes / Objets retournés | Identifiants Stripe (`stripe_customer_id` / `stripe_subscription_id`) | Statut | Concordance |
| :--- | :--- | :--- | :--- | :--- |
| **Base de production (`public.subscriptions`)** | 1. `cd8f68a7-b3f7-4886-af5a-97bdb8bbbc8a` (tenant `3a4cb49e-...` / `nexis-solutions`) | `cus_VNBi...kcCn` / `sub_1UMRLA06XM8Z6gbS523z0HNT` | `CANCELED` | **100 % concordant** : l'abonnement `sub_1UMRLA06XM8Z6gbS523z0HNT` existe sur le compte de test `acct_1UKIuK06XM8Z6gbS` avec `"status": "canceled"`. |
| **Base de production (`public.subscriptions`)** | 2. `dc88a4aa-b5fb-4d99-86b6-cca856a9ad8c` (tenant `f3e25379-...` / `financia-solutions`, créé le `28/09/2026`) | `null` / `null` | `ACTIVE` (seule ligne active du tenant) | **100 % expliqué** : ligne créée en base sans appel Stripe (`stripe_subscription_id: null`), d'où `0` abonnement actif chez Stripe. |
| **Base de production (`public.subscriptions`)** | 3. `013d7102-3bf8-4d89-a1e0-ff10754b31bd` (`financia-solutions`, créé le `03/10/2026` à `12:36 UTC`) | `null` / `null` | `CANCELED` (annulé le `03/10/2026` à `15:26 UTC`) | **100 % expliqué** : doublon en base sans identifiant Stripe (`null`), aujourd'hui passé à `CANCELED` (KAN-87). |
| **Base de production (`public.subscriptions`)** | 4. `49e86460-e367-459b-a754-befc84ce9b90` (`financia-solutions`, créé le `03/10/2026` à `15:27 UTC`) | `null` / `null` | `CANCELED` (annulé le `03/10/2026` à `15:36 UTC`) | **100 % expliqué** : ligne de test en base sans identifiant Stripe (`null`), passée à `CANCELED`. |
| **Stripe (`acct_1UKIuK06XM8Z6gbS`)** | `GET /v1/subscriptions` (actives) : `0`<br>`GET /v1/subscriptions?status=all` : `2` (`sub_1UMRLA06XM8Z6gbS523z0HNT` et `sub_1UKbW706XM8Z6gbSOg8Wk2ua`) | Infixe de compte `06XM8Z6gbS` sur les deux objets | `canceled` | **100 % concordant** avec la base : aucun abonnement actif chez Stripe, et le seul `stripe_subscription_id` stocké en base est bien sur `acct_1UKIuK06XM8Z6gbS`. |

---

## 3. Preuves — Commandes exactes et sorties brutes

### 3.1 Inventaire des appels Stripe et recherche d'API héritées dans `orso-core` (CA1, CA2)

```text
$ git rev-parse --short HEAD
c13b03698c

$ git grep -nE 'api\.stripe\.com' -- '*.py' '*.ts' '*.tsx' '*.js' '*.sh' ':!website' ':!hermes_cli/tui_dist'
hermes_cli/web_routers/client_ui.py:2390:    url = f"https://api.stripe.com/v1/{endpoint}"
olympe/ops_manager.py:2895:        url = f"https://api.stripe.com/v1/{endpoint}"
scripts/iam/bootstrap_stripe_products.py:55:    url = f"https://api.stripe.com/v1/{endpoint}"
[rc=0]

$ git grep -nE '_stripe_request\(|[^_]stripe_request\(' -- '*.py' ':!tests' | grep -v 'def '
hermes_cli/web_routers/client_ui.py:2788:            cust_res = _stripe_request(f"customers?email={urllib.parse.quote(clean_email)}&limit=1")
hermes_cli/web_routers/client_ui.py:2796:                new_cust = _stripe_request("customers", method="POST", data={
hermes_cli/web_routers/client_ui.py:2807:                sub_res = _stripe_request(f"subscriptions?customer={stripe_customer_id}&limit=1")
hermes_cli/web_routers/client_ui.py:2831:                pm_res = _stripe_request(f"payment_methods?customer={stripe_customer_id}&type=card&limit=1")
hermes_cli/web_routers/client_ui.py:2840:                    sepa_res = _stripe_request(f"payment_methods?customer={stripe_customer_id}&type=sepa_debit&limit=1")
hermes_cli/web_routers/client_ui.py:2847:                inv_res = _stripe_request(f"invoices?customer={stripe_customer_id}&limit=10")
hermes_cli/web_routers/client_ui.py:2957:            cust_res = _stripe_request(f"customers?email={urllib.parse.quote(user_email.strip().lower())}&limit=1")
hermes_cli/web_routers/client_ui.py:2961:                sub_res = _stripe_request(f"subscriptions?customer={customer_id}&limit=1")
hermes_cli/web_routers/client_ui.py:2967:                    _stripe_request(
hermes_cli/web_routers/client_ui.py:3068:    cust_res = _stripe_request(f"customers?email={urllib.parse.quote(clean_email)}&limit=1")
hermes_cli/web_routers/client_ui.py:3074:        new_cust = _stripe_request("customers", method="POST", data={
hermes_cli/web_routers/client_ui.py:3085:        portal_res = _stripe_request(
hermes_cli/web_routers/client_ui.py:3116:            inv = _stripe_request(f"invoices/{invoice_id}")
olympe/ops_manager.py:2349:                live_sub_data = self._stripe_request(f"subscriptions/{sub_id}")
olympe/ops_manager.py:2931:        cust_search = self._stripe_request(f"customers?email={urllib.parse.quote(clean_email)}&limit=1")
olympe/ops_manager.py:2943:            new_cust = self._stripe_request("customers", method="POST", data=cust_payload)
olympe/ops_manager.py:2955:        setup_intent = self._stripe_request("setup_intents", method="POST", data=si_payload)
olympe/ops_manager.py:2981:            self._stripe_request(f"payment_methods/{payment_method_id}/attach", method="POST", data={"customer": customer_id})
olympe/ops_manager.py:2987:            self._stripe_request(
olympe/ops_manager.py:3004:        sub = self._stripe_request("subscriptions", method="POST", data=sub_payload)
scripts/iam/bootstrap_stripe_products.py:79:    existing_products_resp = stripe_request("products?limit=100")
scripts/iam/bootstrap_stripe_products.py:87:    existing_prices_resp = stripe_request("prices?limit=100&active=true")
scripts/iam/bootstrap_stripe_products.py:108:            prod = stripe_request("products", method="POST", data=prod_payload)
scripts/iam/bootstrap_stripe_products.py:124:            price = stripe_request("prices", method="POST", data=price_payload)
[rc=0]

$ git grep -nE 'v1/(charges|tokens|sources)|"(charges|tokens|sources)(\?|/)|stripe\.(Charge|Token|Source)|createToken\(|createSource|["'\'' ](tok|src)_[A-Za-z0-9]{8,}|payment_method_data|card\[(number|cvc|exp)' -- olympe hermes_cli/web_routers scripts apps web docker-compose.orso.yml docker-compose.olympe.yml deploy templates ':!hermes_cli/tui_dist' ':!**/dist/**' ':!**/node_modules/**'
olympe/lifecycle_manager.py:379:            src_profiles = (source_template_dir / "profiles") if source_template_dir else (project_root / "profiles")
olympe/lifecycle_manager.py:380:            if src_profiles.is_dir():
[rc=0]  # Note : variable Python locale src_profiles sans rapport avec Stripe
```

### 3.2 Inspection du dépôt `Site_Hermes-core` et `App_Hermes Core` (CA1, CA2)

```text
$ git -C "../Site_Hermes-core" rev-parse --short HEAD
2aaffac

$ git -C "../Site_Hermes-core" grep -nE 'js\.stripe\.com|STRIPE_PUBLISHABLE_KEY|stripeInstance|stripeElements|confirmSetup|createToken|createSource|v1/charges' -- '*.html' '*.js' | sed 's/pk_test_[A-Za-z0-9]*/pk_test_51UKIuK06XM8Z6gbS...yF1n/g'
onboarding.html:17:    <script src="https://js.stripe.com/v3/"></script>
onboarding.html:1168:        const STRIPE_PUBLISHABLE_KEY = "pk_test_51UKIuK06XM8Z6gbS...yF1n";
onboarding.html:1173:        let stripeInstance = null;
onboarding.html:1174:        let stripeElements = null;
onboarding.html:2597:                if (!stripeInstance) {
onboarding.html:2598:                    stripeInstance = Stripe(STRIPE_PUBLISHABLE_KEY);
onboarding.html:2656:                stripeElements = stripeInstance.elements({ clientSecret, appearance });
onboarding.html:2657:                stripePaymentElement = stripeElements.create('payment', {
[rc=0]

$ grep -rnI "stripe\|1UKIu" "../App_Hermes Core" --exclude-dir=node_modules --exclude-dir=.git --exclude-dir=dist -i
[rc=1]  # Aucune occurrence dans App_Hermes Core
```

### 3.3 Inspection des clés (valeurs masquées) et lecture seule de l'API Stripe et de Supabase (CA3, CA4, CA6)

```text
$ python3 -c '... inspection masquée .env + GET /v1/account + GET /v1/subscriptions?status=all + GET /rest/v1/subscriptions ...'
.env:30: STRIPE_SECRET_KEY=sk_test_51UK...iuxE
.env:31: STRIPE_PUBLISHABLE_KEY=pk_test_51UK...yF1n

Stripe /v1/account:
  {"id": "acct_1UKIuK06XM8Z6gbS", "country": "FR", "display_name": "environnement de test ORSO-AGENTS", "charges_enabled": false}

Stripe /v1/subscriptions (actives):
  count = 0

Stripe /v1/subscriptions?status=all:
  count = 2
  - id="sub_1UMRLA06XM8Z6gbS523z0HNT", status="canceled", customer="cus_VNBi...kcCn", default_payment_method="pm_1UMRL506XM8Z6gbSAcd2rzjk", price="price_1UKJ6W06XM8Z6gbS5id4Hf0s", metadata={"tenant_slug": "nexis-solutions", "ticket": "KAN-44"}
  - id="sub_1UKbW706XM8Z6gbSOg8Wk2ua", status="canceled", customer="cus_VLI6...cVF4", default_payment_method=null, price="price_1UKJ6W06XM8Z6gbS5id4Hf0s", metadata={"origine": "drone-qualification", "tenant_slug": "clientx-orso"}

Supabase public.subscriptions (4 lignes, lecture seule):
  - id="cd8f68a7-b3f7-4886-af5a-97bdb8bbbc8a", tenant_id="3a4cb49e-970c-46a4-ada5-70163f2bee06" (nexis-solutions), status="CANCELED", tier_id="1_agent", stripe_customer_id="cus_VNBi...kcCn", stripe_subscription_id="sub_1UMRLA06XM8Z6gbS523z0HNT", stripe_payment_method_id=null
  - id="dc88a4aa-b5fb-4d99-86b6-cca856a9ad8c", tenant_id="f3e25379-6531-479e-b276-3b3185e7421b" (financia-solutions), status="ACTIVE", tier_id="2_agents", stripe_customer_id=null, stripe_subscription_id=null, stripe_payment_method_id=null
  - id="013d7102-3bf8-4d89-a1e0-ff10754b31bd", tenant_id="f3e25379-6531-479e-b276-3b3185e7421b" (financia-solutions), status="CANCELED", tier_id="2_agents", stripe_customer_id=null, stripe_subscription_id=null, stripe_payment_method_id=null
  - id="49e86460-e367-459b-a754-befc84ce9b90", tenant_id="f3e25379-6531-479e-b276-3b3185e7421b" (financia-solutions), status="CANCELED", tier_id="2_agents", stripe_customer_id=null, stripe_subscription_id=null, stripe_payment_method_id=null
```

### 3.4 Contrôle statique (`ruff check`)

```text
$ source .venv/bin/activate && ruff check olympe/ops_manager.py olympe/server.py hermes_cli/web_routers/client_ui.py scripts/iam/bootstrap_stripe_products.py
All checks passed!
[rc=0]
```

---

## 4. Récapitulatif de conformité des Critères d'Acceptation

| Critère | Statut | Preuve et synthèse |
| :--- | :--- | :--- |
| **CA1** — Liste des appels Stripe dans nos dépôts et absence d'appels hérités | **Vérifié (100 %)** | Inventaire complet fichier/ligne sur `orso-core` (`ops_manager.py`, `client_ui.py`, `bootstrap_stripe_products.py`), `Site_Hermes-core` (`onboarding.html`) et `App_Hermes Core` (§2 et §3.1–3.2). Zéro appel aux API `Charges`, `Tokens` ou `Sources`. |
| **CA2** — Origine de l'alerte et angles morts nommés | **Vérifié (Absence prouvée dans nos dépôts + angles morts nommés)** | Aucun dépôt détenu ne référence `acct_1UKIuA0vnfOCTDYd` ni n'utilise d'API dépréciée. L'alerte provient d'un appel externe aux dépôts sur le compte `acct_1UKIuA0vnfOCTDYd` (plugiciel/service tiers ou test console), identifiable uniquement dans `Developers > Logs` de la console Stripe de `acct_1UKIuA0vnfOCTDYd`. |
| **CA3** — Localisation des clés et compte désigné | **Vérifié côté dépôts et `.env` ; clé `acct_1UKIuA0vnfOCTDYd` absente** | `STRIPE_SECRET_KEY` (`.env:30`) et `STRIPE_PUBLISHABLE_KEY` (`.env:31` et `Site_Hermes-core/onboarding.html:1168`) désignent toutes `acct_1UKIuK06XM8Z6gbS` (`GET /v1/account`). Aucune clé du compte `acct_1UKIuA0vnfOCTDYd` n'est présente dans nos dépôts ou `.env`. |
| **CA4** — Rôle des deux comptes et liste des abonnements | **Vérifié** | `acct_1UKIuK06XM8Z6gbS` = environnement de test actif (`0` abonnement actif, `2` abonnements de test `canceled`). `acct_1UKIuA0vnfOCTDYd` = compte principal d'organisation, non utilisé par le code et ne portant aucun abonnement de la base de production (§2 CA4 & §3.3). |
| **CA5** — Parcours de test et journal Stripe sans dépréciation | **Vérifié sur le journal existant (sans écriture nouvelle)** | Le backend (`ops_manager.py:2955-3004`) est déjà sur `SetupIntent` + `PaymentMethod`, et le journal `GET /v1/events` de `acct_1UKIuK06XM8Z6gbS` ne comporte que des événements modernes (`setup_intent.created`, `billing_portal.session.created`). Aucune écriture nouvelle déclenchée conformément aux contraintes. |
| **CA6** — Contradiction des abonnements tranchée (base vs Stripe) | **Vérifié (100 %)** | Lecture côte à côte de `public.subscriptions` et `GET /v1/subscriptions?status=all` (§2 CA6 & §3.3) : `financia-solutions` a `1` ligne `ACTIVE` (`dc88a4aa-...`) et `2` lignes `CANCELED`, toutes trois avec `stripe_subscription_id = null`. La seule ligne avec ID Stripe (`sub_1UMRLA06XM8Z6gbS523z0HNT`, `CANCELED`) concorde exactement avec `acct_1UKIuK06XM8Z6gbS`. |

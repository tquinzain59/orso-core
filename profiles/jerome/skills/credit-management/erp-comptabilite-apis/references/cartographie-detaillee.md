# Cartographie détaillée des API ERP/Comptabilité TPE-PME françaises

*Résultats de probing curl — session août 2026. Revérifier périodiquement (les éditeurs ouvrent/ferment leurs API).*

## 1. Pennylane — ✅ API publique complète

- **Site** : https://pennylane.com
- **Doc API** : https://pennylane.readme.io/docs/api-overview (HTTP 200)
- **Base URL** : `https://api.pennylane.com/v1/` (v2 actuelle)
- **Auth** : OAuth 2.0 + Bearer token
- **Sandbox** : ✅ Oui (mode sandbox documenté)
- **Endpoints credit management** :
  - `Customers` : getList, getOne, filter, create, update (individual & company)
  - `Customer invoices` : create, filter (by status, date, customer), downpayment (facture d'acompte), draft
  - `Supplier invoices` : filter, import
  - `Payments` : automating payment matching, create, list
  - `Credit notes` : filter, create
  - `Ledger entries` : create, filter, lines, accounts
  - `Suppliers` : filter
  - `Products` : filter
- **Pages de doc vérifiées** :
  - `/docs/getting-started`, `/docs/authorization`, `/docs/oauth-20-walkthrough`
  - `/docs/api-overview`, `/docs/api-v2-vs-v1`, `/docs/api-public-roadmap`
  - `/docs/customer-invoicing`, `/docs/create-a-customer-invoice-use-case`
  - `/docs/automating-payment-matching`
  - `/docs/filter-my-customers`, `/docs/filter-my-customer-invoices`, `/docs/filter-my-credit-notes`
  - `/docs/generating-my-api-token`, `/docs/rate-limiting-1`
- **Note** : doc hébergée sur Readme.io (plateforme standard), très bien structurée. La version v2 remplace v1.

## 2. Sellsy — ✅ API publique (v1 complète, v2 partielle)

- **Site** : https://www.sellsy.com
- **Doc v1** : https://docs.sellsy.com/api/v1/documentation/methods (HTTP 200, 1,3 Mo, ~230 méthodes)
- **Doc v2** : https://api.sellsy.com/doc/v2/ (HTTP 200, Redoc SPA — spec non téléchargeable)
- **Auth v1** : OAuth 1.0a (consumer key/secret + request token + access token + signature)
- **Auth v2** : OAuth 2.0 + Bearer
- **Sandbox** : ⚠️ Non documentée publiquement
- **Endpoints credit management (v1, style RPC)** :
  - `Client.create`, `Client.getList`, `Client.getOne`, `Client.update`, `Client.delete`
  - `Client.addAddress`, `Client.updateAddress`, `Client.addContact`, `Client.getContact`
  - `Client.getBankAccountList`, `Client.getBillingContact`, `Client.getMargin`
  - `Client.transformToProspect`, `Client.updateOwner`, `Client.updatePrefs`
  - `Invoice.*` (factures), `Payment.*` (paiements), `Avoir` (avoirs), `Facture` (factures)
- **Pages de doc v1 vérifiées** :
  - `/documentation/oauth` (OAuth 1.0a), `/documentation/curl`, `/documentation/postman`
  - `/documentation/methods`, `/documentation/principles`, `/documentation/rules`
- **Note** : API v1 style RPC (méthodes `Objet.méthode`), pas REST. Body JSON avec `method` et `params`. La v2 est plus moderne mais la spec n'est pas publiquement téléchargeable (301 sur `/openapi.json`).

## 3. Evoliz — ✅ API publique, OpenAPI complet

- **Site** : https://www.evoliz.com
- **Doc** : https://evoliz.io/documentation (HTTP 200, Redoc)
- **Spec OpenAPI** : https://evoliz.io/api-docs/api-docs.yaml (HTTP 200, 830 Ko, 22 793 lignes, v1.54)
- **Auth** : Clé API (public key + secret key → POST `/api/login` → Bearer token, validité 20 min)
- **Sandbox** : ⚠️ Pas de sandbox explicite (le login par clés permet des tests)
- **Endpoints credit management (REST, `/api/v1/companies/{companyid}/...`)** :
  - **Clients** : `GET/POST /clients`, `GET/PUT/DELETE /clients/{clientid}`, `GET /contacts-clients`, `GET /client-addresses`
  - **Factures** : `GET/POST /invoices`, `GET/PUT /invoices/{invoiceid}`, `POST /invoices/{id}/create`, `POST /invoices/{id}/credit` (avoir), `POST /invoices/{id}/partial-credit`, `GET /invoices/{id}/items`, `GET /invoices/{id}/progress`
  - **Paiements** : `GET/POST /payments`, `GET/PUT/DELETE /payments/{paymentid}`
  - **Avoirs/Credits** : `GET/POST /credits`
  - **Acomptes** : `GET/POST /advances`, `POST /advances/{id}/payments`
  - **Rapports credit management** :
    - `GET /reports/overdue-payment` (retards de paiement)
    - `GET /reports/overdue-settlement` (règlements en retard)
    - `GET /reports/turnover` (chiffre d'affaires)
  - **Journaux comptables** : `/journals/trial-balance`, `/journals/general-ledger`, `/journals/sales`, `/journals/purchases`, `/journals/banks`, `/journals/cashes`, `/journals/opening-balance`, `/journals/miscellaneous-operations`, `/journals/fec`
  - **Achats/Fournisseurs** : `/buys`, `/supplier-credits`, `/purchase-classifications`
- **Note** : meilleure spec OpenAPI du panel (830 Ko parsée). Les endpoints `/reports/overdue-payment` et `/reports/overdue-settlement` sont directement pertinents pour le credit management.

## 4. QuickBooks Online (Intuit) — ✅ API publique mature

- **Site** : https://quickbooks.intuit.com
- **Doc** : https://developer.intuit.com/app/developer/qbo/docs/develop (HTTP 200)
- **Auth** : OAuth 2.0
- **Sandbox** : ✅ Oui (sandbox Intuit dédiée)
- **Endpoints credit management (REST v3, `/v3/company/{companyid}/...`)** :
  - `Customer` (CRUD), `Invoice` (CRUD), `Payment` (CRUD), `CreditMemo` (CRUD)
  - `Account`, `Bill`, `Vendor`, `JournalEntry`, `Deposit`, `Purchase`
- **Note** : Intuit s'est retiré du marché français. API reste accessible pour comptes existants. Pas pertinent pour nouveaux déploiements TPE/PME françaises.

## 5. Cegid — ⚠️ Portail développeur, accès sur inscription

- **Site** : https://www.cegid.com
- **Portail** : https://developers.cegid.com (HTTP 200, "Cegid Developer Portal", Next.js)
- **Auth** : Clé d'abonnement (subscription key) — portail type Azure API Management
- **Sandbox** : ⚠️ Test intégré au portail ("test them directly from the portal"), pas de sandbox séparée
- **Endpoints** : APIs produits (Cegid Retail, Cegid Cloud, Cegid HR) — liste précise derrière authentification (login requis)
- **Note** : page Next.js rendue côté client — le HTML curl contient du JS, pas le contenu lisible. Chercher dans les métadonnées JSON embarquées.

## 6. Sage — ⚠️ API existe, doc bloquée par Cloudflare

- **Site** : https://www.sage.com/fr-fr/
- **Portail dev** : https://developer.sage.com (HTTP 403 Cloudflare Challenge en curl)
- **Auth** : OAuth 2.0 (connu publiquement pour Sage Business Cloud Accounting)
- **Sandbox** : ✅ Oui (sandbox Sage, documentée publiquement)
- **Endpoints connus (Sage Business Cloud Accounting API)** :
  - `contacts` (customers/suppliers), `invoices`, `payments`, `bank_transactions`, `journals`, `sales_invoices`, `purchase_invoices`
- **Note** : toutes les URLs `developer.sage.com/*` retournent 403 en curl (Cloudflare Challenge anti-bot). L'API existe bien mais n'est pas vérifiable en curl direct. Accès via navigateur ou API Gateway après inscription.

## 7. Dougs — ⚠️ API-first mentionné, non documenté

- **Site** : https://www.dougs.fr
- **Page API** : https://www.dougs.fr/mcp (HTTP 200) + https://www.dougs.fr/api (HTTP 200)
- **Auth** : Non documenté publiquement
- **Sandbox** : Non documenté
- **Endpoints** : Aucun endpoint public exposé
- **Note** : Dougs mentionne "API-first", "REST", et "MCP" (Model Context Protocol) sur ses pages mais sans documentation technique publique. Page `/api-first-cgu` 404, `/api-first` 404. Probablement en cours d'ouverture — revérifier.

## 8. EBP — ⚠️ Programme intégrateur, pas de doc publique

- **Site** : https://www.ebp.com
- **Page intégrateur** : https://www.ebp.com/partenaires-revendeur-integrateur-ebp/ (HTTP 200)
- **Auth** : Non documenté publiquement
- **Endpoints** : Non documentés publiquement
- **Note** : la page partenaire mentionne "api", "rest", "json" mais aucune documentation technique publique. URLs `/api`, `/developpeurs`, `/integrations`, `developer.ebp.com`, `api.ebp.com` toutes 404/000. Accès sur demande via programme intégrateur.

## 9. Acomba — ⚠️ SDK payant, marché canadien

- **Site** : https://www.acomba.com (HTTP 200)
- **Page développeurs** : https://www.acomba.com/partenaires/developpeurs/ (HTTP 200)
- **Auth** : Clé d'identification (sur demande) + services Web via ACCEO Connecte
- **Sandbox** : ⚠️ Licence d'intégration + services Web (payant, sur demande)
- **Endpoints** : SDK Acomba (formats ADX, GL/CC/CF/P Import), services Web via ACCEO Connecte. Pas d'API REST publique documentée.
- **Note** : Acomba (ACCEO Solutions) s'adresse exclusivement au marché canadien (Québec). Pas pertinent pour TPE/PME françaises. Forfaits développeur : Acolyte (0$/an), Compagnon (692$/an), Compagnon Plus (856$/an), Associé (944$/an), Associé Plus (1077$/an).

## 10. Tiime — ❌ Aucune API publique

- **Site** : https://www.tiime.fr (HTTP 200)
- **URLs testées (toutes 404 ou injoignables)** :
  - `https://www.tiime.fr/api` → 404
  - `https://www.tiime.fr/integrations` → 404
  - `https://www.tiime.fr/developpeurs` → 404
  - `https://api.tiime.fr` → 404
  - `https://docs.tiime.fr` → 404
  - `https://developers.tiime.fr` → 404
  - `https://help.tiime.fr` → 000 (injoignable)
  - `https://intercom.help/tiime` → 404
- **Note** : aucune mention d'API publique sur le site. Tiime est un logiciel de comptabilité/facturation TPE fermé.

## 11. Indy — ❌ Aucune API publique

- **Site** : https://www.indy.fr (HTTP 200)
- **URLs testées (toutes 404 ou injoignables)** :
  - `https://www.indy.fr/api` → 404
  - `https://docs.indy.fr` → 000 (DNS injoignable)
  - `https://help.indy.fr` → 000 (DNS injoignable)
  - `https://developer.indy.fr` → 000 (DNS injoignable)
  - `https://api.indy.fr` → 000 (DNS injoignable)
  - `https://www.indy.fr/developers` → 404
- **Note** : aucune mention d'API publique sur le site. Indy est un logiciel de comptabilité pour auto-entrepreneurs/TPE fermé.
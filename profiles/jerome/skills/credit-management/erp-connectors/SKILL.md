---
name: erp-connectors
description: Se connecter aux ERP et logiciels de comptabilite des TPE/PME francaises (Sellsy, Sage, QuickBooks, Odoo, Dynamics 365 BC, Cegid, Evoliz) pour recuperer les donnees credit management (clients, factures, paiements, balance agee).
version: 1.0
---

# Skill : Connecteurs ERP pour TPE/PME francaises

## Contexte

Le credit manager a besoin de recuperer les donnees comptables et commerciales depuis l'ERP/logiciel de gestion du client pour alimenter l'analyse credit et le recouvrement : encours clients, factures impayees, balance agee, historique de paiements.

## Tableau synoptique

| Solution | Type | API publique | Auth | Base URL | Niveau credit mgmt |
|----------|------|-------------|------|----------|---------------------|
| Sellsy | Facturation/CRM | Oui (V1+V2) | OAuth 2.0 | api.sellsy.com/v2 | Excellent |
| Sage Business Cloud | Comptabilite | Oui | OAuth 2.0 | api.accounting.sage.com/v3.1 | Excellent |
| QuickBooks (Intuit) | Comptabilite | Oui | OAuth 2.0 | quickbooks.api.intuit.com/v3 | Excellent |
| Cegid | ERP | Portail dev | Cle API Azure | developers.cegid.com | Selon module |
| Odoo | ERP open source | Oui (JSON-RPC) | Session | {url_odoo} | Excellent |
| Dynamics 365 BC | ERP | Oui (OData v4) | OAuth 2.0 | api.businesscentral.dynamics.com/v2.0 | Excellent |
| Evoliz | Facturation | Limitee (WP REST) | Nonce WP | www.evoliz.com/wp-json/evoliz/v1 | Basique |
| Tiime | Comptabilite TPE | Non | - | - | Non disponible |
| Pennylane | Comptabilite | Non | - | - | Non disponible |
| Indy | Comptabilite TPE | Non | - | - | Non disponible |
| Dougs | Comptabilite TPE | Non | - | - | Non disponible |
| EBP | Comptabilite/ERP | Non | - | - | Non disponible |
| Acomba | Comptabilite | Non | - | - | Non disponible |

## Donnees credit management recherchees

| Donnee | Usage | Endpoint type |
|--------|-------|---------------|
| Liste des clients | Identification des debiteurs | GET /customers |
| Factures emises | Suivi des encours et echeances | GET /invoices |
| Factures impayees | Recouvrement amiable | GET /invoices?status=unpaid |
| Paiements recus | Suivi des encaissements | GET /payments |
| Avoirs | Suivi des litiges | GET /credit-notes |
| Balance agee | Analyse des risques | Calculee depuis factures |
| Encours client | Suivi des limites de credit | GET /customers/{id}/balance |

## Connecteur 1 : Sellsy (facturation / CRM)

Sellsy est un CRM + facturation en ligne populaire chez les TPE/PME francaises. Deux versions d'API : V2 (REST moderne, OAuth 2.0) et V1 (OAuth 1.0a, legacy).

### Authentification (OAuth 2.0)

Creer une application sur Sellsy (Parametres > API), recuperer client_id et client_secret.

```bash
# Obtenir un token
curl -s -X POST "https://api.sellsy.com/v2/oauth/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=client_credentials&client_id=$SELLSY_CLIENT_ID&client_secret=$SELLSY_CLIENT_SECRET"
```

### Endpoints credit management (V2)

| Methode | Endpoint | Description |
|---------|----------|-------------|
| GET | /v2/contacts | Liste des clients |
| GET | /v2/contacts/{id} | Detail d'un client |
| GET | /v2/invoices | Liste des factures |
| GET | /v2/invoices/{id} | Detail d'une facture |
| GET | /v2/payments | Liste des paiements |
| GET | /v2/estimates | Liste des devis |
| GET | /v2/credits | Liste des avoirs |

### Commandes

```bash
# Clients
curl -s "https://api.sellsy.com/v2/contacts?type=client&limit=100" \
  -H "Authorization: Bearer $SELLSY_TOKEN"

# Factures impayees
curl -s "https://api.sellsy.com/v2/invoices?status=unpaid&limit=100" \
  -H "Authorization: Bearer $SELLSY_TOKEN"

# Paiements
curl -s "https://api.sellsy.com/v2/payments?limit=100" \
  -H "Authorization: Bearer $SELLSY_TOKEN"
```

Documentation V2 : https://api.sellsy.com/doc/v2
Documentation V1 : https://docs.sellsy.com/api/v1/documentation

## Connecteur 2 : Sage Business Cloud Accounting

Sage Business Cloud Accounting (anciennement Sage One) est une solution de comptabilite en ligne pour TPE/PME.

### Authentification (OAuth 2.0)

Portail developpeur : https://developer.sage.com (peut etre protege par Cloudflare, utiliser un navigateur pour l'inscription). Creer une app, s'abonner a l'API Accounting, recuperer client_id et client_secret.

### Endpoints credit management (V3.1)

| Methode | Endpoint | Description |
|---------|----------|-------------|
| GET | /contacts | Liste des clients/fournisseurs |
| GET | /contacts/{id} | Detail d'un contact |
| GET | /sales_invoices | Liste des factures de vente |
| GET | /sales_invoices/{id} | Detail d'une facture |
| GET | /sales_invoices/{id}/payments | Paiements d'une facture |
| POST | /sales_invoices/{id}/payments | Enregistrer un paiement |
| GET | /sales_credit_notes | Avoirs |
| GET | /bank_transactions | Transactions bancaires |

### Commandes

```bash
curl -s "https://api.accounting.sage.com/v3.1/sales_invoices" \
  -H "Authorization: Bearer $SAGE_TOKEN"

curl -s "https://api.accounting.sage.com/v3.1/sales_invoices?status=UNPAID" \
  -H "Authorization: Bearer $SAGE_TOKEN"

curl -s "https://api.accounting.sage.com/v3.1/contacts?contact_type=CUSTOMER" \
  -H "Authorization: Bearer $SAGE_TOKEN"
```

Doc : https://developer.sage.com/api/accounting

## Connecteur 3 : QuickBooks Online (Intuit)

QuickBooks Online d'Intuit est utilise par certaines PME francaises, notamment avec filiales internationales. API tres mature.

Base URL : https://quickbooks.api.intuit.com/v3 (prod) / https://sandbox-quickbooks.api.intuit.com/v3 (sandbox)

### Authentification (OAuth 2.0)

Creer une app sur https://developer.intuit.com. Le token donne acces a un realm_id (identifiant de l'entreprise).

### Endpoints credit management (V3)

| Methode | Endpoint | Description |
|---------|----------|-------------|
| GET | /company/{realm}/customer | Liste des clients |
| GET | /company/{realm}/invoice | Liste des factures |
| GET | /company/{realm}/payment | Liste des paiements |
| GET | /company/{realm}/creditmemo | Avoirs |
| GET | /company/{realm}/query?query=... | Requetes SQL-like |

### Requetes SQL-like

QuickBooks permet d'utiliser un langage de requete SQL-like :

```bash
# Factures impayees
curl -s "https://quickbooks.api.intuit.com/v3/company/$REALM_ID/query?query=SELECT * FROM Invoice WHERE Balance > '0'" \
  -H "Authorization: Bearer $QBO_TOKEN"

# Balance agee par client
curl -s "https://quickbooks.api.intuit.com/v3/company/$REALM_ID/query?query=SELECT CustomerId, SUM(Balance) FROM Invoice WHERE Balance > '0' GROUP BY CustomerId" \
  -H "Authorization: Bearer $QBO_TOKEN"
```

Doc : https://developer.intuit.com/app/developer/qbo/docs/api
Sandbox : https://developer.intuit.com/app/developer/sandbox

## Connecteur 4 : Cegid

Cegid est un editeur francais majeur d'ERP (retail, paie, gestion). Portail developpeur : https://developers.cegid.com

### Authentification

Cle API Azure APIM (Ocp-Apim-Subscription-Key) + token. Creer un compte sur developers.cegid.com, s'abonner a l'API, recuperer la cle de subscription.

```bash
curl -s "https://api.cegid.com/..." \
  -H "Ocp-Apim-Subscription-Key: $CEGID_KEY" \
  -H "Authorization: Bearer $CEGID_TOKEN"
```

Les endpoints dependent du produit Cegid (Retail, Paie, etc.). Necessite un compte Cegid pour la doc detaillee.

## Connecteur 5 : Odoo

ERP open source, self-hosted ou SaaS (odoo.com). API mature et gratuite.

### Authentification (JSON-RPC / Session)

```bash
curl -s -X POST "https://MONODOO/web/session/authenticate" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","params":{"db":"nom_base","login":"admin","password":"mot_de_passe"}}'
# Reutiliser le cookie de session pour les appels suivants
```

### Modeles credit management

| Modele Odoo | Equivalent credit management |
|-------------|------------------------------|
| res.partner | Clients (filtrer sur customer_rank > 0) |
| account.move | Factures (move_type=out_invoice) / Avoirs (out_refund) |
| account.payment | Paiements |

Le champ res.partner.credit contient l'encours total du client (solde debiteur).

### Commandes (JSON-RPC)

```bash
# Clients avec encours
curl -s -X POST "https://MONODOO/web/dataset/call_kw" \
  -H "Content-Type: application/json" \
  -b "session_id=SESSION_COOKIE" \
  -d '{"jsonrpc":"2.0","method":"call","params":{"model":"res.partner","method":"search_read","args":[[["credit",">",0]]],"kwargs":{"fields":["name","credit","debit"],"limit":100}}}'

# Factures impayees
curl -s -X POST "https://MONODOO/web/dataset/call_kw" \
  -H "Content-Type: application/json" \
  -b "session_id=SESSION_COOKIE" \
  -d '{"jsonrpc":"2.0","method":"call","params":{"model":"account.move","method":"search_read","args":[[["move_type","=","out_invoice"],["payment_state","!=","paid"]]],"kwargs":{"fields":["name","partner_id","amount_total","amount_residual","invoice_date_due"],"limit":100}}}'
```

Doc : https://www.odoo.com/documentation/developer/reference/external_api.html

## Connecteur 6 : Dynamics 365 Business Central

ERP cloud de Microsoft, utilise par certaines PME francaises avec un SI Microsoft.

### Authentification (OAuth 2.0 Azure AD)

Enregistrer une app dans Azure AD, ajouter les permissions API pour Business Central, recuperer client_id, client_secret, tenant_id. Flux Client Credentials ou Authorization Code.

Base URL : https://api.businesscentral.dynamics.com/v2.0/{tenant}/production/api/v2.0

### Endpoints credit management (OData v4)

| Methode | Endpoint | Description |
|---------|----------|-------------|
| GET | /customers | Liste des clients |
| GET | /salesInvoices | Liste des factures |
| GET | /customerPayments | Paiements clients |
| GET | /salesCreditMemos | Avoirs |
| GET | /agedAccountsReceivable | Balance agee (endpoint natif!) |

### Commandes

```bash
# Clients
curl -s "https://api.businesscentral.dynamics.com/v2.0/$BC_TENANT_ID/production/api/v2.0/customers" \
  -H "Authorization: Bearer $BC_TOKEN"

# Balance agee (endpoint natif)
curl -s "https://api.businesscentral.dynamics.com/v2.0/$BC_TENANT_ID/production/api/v2.0/agedAccountsReceivable" \
  -H "Authorization: Bearer $BC_TOKEN"

# Factures impayees (filtre OData)
curl -s "https://api.businesscentral.dynamics.com/v2.0/$BC_TENANT_ID/production/api/v2.0/salesInvoices?\$filter=status eq 'Open'" \
  -H "Authorization: Bearer $BC_TOKEN"
```

Doc : https://learn.microsoft.com/en-us/dynamics365/business-central/dev-itpro/api-reference/v2.0/

## Connecteur 7 : Evoliz

Logiciel de facturation/gestion pour TPE francaises. API limitee basee sur WordPress REST.

```bash
curl -s "https://www.evoliz.com/wp-json/evoliz/v1/glossaire" -H "Accept: application/json"
```

Page connexion API : https://www.evoliz.com/api

## Solutions SANS API publique

| Solution | Alternatives |
|----------|-------------|
| Tiime | Export CSV/Excel manuel |
| Pennylane | Integrations via Zapier/Make |
| Indy | Pas d'API |
| Dougs | Pas d'API |
| EBP | Export depuis le logiciel |
| Acomba | Export CSV |

### Strategie pour solutions sans API

1. Demander un export manuel (CSV/Excel) regulier
2. Demander l'acces en lecture a l'interface
3. Automatiser l'export (tache planifiee) si possible
4. Utiliser le script scripts/import_csv.py pour normaliser

## Variables d'environnement

```bash
# Sellsy
export SELLSY_CLIENT_ID="..." SELLSY_CLIENT_SECRET="..." SELLSY_TOKEN="..."
# Sage
export SAGE_CLIENT_ID="..." SAGE_CLIENT_SECRET="..." SAGE_TOKEN="..."
# QuickBooks
export QBO_CLIENT_ID="..." QBO_CLIENT_SECRET="..." QBO_TOKEN="..." QBO_REALM_ID="..."
# Cegid
export CEGID_KEY="..." CEGID_TOKEN="..."
# Dynamics 365 BC
export BC_TENANT_ID="..." BC_CLIENT_ID="..." BC_CLIENT_SECRET="..." BC_TOKEN="..."
# Odoo
export ODOO_URL="..." ODOO_DB="..." ODOO_USER="..." ODOO_PASSWORD="..."
```

## Pieges et points d'attention

1. **Quotas et rate limiting** : espacer les requetes en cas d'erreur 429.
2. **OAuth 2.0 token refresh** : les tokens expirent (generalement 1h). Implementer un refresh automatique.
3. **Pagination** : toutes les API paginent. Utiliser page/offset/cursor selon l'API.
4. **Devises** : verifier la devise des montants (EUR vs autres).
5. **Filtres de date** : les API peuvent limiter la profondeur historique.
6. **Cegid : Azure APIM** : header Ocp-Apim-Subscription-Key obligatoire en plus du token.
7. **Odoo : version** : les modeles/champs different entre versions (14, 15, 16, 17).
8. **Sellsy V1 vs V2** : preferer V2 (OAuth 2.0, REST propre).
9. **Dynamics 365 BC : environnement** : l'URL change selon l'environnement (production, sandbox).
10. **Solutions sans API** : negocier avec le client un export regulier automatise.

## Verification du fonctionnement

```bash
# Sellsy
curl -s "https://api.sellsy.com/v2/contacts?limit=1" -H "Authorization: Bearer $SELLSY_TOKEN" | python3 -m json.tool | head -5

# Sage
curl -s "https://api.accounting.sage.com/v3.1/contacts?limit=1" -H "Authorization: Bearer $SAGE_TOKEN" | python3 -m json.tool | head -5

# QuickBooks
curl -s "https://quickbooks.api.intuit.com/v3/company/$QBO_REALM_ID/query?query=SELECT * FROM Customer MAXRESULTS 1" -H "Authorization: Bearer $QBO_TOKEN" | python3 -m json.tool | head -5

# Odoo
curl -s -X POST "$ODOO_URL/web/session/authenticate" -H "Content-Type: application/json" -d "{\"jsonrpc\":\"2.0\",\"params\":{\"db\":\"$ODOO_DB\",\"login\":\"$ODOO_USER\",\"password\":\"$ODOO_PASSWORD\"}}" | python3 -m json.tool | head -5
```

## Scripts utilitaires

- scripts/balance_agee.py : construit une balance agee a partir des factures impayees de differentes API
- scripts/import_csv.py : importe et normalise un export CSV/Excel pour les ERP sans API

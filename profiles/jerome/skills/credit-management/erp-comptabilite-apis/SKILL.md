---
name: erp-comptabilite-apis
description: Cartographier les API des ERP et logiciels de comptabilité/facturation/gestion des TPE-PME françaises (Pennylane, Sellsy, Evoliz, Sage, Cegid, EBP, Dougs, Tiime, Indy, Acomba, QuickBooks) pour l'intégration credit management — auth, sandbox, endpoints customers/invoices/payments.
version: 1.0
---

# Skill : Cartographie des API ERP / Comptabilité TPE-PME françaises

## Quand utiliser cette skill

- L'utilisateur demande de cartographier, recenser, ou vérifier les API de logiciels de comptabilité/ERP/facturation français.
- L'utilisateur veut connecter un outil de credit management à un ERP comptable (récupérer clients, factures, paiements, soldes, encours).
- L'utilisateur demande quels logiciels TPE/PME ont une API ouverte (REST/OAuth) et un mode sandbox.
- On doit évaluer la faisabilité d'un connecteur vers un logiciel comptable français.

## Méthodologie de vérification des API

### Étape 1 : Probe systématique des URLs candidates

Pour chaque éditeur, tester en curl un ensemble d'URLs candidates (site principal, /api, /developers, /docs, developer.* et api.* sous-domaines). Toujours utiliser un User-Agent navigateur :

```bash
for url in "https://www.editeur.fr" "https://www.editeur.fr/api" "https://api.editeur.fr" \
           "https://docs.editeur.fr" "https://developer.editeur.fr" "https://developers.editeur.fr"; do
  code=$(curl -sS -o /dev/null -w "%{http_code}" -L --max-time 15 -A "Mozilla/5.0" "$url" 2>/dev/null)
  echo "$code  $url"
done
```

**Interprétation des codes :**
- `200` : page existe — récupérer le contenu et chercher API/oauth/swagger/openapi
- `403` : souvent Cloudflare/anti-bot (ex: Sage). L'API existe probablement mais n'est pas vérifiable en curl direct.
- `404` : page n'existe pas
- `000` : DNS injoignable / connexion refusée

### Étape 2 : Récupérer le contenu des pages 200

```bash
curl -sSL --max-time 20 -A "Mozilla/5.0" "https://www.editeur.fr/api" | \
  sed -e 's/<[^>]*>//g' | grep -iE "api|oauth|token|rest|endpoint|sandbox|swagger|openapi"
```

Chercher dans le HTML les liens vers documentation, spec OpenAPI, Swagger, Redoc.

### Étape 3 : Récupérer et parser la spec OpenAPI si disponible

Quand une doc Redoc est trouvée (ex: Evoliz `https://evoliz.io/documentation`), la spec YAML/JSON est souvent chargée par JavaScript. Chercher dans le HTML le chemin de la spec :

```bash
# Evoliz : le HTML contient Redoc.init("/api-docs/api-docs.yaml?...")
curl -sSL "https://evoliz.io/api-docs/api-docs.yaml" -o /tmp/spec.yaml
# Puis parser les paths :
grep -nE "^  \"/" /tmp/spec.yaml | head -80
```

### Étape 4 : Compiler le tableau synthétique

Pour chaque solution : nom, type, API (oui/non), URL doc, auth (OAuth2 / clé API / SDK), sandbox (oui/non), endpoints credit management.

## Solutions de référence et statut API

### ✅ API confirmée et documentée publiquement

| Solution | Type | URL documentation | Auth | Sandbox | Endpoints credit management |
|----------|------|-------------------|------|---------|------------------------------|
| **Pennylane** | ERP comptabilité/facturation TPE-PME | `https://pennylane.readme.io/docs/api-overview` | OAuth 2.0 + Bearer (base `https://api.pennylane.com/v1/`) | ✅ Oui | Customers, Customer invoices (create, filter, downpayment), Supplier invoices, Payments (automating matching), Ledger entries, Credit notes, Suppliers, Products |
| **Sellsy** | CRM + facturation/gestion commerciale | v1 : `https://docs.sellsy.com/api/v1/documentation/methods` ; v2 : `https://api.sellsy.com/doc/v2/` | v1 : OAuth 1.0a (consumer key/secret + token/signature) ; v2 : OAuth 2.0 + Bearer | ⚠️ Non documenté | `Client.create/getList/getOne/update/delete`, `Client.addAddress/addContact`, `Invoice.*`, `Payment.*`, `Avoir` (avoirs), `Facture` (factures) |
| **Evoliz** | Facturation + gestion commerciale TPE-PME | `https://evoliz.io/documentation` (Redoc) + spec OpenAPI `https://evoliz.io/api-docs/api-docs.yaml` (830 Ko, v1.54) | Clé API (public key + secret key → login → Bearer token, validité 20 min) | ⚠️ Pas explicite | `/api/v1/companies/{id}/clients`, `/clients/{clientid}`, `/invoices`, `/invoices/{id}/create`, `/invoices/{id}/credit` (avoir), `/invoices/{id}/partial-credit`, `/payments`, `/payments/{id}`, `/credits`, `/advances`, `/advances/{id}/payments`, `/reports/overdue-payment`, `/reports/overdue-settlement`, `/journals/trial-balance`, `/journals/sales`, `/journals/banks` |
| **QuickBooks Online (Intuit)** | ERP comptabilité (US/global) | `https://developer.intuit.com/app/developer/qbo/docs/develop` | OAuth 2.0 | ✅ Oui (sandbox Intuit) | `Customer`, `Invoice`, `Payment`, `Account`, `CreditMemo`, `Bill`, `Vendor` (REST v3, `/v3/company/{id}/...`) |

### ⚠️ API existante mais accès restreint

| Solution | Type | URL | Note |
|----------|------|-----|------|
| **Cegid** | ERP PME (Cegid Business, Cegid Cloud, Retail/HR) | `https://developers.cegid.com` (portail, HTTP 200) | Auth par subscription key (portail type Azure API Management). Endpoints précis derrière login. |
| **Sage** | ERP PME (Sage 50, Sage 100, Sage Business Cloud Accounting, Intacct) | `https://developer.sage.com` | HTTP 403 Cloudflare Challenge en curl. API Sage Business Cloud Accounting existe (OAuth 2.0, endpoints contacts/invoices/payments/bank_transactions/journals) — vérifier via navigateur. |

### ⚠️ API partielle / non documentée publiquement

| Solution | Type | URL | Note |
|----------|------|-----|------|
| **Dougs** | Expert-comptable en ligne + facturation | `https://www.dougs.fr/mcp` (HTTP 200) | Page mentionne "API-first", "REST", "MCP" mais aucun endpoint public. |
| **EBP** | Logiciel comptabilité/gestion PME | `https://www.ebp.com/partenaires-revendeur-integrateur-ebp/` | Mentions "api/rest/json" mais pas de doc publique. Programme intégrateur sur demande. |
| **Acomba** | Logiciel comptabilité/gestion PME (marché canadien) | `https://www.acomba.com/partenaires/developpeurs/` | SDK + services Web via ACCEO Connecte, programme payant. Pas d'API REST publique. Marché canadien, pas France. |

### ❌ Aucune API publique trouvée

| Solution | Type | Note |
|----------|------|------|
| **Tiime** | Comptabilité/facturation TPE | Toutes URLs testées 404 ou injoignable. Pas de mention d'API publique. |
| **Indy** | Comptabilité TPE/auto-entrepreneurs | Toutes URLs 404 ou DNS injoignable. Pas de mention d'API publique. |

## Recommandations pour un connecteur credit management

**Note : Odoo et Dynamics 365 Business Central ont ete ajoutes comme connecteurs supplementaires lors de la session du 2026-08-26. Voir le skill `erp-connectors` pour leur documentation detaillee (Odoo: JSON-RPC sur res.partner/account.move ; Dynamics 365 BC: OData v4 avec endpoint natif `/agedAccountsReceivable` pour la balance agee).**

**Priorite 1 (meilleure couverture, API publique, sandbox) :**
1. **Pennylane** — OAuth 2.0, sandbox, endpoints complets customers/invoices/payments/credit notes + payment matching automatisé. Meilleure couverture credit management.
2. **Evoliz** — Clé API → Bearer, OpenAPI complet, endpoints `/reports/overdue-payment` et `/reports/overdue-settlement` directement pertinents.

**Priorité 2 (API mature mais marché limité France) :**
3. **QuickBooks Online** — OAuth 2.0 + sandbox, API REST mature, mais Intuit s'est retiré du marché français.

**Priorité 3 (API existante mais accès restreint) :**
4. **Sellsy** — API v1 OAuth 1.0a très complète (~230 méthodes), v2 OAuth 2.0 mais doc moins accessible.
5. **Cegid** — portail développeur accessible mais endpoints derrière authentification.
6. **Sage** — API Business Cloud Accounting confirmée mais doc inaccessible en curl (Cloudflare).

**Pas de connecteur possible sans accord commercial :**
- Tiime, Indy (pas d'API publique), Dougs, EBP, Acomba (API fermée/programme payant).

## Pièges et points d'attention

1. **Cloudflare / anti-bot** — `developer.sage.com` retourne 403 en curl (Cloudflare Challenge). Ne pas conclure que l'API n'existe pas — vérifier via navigateur ou documenter le blocage.

2. **Spec OpenAPI non téléchargeable** — Sellsy v2 affiche une page Redoc SPA mais `/openapi.json` retourne 301 puis un HTML, pas la spec. La spec v2 n'est pas publiquement téléchargeable. Utiliser la doc v1 (HTML statique, ~230 méthodes) qui est complète.

3. **Pages SPA (React/Next.js)** — Cegid et Dougs utilisent Next.js/React : le contenu est rendu côté client. Le HTML récupéré par curl contient du JS et des métadonnées mais pas le contenu lisible. Chercher dans les props JSON embarquées (`__next_f`, `__shellInternal`).

4. **Sellsy v1 : méthodes RPC-style** — L'API v1 utilise un style RPC (`Client.create`, `Invoice.getList`) et non REST. Les "endpoints" sont des noms de méthodes, pas des chemins URL. Le body est JSON avec `method` et `params`.

5. **Evoliz : auth par session courte** — Le token Bearer Evoliz expire après 20 minutes. Prévoir un refresh régulier via `/api/login` avec public key + secret key.

6. **Acomba : marché canadien** — Acomba (ACCEO Solutions) s'adresse exclusivement au marché canadien (Québec). Pas pertinent pour TPE/PME françaises malgré la présence historique du nom dans le paysage comptable francophone.

7. **Dougs : MCP et API-first** — Dougs expose une page `/mcp` (Model Context Protocol) et mentionne "API-first" mais sans documentation publique des endpoints. Probablement en cours d'ouverture — revérifier périodiquement.

8. **QuickBooks France** — Intuit s'est retiré du marché français. QuickBooks Online n'est plus commercialisé aux nouvelles entreprises françaises. L'API reste accessible pour les comptes existants.

9. **Chevauchement avec `erp-connectors`** — Le skill `erp-connectors` couvre le meme domaine avec 7 connecteurs documentes (Sellsy, Sage, QuickBooks, Cegid, Odoo, Dynamics 365 BC, Evoliz) + 2 scripts utilitaires (`balance_agee.py` multi-ERP, `import_csv.py` pour ERP sans API). Ce skill (`erp-comptabilite-apis`) est plus detaille sur Pennylane, Evoliz (spec OpenAPI) et Sellsy V1 (230 methodes). Les deux skills sont complementaires — le background curator devrait envisager une consolidation.

10. **Parsing CSV francais** — Les exports CSV d'ERP francais utilisent le format de date `dd/mm/yyyy` non compatible avec `datetime.fromisoformat()`. Utiliser `datetime.strptime(val, "%d/%m/%Y")`. Les noms de colonnes ont une casse variable (Numero, Client, Montant TTC) — toujours faire un mapping insensible a la casse.

11. **skill_manage `content` parameter** — L'action `create` de skill_manage requiert le parametre `content` (pas `file_content` ou `file_path`). Si le contenu est trop volumineux pour un seul appel, ecrire le fichier directement via `execute_code` puis utiliser `skill_manage` pour les operations ulterieures.

## Fichiers liés

- `references/cartographie-detaillee.md` — tableau complet avec URLs vérifiées, codes HTTP, endpoints détaillés par solution, et notes de probing par éditeur.
- `scripts/probe-api-urls.sh` — script réutilisable pour tester systématiquement les URLs d'API candidates d'un éditeur et détecter les pages de documentation.

## Vérification du fonctionnement

```bash
# Test rapide : vérifier que les 4 API principales sont accessibles
for url in "https://pennylane.readme.io/docs/api-overview" \
           "https://docs.sellsy.com/api/v1/documentation/methods" \
           "https://evoliz.io/documentation" \
           "https://developer.intuit.com/app/developer/qbo/docs/develop"; do
  code=$(curl -sS -o /dev/null -w "%{http_code}" -L --max-time 15 -A "Mozilla/5.0" "$url" 2>/dev/null)
  echo "$code  $url"
done
# Attendu : 200 pour les 4
```
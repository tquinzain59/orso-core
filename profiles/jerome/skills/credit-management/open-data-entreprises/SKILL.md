---
name: open-data-entreprises
description: Récupérer des données d'entreprises françaises via les sources open data gratuites (BODACC, Sirene INSEE, Annuaire des entreprises, RNE INPI, data.gouv.fr) pour l'analyse crédit et le recouvrement TPE/PME.
version: 1.0
---

# Skill : Récupération de données via l'Open Data français

## Contexte

Plusieurs sources open data françaises fournissent gratuitement des données sur les entreprises. Contrairement à l'API Pappers (payante au-delà du quota gratuit), ces sources sont entièrement gratuites mais nécessitent parfois une authentification ou sont limitées en volume/refresh.

## Sources disponibles

| Source | URL | Auth | Coût | Données |
|--------|-----|------|------|---------|
| BODACC (OpenDataSoft/DILA) | `bodacc-datadila.opendatasoft.com` | Aucune | Gratuit | Annonces commerciales |
| Base Sirene (INSEE) | `api.insee.fr` | OAuth2 | Gratuit | Données d'identification |
| Annuaire des entreprises | `annuaire-entreprises.data.gouv.fr` | Aucune | Gratuit | Fiche entreprise enrichie |
| RNE (INPI) | `registre-national-entreprises.inpi.fr` | Token | Gratuit | Registre national |
| data.gouv.fr (catalogue) | `www.data.gouv.fr/api/1` | Aucune | Gratuit | Métadonnées datasets |
| BODACC (fichiers bulk DILA) | `echanges.dila.gouv.fr/OPENDATA/BODACC/` | Aucune | Gratuit | Fichiers XML/PDF |
| Base Sirene (bulk data.gouv.fr) | `static.data.gouv.fr` | Aucune | Gratuit | Fichiers CSV/Parquet |

---

## Source 1 : BODACC via OpenDataSoft (sans authentification)

### Description

Le BODACC (Bulletin Officiel des Annonces Civiles et Commerciales) publie les annonces légales des entreprises : créations, modifications, radiations, dépôts de comptes, procédures collectives, ventes/cessions.

**API** : `https://bodacc-datadila.opendatasoft.com/api/v2/catalog/datasets/annonces-commerciales/records`

**Authentification** : aucune nécessaire

**Format** : JSON

### Endpoint principal : Recherche d'annonces

```
GET https://bodacc-datadila.opendatasoft.com/api/v2/catalog/datasets/annonces-commerciales/records
```

**Paramètres** :
- `where` (string) — Filtre ODSQL (ex: `registre = "752461681"`, `familleavis_lib = "Procédures collectives"`)
- `limit` (int) — Nombre de résultats (défaut: 10, max: 100)
- `offset` (int) — Pagination
- `select` (string) — Champs à retourner (séparés par virgules)
- `order_by` (string) — Tri (ex: `dateparution desc`)

**Champs disponibles** :

| Champ | Type | Description |
|-------|------|-------------|
| `id` | string | Identifiant unique de l'annonce |
| `dateparution` | string | Date de parution (YYYY-MM-DD) |
| `familleavis` | string | Code famille (dpc, mod, cre, rad, pro, ven, imm, div) |
| `familleavis_lib` | string | Libellé famille (Dépôts des comptes, Modifications diverses, Créations, Radiations, Procédures collectives, Ventes et cessions, Immatriculations, Annonces diverses) |
| `typeavis` | string | Type (annonce, rectificatif, annulation) |
| `typeavis_lib` | string | Libellé type |
| `commercant` | string | Nom du commerçant/entreprise |
| `ville` | string | Ville |
| `cp` | string | Code postal |
| `registre` | array | Numéro(s) de registre (SIREN) |
| `tribunal` | string | Greffe du tribunal |
| `numerodepartement` | string | Numéro de département |
| `departement_nom_officiel` | string | Nom du département |
| `region_code` | int | Code région |
| `region_nom_officiel` | string | Nom de la région |
| `parution` | string | Numéro de parution |
| `numeroannonce` | int | Numéro de l'annonce |
| `listepersonnes` | string (JSON) | Détail des personnes mentionnées (JSON embarqué) |
| `pdf_parution_subfolder` | int | Sous-dossier PDF |
| `ispdf_unitaire` | string | PDF unitaire disponible (oui/non) |

### Commandes utiles

```bash
# Rechercher les annonces BODACC d'une entreprise par SIREN
curl -s "https://bodacc-datadila.opendatasoft.com/api/v2/catalog/datasets/annonces-commerciales/records?where=registre%20%3D%20%22SIREN%22&limit=50&order_by=dateparution%20desc"

# Rechercher les procédures collectives dans un département
curl -s "https://bodacc-datadila.opendatasoft.com/api/v2/catalog/datasets/annonces-commerciales/records?where=familleavis_lib%20%3D%20%22Proc%C3%A9dures%20collectives%22%20AND%20numerodepartement%20%3D%20%2275%22&limit=50&order_by=dateparution%20desc"

# Rechercher les dépôts de comptes récents d'une entreprise
curl -s "https://bodacc-datadila.opendatasoft.com/api/v2/catalog/datasets/annonces-commerciales/records?where=registre%20%3D%20%22SIREN%22%20AND%20familleavis%20%3D%20%22dpc%22&limit=10&order_by=dateparution%20desc"
```

### Structure de la réponse

```json
{
  "total_count": 14,
  "records": [
    {
      "links": [...],
      "record": {
        "id": "abc123...",
        "timestamp": "2025-01-27T06:03:00Z",
        "size": 1140,
        "fields": {
          "id": "C202500182618",
          "dateparution": "2025-01-26",
          "familleavis_lib": "Dépôts des comptes",
          "commercant": "Le Fournil des Bocages",
          "ville": "Thiescourt",
          "registre": ["752 461 681", "752461681"]
        }
      }
    }
  ]
}
```

⚠️ **Important** : Les champs sont dans `record.fields` et non `fields` directement au niveau du record.

### Familles de BODACC pour le credit management

| Code | Libellé | Implication crédit |
|------|---------|-------------------|
| `dpc` | Dépôts des comptes | 🟢 Nouveaux comptes publiés — analyser |
| `mod` | Modifications diverses | 🟠 Changement (dirigeant, capital, adresse) |
| `cre` | Créations | 🟢 Nouvelle entreprise |
| `rad` | Radiations | 🔴 Radiation RCS |
| `pro` | Procédures collectives | 🔴 Procédure collective — déclaration créance |
| `ven` | Ventes et cessions | 🟡 Changement de contrôle |
| `imm` | Immatriculations | 🟢 Immatriculation RCS |
| `div` | Annonces diverses | ℹ️ À examiner |

---

## Source 2 : Base Sirene INSEE (OAuth2)

### Description

L'INSEE propose un accès API à la base Sirene (données d'identification des entreprises et établissements).

**API** : `https://api.insee.fr/entreprises/sirene/V3`

**Authentification** : OAuth2 (client credentials)

### Prérequis

1. Créer un compte sur https://api.insee.fr
2. Créer une application
3. Récupérer `consumer_key` et `consumer_secret`

### Obtenir un token

```bash
# Générer un token OAuth2 (valide 7 jours par défaut)
curl -s -X POST "https://api.insee.fr/token" \
  -H "Authorization: Basic $(echo -n 'consumer_key:consumer_secret' | base64)" \
  -d "grant_type=client_credentials"

# Réponse :
# {"access_token":"xxxxx","token_type":"Bearer","expires_in":604800}
```

### Endpoints

#### Fiche unité légale (entreprise)

```
GET https://api.insee.fr/entreprises/sirene/V3/siren/{siren}
```

**Paramètres** :
- `siren` (path) — SIREN (9 chiffres)
- `masquerValeursNulles` (query, bool) — masquer les valeurs nulles
- `date` (query) — date d'effet souhaitée (YYYY-MM-DD)
- `facultatif` (query, bool) — inclure les champs facultatifs

**Commande** :

```bash
curl -s "https://api.insee.fr/entreprises/sirene/V3/siren/552083299" \
  -H "Authorization: Bearer $INSEE_TOKEN" \
  -H "Accept: application/json"
```

#### Fiche établissement

```
GET https://api.insee.fr/entreprises/sirene/V3/siret/{siret}
```

#### Recherche (liens de navigation)

```
GET https://api.insee.fr/entreprises/sirene/V3/siren?q=...
```

### Champs clés de la réponse Sirene

**Unité légale** (`uniteLegale`) :
- `siren`, `denominationUniteLegale`, `nomUniteLegale`, `prenomUniteLegale`
- `categorieJuridiqueUniteLegale` (code Insee)
- `activitePrincipaleUniteLegale` (code NAF)
- `economieSocialeSolidaireUniteLegale`
- `statutDiffusionUniteLegale`
- `nicSiegeUniteLegale`
- `categorieEntreprise` (TPE, PME, ETI, GE)
- `trancheEffectifsUniteLegale`

**Établissement** (`etablissement`) :
- `siret`, `adresseEtablissement`, `codePostalEtablissement`
- `libelleCommuneEtablissement`, `etatAdministratifEtablissement`

---

## Source 3 : Annuaire des entreprises

### Description

Portail gouvernemental qui agrège plusieurs sources (Sirene, RNCS, INPI, ACOSS...). API gratuite sans authentification.

**URL** : `https://annuaire-entreprises.data.gouv.fr`

⚠️ Le site est protégé par Incapsula/WAF qui peut bloquer les requêtes curl. L'API peut nécessiter un User-Agent de navigateur ou être inaccessible depuis certains environnements.

### Endpoints connus

```bash
# Fiche entreprise par SIREN
curl -s "https://annuaire-entreprises.data.gouv.fr/api/entreprise/{siren}"

# Recherche
curl -s "https://annuaire-entreprises.data.gouv.fr/recherche?terme={terme}"

# Dirigeants
curl -s "https://annuaire-entreprises.data.gouv.fr/dirigeants/{siren}"

# Bénéficiaires effectifs
curl -s "https://annuaire-entreprises.data.gouv.fr/beneficiaires/{siren}"

# Conventions collectives
curl -s "https://annuaire-entreprises.data.gouv.fr/api/conventions/{siren}"

# Certificats (Kbis, etc.)
curl -s "https://annuaire-entreprises.data.gouv.fr/certificat/{siren}"
```

---

## Source 4 : Registre National des Entreprises (RNE) - INPI

### Description

L'INPI gère le RNE, qui a remplacé le registre du tribunal de commerce. Données d'immatriculation, dirigeants, actes, comptes.

**API** : `https://registre-national-entreprises.inpi.fr/api`

**Authentification** : Token (créer un compte sur https://data.inpi.fr)

### Endpoints principaux

```bash
# Récupérer une entreprise
curl -s "https://registre-national-entreprises.inpi.fr/api/companies/{siren}" \
  -H "Authorization: Bearer $INPI_TOKEN"

# Rechercher des entreprises
curl -s "https://registre-national-entreprises.inpi.fr/api/companies?q={terme}" \
  -H "Authorization: Bearer $INPI_TOKEN"
```

---

## Source 5 : data.gouv.fr (catalogue API)

### Description

API de catalogue des datasets disponibles sur data.gouv.fr. Utile pour trouver des datasets spécifiques.

**API** : `https://www.data.gouv.fr/api/1`

**Authentification** : aucune

### Endpoints

```bash
# Rechercher des datasets
curl -s "https://www.data.gouv.fr/api/1/datasets/?q=sirene&pageSize=10"

# Détails d'un dataset
curl -s "https://www.data.gouv.fr/api/1/datasets/{slug}/"

# Lister les ressources d'un dataset
curl -s "https://www.data.gouv.fr/api/1/datasets/{slug}/resources/"
```

---

## Source 6 : Base Sirene en téléchargement bulk

### Description

Fichiers complets de la base Sirene, téléchargeables gratuitement sur data.gouv.fr. Mis à jour mensuellement (ou quotidiennement pour les fichiers journaliers).

**URL** : `https://static.data.gouv.fr/resources/base-sirene-des-entreprises-et-de-leurs-etablissements-siren-siret/`

### Fichiers disponibles

| Fichier | Format | Description | Taille |
|---------|--------|-------------|--------|
| StockUniteLegale | CSV/Parquet | Toutes les entreprises (SIREN) | ~1.5 Go |
| StockEtablissement | CSV/Parquet | Tous les établissements (SIRET) | ~5 Go |
| StockEtablissementHistorique | CSV/Parquet | Historique des établissements | ~2 Go |
| FluxUniteLegale | CSV | Modifications journalières | Variable |
| FluxEtablissement | CSV | Modifications journalières | Variable |

### Usage

Ces fichiers bulk sont utiles pour :
- Construire une base locale d'entreprises
- Analyser un secteur complet
- Enrichir un portefeuille clients avec données INSEE
- Ne convient PAS pour une consultation unitaire (utiliser l'API INSEE ou Pappers)

---

## Workflows Credit Management avec l'Open Data

### Workflow A : Vérification BODACC d'un débiteur (gratuit, sans auth)

```bash
# 1. Récupérer toutes les annonces BODACC d'une entreprise par SIREN
curl -s "https://bodacc-datadila.opendatasoft.com/api/v2/catalog/datasets/annonces-commerciales/records?where=registre%20%3D%20%22SIREN%22&limit=100&order_by=dateparution%20desc"

# 2. Filtrer sur les procédures collectives
curl -s "https://bodacc-datadila.opendatasoft.com/api/v2/catalog/datasets/annonces-commerciales/records?where=registre%20%3D%20%22SIREN%22%20AND%20familleavis%20%3D%20%22pro%22&limit=50&order_by=dateparution%20desc"

# 3. Vérifier les dépôts de comptes récents
curl -s "https://bodacc-datadila.opendatasoft.com/api/v2/catalog/datasets/annonces-commerciales/records?where=registre%20%3D%20%22SIREN%22%20AND%20familleavis%20%3D%20%22dpc%22&limit=10&order_by=dateparution%20desc"
```

### Workflow B : Identification d'une entreprise (gratuit)

```bash
# 1. Si on a un nom mais pas de SIREN : recherche BODACC par nom
curl -s "https://bodacc-datadila.opendatasoft.com/api/v2/catalog/datasets/annonces-commerciales/records?where=commercant%20like%20%22NOM_ENTREPRISE%22&limit=10&order_by=dateparution%20desc"

# 2. Une fois le SIREN identifié, récupérer les données INSEE
curl -s "https://api.insee.fr/entreprises/sirene/V3/siren/SIREN" \
  -H "Authorization: Bearer $INSEE_TOKEN"

# 3. Vérifier les BODACC récents pour signaux d'alerte
curl -s "https://bodacc-datadila.opendatasoft.com/api/v2/catalog/datasets/annonces-commerciales/records?where=registre%20%3D%20%22SIREN%22&limit=20&order_by=dateparution%20desc"
```

### Workflow C : Veille BODACC sectorielle (gratuit)

```bash
# Surveiller les procédures collectives dans un département
curl -s "https://bodacc-datadila.opendatasoft.com/api/v2/catalog/datasets/annonces-commerciales/records?where=familleavis%20%3D%20%22pro%22%20AND%20numerodepartement%20%3D%20%2275%22&limit=100&order_by=dateparution%20desc"

# Surveiller les radiations dans un secteur (par code NAF non disponible directement, 
# mais on peut filtrer par département et examiner les résultats)
```

---

## Script utilitaire : veille BODACC par SIREN

Le script `scripts/veille_bodacc.py` (voir fichier lié) automatise la récupération et le formatage des annonces BODACC d'une entreprise.

---

## Complémentarité Pappers vs Open Data

| Critère | Pappers (API payante) | Open Data (gratuit) |
|---------|----------------------|---------------------|
| Coût | Payant au-delà du quota | Gratuit |
| Couverture | Très large (toutes sources agrégées) | Fragmenté (plusieurs APIs) |
| Qualité données | Enrichies et nettoyées | Brutes (parfois incomplètes) |
| Scoring | Inclus (payant) | Non disponible |
| BODACC | Inclus | Disponible via OpenDataSoft |
| Sirene | Inclus | Disponible via INSEE |
| Dirigeants/BE | Inclus | Disponible via INPI/Annuaire |
| Comptes annuels | Inclus | Partiel (BODACC signale le dépôt) |
| Mise à jour | Temps réel | Variable (J+1 à J+7) |
| Rate limiting | Selon plan | Généreux |
| Setup | 1 clé API | Plusieurs clés/tokens |

**Stratégie recommandée** : Utiliser l'open data en priorité pour le screening de masse et la veille. Compléter avec Pappers pour les analyses approfondies nécessitant scoring et données financières détaillées.

---

## Pièges et points d'attention

1. **BODACC : champ `registre` est un array** — Le SIREN peut être stocké sous différents formats (`"752461681"` ou `"752 461 681"`). La recherche ODS `registre = "752461681"` matche les deux formats.

2. **BODACC : structure de réponse** — Les champs sont dans `record.fields` et non `fields` directement. Ne pas confondre.

3. **INSEE : token OAuth2** — Le token expire (7 jours par défaut). Il faut le rafraîchir régulièrement. Le stocker dans `$INSEE_TOKEN`.

4. **Annuaire des entreprises : WAF** — Le site peut bloquer les requêtes automatisées. Utiliser un User-Agent de navigateur ou passer par les APIs alternatives.

5. **INPI RNE : authentification** — Nécessite un compte INPI. L'API peut avoir des limites de taux.

6. **BODACC : pas de données financières** — Le BODACC signale le dépôt de comptes mais ne contient pas les chiffres. Pour les chiffres, utiliser Pappers ou les comptes annuels de l'INPI.

7. **Base Sirene bulk : volumétrie** — Les fichiers font plusieurs Go. Ne pas télécharger pour une consultation unitaire. Utiliser l'API INSEE pour les requêtes unitaires.

8. **Délais de mise à jour** :
   - BODACC OpenDataSoft : J+1 à J+2
   - Sirene INSEE : J+1 (flux quotidien)
   - Annuaire des entreprises : variable selon source
   - RNE INPI : J+1 à J+7

9. **OpenDataSoft : langue des filtres** — Les valeurs textuelles sont en français avec accents. Bien encoder les URLs (ex: `Proc%C3%A9dures%20collectives`).

10. **Recherche BODACC par nom** — Le champ `commercant` peut contenir des variantes. Utiliser l'opérateur `like` pour une recherche floue : `commercant like "NOM"`.

## Vérification du fonctionnement

```bash
# Test BODACC (doit retourner un JSON avec total_count > 0)
curl -s "https://bodacc-datadila.opendatasoft.com/api/v2/catalog/datasets/annonces-commerciales/records?limit=1" | python3 -m json.tool | head -20

# Test data.gouv.fr
curl -s "https://www.data.gouv.fr/api/1/datasets/?q=bodacc&pageSize=1" | python3 -m json.tool | head -20

# Test INSEE (nécessite un token valide)
curl -s "https://api.insee.fr/entreprises/sirene/V3/siren/552083299" \
  -H "Authorization: Bearer $INSEE_TOKEN" | python3 -m json.tool | head -20
```

## Liens utiles

- BODACC OpenDataSoft : https://bodacc-datadila.opendatasoft.com
- API INSEE Sirene : https://api.insee.fr/catalog/site/portail/swagger
- Annuaire des entreprises : https://annuaire-entreprises.data.gouv.fr
- RNE INPI : https://data.inpi.fr
- data.gouv.fr : https://www.data.gouv.fr
- Documentation OpenDataSoft (ODSQL) : https://help.opendatasoft.com/apis/ods-search/
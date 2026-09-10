---
name: pappers-api
description: Récupérer et analyser des données d'entreprises françaises via l'API Pappers (société, dirigeants, comptes annuels, procédures collectives, scoring) pour l'analyse crédit et le recouvrement TPE/PME.
version: 1.0
---

# Skill : Récupération de données via l'API Pappers

## Contexte

Pappers (https://www.pappers.fr) est une plateforme d'informations légales et financières sur les entreprises françaises. Son API REST permet de récupérer des données structurées (JSON) pour l'analyse crédit et le recouvrement.

## Prérequis

### 1. Obtenir une clé API

- Créer un compte sur https://www.pappers.fr
- Souscrire à un plan API (gratuit limité, puis payant selon volume)
- Récupérer le **API token** depuis le tableau de bord

### 2. Stocker la clé

Stocker la clé dans une variable d'environnement :

```bash
export PAPPERS_API_TOKEN="votre_cle_api_ici"
```

⚠️ Ne jamais commit la clé dans un fichier. Toujours utiliser la variable d'environnement `$PAPPERS_API_TOKEN`.

## Architecture de l'API

- **Base URL** : `https://api.pappers.fr/v2`
- **Authentification** : paramètre `api_token` en query string OU header `api-key`
- **Format** : JSON (requêtes et réponses)
- **Méthode** : GET pour la consultation, POST pour la surveillance/listes
- **Codes de retour** : 200 (succès), 206 (succès partiel), 400 (bad request), 401 (non autorisé), 404 (introuvable)

### Coûts en crédits

Chaque appel consomme des crédits selon le plan souscrit. Attention aux champs supplémentaires qui peuvent être coûteux :

| Champ supplémentaire | Coût |
|---------------------|------|
| `sites_internet` | +1 crédit |
| `telephone` | +3 crédits |
| `email` | +3 crédits |
| `lien_linkedin` | +3 crédits |
| `sanctions` | +1 crédit |
| `personne_politiquement_exposee` | +1 crédit |
| `scoring_financier` | +30 crédits |
| `scoring_non_financier` | +30 crédits |
| `decisions` | +5 crédits |
| `finances_estimations` | +5 crédits |
| `entreprises_dirigees` | +1 crédit |
| `observations` | +0.5 crédit |
| `representants_legaux` | gratuit |
| `micro_entreprise` | gratuit |
| `categorie_entreprise` | gratuit |

## Endpoints pour le Credit Management

### 1. Fiche entreprise — `GET /entreprise`

**Le plus utilisé** : récupère toutes les informations d'une entreprise à partir de son SIREN ou SIRET.

**Paramètres** :
- `siren` (string) — SIREN de l'entreprise (9 chiffres)
- `siret` (string) — SIRET de l'établissement (14 chiffres)
- `format_publications_bodacc` (string) — `"objet"` (défaut) ou `"texte"`
- `validite_tva_intracommunautaire` (bool) — vérifie la validité du n° TVA
- `publications_bodacc_brutes` (bool) — inclut les BODACC non traités
- `beneficiaires_effectifs_complets` (bool) — accès complet au registre (nécessite habilitation)
- `champs_supplementaires` (string) — liste séparée par virgules (voir tableau ci-dessus)

**Données retournées** : nom, forme juridique, capital, adresse, dirigeants, bénéficiaires effectifs, établissements, publications BODACC, procédures collectives, comptes (si publiés), statut RCS, code NAF, date de création, etc.

**Commande** :

```bash
# Exemple : fiche complète d'une entreprise avec scoring
curl -s "https://api.pappers.fr/v2/entreprise?api_token=$PAPPERS_API_TOKEN&siren=552083299&champs_supplementaires=representants_legaux,scoring_financier,categorie_entreprise,entreprises_dirigees"
```

### 2. Recherche d'entreprises — `GET /recherche`

Recherche multi-critères d'entreprises. Idéale pour identifier un débiteur, vérifier des filiales, ou scanner un secteur.

**Paramètres principaux** :
- `q` (string) — texte à rechercher (dénomination ou nom dirigeant)
- `page`, `par_page` — pagination (max 400 résultats)
- `curseur`, `par_curseur` — curseur pour >400 résultats (`curseur=*` pour démarrer, `par_curseur` max 1000)
- `bases` (string) — `"entreprises"` (défaut), `"dirigeants"`, `"beneficiaires"`
- `precision` (string) — `"standard"` (défaut) ou `"exacte"`
- `code_naf`, `departement`, `region`, `code_postal` — filtres géographiques/sectoriels
- `categorie_juridique` (string) — ex: 5720 pour SASU, 5498 pour EURL
- `entreprise_cessee` (bool) — filtrer sur activité cessée
- `statut_rcs` (string) — statut au RCS
- `capital_min`, `capital_max` — filtres capital
- `chiffre_affaires_min`, `chiffre_affaires_max` — filtres CA
- `resultat_min`, `resultat_max` — filtres résultat
- `date_creation_min`, `date_creation_max` — dates au format JJ-MM-AAAA
- `tranche_effectif_min`, `tranche_effectif_max` — selon nomenclature Sirene
- `nom_dirigeant`, `prenom_dirigeant`, `type_dirigeant`, `qualite_dirigeant`
- `age_beneficiaire_min`, `age_beneficiaire_max`

**Commande** :

```bash
# Recherche par nom dans un département
curl -s "https://api.pappers.fr/v2/recherche?api_token=$PAPPERS_API_TOKEN&q=durand+btp&departement=75&par_page=20"
```

### 3. Comptes annuels — `GET /entreprise/comptes`

Récupère les comptes annuels détaillés d'une entreprise (liasse fiscale).

**Paramètres** :
- `siren` (string, requis) — SIREN de l'entreprise
- `annee` (int) — année des comptes (si omis, tous les exercices disponibles)

**Commande** :

```bash
# Comptes de l'exercice 2023
curl -s "https://api.pappers.fr/v2/entreprise/comptes?api_token=$PAPPERS_API_TOKEN&siren=552083299&annee=2023"
```

### 4. Conformité personne physique — `GET /conformite/personne_physique`

Vérifie la conformité d'une personne physique (dirigeant, bénéficiaire effectif) contre listes de sanctions et PPE.

**Paramètres** :
- `nom` (string, requis) — nom de la personne
- `prenom` (string, requis) — prénom
- `date_de_naissance` (string) — JJ-MM-AAAA

**Commande** :

```bash
curl -s "https://api.pappers.fr/v2/conformite/personne_physique?api_token=$PAPPERS_API_TOKEN&nom=Durand&prenom=Jean&date_de_naissance=01-01-1970"
```

### 5. Recherche de bénéficiaires effectifs — `GET /recherche-beneficiaires`

Recherche de bénéficiaires effectifs dans la base Pappers.

**Commande** :

```bash
curl -s "https://api.pappers.fr/v2/recherche-beneficiaires?api_token=$PAPPERS_API_TOKEN&q=jean+durand"
```

### 6. Recherche de dirigeants — `GET /recherche-dirigeants`

Recherche de dirigeants d'entreprises.

**Commande** :

```bash
curl -s "https://api.pappers.fr/v2/recherche-dirigeants?api_token=$PAPPERS_API_TOKEN&q=jean+durand"
```

### 7. Suivi des jetons (consommation) — `GET /suivi-jetons`

Permet de suivre la consommation de crédits API.

**Commande** :

```bash
curl -s "https://api.pappers.fr/v2/suivi-jetons?api_token=$PAPPERS_API_TOKEN"
```

### 8. Documents téléchargeables

Plusieurs endpoints permettent de récupérer des documents officiels :

| Endpoint | URL | Description |
|----------|-----|-------------|
| Extrait Pappers | `GET /document/extrait_pappers` | Fiche synthèse entreprise |
| Statuts documents | `GET /document/statuts` | Statut des documents disponibles |
| Téléchargement | `GET /document/telechargement` | Téléchargement document (acte, statuts, comptes) |
| Scoring financier | `GET /document/rapport_financier` | Rapport de scoring financier |
| Scoring non-financier | `GET /document/rapport_non_financier` | Rapport de scoring non-financier |
| Avis situation Insee | `GET /document/avis_situation_insee` | Avis de situation Insee |
| Bénéficiaires effectifs | `GET /document/beneficiaires_effectifs` | Document BE |
| Extrait INPI | `GET /document/extrait_inpi` | Extrait Kbis INPI |

### 9. Surveillance / Veille — `POST /liste` et `POST /liste-informations`

Permet de créer des listes de surveillance d'entreprises pour être notifié des changements (dépot de comptes, procédure collective, changement de dirigeant, etc.).

**Paramètres SurveillanceEntreprise** :
- `id_liste` — identifiant de la liste
- + body JSON avec liste d'entreprises à surveiller

### 10. Suggestions — `GET /suggestions`

Autocomplétion pour recherche d'entreprises.

**Commande** :

```bash
curl -s "https://api.pappers.fr/v2/suggestions?api_token=$PAPPERS_API_TOKEN&q=app"
```

## Workflows Credit Management avec Pappers

### Workflow A : Analyse de solvabilité d'un prospect/client

```bash
# 1. Identifier l'entreprise par nom ou SIREN
curl -s "https://api.pappers.fr/v2/suggestions?api_token=$PAPPERS_API_TOKEN&q=NOM_ENTREPRISE"

# 2. Récupérer la fiche complète avec scoring
curl -s "https://api.pappers.fr/v2/entreprise?api_token=$PAPPERS_API_TOKEN&siren=SIREN&champs_supplementaires=representants_legaux,scoring_financier,categorie_entreprise,entreprises_dirigees,sanctions,deces"

# 3. Récupérer les comptes annuels détaillés
curl -s "https://api.pappers.fr/v2/entreprise/comptes?api_token=$PAPPERS_API_TOKEN&siren=SIREN"

# 4. (Optionnel) Vérifier la conformité du dirigeant
curl -s "https://api.pappers.fr/v2/conformite/personne_physique?api_token=$PAPPERS_API_TOKEN&nom=NOM&prenom=PRENOM&date_de_naissance=DD-MM-YYYY"
```

### Workflow B : Vérification avant recouvrement contentieux

```bash
# 1. Vérifier le statut de l'entreprise (procédure collective ?)
curl -s "https://api.pappers.fr/v2/entreprise?api_token=$PAPPERS_API_TOKEN&siren=SIREN"

# 2. Vérifier les BODACC récents pour dépôt de comptes / procédures
# → Analyser le champ "publications_bodacc" dans la réponse
# → Chercher type "procedure_collective", "depot_des_comptes"

# 3. Si procédure collective : vérifier les délais de déclaration de créance
```

### Workflow C : Veille sur portefeuille clients

```bash
# 1. Créer une liste de surveillance
curl -s -X POST "https://api.pappers.fr/v2/liste?api_token=$PAPPERS_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"siren": ["SIREN1", "SIREN2", "SIREN3"]}'

# 2. Surveiller les notifications
curl -s "https://api.pappers.fr/v2/liste-informations?api_token=$PAPPERS_API_TOKEN&id_liste=ID_LISTE"
```

## Interprétation des données pour le Credit Management

### Champs-clés de la réponse `/entreprise` pour analyse crédit

| Champ | Signification | Usage credit management |
|-------|---------------|-------------------------|
| `statut_rcs` | "Inscrit" / "Radié" | Radié = risque critique |
| `entreprise_cessee` | true/false | Cessation = bloquer encours |
| `procedures_collectives` | tableau | Procédure en cours = action urgente |
| `publications_bodacc` | tableau | BODACC récents = signaux |
| `dirigeants` | tableau | Identité et mandats des dirigeants |
| `beneficiaires_effectifs` | tableau | UBIO et structure de contrôle |
| `comptes` | tableau | Bilan et résultat pour ratios |
| `capital_social` | montant | Solidité financière de base |
| `forme_juridique` | string | SARL, SAS, SA, etc. |
| `date_creation` | timestamp | Ancienneté = stabilité |
| `code_naf` / `nomenclature_code_naf` | string | Secteur d'activité |
| `effectif` | string | Taille (tranches) |
| `domain` | string | Site internet |

### Types de BODACC à surveiller

| Type BODACC | Implication crédit |
|-------------|-------------------|
| `procedure_collective` | 🔴 Procédure collective ouverte — vérifier déclaration créance |
| `depot_des_comptes` | 🟢 Nouveaux comptes disponibles — analyse annuelle |
| `modification` | 🟠 Changement de dirigeant/capital — réévaluer le risque |
| `radiation` | 🔴 Radiation RCS — arrêt encours |
| `vente` / `achat` | 🟡 Changement de contrôle — réévaluation |
| `creation` / `immatriculation` | 🟢 Nouvelle entreprise |

### Scoring financier Pappers

Le scoring financier (champ `scoring_financier`, +30 crédits) fournit une note de risque financier. À utiliser pour les encours significatifs.

Le scoring non-financier (champ `scoring_non_financier`, +30 crédits) évalue le risque lié à des critères non-financiers (signaux légaux, juridiques, comportementaux).

## Script utilitaire : fiche crédit complète

Le script `scripts/fiche_credit.py` (voir fichier lié) automatise la récupération et le formatage d'une fiche crédit complète à partir d'un SIREN.

## Pièges et points d'attention

1. **Coûts en crédits** : les champs `scoring_financier` et `scoring_non_financier` coûtent 30 crédits chacun. Les utiliser avec parcimonie, pas pour du screening de masse.
2. **Diffusion partielle** : certaines entreprises sont en `diffusable=false` — les champs nominatifs seront alors null.
3. **Comptes non publiés** : les TPE/micro-entreprises ne publient pas toujours leurs comptes. Ne pas se fier uniquement aux données financières.
4. **Délai de mise à jour** : les données BODACC peuvent avoir un délai de quelques jours par rapport au registre officiel.
5. **Bénéficiaires effectifs** : depuis 2024, le registre des BE est géré par l'INPI. Les données peuvent être incomplètes pour les entreprises n'ayant pas encore déposé leur déclaration.
6. **Rate limiting** : l'API a des limites de taux selon le plan souscrit. En cas d'erreur 429, espacer les requêtes.
7. **TVA intracommunautaire** : utiliser `validite_tva_intracommunautaire=true` pour vérifier la validité du numéro de TVA auprès de la Commission européenne (utile pour facturation intra-UE).
8. **Format dates** : les dates dans les paramètres de recherche sont au format `JJ-MM-AAAA`, mais les dates dans les réponses sont au format timestamp Unix ou ISO.

## Vérification du fonctionnement

Tester la connexion API :

```bash
# Test simple — doit retourner un JSON valide (pas d'erreur 401)
curl -s "https://api.pappers.fr/v2/suivi-jetons?api_token=$PAPPERS_API_TOKEN"
```

Réponse attendue :

```json
{
  "jetons_restants": 1234,
  "jetons_consommes": 567,
  "date_reapprovisionnement": "2024-12-01"
}
```

## Liens utiles

- Documentation officielle : https://www.pappers.fr/api/documentation
- Tableau de bord API : https://www.pappers.fr/mon-compte/api
- Statut de l'API : https://www.pappers.fr/api
- Wrapper PHP : https://github.com/qdequippe-tech/pappers-php-api
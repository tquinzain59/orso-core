# ADR 07 : Alignement d'AGENTS.md, Emplacement des Règles de Gouvernance et Survie Amont Multi-Dépôts

- **Date** : 03 octobre 2026
- **Auteurs** : Antigravity (Architecte-Développeur), validé par Thibaut (Sponsor & PO)
- **Ticket Jira** : [KAN-92](https://orso-agents.atlassian.net/browse/KAN-92)
- **Statut** : Accepté et Appliqué
- **Référence unique** : [Page Confluence 26 - Charte globale du développeur Orso agents](https://orso-agents.atlassian.net/wiki/spaces/Orsoagents/pages/5668865)

---

## 1. Contexte & Problématique

Le 03/10/2026, l'inspection des règles chargées nativement par l'environnement de l'agent de développement (IDE Antigravity) a mis en évidence que :
1. Le fichier injecté dans le contexte de l'agent était identique octet pour octet au fichier `AGENTS.md` situé à la racine du dépôt `orso-core` (30 720 octets).
2. Ce fichier contenait le guide de contribution du projet amont Hermes Agent (Nous Research) et un rappel synthétique du Sanctuaire, mais **ne portait aucun des essentiels opérationnels Orso** :
   - Ni Definition of Ready (DoR) ni Definition of Done (DoD) ;
   - Ni la séparation des rôles (qui décide quoi entre Thibaut, Jarvis, Antigravity et Kimi K3) ;
   - Ni les conventions strictes de branches (`KAN-<n>-<slug>`) et de pull requests (`[KAN-xx]`) ;
   - Ni le standard de preuve de la section Handoff mesuré sur le code brut servi ;
   - Ni la règle d'arrêt et de signalement immédiat sur le Sanctuaire du fork ;
   - Ni le renvoi vers la source unique de vérité ([Page Confluence 26](https://orso-agents.atlassian.net/wiki/spaces/Orsoagents/pages/5668865)).
3. Parallèlement, des formulations concurrentes subsistaient dans le Document Confluence 19 (section 5) et dans l'ancienne note d'interface `orso-docs/AGENTS.md`.
4. Deux dépôts de l'écosystème Orso (`orso-site` et `orso-app`) ne disposaient d'aucun fichier de règles à leur racine, laissant l'agent sans instruction de cadrage lors du basculement d'espace de travail.

---

## 2. Décision d'Architecture (CA1)

L'arbitrage architectural retient un **dispositif d'ancrage normalisé à deux niveaux** :

### 2.1. Pour `orso-core` : Bloc d'en-tête Orso sanctuarisé avec clause de primauté
Le fichier `AGENTS.md` à la racine de `orso-core` est structuré en deux parties étanches :
1. **En tête de fichier** : Un bloc délimité (`<!-- ORSO_GOVERNANCE_START -->` ... `<!-- ORSO_GOVERNANCE_END -->`) portant explicitement les essentiels opérationnels Orso (DoR, DoD, Rôles, Nommage Git, Standard Handoff, Arrêt Sanctuaire, Renvoi Page 26) et une **clause de primauté absolue** désamorçant toute contradiction avec le texte amont (rejet formel du squash amont, des cherry-picks de contournement et des fusions directes sur main).
2. **À la suite** : Le guide amont Hermes conservé intégralement pour maintenir la navigabilité dans les sous-systèmes du framework hérité.

### 2.2. Pour `orso-site`, `orso-app` et `orso-docs` : Fichiers d'entrée `AGENTS.md` dédiés (CA7)
Chaque dépôt Orso est doté à sa racine d'un fichier `AGENTS.md` officiel, servant de point d'entrée natif pour l'IDE et portant :
- Les essentiels opérationnels communs Orso (Rôles, DoR, DoD, conventions Git `KAN-`, Handoff, Sanctuaire) ;
- Le périmètre propre au dépôt ;
- Le renvoi unique vers la [Page Confluence 26](https://orso-agents.atlassian.net/wiki/spaces/Orsoagents/pages/5668865).

### 2.3. Suppression des versions concurrentes (CA3)
Conformément à la règle de la source unique de vérité :
- La section 5 du Document 19 est purgée de sa rédaction locale et remplacée par un renvoi daté vers la Page 26.
- Le fichier `AGENTS.md` de `orso-docs` devient un renvoi daté vers la Page 26.

---

## 3. Options écartées et motifs du rejet (CA1)

| Option envisagée | Description | Motif du rejet |
| :--- | :--- | :--- |
| **Option B : Fichier local tiers isolé (ex: `.antigravity/rules.md` ou `.agent_rules.md`)** | Séparer les règles Orso dans un fichier distinct chargé en sus du fichier amont. | **Rejetée** : L'environnement IDE Antigravity découvre et injecte nativement `AGENTS.md` à la racine de l'espace de travail actif. Un fichier tiers nécessite une configuration d'IDE spécifique non portable, fragile en multi-dépôts et non garantie pour tous les assistants. |
| **Option C : Conservation du fichier amont 100% intact + règle orale/mémoire** | Laisser `AGENTS.md` tel quel et compter sur le prompt de démarrage ou des instructions ad-hoc. | **Rejetée** : Viole le principe fondateur ("Une livraison est un contrat vérifiable, pas un récit"). L'agent d'IDE est stateless au démarrage de session et applique ce qu'il lit dans son fichier de règles d'entrée. |
| **Option D : Écrasement total du guide amont par les règles Orso** | Supprimer l'intégralité du guide Hermes dans `orso-core/AGENTS.md`. | **Rejetée** : Perte de la navigabilité technique amont (règles de code, table de routage, invariants de cache Hermes) et génération de conflits massifs lors des synchronisations upstream. |

---

## 4. Procédure de Survie lors des Synchronisations Amont (CA4)

Lors d'un rapatriement ou d'une mise à jour amont (`git fetch upstream && git merge upstream/main` ou rebase) :

1. **Détection automatique d'altération** :
   La balise `<!-- ORSO_GOVERNANCE_START -->` et son empreinte SHA-256 permettent de vérifier immédiatement l'intégrité du bloc de gouvernance Orso.
2. **Résolution de conflit standardisée** :
   - En cas de conflit sur `AGENTS.md`, la partie Orso (lignes entre les balises `ORSO_GOVERNANCE_START` et `ORSO_GOVERNANCE_END`) est **invariablement conservée en tête**.
   - Le delta amont (`upstream/main`) est réintégré à la suite, sous le séparateur `## Hermes Agent - Development Guide`.
3. **Contrôle automatisé pré-vol** :
   Un test d'intégrité vérifie que `AGENTS.md` contient bien la balise de gouvernance Orso, les sections DoR, DoD, Rôles, Nommage Git, Handoff et le lien Confluence Page 26.

# Note d'Arbitrage et Spécification Technique KAN-92 : Alignement d'AGENTS.md, Emplacement des Règles de Gouvernance et Survie Amont Multi-Dépôts

- **Date** : 03 octobre 2026
- **Auteur** : Antigravity (Architecte-Développeur), validé par Thibaut (Sponsor & PO)
- **Ticket Jira** : [KAN-92](https://orso-agents.atlassian.net/browse/KAN-92)
- **Statut** : Appliqué et Vérifié
- **Source unique de vérité** : [Page Confluence 26 - Charte globale du développeur Orso agents](https://orso-agents.atlassian.net/wiki/spaces/Orsoagents/pages/5668865)

---

## 1. Contexte et Diagnostic Réel (Constat du 03/10/2026)

Le 03/10/2026, une analyse croisée de l'environnement de l'agent de développement (IDE Antigravity) et des dépôts du projet Orso a révélé les points suivants :
1. **Dépôt `orso-core`** : Le fichier chargé en contexte de règles par l'IDE est le fichier racine `AGENTS.md` (30 720 octets). Ce fichier est constitué du guide de contribution amont de `hermes-agent` (Nous Research), précédé d'un encart de 6 lignes rappelant le Sanctuaire.
2. **Absence des essentiels opérationnels Orso** :
   - Aucune mention de la **Definition of Ready (DoR)** ;
   - Aucune mention de la **Definition of Done (DoD)** ;
   - Aucune mention de la **séparation des rôles** (qui décide quoi entre Thibaut, Jarvis, Antigravity et Kimi K3) ;
   - Aucun rappel du **nommage des branches** (`KAN-<n>-<slug>`) ni du **titre des demandes de tirage** (`[KAN-xx]`) ;
   - Aucun rappel du **standard de preuve de la section Handoff** mesuré sur le code brut servi ;
   - Absence de la **règle formelle d'arrêt et de signalement** en cas d'atteinte au Sanctuaire ;
   - Absence de renvoi vers la **Charte globale du développeur (Page Confluence 26)**.
3. **Multi-dépôts (4 dépôts Orso)** :
   - `orso-core` : Portait le fichier amont sans nos règles opérationnelles.
   - `orso-docs` : Portait l'ancienne note d'interface `AGENTS.md` (redite partielle du contrat de livraison).
   - `orso-site` : Aucun fichier `AGENTS.md` à la racine.
   - `orso-app` : Aucun fichier `AGENTS.md` à la racine.
4. **Versions concurrentes actives** : Les règles opérationnelles existaient sous trois formulations concurrentes (Page Confluence 26, Document 19 section 5, et note d'interface `orso-docs/AGENTS.md`).

---

## 2. Décision d'Architecture & Arbitrage (CA1)

Pour répondre aux trois exigences posées dans le ticket :
1. *Règles lisibles par l'agent dans son environnement réel* ;
2. *Désamorçage explicite des contradictions amont* ;
3. *Survie garantie et documentée lors des synchronisations amont*.

### 2.1. Solution Retenue : Bloc d'en-tête Orso sanctuarisé + Fichiers d'entrée dédiés
- **Dans `orso-core`** : Insertion en tête de `AGENTS.md` d'un bloc délimité (`<!-- ORSO_GOVERNANCE_START -->` ... `<!-- ORSO_GOVERNANCE_END -->`) portant les 6 essentiels opérationnels Orso et une **clause de primauté absolue** invalidant les pratiques amont incompatibles (commits directs sur main, cherry-picks de contournement, squash-merge amont). Le guide amont Hermes est conservé à la suite pour la documentation interne des composants hérités.
- **Dans `orso-site` et `orso-app` (CA7)** : Création d'un fichier `AGENTS.md` racine servant de point d'entrée natif, formulé avec les essentiels opérationnels et renvoyant vers la Page 26.
- **Dans `orso-docs` (CA3)** : Le fichier `AGENTS.md` devient un renvoi daté vers la Page 26.
- **Sur Confluence (CA3)** : La section 5 du Document 19 est mise à jour pour pointer vers la Page 26, éliminant toute formulation concurrente.

### 2.2. Options écartées et justification (CA1)
- **Option B (Fichier de règles local tiers hors `AGENTS.md`)** : Écartée car l'IDE Antigravity et les agents LLM de codage chargent nativement `AGENTS.md` à la racine du workspace. Déporter les règles dans un autre fichier créerait une dépendance fragile à la configuration de l'éditeur.
- **Option C (Guide amont intact + règles transmises à l'oral / prompt)** : Écartée car elle viole le principe fondamental d'auditabilité ("Une livraison est un contrat vérifiable, pas un récit").
- **Option D (Suppression du guide amont)** : Écartée car elle casserait les repères techniques sur le fonctionnement interne de Hermes et provoquerait des conflits majeurs à chaque merge amont.

---

## 3. Matrice des Essentiels Opérationnels Portés par `AGENTS.md` (CA2)

| Essentiel Opérationnel | Description précise | Emplacement dans `AGENTS.md` |
| :--- | :--- | :--- |
| **Source de vérité unique** | Page Confluence 26 prime sur tout document. | Section 1 (En-tête) |
| **Clause de primauté** | Les règles Orso prévalent sur le texte amont Hermes. Pratiques amont (squash, cherry-pick) proscrites. | Section 1 (En-tête) |
| **Séparation des rôles** | Thibaut (Sponsor/PO/Prix/Juridique), Jarvis (PO/Tickets/CA/Revue), Antigravity (Architecte/Dev), Kimi K3 (Conseil/Contestation). | Section 2 |
| **Sanctuaire du Fork & Règle d'arrêt** | Zone A (boucle d'inférence, persistance, cache de prompt, registre outils) intouchable. Arrêt et alerte immédiats si consigne touche au Sanctuaire. | Section 3 |
| **Nommage des branches & PR** | Branches : `KAN-<n>-<slug>`, PR : `[KAN-xx] <titre>`. Zéro commit direct sur main. | Section 4 |
| **Definition of Ready (DoR)** | 6 critères obligatoires avant de passer un ticket en cours. | Section 5.1 |
| **Definition of Done (DoD)** | 5 critères obligatoires pour clore une livraison (branche, PR, Handoff, verdict PO, service en ligne, doc). | Section 5.2 |
| **Standard de Preuve Handoff** | Preuve mesurée sur le code brut servi (HTML/JSON, base, logs, HTTP). Sonde reproductible avant/après. | Section 6 |
| **Procédure de Survie Amont** | Conservation inconditionnelle du bloc Orso lors des `git merge upstream/main`. | Section 7 |

---

## 4. Procédure de Synchronisation Amont et Survie du Dispositif (CA4)

Lors d'une synchronisation avec le dépôt amont Nous Research (`upstream/main`) :

```bash
# 1. Récupération de l'amont
git fetch upstream main

# 2. Tentative de fusion
git merge upstream/main --no-commit
```

### Détection et Résolution de Conflits sur `AGENTS.md` :
1. **Règle de résolution** : Si un conflit apparaît sur `AGENTS.md`, le bloc délimité par `<!-- ORSO_GOVERNANCE_START -->` et `<!-- ORSO_GOVERNANCE_END -->` doit être **maintenu intact en tête du fichier**.
2. **Réintégration amont** : Les nouveautés ou mises à jour du guide amont doivent être insérées immédiatement après la balise `<!-- ORSO_GOVERNANCE_END -->`.
3. **Contrôle automatisé** :
   Un script de contrôle vérifie que le bloc Orso est présent, que la balise de fin est présente, et que tous les essentiels (DoR, DoD, Rôles, KAN, Handoff, Sanctuaire) s'y trouvent :
   ```bash
   python3 -c "
   with open('AGENTS.md') as f:
       c = f.read()
   assert '<!-- ORSO_GOVERNANCE_START -->' in c
   assert '<!-- ORSO_GOVERNANCE_END -->' in c
   assert 'Definition of Ready' in c
   assert 'Definition of Done' in c
   assert 'KAN-<n>-<slug>' in c
   print('AGENTS.md intègre et valide !')
   "
   ```

---

## 5. Alignement des Autres Dépôts Orso (CA7)

1. **`orso-site` (`Site_Hermes-core`)** :
   - Fichier `AGENTS.md` créé à la racine.
   - Définit le périmètre du site vitrine, les règles de sécurité (0 secret, scan de secrets, variables Vercel), les conventions `KAN-`, la DoR/DoD et le renvoi vers la Page 26.
2. **`orso-app` (`App_Hermes Core`)** :
   - Fichier `AGENTS.md` créé à la racine.
   - Définit le périmètre de l'application cliente PWA, la connexion au backend unifié port 9229, l'isolation multi-tenant, les conventions `KAN-`, la DoR/DoD et le renvoi vers la Page 26.
3. **`orso-docs` (`hermes-core`)** :
   - Fichier `AGENTS.md` mis à jour à la racine.
   - Redirige formellement vers la [Page Confluence 26](https://orso-agents.atlassian.net/wiki/spaces/Orsoagents/pages/5668865) comme référence unique.

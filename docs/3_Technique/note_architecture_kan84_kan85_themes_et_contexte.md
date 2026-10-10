# Note d'Architecture KAN-84 & KAN-85 : Organisation des Conversations par Thèmes et Reprise de Contexte

- **Date** : 10 octobre 2026
- **Auteur** : Antigravity (Architecte Technique & Développeur)
- **Destinataires** : Thibaut (Lead / Arbitre), Jarvis (PO)
- **Tickets Jira** : [KAN-84](https://orso-agents.atlassian.net/browse/KAN-84) & [KAN-85](https://orso-agents.atlassian.net/browse/KAN-85)
- **Branche de travail** : `KAN-84-themes-conversations` (dérivée de `KAN-83-historique-conversations-client`)
- **Gouvernance & Intégrité** : Respect absolu du Sanctuaire (`agent/turn_*.py`, `hermes_state*.py`, `run_agent.py`, `conversation_loop.py`). Toute logique d'exposition, de regroupement par thèmes et d'injection de contexte vit aux bords (Zone d'Évolution Orso).

---

## 1. Relevé Étape 0 : État Observé au Démarrage

Conformément à l'Étape 0 de la Charte Développeur (Page Confluence 26) :
- **Socle KAN-83** : La table `client_chat_sessions` dispose déjà des colonnes `session_id`, `tenant_id`, `user_id`, `agent_id`, `title`, `title_source`, `dossier_metier_id`, `created_at`, `last_activity_at`.
- **Validation des tests KAN-83** : 9/9 tests au vert via `./scripts/run_tests.sh tests/hermes_cli/test_client_chat_history_kan83.py`.
- **Constat d'absence de thèmes** : Aucune table `client_chat_themes` n'existe encore. Les conversations sont listées à plat.
- **Constat d'absence de contexte inter-sessions** : Chaque session de chat démarre actuellement de manière isolée sans réutilisation des échanges précédents du même thème.

---

## 2. Architecture Technique KAN-84 : Organisation en Blocs de Thèmes (4 Mots)

### 2.1 Modèle de Données SQLite (`client_chat_sessions.db`)
Création de la table `client_chat_themes` assurant l'étanchéité multi-tenant :
```sql
CREATE TABLE IF NOT EXISTS client_chat_themes (
    theme_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    title TEXT NOT NULL,
    title_source TEXT NOT NULL DEFAULT 'auto', -- 'auto' ou 'user'
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_client_themes_lookup 
ON client_chat_themes(tenant_id, user_id, agent_id, updated_at DESC);
```
Dans `client_chat_sessions`, la colonne existante `dossier_metier_id` stocke l'identifiant `theme_id` associé.

### 2.2 Extraction du Thème en Quatre Mots (CA1, CA2)
- **Règle des 4 mots maximum** : La fonction `generate_theme_title(prompt, max_words=4)` extrait un intitulé thématique percutant, en français, limité strictement à 4 mots.
- **Stabilité temporelle** : Le titre est fixé dès le premier message et ne change pas à chaque échange.
- **Rattachement automatique ou création** :
  1. Si la conversation a été initiée depuis un thème existant (via l'icône `+`), elle y est attachée directement.
  2. Si la conversation est créée de zéro (« from scratch ») :
     - Analyse du premier message : recherche de similarité lexicale avec les thèmes récents de l'utilisateur pour cet agent.
     - Si une correspondance nette est trouvée (> 60% mots-clés significatifs), la conversation rejoint ce thème.
     - Sinon, un nouveau thème est créé avec l'intitulé extrait (4 mots max).
- **Bloc provisoire UI** : Avant le premier envoi, l'UI affiche "Nouvelle discussion" comme état d'affichage transitoire (zéro écriture en base).

### 2.3 Opérations Utilisateur (Garde-fous CA3, CA4)
- **Renommage** : `PATCH /api/client/chat/themes/{theme_id}` permet à l'utilisateur de modifier le titre du thème (`title_source='user'`, interdisant tout ré-écrasement).
- **Déplacement** : `POST /api/client/chat/themes/{theme_id}/sessions/{session_id}` réaffecte une conversation à un autre thème.
- **Fusion** : `POST /api/client/chat/themes/{theme_id}/merge/{target_theme_id}` migre toutes les sessions du thème source vers le thème cible, puis supprime le thème source.
- **Suppression** : `DELETE /api/client/chat/themes/{theme_id}` supprime le thème (et ses sessions orphelines ou les détache).

---

## 3. Architecture Technique KAN-85 : Reprise de Contexte Bornée au Sein du Thème

### 3.1 Déclencheur : Icône `+` sur le Bloc de Thème (CA1)
L'icône `+` présente sur chaque bloc de thème dans l'UI Client ouvre une nouvelle session avec `theme_id` renseigné.

### 3.2 Stratégie de Contexte Retenue & Bornage Strict (CA2, CA3)
- **Problématique** : Transmettre l'intégralité des conversations d'un thème provoquerait une explosion des coûts LLM et dégraderait le cache de prompt.
- **Solution d'architecture** :
  1. **Synthèse chronologique bornée** : On sélectionne les conversations antérieures du même thème (même tenant, même utilisateur, même agent), triées par récence.
  2. **Extraction des résumés / derniers tours clés** : Pour chaque conversation précédente du thème, on extrait le titre, le sujet et le dernier échange significatif (question/réponse).
  3. **Plafond strict de jetons (Token Budget)** :
     - Plafond maximal fixé à **1 500 tokens** (~6 000 caractères).
     - Si le volume dépasse le plafond, un élagage chronologique retient les éléments les plus récents en signalant la troncature.
  4. **Format d'injection étanche** :
     Le contexte est injecté en tête de conversation sous forme de bloc délimité :
     ```text
     [CONTEXTE MÉTIER DU THÈME : "{theme_title}"]
     (Historique des échanges précédents au sein de ce thème)
     - Conversation "{titre_1}" : ...
     - Conversation "{titre_2}" : ...
     [FIN DU CONTEXTE THÉMATIQUE — Réponds aux questions de l'utilisateur en exploitant ce contexte. Si une information n'y figure pas, signale-le sans l'inventer.]
     ```
  5. **Thème neuf / vide (CA5)** : Si le thème ne comporte aucune conversation ou uniquement des discussions vides, le contexte injecté est strictement vide (0 surcoût).
  6. **Cloisonnement hermétique (CA4)** : La requête SQL filtre strictement sur `tenant_id`, `user_id`, `agent_id` et `theme_id`. Zéro fuite inter-thèmes ni inter-clients.

---

## 4. Réponses aux Questions Ouvertes du PO & Arbitrages Proposés

| Question Ouverte | Recommandation PO | Décision / Arbitrage Technique Proposé |
| :--- | :--- | :--- |
| **Placement de la colonne de thèmes dans l'UI** | Colonne repliable à droite | **Validé** : Colonne latérale droite repliable (collapsible drawer), ouverte par défaut sur grand écran et escamotable pour préserver les commandes et la zone de chat. |
| **Bouton en-tête vs bouton haut de colonne** | Garder les deux boutons | **Validé** : Les deux boutons coexistent avec la même mécanique : « Nouvelle discussion » en haut de colonne démarre un fil vierge ; l'icône `+` sur un thème crée un fil lié à ce thème. |
| **Portée des thèmes (par agent ou transverse)** | Isoler les thèmes par agent | **Validé** : Les thèmes sont strictement partitionnés par agent (`agent_id`) afin d'éviter toute confusion entre le domaine juridique (Lucas), comptable (Jérôme) ou prospection (Clara/Victor). |
| **Suppression d'un bloc quand vide** | Suppression si vide | **Validé** : Si toutes les conversations d'un thème sont supprimées, le thème est automatiquement nettoyé. |
| **Méthode de rapprochement automatique** | Décision début de conversation | **Validé** : Rapprochement basé sur l'empreinte lexicale des mots-clés du premier message, simple, déterministe et sans coût d'inférence LLM superflu. |
| **Plafond de contexte KAN-85** | Proposition 100k chars | **Ajustement d'architecture** : 100 000 caractères (~25 000 tokens) est excessif pour chaque tour de parole. Nous retenons **6 000 caractères (~1 500 tokens)**, suffisant pour l'historique d'un thème sans multiplier la facture par 10. |

---

## 5. Plan d'Implémentation & Fichiers Impactés

1. **Backend (`hermes_cli/web_routers/client_chat_history.py`)** :
   - Ajout des fonctions de gestion des thèmes (`client_chat_themes`) : création, liste, renommage, fusion, suppression, extraction en 4 mots.
   - Ajout des endpoints `/api/client/chat/themes` et sous-routes.
   - Ajout de la mécanique de construction du contexte de reprise borné (`build_theme_context_for_session`).
2. **Frontend (`apps/ui-client`)** :
   - Intégration du composant `ThemesSidebar` dans `ChatView.tsx`.
   - Affichage des thèmes, création from scratch, création contextualisée via `+`.
   - Renommage manuel et suppression de thème.
3. **Tests d'Acceptation** :
   - `tests/hermes_cli/test_client_chat_themes_kan84.py` (CA1 à CA6).
   - `tests/hermes_cli/test_client_chat_context_kan85.py` (CA1 à CA5).

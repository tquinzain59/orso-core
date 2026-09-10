# Vision et Objectifs : L'Écosystème Orso agents

Site officiel : [www.orso-agents.fr](http://www.orso-agents.fr)

---

## 1. Vision Stratégique Globale
Le projet **Orso agents** (initialement baptisé en interne *Hermes Core*) est une suite d'agents d'intelligence artificielle autonomes conçue pour révolutionner la gestion opérationnelle des Très Petites Entreprises (TPE) et des Petites et Moyennes Entreprises (PME) françaises.

Historiquement initié sur le poste névralgique de **Credit Manager & Recouvrement** (première cause de défaillance des TPE/PME), Orso agents a étendu son envergure pour devenir une **plateforme modulaire multi-agents** couvrant les fonctions vitales de l'entreprise :
1. **La Trésorerie & Finance** : Recouvrement automatisé, préservation du cash, conformité L.441-10 (Agent *Jérôme*).
2. **Le Développement Commercial** : Prospection automatisée, qualification de leads, synchronisation CRM (Agent *Lucas*).
3. **Le Support Client & SAV** : Résolution de requêtes 24/7, base de connaissances sémantique, escalade d'incidents (Agente *Clara*).
4. **La Réponse aux Marchés** : Veille sur les marchés publics (BOAMP/TED), analyse de DCE et génération de mémoires techniques (Agent *Victor*).

---

## 2. Les Trois Piliers de l'Écosystème Orso agents

L'architecture d'Orso repose sur une synergie étroite entre trois composants complémentaires :

```
                     ┌────────────────────────────────┐
                     │   Site_Hermes-core (Portail)   │
                     │  - Vitrine & démonstrations    │
                     │  - Dashboard de supervision    │
                     │  - Administration sécurisée    │
                     └───────────────┬────────────────┘
                                     │
                                     ▼
┌──────────────────────────────┐          ┌──────────────────────────────┐
│    App_Hermes Core (Client)  │◄────────►│      orso-core (Backend)     │
│  - Interface PWA multi-agents│          │  - Moteur d'agents unifié    │
│  - Cartes d'actions 1-clic   │          │  - Connecteurs ERP & APIs    │
│  - Streaming WebSocket       │          │  - Base d'état SQLite        │
│  - Pilotage des décisions    │          │  - Télémétrie financière     │
└──────────────────────────────┘          └──────────────────────────────┘
```

1. **`orso-core` (Le Moteur Backend Unifié)** : Le socle Dockerisé hébergeant l'intelligence artificielle (moteur autonome dérivé d'Hermes Agent sous licence MIT), les intégrations comptables (APIs ERP, Open Data BODACC/Sirene, Pappers), la base de données d'état SQLite et le moteur de règles métier.
2. **`Site_Hermes-core` (Le Portail Vitrine & Supervision)** : L'espace public présentant les solutions aux dirigeants ([www.orso-agents.fr](http://www.orso-agents.fr)), intégrant les vidéos de démonstration et hébergeant les consoles de supervision technique et télémétrique (`monitoring.html`, `admin.html`).
3. **`App_Hermes Core` (L'Application Client PWA)** : L'espace de pilotage opérationnel quotidien des dirigeants et équipes PME. Une application Web & Mobile moderne permettant de converser avec chaque agent et de valider des actions critiques en un clic.

---

## 3. Objectifs Stratégiques Clés

### A. Réduction du DSO et Accélération du Cash-flow (Agent Recouvrement - Jérôme)
* Traitement proactif et individualisé des créances dès le 1er jour de retard.
* Respect scrupuleux des relations commerciales et du cadre légal français (pas d'agressivité injustifiée, propositions d'échéanciers).
* Élimination des pertes sur créances irrécouvrables grâce à la veille légale anticipée (alertes BODACC).

### B. Dynamisation du Pipeline de Ventes (Agent Commercial - Lucas)
* Démultiplication de la capacité de prospection sans recrutement de SDR dédié.
* Qualification rigoureuse des prospects entrants et alimentation automatique du CRM.

### C. Excellence du Service Client 24/7 (Agent Support - Clara)
* Réduction à zéro du temps d'attente pour les requêtes courantes.
* Escalade intelligente vers les équipes humaines uniquement pour les cas à forte valeur ajoutée.

### D. Conquête de la Commande Publique (Agent Appels d'Offres - Victor)
* Démocratisation des marchés publics pour les PME en automatisant l'analyse fastidieuse des cahiers des charges (DCE) et la rédaction des mémoires techniques.

### E. Transparence et Maîtrise des Coûts LLM
* Grâce à la supervision télémétrique intégrée (`monitoring.html`), les dirigeants et administrateurs contrôlent chaque euro dépensé en inférence LLM avec un coût d'exploitation maîtrisé (< 15 $ pour plusieurs milliers d'interactions).

# Télémétrie, Suivi Financier et Supervision Temps Réel

Ce document détaille l'architecture complète de télémétrie de l'écosystème Hermès, reliant l'agrégation backend de consommation de jetons au tableau de bord graphique de supervision.

---

## 1. Pipeline de Télémétrie de Bout en Bout

```
[Conteneurs d'Agents (Backend)]
       │
       │ (Enregistre l'inférence dans state.db : session_model_usage)
       ▼
[Script telemetry.py]
       │
       │ (Agrège et génère telemetry_export.json)
       ▼
[API de Télémétrie (Port 9120)]
       │
       │ (Endpoints : /api/telemetry/summary & /api/telemetry/latest)
       ▼
[Dashboard monitoring.html (Chart.js)]
```

---

## 2. Extraction Backend (`telemetry.py`)

Le script `skills/telemetry.py` interroge la base locale SQLite (`state.db`) :
* **Volumes de Tokens** : Calcul de $\text{input\_tokens}$ et $\text{output\_tokens}$.
* **Nombre d'Appels API** : Comptabilisation des requêtes envoyées aux modèles.
* **Coût Financier Direct** : Calcul du coût réel ou estimé en USD d'après les grilles tarifaires des fournisseurs LLM (ex: OpenRouter).
* **Détection d'Erreurs** : Extraction des erreurs récentes (`handoff_error`, `compression_failure_error`) dans la table `sessions`.

### Format du Rapport Consolidé (`telemetry_export.json`)
```json
{
  "tenant_id": "hermes_recouvrement",
  "timestamp": 1788111600.0,
  "last_activity": 1788110200.0,
  "metrics": {
    "input_tokens": 4982961,
    "output_tokens": 113171,
    "total_tokens": 5096132,
    "api_calls": 331,
    "cost_usd": 10.520391264484
  },
  "errors": [],
  "status": "active"
}
```

---

## 3. Visualisation Frontend (`monitoring.html` dans `Site_Hermes-core`)

La page de supervision `monitoring.html` permet aux administrateurs et dirigeants de surveiller la consommation de la flotte d'agents :

### Fonctionnalités Clés du Dashboard
* **Graphiques Interactifs (Chart.js)** :
  * Évolution chronologique des tokens consommés par heure/jour.
  * Répartition des dépenses en dollars ($) par agent (Recouvrement, Commercial, Support, AO).
* **Cartes d'État par Serveur d'Agent** :
  * Affichage du statut en temps réel (`🟢 Opérationnel`, `🟡 En charge`, `🔴 Erreur`).
  * Modèle actif (ex: `deepseek/deepseek-v4-flash`, `claude-sonnet-4`).
  * Latence moyenne et nombre d'erreurs au cours des dernières 24 heures.
* **Résilience et Mode Démo (Mock Fallback)** :
  * Si l'API distante (`http://localhost:9120`) est temporairement injoignable, le tableau de bord bascule automatiquement sur un jeu de données simulé réaliste, permettant la démonstration des fonctionnalités de supervision à tout moment.

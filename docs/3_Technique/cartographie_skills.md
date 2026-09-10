# Cartographie des Skills, APIs et Déclencheurs UI

Ce document répertorie les compétences Python développées dans le backend, les passerelles d'intégration ERP, ainsi que leur mise en correspondance avec les actions rapides de l'application cliente `App_Hermes Core`.

---

## 1. Compétences Backend Développées (Python)

### A. Détection des Retards et Pénalités (`check_overdue.py`)
* **Emplacement** : `skills/check_overdue.py`
* **Rôle** : Détection des retards de paiement critiques, calcul des intérêts moratoires et indemnités forfaitaires de recouvrement (Code de commerce L.441-10).
* **Déclencheur App Cliente** : Commande `/retards`.

### B. Balance Âgée (`balance_agee.py`)
* **Emplacement** : `skills/credit_management/balance_agee.py`
* **Rôle** : Partitionnement de l'encours client par tranches d'ancienneté de retard (0-15j, 16-30j, 31-60j, 61-90j, 90j+).
* **Déclencheur App Cliente** : Bouton Quick Action `📊 État de la balance âgée` ou commande `/balance`.

### C. Normalisation d'Exports Comptables (`import_csv.py`)
* **Emplacement** : `skills/credit_management/import_csv.py`
* **Rôle** : Conversion des exports CSV/Excel (détection auto délimiteur `;` ou `,`) vers une structure JSON normalisée avec parsing des dates et montants français.

### D. Veille Légale Automatique (`veille_bodacc.py`)
* **Emplacement** : `skills/credit_management/veille_bodacc.py`
* **Rôle** : Interrogation de l'API OpenDataSoft BODACC (DILA) pour détecter les procédures collectives (`familleavis = "pro"`) ou radiations (`familleavis = "rad"`).

### E. Enquête de Solvabilité Pappers (`fiche_credit.py`)
* **Emplacement** : `skills/credit_management/fiche_credit.py`
* **Rôle** : Extraction de données enrichies (dirigeants, scoring financier, comptes annuels) via l'API Pappers `/entreprise`.
* **Déclencheur App Cliente** : Commande `/check <siren>` dans le chat avec Jérôme.


---

## 2. Compétences Fonctionnelles par Agent dans l'Application Cliente

Dans `App_Hermes Core/js/agents.js`, chaque agent dispose de compétences déclarées et de déclencheurs d'action rapide :

| Agent | Compétence Déclarée | Description Technique | Déclencheur UI App |
|---|---|---|---|
| **Jérôme (Recouvrement)** | `check_overdue.py`<br>`bodacc_lookup`<br>`negotiate_schedule` | Détection des retards critiques, alertes SIREN et calcul d'échéanciers L.441-10. | `/balance`<br>`/retards`<br>`/check <siren>` |
| **Lucas (Commercial)** | `lead_enrichment`<br>`crm_sync`<br>`email_outreach` | Enrichissement SIRENE/LinkedIn, mise à jour des deals CRM et rédaction d'accroches ciblées. | `/leads`<br>`/pipeline` |
| **Clara (Support)** | `kb_search`<br>`ticket_manager`<br>`smart_escalation` | Recherche vectorielle dans les FAQ, cycle de vie des tickets et alerte d'astreinte. | `/tickets`<br>`/satisfaction` |
| **Victor (Appels d'Offres)**| `boamp_scraper`<br>`dce_analyzer`<br>`technical_pitch` | Veille BOAMP/TED, extraction des critères de notation DCE et génération de trames de mémoires. | `/ao_list`<br>`/dce_analyze` |

---

## 3. Synthèse des Connecteurs ERP TPE/PME

| Solution ERP | Protocole | Méthode d'Auth | Endpoint Clé de Facturation | Statut Connecteur |
|---|---|---|---|---|
| **Pennylane** | REST | OAuth 2.0 | `api.pennylane.com/v1/customer_invoices` | ✅ Prioritaire (Sandbox) |
| **Sellsy (V2)** | REST | OAuth 2.0 | `api.sellsy.com/v2/invoices` | ✅ Opérationnel |
| **Sage Business Cloud** | REST | OAuth 2.0 | `api.accounting.sage.com/v3.1/sales_invoices` | ✅ Opérationnel |
| **QuickBooks** | REST | OAuth 2.0 | `quickbooks.api.intuit.com/v3/.../invoice` | ✅ Opérationnel |
| **Odoo (SaaS/On-Prem)** | JSON-RPC | Session Cookie | `{url}/web/dataset/call_kw` (`account.move`) | ✅ Opérationnel |
| **Dynamics 365 BC** | OData v4 | OAuth 2.0 Azure | `.../api/v2.0/agedAccountsReceivable` | ✅ Opérationnel (Balance native) |
| **Evoliz** | REST | API Key -> Bearer | `evoliz.io/api/v1/invoices` | ✅ Opérationnel |
| **Tiime / EBP / Indy** | Fichier plat | N/A | Normalisation via `import_csv.py` | ✅ Import Manuel |

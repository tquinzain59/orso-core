# KAN-53 — Gouvernance et rotation des clés d'API LLM (page d'exploitation)

Code : `olympe/llm_key_governance.py` · CLI : `scripts/iam/llm_key_governance_cli.py` · Tests : `tests/olympe/test_kan53_llm_key_governance.py`.
Périmètre : plan de gestion (Olympe) uniquement. Aucun fichier du Sanctuaire du moteur n'est modifié.

## 1. Inventaire des clés (CA1)

La base de gouvernance (`ORSO_LLM_GOVERNANCE_DB`, défaut `./data/llm_governance.db`, hors dépôt) est la source de l'inventaire. Le tableau se génère avec :

```bash
python scripts/iam/llm_key_governance_cli.py inventory --markdown
```

Il ne contient jamais de valeur ni d'empreinte. Un champ `location`, `owner` ou `key_id` qui ressemble à une clé est refusé à l'inscription.

État relevé dans le code le 17/10/2026 (point de départ à inscrire, **responsable et dernière rotation à confirmer par l'exploitation**) :

| Fournisseur | Variable | Tenant | Emplacement | Dernière rotation | Responsable |
|---|---|---|---|---|---|
| openrouter | `OPENROUTER_API_KEY` | mutualisée | environnement du plan de gestion, injectée dans chaque conteneur client (`olympe/lifecycle_manager.py`, `base_envs`) et `docker-compose.orso.yml` / `docker-compose.olympe.yml` | inconnue | à renseigner |
| openai | `OPENAI_API_KEY` | mutualisée | idem | inconnue | à renseigner |
| anthropic | `ANTHROPIC_API_KEY` | mutualisée | idem (`base_envs` seulement) | inconnue | à renseigner |
| deepseek | `DEEPSEEK_API_KEY` | mutualisée | idem (`base_envs` ; lue aussi par `olympe/ops_manager.py`) | inconnue | à renseigner |
| google | `GOOGLE_API_KEY` | mutualisée | `docker-compose.orso.yml` | inconnue | à renseigner |

Le ticket cite 14 fournisseurs ; seuls ces 5 sont visibles dans le dépôt. Les autres restent à inventorier à partir des environnements réels.

## 2. Plafond par tenant (CA2) et alertes (CA3)

```bash
# plafond mensuel (mois civil UTC), refus au-delà, alertes à 50 / 80 / 100 %
python scripts/iam/llm_key_governance_cli.py set-policy --tenant <slug> --cap-usd <montant> --mode refuse --thresholds 0.5 0.8 1.0
# défaut applicable aux tenants sans politique propre
python scripts/iam/llm_key_governance_cli.py set-policy --tenant '*' --cap-usd <montant>
```

- `mode refuse` : `authorize` renvoie `allowed=false` (code retour 3 en CLI) et journalise le refus. `mode alert_only` : l'appel passe, l'alerte part.
- Sans politique, **aucun plafond n'est appliqué** (montant non arbitré, voir §6). L'alerte de dérive reste active.
- Alerte de seuil : une fois par seuil et par mois et par tenant. Alerte de dépassement : une fois par heure et par tenant. Alerte de dérive : dépense du jour supérieure à 3 fois la moyenne quotidienne des 7 jours précédents et d'au moins 1 USD, une fois par jour. Aucune dérive n'est évaluée tant que le tenant n'a pas d'historique.
- Chaque alerte est écrite en base (`llm_alerts`), loguée au niveau WARNING (`[LLM-ALERT]`) et transmise à un `alert_sink` optionnel. Un canal externe en panne n'empêche ni l'appel ni la persistance.
- Le coût passé à `record_call` doit venir de la source de vérité (journal du fournisseur ou compteur du point de passage), jamais d'un écran applicatif.

## 3. Point d'application (état réel)

Le module fournit les contrôles `authorize` (avant l'appel) et `record_call` (après). **Rien dans le moteur n'appelle encore ces fonctions** : les clés sont toujours injectées par conteneur et le moteur appelle le fournisseur directement. Tant qu'un point de passage (proxy de budget qui détient les vraies clés et distribue des clés virtuelles par tenant) n'est pas déployé, le plafond n'est appliqué que si l'appelant l'interroge. Ce point d'application est le reste à faire principal (voir le handoff).

## 4. Rotation à chaud (CA4)

Contrainte : une conversation en cours ne doit pas être coupée. La clé est injectée dans l'environnement du conteneur au démarrage ; une session ouverte garde donc l'ancienne valeur jusqu'au redéploiement du conteneur.

1. L'opérateur (compte de service, jamais un identifiant humain) crée la nouvelle clé chez le fournisseur. **Ne pas révoquer l'ancienne.**
2. `NEW=... python scripts/iam/llm_key_governance_cli.py rotate --key-id <id> --actor svc-orso-rotation --new-key-env NEW --grace-seconds <fenêtre>` : la nouvelle valeur devient active, l'ancienne entre en grâce (défaut 900 s). La valeur n'est ni journalisée ni stockée en clair.
3. Mettre à jour l'emplacement du secret (environnement du plan de gestion), puis recréer les conteneurs : les nouvelles sessions démarrent avec la nouvelle clé. Les sessions actives continuent avec l'ancienne tant que la fenêtre court.
4. La fenêtre doit couvrir la durée du redéploiement ; elle se règle par `--grace-seconds`. À l'échéance, l'ancienne valeur passe en `revoked` : `verify` la refuse (code retour 4) et journalise le refus.
5. **Révoquer ensuite l'ancienne clé chez le fournisseur.** Cette étape reste manuelle : le module ne parle à aucun fournisseur. Le refus constaté ici est celui de la gouvernance, pas celui du fournisseur.

Journal de rotation : `rotation-log` (événements `rotation_started`, `new_key_activated`, `old_key_grace_open`, `old_key_revoked`, `verification_refused`, tous horodatés UTC avec l'acteur).

## 5. Journal d'audit des appels (CA6)

```bash
python scripts/iam/llm_key_governance_cli.py audit --tenant <slug> --since 2026-10-01T00:00:00+00:00 --csv
```

Colonnes : horodatage, tenant, fournisseur, modèle, coût USD, jetons, clé, session, décision (`allowed` ou `refused`). Les appels refusés sont consignés à coût nul et ne consomment pas le plafond.

## 6. Décisions en attente (Thibaut)

- Montant du plafond par tenant et par mois, et refus ou alerte seule au dépassement (le code supporte les deux, par tenant).
- Couplage avec Stripe : non traité ici, à porter par un ticket distinct (KAN-44 et KAN-45 sont hors périmètre).
- Clés portées par le tenant ou mutualisées : l'inventaire et l'audit gèrent les deux (`tenant = '*'` pour une clé mutualisée), mais l'état actuel est mutualisé, sans plafond côté fournisseur.

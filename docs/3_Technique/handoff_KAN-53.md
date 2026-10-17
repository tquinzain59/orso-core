# Handoff KAN-53 — Gouvernance et rotation des clés d'API LLM

Branche : `KAN-53-auto` (à renommer `KAN-53-<slug>` selon la DoD avant la PR, titre de PR avec `[KAN-53]`). Rien n'a été poussé, `main` n'a pas été touchée.
Page d'exploitation : `docs/3_Technique/procedure_kan53_gouvernance_cles_llm.md`.

**Livraison partielle** : le noyau de contrôle, son CLI, ses tests et la procédure sont livrés et vérifiés. Le **point d'application** (ce qui intercepte réellement les appels LLM des conteneurs) n'est pas livré : sans lui, le plafond ne protège rien en production. Voir « Reste à faire ».

## Étape 0 — prémisse vérifiée (avant modification)

Le ticket affirme : clés injectées par conteneur, pas de quota, pas d'alerte, pas de rotation testée. Constat sur `main` (`d4557974fd`) :

```
$ grep -n "OPENROUTER_API_KEY" olympe/lifecycle_manager.py docker-compose.orso.yml docker-compose.olympe.yml
olympe/lifecycle_manager.py:1143:        for key in ["OPENROUTER_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY"]:
docker-compose.orso.yml:17:      - OPENROUTER_API_KEY=${OPENROUTER_API_KEY:-}
docker-compose.olympe.yml:100:      - OPENROUTER_API_KEY=${OPENROUTER_API_KEY:-}
$ grep -nE "quota|plafond|spend|budget|rotat|audit" olympe/*.py | grep -iE "llm|key|cost|spend|budget"
(seules correspondances : suspend_tenant, sans rapport avec les clés LLM)
$ grep -n "cost_usd" olympe/telemetry_client.py
157: "total_cost_usd": 0.0,   203: "cost_usd": 0.0,   312: ag.get("cost_usd", 0.0)
```

Les clés sont recopiées de l'environnement de gestion dans chaque conteneur, aucun module ne plafonne, n'alerte ni ne fait tourner une clé LLM, et le coût affiché par la télémétrie est codé à 0.0. Les `rotate_poc_credentials.py` (KAN-46) et `reset_superadmin_password.py` (KAN-50) concernent des identifiants IAM, pas des clés LLM. Prémisse vraie : correction justifiée.

## Ce qui a été fait

| Fichier | Contenu |
|---|---|
| `olympe/llm_key_governance.py` | Classe `LLMGovernance` (SQLite) : inventaire sans valeur, politique de plafond par tenant (refus ou alerte seule, défaut `*`), `authorize` / `record_call`, alertes de seuil, de dépassement et de dérive dédupliquées, journal d'audit, rotation à chaud avec fenêtre de grâce, `verify_key`, journal de rotation. |
| `scripts/iam/llm_key_governance_cli.py` | CLI : `register`, `inventory`, `set-policy`, `authorize`, `record`, `audit`, `alerts`, `rotate`, `verify`, `rotation-log`, `finalize`. Les valeurs de clés se lisent en variable d'environnement ou sur stdin, jamais en argument. Codes retour : 3 appel refusé, 4 clé refusée. |
| `tests/olympe/test_kan53_llm_key_governance.py` | 18 tests de contrat (CA1 à CA6) sur base SQLite réelle et horloge injectée, dont un scénario CLI de bout en bout. |
| `docs/3_Technique/procedure_kan53_gouvernance_cles_llm.md` | Page d'exploitation : inventaire de départ, plafonds, rotation, audit, décisions en attente. |

Choix de conception :
- Aucune valeur de clé stockée : empreinte HMAC-SHA256 salée par clé, pour pouvoir refuser l'ancienne valeur. Les champs `location`, `owner`, `key_id` qui ressemblent à une clé sont refusés.
- Acteur de rotation = compte de service (`^[a-z0-9][a-z0-9_.:-]{2,63}$`, `@` refusé), conforme S1.3.
- Rotation sans coupure : l'ancienne valeur reste en `grace` pendant la fenêtre, puis passe `revoked`. Il faut une fenêtre car la clé est figée dans l'environnement du conteneur jusqu'à son redéploiement.
- Sans politique, aucun plafond (montant non arbitré). Le code gère refus et alerte seule, par tenant.

Sanctuaire non touché (aucun fichier de `agent/turn_*`, `run_agent.py`, `hermes_state*`, `providers/`, `tools/registry.py`). Aucun fichier existant modifié : 4 fichiers ajoutés.

## Vérifications (sorties brutes résumées)

- `scripts/run_tests.sh tests/olympe/test_kan53_llm_key_governance.py` : `1 files, 18 tests passed, 0 failed`, code retour 0.
- Rouge sur mutation : avec `exceeded = False` et la révocation neutralisée, 8 tests échouent (`test_ca2_*`, `test_ca4_*`, `test_alert_only_*`, `test_default_policy_*`, `test_two_successive_rotations_*`, `test_cli_end_to_end_*`) ; le code restauré repasse à 18/18.
- `ruff check` sur les 3 fichiers Python : `All checks passed!`, code retour 0. `ruff check .` (gate CI) : `All checks passed!`, code retour 0.
- Scan de secrets : aucun scan de dépôt dédié n'existe en local (pas de gitleaks). Regex (`sk-`, `AIza`, `ghp_`, `xox*`, hexadécimal ≥ 40) sur les 4 fichiers : aucune correspondance (code retour 1). Les valeurs de test sont factices et générées dans le test.

### Preuves brutes de scénario (CLI réel, base temporaire, valeurs de clés aléatoires jetables)

CA2 — plafond 10 USD, 8.5 dépensés, appel estimé à 2.0 :
```
[LLM-ALERT] {"cap_usd": 10.0, "estimated_cost_usd": 2.0, "kind": "cap_exceeded", "mode": "refuse", "model": "demo/model-a", "period": "2026-10", "provider": "openrouter", "refused": true, "spent_usd": 8.5, "tenant_slug": "demo", "ts": "2026-10-17T05:56:50+00:00"}
{"allowed": false, "cap_usd": 10.0, "mode": "refuse", "reason": "cap_exceeded", "spent_usd": 8.5, "tenant_slug": "demo", "ts": "2026-10-17T05:56:50+00:00", ...}
code retour authorize = 3
```
CA3 — seuils configurés 0.5 / 0.8 / 1.0 :
```
{"cap_usd": 10.0, "kind": "threshold", "spent_usd": 6.0, "threshold_ratio": 0.5, "threshold_usd": 5.0, "ts": "2026-10-17T05:56:50+00:00"}
{"cap_usd": 10.0, "kind": "threshold", "spent_usd": 8.5, "threshold_ratio": 0.8, "threshold_usd": 8.0, "ts": "2026-10-17T05:56:50+00:00"}
```
CA4 — rotation avec grâce de 3 s :
```
rotate  -> rotated_at 2026-10-17T05:56:50+00:00, grace_until 2026-10-17T05:56:53+00:00
verify ancienne (pendant la grâce) -> status grace, accepted true,  ts 05:56:51, code retour 0
verify ancienne (après la grâce)   -> status revoked, accepted false, ts 05:56:55, code retour 4
verify nouvelle                    -> status active, accepted true,  ts 05:56:55, code retour 0
journal : rotation_started, new_key_activated, old_key_grace_open (05:56:50), old_key_revoked, verification_refused (05:56:55)
```
CA6 — extrait du journal d'audit :
```
ts,tenant_slug,provider,model,cost_usd,input_tokens,output_tokens,key_id,session_id,decision
2026-10-17T05:56:50+00:00,demo,openrouter,demo/model-a,3.0,1000,400,openrouter-demo,,allowed
2026-10-17T05:56:50+00:00,demo,openrouter,demo/model-a,2.5,0,0,openrouter-demo,,allowed
2026-10-17T05:56:50+00:00,demo,openrouter,demo/model-a,0.0,0,0,,,refused
```
CA5 — `grep -c` des deux valeurs de clé dans le fichier de base : `0`.

> Ces preuves viennent d'un scénario synthétique sur base temporaire, pas d'un tenant réel ni d'un fournisseur réel. Elles prouvent le contrôle, pas son application en production.

## Reste à faire (non fait)

1. **Point d'application (bloquant pour la valeur du ticket)** : un proxy de budget entre les conteneurs et les fournisseurs, qui détient les vraies clés, distribue des clés virtuelles par tenant, appelle `authorize` avant et `record_call` après avec le coût lu au fournisseur. Alternative ou complément : plafonds natifs côté fournisseur (limite par clé), à vérifier fournisseur par fournisseur. Cela touche le chemin d'appel des modèles ; il doit se faire au bord (proxy, `base_url` par profil), **pas** dans `providers/` ni la boucle (Sanctuaire).
2. **Coût source de vérité** : brancher `record_call` sur le journal du fournisseur ou sur le compteur du proxy. La télémétrie Olympe renvoie encore `cost_usd = 0.0` en dur.
3. **Inventaire réel (CA1)** : inscrire les clés (`register`), renseigner responsables et dates de rotation, publier le tableau sur la page d'exploitation. Seuls 5 fournisseurs sont visibles dans le dépôt sur les 14 cités.
4. **Canal d'alerte** : l'`alert_sink` est un point d'extension sans consommateur câblé ; aujourd'hui l'alerte est en base et dans les logs. Brancher le canal retenu (le cockpit Ops a déjà une table d'alertes).
5. **Révocation côté fournisseur** après la fenêtre de grâce : manuelle, hors module. CA4 « ancienne clé refusée » est prouvé côté gouvernance, pas côté fournisseur.
6. **Scan de secrets (CA5)** : à exécuter par l'outil officiel sur tous les dépôts concernés ; non fait ici faute d'outil installé.
7. **Concurrence** : le plafond se vérifie puis se consomme en deux temps (`authorize`, puis `record_call`). Sous forte concurrence, un dépassement d'un petit nombre d'appels en vol reste possible ; un proxy mono-point avec réservation atomique le réduirait. La base SQLite est locale à un hôte : pas de partage multi-hôtes.
8. **Hors ticket** : renommage de branche, PR `[KAN-53]`, écriture de la version livrée dans le ticket, mise à jour de la page Confluence, verdict du PO et vérification en ligne.

## À vérifier à la recette (PO)

1. Décision de Thibaut : montant du plafond par tenant et par mois, refus ou alerte seule, clés par tenant ou mutualisées, Stripe dans un ticket séparé. Puis `set-policy` en conséquence.
2. Rejouer le scénario CA2 à CA4 et CA6 sur la base de recette avec les commandes de la page d'exploitation (§2, §4, §5) ; contrôler les codes retour 3 et 4.
3. Lire la page d'exploitation et le tableau d'inventaire : aucune valeur secrète.
4. Confirmer que le point d'application (reste à faire n°1) est prévu avant de déclarer le plafond « actif » : tant qu'il manque, CA2 n'est prouvé qu'au niveau du module.

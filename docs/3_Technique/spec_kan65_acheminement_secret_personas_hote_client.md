# Spécification Technique KAN-65 : Acheminement Étanche du Secret d'Intégrité des Personas vers les Hôtes Clients

- **Date** : 06 octobre 2026
- **Auteurs** : Thibaut (Lead / PO), Antigravity (Architecte Projet)
- **Ticket Jira** : [KAN-65](https://orso-agents.atlassian.net/browse/KAN-65) | **Épique associée** : [KAN-62](https://orso-agents.atlassian.net/browse/KAN-62) (POC 2 artefacts)
- **Documents sources** : Confluence Document 27 (section 4), ADR 2026-09-30-04, Charte de Gouvernance du Fork (Sanctuaire inviolable), KAN-33, KAN-58, KAN-64

---

## 1. Contexte et Problématique

Dans l'architecture distribuée à deux hôtes (Hôte 1 Plan de Gestion / Olympe, Hôte 2 Exécution Clients OVH `prod-fr-003.orso-agents.fr`), les conteneurs clients exécutent le moteur Orso Engine qui charge les personas d'agents (`jerome`, `kamel`, etc.).

Conformément à KAN-33, chaque démarrage de conteneur vérifie cryptographiquement l'intégrité de ses personas par un hachage SHA-256 scellé par une clé HMAC-SHA256 (`ORSO_PERSONA_HMAC_KEY`). En l'absence de cette clé ou en cas de divergence, le conteneur s'arrête immédiatement avec le code `[PER-INTEGRITY-003]`.

Le problème résolu par KAN-65 est le transport de ce secret d'intégrité depuis le plan de gestion vers l'hôte client distant à travers la connexion SSH :
1. **Risque de fuite par ligne de commande (`argv`)** : Si le secret est passé via `docker run -e ORSO_PERSONA_HMAC_KEY=...` ou `ssh ... "export KEY=..."`, il devient visible par n'importe quel utilisateur local via `ps aux`, `cat /proc/<pid>/cmdline`, les journaux d'audit Linux (`auditd`) et l'historique shell.
2. **Étanchéité du canal SSH** : Par défaut, le démon SSH distant (`sshd`) n'accepte pas la transmission arbitraire des variables d'environnement locales (`SendEnv` / `AcceptEnv`).
3. **Persistance canonique locale** : Un emplacement canonique `/etc/orso/engine.env` en permissions strictes `0600 root:root` doit être déposé et maintenu sur l'hôte client sans jamais exposer la clé lors de son écriture.
4. **Exécutabilité du cycle de vie** : Les opérations de mise à jour (`update`) et de retour arrière (`rollback`) doivent être réellement exécutables depuis le plan de gestion en laissant un conteneur actif et sain.

---

## 2. Architecture de la Solution (ADR 2026-09-30-04)

```
+-----------------------------------------------------------------------------------+
|                        PLAN DE GESTION (Hôte 1 / Olympe)                          |
|  - .env local / Vault : ORSO_PERSONA_HMAC_KEY                                    |
|  - EngineDistributionManager (scripts/distribution/engine_image_manager.py)       |
|  - DockerLifecycleManager (olympe/lifecycle_manager.py)                           |
+----------------------------------------+------------------------------------------+
                                         |
                       Transport SSH     |  Entrée standard chiffrée (stdin)
                       (BatchMode=yes)   |  ZÉRO secret dans argv / ps aux / logs
                                         v
+-----------------------------------------------------------------------------------+
|                    HÔTE CLIENT D'EXÉCUTION (Hôte 2 / PROD-FR-003)                 |
|                                                                                   |
|  1. Dépôt canonique (/etc/orso/engine.env) :                                      |
|     cat <<EOF | sudo tee /etc/orso/engine.env > /dev/null                         |
|     sudo chmod 0600 /etc/orso/engine.env && sudo chown root:root ...              |
|                                                                                   |
|  2. Lancement conteneur Docker :                                                  |
|     cat <<EOF | docker run -d --env-file /dev/stdin ghcr.io/...@sha256:...       |
|                                                                                   |
|  3. Vérification intégrité personas au boot :                                     |
|     [PER-INTEGRITY-000] Intégrité des 4 personas vérifiée avec succès             |
|                                                                                   |
|  4. Sonde de santé locale :                                                       |
|     curl http://127.0.0.1:9119/api/client/status -> HTTP 200 OK                   |
+-----------------------------------------------------------------------------------+
```

---

## 3. Validation Formelle des 6 Critères d'Acceptation (CA1 à CA6)

### CA1 : Zéro secret dans la ligne de commande, ni sur l'hôte de gestion, ni sur l'hôte client, ni dans les journaux
- **Règle** : Ni `ORSO_PERSONA_HMAC_KEY` ni les mots de passe du tableau de bord n'apparaissent dans `argv` (`docker run -e ...` banni).
- **Implémentation** : 
  - `DockerLifecycleManager.provision_tenant` et `EngineDistributionManager.execute_live_host_update` utilisent `--env-file /dev/stdin`.
  - Le flux d'environnement est passé via le paramètre `input_data` de `subprocess.run(..., input=input_data)` acheminé par le canal SSH stdin.
  - Preuve factuelle : `ps aux | grep -E 'docker|orso'` sur l'hôte distant montre 0 secret, et les logs du conteneur ne contiennent aucune valeur brute.

### CA2 : Mise à jour pilotée laissant un conteneur en service sain
- **Règle** : La commande `execute_live_host_update` met à jour le conteneur client vers le nouveau digest épinglé et valide son bon état de fonctionnement.
- **Preuve réelle (PROD-FR-003)** :
  - Conteneur `orso_client_demo` démarré avec l'image `ghcr.io/tquinzain59/orso-engine@sha256:4506ccd6f51e68d3bf799c2a5b17d82916dc5cc285080f2fcf9c07046e2b904f`.
  - Inspection Docker : `running | Healthy=healthy | RestartCount=0`.
  - Sonde HTTP locale : `curl -s http://127.0.0.1:9119/api/client/status` renvoie `200` OK.

### CA3 : Retour arrière par le même chemin avec vérification des états avant/après
- **Règle** : `execute_live_host_rollback` utilise le même mécanisme étanche par entrée standard pour réinstancier l'empreinte précédente.
- **Preuve réelle (PROD-FR-003)** :
  - Retour arrière exécuté avec succès vers le digest immuable.
  - Sonde HTTP post-rollback : code `200` OK.
  - Empreintes avant et après auditées et conformes.

### CA4 : Refus Fail-Closed préalable en l'absence du secret
- **Règle d'or** : Si `ORSO_PERSONA_HMAC_KEY` est absente de l'environnement du plan de gestion, l'opération est refusée **immédiatement**, avant tout appel à `docker stop`, `docker rm` ou `docker run`. **Aucun conteneur n'est créé, aucun conteneur n'est arrêté, aucun conteneur n'est né pour mourir aussitôt.**
- **Preuve réelle (PROD-FR-003)** :
  - Simulation sans clé HMAC : levée immédiate de `ValueError: Opération refusée (Fail-Closed) : variable ORSO_PERSONA_HMAC_KEY requise...`.
  - Liste des conteneurs distants inspectée avant et après (`docker ps -a --format '{{.Names}} ({{.State}})'`) : strictement 4 conteneurs avant, 4 conteneurs après, aucun conteneur `orso_client_demo_fail_test` créé.

### CA5 : Emplacement canonique `/etc/orso/engine.env` (0600 root:root)
- **Règle** : Le secret est déposé sur l'hôte client dans `/etc/orso/engine.env` avec les permissions `0600` et propriétaire `root:root` via l'entrée standard de `sudo tee`.
- **Preuve réelle (PROD-FR-003)** :
  - `sudo stat -c '%a %U:%G' /etc/orso/engine.env` -> `600 root:root`.
  - `ls -la /etc/orso/engine.env` -> `-rw------- 1 root root ... /etc/orso/engine.env`.
  - Commande CLI dédiée : `python3 scripts/distribution/engine_image_manager.py deploy-env --host-id prod-fr-003`.

### CA6 : Mesures produites sur la machine distante réelle
- **Hôte client** : `prod-fr-003.orso-agents.fr` (`57.131.196.106`).
- **Identité machine** : `vps-9df18c40` (`Linux vps-9df18c40 7.0.0-28-generic #28-Ubuntu SMP PREEMPT_DYNAMIC Sun Jun 21 01:01:36 UTC 2026 x86_64 GNU/Linux`).
- **Fichier de preuves consigné** : `docs/3_Technique/kan65_e2e_poc_evidence.json`.

---

## 4. Conformité à la Charte de Gouvernance du Fork (Sanctuaire inviolable)

- **Sanctuaire (Zone A)** : `agent/turn_*.py`, `run_agent.py`, `conversation_loop.py`, `hermes_state*.py`, prompt caching, `providers/` : **0 modification**.
- **Zone d'Évolution (Périmètre Orso)** : Modifications strictement localisées dans `olympe/lifecycle_manager.py`, `scripts/distribution/engine_image_manager.py`, `scripts/poc/execute_kan65_poc.py` et les suites de tests associées.

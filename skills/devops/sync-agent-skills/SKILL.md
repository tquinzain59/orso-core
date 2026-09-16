---
name: sync-agent-skills
description: Rapatrie et assainit les skills d'un agent distant.
version: 1.0.0
author: Thomas Quinzain + Orso Team
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [devops, sync, skills, docker, vps, repatriation]
    category: devops
---

# Sync Agent Skills Skill

Rapatrie les nouvelles compétences, mémoires et connecteurs développés par un agent lors de son entraînement en conditions réelles (sur VPS ou conteneur) vers le socle `orso-core`. Ce skill assainit systématiquement les données en filtrant les secrets et identifiants pour sécuriser les futurs déploiements.

## When to Use

- Après avoir entraîné un agent sur un serveur VPS OVH ou un conteneur distant.
- Quand un agent a créé ou enrichi des compétences (`skills/`) ou des mémoires (`USER.md`).
- Pour intégrer les nouveaux connecteurs dans les sources git sans divulguer de secrets.

Do not use this skill to synchronise raw production databases or sensitive runtime tokens.

## Prerequisites

- Accès au dossier ou au volume de l'agent distant (via SSH, rsync ou montage local).
- Outils natifs disponibles dans le terminal : `read_file`, `search_files`, `terminal`.
- Interpréteur Python 3.10+ pour exécuter le script d'automatisation.

## How to Run

Lancez le script d'assainissement et de rapatriement via le `terminal` :

```bash
python -m skills.devops.sync-agent-skills.scripts.repatriate_agent --source <source_path> --agent <agent_id> --sanitize
```

## Quick Reference

| Action | Commande | Description |
|---|---|---|
| Simulation (dry run) | `python -m skills.devops.sync-agent-skills.scripts.repatriate_agent --source <src> --agent jerome --dry-run` | Affiche les fichiers détectés et exclus sans rien écrire |
| Rapatriement assaini | `python -m skills.devops.sync-agent-skills.scripts.repatriate_agent --source <src> --agent jerome --sanitize` | Copie skills + mémoires en expurgeant tous les secrets |
| Export global | `python -m skills.devops.sync-agent-skills.scripts.repatriate_agent --source <src> --agent jerome --export-shared` | Copie aussi les skills dans le catalogue racine `skills/` |

## Procedure

1. **Identifier la source** : Localiser le profil de l'agent sur le VPS (ex: `/opt/orso/data/profiles/jerome`).
2. **Exécuter la simulation** : Utiliser `--dry-run` pour vérifier la liste des compétences et des fichiers à importer.
3. **Appliquer le rapatriement** : Exécuter avec `--sanitize` pour garantir qu'aucun fichier `.env` ni jeton API n'est copié.
4. **Vérifier les gabarits** : Contrôler le fichier `.env.example` généré pour documenter les nouvelles variables requises.
5. **Valider les tests** : Exécuter la suite de tests unitaires avec `terminal` pour confirmer l'intégrité du code.

## Pitfalls

- **Fuite d'identifiants** : Ne jamais forcer la copie d'un fichier `.env` de production vers le dépôt git.
- **Collisions de version** : Vérifier que le nom d'un skill créé à distance n'écrase pas une compétence existante sans accord.
- **Dépendances manquantes** : Si un skill distant nécessite des paquets Python additionnels, les reporter dans `requirements-base.txt`.

## Verification

Vérifier que les fichiers rapatriés sont présents et assainis :

```bash
python -m unittest tests/skills/test_sync_agent_skills.py
```

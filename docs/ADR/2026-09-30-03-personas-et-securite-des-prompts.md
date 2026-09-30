# ADR 2026-09-30-03 : Architecture des Personas Agents (SOUL.md), Intégrité au Démarrage et Résistance aux Injections

- **Date** : 30 septembre 2026
- **Statut** : Accepté et Mis en œuvre (Livraison KAN-33)
- **Auteur** : Antigravity (Architecte-Développeur)
- **Référence Charte** : D1.3, A1.1, A1.5, A1.8, S1.1, S1.5

---

## 1. Contexte
Dans le framework Hermes Agent sous-jacent, le comportement de base de l'agent est instruit par une persona déclarée dans le fichier `SOUL.md` (ton, rôle, directives opérationnelles, limites déontologiques).
Dans Orso Agents, plusieurs personas métiers sont configurées selon le profil d'entreprise souscrit : DAF (Sophie / Jérôme), Support client (Claire / Clara), Opérateur IA (Lucas), Assistant AO (Victor), etc.

**Faits constatés au 30/09/2026 (Résolus par KAN-33)** :
1. *Absence de verrouillage physique de SOUL.md* : Dans le modèle upstream hérité, `SOUL.md` était accessible en lecture et écriture dans l'espace de travail de l'agent.
2. *Risque d'injection et d'auto-altération* : Disposant d'outils d'écriture de fichiers (`write_file`, `patch_file`, `terminal`), un agent soumis à un prompt injection sophistiqué ou une dérive d'hallucination pouvait tenter d'écraser son propre fichier `SOUL.md`.
3. *Absence de contrôle d'intégrité au démarrage* : Aucun hash cryptographique de la persona n'était vérifié au boot du conteneur Docker.

## 2. Décision (État Réel & Mesures de Durcissement KAN-33)
1. **Sanctuaire et Invariance du Cache de Prompt** :
   - L'instruction de la persona est injectée lors de la phase d'initialisation de l'agent dans le préfixe immuable du prompt système.
   - Conformément aux règles inviolables du Sanctuaire Hermes, la persona ne subit **aucune modification dynamique en cours de session**, ce qui garantit le bénéfice intégral du prompt caching des fournisseurs d'API et la stabilité du comportement.
2. **Immutabilité physique du fichier SOUL.md** :
   - Le fichier `SOUL.md` est déployé avec des permissions strictes en lecture seule (`chmod 0444`) appartenant à l'utilisateur root (`chown root:root`).
   - Dans le conteneur Docker, le répertoire des personas est monté avec le drapeau `:ro` (read-only volume).
3. **Contrôle d'intégrité cryptographique au démarrage (Fail-Closed)** :
   - À chaque démarrage d'un conteneur d'agent, le script `scripts/security/persona_integrity.py` recalcule l'empreinte SHA-256 de chaque `SOUL.md`.
   - Cette empreinte est comparée au manifeste `profiles/personas.lock.json` commité dans le dépôt.
   - En cas de divergence (altération, corruption ou falsification), le démarrage échoue immédiatement avec alerte critique `PER-INTEGRITY-001` (Règle I1.1, code retour 1).
4. **Surveillance périodique à l'exécution** :
   - Un processus d'arrière-plan inspecte les hashs toutes les 300 secondes. En cas d'écart, alerte `PER-INTEGRITY-002` enregistrée dans la télémétrie et arrêt d'urgence du conteneur.
5. **Cloisonnement des outils du modèle** :
   - Les outils de manipulation de fichiers (`tools/file_tools_write_guards.py`) bloquent strictement toute tentative d'écriture dans `profiles/`, `SOUL.md` ou `personas.lock.json`.

## 3. Alternatives écartées et raisons du rejet
- **Modification de persona en cours de conversation (live tuning)** : Rejeté formellement car cela invalide immédiatement le cache de prompt Hermes, multipliant les coûts de tokens par 5 à 10 et introduisant un risque majeur de contamination du prompt.
- **Intégration en dur dans le code Python** : Rejeté car cela brise la séparation entre le Sanctuaire du moteur et la personnalisation métier propre à Orso.

## 4. Conséquences (y compris ce qui devient plus difficile)
- Toute mise à jour de persona (changement de ton, ajustement de prompt) nécessite un re-démarrage du conteneur de l'agent et la mise à jour de `personas.lock.json` par commit Git revu.
- L'agent ne peut pas "apprendre" de nouvelles règles en modifiant sa propre persona : son apprentissage à long terme doit emprunter exclusivement le mécanisme standardisé de mémoire et de skills Hermes.

## 5. Éléments dépréciés et retrait effectif
- **Montage de `SOUL.md` en lecture-écriture** : Retiré et verrouillé définitivement le 30/09/2026 (Livraison KAN-33).

## 6. Date de réexamen
- **Date prévue** : 30 octobre 2026 (revue des tests d'injection red-team sur les personas).

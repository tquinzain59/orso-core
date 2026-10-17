# Procédure de réinitialisation encadrée de la base client (KAN-98)

> **Statut : projet, à valider par le PO.** Cette procédure est publiée pour rendre la borne (CA5) opposable. Elle n'a été exécutée à aucun moment. Le script de purge du ticket KAN-71 (`scripts/iam/clean_production_database_kan71.py`) ne doit pas être réutilisé tel quel : il cible une liste figée de slugs.

## 1. Borne : quand la réinitialisation est interdite

**La réinitialisation est interdite dès qu'une facture de valeur comptable existe, c'est-à-dire dès le premier client réel facturé.**

- La règle de conservation des pièces justificatives comptables (dix ans à compter de la clôture de l'exercice) prime sur tout besoin de confort d'exploitation.
- Vérification obligatoire avant toute étape, à consigner dans le ticket avec sa date : aucune ligne de `invoices` ne correspond à un client réel (hors clients de test connus), et aucune facture Stripe en mode réel n'a été émise.
- En cas de doute, la réinitialisation n'a pas lieu. Un effacement ne remplace pas une réparation.

## 2. Porte d'entrée : les conditions préalables

Toutes doivent être vraies et prouvées avant l'étape 3 :

1. KAN-87, KAN-88 et KAN-96 sont fermés, chacun avec un verdict signé selon la procédure de revue, et leur code est fusionné dans `main`.
2. Le contrat « une ligne d'abonnement naît d'un objet Stripe, ou elle ne naît pas ; l'essai est un état de cette ligne » est écrit par le PO, et le mécanisme est décidé par l'architecte.
3. La borne du §1 est vérifiée à la date de l'exécution.
4. L'approbation écrite de Thibaut est donnée pour l'exécution sur l'environnement réel.

## 3. Périmètre

- **Recréé par le tunnel** : clients, abonnements, instances de conteneur, agents déployés.
- **Jamais touché** : le superviseur Olympe, les définitions d'agents, les tarifs et objets Stripe, les secrets et accès, la documentation.

## 4. Étapes

1. **Archiver avant tout.** Faire un export daté de toutes les tables concernées (`tenants`, `profiles`, `tenant_instances`, `agent_instances`, `subscriptions`, `tenant_integrations`, `tenant_channels`, `invoices`, `audit_logs`, `processed_events`, comptes d'authentification liés). Conserver le fichier comme pièce, avec son nom daté, son empreinte SHA-256 et son emplacement, dans un répertoire non suivi par Git (`scripts/iam/backups/` est ignoré). L'export contient des données nominatives : il ne va jamais dans le dépôt. Contrôler que l'archive est lisible avant de continuer. **Rien n'est recréé tant que l'archive n'est pas produite** (CA2).
2. **Remettre à zéro le périmètre du §3**, par une opération qui ne supprime jamais une facture. Elle s'exécute en simulation d'abord, puis avec confirmation explicite.
3. **Recréer deux clients de test par le tunnel d'abonnement**, sans aucune écriture manuelle dans les tables. Le second client rejoue le même parcours que le premier, pour vérifier que le tunnel se comporte de la même façon deux fois (arbitrage du 07/10/2026). Garder le journal du tunnel (CA3).
4. **Rejouer la grille d'acceptation** (section 5) sur la base neuve, avec les identifiants obtenus pour chaque point (CA4).
5. **Garder l'archive accessible** pendant toute la campagne, pour comparer le neuf et l'ancien.

## 5. Grille d'acceptation à remplir (CA4)

| # | Point | Preuve mesurée à consigner |
|---|---|---|
| 1 | Un paiement crée exactement un client et une seule ligne d'abonnement, qui porte l'identifiant `sub_…` Stripe | identifiant du client, de la ligne, de l'abonnement Stripe ; nombre de lignes |
| 2 | Une facture existe et reste consultable de notre côté, sans dépendre du prestataire | identifiant de la facture, lecture dans notre base |
| 3 | Le statut commercial du cockpit s'explique : ligne, date, contrepartie Stripe | capture ou réponse de l'API OPS avec les trois éléments |
| 4 | Une résiliation endort l'environnement et laisse la trace intacte | statut de l'instance, lignes d'audit et factures avant/après |
| 5 | Un second paiement sur le même client ne crée pas de seconde ligne | nombre de lignes avant/après |
| 6 | L'archive de l'ancienne base existe, est datée et consultable | nom, date, SHA-256, emplacement |

## 6. Ce qui est interdit

- Toute réinitialisation dès le premier client réel facturé.
- Toute suppression de facture, par n'importe quel chemin.
- Tout remplissage manuel des tables du périmètre pour « fabriquer » les clients de test.
- Toute modification du sanctuaire du moteur.

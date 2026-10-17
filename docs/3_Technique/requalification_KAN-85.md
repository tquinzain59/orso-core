# Requalification KAN-85 — Reprise du contexte au sein d'un thème

- **Date** : 2026-10-17
- **Branche** : `KAN-85-auto` (= `main` @ `d4557974fd`)
- **Verdict** : la prémisse du ticket ne tient plus. **Aucun code modifié, aucun commit de correction.**

## 1. Ce que le ticket affirme

> « Etat actuel : aucune mécanique de contexte n'existe entre conversations, puisqu'il n'existe déjà pas d'historique. »

Il demande donc de construire : l'icône plus, le contexte de reprise borné, la trace de ce qui est transmis, le cloisonnement, le signalement de l'information manquante, et le contexte nul pour un thème vide (CA1 à CA5).

## 2. Ce que le code fait réellement

Tout cela existe déjà sur `main`, livré par les PR KAN-83, KAN-84 (#30) et KAN-85 :

```
$ git log --oneline --all -i --grep="KAN-8[345]"
98f70e3fb4 test(recette): script de vérification en ligne des 8 mesures KAN-84/KAN-85 et support SUPABASE_JWT_SECRET
9aad9be2ca fix(client-ui): reprise des lots KAN-84 et KAN-85, étanchéité du harnais 44/44 et alignement CA1-CA9
8d9db4bf63 Merge pull request #30 from tquinzain59/KAN-84-themes-conversations
a5f41f5d60 [KAN-85] feat(client-ui): reprise de contexte bornee au sein d'un theme et integration UI (CA1-CA5)
12e301c0cd [KAN-84] feat(client-ui): organisation des conversations par themes en 4 mots (CA1-CA7)
1ff7d271a6 [KAN-83] feat(client-ui): historique des conversations, renommage, suppression et retention 60j (CA1-CA7)
```

Éléments en place (zone d'évolution uniquement) :

| Exigence du ticket | Où dans le code |
| :--- | :--- |
| Icône plus sur le bloc de thème (CA1) | `apps/ui-client/src/pages/ChatView.tsx` : `handleStartSessionInTheme` (l. 325), `Plus` |
| Contexte construit depuis les conversations précédentes du thème | `hermes_cli/web_routers/client_chat_history.py` : `get_theme_context_for_session` (l. 303-400) |
| Cloisonnement tenant / utilisateur / agent / thème (CA4) | requêtes SQL filtrées sur les 4 clés (l. 329-344) ; session active exclue (`session_id != ?`) |
| Contexte nul si thème neuf ou vide (CA5) | retours `""` (l. 335, 348, 357, 391) |
| « Signaler sans inventer » | pied de contexte (l. 394) |
| Borne + troncature garde-fou (CA3) | `max_chars` (l. 309), troncature (l. 398-399) ; endpoint `/api/client/chat/themes/.../context` renvoyant `length_chars` (l. 979) |
| Injection au démarrage de session | `hermes_cli/web_routers/client_ui.py` l. 1946-1960, 2029 (`ephemeral_system_prompt`), 2205-2234 |
| Stratégie écrite | `docs/3_Technique/note_architecture_kan84_kan85_themes_et_contexte.md` §3 |
| Recette en ligne | `scripts/recette_en_ligne_kan84_kan85.py` |

Aucun fichier du Sanctuaire n'est concerné par ce dispositif.

## 3. Commandes et sorties brutes

### 3.1 Contrôle ruff (gate du ticket)

```
$ ruff --version
ruff 0.15.10
$ ruff check hermes_cli/web_routers/client_chat_history.py hermes_cli/web_routers/client_ui.py \
    tests/hermes_cli/test_client_chat_context_kan85.py tests/hermes_cli/test_client_chat_themes_kan84.py \
    scripts/recette_en_ligne_kan84_kan85.py
All checks passed!
RC=0
```

### 3.2 Tests d'acceptation

```
$ ./scripts/run_tests.sh tests/hermes_cli/test_client_chat_context_kan85.py \
    tests/hermes_cli/test_client_chat_themes_kan84.py tests/hermes_cli/test_client_chat_history_kan83.py
...
INFO hermes_cli.client_ui:client_ui.py:2078 Passerelle AIAgent directe indisponible (No module named 'requests'), bascule vers mode résilient
...
=== 3 files with test failures (4 tests failed) ===
  tests/hermes_cli/test_client_chat_history_kan83.py  (1 test failed)
  tests/hermes_cli/test_client_chat_context_kan85.py  (2 tests failed)
  tests/hermes_cli/test_client_chat_themes_kan84.py  (1 test failed)
  - tests/hermes_cli/test_client_chat_context_kan85.py::test_kan85_ca2_engine_receives_theme_context_in_prompt
  - tests/hermes_cli/test_client_chat_context_kan85.py::test_kan85_ca4_trap_question_no_hallucination_or_cross_theme_leak
  - tests/hermes_cli/test_client_chat_history_kan83.py::test_ca3_context_continuity_on_resumed_conversation
  - tests/hermes_cli/test_client_chat_themes_kan84.py::test_kan84_cost_and_frequency_of_classification_bounded
RC=1
```

```
$ source .venv/bin/activate; python -c "import requests"
ModuleNotFoundError: No module named 'requests'
```

Les 4 tests rouges sont ceux qui exigent que le moteur factice (`AIAgent`) soit réellement appelé. Dans cet environnement, l'import de `AIAgent` échoue sur `requests` (absent du `.venv`), le code bascule en « mode résilient » et les faux moteurs ne reçoivent aucun appel (`len(calls) == 0`). Les autres tests passent. La cause relève donc de l'environnement, pas d'une régression du code. Ce point reste à confirmer sur un venv complet (`uv sync` / CI) : je n'ai pas modifié l'environnement.

## 4. Écarts réels entre le ticket et le code (restent à faire / arbitrer)

1. **Plafond non aligné sur l'arbitrage du 10/10/2026.** Le ticket retient **3 000 caractères (~750 jetons)**. Le code applique `max_chars = 6000` (l. 309), et la note d'architecture annonce 6 000 caractères / 1 500 jetons. Les tests assertent `<= 6000`. Une correction de la valeur par défaut (et des tests/doc) est petite, mais je ne l'ai pas faite : la consigne est de ne produire aucun commit de correction quand la prémisse est caduque. À trancher par le PO / Thibaut.
2. **Réponse « mode résilient » à mots-clés** (`client_ui.py` l. 2080-2092). Quand le moteur est injoignable, une réponse écrite à la main renvoie le contexte du thème pour tout prompt contenant « devis », « montant », « combien », etc., et une réponse « information absente » pour « piège », « inconnu », etc. Ces réponses ne viennent pas du moteur. Elles peuvent faire passer CA2 et CA4 sans que le moteur ait raisonné. Les preuves de recette doivent inclure l'identifiant de la requête moteur (CA2) et confirmer que `llm_invoked` est vrai.
3. **Surcoût chiffré et mesuré** : aucune mesure de jetons ajoutés par conversation et d'effet sur la facture (cache relu) n'est dans le dépôt. À mesurer en ligne.
4. **Journal de la requête (CA3)** : l'endpoint de contexte renvoie la longueur, mais je n'ai pas trouvé de journal serveur du contenu réellement transmis au moteur. À confirmer.
5. **Pire cas mesuré 2 525 caractères** (5 conversations x 150 + 250) : le code ne correspond pas au plafond de 3 000 caractères tant que `max_chars` reste à 6 000. La troncature garde-fou reste à retester à 3 000.
6. **Non réalisé / hors capacité d'un agent** : la déclaration du SHA déployé, la vérification en ligne (normal, plafond atteint, question piège), le coût constaté, l'avis d'architecture. Aucun accès à la production.

## 5. Ce qui reste à faire

- Décider si le ticket doit être **clos** (fonction livrée) ou **rouvert** pour les écarts 1 à 4.
- Rejouer les tests sur un venv complet (CI) pour confirmer que les 4 échecs viennent de `requests`.
- Si l'écart de plafond est confirmé : un nouveau ticket ciblé (`max_chars=3000`, tests, note d'architecture).
- Lancer `scripts/recette_en_ligne_kan84_kan85.py` en ligne et consigner le coût mesuré.

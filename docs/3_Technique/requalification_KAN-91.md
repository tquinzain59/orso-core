# Requalification KAN-91 — alerte Stripe « intégration dépréciée »

> **Verdict : aucune correction de code n'est justifiée.** Le ticket demande de « remplacer tout usage de jeton ou de source en ligne », or le dépôt `orso-core` n'en contient aucun. Conformément à la consigne d'étape 0, aucun commit de correction n'est produit ; ce rapport en tient lieu. Le ticket reste **ouvert** : son vrai objet (retrouver qui parle au compte alerté avec une API héritée) est hors de ce dépôt.

- Branche / SHA examinés : `KAN-91-auto` @ `c13b03698c` (aucun écart avec `main`/`origin/main`).
- Date de l'analyse : 2026-10-15.

## 1. Ce que le ticket affirme

1. Le seul appelant Stripe du dépôt est `olympe/ops_manager.py` (lignes 22, 1941, 2321, 2361, 2373, 2385, 2411, 2434), « dernier commit : `0986522e78` du 01/10/2026 ».
2. Ce fichier est sur le chemin moderne (Customers sans source, SetupIntent, attache de PaymentMethod, Subscription) : aucun appel Charges, aucun jeton, aucune source en ligne.
3. L'alerte (compte `ORSO-AGENTS`) ne vient donc pas de ce fichier « ou pas de lui seul » ; la clef du serveur d'exploitation désigne un autre compte (test).
4. Correction attendue : remplacer tout jeton / source en ligne par Payment Methods + Payment Intents.

## 2. Ce que le code fait réellement

### 2.1 Prémisse **partiellement fausse** (références périmées, conclusion de fond confirmée)

| Affirmation du ticket | Constat |
|---|---|
| Lignes 22/1941/2321/2361/2373/2385/2411/2434 de `ops_manager.py` | Périmées. Les appels sont aujourd'hui aux lignes 2349, 2931, 2943, 2955, 2981, 2987, 3004 ; la clef est lue aux lignes 271 et 2891 ; la table de prix est ligne 25 (commentaire de compte ligne 24). Le fichier a évolué depuis le ticket (3 025 lignes). |
| Dernier commit sur le fichier : `0986522e78` du 01/10 | Faux. `0986522e78` (2026-10-01) **ne touche pas** `ops_manager.py` mais `hermes_cli/web_routers/client_ui.py`. Dernier commit sur `ops_manager.py` : `f490d7b695` (2026-10-05). |
| `ops_manager.py` est le seul appelant Stripe | **Faux.** Trois fichiers appellent `api.stripe.com` : `olympe/ops_manager.py`, `hermes_cli/web_routers/client_ui.py` (13 sites d'appel, absents du ticket) et `scripts/iam/bootstrap_stripe_products.py` (4 sites). |
| Aucun appel Charges / jeton / source en ligne | **Confirmé** pour les trois fichiers (voir §3, recherche 4). |
| Clef lue dans `STRIPE_SECRET_KEY`, jamais en dur | **Confirmé** pour les trois fichiers. `STRIPE_TEST_SECRET_KEY` n'apparaît **nulle part** dans le dépôt (recherche 7). |

### 2.2 Inventaire des appels à l'API Stripe (CA1)

Tous passent par un wrapper HTTP (`urllib`) vers `https://api.stripe.com/v1/<endpoint>` ; aucun SDK `stripe` n'est importé. Ressources utilisées : `customers`, `subscriptions`, `setup_intents`, `payment_methods` (lecture et `attach`), `invoices`, `billing_portal/sessions`, `products`, `prices`. **Aucune** ressource `charges`, `tokens` ou `sources`, et aucun champ `source=`, `card[...]`, `payment_method_data` n'est émis. Liste fichier:ligne complète en §3, recherches 4 et 5.

- Parcours d'empreinte bancaire : `olympe/ops_manager.py:2955` crée un **SetupIntent** (`automatic_payment_methods[enabled]=true`, `usage=off_session`) ; `:2981` attache un `payment_method_id` (`pm_…`) fourni par le client ; `:3004` crée l'abonnement avec `default_payment_method`. C'est le chemin moderne.
- `hermes_cli/web_routers/client_ui.py` : lecture client/abonnement/factures/moyens de paiement, mise à jour de prix d'abonnement avec prorata, session de portail de facturation. Aucune écriture de moyen de paiement.
- `scripts/iam/bootstrap_stripe_products.py` : création idempotente de produits et prix (outillage, exécution manuelle).

### 2.3 Variable de clef (CA3, partie dépôt)

- Le code attend `STRIPE_SECRET_KEY` (`ops_manager.py:271,2891`, `client_ui.py:2370`, `bootstrap_stripe_products.py:20`). Les deux fichiers compose injectent `STRIPE_SECRET_KEY=${STRIPE_SECRET_KEY:-}` (`docker-compose.olympe.yml:53`, `docker-compose.orso.yml:22`).
- Si le serveur d'exploitation ne définit que `STRIPE_TEST_SECRET_KEY` (assertion du ticket), **aucun code de ce dépôt ne la lit** : un conteneur démarré avec ce seul nom aurait une clef vide et lèverait `Clé secrète STRIPE_SECRET_KEY non configurée`. Soit la variable réellement injectée est `STRIPE_SECRET_KEY` (et la lecture du ticket sur le nom est inexacte), soit une autre couche (`.env` de déploiement, site/tunnel hors dépôt) porte la clef. **Non tranchable depuis le dépôt.**
- Repli fichier `.env` : `ops_manager.py:278` et `client_ui.py:2373-2379` relisent `STRIPE_SECRET_KEY=` depuis `.env`, `PROJECT_ROOT/.env`, `~/.hermes/.env` si l'environnement est vide. Cela peut faire désigner au processus une clef différente de celle de l'environnement du conteneur : à vérifier lors de l'inspection serveur.
- `STRIPE_PUBLISHABLE_KEY` est injectée (`docker-compose.orso.yml:23`) mais **consommée par aucun code** du dépôt.

### 2.4 Interface de saisie de carte

Aucune occurrence de `js.stripe.com`, `@stripe/stripe-js`, `loadStripe`, `elements`, `confirmSetup`, `confirmCard…`, `createPaymentMethod`, `createToken` dans `olympe/`, `hermes_cli/web_routers/`, `apps/`, `web/`, `templates/`, `scripts/` (recherche 6). **Le formulaire qui saisit la carte n'est pas dans ce dépôt.** C'est le candidat principal d'une intégration héritée (Elements/Checkout ancien, `createToken`, plugiciel tiers) et il n'a pas pu être couvert.

## 3. Preuves — commandes exactes et sorties brutes

Sorties brutes générées le 2026-10-15 (`cd` à la racine du dépôt). Les numéros de recherche cités plus haut correspondent à l'ordre des commandes ci-dessous (1 = SHA, 2 = historique du fichier, 3 = commit cité, 4 = `api.stripe.com`, 5 = sites d'appel, 6 = API héritées, 7 = Stripe.js, 8 = variables de clef, 9 = `STRIPE_TEST`, 10 = chemin moderne, 11 = ruff).

> Recherche « API héritées » : seules deux lignes remontent (`olympe/lifecycle_manager.py:379-380`, variable `src_profiles`) ; ce sont des **faux positifs** sans lien avec Stripe. Un commit historique (`3dbdb8704a`) contient la chaîne `tok_alert_50h`, identifiant de test d'alerte, également sans lien avec Stripe.

```text
$ git rev-parse --abbrev-ref HEAD && git rev-parse --short HEAD
KAN-91-auto
c13b03698c
[rc=0]

$ git log -n 3 --format='%h %ad %s' --date=short -- olympe/ops_manager.py | cut -c1-110
f490d7b695 2026-10-05 [KAN-58] fix(olympe): retrait absolu du secret de repli, refus explicite ERR_DASHBOARD_A
dae6b93df8 2026-10-05 [KAN-45] Merge PR #18: persistance SQL reelle des tenants/leads, durcissement contact et
665bd940c6 2026-10-02 [KAN-59] POC : quotas de ressources et refus de provisioning au-dela de la capacite de l
[rc=0]

$ git show -s --format='%h %ad' --date=short 0986522e78 && git show --stat --format= 0986522e78 | grep -E 'ops_manager|client_ui' | cut -c1-90
0986522e78 2026-10-01
 hermes_cli/web_routers/client_ui.py                |  98 ++++----
[rc=0]

$ git grep -nE 'api\.stripe\.com' -- '*.py' '*.ts' '*.tsx' '*.js' '*.sh' ':!website' ':!hermes_cli/tui_dist'
hermes_cli/web_routers/client_ui.py:2390:    url = f"https://api.stripe.com/v1/{endpoint}"
olympe/ops_manager.py:2895:        url = f"https://api.stripe.com/v1/{endpoint}"
scripts/iam/bootstrap_stripe_products.py:55:    url = f"https://api.stripe.com/v1/{endpoint}"
[rc=0]

$ git grep -nE '_stripe_request\(|[^_]stripe_request\(' -- '*.py' ':!tests' | grep -v 'def '
hermes_cli/web_routers/client_ui.py:2788:            cust_res = _stripe_request(f"customers?email={urllib.parse.quote(clean_email)}&limit=1")
hermes_cli/web_routers/client_ui.py:2796:                new_cust = _stripe_request("customers", method="POST", data={
hermes_cli/web_routers/client_ui.py:2807:                sub_res = _stripe_request(f"subscriptions?customer={stripe_customer_id}&limit=1")
hermes_cli/web_routers/client_ui.py:2831:                pm_res = _stripe_request(f"payment_methods?customer={stripe_customer_id}&type=card&limit=1")
hermes_cli/web_routers/client_ui.py:2840:                    sepa_res = _stripe_request(f"payment_methods?customer={stripe_customer_id}&type=sepa_debit&limit=1")
hermes_cli/web_routers/client_ui.py:2847:                inv_res = _stripe_request(f"invoices?customer={stripe_customer_id}&limit=10")
hermes_cli/web_routers/client_ui.py:2957:            cust_res = _stripe_request(f"customers?email={urllib.parse.quote(user_email.strip().lower())}&limit=1")
hermes_cli/web_routers/client_ui.py:2961:                sub_res = _stripe_request(f"subscriptions?customer={customer_id}&limit=1")
hermes_cli/web_routers/client_ui.py:2967:                    _stripe_request(
hermes_cli/web_routers/client_ui.py:3068:    cust_res = _stripe_request(f"customers?email={urllib.parse.quote(clean_email)}&limit=1")
hermes_cli/web_routers/client_ui.py:3074:        new_cust = _stripe_request("customers", method="POST", data={
hermes_cli/web_routers/client_ui.py:3085:        portal_res = _stripe_request(
hermes_cli/web_routers/client_ui.py:3116:            inv = _stripe_request(f"invoices/{invoice_id}")
olympe/ops_manager.py:2349:                live_sub_data = self._stripe_request(f"subscriptions/{sub_id}")
olympe/ops_manager.py:2931:        cust_search = self._stripe_request(f"customers?email={urllib.parse.quote(clean_email)}&limit=1")
olympe/ops_manager.py:2943:            new_cust = self._stripe_request("customers", method="POST", data=cust_payload)
olympe/ops_manager.py:2955:        setup_intent = self._stripe_request("setup_intents", method="POST", data=si_payload)
olympe/ops_manager.py:2981:            self._stripe_request(f"payment_methods/{payment_method_id}/attach", method="POST", data={"customer": customer_id})
olympe/ops_manager.py:2987:            self._stripe_request(
olympe/ops_manager.py:3004:        sub = self._stripe_request("subscriptions", method="POST", data=sub_payload)
scripts/iam/bootstrap_stripe_products.py:79:    existing_products_resp = stripe_request("products?limit=100")
scripts/iam/bootstrap_stripe_products.py:87:    existing_prices_resp = stripe_request("prices?limit=100&active=true")
scripts/iam/bootstrap_stripe_products.py:108:            prod = stripe_request("products", method="POST", data=prod_payload)
scripts/iam/bootstrap_stripe_products.py:124:            price = stripe_request("prices", method="POST", data=price_payload)
[rc=0]

$ git grep -nE 'v1/(charges|tokens|sources)|"(charges|tokens|sources)(\?|/)|stripe\.(Charge|Token|Source)|createToken\(|createSource|["'\'' ](tok|src)_[A-Za-z0-9]{8,}|payment_method_data|card\[(number|cvc|exp)' -- olympe hermes_cli/web_routers scripts apps web docker-compose.orso.yml docker-compose.olympe.yml deploy templates ':!hermes_cli/tui_dist' ':!**/dist/**' ':!**/node_modules/**'
olympe/lifecycle_manager.py:379:            src_profiles = (source_template_dir / "profiles") if source_template_dir else (project_root / "profiles")
olympe/lifecycle_manager.py:380:            if src_profiles.is_dir():
[rc=0]

$ git grep -nE 'js\.stripe\.com|@stripe/stripe-js|loadStripe|stripe\.elements|confirmSetup|confirmPayment|confirmCard|createPaymentMethod' -- olympe hermes_cli/web_routers scripts apps web templates deploy docker-compose.orso.yml docker-compose.olympe.yml ':!**/dist/**'
[rc=1]

$ git grep -nE 'STRIPE_[A-Z_]+' -- olympe hermes_cli/web_routers scripts/iam docker-compose.orso.yml docker-compose.olympe.yml orso.env.example | cut -c1-120
docker-compose.olympe.yml:53:      - STRIPE_SECRET_KEY=${STRIPE_SECRET_KEY:-}
docker-compose.olympe.yml:54:      - STRIPE_WEBHOOK_SECRET=${STRIPE_WEBHOOK_SECRET:-}
docker-compose.orso.yml:22:      - STRIPE_SECRET_KEY=${STRIPE_SECRET_KEY:-}
docker-compose.orso.yml:23:      - STRIPE_PUBLISHABLE_KEY=${STRIPE_PUBLISHABLE_KEY:-}
hermes_cli/web_routers/client_ui.py:2370:    key = os.environ.get("STRIPE_SECRET_KEY", "").strip()
hermes_cli/web_routers/client_ui.py:2378:                        if line.startswith("STRIPE_SECRET_KEY="):
hermes_cli/web_routers/client_ui.py:2389:        raise ValueError("Clé secrète STRIPE_SECRET_KEY non configurée.")
hermes_cli/web_routers/client_ui.py:2410:TIER_STRIPE_PRICES: Dict[str, str] = {
hermes_cli/web_routers/client_ui.py:2821:                        for tid, pid in TIER_STRIPE_PRICES.items():
hermes_cli/web_routers/client_ui.py:2827:                    if meta_tier in TIER_STRIPE_PRICES:
hermes_cli/web_routers/client_ui.py:2943:    if req.tier_id not in TIER_STRIPE_PRICES:
hermes_cli/web_routers/client_ui.py:2944:        raise HTTPException(status_code=400, detail=f"Palier inconnu: {req.tier
hermes_cli/web_routers/client_ui.py:2947:    target_price_id = TIER_STRIPE_PRICES[req.tier_id]
olympe/ops_manager.py:25:TIER_STRIPE_PRICES = {
olympe/ops_manager.py:271:        self.stripe_secret_key = stripe_secret_key or os.environ.get("STRIPE_SECRET_KEY", "")
olympe/ops_manager.py:278:                            if line.startswith("STRIPE_SECRET_KEY="):
olympe/ops_manager.py:2891:        key = self.stripe_secret_key or os.environ.get("STRIPE_SECRET_KEY", "")
olympe/ops_manager.py:2893:            raise ValueError("Clé secrète STRIPE_SECRET_KEY non configurée.")
olympe/ops_manager.py:2973:        price_id = TIER_STRIPE_PRICES.get(tier_id)
olympe/ops_manager.py:2977:            price_id = TIER_STRIPE_PRICES.get(tier_key, "price_1UKJ6W06XM8Z6gbS5id4Hf0s")
olympe/server.py:605:    webhook_secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "").strip()
olympe/server.py:616:        _log.error("[SECURITY] STRIPE_WEBHOOK_SECRET non configuré en production.")
scripts/iam/bootstrap_stripe_products.py:20:STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "").strip()
scripts/iam/bootstrap_stripe_products.py:57:        "Authorization": f"Bearer {STRIPE_SECRET_KEY}",
[rc=0]

$ git grep -nI 'STRIPE_TEST' -- .
[rc=1]

$ git grep -nE 'setup_intents|automatic_payment_methods|payment_methods/|default_payment_method' -- olympe hermes_cli/web_routers | cut -c1-150
olympe/ops_manager.py:2950:            "automatic_payment_methods[enabled]": "true",
olympe/ops_manager.py:2955:        setup_intent = self._stripe_request("setup_intents", method="POST", data=si_payload)
olympe/ops_manager.py:2981:            self._stripe_request(f"payment_methods/{payment_method_id}/attach", method="POST", data={"customer": customer_i
olympe/ops_manager.py:2990:                data={"invoice_settings[default_payment_method]": payment_method_id},
olympe/ops_manager.py:2993:            _log.warning("Notice mise à jour default_payment_method client : %s", e)
olympe/ops_manager.py:3000:            "default_payment_method": payment_method_id,
[rc=0]

$ source .venv/bin/activate && ruff --version && ruff check olympe/ops_manager.py olympe/server.py hermes_cli/web_routers/client_ui.py scripts/iam/bootstrap_stripe_products.py
ruff 0.15.10
All checks passed!
[rc=0]
```

## 4. Statut des critères d'acceptation

| CA | Statut | Preuve / motif |
|---|---|---|
| CA1 — liste des appels Stripe, aucun appel hérité | **Couvert pour le dépôt** | §2.2 et §3 (recherches 4, 5, 6). Liste plus large que celle du ticket (3 fichiers). Valable pour `c13b03698c`, branche courante uniquement. |
| CA2 — origine de l'alerte | **Absence prouvée dans le dépôt ; origine non trouvée** | Aucun appel hérité dans le code courant. Angles morts : voir §5. |
| CA3 — clef du compte ORSO-AGENTS en exploitation | **Non vérifié** | Exige un accès au serveur d'exploitation, au déploiement du site/tunnel et à l'API Stripe (lecture seule). Seule la moitié « dépôt » est établie (§2.3). |
| CA4 — rôle des deux comptes, abonnements par compte | **Non vérifié** | Exige la lecture des abonnements dans chaque compte via l'API Stripe. Aucune clef n'est disponible ici et aucune ne doit entrer dans le dépôt. |
| CA5 — parcours de test, objet Stripe, journal sans dépréciation | **Non vérifié, sans objet côté code** | Aucune correction livrée. À exécuter après identification de la source réelle (§6). |
| CA6 — base et Stripe concordent (abonnements en double) | **Non vérifié** | Exige la lecture de la base de production et des deux comptes. |

## 5. Angles morts nommés (CA2)

1. **Interface de saisie de carte** : absente du dépôt (§2.4). Si elle vient d'un site, d'un tunnel ou d'un plugiciel hébergé ailleurs, c'est la piste n°1 (jeton ou source en ligne côté navigateur).
2. **Déploiement du site et du tunnel d'abonnement** : sa configuration d'environnement (clef réellement injectée, version d'API) n'est pas dans ce dépôt.
3. **Autres dépôts** de l'organisation (site vitrine, tunnel, services tiers) : non examinés, aucun accès depuis ce dépôt.
4. **Gestes manuels** dans le tableau de bord Stripe ou outils tiers (import, Payment Links, Zapier, etc.) : invisibles par construction.
5. **Autres branches et historique** : seule la branche courante est inspectée pour les occurrences ; l'historique n'a été sondé que par `git log -S/-G` sur les motifs Stripe (aucun appel hérité retrouvé ; sortie brute dans l'annexe en fin de document).
6. **Clef présente dans l'environnement du serveur ou dans un `.env` repli** (§2.3) : non lisible depuis ici.
7. **Version d'API** : le wrapper n'envoie pas d'en-tête `Stripe-Version` ; la version est celle par défaut du compte. Sans lien établi avec l'alerte, mentionné pour mémoire.

## 6. Ce qui reste à faire (hors dépôt, décisions de Thibaut)

1. **Lire** la liste des abonnements dans **chacun** des deux comptes (lecture seule) avant toute modification du tunnel : tranche CA4 et CA6.
2. **Inspecter le serveur d'exploitation et le déploiement du site/tunnel** (nom de variable, valeur masquée, composant porteur, date de mise en service) ; appeler `GET /v1/account` avec la clef trouvée pour obtenir l'identifiant de compte (CA3). L'identifiant à comparer se prend **dans la console Stripe**, pas dans une image (cf. ticket : un caractère O/0 diffère).
3. **Obtenir la source de l'alerte** : dans le tableau de bord Stripe du compte alerté, consulter le journal des requêtes / la page des API héritées pour identifier la clef, l'endpoint et la date des appels `charges`/`customers` avec `source`/jeton ; en déduire le composant fautif.
4. Si le formulaire de carte est un composant externe : le migrer vers Elements/SetupIntent (le `client_secret` est déjà renvoyé par `olympe/ops_manager.py:2958-2963`) ou contacter l'éditeur du plugiciel.
5. **Tolérance dans les politiques d'API** : non recommandée (le ticket le dit) ; si elle est activée pour l'essai en cours, la dater dans le ticket avec un ticket de fermeture lié.
6. Après correction à la vraie source : rejouer un parcours de test complet (CA5) et relire les deux comptes (CA6).

Durcissement optionnel côté dépôt, **non appliqué** car non lié à l'alerte et hors périmètre de ce rapport : valider que `payment_method_id` commence par `pm_` dans `olympe/server.py` (modèle ligne ~161) afin de rejeter explicitement tout `tok_…`/`src_…` qui arriverait d'un formulaire hérité, et le journaliser. À ouvrir en sous-ticket si le PO le souhaite.

## 7. Contrôle mécanique

`ruff check` sur les quatre fichiers qui touchent à Stripe : `All checks passed!`, code retour 0 (sortie brute en §3, recherche 11). Aucun fichier de code n'a été modifié ; seul ce document est ajouté.

## 8. Contraintes respectées

Aucun secret lu ni écrit, aucune clef ou identifiant client réel dans ce document, aucune écriture sur un compte Stripe, aucune modification du sanctuaire, pas de `git push`, `main` non touchée.

### Annexe — historique (commande 12, toutes branches, fichiers Stripe + tests facturation)
```text
$ git log --all --oneline -G'v1/charges|stripe\.Charge|stripe\.Token|createToken|createSource|tok_[a-z]+|payment_method_data|"source": *"(tok|src)_|/sources' -- olympe/ops_manager.py hermes_cli/web_routers/client_ui.py scripts/iam/bootstrap_stripe_products.py olympe/server.py tests/olympe tests/hermes_cli/test_client_settings_billing.py
3dbdb8704a feat(olympe): conformité KAN-104 mailer Brevo et notifications onboarding
[rc=0]
$ git show 3dbdb8704a | grep -nE "^\+.*tok_[a-z]+" | cut -c1-120
1038:+            ("tok_alert_50h", "tenant-alert", "boss@alert.fr", old_time, old_time),
```

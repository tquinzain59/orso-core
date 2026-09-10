#!/usr/bin/env bash
# probe-api-urls.sh — Tester systématiquement les URLs d'API candidates d'un éditeur de logiciel.
#
# Usage : ./probe-api-urls.sh <domaine-editeur>
# Exemple : ./probe-api-urls.sh tiime.fr
#
# Teste un ensemble d'URLs candidates (site, /api, /developers, /docs, sous-domaines api./developer./docs.)
# et affiche le code HTTP de chacune. Utilise un User-Agent navigateur et suit les redirections (-L).
#
# Interprétation :
#   200  = page existe (récupérer le contenu et chercher api/oauth/swagger/openapi)
#   403  = souvent Cloudflare/anti-bot (l'API existe peut-être — vérifier via navigateur)
#   404  = page n'existe pas
#   000  = DNS injoignable / connexion refusée

set -euo pipefail

DOMAIN="${1:-}"
if [[ -z "$DOMAIN" ]]; then
  echo "Usage: $0 <domaine-editeur> (ex: tiime.fr, pappers.fr, pennylane.com)" >&2
  exit 1
fi

UA="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"

# Strip leading www. for subdomain construction
BASE="${DOMAIN#www.}"

urls=(
  "https://www.${BASE}"
  "https://${BASE}"
  "https://www.${BASE}/api"
  "https://${BASE}/api"
  "https://www.${BASE}/developers"
  "https://${BASE}/developers"
  "https://www.${BASE}/developer"
  "https://${BASE}/developer"
  "https://www.${BASE}/integrations"
  "https://${BASE}/integrations"
  "https://www.${BASE}/developpeurs"
  "https://${BASE}/developpeurs"
  "https://www.${BASE}/docs"
  "https://${BASE}/docs"
  "https://www.${BASE}/documentation"
  "https://${BASE}/documentation"
  "https://api.${BASE}"
  "https://developer.${BASE}"
  "https://developers.${BASE}"
  "https://docs.${BASE}"
  "https://doc.${BASE}"
  "https://help.${BASE}"
)

echo "=== Probing API URLs for ${BASE} ==="
echo "(UA: ${UA})"
echo

for url in "${urls[@]}"; do
  code=$(curl -sS -o /dev/null -w "%{http_code}" -L --max-time 15 -A "$UA" "$url" 2>/dev/null || echo "ERR")
  printf "%-5s %s\n" "$code" "$url"
done

echo
echo "=== Pour les URLs en 200, récupérer le contenu et chercher les indices d'API : ==="
echo "# Exemple :"
echo "# curl -sSL --max-time 20 -A '${UA}' 'https://www.${BASE}/api' | \\"
echo "#   sed -e 's/<[^>]*>//g' | grep -iE 'api|oauth|token|rest|endpoint|sandbox|swagger|openapi'"
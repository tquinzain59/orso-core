#!/bin/sh
set -e

# ==============================================================================
# Orso Agents - Entrypoint de Démarrage Sécurisé
# ==============================================================================

echo "==> [Orso Entrypoint] Démarrage du conteneur Orso Agents..."

# 1. Préparation et sécurisation des répertoires inscriptibles dans /app/data
mkdir -p /app/data/hermes_home \
         /app/data/agents \
         /app/data/reports \
         /app/data/telemetry \
         /app/config

# Si le conteneur démarre avec les droits root, fixer les permissions pour orso (UID 10001)
if [ "$(id -u)" = "0" ]; then
    chown -R orso:orso /app/data /app/config 2>/dev/null || true
    chmod -R 775 /app/data 2>/dev/null || true
fi

# 2. Vérification et initialisation de la configuration par défaut
if [ ! -f /app/config/hermes.yaml ] && [ -f /app/config/hermes.default.yaml ]; then
    echo "==> [Orso Entrypoint] Aucun hermes.yaml détecté. Initialisation depuis hermes.default.yaml..."
    cp /app/config/hermes.default.yaml /app/config/hermes.yaml
    if [ "$(id -u)" = "0" ]; then
        chown orso:orso /app/config/hermes.yaml 2>/dev/null || true
    fi
fi

# 3. Contrôle de diagnostic sur les montages en lecture seule
check_readable() {
    target_dir="$1"
    dir_name="$2"
    if [ -d "$target_dir" ]; then
        if ! ls "$target_dir" >/dev/null 2>&1; then
            echo "[ALERTE PERMISSION] Le dossier monté '$dir_name' ($target_dir) n'est pas lisible par l'utilisateur du conteneur."
            echo "                     Exécutez sur l'hôte : sudo chmod -R a+rX .$dir_name"
        fi
    fi
}

check_readable "/app/profiles" "/profiles"
check_readable "/app/skills" "/skills"
check_readable "/app/templates" "/templates"

# Vérification spécifique sur le profil de Jérôme si présent
if [ -d "/app/profiles/jerome" ] && [ ! -r "/app/profiles/jerome/SOUL.md" ] && [ -f "/app/profiles/jerome/SOUL.md" ]; then
    echo "[ALERTE PERMISSION] Le fichier /app/profiles/jerome/SOUL.md n'a pas les droits de lecture suffisants."
    echo "                     Exécutez sur l'hôte : sudo chmod -R a+rX ./profiles"
fi

# 4. Définition explicite de HERMES_HOME vers le volume persistant
export HERMES_HOME="${HERMES_HOME:-/app/data/hermes_home}"
export HERMES_CONFIG_PATH="${HERMES_CONFIG_PATH:-/app/config/hermes.yaml}"

echo "==> [Orso Entrypoint] HERMES_HOME configuré sur : $HERMES_HOME"
echo "==> [Orso Entrypoint] HERMES_CONFIG_PATH : $HERMES_CONFIG_PATH"

# 5. Exécution de la commande
if [ "$(id -u)" = "0" ]; then
    # Drop de privilèges vers l'utilisateur applicatif non-root 'orso'
    exec gosu orso "$@"
else
    # Déjà exécuté en tant que non-root
    exec "$@"
fi

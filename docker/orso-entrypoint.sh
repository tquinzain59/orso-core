#!/bin/sh
set -e
umask 0002

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
    if [ -d "/app/profiles" ]; then
        # R2, CA2: Propriété root:root, mode 0555 répertoires et 0444 fichiers
        chown -R root:root /app/profiles 2>/dev/null || true
        chmod -R 0555 /app/profiles 2>/dev/null || true
        find /app/profiles -type f -exec chmod 0444 {} + 2>/dev/null || true
    fi
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

# Liaison des profils pour la découverte multi-profils Hermès
mkdir -p /home/orso/.hermes /app/data/hermes_home
if [ -d /app/profiles ]; then
    # Si /app/data/hermes_home/profiles n'existe pas, n'est pas un symlink, ou est un dossier vide
    if [ ! -e /app/data/hermes_home/profiles ] || [ ! -L /app/data/hermes_home/profiles -a -z "$(ls -A /app/data/hermes_home/profiles 2>/dev/null)" ]; then
        rm -rf /app/data/hermes_home/profiles
        ln -sfn /app/profiles /app/data/hermes_home/profiles
    fi
fi
if [ ! -e /home/orso/.hermes/profiles ]; then
    ln -sfn /app/data/hermes_home/profiles /home/orso/.hermes/profiles 2>/dev/null || ln -sfn /app/profiles /home/orso/.hermes/profiles
fi
if [ "$(id -u)" = "0" ]; then
    chown -h orso:orso /home/orso/.hermes/profiles /app/data/hermes_home/profiles 2>/dev/null || true
    chown -R orso:orso /home/orso/.hermes /app/data/hermes_home 2>/dev/null || true
    chmod -R 775 /app/data/hermes_home 2>/dev/null || true
fi

echo "==> [Orso Entrypoint] HERMES_HOME configuré sur : $HERMES_HOME"
echo "==> [Orso Entrypoint] HERMES_CONFIG_PATH : $HERMES_CONFIG_PATH"

# 4bis. Contrôle d'intégrité cryptographique des personas (KAN-33, R3, R4, R6, R7)
# Purge préventive de tout SOUL.md illégitime dans les répertoires de données inscriptibles (faille de repli ambient)
rm -f /app/data/hermes_home/SOUL.md /app/data/SOUL.md /home/orso/.hermes/SOUL.md ./data/hermes_home/SOUL.md ./data/SOUL.md 2>/dev/null || true

echo "==> [Orso Entrypoint] Contrôle d'intégrité des personas (KAN-33)..."
INTEGRITY_SCRIPT="/app/scripts/security/persona_integrity.py"
if [ ! -f "$INTEGRITY_SCRIPT" ] && [ -f "./scripts/security/persona_integrity.py" ]; then
    INTEGRITY_SCRIPT="./scripts/security/persona_integrity.py"
fi

if [ -f "$INTEGRITY_SCRIPT" ]; then
    if ! python3 "$INTEGRITY_SCRIPT" verify --fail-fast; then
        echo "🚨 [PER-INTEGRITY-001] Échec critique d'intégrité des personas au démarrage. Arrêt immédiat." >&2
        exit 1
    fi
    echo "==> [Orso Entrypoint] Intégrité des personas validée (PER-INTEGRITY-000)."
    echo "==> [Orso Entrypoint] Démarrage du moniteur d'intégrité périodique (300s)..."
    python3 "$INTEGRITY_SCRIPT" monitor --interval 300 &
fi

# 5. Exécution de la commande
if [ "$(id -u)" = "0" ]; then
    # Drop de privilèges vers l'utilisateur applicatif non-root 'orso'
    exec gosu orso "$@"
else
    # Déjà exécuté en tant que non-root
    exec "$@"
fi

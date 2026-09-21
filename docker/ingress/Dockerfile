# ==============================================================================
# ORSO AGENTS - DOCKERFILE INGRESS REVERSE PROXY (OPTION B)
# ==============================================================================
FROM nginx:alpine

# Copie de la configuration d'aiguillage Ingress
COPY docker/ingress/nginx.ingress.conf /etc/nginx/conf.d/default.conf

# Copie du bundle de l'UI Client compilé (dist)
COPY apps/ui-client/dist /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]

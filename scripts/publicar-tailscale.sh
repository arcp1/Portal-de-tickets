#!/usr/bin/env bash
#
# Publica el portal en internet a traves de Tailscale Funnel.
#
# Funnel termina el TLS con un certificado de Let's Encrypt y reenvia a NGINX,
# que escucha SOLO en 127.0.0.1:8080. Esa es la parte que importa: si NGINX se
# publicara tambien hacia la red, cualquiera podria mandar su propia cabecera
# X-Forwarded-For, declararse la IP que quisiera y saltarse el limitador de
# intentos de activacion, que solo cuenta por IP.
#
# Uso:   sudo ./scripts/publicar-tailscale.sh
# Quitar: sudo ./scripts/publicar-tailscale.sh --quitar

set -euo pipefail

PUERTO_LOCAL=8080
RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ "${1:-}" = "--quitar" ]; then
    echo "[portal] Retirando la publicacion..."
    tailscale funnel --https=443 off || true
    tailscale serve reset || true
    echo "[portal] El portal ya no es accesible desde internet."
    echo "[portal] NGINX sigue escuchando en 127.0.0.1:${PUERTO_LOCAL} (solo este equipo)."
    exit 0
fi

if [ "$(id -u)" -ne 0 ]; then
    echo "Este script necesita root para configurar Tailscale." >&2
    echo "  sudo $0" >&2
    exit 1
fi

echo "[portal] 1/4 Comprobando que el portal responde en local..."
if ! curl -sf -m 10 -o /dev/null "http://127.0.0.1:${PUERTO_LOCAL}/"; then
    echo "ERROR: nada responde en 127.0.0.1:${PUERTO_LOCAL}." >&2
    echo "       Levante el portal primero:  docker compose up -d" >&2
    exit 1
fi
echo "        responde."

echo "[portal] 2/4 Publicando por Funnel..."
tailscale funnel --bg --https=443 "http://127.0.0.1:${PUERTO_LOCAL}"

echo "[portal] 3/4 Esperando el certificado de Let's Encrypt (puede tardar)..."
DOMINIO="$(tailscale status --json | python3 -c 'import sys,json;print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))')"
URL="https://${DOMINIO}"
for _ in $(seq 1 30); do
    sleep 4
    if curl -sf -m 10 -o /dev/null "${URL}/"; then break; fi
done

echo "[portal] 4/4 Comprobando..."
CODIGO="$(curl -s -m 15 -o /dev/null -w '%{http_code}' "${URL}/")"
echo
echo "  URL publica : ${URL}"
echo "  HTTP        : ${CODIGO}"
echo
tailscale funnel status
echo
echo "  Para retirarlo:  sudo $0 --quitar"

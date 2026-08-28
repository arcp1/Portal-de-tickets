#!/bin/sh
#
# Elige la configuración de nginx según haya certificado o no.
#
# La idea es que activar TLS no requiera tocar archivos: se dejan el .crt y el
# .key en nginx/certs y al reiniciar el portal ya está en HTTPS. Si no están,
# arranca en HTTP como siempre, para no dejar el portal caído por un detalle
# de configuración.
#
# TLS_ACTIVO controla eso:
#   auto (por omisión)  HTTPS si hay certificado, HTTP si no.
#   off                 HTTP siempre, aunque haya certificado.
#
# El "off" existe para poder dar marcha atrás en un minuto. Un certificado
# autofirmado hace que el navegador avise, y si eso pasa el primer día que 300
# personas entran al portal, la conclusión de todas va a ser "no sirve". Mejor
# tener el interruptor a la mano que descubrirlo sin él.

set -e

CERT=/etc/nginx/certs/portal.crt
LLAVE=/etc/nginx/certs/portal.key
DESTINO=/etc/nginx/conf.d/default.conf
TLS_ACTIVO="${TLS_ACTIVO:-auto}"

if [ "$TLS_ACTIVO" = "off" ]; then
    echo "[portal] TLS_ACTIVO=off: se sirve por HTTP aunque haya certificado."
    cp /etc/nginx/plantillas/http.conf "$DESTINO"
elif [ -s "$CERT" ] && [ -s "$LLAVE" ]; then
    echo "[portal] Certificado encontrado: se sirve por HTTPS y el 80 redirige."
    cp /etc/nginx/plantillas/https.conf "$DESTINO"
else
    echo "[portal] AVISO: sin certificado en $CERT."
    echo "[portal] El portal arranca en HTTP: las contraseñas viajan en claro."
    echo "[portal] Para activar TLS: ./scripts/generar-certificado.sh"
    cp /etc/nginx/plantillas/http.conf "$DESTINO"
fi

exec nginx -g 'daemon off;'

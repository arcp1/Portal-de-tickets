#!/bin/sh
# Arma el archivo de contraseñas de Mosquitto a partir del .env y arranca.
#
# El archivo vive en un tmpfs (/mosquitto/run): no queda en disco ni en el
# repositorio, y se rehace en cada arranque, así que cambiar una contraseña es
# cambiarla en el .env y `docker compose up -d mosquitto`.
set -eu
umask 077

: "${MQTT_PASSWORD:?falta MQTT_PASSWORD en el .env}"
: "${MQTT_DISPOSITIVO_PASSWORD:?falta MQTT_DISPOSITIVO_PASSWORD en el .env}"

receptor="${MQTT_USUARIO:-portal}"
sensores="${MQTT_DISPOSITIVO_USUARIO:-sensor}"
# Los nombres van dentro del ACL: solo letras, números, guion y guion bajo,
# y distintos entre sí (con el mismo nombre, los sensores podrían leer).
for nombre in "$receptor" "$sensores"; do
    case "$nombre" in
        ''|*[!A-Za-z0-9_-]*) echo "Nombre de usuario MQTT no válido: '$nombre'" >&2; exit 1 ;;
    esac
done
if [ "$receptor" = "$sensores" ]; then
    echo "MQTT_USUARIO y MQTT_DISPOSITIVO_USUARIO deben ser distintos" >&2
    exit 1
fi

archivo=/mosquitto/run/passwd
rm -f "$archivo"
touch "$archivo"
mosquitto_passwd -b "$archivo" "$receptor" "$MQTT_PASSWORD"
mosquitto_passwd -b "$archivo" "$sensores" "$MQTT_DISPOSITIVO_PASSWORD"

# El ACL sale de la plantilla con los nombres del .env. Además, la copia vive
# aquí porque Mosquitto exige que sea suya y privada, y la montada es del host.
sed -e "s/{{RECEPTOR}}/$receptor/" -e "s/{{SENSORES}}/$sensores/" \
    /mosquitto/config/acl > /mosquitto/run/acl

exec mosquitto -c /mosquitto/config/mosquitto.conf

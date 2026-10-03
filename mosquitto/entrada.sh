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

archivo=/mosquitto/run/passwd
rm -f "$archivo"
touch "$archivo"
mosquitto_passwd -b "$archivo" "${MQTT_USUARIO:-portal}" "$MQTT_PASSWORD"
mosquitto_passwd -b "$archivo" "${MQTT_DISPOSITIVO_USUARIO:-sensor}" "$MQTT_DISPOSITIVO_PASSWORD"

# El ACL va montado desde el repositorio (dueño y permisos del host);
# Mosquitto exige que sea suyo y privado, así que se usa una copia.
cp /mosquitto/config/acl /mosquitto/run/acl

exec mosquitto -c /mosquitto/config/mosquitto.conf

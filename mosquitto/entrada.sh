#!/bin/sh
# Arma el archivo de contraseñas de Mosquitto a partir del .env y arranca.
#
# El archivo vive en un tmpfs (/mosquitto/run): no queda en disco ni en el
# repositorio, y se rehace en cada arranque, así que cambiar una contraseña es
# cambiarla en el .env y `docker compose up -d mosquitto`.
#
# Dos clases de cuenta para los ESP32, y pueden convivir mientras se migra:
#
#   MQTT_DISPOSITIVO_PASSWORD  una para todos (la de siempre). Quien la tiene
#                              —basta con escucharla en la red, viaja en claro—
#                              publica en nombre de cualquier equipo y planta.
#   MQTT_SENSORES              una por equipo: "CLAVE_EQUIPO:contraseña",
#                              separadas por espacios o comas. El usuario es la
#                              clave del equipo y el ACL (`%u`) solo le deja
#                              publicar en su propio tema.
#
# Con todos los equipos migrados, vaciar MQTT_DISPOSITIVO_PASSWORD retira la
# cuenta compartida.
set -eu
umask 077

: "${MQTT_PASSWORD:?falta MQTT_PASSWORD en el .env}"
compartida="${MQTT_DISPOSITIVO_PASSWORD:-}"
por_equipo="${MQTT_SENSORES:-}"
if [ -z "$compartida" ] && [ -z "$por_equipo" ]; then
    echo "Sin cuentas para los sensores: ponga MQTT_SENSORES (una por equipo)" \
         "o MQTT_DISPOSITIVO_PASSWORD (compartida) en el .env" >&2
    exit 1
fi

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
if [ -n "$compartida" ]; then
    mosquitto_passwd -b "$archivo" "$sensores" "$compartida"
fi

# Las cuentas por equipo. Los mensajes de error nunca repiten la entrada
# entera: llevaría la contraseña al registro del contenedor.
set -f   # sin comodines: una contraseña con * no se expande
for par in $(printf '%s' "$por_equipo" | tr ',' ' '); do
    case "$par" in
        ?*:?*) ;;
        *) echo "MQTT_SENSORES: hay una entrada sin la forma CLAVE_EQUIPO:contraseña" >&2; exit 1 ;;
    esac
    nombre="${par%%:*}"
    clave="${par#*:}"
    # La misma regla que el tema que acepta el portal (iot_service.TEMA).
    case "$nombre" in
        *[!A-Za-z0-9_-]*) echo "MQTT_SENSORES: clave de equipo no válida: '$nombre'" >&2; exit 1 ;;
    esac
    if [ "${#nombre}" -gt 64 ]; then
        echo "MQTT_SENSORES: clave de equipo de más de 64 caracteres: '$nombre'" >&2; exit 1
    fi
    if [ "$nombre" = "$receptor" ] || [ "$nombre" = "$sensores" ]; then
        echo "MQTT_SENSORES: '$nombre' choca con MQTT_USUARIO o MQTT_DISPOSITIVO_USUARIO" >&2
        exit 1
    fi
    mosquitto_passwd -b "$archivo" "$nombre" "$clave"
done
set +f

# El ACL sale de la plantilla con los nombres del .env. Además, la copia vive
# aquí porque Mosquitto exige que sea suya y privada, y la montada es del host.
sed -e "s/{{RECEPTOR}}/$receptor/" -e "s/{{SENSORES}}/$sensores/" \
    /mosquitto/config/acl > /mosquitto/run/acl

exec mosquitto -c /mosquitto/config/mosquitto.conf

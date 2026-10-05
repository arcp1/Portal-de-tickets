#!/usr/bin/env bash
#
# Prueba la topología de redes y el reparto de secretos de docker-compose.yml en
# una copia desechable del portal, sin tocar producción.
#
#   scripts/prueba-aislamiento.sh                    levanta, comprueba y retira
#   CONSERVAR=1 scripts/prueba-aislamiento.sh        la deja arriba para mirarla
#   OLLAMA_IMAGEN=ollama/ollama:0.12.3 scripts/...   con otra versión de Ollama
#
# Si la imagen de Ollama de docker-compose.yml no está en el servidor, compose
# la descarga al levantar la copia (la 0.33.2 son ~3,4 GB).
#
# **No toca producción.** Proyecto `portal-prueba` (redes y volúmenes propios),
# contenedores `prueba_*`, puertos en 127.0.0.1 (18080, 18081, 11883) y un .env
# de prueba con secretos inventados, que se borra al terminar. Comparte con
# producción las imágenes y, en solo lectura, los modelos de Ollama.
#
# Sale con 0 si todo está bien y con 1 si algo falló; cada comprobación dice
# qué esperaba.

set -euo pipefail
cd "$(dirname "$0")/.."

PROYECTO=portal-prueba
TMP=$(mktemp -d)
chmod 700 "$TMP"
export PRUEBA_ENV="$TMP/env"
C=(docker compose -p "$PROYECTO" --env-file "$PRUEBA_ENV" -f docker-compose.yml -f docker-compose.prueba.yml)
FALLOS=0

ok()    { printf '  \033[32m✔\033[0m %s\n' "$1"; }
falla() { printf '  \033[31m✘\033[0m %s\n' "$1"; FALLOS=$((FALLOS + 1)); }
espera() {  # espera <descripción> <comando...>: ✔ si el comando sale bien
    local d=$1; shift
    if "$@" >/dev/null 2>&1; then ok "$d"; else falla "$d"; fi
}
no_debe() {  # no_debe <descripción> <comando...>: ✔ si el comando FALLA
    local d=$1; shift
    if "$@" >/dev/null 2>&1; then falla "$d (¡se pudo!)"; else ok "$d"; fi
}

retirar() {
    if [ "${CONSERVAR:-0}" = "1" ]; then
        echo
        echo "Copia conservada. Para retirarla:"
        echo "  PRUEBA_ENV=$PRUEBA_ENV ${C[*]} down --remove-orphans"
        echo "  docker volume ls -q --filter name=^${PROYECTO}_ | xargs -r docker volume rm"
        echo "  rm -rf $TMP"
        return
    fi
    echo
    echo "== Retirando la copia"
    "${C[@]}" down --remove-orphans >/dev/null 2>&1 || true
    # Solo los volúmenes de la prueba, por nombre. Nunca `down -v`: el de los
    # modelos es el de producción.
    docker volume ls -q --filter "name=^${PROYECTO}_" | xargs -r docker volume rm >/dev/null
    rm -rf "$TMP"
    echo "  hecho"
}
trap retirar EXIT

# --- 0. Antes de empezar ---------------------------------------------------
for puerto in 18080 18081 11883; do
    if [ -n "$(ss -tlnH "sport = :$puerto")" ]; then
        echo "El puerto $puerto ya está en uso: ¿quedó otra copia arriba?" >&2
        exit 1
    fi
done
docker volume inspect portal-de-tickets_ollama_models >/dev/null

# --- 1. El .env de prueba: el de producción con secretos inventados --------
python3 - "$PRUEBA_ENV" <<'PY'
import re, secrets, sys
destino = sys.argv[1]
nuevo = lambda n=32: secrets.token_urlsafe(n)
valores, orden = {}, []
for linea in open(".env", encoding="utf-8"):
    linea = linea.rstrip("\n")
    if "=" in linea and not linea.lstrip().startswith("#"):
        k, v = linea.split("=", 1)
        valores[k.strip()] = v
        orden.append(k.strip())
reales = {k: v for k, v in valores.items() if re.search(r"PASS|SECRET|KEY|TOKEN|SENSORES", k) and v}
app = nuevo(18)
cambios = {
    "POSTGRES_PASSWORD": nuevo(18),
    # La aplicación entra con su rol, no con el superusuario (M-2).
    "POSTGRES_APP_USER": "portal_app",
    "POSTGRES_APP_PASSWORD": app,
    "DATABASE_URL": f"postgresql://portal_app:{app}@db:5432/"
                    f"{valores.get('POSTGRES_DB', 'portal_tickets')}",
    "JWT_SECRET": nuevo(48),
    "REDIS_PASSWORD": nuevo(),
    "MQTT_PASSWORD": nuevo(),
    "MQTT_DISPOSITIVO_PASSWORD": nuevo(),
    "MQTT_SENSORES": f"esp-prueba:{nuevo(18)}",
    # Con valor, para ver a qué contenedores llegan; apagados, para no usarlos.
    "GEMINI_API_KEY": "prueba-no-es-una-llave",
    "GEMINI_HABILITADO": "false",
    "SMTP_PASSWORD": "prueba-no-es-una-clave",
    "SMTP_HOST": "",
    "NOTIFICACIONES_ACTIVAS": "false",
    "PORTAL_URL": "http://127.0.0.1:18080",
    "MQTT_PUBLICAR": "127.0.0.1:11883",
}
for k, v in cambios.items():
    if k not in valores:
        orden.append(k)
    valores[k] = v
texto = "".join(f"{k}={valores[k]}\n" for k in orden)
# Ningún secreto real puede quedar en la copia.
fugas = [k for k, v in reales.items() if len(v) >= 8 and v in texto]
if fugas:
    sys.exit(f"El .env de prueba conserva secretos reales: {fugas}")
with open(destino, "w", encoding="utf-8") as f:
    f.write(texto)
PY
chmod 600 "$PRUEBA_ENV"
leer() { grep "^$1=" "$PRUEBA_ENV" | cut -d= -f2-; }

# --- 2. Levantar -------------------------------------------------------------
echo "== Levantando la copia (proyecto $PROYECTO, Ollama ${OLLAMA_IMAGEN:-de docker-compose.yml})"
if ! "${C[@]}" up -d --wait --wait-timeout 300; then
    echo "La copia no llegó a estar sana:" >&2
    "${C[@]}" ps -a >&2
    exit 1
fi
for _ in $(seq 90); do
    # `grep -c` y no `-q`: con pipefail, cortar la tubería antes de tiempo la
    # da por fallida aunque haya encontrado el texto.
    docker logs prueba_backend 2>&1 | grep -c "Application startup complete" >/dev/null && break
    sleep 2
done
docker exec prueba_db psql -U "$(leer POSTGRES_USER)" -d "$(leer POSTGRES_DB)" -qc \
    "insert into sitios (clave, nombre, pais, activo) values ('QRO', 'Planta de prueba', 'México', true)
     on conflict (clave) do nothing;" >/dev/null

PY_OLLAMA='from app.services.ollama_client import ollama; import sys; sys.exit(0 if ollama.disponible() else 1)'
PY_EMBEDDING='from app.services.ollama_client import ollama; import sys; v = ollama.generar_embedding("la impresora no imprime", tarea="consulta"); sys.exit(0 if v else 1)'
PY_DB='from app.core.db import SessionLocal; from sqlalchemy import text; SessionLocal().execute(text("select 1"))'
PY_SALIDA='import socket; socket.create_connection(("1.1.1.1", 443), timeout=4)'
tcp() { docker exec "$1" sh -c "nc -z -w 2 $2 $3"; }                              # alpine
tcp_bash() { docker exec "$1" timeout 4 bash -c "</dev/tcp/$2/$3"; }             # debian/ubuntu

# --- 3. Lo que tiene que seguir funcionando ----------------------------------
echo
echo "== Lo que tiene que funcionar"
espera "nginx → frontend: la aplicación responde" \
    sh -c '[ "$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:18080/)" = 200 ]'
espera "nginx → backend: la API responde" \
    sh -c '[ "$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:18080/api/auth/requisitos-password)" = 200 ]'
espera "backend → base de datos: el login consulta y responde 401" \
    sh -c '[ "$(curl -s -o /dev/null -w "%{http_code}" -H "Content-Type: application/json" -d "{\"email\":\"nadie@prueba\",\"password\":\"x\"}" http://127.0.0.1:18080/api/auth/login)" = 401 ]'
espera "backend → Redis: el freno de login quedó anotado" \
    sh -c "docker exec prueba_redis redis-cli --no-auth-warning -a '$(leer REDIS_PASSWORD)' --scan --pattern 'lim:login*' | grep -q ."
espera "backend → Ollama: disponible" docker exec prueba_backend python -c "$PY_OLLAMA"
espera "backend → Ollama: calcula un embedding con los modelos de producción" \
    docker exec prueba_backend python -c "$PY_EMBEDDING"
espera "worker → Redis: su latido lo marca sano" \
    sh -c '[ "$(docker inspect -f "{{.State.Health.Status}}" prueba_worker)" = healthy ]'
espera "worker → base de datos" docker exec prueba_worker python -c "$PY_DB"
espera "worker → Ollama" docker exec prueba_worker python -c "$PY_OLLAMA"
docker run --rm --network host eclipse-mosquitto:2.0.22 mosquitto_pub -h 127.0.0.1 -p 11883 \
    -u esp-prueba -P "$(leer MQTT_SENSORES | cut -d: -f2-)" \
    -t portal/QRO/sensores/esp-prueba/telemetria -m '{"temperatura": 21.5, "humedad": 40}' >/dev/null 2>&1 || true
sleep 3
espera "sensor → Mosquitto → ingestor → base: la lectura quedó guardada" \
    sh -c "[ \"\$(docker exec prueba_db psql -U '$(leer POSTGRES_USER)' -d '$(leer POSTGRES_DB)' -Atc \"select count(*) from lecturas_iot l join dispositivos_iot d on d.id = l.dispositivo_id where d.clave = 'esp-prueba'\")\" = 1 ]"
espera "camino de Funnel: la IP de la planta entra" \
    sh -c '[ "$(curl -s -o /dev/null -w "%{http_code}" -H "X-Forwarded-For: 189.254.199.194" http://127.0.0.1:18081/)" = 200 ]'
espera "camino de Funnel: una IP ajena recibe 403" \
    sh -c '[ "$(curl -s -o /dev/null -w "%{http_code}" -H "X-Forwarded-For: 203.0.113.9" http://127.0.0.1:18081/)" = 403 ]'
espera "backend sale a internet (Gemini, correo)" docker exec prueba_backend python -c "$PY_SALIDA"
espera "worker sale a internet (correo)" docker exec prueba_worker python -c "$PY_SALIDA"

# --- 4. La base: la aplicación entra sin superusuario (M-2) -----------------
echo
echo "== Base de datos: menor privilegio"
# Una consulta con la conexión de la aplicación (la de DATABASE_URL), desde un
# archivo: así ninguna comilla del SQL depende de cómo se escape en el shell.
cat > "$TMP/sql_app.py" <<'PYSQL'
import sys
from sqlalchemy import text
from app.core.db import engine
with engine.connect() as conexion:
    print(conexion.execute(text(sys.argv[1])).scalar())
PYSQL
# Por la entrada estándar y no con `docker cp`: el contenedor es de solo lectura.
sql_app() { docker exec -i prueba_backend python - "$1" < "$TMP/sql_app.py" 2>/dev/null; }
sql_super() { docker exec prueba_db psql -U "$(leer POSTGRES_USER)" -d "$(leer POSTGRES_DB)" -Atc "$1"; }
app_sin_superusuario() {
    [ "$(sql_app "select current_user || ':' || (select rolsuper from pg_roles where rolname = current_user)::text")" = "portal_app:false" ]
}
tablas_de_la_app() { [ "$(sql_super "select count(*) from pg_tables where schemaname = 'public' and tableowner <> 'portal_app'")" = 0 ]; }
espera "la aplicación entra como portal_app, sin superusuario" app_sin_superusuario
espera "las migraciones crearon todas las tablas a su nombre" tablas_de_la_app
no_debe "la aplicación ejecuta un programa en la base (COPY ... PROGRAM)" sql_app "copy (select 1) to program 'id'"
no_debe "la aplicación lee archivos del servidor (pg_read_file)" sql_app "select pg_read_file('/etc/passwd')"
no_debe "la aplicación crea un rol" sql_app "create role intruso"
no_debe "la aplicación entra a la base postgres" docker exec prueba_backend python -c \
    "import os, psycopg2; from urllib.parse import urlsplit; u = urlsplit(os.environ['DATABASE_URL']); psycopg2.connect(host=u.hostname, user=u.username, password=u.password, dbname='postgres')"

# --- 5. Lo que ya no debe poder hacerse ---------------------------------------
echo
echo "== Aislamiento: esto tiene que fallar"
for destino in "db 5432" "redis 6379" "ollama 11434" "backend 8000"; do
    set -- $destino
    no_debe "frontend → $1:$2" tcp prueba_frontend "$1" "$2"
done
IP_DB=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}' prueba_db | awk '{print $1}')
no_debe "frontend → base por IP ($IP_DB:5432), sin nombre de por medio" tcp prueba_frontend "$IP_DB" 5432
for destino in "db 5432" "redis 6379" "ollama 11434"; do
    set -- $destino
    no_debe "nginx → $1:$2" tcp prueba_nginx "$1" "$2"
done
for destino in "db 5432" "redis 6379" "ollama 11434" "backend 8000"; do
    set -- $destino
    no_debe "mosquitto → $1:$2" tcp prueba_mosquitto "$1" "$2"
done
no_debe "Ollama sale a internet" tcp_bash prueba_ollama 1.1.1.1 443
no_debe "la base sale a internet" tcp_bash prueba_db 1.1.1.1 443
no_debe "Redis sale a internet" tcp prueba_redis 1.1.1.1 443
espera "nginx → backend:8000 (control: esto sí)" tcp prueba_nginx backend 8000

# --- 6. Qué secretos ve cada contenedor ----------------------------------------
echo
echo "== Secretos por contenedor (solo nombres)"
python3 - "$PRUEBA_ENV" <<'PY' || FALLOS=$((FALLOS + 1))
import json, subprocess, sys
secretos = ["POSTGRES_PASSWORD", "POSTGRES_APP_PASSWORD", "DATABASE_URL", "JWT_SECRET", "REDIS_PASSWORD", "REDISCLI_AUTH",
            "REDIS_URL", "GEMINI_API_KEY", "SMTP_PASSWORD", "MQTT_PASSWORD",
            "MQTT_DISPOSITIVO_PASSWORD", "MQTT_SENSORES"]
esperado = {
    "backend": {"DATABASE_URL", "JWT_SECRET", "REDIS_URL", "GEMINI_API_KEY", "SMTP_PASSWORD"},
    "worker": {"DATABASE_URL", "REDIS_URL", "SMTP_PASSWORD"},
    "ingestor": {"DATABASE_URL", "REDIS_URL", "MQTT_PASSWORD"},
    "mosquitto": {"MQTT_PASSWORD", "MQTT_DISPOSITIVO_PASSWORD", "MQTT_SENSORES"},
    "redis": {"REDIS_PASSWORD", "REDISCLI_AUTH"},
    "db": {"POSTGRES_PASSWORD", "POSTGRES_APP_PASSWORD"},
    "nginx": set(), "frontend": set(), "ollama": set(),
}
mal = 0
for nombre, quiere in esperado.items():
    entorno = json.loads(subprocess.run(["docker", "inspect", f"prueba_{nombre}", "--format",
                                         "{{json .Config.Env}}"], capture_output=True, text=True).stdout)
    tiene = {e.split("=", 1)[0] for e in entorno
             if e.split("=", 1)[0] in secretos and e.split("=", 1)[1]}
    marca = "\033[32m✔\033[0m" if tiene == quiere else "\033[31m✘\033[0m"
    extra = f"  sobran {sorted(tiene - quiere)}" if tiene - quiere else ""
    falta = f"  faltan {sorted(quiere - tiene)}" if quiere - tiene else ""
    print(f"  {marca} {nombre:10} {sorted(tiene) or '—'}{extra}{falta}")
    mal += tiene != quiere
sys.exit(1 if mal else 0)
PY

echo
echo "== Versiones: $(docker exec prueba_ollama ollama --version 2>/dev/null | tail -1)"
echo
if [ "$FALLOS" -eq 0 ]; then
    echo "Todo bien: la topología nueva funciona y aísla."
else
    echo "Fallaron $FALLOS comprobaciones."
fi
exit $(( FALLOS > 0 ))

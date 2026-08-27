#!/usr/bin/env bash
#
# Respaldo del Portal de Tickets.
#
# Respalda las tres cosas que no se pueden reconstruir:
#   1. La base de datos (tickets, resguardos, expedientes, bitácora).
#   2. Los adjuntos de tickets (fotos del error).
#   3. Los documentos del expediente (resguardos firmados escaneados).
#
# NO respalda los modelos de Ollama ni las imágenes de Docker: eso se vuelve a
# descargar. Tampoco el .env, que tiene secretos y debe resguardarse aparte,
# fuera de la rotación automática.
#
# Uso:
#   ./respaldo.sh                      # respaldo a ./respaldos
#   ./respaldo.sh /mnt/nas/portal      # respaldo a otra ruta
#   ./respaldo.sh --verificar ARCHIVO  # comprueba que un respaldo sirve
#
# Para que corra solo, en el servidor:
#   0 2 * * * /opt/portal-tickets/scripts/respaldo.sh /mnt/nas/portal >> /var/log/portal-respaldo.log 2>&1

set -euo pipefail

PROYECTO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DESTINO="${1:-$PROYECTO/respaldos}"
RETENCION_DIAS="${RETENCION_DIAS:-30}"
SELLO="$(date +%Y%m%d-%H%M%S)"

# Arreglos, no cadenas: la ruta del proyecto puede llevar espacios
# ("Portal de tickets") y una cadena sin comillas se parte en pedazos.
if docker info >/dev/null 2>&1; then
  DOCKER=(docker)
else
  DOCKER=(sudo -n docker)
fi
COMPOSE=("${DOCKER[@]}" compose -f "$PROYECTO/docker-compose.yml")

decir() { echo "[$(date +'%H:%M:%S')] $*"; }

# ---------------------------------------------------------------------
# Verificar un respaldo existente
# ---------------------------------------------------------------------
if [ "${1:-}" = "--verificar" ]; then
  ARCHIVO="${2:?Falta la ruta del respaldo}"
  decir "Verificando $ARCHIVO"
  gzip -t "$ARCHIVO" || { decir "ERROR: el archivo está corrupto"; exit 1; }
  # Un volcado válido termina con la marca de PostgreSQL.
  if zcat "$ARCHIVO" | tail -5 | grep -q "PostgreSQL database dump complete"; then
    decir "OK: el volcado está completo"
    # `decir` es una función del script: xargs no la ve, así que se calcula
    # el número aparte y se imprime desde aquí.
    TABLAS=$(zcat "$ARCHIVO" | grep -c "^COPY" || true)
    decir "  $TABLAS tabla(s) con datos"
    exit 0
  fi
  decir "ERROR: el volcado está truncado. NO sirve para restaurar."
  exit 1
fi

mkdir -p "$DESTINO"

# ---------------------------------------------------------------------
# 1. Base de datos
# ---------------------------------------------------------------------
decir "Respaldando la base de datos..."
BD="$DESTINO/portal-bd-$SELLO.sql.gz"

# --clean --if-exists deja el volcado listo para restaurar sobre una base
# existente sin tener que borrarla a mano antes.
"${COMPOSE[@]}" exec -T db pg_dump \
  -U "${POSTGRES_USER:-cgr_user}" \
  -d "${POSTGRES_DB:-portal_tickets}" \
  --clean --if-exists --no-owner \
  | gzip > "$BD"

# Un respaldo que no se verifica no es un respaldo. Esto es lo que separa
# "tenemos respaldos" de "tenemos respaldos que sirven".
if ! zcat "$BD" | tail -5 | grep -q "PostgreSQL database dump complete"; then
  decir "ERROR: el volcado quedó truncado. Se descarta."
  rm -f "$BD"
  exit 1
fi
decir "  $(du -h "$BD" | cut -f1) -> $(basename "$BD")"

# ---------------------------------------------------------------------
# 2 y 3. Archivos subidos
# ---------------------------------------------------------------------
for VOLUMEN in adjuntos documentos; do
  decir "Respaldando $VOLUMEN..."
  ARCHIVO="$DESTINO/portal-$VOLUMEN-$SELLO.tar.gz"
  NOMBRE_VOL="$(basename "$PROYECTO" | tr -d ' ' | tr '[:upper:]' '[:lower:]')_$VOLUMEN"

  # Se monta el volumen en un contenedor efímero para poder empaquetarlo.
  if "${DOCKER[@]}" volume inspect "$NOMBRE_VOL" >/dev/null 2>&1; then
    "${DOCKER[@]}" run --rm \
      -v "$NOMBRE_VOL":/origen:ro \
      -v "$DESTINO":/respaldo \
      alpine tar czf "/respaldo/$(basename "$ARCHIVO")" -C /origen . 2>/dev/null
    decir "  $(du -h "$ARCHIVO" | cut -f1) -> $(basename "$ARCHIVO")"
  else
    decir "  (el volumen $NOMBRE_VOL no existe todavía; se omite)"
  fi
done

# ---------------------------------------------------------------------
# Rotación
# ---------------------------------------------------------------------
decir "Quitando respaldos de más de $RETENCION_DIAS días..."
BORRADOS=$(find "$DESTINO" -name 'portal-*' -type f -mtime +"$RETENCION_DIAS" -print -delete | wc -l)
decir "  $BORRADOS archivo(s) retirados"

decir "Listo. Respaldos en $DESTINO:"
ls -lh "$DESTINO" | tail -5

cat <<'NOTA'

Para restaurar la base:
    zcat portal-bd-FECHA.sql.gz | docker compose exec -T db psql -U cgr_user -d portal_tickets

Para restaurar los archivos:
    docker run --rm -v portaldetickets_documentos:/destino -v "$PWD":/respaldo \
        alpine sh -c "cd /destino && tar xzf /respaldo/portal-documentos-FECHA.tar.gz"

Un respaldo que nunca se ha restaurado no se sabe si sirve.
Pruebe la restauración en una base de prueba al menos una vez.
NOTA

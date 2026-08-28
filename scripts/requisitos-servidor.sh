#!/usr/bin/env bash
#
# Qué está consumiendo el portal ahora mismo, y qué servidor necesita.
#
# Nace de una pregunta concreta: "no sé qué componentes tiene el servidor que me
# van a dar, ¿alcanza?". En vez de adivinar, esto mide lo que el portal usa de
# verdad en esta máquina y lo compara con lo que hace falta para la planta.
#
# Uso:
#   ./scripts/requisitos-servidor.sh
#
# Se puede correr con el portal en marcha; no toca nada.

set -uo pipefail

PROYECTO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if docker info >/dev/null 2>&1; then DOCKER=(docker); else DOCKER=(sudo -n docker); fi
COMPOSE=("${DOCKER[@]}" compose -f "$PROYECTO/docker-compose.yml")

titulo() { echo; echo "=== $* ==="; }

titulo "Lo que consume ahora mismo"
"${DOCKER[@]}" stats --no-stream \
  --format 'table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}' 2>/dev/null \
  | grep -i 'portal\|NAME' || echo "  (no se pudo leer docker stats)"

titulo "Espacio en disco"
echo "Base de datos:"
"${COMPOSE[@]}" exec -T db psql -U "${POSTGRES_USER:-cgr_user}" \
  -d "${POSTGRES_DB:-portal_tickets}" -t -c \
  "SELECT '  ' || pg_size_pretty(pg_database_size(current_database()));" 2>/dev/null \
  || echo "  (base no disponible)"

echo "Volúmenes de archivos:"
for VOLUMEN in adjuntos documentos ollama_models; do
  NOMBRE="$(basename "$PROYECTO" | tr -d ' ' | tr '[:upper:]' '[:lower:]')_$VOLUMEN"
  if "${DOCKER[@]}" volume inspect "$NOMBRE" >/dev/null 2>&1; then
    TAM=$("${DOCKER[@]}" run --rm -v "$NOMBRE":/v:ro alpine du -sh /v 2>/dev/null | cut -f1)
    printf '  %-16s %s\n' "$VOLUMEN" "${TAM:-?}"
  fi
done

titulo "Cuánto pesa el conocimiento"
"${COMPOSE[@]}" exec -T db psql -U "${POSTGRES_USER:-cgr_user}" \
  -d "${POSTGRES_DB:-portal_tickets}" -t -c \
  "SELECT '  tickets: ' || (SELECT count(*) FROM tickets)
       || ' · indexados: ' || (SELECT count(*) FROM base_conocimiento)
       || ' · documentos TI: ' || (SELECT count(*) FROM documentos_ti)
       || ' · usuarios: ' || (SELECT count(*) FROM usuarios);" 2>/dev/null \
  || echo "  (base no disponible)"

titulo "Modelos de Ollama cargados"
"${COMPOSE[@]}" exec -T ollama ollama list 2>/dev/null | sed 's/^/  /' \
  || echo "  (Ollama no disponible)"

cat <<'RECOMENDACION'

=== Qué servidor pedir ===

Lo que de verdad manda es Ollama: el resto del portal cabe en cualquier cosa.
El modelo de texto ocupa alrededor de 2 GB de RAM mientras responde, y el de
embeddings otro medio giga. Todo lo demás —base de datos, backend, NGINX— vive
cómodo en 2 GB entre los tres.

  MÍNIMO VIABLE          RECOMENDADO           CÓMODO A 3 AÑOS
  4 núcleos              4 núcleos             8 núcleos
  8 GB RAM               16 GB RAM             16 GB RAM
  60 GB SSD              120 GB SSD            250 GB SSD
  Sin GPU                Sin GPU               Sin GPU

**No hace falta GPU.** Un modelo de 3 000 millones de parámetros corre en CPU y
responde en menos de un segundo con el modelo ya cargado en memoria. Comprar una
tarjeta para esto sería gastar en algo que no se va a notar.

Lo que sí importa: **SSD, no disco mecánico.** La búsqueda por significado
consulta un índice vectorial, y ahí la latencia del disco se siente.

Sobre el disco: la base de datos crece poco —unos cuantos MB al año con el
volumen de la planta—. Lo que crece son los adjuntos de los tickets (fotos del
error) y los resguardos escaneados. Con 120 GB hay para años; cuando se acerque
el límite, lo que se archiva primero son los adjuntos viejos, no la base.

Sistema operativo: cualquier Linux con Docker. Ubuntu Server LTS o Debian
estable son la apuesta aburrida y correcta.

Si el servidor que les den se queda corto de RAM, hay salida sin comprar nada:
poner IA_HABILITADA=false. El portal funciona completo —tickets, resguardos,
expedientes, todo— y lo único que se pierde son las sugerencias automáticas.
RECOMENDACION

#!/usr/bin/env bash
#
# Deja el servidor limpio para el dia del despliegue.
#
# **No se ejecuta durante el desarrollo.** Borra las bitacoras de las sesiones
# de trabajo, y esas son justamente las que sirven para entender por que algo
# quedo como quedo.
#
# Que quita y por que:
#
#   ~/.claude/projects   Transcripciones completas de cada sesion de trabajo.
#                        Aqui aparecen en claro las contrasenas que se teclearon
#                        durante la configuracion: se comprobo que si estan.
#                        Vive en el home, NO en el repositorio, asi que nunca se
#                        publico con el codigo; pero en un servidor que da a
#                        internet no tiene nada que hacer.
#
#   ~/.claude/*          Instantaneas del shell e historial de sesiones.
#
#   .env.respaldo-*      Copias del .env con credenciales anteriores.
#
#   ~/.bash_history      Ordenes tecleadas, con lo que llevaran dentro.
#
# **Despues de correr esto hay que rotar las contrasenas otra vez.** Borrar las
# transcripciones no deshace que estuvieran escritas ahi: quien haya tenido
# acceso al servidor mientras existian pudo leerlas. El guion lo recuerda al
# final y no lo hace solo, porque cambiar la contrasena de la base a destiempo
# deja el portal caido.

set -euo pipefail

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SIMULACRO=1

if [ "${1:-}" = "--de-verdad" ]; then
    SIMULACRO=0
fi

quitar() {
    local ruta="$1" motivo="$2"
    [ -e "$ruta" ] || return 0
    local peso
    peso="$(du -sh "$ruta" 2>/dev/null | cut -f1)"
    if [ "$SIMULACRO" -eq 1 ]; then
        printf '  [simulacro] se borraria  %-38s %6s  %s\n' "$ruta" "$peso" "$motivo"
    else
        rm -rf -- "$ruta"
        printf '  borrado  %-38s %6s  %s\n' "$ruta" "$peso" "$motivo"
    fi
}

echo "=== Esterilizacion del servidor ==="
if [ "$SIMULACRO" -eq 1 ]; then
    echo "    MODO SIMULACRO. Nada se borra."
    echo "    Para hacerlo de verdad:  $0 --de-verdad"
fi
echo

quitar "$HOME/.claude/projects"        "transcripciones con secretos en claro"
quitar "$HOME/.claude/shell-snapshots" "instantaneas del shell"
quitar "$HOME/.claude/sessions"        "historial de sesiones"
quitar "$HOME/.claude/backups"         "respaldos de sesiones"
quitar "$HOME/.bash_history"           "ordenes tecleadas"

for respaldo in "$RAIZ"/.env.respaldo-*; do
    [ -e "$respaldo" ] || continue
    quitar "$respaldo" "credenciales anteriores"
done

echo
echo "=== Comprobacion posterior ==="
restos=0
for patron in 'CGRTI01' 'ClaveTemporal'; do
    n="$(grep -rl "$patron" "$HOME/.claude" "$HOME/.bash_history" 2>/dev/null | wc -l)"
    printf '  archivos que aun contienen %-16s %s\n' "$patron:" "$n"
    restos=$((restos + n))
done

echo
if [ "$SIMULACRO" -eq 1 ]; then
    echo "  (simulacro: los conteos de arriba son los de ahora, sin borrar nada)"
else
    echo "  PENDIENTE Y OBLIGATORIO: rotar las contrasenas."
    echo "  Borrarlas de aqui no deshace que estuvieran escritas. Rote:"
    echo "    - la de Postgres (ALTER USER + .env + reiniciar backend)"
    echo "    - la del administrador del portal"
    echo "    - JWT_SECRET, si alguna vez se mostro"
fi

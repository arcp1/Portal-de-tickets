"""El numero de serie identifica una sola pieza dentro de la planta.

El numero de serie es lo que distingue el equipo fisico: es lo que se imprime
en el resguardo que la persona firma y lo que se lee del activo cuando se
devuelve. La columna existia desde el principio con un indice normal, sin
restriccion, asi que dos altas del mismo equipo convivian sin que nada se
quejara. A partir de ahi el inventario cuenta dos donde hay uno, y un
resguardo firmado puede apuntar a la fila equivocada: el papel deja de
identificar el activo, que es lo unico que tenia que hacer.

**Por sitio y no global.** Dos plantas distintas no comparten un activo, pero
las series se repiten entre fabricantes con mas frecuencia de la que parece.
Acotarlo al sitio ataca el caso real —dar de alta dos veces el mismo equipo en
la misma planta— sin rechazar altas legitimas de otra.

**Indice parcial.** Un activo puede llegar sin serie legible: etiquetas
despegadas, equipo antiguo, consumibles que no la traen. Esas filas quedan
fuera de la restriccion en vez de pelearse entre si. En Postgres los NULL ya
son distintos entre si, pero la cadena vacia no, y en un formulario web la
cadena vacia es lo que llega: por eso el `WHERE` la excluye tambien, y por eso
la API normaliza "" a NULL antes de guardar.

Revision ID: 0015_serie_unica_por_sitio
Revises: 0014_intentos_de_activacion
"""

from alembic import op

revision = "0015_serie_unica_por_sitio"
down_revision = "0014_intentos_de_activacion"
branch_labels = None
depends_on = None

INDICE = "ix_equipos_serie_unica_por_sitio"


def upgrade() -> None:
    # Las filas que ya existan con la serie en blanco pasan a NULL: es lo que
    # significan de verdad —"no se registro"— y es lo que el indice parcial
    # espera encontrar.
    op.execute(
        "UPDATE equipos SET numero_serie = NULL "
        "WHERE numero_serie IS NOT NULL AND btrim(numero_serie) = ''"
    )
    # Si la base ya trae duplicados, esto falla y el arranque se detiene. Es lo
    # correcto: son dos filas que dicen ser el mismo activo y hay que decidir a
    # mano cual se queda. Fallar aqui es mas barato que descubrirlo el dia que
    # alguien devuelve el equipo equivocado.
    op.execute(
        f"CREATE UNIQUE INDEX {INDICE} ON equipos (sitio_id, numero_serie) "
        "WHERE numero_serie IS NOT NULL AND btrim(numero_serie) <> ''"
    )


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {INDICE}")

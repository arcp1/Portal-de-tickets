"""Índices para los listados que crecen, y fuera los que no sirven.

**Los dos que faltaban** salen de las consultas que más se repiten:

  * `tickets (sitio_id, estado, creado_en)`: el tablero de TI filtra por planta
    y por estado y ordena por fecha, y se vuelve a pedir en cada pantalla
    abierta cada vez que alguien mueve un ticket. Había `(sitio_id, creado_en)`
    y `estado` por separado; con el filtro de estado puesto, Postgres tenía
    que elegir uno y filtrar el resto a mano.
  * `usuarios (sitio_id, nombre)`: ocho consultas filtran personas por planta
    —el panel de Personas las ordena además por nombre— y no había ninguno.

**Los que sobraban** son dieciocho índices sobre `id`, uno por tabla, además
de la llave primaria, que ya es un índice sobre `id`. Los creaba el
`index=True` que el modelo llevaba en cada llave primaria. No aceleran nada
—la llave primaria ya responde lo mismo— y cada alta y cada borrado los
mantiene igual. Lo mismo `ix_resguardos_folio`, que repite la restricción
única `resguardos_folio_key`.

`IF EXISTS` porque una base creada con `create_all` en algún momento puede no
tenerlos todos, y esta migración no debe fallar por quitar lo que no está.

Revision ID: 0022_indices_de_listados
Revises: 0021_ficha_desde_ticket
"""

from alembic import op

revision = "0022_indices_de_listados"
down_revision = "0021_ficha_desde_ticket"
branch_labels = None
depends_on = None

TABLAS_CON_ID_DUPLICADO = (
    "auditoria", "base_conocimiento", "chat_sesiones", "checklists", "consumo_ia",
    "documentos_ti", "documentos_usuario", "equipos", "movimientos_equipo",
    "reglas_negocio", "resguardos", "sitios", "sugerencias_kb", "temas_sugeridos",
    "ticket_adjuntos", "ticket_comentarios", "tickets", "usuarios",
)


def upgrade() -> None:
    op.create_index("ix_tickets_sitio_estado_creado", "tickets",
                    ["sitio_id", "estado", "creado_en"])
    op.create_index("ix_usuarios_sitio_nombre", "usuarios", ["sitio_id", "nombre"])

    for tabla in TABLAS_CON_ID_DUPLICADO:
        op.execute(f"DROP INDEX IF EXISTS ix_{tabla}_id")
    op.execute("DROP INDEX IF EXISTS ix_resguardos_folio")


def downgrade() -> None:
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_resguardos_folio ON resguardos (folio)")
    for tabla in TABLAS_CON_ID_DUPLICADO:
        op.execute(f"CREATE INDEX IF NOT EXISTS ix_{tabla}_id ON {tabla} (id)")
    op.drop_index("ix_usuarios_sitio_nombre", table_name="usuarios")
    op.drop_index("ix_tickets_sitio_estado_creado", table_name="tickets")

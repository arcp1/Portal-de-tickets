"""De donde salio una ficha visual.

Las fotos del problema **ya existen**: la gente las adjunta a sus tickets desde
que hay adjuntos. Obligar a TI a volver a fotografiar el mismo defecto para
documentarlo, o a descargarlo y resubirlo a mano, era pedir dos veces un
trabajo ya hecho — y el trabajo que se pide dos veces no se hace ninguna.

Con esta columna una ficha puede nacer de un ticket resuelto llevandose su
descripcion, su solucion, lo que se descarto y sus fotos. Y queda dicho de
cual, que sirve para dos cosas:

  * **No duplicar.** Pulsar el boton dos veces no crea dos fichas del mismo
    defecto; la segunda vez se devuelve la que ya existe.
  * **Poder comprobar.** Igual que en `base_conocimiento.ticket_origen_id`,
    quien lea la ficha dentro de un ano puede abrir el ticket del que salio y
    ver el caso real.

`SET NULL` y no `CASCADE`: si algun dia se borrara el ticket, la ficha sigue
siendo valida —el defecto existe y la solucion funciona— y lo unico que se
pierde es el rastro de donde se documento.

Revision ID: 0021_ficha_desde_ticket
Revises: 0020_ficha_resuelta
"""

import sqlalchemy as sa
from alembic import op

revision = "0021_ficha_desde_ticket"
down_revision = "0020_ficha_resuelta"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "fichas_visuales",
        sa.Column("ticket_origen_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fichas_visuales_ticket_origen_id_fkey",
        "fichas_visuales", "tickets",
        ["ticket_origen_id"], ["id"],
        ondelete="SET NULL",
    )
    # La consulta es "¿ya hay ficha de este ticket?", una por pulsacion del
    # boton. Parcial: las fichas escritas a mano no tienen origen y no tienen
    # por que ocupar sitio en el indice.
    op.create_index(
        "ix_fichas_visuales_ticket_origen",
        "fichas_visuales",
        ["ticket_origen_id"],
        postgresql_where=sa.text("ticket_origen_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_fichas_visuales_ticket_origen", table_name="fichas_visuales")
    op.drop_constraint("fichas_visuales_ticket_origen_id_fkey",
                       "fichas_visuales", type_="foreignkey")
    op.drop_column("fichas_visuales", "ticket_origen_id")

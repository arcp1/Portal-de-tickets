"""Imagenes en los pasos, en la base de conocimiento y en la solucion de un ticket.

Las tres cosas eran texto puro. "Pulse el boton de reinicio de la parte
trasera" obliga a buscar un boton; con la foto de donde esta, se pulsa a la
primera. Y la solucion de un ticket es lo que la persona abre para ver como le
arreglaron su problema: una captura de la configuracion que se cambio dice mas
que el parrafo que la describe.

Una sola tabla para las tres, con una llave foranea por dueno y una
restriccion que exige exactamente una. Ver `ImagenConocimiento` en
app/models/__init__.py.

Revision ID: 0028_imagenes_conocimiento
Revises: 0027_alertas_datos_umbrales
"""

import sqlalchemy as sa
from alembic import op

revision = "0028_imagenes_conocimiento"
down_revision = "0027_alertas_datos_umbrales"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Crear una llave foranea pide un bloqueo sobre la tabla a la que apunta
    # —tickets, checklists, base_conocimiento—. Con limite, una transaccion
    # colgada hace fallar la migracion en vez de encolar detras de ella todas
    # las consultas del portal (paso con la 0016).
    op.execute("SET lock_timeout = '10s'")

    op.create_table(
        "imagenes_conocimiento",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("paso_id", sa.Integer(),
                  sa.ForeignKey("checklists.id", ondelete="CASCADE"), nullable=True),
        sa.Column("kb_id", sa.Integer(),
                  sa.ForeignKey("base_conocimiento.id", ondelete="CASCADE"), nullable=True),
        sa.Column("ticket_id", sa.Integer(),
                  sa.ForeignKey("tickets.id", ondelete="CASCADE"), nullable=True),
        sa.Column("orden", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("pie", sa.String(300), nullable=True),
        sa.Column("nombre_original", sa.String(255), nullable=False),
        sa.Column("nombre_guardado", sa.String(255), nullable=False, unique=True),
        sa.Column("tipo_mime", sa.String(100), nullable=False),
        sa.Column("tamano_bytes", sa.Integer(), nullable=False),
        sa.Column("subido_por", sa.Integer(), sa.ForeignKey("usuarios.id"), nullable=False),
        sa.Column("creado_en", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "(CASE WHEN paso_id IS NULL THEN 0 ELSE 1 END)"
            " + (CASE WHEN kb_id IS NULL THEN 0 ELSE 1 END)"
            " + (CASE WHEN ticket_id IS NULL THEN 0 ELSE 1 END) = 1",
            name="ck_imagenes_conocimiento_un_dueno",
        ),
    )
    # Se busca siempre por dueno: "las imagenes de este paso".
    op.create_index("ix_imagenes_conocimiento_paso_id", "imagenes_conocimiento", ["paso_id"])
    op.create_index("ix_imagenes_conocimiento_kb_id", "imagenes_conocimiento", ["kb_id"])
    op.create_index("ix_imagenes_conocimiento_ticket_id", "imagenes_conocimiento", ["ticket_id"])


def downgrade() -> None:
    op.drop_index("ix_imagenes_conocimiento_ticket_id", table_name="imagenes_conocimiento")
    op.drop_index("ix_imagenes_conocimiento_kb_id", table_name="imagenes_conocimiento")
    op.drop_index("ix_imagenes_conocimiento_paso_id", table_name="imagenes_conocimiento")
    op.drop_table("imagenes_conocimiento")

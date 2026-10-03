"""Imagenes tambien en los procedimientos de Soluciones generales.

La 0028 dio imagenes a los pasos, a la base de conocimiento y a la solucion de
un ticket. Los procedimientos consolidados de Soluciones generales son el
mismo tipo de texto —"que revisar primero, que suele ser"— y se le ensenan a
la gente por el asistente igual que una entrada de la base: les faltaba lo
mismo.

Misma tabla, un cuarto dueno: columna `solucion_id` y la restriccion de
"exactamente un dueno" rehecha para contarlo.

Revision ID: 0029_imagenes_soluciones
Revises: 0028_imagenes_conocimiento
"""

import sqlalchemy as sa
from alembic import op

revision = "0029_imagenes_soluciones"
down_revision = "0028_imagenes_conocimiento"
branch_labels = None
depends_on = None

_DUENOS_3 = (
    "(CASE WHEN paso_id IS NULL THEN 0 ELSE 1 END)"
    " + (CASE WHEN kb_id IS NULL THEN 0 ELSE 1 END)"
    " + (CASE WHEN ticket_id IS NULL THEN 0 ELSE 1 END) = 1"
)
_DUENOS_4 = (
    "(CASE WHEN paso_id IS NULL THEN 0 ELSE 1 END)"
    " + (CASE WHEN kb_id IS NULL THEN 0 ELSE 1 END)"
    " + (CASE WHEN ticket_id IS NULL THEN 0 ELSE 1 END)"
    " + (CASE WHEN solucion_id IS NULL THEN 0 ELSE 1 END) = 1"
)


def upgrade() -> None:
    # Ver la 0016: con limite, un bloqueo hace fallar la migracion en vez de
    # encolar detras de ella todas las consultas del portal.
    op.execute("SET lock_timeout = '10s'")
    op.add_column(
        "imagenes_conocimiento",
        sa.Column("solucion_id", sa.Integer(),
                  sa.ForeignKey("soluciones_generales.id", ondelete="CASCADE"), nullable=True),
    )
    op.create_index("ix_imagenes_conocimiento_solucion_id", "imagenes_conocimiento",
                    ["solucion_id"])
    op.drop_constraint("ck_imagenes_conocimiento_un_dueno", "imagenes_conocimiento", type_="check")
    op.create_check_constraint("ck_imagenes_conocimiento_un_dueno", "imagenes_conocimiento",
                               _DUENOS_4)


def downgrade() -> None:
    op.execute("DELETE FROM imagenes_conocimiento WHERE solucion_id IS NOT NULL")
    op.drop_constraint("ck_imagenes_conocimiento_un_dueno", "imagenes_conocimiento", type_="check")
    op.create_check_constraint("ck_imagenes_conocimiento_un_dueno", "imagenes_conocimiento",
                               _DUENOS_3)
    op.drop_index("ix_imagenes_conocimiento_solucion_id", table_name="imagenes_conocimiento")
    op.drop_column("imagenes_conocimiento", "solucion_id")

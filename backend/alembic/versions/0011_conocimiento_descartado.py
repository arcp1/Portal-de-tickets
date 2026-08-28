"""Lo que ya se probó y NO funcionó.

Media hora de un técnico se va en repetir lo que alguien más ya descartó. Si el
ticket anterior dice "cambiamos el cartucho y siguió igual; era el rodillo", el
siguiente que reporte la misma raya negra se ahorra el cartucho.

Ese saber negativo hoy no se guarda en ningún lado: el campo `solucion` cuenta lo
que sí funcionó, y lo demás se pierde. Aquí se le da lugar propio, y se indexa
junto con la solución para que el asistente lo pueda citar.

Revision ID: 0011_conocimiento_descartado
Revises: 0010_numero_epp
Create Date: 2026-08-27
"""

import sqlalchemy as sa
from alembic import op

revision = "0011_conocimiento_descartado"
down_revision = "0010_numero_epp"
branch_labels = None
depends_on = None


def _tiene_columna(tabla, columna):
    inspector = sa.inspect(op.get_bind())
    if tabla not in inspector.get_table_names():
        return False
    return columna in {c["name"] for c in inspector.get_columns(tabla)}


def upgrade():
    if not _tiene_columna("tickets", "descartado"):
        op.add_column("tickets", sa.Column("descartado", sa.Text(), nullable=True))
    if not _tiene_columna("base_conocimiento", "descartado"):
        op.add_column("base_conocimiento", sa.Column("descartado", sa.Text(), nullable=True))


def downgrade():
    if _tiene_columna("base_conocimiento", "descartado"):
        op.drop_column("base_conocimiento", "descartado")
    if _tiene_columna("tickets", "descartado"):
        op.drop_column("tickets", "descartado")

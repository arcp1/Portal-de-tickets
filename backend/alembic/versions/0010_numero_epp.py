"""Número de EPP: el segundo factor que la gente sí se sabe.

Cada persona en planta tiene, además de su número de empleado, un número de
cuatro dígitos con el que saca su equipo de protección. Lo usa seguido, así que
se lo sabe de memoria —a diferencia de su fecha de ingreso, que casi nadie
recuerda—.

Eso permite pedir **dos** datos en vez de uno para activar una cuenta sin código:
número de EPP y fecha de nacimiento. Con uno solo, alguien de RH que viera la
lista podría activar cuentas ajenas; con dos, tiene que conocer las dos cosas de
esa persona en concreto.

No lleva índice único a propósito: es un dato de verificación, no una llave de
acceso. Si mañana resulta que dos personas comparten número, el portal no se
rompe.

Revision ID: 0010_numero_epp
Revises: 0009_fecha_nacimiento
Create Date: 2026-08-27
"""

import sqlalchemy as sa
from alembic import op

revision = "0010_numero_epp"
down_revision = "0009_fecha_nacimiento"
branch_labels = None
depends_on = None


def _tiene_columna(tabla, columna):
    inspector = sa.inspect(op.get_bind())
    if tabla not in inspector.get_table_names():
        return False
    return columna in {c["name"] for c in inspector.get_columns(tabla)}


def upgrade():
    if not _tiene_columna("usuarios", "numero_epp"):
        op.add_column("usuarios", sa.Column("numero_epp", sa.String(length=10), nullable=True))


def downgrade():
    if _tiene_columna("usuarios", "numero_epp"):
        op.drop_column("usuarios", "numero_epp")

"""Fecha de nacimiento como dato de verificación.

La fecha de ingreso resultó mal elegida en la práctica: buena parte de la
plantilla lleva años en la planta y **no se acuerda de en qué mes entró**. Un
dato de verificación que la persona no recuerda no verifica nada, solo la deja
fuera.

Su cumpleaños, en cambio, se lo sabe todo el mundo, y RH lo tiene en la misma
lista. Así que la verificación pasa a apoyarse en la fecha de nacimiento, y la
de ingreso se queda como alternativa para quien la tenga a la mano.

Revision ID: 0009_fecha_nacimiento
Revises: 0008_numero_empleado
Create Date: 2026-08-27
"""

import sqlalchemy as sa
from alembic import op

revision = "0009_fecha_nacimiento"
down_revision = "0008_numero_empleado"
branch_labels = None
depends_on = None


def _inspector():
    return sa.inspect(op.get_bind())


def _tiene_columna(tabla, columna):
    if tabla not in _inspector().get_table_names():
        return False
    return columna in {c["name"] for c in _inspector().get_columns(tabla)}


def upgrade():
    if not _tiene_columna("usuarios", "fecha_nacimiento"):
        op.add_column("usuarios", sa.Column("fecha_nacimiento", sa.DateTime(), nullable=True))


def downgrade():
    if _tiene_columna("usuarios", "fecha_nacimiento"):
        op.drop_column("usuarios", "fecha_nacimiento")

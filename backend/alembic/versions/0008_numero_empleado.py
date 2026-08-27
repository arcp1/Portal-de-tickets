"""Número de empleado como identificador principal.

En planta no todo el mundo tiene correo corporativo: un operador de línea
normalmente no. Pero **todos** tienen número de empleado. Hacer del correo la
llave de acceso dejaría fuera a la mayor parte de la plantilla.

Cambios:
  - `numero_empleado` único: la nueva llave de acceso.
  - `email` pasa a opcional: sin correo la cuenta funciona igual, solo que esa
    persona no recibe avisos.
  - `fecha_ingreso`: dato de verificación para la activación masiva.

A las cuentas existentes se les asigna un número provisional derivado de su id,
para no romper el acceso de quien ya entraba. TI los corrige desde el panel.

Revision ID: 0008_numero_empleado
Revises: 0007_cuentas_docti
Create Date: 2026-08-27
"""

import sqlalchemy as sa
from alembic import op

revision = "0008_numero_empleado"
down_revision = "0007_cuentas_docti"
branch_labels = None
depends_on = None


def _inspector():
    return sa.inspect(op.get_bind())


def _tiene_columna(tabla, columna):
    if tabla not in _inspector().get_table_names():
        return False
    return columna in {c["name"] for c in _inspector().get_columns(tabla)}


def upgrade():
    if not _tiene_columna("usuarios", "numero_empleado"):
        op.add_column("usuarios", sa.Column("numero_empleado", sa.String(length=20), nullable=True))

    if not _tiene_columna("usuarios", "fecha_ingreso"):
        op.add_column("usuarios", sa.Column("fecha_ingreso", sa.DateTime(), nullable=True))

    # Número provisional para las cuentas que ya existían. Se marca con el
    # prefijo TMP- para que TI las distinga de un número real de nómina.
    op.execute(
        "UPDATE usuarios SET numero_empleado = 'TMP-' || LPAD(id::text, 5, '0') "
        "WHERE numero_empleado IS NULL"
        if op.get_bind().dialect.name == "postgresql"
        else "UPDATE usuarios SET numero_empleado = 'TMP-' || substr('00000' || id, -5) "
             "WHERE numero_empleado IS NULL"
    )

    indices = {i["name"] for i in _inspector().get_indexes("usuarios")}
    if "ix_usuarios_numero_empleado" not in indices:
        op.create_index("ix_usuarios_numero_empleado", "usuarios",
                        ["numero_empleado"], unique=True)

    # El correo deja de ser obligatorio.
    op.alter_column("usuarios", "email", existing_type=sa.String(length=100), nullable=True)


def downgrade():
    indices = {i["name"] for i in _inspector().get_indexes("usuarios")}
    if "ix_usuarios_numero_empleado" in indices:
        op.drop_index("ix_usuarios_numero_empleado", table_name="usuarios")

    for columna in ("fecha_ingreso", "numero_empleado"):
        if _tiene_columna("usuarios", columna):
            op.drop_column("usuarios", columna)

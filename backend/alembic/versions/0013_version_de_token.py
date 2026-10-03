"""Versionado de token: poder invalidar sesiones ya emitidas.

Hasta ahora un token valia sus 8 horas pasara lo que pasara. Cambiar la
contrasena no lo invalidaba, restablecer la cuenta tampoco, y "cerrar sesion"
solo borraba el token del navegador: quien tuviera una copia seguia entrando.

Con un contador por cuenta que viaja dentro del token, subir el contador
invalida de golpe todo lo emitido antes. Se sube al cambiar la contrasena, al
restablecer la cuenta y al abrir una activacion asistida, que son justo los
momentos en que uno quiere echar fuera a quien estuviera dentro.

Revision ID: 0013_version_de_token
Revises: 0012_soluciones_generales
"""

import sqlalchemy as sa
from alembic import op

revision = "0013_version_de_token"
down_revision = "0012_soluciones_generales"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # `server_default` para que las filas que ya existen arranquen en 1 sin
    # necesidad de un UPDATE aparte; las sesiones abiertas hoy siguen valiendo.
    op.add_column(
        "usuarios",
        sa.Column("version_token", sa.Integer(), nullable=False, server_default="1"),
    )


def downgrade() -> None:
    op.drop_column("usuarios", "version_token")

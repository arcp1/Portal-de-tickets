"""Contador de activaciones fallidas por cuenta.

El modo sin codigo se apoya en numero de EPP y fecha de nacimiento. Los dos
salen de la misma lista de RH, asi que contra alguien que la haya visto valen
cero, y contra un desconocido son unos 27 bits: mucho para teclear a mano, poco
para un programa.

Lo que de verdad lo acota es cerrar la puerta despues de unos pocos fallos. Con
cinco intentos por cuenta, adivinar un cumpleaños pasa de "cuestion de tiempo" a
una probabilidad despreciable, y el intento queda registrado para que TI lo vea
en vez de enterarse cuando ya paso.

Revision ID: 0014_intentos_de_activacion
Revises: 0013_version_de_token
"""

import sqlalchemy as sa
from alembic import op

revision = "0014_intentos_de_activacion"
down_revision = "0013_version_de_token"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "usuarios",
        sa.Column("intentos_activacion", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "usuarios",
        sa.Column("verificacion_bloqueada", sa.Boolean(), nullable=False,
                  server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("usuarios", "verificacion_bloqueada")
    op.drop_column("usuarios", "intentos_activacion")

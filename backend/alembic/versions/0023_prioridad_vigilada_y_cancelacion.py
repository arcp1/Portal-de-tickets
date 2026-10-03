"""Prioridad alta revocable y tickets cancelados por quien los reportó.

**`usuarios.puede_usar_prioridad_alta`.** Quien levanta un ticket indica su
urgencia —alta o crítica incluidas—, porque la conoce mejor que nadie; pero
es la única palanca que tiene sobre la cola de TI. TI puede quitársela a quien
abusa de ella: con el permiso en falso, el ticket nace en "media" aunque se
pida más. Nace en verdadero para todas las cuentas, las de hoy incluidas.

**`tickets.cancelado_en`.** El estado nuevo, "cancelado", no necesita cambio
de esquema: `estado` es texto libre. Lo que sí hace falta es el momento, y va
en su propia columna y no en `resuelto_en`: un ticket retirado no se resolvió,
y contarlo como resuelto ensuciaría el tiempo de resolución y la tasa de
deflexión.

Revision ID: 0023_prioridad_vigilada
Revises: 0022_indices_de_listados
"""

import sqlalchemy as sa
from alembic import op

revision = "0023_prioridad_vigilada"
down_revision = "0022_indices_de_listados"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "usuarios",
        sa.Column("puede_usar_prioridad_alta", sa.Boolean(), nullable=False,
                  server_default=sa.text("true")),
    )
    op.add_column("tickets", sa.Column("cancelado_en", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("tickets", "cancelado_en")
    op.drop_column("usuarios", "puede_usar_prioridad_alta")

"""Clave de envío de los tickets, contra duplicados cuando la red falla.

**El problema.** Si la conexión se corta *después* de que el servidor creó el
ticket pero *antes* de que la respuesta llegue —el Wi-Fi de planta lo hace—,
la pantalla dice "no se pudo crear" y la persona vuelve a pulsar. Resultado:
dos tickets iguales, dos folios, el SLA corriendo dos veces.

**La solución.** El formulario genera una clave al abrirse y la manda en cada
intento (`Idempotency-Key`). Si el servidor ya creó un ticket con esa clave
para esa persona, devuelve ese mismo en vez de crear otro.

El índice único es **parcial**: solo cubre los tickets que traen clave. Los
de antes, y los que se crean sin ella, no se tocan.

Revision ID: 0024_clave_de_envio
Revises: 0023_prioridad_vigilada
"""

import sqlalchemy as sa
from alembic import op

revision = "0024_clave_de_envio"
down_revision = "0023_prioridad_vigilada"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tickets", sa.Column("clave_envio", sa.String(64), nullable=True))
    op.create_index(
        "ux_tickets_usuario_clave_envio", "tickets", ["usuario_id", "clave_envio"],
        unique=True,
        postgresql_where=sa.text("clave_envio IS NOT NULL"),
        sqlite_where=sa.text("clave_envio IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ux_tickets_usuario_clave_envio", table_name="tickets")
    op.drop_column("tickets", "clave_envio")

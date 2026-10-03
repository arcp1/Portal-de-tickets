"""Datos de cada alerta y umbrales por sensor.

  * `alertas.datos`: lo que la pantalla necesita para redactar la alerta en el
    idioma de quien la lee (folio, minutos que faltan, valor medido y umbral).
  * `dispositivos_iot.umbrales`: los límites propios de un sensor, cuando los
    generales (IOT_*_MAX) no le valen —un cuarto de servidores no aguanta lo
    que aguanta una nave—.

Va aparte de la 0026 porque esa ya está aplicada en producción.

Revision ID: 0027_alertas_datos_umbrales
Revises: 0026_satisfaccion_alertas_iot
"""

import sqlalchemy as sa
from alembic import op

revision = "0027_alertas_datos_umbrales"
down_revision = "0026_satisfaccion_alertas_iot"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("alertas", sa.Column("datos", sa.JSON(), nullable=True))
    op.add_column("dispositivos_iot", sa.Column("umbrales", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("dispositivos_iot", "umbrales")
    op.drop_column("alertas", "datos")

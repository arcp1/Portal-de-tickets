"""Encuesta de satisfacción, alertas para TI y telemetría de sensores ESP32.

  * `tickets.satisfaccion*`: de 1 a 5 estrellas y un comentario opcional, que
    responde quien reportó cuando el ticket queda resuelto.
  * `dispositivos_iot` / `lecturas_iot`: los ESP32 que publican por MQTT y lo
    que van midiendo. El índice `(dispositivo_id, registrado_en)` es el que
    sirve la gráfica de las últimas horas.
  * `alertas`: lo que el vigilante del SLA y la telemetría le avisan a TI. El
    único de `(tipo, clave)` evita avisar dos veces de lo mismo.

Revision ID: 0026_satisfaccion_alertas_iot
Revises: 0025_multiplanta
"""

import sqlalchemy as sa
from alembic import op

revision = "0026_satisfaccion_alertas_iot"
down_revision = "0025_multiplanta"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tickets", sa.Column("satisfaccion", sa.Integer(), nullable=True))
    op.add_column("tickets", sa.Column("satisfaccion_comentario", sa.Text(), nullable=True))
    op.add_column("tickets", sa.Column("satisfaccion_en", sa.DateTime(), nullable=True))
    op.create_check_constraint("ck_tickets_satisfaccion_1_a_5", "tickets",
                               "satisfaccion IS NULL OR satisfaccion BETWEEN 1 AND 5")

    op.create_table(
        "dispositivos_iot",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("clave", sa.String(64), nullable=False),
        sa.Column("nombre", sa.String(100), nullable=True),
        sa.Column("ubicacion", sa.String(100), nullable=True),
        sa.Column("sitio_id", sa.Integer(), sa.ForeignKey("sitios.id"), nullable=True),
        sa.Column("activo", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("ultimo_contacto", sa.DateTime(), nullable=True),
        sa.Column("creado_en", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_dispositivos_iot_clave", "dispositivos_iot", ["clave"], unique=True)
    op.create_index("ix_dispositivos_iot_sitio_id", "dispositivos_iot", ["sitio_id"])

    op.create_table(
        "lecturas_iot",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("dispositivo_id", sa.Integer(),
                  sa.ForeignKey("dispositivos_iot.id", ondelete="CASCADE"), nullable=False),
        sa.Column("temperatura", sa.Float(), nullable=True),
        sa.Column("humedad", sa.Float(), nullable=True),
        sa.Column("calidad_aire", sa.Float(), nullable=True),
        sa.Column("extra", sa.JSON(), nullable=True),
        sa.Column("registrado_en", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_lecturas_iot_dispositivo_fecha", "lecturas_iot",
                    ["dispositivo_id", "registrado_en"])

    op.create_table(
        "alertas",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tipo", sa.String(30), nullable=False),
        sa.Column("clave", sa.String(120), nullable=False),
        sa.Column("sitio_id", sa.Integer(), sa.ForeignKey("sitios.id"), nullable=True),
        sa.Column("ticket_id", sa.Integer(), sa.ForeignKey("tickets.id", ondelete="CASCADE"),
                  nullable=True),
        sa.Column("dispositivo_id", sa.Integer(),
                  sa.ForeignKey("dispositivos_iot.id", ondelete="CASCADE"), nullable=True),
        sa.Column("titulo", sa.String(200), nullable=False),
        sa.Column("detalle", sa.Text(), nullable=True),
        sa.Column("creado_en", sa.DateTime(), nullable=False),
        sa.Column("atendida_en", sa.DateTime(), nullable=True),
        sa.Column("atendida_por", sa.Integer(), sa.ForeignKey("usuarios.id"), nullable=True),
        sa.UniqueConstraint("tipo", "clave", name="uq_alertas_tipo_clave"),
    )
    op.create_index("ix_alertas_tipo", "alertas", ["tipo"])
    op.create_index("ix_alertas_sitio_id", "alertas", ["sitio_id"])
    op.create_index("ix_alertas_creado_en", "alertas", ["creado_en"])


def downgrade() -> None:
    op.drop_table("alertas")
    op.drop_table("lecturas_iot")
    op.drop_table("dispositivos_iot")
    op.drop_constraint("ck_tickets_satisfaccion_1_a_5", "tickets", type_="check")
    op.drop_column("tickets", "satisfaccion_en")
    op.drop_column("tickets", "satisfaccion_comentario")
    op.drop_column("tickets", "satisfaccion")

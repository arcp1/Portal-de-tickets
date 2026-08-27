"""Adjuntos en tickets y SLA por horario laboral.

Agrega:
  - tickets.vence_en / tickets.fuera_horario
  - tabla ticket_adjuntos

Revision ID: 0004_adjuntos_sla
Revises: 0003_temas
Create Date: 2026-08-26
"""

import sqlalchemy as sa
from alembic import op

revision = "0004_adjuntos_sla"
down_revision = "0003_temas"
branch_labels = None
depends_on = None


def _inspector():
    return sa.inspect(op.get_bind())


def _tiene_tabla(nombre):
    return nombre in _inspector().get_table_names()


def _tiene_columna(tabla, columna):
    if not _tiene_tabla(tabla):
        return False
    return columna in {c["name"] for c in _inspector().get_columns(tabla)}


def upgrade():
    if not _tiene_columna("tickets", "vence_en"):
        op.add_column("tickets", sa.Column("vence_en", sa.DateTime(), nullable=True))

    if not _tiene_columna("tickets", "fuera_horario"):
        op.add_column(
            "tickets",
            sa.Column("fuera_horario", sa.Boolean(), nullable=False, server_default=sa.false()),
        )

    if not _tiene_tabla("ticket_adjuntos"):
        op.create_table(
            "ticket_adjuntos",
            sa.Column("id", sa.Integer(), primary_key=True, index=True),
            sa.Column("ticket_id", sa.Integer(), sa.ForeignKey("tickets.id"), nullable=False),
            sa.Column("subido_por", sa.Integer(), sa.ForeignKey("usuarios.id"), nullable=False),
            sa.Column("nombre_original", sa.String(length=255), nullable=False),
            sa.Column("nombre_guardado", sa.String(length=255), nullable=False, unique=True),
            sa.Column("tipo_mime", sa.String(length=100), nullable=False),
            sa.Column("tamano_bytes", sa.Integer(), nullable=False),
            sa.Column("creado_en", sa.DateTime(), nullable=True),
        )
        # Se listan siempre por ticket.
        op.create_index("ix_ticket_adjuntos_ticket", "ticket_adjuntos", ["ticket_id"])

    # Los tickets abiertos de antes no tienen vencimiento. Se les asigna uno
    # por prioridad para que el tablero no los muestre como "sin SLA" para
    # siempre. Las horas son de reloj aquí: recalcular horas hábiles hacia
    # atrás no aporta nada y complica la migración.
    horas = {"critica": 2, "alta": 8, "media": 24, "baja": 72}
    for prioridad, h in horas.items():
        op.execute(
            f"""
            UPDATE tickets
               SET vence_en = creado_en + INTERVAL '{h} hours'
             WHERE vence_en IS NULL
               AND prioridad = '{prioridad}'
               AND estado NOT IN ('resuelto', 'cerrado')
            """
            if op.get_bind().dialect.name == "postgresql"
            else f"""
            UPDATE tickets
               SET vence_en = datetime(creado_en, '+{h} hours')
             WHERE vence_en IS NULL
               AND prioridad = '{prioridad}'
               AND estado NOT IN ('resuelto', 'cerrado')
            """
        )


def downgrade():
    if _tiene_tabla("ticket_adjuntos"):
        op.drop_table("ticket_adjuntos")

    for columna in ("fuera_horario", "vence_en"):
        if _tiene_columna("tickets", columna):
            op.drop_column("tickets", columna)

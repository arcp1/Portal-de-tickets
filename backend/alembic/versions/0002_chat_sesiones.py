"""Sesiones del chatbot flotante.

Agrega la tabla chat_sesiones. Misma nota que en 0001: se inspecciona antes de
crear porque ``main.py`` todavía llama a ``Base.metadata.create_all()`` en el
arranque, así que la tabla puede existir ya.

Revision ID: 0002_chat_sesiones
Revises: 0001_solucion_kb
Create Date: 2026-08-25
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0002_chat_sesiones"
down_revision = "0001_solucion_kb"
branch_labels = None
depends_on = None


def _inspector():
    return sa.inspect(op.get_bind())


def _tiene_tabla(nombre):
    return nombre in _inspector().get_table_names()


def upgrade():
    es_postgres = op.get_bind().dialect.name == "postgresql"

    # Igual que en 0001: sobre una base vacía no hay nada que hacer, create_all
    # va a crear la tabla con la forma correcta.
    if not _tiene_tabla("usuarios"):
        return

    if _tiene_tabla("chat_sesiones"):
        return

    op.create_table(
        "chat_sesiones",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("usuario_id", sa.Integer(), sa.ForeignKey("usuarios.id"), nullable=False),
        sa.Column("ticket_id", sa.Integer(), sa.ForeignKey("tickets.id"), nullable=True),
        sa.Column("categoria_detectada", sa.String(length=50), nullable=True),
        sa.Column("confianza", sa.Float(), nullable=True),
        sa.Column("mensajes", JSONB() if es_postgres else sa.JSON(), nullable=False),
        sa.Column("cerrada", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("creado_en", sa.DateTime(), nullable=True),
    )


def downgrade():
    if _tiene_tabla("chat_sesiones"):
        op.drop_table("chat_sesiones")

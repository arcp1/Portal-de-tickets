"""Soluciones generales: un artículo por problema recurrente.

Diez tickets sobre la misma impresora dejan diez soluciones parecidas y ninguna
completa. Cada una cuenta lo que pasó ese día; ninguna cuenta **el problema**.

Esta tabla guarda el paso siguiente: cuando un problema ya se repitió varias
veces, se junta lo aprendido en un solo procedimiento —qué revisar primero, qué
suele ser, qué ya se descartó— que TI revisa y publica.

Y ahí es donde el modelo de pago se gana el sueldo: redactar sobre diez tickets a
la vez es exactamente lo que un modelo chico no puede hacer, y es una consulta al
mes por problema, no una por ticket.

Nada se publica solo. El borrador lo escribe la máquina; **la publicación la
firma una persona**, porque un procedimiento equivocado en una planta se paga
caro.

Revision ID: 0012_soluciones_generales
Revises: 0011_conocimiento_descartado
Create Date: 2026-08-27
"""

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision = "0012_soluciones_generales"
down_revision = "0011_conocimiento_descartado"
branch_labels = None
depends_on = None


def _tablas():
    return sa.inspect(op.get_bind()).get_table_names()


def upgrade():
    if "soluciones_generales" in _tablas():
        return

    op.create_table(
        "soluciones_generales",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sitio_id", sa.Integer(), sa.ForeignKey("sitios.id"), nullable=False),
        sa.Column("titulo", sa.String(length=200), nullable=False),
        sa.Column("categoria", sa.String(length=50), nullable=True),
        # El procedimiento consolidado, ya revisado.
        sa.Column("contenido", sa.Text(), nullable=False),
        # Lo que se ha probado y no era. Se junta de los descartes de los
        # tickets que dieron origen a esta solución.
        sa.Column("descartado", sa.Text(), nullable=True),
        # borrador | publicada | archivada
        sa.Column("estado", sa.String(length=20), nullable=False, server_default="borrador"),
        # De cuántos tickets salió. Es lo que dice si vale la pena leerla.
        sa.Column("tickets_origen", sa.Integer(), nullable=False, server_default="0"),
        # Quién la redactó: gemini | ollama | persona
        sa.Column("redactada_por", sa.String(length=20), nullable=True),
        sa.Column("revisada_por", sa.Integer(), sa.ForeignKey("usuarios.id"), nullable=True),
        sa.Column("embedding", Vector(768), nullable=True),
        sa.Column("veces_sugerida", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("veces_util", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("creado_en", sa.DateTime(), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("publicado_en", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_soluciones_generales_sitio", "soluciones_generales",
                    ["sitio_id", "estado"])


def downgrade():
    if "soluciones_generales" in _tablas():
        op.drop_index("ix_soluciones_generales_sitio", table_name="soluciones_generales")
        op.drop_table("soluciones_generales")

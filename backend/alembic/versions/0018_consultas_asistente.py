"""Bitacora de consultas al asistente: que se pregunta que el portal no sabe.

Todas las metricas del portal miden lo que **si** funciono: sugerencias utiles,
tickets deflectados, checklists que resolvieron. Ninguna guardaba los fallos —y
los fallos son los unicos que dicen que documentacion falta escribir—.

El caso que lo hizo evidente: una consulta sobre un escaner de codigo de barras
recupero un ticket de "cuenta bloqueada" al 66% de parecido, el modelo no pudo
fundamentar nada encima y la respuesta acabo en extractos, tras 27 segundos de
CPU. Nada de eso quedaba registrado en ninguna parte. Con esta tabla, doce casos
asi dejan de ser invisibles y pasan a ser una lista de temas por documentar.

Revision ID: 0018_consultas_asistente
Revises: 0017_indices_vectoriales
"""

import sqlalchemy as sa
from alembic import op

revision = "0018_consultas_asistente"
down_revision = "0017_indices_vectoriales"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "consultas_asistente",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sitio_id", sa.Integer(), sa.ForeignKey("sitios.id"), nullable=False),
        # Nullable y SET NULL: dar de baja a una persona no puede borrar el
        # rastro de que esa pregunta se hizo. El hueco de conocimiento sigue
        # existiendo aunque quien lo encontro ya no trabaje aqui.
        sa.Column("usuario_id", sa.Integer(),
                  sa.ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True),
        sa.Column("pregunta", sa.Text(), nullable=False),
        sa.Column("categoria", sa.String(50), nullable=True),
        sa.Column("pasajes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("mejor_similitud", sa.Float(), nullable=True),
        sa.Column("mejor_fuente", sa.String(30), nullable=True),
        sa.Column("origen", sa.String(20), nullable=False),
        sa.Column("duracion_ms", sa.Integer(), nullable=True),
        sa.Column("creado_en", sa.DateTime(), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
    )

    # El indice que de verdad se usa: "los huecos de este sitio, los mas
    # recientes primero". Compuesto y no tres sueltos porque esa consulta
    # filtra por los tres campos a la vez y ordena por la fecha.
    op.create_index(
        "ix_consultas_sitio_origen_fecha",
        "consultas_asistente",
        ["sitio_id", "origen", "creado_en"],
    )
    # Para el desglose por categoria de la pantalla de Conciencia.
    op.create_index(
        "ix_consultas_sitio_categoria",
        "consultas_asistente",
        ["sitio_id", "categoria"],
    )


def downgrade() -> None:
    op.drop_index("ix_consultas_sitio_categoria", table_name="consultas_asistente")
    op.drop_index("ix_consultas_sitio_origen_fecha", table_name="consultas_asistente")
    op.drop_table("consultas_asistente")

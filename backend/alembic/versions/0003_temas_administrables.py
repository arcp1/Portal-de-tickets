"""Temas administrables y detección de problemas recurrentes.

Agrega:
  - checklists.pregunta_texto / activo / veces_resolvio / creado_en
  - tabla temas_sugeridos con su índice vectorial

Revision ID: 0003_temas
Revises: 0002_chat_sesiones
Create Date: 2026-08-26
"""

import sqlalchemy as sa
from alembic import op

revision = "0003_temas"
down_revision = "0002_chat_sesiones"
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
    es_postgres = op.get_bind().dialect.name == "postgresql"

    # Igual que 0001 y 0002: sobre una base vacía no hay nada que alterar,
    # create_all() la construye con la forma correcta.
    if not _tiene_tabla("checklists"):
        return

    if not _tiene_columna("checklists", "pregunta_texto"):
        op.add_column("checklists", sa.Column("pregunta_texto", sa.Text(), nullable=True))

    if not _tiene_columna("checklists", "activo"):
        op.add_column(
            "checklists",
            sa.Column("activo", sa.Boolean(), nullable=False, server_default=sa.true()),
        )

    if not _tiene_columna("checklists", "veces_resolvio"):
        op.add_column(
            "checklists",
            sa.Column("veces_resolvio", sa.Integer(), nullable=False, server_default=sa.text("0")),
        )

    if not _tiene_columna("checklists", "creado_en"):
        op.add_column("checklists", sa.Column("creado_en", sa.DateTime(), nullable=True))

    if not _tiene_tabla("temas_sugeridos"):
        columnas = [
            sa.Column("id", sa.Integer(), primary_key=True, index=True),
            sa.Column("sitio_id", sa.Integer(), sa.ForeignKey("sitios.id"), nullable=False),
            sa.Column("titulo", sa.String(length=200), nullable=False),
            sa.Column("descripcion_ejemplo", sa.Text(), nullable=False),
            sa.Column("categoria_sugerida", sa.String(length=50), nullable=True),
            sa.Column("ocurrencias", sa.Integer(), nullable=False, server_default=sa.text("1")),
            sa.Column("estado", sa.String(length=20), nullable=False, server_default="pendiente"),
            sa.Column("primera_vez", sa.DateTime(), nullable=True),
            sa.Column("ultima_vez", sa.DateTime(), nullable=True),
        ]
        if es_postgres:
            from pgvector.sqlalchemy import Vector
            columnas.insert(5, sa.Column("embedding", Vector(768), nullable=True))
        else:
            columnas.insert(5, sa.Column("embedding", sa.Text(), nullable=True))

        op.create_table("temas_sugeridos", *columnas)

    if es_postgres:
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_temas_sugeridos_embedding "
            "ON temas_sugeridos USING ivfflat (embedding vector_cosine_ops) "
            "WITH (lists = 100);"
        )


def downgrade():
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_temas_sugeridos_embedding;")

    if _tiene_tabla("temas_sugeridos"):
        op.drop_table("temas_sugeridos")

    for columna in ("creado_en", "veces_resolvio", "activo", "pregunta_texto"):
        if _tiene_columna("checklists", columna):
            op.drop_column("checklists", columna)

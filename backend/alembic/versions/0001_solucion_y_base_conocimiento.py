"""Solución obligatoria al cerrar y base de conocimiento con feedback.

Agrega:
  - tickets.solucion / tickets.indexado_kb
  - contadores de utilidad en base_conocimiento
  - tabla sugerencias_kb
  - índice ivfflat para pgvector

La migración es idempotente porque ``main.py`` todavía llama a
``Base.metadata.create_all()`` en el arranque: en una base nueva las tablas y
columnas pueden existir ya, y en una base que viene de la Fase 1 no. Se
inspecciona antes de crear para que funcione en ambos casos.

Revision ID: 0001_solucion_kb
Revises:
Create Date: 2026-08-25
"""

import sqlalchemy as sa
from alembic import op

revision = "0001_solucion_kb"
down_revision = None
branch_labels = None
depends_on = None


def _inspector():
    return sa.inspect(op.get_bind())


def _tiene_tabla(nombre):
    return nombre in _inspector().get_table_names()


def _tiene_columna(tabla, columna):
    if not _tiene_tabla(tabla):
        return False
    return columna in {col["name"] for col in _inspector().get_columns(tabla)}


def upgrade():
    bind = op.get_bind()
    es_postgres = bind.dialect.name == "postgresql"

    if es_postgres:
        op.execute("CREATE EXTENSION IF NOT EXISTS vector;")

    # En este proyecto el esquema base todavía lo construye
    # ``Base.metadata.create_all()`` en el arranque de main.py; esta migración
    # solo aporta el delta para las bases que vienen de la Fase 1.
    # Si la base está vacía no hay nada que alterar: create_all va a crear las
    # tablas ya con estas columnas.
    if not _tiene_tabla("tickets"):
        return

    # --- tickets ---
    if not _tiene_columna("tickets", "solucion"):
        op.add_column("tickets", sa.Column("solucion", sa.Text(), nullable=True))

    if not _tiene_columna("tickets", "indexado_kb"):
        op.add_column(
            "tickets",
            sa.Column("indexado_kb", sa.Boolean(), nullable=False, server_default=sa.false()),
        )

    # --- base_conocimiento ---
    for columna, tipo, defecto in (
        ("veces_sugerida", sa.Integer(), sa.text("0")),
        ("veces_util", sa.Integer(), sa.text("0")),
    ):
        if not _tiene_columna("base_conocimiento", columna):
            op.add_column(
                "base_conocimiento",
                sa.Column(columna, tipo, nullable=False, server_default=defecto),
            )

    if not _tiene_columna("base_conocimiento", "ultima_sugerencia"):
        op.add_column(
            "base_conocimiento",
            sa.Column("ultima_sugerencia", sa.DateTime(), nullable=True),
        )

    # --- sugerencias_kb ---
    if not _tiene_tabla("sugerencias_kb"):
        op.create_table(
            "sugerencias_kb",
            sa.Column("id", sa.Integer(), primary_key=True, index=True),
            sa.Column("ticket_id", sa.Integer(), sa.ForeignKey("tickets.id"), nullable=True),
            sa.Column("kb_id", sa.Integer(), sa.ForeignKey("base_conocimiento.id"), nullable=False),
            sa.Column("usuario_id", sa.Integer(), sa.ForeignKey("usuarios.id"), nullable=True),
            sa.Column("similitud", sa.Float(), nullable=False),
            sa.Column("fue_util", sa.Boolean(), nullable=True),
            sa.Column("creado_en", sa.DateTime(), nullable=True),
        )

    # --- índice vectorial ---
    # Sin él la búsqueda hace escaneo completo. Con pocos registros ni se nota;
    # con miles se arrastra.
    if es_postgres:
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_base_conocimiento_embedding "
            "ON base_conocimiento USING ivfflat (embedding vector_cosine_ops) "
            "WITH (lists = 100);"
        )


def downgrade():
    bind = op.get_bind()
    es_postgres = bind.dialect.name == "postgresql"

    if es_postgres:
        op.execute("DROP INDEX IF EXISTS ix_base_conocimiento_embedding;")

    if _tiene_tabla("sugerencias_kb"):
        op.drop_table("sugerencias_kb")

    for columna in ("ultima_sugerencia", "veces_util", "veces_sugerida"):
        if _tiene_columna("base_conocimiento", columna):
            op.drop_column("base_conocimiento", columna)

    for columna in ("indexado_kb", "solucion"):
        if _tiene_columna("tickets", columna):
            op.drop_column("tickets", columna)

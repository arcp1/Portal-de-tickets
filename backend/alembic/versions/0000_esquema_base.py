"""Esquema base de la Fase 1.

Hasta ahora el esquema lo construía ``Base.metadata.create_all()`` en el
arranque de la aplicación, y Alembic solo aportaba los deltas. Eso dejaba dos
fuentes de verdad compitiendo: sobre una base nueva las tablas existían sin que
Alembic lo supiera, y sobre una base existente las migraciones no se aplicaban
solas. Ya causó una falla real (la 0003 no se aplicó y el seed reventó).

Esta migración crea el esquema de la Fase 1 para que Alembic sea la única
fuente de verdad. Es idempotente: si las tablas ya existen —porque vienen de
una base creada con create_all()— no hace nada y solo deja la revisión
registrada.

Revision ID: 0000_esquema_base
Revises:
Create Date: 2026-08-26
"""

import sqlalchemy as sa
from alembic import op

revision = "0000_esquema_base"
down_revision = None
branch_labels = None
depends_on = None


def _tablas():
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade():
    bind = op.get_bind()
    es_postgres = bind.dialect.name == "postgresql"

    if es_postgres:
        op.execute("CREATE EXTENSION IF NOT EXISTS vector;")

    existentes = _tablas()

    # Base que ya venía de create_all(): no hay nada que construir, solo
    # registrar que a partir de aquí manda Alembic.
    if "tickets" in existentes:
        return

    if es_postgres:
        from pgvector.sqlalchemy import Vector
        tipo_vector = Vector(768)
    else:
        tipo_vector = sa.Text()

    op.create_table(
        "sitios",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("clave", sa.String(length=10), unique=True, index=True, nullable=False),
        sa.Column("nombre", sa.String(length=100), nullable=False),
        sa.Column("pais", sa.String(length=50), nullable=False, server_default="México"),
        sa.Column("activo", sa.Boolean(), server_default=sa.true()),
    )

    op.create_table(
        "usuarios",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("sitio_id", sa.Integer(), sa.ForeignKey("sitios.id"), nullable=False),
        sa.Column("nombre", sa.String(length=100), nullable=False),
        sa.Column("email", sa.String(length=100), unique=True, index=True, nullable=False),
        sa.Column("rol", sa.String(length=20), nullable=False, server_default="usuario"),
        sa.Column("area", sa.String(length=50), nullable=True),
        sa.Column("idioma_preferido", sa.String(length=5), server_default="es"),
        sa.Column("activo", sa.Boolean(), server_default=sa.true()),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
    )

    op.create_table(
        "equipos",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("sitio_id", sa.Integer(), sa.ForeignKey("sitios.id"), nullable=False),
        sa.Column("tipo", sa.String(length=20), nullable=False),
        sa.Column("categoria", sa.String(length=50), nullable=False),
        sa.Column("marca", sa.String(length=50), nullable=False),
        sa.Column("modelo", sa.String(length=50), nullable=False),
        sa.Column("numero_serie", sa.String(length=100), nullable=True, index=True),
        sa.Column("ubicacion", sa.String(length=100), nullable=True),
        sa.Column("estado", sa.String(length=20), server_default="disponible"),
        sa.Column("asignado_a", sa.Integer(), sa.ForeignKey("usuarios.id"), nullable=True),
        sa.Column("fecha_asignacion", sa.DateTime(), nullable=True),
        sa.Column("notas", sa.Text(), nullable=True),
    )

    op.create_table(
        "tickets",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("sitio_id", sa.Integer(), sa.ForeignKey("sitios.id"), nullable=False),
        sa.Column("folio", sa.String(length=30), unique=True, index=True, nullable=False),
        sa.Column("usuario_id", sa.Integer(), sa.ForeignKey("usuarios.id"), nullable=False),
        sa.Column("equipo_id", sa.Integer(), sa.ForeignKey("equipos.id"), nullable=True),
        sa.Column("categoria", sa.String(length=50), nullable=False),
        sa.Column("subcategoria", sa.String(length=50), nullable=True),
        sa.Column("descripcion_original", sa.Text(), nullable=False),
        sa.Column("descripcion_normalizada", sa.Text(), nullable=True),
        sa.Column("prioridad", sa.String(length=20), server_default="media"),
        sa.Column("estado", sa.String(length=30), server_default="abierto"),
        sa.Column("asignado_a", sa.Integer(), sa.ForeignKey("usuarios.id"), nullable=True),
        sa.Column("canal_resolucion", sa.String(length=30), nullable=True),
        sa.Column("creado_en", sa.DateTime(), nullable=True),
        sa.Column("resuelto_en", sa.DateTime(), nullable=True),
        sa.Column("tiempo_resolucion", sa.Integer(), nullable=True),
    )

    op.create_table(
        "ticket_comentarios",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("ticket_id", sa.Integer(), sa.ForeignKey("tickets.id"), nullable=False),
        sa.Column("autor_id", sa.Integer(), sa.ForeignKey("usuarios.id"), nullable=False),
        sa.Column("comentario", sa.Text(), nullable=False),
        sa.Column("es_interno", sa.Boolean(), server_default=sa.false()),
        sa.Column("creado_en", sa.DateTime(), nullable=True),
    )

    op.create_table(
        "base_conocimiento",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("sitio_id", sa.Integer(), sa.ForeignKey("sitios.id"), nullable=False),
        sa.Column("titulo", sa.String(length=150), nullable=False),
        sa.Column("contenido", sa.Text(), nullable=False),
        sa.Column("categoria", sa.String(length=50), nullable=False),
        sa.Column("tags", sa.String(length=200), nullable=True),
        sa.Column("embedding", tipo_vector, nullable=True),
        sa.Column("ticket_origen_id", sa.Integer(), sa.ForeignKey("tickets.id"), nullable=True),
        sa.Column("creado_en", sa.DateTime(), nullable=True),
    )

    op.create_table(
        "checklists",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("categoria", sa.String(length=50), nullable=False),
        sa.Column("orden", sa.Integer(), server_default=sa.text("1")),
        sa.Column("pregunta_key", sa.String(length=100), nullable=False),
        sa.Column("accion_si_no", sa.Text(), nullable=True),
        sa.Column("resuelve", sa.Boolean(), server_default=sa.false()),
    )

    op.create_table(
        "reglas_negocio",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("sitio_id", sa.Integer(), sa.ForeignKey("sitios.id"), nullable=False),
        sa.Column("categoria", sa.String(length=50), nullable=False),
        sa.Column("condicion", sa.String(length=100), nullable=False),
        sa.Column("accion", sa.String(length=30), nullable=False),
        sa.Column("destinatario", sa.String(length=100), nullable=True),
        sa.Column("activa", sa.Boolean(), server_default=sa.true()),
    )

    op.create_table(
        "consumo_ia",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("usuario_id", sa.Integer(), sa.ForeignKey("usuarios.id"), nullable=False),
        sa.Column("ticket_id", sa.Integer(), sa.ForeignKey("tickets.id"), nullable=True),
        sa.Column("tokens_entrada", sa.Integer(), server_default=sa.text("0")),
        sa.Column("tokens_salida", sa.Integer(), server_default=sa.text("0")),
        sa.Column("modelo", sa.String(length=50), nullable=False),
        sa.Column("costo_estimado", sa.Float(), server_default=sa.text("0")),
        sa.Column("creado_en", sa.DateTime(), nullable=True),
    )


def downgrade():
    for tabla in (
        "consumo_ia", "reglas_negocio", "checklists", "base_conocimiento",
        "ticket_comentarios", "tickets", "equipos", "usuarios", "sitios",
    ):
        if tabla in _tablas():
            op.drop_table(tabla)

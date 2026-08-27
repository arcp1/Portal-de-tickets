"""Activación de cuentas y documentación interna de TI.

Cambia el modelo de acceso: TI da de alta a la persona sin contraseña y le
entrega un código de un solo uso; la persona define su propia contraseña. TI
deja de conocer contraseñas ajenas.

Revision ID: 0007_cuentas_docti
Revises: 0006_resguardos
Create Date: 2026-08-27
"""

import sqlalchemy as sa
from alembic import op

revision = "0007_cuentas_docti"
down_revision = "0006_resguardos"
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

    # --- Cuentas ---
    if not _tiene_columna("usuarios", "estado_cuenta"):
        op.add_column("usuarios", sa.Column(
            "estado_cuenta", sa.String(length=25), nullable=False,
            server_default="pendiente_activacion",
        ))
        op.create_index("ix_usuarios_estado_cuenta", "usuarios", ["estado_cuenta"])

    for columna, tipo in (
        ("codigo_activacion_hash", sa.String(length=255)),
        ("codigo_expira", sa.DateTime()),
        ("ultimo_acceso", sa.DateTime()),
        ("creado_en", sa.DateTime()),
    ):
        if not _tiene_columna("usuarios", columna):
            op.add_column("usuarios", sa.Column(columna, tipo, nullable=True))

    if not _tiene_columna("usuarios", "debe_cambiar_password"):
        op.add_column("usuarios", sa.Column(
            "debe_cambiar_password", sa.Boolean(), nullable=False, server_default=sa.false(),
        ))

    # Las cuentas que ya existían tienen contraseña: quedan activas. Si se
    # dejaran como pendientes, nadie podría entrar tras el despliegue.
    op.execute(
        "UPDATE usuarios SET estado_cuenta = 'activa' "
        "WHERE password_hash IS NOT NULL AND password_hash <> ''"
    )
    op.execute("UPDATE usuarios SET creado_en = CURRENT_TIMESTAMP WHERE creado_en IS NULL")

    # password_hash pasa a ser opcional: una cuenta recién dada de alta no
    # tiene contraseña hasta que su dueño la define.
    if _tiene_columna("usuarios", "password_hash"):
        op.alter_column("usuarios", "password_hash",
                        existing_type=sa.String(length=255), nullable=True)

    # --- Documentación de TI ---
    if not _tiene_tabla("documentos_ti"):
        if es_postgres:
            from pgvector.sqlalchemy import Vector
            tipo_vector = Vector(768)
        else:
            tipo_vector = sa.Text()

        op.create_table(
            "documentos_ti",
            sa.Column("id", sa.Integer(), primary_key=True, index=True),
            sa.Column("sitio_id", sa.Integer(), sa.ForeignKey("sitios.id"), nullable=False),
            sa.Column("categoria", sa.String(length=40), nullable=False),
            sa.Column("titulo", sa.String(length=200), nullable=False),
            sa.Column("contenido", sa.Text(), nullable=False),
            sa.Column("etiquetas", sa.String(length=300), nullable=True),
            sa.Column("sensible", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("embedding", tipo_vector, nullable=True),
            sa.Column("creado_por", sa.Integer(), sa.ForeignKey("usuarios.id"), nullable=False),
            sa.Column("actualizado_por", sa.Integer(), sa.ForeignKey("usuarios.id"), nullable=True),
            sa.Column("creado_en", sa.DateTime(), nullable=True),
            sa.Column("actualizado_en", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_docti_sitio", "documentos_ti", ["sitio_id"])
        op.create_index("ix_docti_categoria", "documentos_ti", ["categoria"])

        if es_postgres:
            op.execute(
                "CREATE INDEX IF NOT EXISTS ix_docti_embedding "
                "ON documentos_ti USING ivfflat (embedding vector_cosine_ops) "
                "WITH (lists = 100);"
            )


def downgrade():
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_docti_embedding;")
    if _tiene_tabla("documentos_ti"):
        op.drop_table("documentos_ti")

    for columna in ("debe_cambiar_password", "creado_en", "ultimo_acceso",
                    "codigo_expira", "codigo_activacion_hash", "estado_cuenta"):
        if _tiene_columna("usuarios", columna):
            op.drop_column("usuarios", columna)

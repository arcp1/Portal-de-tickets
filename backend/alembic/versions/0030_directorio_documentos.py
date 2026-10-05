"""Directorio de documentos: carpetas, archivos y versiones.

Un árbol de carpetas para lo que hoy anda en correos y memorias USB:
manuales de equipos, formatos, planos, hojas de cálculo de inventario. No es
el expediente de una persona (`documentos_usuario`), que tiene otras reglas:
aquí lo sube TI y lo lee quien la carpeta deje.

**La ruta va materializada** (`ruta = '/1/7/12/'`) y no con `ltree`: el rol de
la aplicación (M-2) no puede crear extensiones, y para lo que se pregunta
—«¿qué hay debajo de esta carpeta?», «¿esta carpeta está dentro de aquella?»—
basta un prefijo de texto con su índice `text_pattern_ops`. Mover una
carpeta es un solo UPDATE del prefijo de su subárbol.

**La visibilidad solo la llevan las carpetas de primer nivel** y las de
debajo la heredan. Una restricción lo obliga: una raíz siempre la tiene y una
subcarpeta nunca. Así no hay que resolver qué pasa si una subcarpeta dice
«todos» dentro de una raíz que dice «solo TI».

**Los nombres se repiten sin distinguir mayúsculas, pero solo entre lo vivo.**
Los índices únicos son parciales (`WHERE eliminado_en IS NULL`): lo que está
en la papelera no le quita el nombre a nadie.

Revision ID: 0030_directorio_documentos
Revises: 0029_imagenes_soluciones
"""

import sqlalchemy as sa
from alembic import op

revision = "0030_directorio_documentos"
down_revision = "0029_imagenes_soluciones"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Ver la 0016: con límite, un bloqueo hace fallar la migración en vez de
    # encolar detrás de ella todas las consultas del portal.
    op.execute("SET lock_timeout = '10s'")

    op.create_table(
        "carpetas",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("padre_id", sa.Integer(),
                  sa.ForeignKey("carpetas.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("nombre", sa.String(120), nullable=False),
        sa.Column("ruta", sa.Text(), nullable=False),
        sa.Column("profundidad", sa.SmallInteger(), nullable=False),
        sa.Column("visibilidad", sa.String(10), nullable=True),
        sa.Column("descripcion", sa.Text(), nullable=True),
        sa.Column("creado_por", sa.Integer(), sa.ForeignKey("usuarios.id"), nullable=True),
        sa.Column("creado_en", sa.DateTime(), nullable=False),
        sa.Column("actualizado_en", sa.DateTime(), nullable=False),
        sa.Column("eliminado_en", sa.DateTime(), nullable=True),
        sa.Column("eliminado_por", sa.Integer(), sa.ForeignKey("usuarios.id"), nullable=True),
        sa.CheckConstraint("profundidad BETWEEN 1 AND 8", name="ck_carpetas_profundidad"),
        sa.CheckConstraint("visibilidad IN ('ti', 'todos', 'plantas')", name="ck_carpetas_visibilidad"),
        sa.CheckConstraint("(padre_id IS NULL) = (visibilidad IS NOT NULL)",
                           name="ck_carpetas_visibilidad_solo_raiz"),
    )
    op.execute(
        "CREATE UNIQUE INDEX ux_carpetas_padre_nombre ON carpetas "
        "(coalesce(padre_id, 0), lower(nombre)) WHERE eliminado_en IS NULL"
    )
    op.execute("CREATE INDEX ix_carpetas_ruta ON carpetas (ruta text_pattern_ops)")
    op.create_index("ix_carpetas_padre_id", "carpetas", ["padre_id"])

    op.create_table(
        "carpeta_plantas",
        sa.Column("carpeta_id", sa.Integer(),
                  sa.ForeignKey("carpetas.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("sitio_id", sa.Integer(),
                  sa.ForeignKey("sitios.id"), primary_key=True),
    )

    op.create_table(
        "archivos",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("carpeta_id", sa.Integer(),
                  sa.ForeignKey("carpetas.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("nombre", sa.String(255), nullable=False),
        sa.Column("tipo_mime", sa.String(100), nullable=False),
        sa.Column("tamano_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.CHAR(64), nullable=False),
        sa.Column("nombre_guardado", sa.String(64), nullable=False, unique=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("descripcion", sa.Text(), nullable=True),
        sa.Column("subido_por", sa.Integer(), sa.ForeignKey("usuarios.id"), nullable=True),
        sa.Column("creado_en", sa.DateTime(), nullable=False),
        sa.Column("actualizado_en", sa.DateTime(), nullable=False),
        sa.Column("eliminado_en", sa.DateTime(), nullable=True),
        sa.Column("eliminado_por", sa.Integer(), sa.ForeignKey("usuarios.id"), nullable=True),
    )
    op.execute(
        "CREATE UNIQUE INDEX ux_archivos_carpeta_nombre ON archivos "
        "(carpeta_id, lower(nombre)) WHERE eliminado_en IS NULL"
    )
    op.create_index("ix_archivos_carpeta_id", "archivos", ["carpeta_id"])

    op.create_table(
        "archivo_versiones",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("archivo_id", sa.Integer(),
                  sa.ForeignKey("archivos.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("nombre_guardado", sa.String(64), nullable=False, unique=True),
        sa.Column("tipo_mime", sa.String(100), nullable=False),
        sa.Column("tamano_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.CHAR(64), nullable=False),
        sa.Column("subido_por", sa.Integer(), sa.ForeignKey("usuarios.id"), nullable=True),
        sa.Column("creado_en", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("archivo_id", "version", name="uq_archivo_versiones_archivo_version"),
    )


def downgrade() -> None:
    op.drop_table("archivo_versiones")
    op.execute("DROP INDEX IF EXISTS ux_archivos_carpeta_nombre")
    op.drop_index("ix_archivos_carpeta_id", table_name="archivos")
    op.drop_table("archivos")
    op.drop_table("carpeta_plantas")
    op.execute("DROP INDEX IF EXISTS ux_carpetas_padre_nombre")
    op.execute("DROP INDEX IF EXISTS ix_carpetas_ruta")
    op.drop_index("ix_carpetas_padre_id", table_name="carpetas")
    op.drop_table("carpetas")

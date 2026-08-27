"""Bitácora de auditoría e índices en llaves foráneas.

Dos cosas distintas que van juntas porque ambas son de "que aguante volumen
real":

  - Tabla `auditoria`: la spec §12 pide bitácora de acciones administrativas.
  - Índices: ninguna llave foránea los tenía, así que cada listado de tickets
    hacía escaneo secuencial. Con cien tickets no se nota; con veinte mil sí.

Revision ID: 0005_auditoria_indices
Revises: 0004_adjuntos_sla
Create Date: 2026-08-26
"""

import sqlalchemy as sa
from alembic import op

revision = "0005_auditoria_indices"
down_revision = "0004_adjuntos_sla"
branch_labels = None
depends_on = None


def _inspector():
    return sa.inspect(op.get_bind())


def _tiene_tabla(nombre):
    return nombre in _inspector().get_table_names()


def _indices(tabla):
    if not _tiene_tabla(tabla):
        return set()
    return {i["name"] for i in _inspector().get_indexes(tabla)}


# (tabla, columnas, nombre)
INDICES = [
    # Los listados siempre filtran por sitio y ordenan por fecha.
    ("tickets", ["sitio_id", "creado_en"], "ix_tickets_sitio_creado"),
    # "mis tickets" del usuario normal.
    ("tickets", ["usuario_id"], "ix_tickets_usuario"),
    # Filtros del tablero.
    ("tickets", ["estado"], "ix_tickets_estado"),
    ("tickets", ["categoria"], "ix_tickets_categoria"),
    # Historial por equipo.
    ("tickets", ["equipo_id"], "ix_tickets_equipo"),
    # Cola de trabajo del técnico y vencimientos.
    ("tickets", ["asignado_a"], "ix_tickets_asignado"),
    ("tickets", ["vence_en"], "ix_tickets_vence"),
    # El detalle del ticket carga sus comentarios.
    ("ticket_comentarios", ["ticket_id"], "ix_comentarios_ticket"),
    # Métricas de utilidad.
    ("sugerencias_kb", ["kb_id"], "ix_sugerencias_kb"),
    ("sugerencias_kb", ["creado_en"], "ix_sugerencias_creado"),
    # Búsqueda en la base de conocimiento por sitio y categoría.
    ("base_conocimiento", ["sitio_id", "categoria"], "ix_kb_sitio_categoria"),
    # Inventario por sitio.
    ("equipos", ["sitio_id"], "ix_equipos_sitio"),
    ("equipos", ["asignado_a"], "ix_equipos_asignado"),
    # Checklists por categoría, que es como siempre se piden.
    ("checklists", ["categoria", "activo"], "ix_checklists_categoria"),
    # Sesiones de chat del usuario.
    ("chat_sesiones", ["usuario_id"], "ix_chat_usuario"),
]


def upgrade():
    if not _tiene_tabla("auditoria"):
        es_postgres = op.get_bind().dialect.name == "postgresql"
        from sqlalchemy.dialects.postgresql import JSONB

        op.create_table(
            "auditoria",
            sa.Column("id", sa.Integer(), primary_key=True, index=True),
            sa.Column("usuario_id", sa.Integer(), sa.ForeignKey("usuarios.id"), nullable=False),
            sa.Column("accion", sa.String(length=50), nullable=False),
            sa.Column("entidad", sa.String(length=50), nullable=False),
            sa.Column("entidad_id", sa.Integer(), nullable=True),
            sa.Column("detalle", JSONB() if es_postgres else sa.JSON(), nullable=True),
            sa.Column("ip", sa.String(length=45), nullable=True),
            sa.Column("creado_en", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_auditoria_usuario", "auditoria", ["usuario_id"])
        op.create_index("ix_auditoria_accion", "auditoria", ["accion"])
        op.create_index("ix_auditoria_creado", "auditoria", ["creado_en"])

    for tabla, columnas, nombre in INDICES:
        if not _tiene_tabla(tabla):
            continue
        if nombre in _indices(tabla):
            continue
        op.create_index(nombre, tabla, columnas)


def downgrade():
    for tabla, _, nombre in INDICES:
        if _tiene_tabla(tabla) and nombre in _indices(tabla):
            op.drop_index(nombre, table_name=tabla)

    if _tiene_tabla("auditoria"):
        op.drop_table("auditoria")

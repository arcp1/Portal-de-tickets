"""Resguardos de equipo, movimientos de activo y expediente de la persona.

El portal deja de ser solo de tickets: concentra también quién responde por qué
activo y qué documentos tiene firmados cada quien.

Revision ID: 0006_resguardos
Revises: 0005_auditoria_indices
Create Date: 2026-08-26
"""

import sqlalchemy as sa
from alembic import op

revision = "0006_resguardos"
down_revision = "0005_auditoria_indices"
branch_labels = None
depends_on = None


def _tablas():
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade():
    existentes = _tablas()

    if "resguardos" not in existentes:
        op.create_table(
            "resguardos",
            sa.Column("id", sa.Integer(), primary_key=True, index=True),
            sa.Column("folio", sa.String(length=30), nullable=False, unique=True),
            sa.Column("sitio_id", sa.Integer(), sa.ForeignKey("sitios.id"), nullable=False),
            sa.Column("usuario_id", sa.Integer(), sa.ForeignKey("usuarios.id"), nullable=False),
            sa.Column("equipo_id", sa.Integer(), sa.ForeignKey("equipos.id"), nullable=False),
            sa.Column("creado_por", sa.Integer(), sa.ForeignKey("usuarios.id"), nullable=False),
            sa.Column("estado", sa.String(length=20), nullable=False, server_default="pendiente_firma"),
            sa.Column("condiciones", sa.Text(), nullable=False),
            sa.Column("accesorios", sa.Text(), nullable=True),
            sa.Column("observaciones_entrega", sa.Text(), nullable=True),
            sa.Column("observaciones_devolucion", sa.Text(), nullable=True),
            sa.Column("entregado_en", sa.DateTime(), nullable=True),
            sa.Column("firmado_en", sa.DateTime(), nullable=True),
            sa.Column("firma_nombre", sa.String(length=150), nullable=True),
            sa.Column("firma_ip", sa.String(length=45), nullable=True),
            sa.Column("devuelto_en", sa.DateTime(), nullable=True),
            sa.Column("recibido_por", sa.Integer(), sa.ForeignKey("usuarios.id"), nullable=True),
            sa.Column("creado_en", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_resguardos_folio", "resguardos", ["folio"], unique=True)
        op.create_index("ix_resguardos_usuario", "resguardos", ["usuario_id"])
        op.create_index("ix_resguardos_equipo", "resguardos", ["equipo_id"])
        op.create_index("ix_resguardos_estado", "resguardos", ["estado"])
        op.create_index("ix_resguardos_sitio", "resguardos", ["sitio_id"])

    if "movimientos_equipo" not in existentes:
        op.create_table(
            "movimientos_equipo",
            sa.Column("id", sa.Integer(), primary_key=True, index=True),
            sa.Column("equipo_id", sa.Integer(), sa.ForeignKey("equipos.id"), nullable=False),
            sa.Column("tipo", sa.String(length=20), nullable=False),
            sa.Column("usuario_id", sa.Integer(), sa.ForeignKey("usuarios.id"), nullable=True),
            sa.Column("resguardo_id", sa.Integer(), sa.ForeignKey("resguardos.id"), nullable=True),
            sa.Column("estado_anterior", sa.String(length=20), nullable=True),
            sa.Column("estado_nuevo", sa.String(length=20), nullable=True),
            sa.Column("nota", sa.Text(), nullable=True),
            sa.Column("realizado_por", sa.Integer(), sa.ForeignKey("usuarios.id"), nullable=False),
            sa.Column("creado_en", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_movimientos_equipo", "movimientos_equipo", ["equipo_id"])
        op.create_index("ix_movimientos_tipo", "movimientos_equipo", ["tipo"])
        op.create_index("ix_movimientos_creado", "movimientos_equipo", ["creado_en"])

    if "documentos_usuario" not in existentes:
        op.create_table(
            "documentos_usuario",
            sa.Column("id", sa.Integer(), primary_key=True, index=True),
            sa.Column("usuario_id", sa.Integer(), sa.ForeignKey("usuarios.id"), nullable=False),
            sa.Column("sitio_id", sa.Integer(), sa.ForeignKey("sitios.id"), nullable=False),
            sa.Column("tipo", sa.String(length=30), nullable=False),
            sa.Column("titulo", sa.String(length=200), nullable=False),
            sa.Column("descripcion", sa.Text(), nullable=True),
            sa.Column("resguardo_id", sa.Integer(), sa.ForeignKey("resguardos.id"), nullable=True),
            sa.Column("nombre_original", sa.String(length=255), nullable=False),
            sa.Column("nombre_guardado", sa.String(length=255), nullable=False, unique=True),
            sa.Column("tipo_mime", sa.String(length=100), nullable=False),
            sa.Column("tamano_bytes", sa.Integer(), nullable=False),
            sa.Column("vigente_hasta", sa.DateTime(), nullable=True),
            sa.Column("subido_por", sa.Integer(), sa.ForeignKey("usuarios.id"), nullable=False),
            sa.Column("creado_en", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_documentos_usuario", "documentos_usuario", ["usuario_id"])
        op.create_index("ix_documentos_tipo", "documentos_usuario", ["tipo"])

    # Los equipos que ya estaban asignados antes de que existieran los
    # resguardos no tienen historial. Se les registra un movimiento de alta para
    # que su bitácora no empiece en blanco.
    if "movimientos_equipo" in _tablas():
        op.execute(
            """
            INSERT INTO movimientos_equipo
                (equipo_id, tipo, usuario_id, estado_nuevo, nota, realizado_por, creado_en)
            SELECT e.id, 'alta', e.asignado_a, e.estado,
                   'Registro inicial al implementar el control de resguardos',
                   (SELECT id FROM usuarios WHERE rol = 'admin' ORDER BY id LIMIT 1),
                   COALESCE(e.fecha_asignacion, CURRENT_TIMESTAMP)
              FROM equipos e
             WHERE EXISTS (SELECT 1 FROM usuarios WHERE rol = 'admin')
               AND NOT EXISTS (
                   SELECT 1 FROM movimientos_equipo m WHERE m.equipo_id = e.id
               )
            """
        )


def downgrade():
    for tabla in ("documentos_usuario", "movimientos_equipo", "resguardos"):
        if tabla in _tablas():
            op.drop_table(tabla)

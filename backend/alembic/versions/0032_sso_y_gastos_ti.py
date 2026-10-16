"""Inicio de sesión con Microsoft y el módulo de Gastos de TI.

**Microsoft.** `usuarios.microsoft_oid`: el identificador de la cuenta de
Microsoft de cada persona, vacío para todos. Se rellena solo la primera vez
que alguien entra con Microsoft y su correo coincide con el del portal (ver
app/services/sso_microsoft.py). Único, para que una cuenta de Microsoft no
abra dos cuentas del portal.

`auditoria.usuario_id` deja de ser obligatorio: un intento de entrar con
Microsoft con un correo que el portal no conoce no tiene cuenta a quien
atribuírselo, y también tiene que quedar en la bitácora. Todas las filas que
ya existen lo tienen; ninguna cambia.

**Gastos de TI.** Cinco tablas nuevas, con prefijo `gasto_` para no chocar
con nada: categorías, proveedores, gastos, presupuesto anual por categoría y
comprobantes del expediente (los binarios van a `documentos/gastos/`). Se
siembran las ocho categorías con las que arrancaba la aplicación original.
No hay datos que traer de ella: su base solo tenía un gasto de prueba.

**Todo lo puede hacer el rol de la aplicación (M-2)**, que es dueño de
`usuarios` y `auditoria`: tablas e índices nuevos, una columna sin valor por
omisión (no reescribe la tabla) y quitar un NOT NULL. Ninguna extensión.

Revision ID: 0032_sso_y_gastos_ti
Revises: 0031_aceptacion_terminos
"""

import sqlalchemy as sa
from alembic import op

revision = "0032_sso_y_gastos_ti"
down_revision = "0031_aceptacion_terminos"
branch_labels = None
depends_on = None

CATEGORIAS_INICIALES = (
    "Arrendamiento de equipo", "Telefonía y líneas", "Internet y enlaces",
    "Licencias y software", "Hardware y refacciones", "Mantenimiento del site",
    "Servicios profesionales", "Otros",
)


def upgrade() -> None:
    # Ver la 0016: con límite, un bloqueo hace fallar la migración en vez de
    # encolar detrás de ella todas las consultas del portal.
    op.execute("SET lock_timeout = '10s'")

    # --- Microsoft ---
    op.add_column("usuarios", sa.Column("microsoft_oid", sa.String(length=36), nullable=True))
    op.create_index("ux_usuarios_microsoft_oid", "usuarios", ["microsoft_oid"], unique=True)
    op.alter_column("auditoria", "usuario_id", existing_type=sa.Integer(), nullable=True)

    # --- Gastos ---
    op.create_table(
        "gasto_categorias",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("nombre", sa.String(80), nullable=False),
        sa.Column("activa", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("creado_en", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
    )
    op.execute("CREATE UNIQUE INDEX ux_gasto_categorias_nombre ON gasto_categorias (lower(nombre))")

    op.create_table(
        "gasto_proveedores",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("nombre", sa.String(150), nullable=False),
        sa.Column("rfc", sa.String(13), nullable=True),
        sa.Column("creado_en", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
    )
    op.execute("CREATE UNIQUE INDEX ux_gasto_proveedores_nombre ON gasto_proveedores (lower(nombre))")
    op.execute("CREATE UNIQUE INDEX ux_gasto_proveedores_rfc ON gasto_proveedores (rfc) "
               "WHERE rfc IS NOT NULL")

    op.create_table(
        "gastos",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("fecha", sa.Date(), nullable=False),
        sa.Column("concepto", sa.String(200), nullable=False),
        sa.Column("categoria_id", sa.Integer(),
                  sa.ForeignKey("gasto_categorias.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("proveedor_id", sa.Integer(),
                  sa.ForeignKey("gasto_proveedores.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("tipo_compra", sa.String(10), nullable=False, server_default="proveedor"),
        sa.Column("referencia", sa.String(60), nullable=True),
        sa.Column("cantidad", sa.Numeric(12, 2), nullable=False, server_default="1"),
        sa.Column("moneda", sa.CHAR(3), nullable=False, server_default="MXN"),
        sa.Column("tipo_cambio", sa.Numeric(12, 6), nullable=False, server_default="1"),
        sa.Column("subtotal", sa.Numeric(14, 2), nullable=False),
        sa.Column("tasa_iva", sa.Numeric(5, 4), nullable=False, server_default="0.16"),
        sa.Column("iva", sa.Numeric(14, 2), nullable=False),
        sa.Column("retenciones", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("total", sa.Numeric(14, 2), nullable=False),
        sa.Column("total_mxn", sa.Numeric(14, 2), nullable=False),
        sa.Column("estado", sa.String(10), nullable=False, server_default="pendiente"),
        sa.Column("fecha_pago", sa.Date(), nullable=True),
        sa.Column("centro_costo", sa.String(60), nullable=True),
        sa.Column("notas", sa.Text(), nullable=True),
        sa.Column("sitio_id", sa.Integer(), sa.ForeignKey("sitios.id", ondelete="SET NULL"), nullable=True),
        sa.Column("equipo_id", sa.Integer(), sa.ForeignKey("equipos.id", ondelete="SET NULL"), nullable=True),
        sa.Column("ticket_id", sa.Integer(), sa.ForeignKey("tickets.id", ondelete="SET NULL"), nullable=True),
        sa.Column("responsable_id", sa.Integer(), sa.ForeignKey("usuarios.id"), nullable=True),
        sa.Column("creado_por", sa.Integer(), sa.ForeignKey("usuarios.id"), nullable=True),
        sa.Column("creado_en", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("actualizado_en", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("tipo_compra IN ('proveedor', 'linea')", name="ck_gastos_tipo_compra"),
        sa.CheckConstraint("moneda IN ('MXN', 'USD')", name="ck_gastos_moneda"),
        sa.CheckConstraint("estado IN ('pendiente', 'pagado')", name="ck_gastos_estado"),
        sa.CheckConstraint("cantidad > 0", name="ck_gastos_cantidad"),
        sa.CheckConstraint("tipo_cambio > 0 AND (moneda <> 'MXN' OR tipo_cambio = 1)",
                           name="ck_gastos_tipo_cambio"),
        sa.CheckConstraint("subtotal >= 0 AND iva >= 0 AND retenciones >= 0 AND total >= 0",
                           name="ck_gastos_importes"),
        sa.CheckConstraint("tasa_iva >= 0 AND tasa_iva <= 1", name="ck_gastos_tasa_iva"),
        sa.CheckConstraint("abs(total - (subtotal + iva - retenciones)) < 0.005",
                           name="ck_gastos_total_cuadra"),
        sa.CheckConstraint("(estado = 'pagado') = (fecha_pago IS NOT NULL)",
                           name="ck_gastos_fecha_pago"),
    )
    # Los listados y el resumen filtran por rango de fechas del año: con el
    # índice, `fecha >= '2026-01-01' AND fecha < '2027-01-01'` no recorre la
    # tabla. El original filtraba con `EXTRACT(YEAR FROM fecha)`, que no
    # puede usar ninguno.
    op.create_index("ix_gastos_fecha", "gastos", ["fecha"])
    op.create_index("ix_gastos_categoria_id", "gastos", ["categoria_id"])
    op.create_index("ix_gastos_proveedor_id", "gastos", ["proveedor_id"])
    op.create_index("ix_gastos_sitio_id", "gastos", ["sitio_id"])
    op.create_index("ix_gastos_equipo_id", "gastos", ["equipo_id"])
    op.create_index("ix_gastos_ticket_id", "gastos", ["ticket_id"])

    op.create_table(
        "gasto_presupuestos",
        sa.Column("anio", sa.SmallInteger(), primary_key=True),
        sa.Column("categoria_id", sa.Integer(),
                  sa.ForeignKey("gasto_categorias.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("monto", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("actualizado_por", sa.Integer(), sa.ForeignKey("usuarios.id"), nullable=True),
        sa.Column("actualizado_en", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("monto >= 0", name="ck_gasto_presupuestos_monto"),
    )

    op.create_table(
        "gasto_comprobantes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("gasto_id", sa.Integer(),
                  sa.ForeignKey("gastos.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tipo", sa.String(15), nullable=False),
        sa.Column("folio", sa.String(60), nullable=True),
        sa.Column("fecha", sa.Date(), nullable=True),
        sa.Column("cfdi_uuid", sa.String(36), nullable=True),
        sa.Column("nombre", sa.String(255), nullable=False),
        sa.Column("tipo_mime", sa.String(100), nullable=False),
        sa.Column("tamano_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.CHAR(64), nullable=False),
        sa.Column("nombre_guardado", sa.String(64), nullable=False, unique=True),
        sa.Column("subido_por", sa.Integer(), sa.ForeignKey("usuarios.id"), nullable=True),
        sa.Column("creado_en", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "tipo IN ('cotizacion', 'orden_compra', 'factura', 'albaran', 'pago', 'pedido')",
            name="ck_gasto_comprobantes_tipo"),
    )
    op.create_index("ix_gasto_comprobantes_gasto_id", "gasto_comprobantes", ["gasto_id"])
    op.execute("CREATE UNIQUE INDEX ux_gasto_comprobantes_cfdi_uuid ON gasto_comprobantes (cfdi_uuid) "
               "WHERE cfdi_uuid IS NOT NULL")

    categorias = sa.table("gasto_categorias", sa.column("nombre", sa.String))
    op.bulk_insert(categorias, [{"nombre": n} for n in CATEGORIAS_INICIALES])


def downgrade() -> None:
    op.drop_table("gasto_comprobantes")
    op.drop_table("gasto_presupuestos")
    op.drop_table("gastos")
    op.drop_table("gasto_proveedores")
    op.drop_table("gasto_categorias")
    # Las filas sin cuenta no caben en la columna obligatoria: se pierden.
    op.execute("DELETE FROM auditoria WHERE usuario_id IS NULL")
    op.alter_column("auditoria", "usuario_id", existing_type=sa.Integer(), nullable=False)
    op.drop_index("ux_usuarios_microsoft_oid", table_name="usuarios")
    op.drop_column("usuarios", "microsoft_oid")

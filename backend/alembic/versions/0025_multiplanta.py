"""Multi-planta: las personas en una o varias plantas, y TI global.

**Antes** cada cuenta tenía exactamente una planta (`usuarios.sitio_id`), y el
rol de admin se limitaba a la suya: TI de Querétaro no veía Monterrey.

**Ahora**:

  * `usuario_sitios` dice en qué plantas trabaja cada persona —una o varias—.
    Se llena con la planta que ya tenía cada cuenta.
  * `usuarios.sitio_id` se queda como la planta **principal** de la persona
    (la que se propone al levantar un ticket) y admite vacío: TI no tiene
    planta, atiende a todas. Las cuentas de TI se quedan sin ella.
  * El conocimiento —base de conocimiento, soluciones, documentación de TI,
    fichas visuales— se vuelve compartido: su `sitio_id` pasa a ser solo la
    planta de origen, y vacío significa "general". Lo mismo para documentos
    del expediente y consultas al asistente, que pueden venir de alguien de TI.

Revision ID: 0025_multiplanta
Revises: 0024_clave_de_envio
"""

import sqlalchemy as sa
from alembic import op

revision = "0025_multiplanta"
down_revision = "0024_clave_de_envio"
branch_labels = None
depends_on = None

OPCIONALES = ("base_conocimiento", "soluciones_generales", "documentos_ti", "fichas_visuales",
              "documentos_usuario", "consultas_asistente")


def upgrade() -> None:
    op.create_table(
        "usuario_sitios",
        sa.Column("usuario_id", sa.Integer(), sa.ForeignKey("usuarios.id", ondelete="CASCADE"),
                  primary_key=True),
        sa.Column("sitio_id", sa.Integer(), sa.ForeignKey("sitios.id"), primary_key=True),
    )
    op.alter_column("usuarios", "sitio_id", existing_type=sa.Integer(), nullable=True)
    op.execute(
        "INSERT INTO usuario_sitios (usuario_id, sitio_id) "
        "SELECT id, sitio_id FROM usuarios WHERE sitio_id IS NOT NULL AND rol <> 'admin'"
    )
    op.execute("UPDATE usuarios SET sitio_id = NULL WHERE rol = 'admin'")
    for tabla in OPCIONALES:
        op.alter_column(tabla, "sitio_id", existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    primera = "(SELECT min(id) FROM sitios)"
    for tabla in OPCIONALES:
        op.execute(f"UPDATE {tabla} SET sitio_id = {primera} WHERE sitio_id IS NULL")
        op.alter_column(tabla, "sitio_id", existing_type=sa.Integer(), nullable=False)
    op.execute(f"UPDATE usuarios SET sitio_id = {primera} WHERE sitio_id IS NULL")
    op.alter_column("usuarios", "sitio_id", existing_type=sa.Integer(), nullable=False)
    op.drop_table("usuario_sitios")

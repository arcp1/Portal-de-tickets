"""Eliminacion definitiva de cuentas, sin perder el historial.

Hasta ahora a una persona solo se le podia cortar el acceso (`activo = false`).
No habia forma de darla de baja del padron: seguia saliendo en la lista de
Personas para siempre, mezclada con quien si trabaja aqui.

Un DELETE de verdad no es una opcion. Diecinueve columnas apuntan a
`usuarios.id` y once son NOT NULL —tickets, comentarios, resguardos,
documentos, movimientos de inventario—, asi que borrar la fila obliga a
arrastrar el historial o a dejar la base rota.

Con una marca de fecha, la fila se queda para que el historial siga siendo
legible y la cuenta se vacia: sin contrasena, sin codigo, sin correo y sin
numero de empleado —que asi queda libre para otra alta—. Desde el portal la
persona ya no existe.

Revision ID: 0016_baja_definitiva
Revises: 0015_serie_unica_por_sitio
"""

import sqlalchemy as sa
from alembic import op

revision = "0016_baja_definitiva"
down_revision = "0015_serie_unica_por_sitio"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # **Falla rapido en vez de congelar el portal.**
    #
    # `ALTER TABLE` pide un bloqueo exclusivo sobre `usuarios`. Si alguien
    # tiene una transaccion de lectura abierta, este comando se pone a esperar
    # —y, peor, toda consulta posterior sobre la tabla se encola detras de el,
    # porque la cola de bloqueos de Postgres es por orden de llegada—. O sea
    # que una migracion bloqueada no espera: tumba el portal mientras espera.
    #
    # Paso en esta misma: el canal de eventos en vivo retenia una transaccion
    # por pestana abierta. Con un limite, el peor caso es que la migracion
    # falle y haya que repetirla.
    op.execute("SET lock_timeout = '5s'")

    op.add_column("usuarios", sa.Column("eliminado_en", sa.DateTime(), nullable=True))
    # Indice porque todas las consultas de personas lo filtran: listar el
    # padron, el selector de "asignado a", el de emision de resguardos.
    op.create_index("ix_usuarios_eliminado_en", "usuarios", ["eliminado_en"])


def downgrade() -> None:
    op.drop_index("ix_usuarios_eliminado_en", table_name="usuarios")
    op.drop_column("usuarios", "eliminado_en")

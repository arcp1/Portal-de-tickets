"""Términos y Condiciones: la versión que aceptó cada persona y cuándo.

Dos columnas en `usuarios`, vacías para todos: nadie ha aceptado nada todavía,
así que al desplegar a cada quien le toca aceptar en su siguiente acción. No se
toca ningún dato existente.

La constancia completa de cada aceptación —la IP y la huella SHA-256 del texto
exacto que se mostró— va a la bitácora (`auditoria`, acción
`terminos.aceptados`): una fila por aceptación, de modo que también quedan las
versiones anteriores. Ver app/core/terminos.py.

La corre el rol de la aplicación (M-2), que es dueño de `usuarios`: un
`ADD COLUMN` sin valor por omisión no reescribe la tabla.

Revision ID: 0031_aceptacion_terminos
Revises: 0030_directorio_documentos
"""

from alembic import op
import sqlalchemy as sa


revision = "0031_aceptacion_terminos"
down_revision = "0030_directorio_documentos"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("usuarios", sa.Column("terminos_version", sa.String(length=20), nullable=True))
    op.add_column("usuarios", sa.Column("terminos_aceptados_en", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("usuarios", "terminos_aceptados_en")
    op.drop_column("usuarios", "terminos_version")

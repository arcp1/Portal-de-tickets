"""Reconocer la foto y arreglar el problema son dos cosas distintas.

`veces_confirmada` cuenta que alguien dijo "si, es esta" mirando la foto. Eso
mide si la **foto** esta bien elegida, y ya sirve para algo: una ficha que se
ensena mucho y no reconoce nadie empareja con lo que no debe.

Lo que no mide es si la solucion de esa ficha **funciono**, y son dos fallos
distintos que piden dos arreglos distintos:

    ensenada y no reconocida ...... la foto o las frases estan mal
    reconocida y no resuelta ...... la solucion esta mal escrita, o bajo esa
                                    misma foto hay dos averias distintas

El segundo es el peor de los dos y era invisible: la ficha salia en el tablero
con un 90% de reconocimiento mientras mandaba a todo el mundo a agitar un
cartucho que no era el problema. Con esta columna, `resuelta / confirmada` lo
dice de un vistazo.

Va aparte de 0019 y no dentro porque 0019 ya esta aplicada. Una migracion
publicada no se edita: se anade la siguiente.

Revision ID: 0020_ficha_resuelta
Revises: 0019_catalogo_visual
"""

import sqlalchemy as sa
from alembic import op

revision = "0020_ficha_resuelta"
down_revision = "0019_catalogo_visual"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "fichas_visuales",
        sa.Column("veces_resuelta", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("fichas_visuales", "veces_resuelta")

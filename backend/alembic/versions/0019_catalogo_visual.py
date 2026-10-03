"""Catalogo visual: los problemas que se reconocen mirandolos.

**El hueco que tapa.** Todo el conocimiento del portal esta escrito en prosa —
la solucion de un ticket, un procedimiento de TI, una solucion general— y eso
funciona mientras el problema se pueda *nombrar*. Una copia borrosa, una con
sombra doble y una con una raya fina se describen las tres igual, "sale mal", y
se arreglan de tres maneras distintas. El texto no las separa. La foto si.

Dos tablas:

  * `fichas_visuales` — el defecto descrito por TI, con la solucion atada a el.
  * `imagenes_ficha`  — las fotos. `rol` separa las dos que hacen falta: como
    se ve el problema, y donde hay que picar para arreglarlo.

**Sin indice vectorial, y es deliberado.** Las demas tablas con embedding
llevan HNSW desde 0017 porque tienen cientos o miles de filas. Un catalogo
visual son decenas: TI documenta con foto lo que se repite, no todo. A esa
escala el planificador de Postgres ignora el indice y hace un barrido
secuencial —que sobre cuarenta filas tarda menos que bajar por el indice—, asi
que crearlo solo anadiria peso a cada insercion a cambio de nada. Si algun dia
el catalogo pasa de unos cientos, el indice se anade entonces: HNSW se
construye insertando y no hay que reconstruir nada.

Revision ID: 0019_catalogo_visual
Revises: 0018_consultas_asistente
"""

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision = "0019_catalogo_visual"
down_revision = "0018_consultas_asistente"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fichas_visuales",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sitio_id", sa.Integer(), sa.ForeignKey("sitios.id"), nullable=False),
        sa.Column("categoria", sa.String(50), nullable=True),
        sa.Column("titulo", sa.String(200), nullable=False),
        sa.Column("sintoma", sa.Text(), nullable=False),
        # Como lo dice la gente. Ademas de mejorar la busqueda, es lo que
        # ensena al disparador a reconocer problemas visuales que nadie previo
        # en el codigo: ver `visual_service.py`.
        sa.Column("frases", sa.Text(), nullable=True),
        sa.Column("solucion", sa.Text(), nullable=False),
        sa.Column("descartado", sa.Text(), nullable=True),
        sa.Column("estado", sa.String(20), nullable=False, server_default="borrador"),
        sa.Column("embedding", Vector(768), nullable=True),
        sa.Column("veces_mostrada", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("veces_confirmada", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("veces_descartada", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("creado_por", sa.Integer(), sa.ForeignKey("usuarios.id"), nullable=False),
        sa.Column("actualizado_por", sa.Integer(), sa.ForeignKey("usuarios.id"), nullable=True),
        sa.Column("creado_en", sa.DateTime(), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("actualizado_en", sa.DateTime(), nullable=True),
    )

    # La consulta real es siempre la misma: "las fichas publicadas de este
    # sitio". Compuesto y no dos sueltos porque filtra por los dos a la vez.
    op.create_index(
        "ix_fichas_visuales_sitio_estado",
        "fichas_visuales",
        ["sitio_id", "estado"],
    )

    op.create_table(
        "imagenes_ficha",
        sa.Column("id", sa.Integer(), primary_key=True),
        # Borrar la ficha se lleva sus fotos. A diferencia de un usuario, una
        # ficha no es historial de nadie: si TI la retira, sus imagenes dejan
        # de tener a que pertenecer.
        sa.Column("ficha_id", sa.Integer(),
                  sa.ForeignKey("fichas_visuales.id", ondelete="CASCADE"), nullable=False),
        # sintoma | solucion
        sa.Column("rol", sa.String(20), nullable=False, server_default="sintoma"),
        sa.Column("orden", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("pie", sa.String(300), nullable=True),
        sa.Column("nombre_original", sa.String(255), nullable=False),
        sa.Column("nombre_guardado", sa.String(255), nullable=False, unique=True),
        sa.Column("tipo_mime", sa.String(100), nullable=False),
        sa.Column("tamano_bytes", sa.Integer(), nullable=False),
        sa.Column("subido_por", sa.Integer(), sa.ForeignKey("usuarios.id"), nullable=False),
        sa.Column("creado_en", sa.DateTime(), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
    )

    # Se piden siempre por ficha y en orden de presentacion.
    op.create_index(
        "ix_imagenes_ficha_ficha_rol_orden",
        "imagenes_ficha",
        ["ficha_id", "rol", "orden"],
    )


def downgrade() -> None:
    op.drop_index("ix_imagenes_ficha_ficha_rol_orden", table_name="imagenes_ficha")
    op.drop_table("imagenes_ficha")
    op.drop_index("ix_fichas_visuales_sitio_estado", table_name="fichas_visuales")
    op.drop_table("fichas_visuales")

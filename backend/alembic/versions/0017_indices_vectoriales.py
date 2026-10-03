"""Indices vectoriales: el que faltaba, y los tres que estaban mal puestos.

**Lo que faltaba.** `soluciones_generales.embedding` no tenia indice de ningun
tipo. Es la tabla que `recuperacion_service._de_soluciones` consulta **primero**
en cada pregunta al asistente, y ademas la unica cuyos resultados llevan ventaja
sobre las demas fuentes. O sea: la consulta mas influyente del RAG se estaba
resolviendo con un barrido completo de la tabla.

**Lo que estaba mal puesto.** Las otras tres —`base_conocimiento`,
`documentos_ti`, `temas_sugeridos`— si tienen indice, pero es `ivfflat` con
`lists = 100`, y ese numero es el problema.

`ivfflat` reparte los vectores en `lists` grupos y al buscar mira solo `probes`
grupos, que por defecto es **uno**. Con 100 grupos eso significa revisar el 1%
de la tabla. La regla de pgvector es `lists ≈ filas / 1000`, o sea que 100
corresponde a **cien mil filas**; aqui hay cientos. Con 400 tickets indexados,
cada grupo tiene cuatro vectores y la busqueda mira cuatro: el ticket correcto
se queda fuera la mayoria de las veces.

Y hay algo peor, que es la razon de que esto no diera la cara antes: un indice
`ivfflat` construido sobre una tabla **vacia** —que es como se construyeron
estos, en la migracion que creo cada tabla— no tiene centroides con los que
repartir nada. Queda inservible hasta que se reconstruye a mano, cosa que nadie
hizo nunca porque nada avisa.

El sintoma de todo esto no es un error: es que el asistente "no encuentra" cosas
que si estan escritas, y sobre eso no hay nada que depurar.

**Por que HNSW.** No se entrena: se construye insertando, asi que funciona
igual de bien con cero filas que con cien mil y no hay que reconstruirlo cuando
la tabla crece. Con los volumenes de esta planta —miles de vectores, no
millones— da practicamente la misma respuesta que un barrido completo, y a
diferencia de `ivfflat` no depende de un numero que alguien tiene que acertar y
despues mantener. Cuesta mas construirlo y ocupa mas: a esta escala, nada.

Requiere pgvector >= 0.5. La imagen del compose trae 0.8.6. Si acaso se corre
contra una version vieja, se detecta y se deja lo que habia: es preferible un
indice mal calibrado a una migracion que no aplica.

**Cuando estos indices se usan, y cuando no.** Medido despues, con una tabla
temporal de 5000 entradas y vectores de 768 dimensiones —la base real tiene
demasiadas pocas filas para que el planificador decida nada representativo—:

- Busqueda **sin filtro de categoria**: el planificador elige el HNSW.
  `Index Scan ... Order By: (embedding <=> $1)`, diez filas leidas.
- Busqueda **con filtro de categoria**: **no** lo elige. Recorre el indice
  `(sitio_id, categoria)`, saca las 833 filas de esa categoria, calcula las 833
  distancias y ordena. 3,6 ms.

No es un fallo ni hay nada que arreglar hoy: 3,6 ms no se nota en una pantalla,
y el filtro reduce tanto el conjunto que ordenarlo sale barato. Se anota porque
es justo lo que uno supondria al reves —«puse indices HNSW, luego toda busqueda
vectorial es logaritmica»— y porque marca donde mirar si algun dia la base
crece en un orden de magnitud: la salida seria un indice parcial por categoria,
o subir `hnsw.ef_search` y dejar que el HNSW filtre el mismo. Para reproducir la
medicion, la receta esta en la memoria del proyecto.

Revision ID: 0017_indices_vectoriales
Revises: 0016_baja_definitiva
"""

from alembic import op

revision = "0017_indices_vectoriales"
down_revision = "0016_baja_definitiva"
branch_labels = None
depends_on = None


#: (tabla, indice HNSW, indice ivfflat que sustituye)
#:
#: `soluciones_generales` no trae tercer elemento porque no habia nada que
#: sustituir: ese es el indice que faltaba.
TABLAS = (
    ("base_conocimiento", "ix_base_conocimiento_embedding_hnsw",
     "ix_base_conocimiento_embedding"),
    ("documentos_ti", "ix_docti_embedding_hnsw", "ix_docti_embedding"),
    ("temas_sugeridos", "ix_temas_sugeridos_embedding_hnsw",
     "ix_temas_sugeridos_embedding"),
    ("soluciones_generales", "ix_soluciones_generales_embedding_hnsw", None),
)


def _version_vector(bind) -> tuple:
    """La version de pgvector instalada, como tupla comparable."""
    fila = bind.exec_driver_sql(
        "SELECT extversion FROM pg_extension WHERE extname = 'vector'"
    ).fetchone()
    if not fila or not fila[0]:
        return ()
    partes = []
    for trozo in str(fila[0]).split("."):
        digitos = "".join(c for c in trozo if c.isdigit())
        partes.append(int(digitos) if digitos else 0)
    return tuple(partes)


def _existe_tabla(bind, nombre: str) -> bool:
    return bool(bind.exec_driver_sql(
        "SELECT to_regclass(%(n)s) IS NOT NULL", {"n": f"public.{nombre}"}
    ).scalar())


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        # Las pruebas corren sobre SQLite, que no tiene pgvector ni falta que
        # le hace: ahi la busqueda por similitud no se ejercita.
        return

    if _version_vector(bind) < (0, 5, 0):
        print("pgvector < 0.5: sin HNSW. Se deja el indice que hubiera.")
        return

    # Mismo cinturon que en 0016: `CREATE INDEX` toma un bloqueo que frena las
    # escrituras de la tabla, y una migracion bloqueada no solo espera —encola
    # detras de si todo lo que llegue despues—. Con limite, el peor caso es
    # repetirla.
    #
    # `CONCURRENTLY` evitaria el bloqueo pero no puede correr dentro de una
    # transaccion, y Alembic envuelve cada migracion en una. A esta escala
    # —cientos de filas— la construccion es cuestion de milisegundos.
    op.execute("SET lock_timeout = '10s'")

    for tabla, hnsw, ivfflat in TABLAS:
        if not _existe_tabla(bind, tabla):
            # Una instalacion a la que aun no le toco la migracion que crea
            # esta tabla. No es un error: no hay nada que indexar todavia.
            continue

        op.execute(
            f"CREATE INDEX IF NOT EXISTS {hnsw} "
            f"ON {tabla} USING hnsw (embedding vector_cosine_ops);"
        )
        if ivfflat:
            # Se quita el viejo **despues** de crear el nuevo, y solo si el
            # nuevo se creo: en ningun momento la tabla se queda sin indice.
            #
            # Dejar los dos seria peor que quedarse con uno: cada alta pagaria
            # el mantenimiento de ambos y el planificador tendria que elegir
            # entre un indice bueno y uno que devuelve resultados incompletos.
            op.execute(f"DROP INDEX IF EXISTS {ivfflat};")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute("SET lock_timeout = '10s'")

    for tabla, hnsw, ivfflat in TABLAS:
        if not _existe_tabla(bind, tabla):
            continue
        if ivfflat:
            # Se restituye tal como estaba, `lists = 100` incluido. Un
            # `downgrade` devuelve el esquema anterior; no es el sitio para
            # corregirlo.
            op.execute(
                f"CREATE INDEX IF NOT EXISTS {ivfflat} "
                f"ON {tabla} USING ivfflat (embedding vector_cosine_ops) "
                f"WITH (lists = 100);"
            )
        op.execute(f"DROP INDEX IF EXISTS {hnsw};")

"""Los problemas que se reconocen mirándolos.

**El hueco que tapa.** Todo lo que el portal sabe está escrito en prosa: la
solución de un ticket, un procedimiento de TI, una solución general. Eso
funciona mientras el problema se pueda *nombrar*. Una copia borrosa, una con
sombra doble y una con una raya fina se describen las tres igual —"sale mal"—
y se arreglan de tres maneras distintas. El texto no las separa; la foto sí.

Así que aquí el portal hace algo que no hace en ningún otro sitio: en vez de
contestar, **enseña y pregunta**. Muestra las fotos de los defectos que se
parecen a lo que la persona escribió y le deja señalar el suyo. Lo que entrega
después es la solución atada a la foto que *ella* eligió, no la que el parecido
de texto creyó más probable.

----------------------------------------------------------------------------
Cuándo se activa, que es la mitad del problema
----------------------------------------------------------------------------

"No manda a imprimir" y "mi copia sale borrosa" son dos incidencias de
impresora y no se parecen en nada:

    no manda a imprimir  ->  no hay nada que ver. Falta una función.
    la copia sale borrosa ->  hay algo que ver, y verlo es lo que lo resuelve.

Enseñar fotos a quien reporta lo primero es ruido: le estorba para llegar a su
ticket. No enseñárselas a quien reporta lo segundo desperdicia lo único que lo
habría resuelto sin levantar nada.

**Dos puertas, y ninguna sobra.**

*Puerta 1 — ¿esto describe algo que se ve?* Determinista, en esta tabla de
abajo, instantánea y auditable: si clasifica mal, se corrige una línea en vez
de reentrenar nada. Es el mismo criterio con el que ya se clasifica por
`VOCABULARIO_PLANTA` en `ollama_client.py`, y por el mismo motivo.

*Puerta 2 — ¿tenemos una foto de eso?* La búsqueda por significado contra el
catálogo. Da igual cuánto suene a defecto visual lo que alguien escriba: si TI
no ha documentado nada parecido con una foto, no hay nada que enseñar y la
consulta sigue su camino de siempre, sin enterarse de que esto existió.

**La segunda puerta no vuelve prescindible a la primera**, y conviene dejarlo
dicho porque parece que sí. Sin la primera, "no manda a imprimir" emparejaría
con la ficha de "la hoja sale en blanco" —hablan de la misma impresora y de la
misma ausencia de resultado— y el portal le enseñaría fotos de hojas a alguien
cuyo problema es que no llega el trabajo a la cola.

----------------------------------------------------------------------------
Lo que hace universal a esto
----------------------------------------------------------------------------

La tabla de abajo la escribió alguien que estaba pensando en impresoras,
pantallas y luces de equipo. Mañana el problema visual será de una báscula, de
una etiqueta de embarque o de algo que hoy no existe en la planta, y nadie va a
tocar este archivo para darlo de alta.

Por eso **las frases de las fichas también abren la primera puerta**. Cuando TI
documenta un defecto, escribe en `frases` cómo lo dice la gente —"queda
recorrida la etiqueta", "marca el peso en cero"— y esas frases pasan a ser
señales tan válidas como las de aquí. El catálogo le va enseñando al disparador
a reconocer lo que el código no previó, sin que nadie programe nada.

**Y es también la respuesta al otro idioma.** Las tablas de abajo están en
español porque en esta planta se escribe en español, aunque el portal hable
tres. No se tradujeron a ciegas: un léxico inventado sin haber visto cómo
reporta la gente en inglés o en francés daría por bueno un vocabulario que
nadie usa, y los fallos de esto no se reportan solos. Mientras llegue esa
necesidad, el camino es el mismo que para la báscula: el administrador escribe
en `frases` la forma real en que se dijo, en el idioma en que se dijo, y a
partir de ahí el portal la reconoce.

----------------------------------------------------------------------------
Lo que este módulo NO hace
----------------------------------------------------------------------------

**Ningún modelo mira las fotos.** No hay visión por computadora en ninguna
parte de esto. La imagen la etiqueta quien la sube, que es quien estuvo delante
del equipo; lo único que empareja el modelo es texto contra texto —lo que
escribe el usuario contra lo que TI escribió—. Un modelo de visión aquí sólo
añadiría una manera nueva de equivocarse sobre algo que ya estaba escrito.

Y **el portal nunca decide cuál es el problema**: enseña dos o tres y pregunta.
Quien tiene la hoja en la mano decide en dos segundos algo que ningún parecido
de coseno puede decidir por él.
"""

import unicodedata
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import logger
from app.models import FichaVisual, ImagenFicha
from app.services.conciencia_service import ConcienciaService
from app.services.ollama_client import normalizar_categoria, ollama

# --- Puerta 1: ¿el texto describe algo que se ve? --------------------------
#
# Reglas para editar estas tres tablas, y son las que las mantienen útiles:
#
#   1. Sólo va lo que describe **apariencia**, nunca un objeto ni una acción.
#      "impresora" y "pantalla" no dicen si hay algo que mirar; "borroso" y
#      "parpadea" no pueden significar otra cosa.
#   2. Cada término se compara **por el principio de la palabra**, así que se
#      escriben como raíces: "borros" cubre borroso, borrosa y borrosas sin
#      tener que enumerarlas. Es el mismo recorte que usa el asistente para
#      medir anclaje, y por la misma razón: el español declina mucho.
#   3. Ante la duda, fuera. Un término ambiguo no se nota cuando falla: hace
#      que a alguien le salgan fotos de impresoras cuando preguntaba por la
#      red, y nadie reporta eso. Se quedaron fuera "corta" (se corta el
#      internet), "carga" (no carga la página / no carga la batería) y "rojo"
#      suelto (hay un rojo que es una luz y otro que es un color de etiqueta).
RAICES_APARIENCIA = (
    # Defectos de impresión, copia y etiqueta
    "borros", "manch", "raya", "rayon", "franja", "sombra", "tenue",
    "despint", "desvanec", "descolorid", "opaco", "moteado", "salpic",
    "arrug", "chueco", "torcid", "desalinead", "cortad", "encimad",
    "difumin", "punteado", "granul", "corrid", "recorrid", "desfasad",
    # Pantallas y vídeo
    "pixel", "distorsion", "congelad", "estirad", "invertid", "verdos",
    "amarillent", "azulad", "desenfoc", "espejead",
    # Luces, indicadores y cosas que se mueven a la vista
    "parpade", "titil", "intermitent", "ambar",
    # Formas de decir "no se lee lo que salió"
    "ilegible", "irreconocib", "fantasma",
)

# Lo mismo, pero cuando hacen falta varias palabras para que no sea ambiguo.
# Se comparan tal cual, como texto dentro del texto.
FRASES_APARIENCIA = (
    "se ve mal", "se ve raro", "se ve asi", "se ve feo", "se mira mal",
    "en blanco", "sale blanca", "sale negra", "todo negro", "medio borrado",
    "luz roja", "luz naranja", "luz amarilla", "led rojo", "foco rojo",
    "pantalla azul", "pantalla negra", "pantalla en negro",
    "codigo de error", "mensaje de error", "sale un error", "marca error",
    "letras raras", "simbolos raros", "caracteres raros", "cuadritos",
    "doble imagen", "imagen doble", "se repite la imagen",
    "no se entiende lo que", "no se alcanza a leer", "se alcanza a ver",
    # **"línea" no puede ir como raíz suelta** —"el sistema no está en línea"
    # no tiene nada que mirar— pero es una de las dos formas en que la gente
    # describe este defecto, junto con "raya". Así que va acompañada, que es
    # como se dice de verdad cuando se habla de una hoja.
    "con linea", "sale linea", "salen linea", "unas linea", "varias linea",
    "linea blanca", "linea negra", "linea oscura", "linea clara",
    "linea vertical", "linea horizontal", "lineas por",
    "al reves", "de cabeza",
)

# Señal **débil**: dicen que hay un resultado a la vista, no cómo se ve.
# Por sí solas activan; acompañadas de una ausencia de función, no.
VERBOS_PERCEPCION = (
    "se ve", "se ven", "se mira", "sale", "salen", "aparece", "aparecen",
    "muestra", "se nota", "queda", "quedan", "viene con", "trae",
)

# Ausencia de función: no hay resultado que mirar porque no hubo resultado.
# Vetan la señal débil de arriba, nunca a las dos primeras tablas: "no imprime,
# sale la hoja en blanco" sí tiene algo que ver, y es justo lo que hay que ver.
FRASES_AUSENCIA = (
    "no imprime", "no manda a imprimir", "no manda imprimir", "no sale nada",
    "no enciende", "no prende", "no responde", "no arranca", "no inicia",
    "no conecta", "no se conecta", "no hay internet", "no hay red",
    "no hay senal", "sin senal", "sin internet", "sin conexion", "sin red",
    "no funciona", "no sirve", "no abre", "no me deja", "no entra",
    "no reconoce", "no detecta", "no llega", "esta apagad", "no hay nada",
    # Éstas llevan dentro un verbo de percepción y aun así no hay nada que
    # mirar: "no aparece la impresora en la lista" es un problema de cola de
    # impresión, no del papel. Van aquí justamente para vetar la señal débil.
    "no aparece", "no se ve nada", "no muestra nada", "no se alcanza a ver nada",
)

# Una frase de ficha más corta que esto no se usa como señal. Con "error" o
# "raro" en `frases`, una sola ficha mal escrita abriría la puerta para media
# planta; el mínimo es lo que impide que un descuido de captura se convierta en
# ruido para todo el mundo.
MINIMO_FRASE_CATALOGO = 6

# Qué puede salir en `motivo`. Se registra en el log y lo enseña la pantalla de
# calibración del administrador: sin esto, "no se activó" no se puede depurar.
MOTIVO_APARIENCIA = "apariencia"            # describe cómo se ve algo
MOTIVO_PERCEPCION = "percepcion"            # dice que hay algo a la vista
MOTIVO_CATALOGO = "frase_del_catalogo"      # lo dijo con las palabras de una ficha
MOTIVO_AUSENCIA = "ausencia_de_funcion"     # falta una función; no hay nada que ver
MOTIVO_NADA = "nada_que_ver"                # no describe nada visible
MOTIVO_SIN_CATALOGO = "sin_catalogo"        # no hay fichas publicadas
MOTIVO_SIN_PARECIDO = "sin_parecido"        # las hay, pero ninguna se parece

# Cómo queda anotada la consulta en la bitácora de conciencia, que es la lista
# con la que se decide qué documentar el lunes.
#
# **Sin esto, el catálogo visual sería el único rincón del portal que no rinde
# cuentas de lo que no supo.** Los contadores de cada ficha dicen cómo le fue a
# las fichas que existen; no dicen nada de las que faltan, y ése es el dato que
# hace falta para escribir la siguiente. Se aprovecha la tabla que ya lleva esa
# cuenta para el asistente de texto —mismo sitio, misma pantalla, misma
# pregunta— en vez de abrir una bitácora paralela que nadie miraría.
ORIGEN_RESUELTO = "visual"              # reconoció la foto y la solución sirvió
ORIGEN_NINGUNA = "visual_ninguna"       # se le enseñaron y ninguna era la suya
ORIGEN_SIN_FOTO = "visual_sin_foto"     # pedía una foto y no teníamos ninguna
ORIGEN_NO_ARREGLO = "visual_no_arreglo"  # reconoció la foto y no se arregló


def _plano(texto: str) -> str:
    """Minúsculas, sin acentos y con un espacio en cada punta.

    Los espacios de los extremos no son cosmética: todas las comparaciones de
    raíz buscan `" borros"` con el espacio delante, y sin ellos la primera
    palabra del mensaje nunca casaría.
    """
    crudo = unicodedata.normalize("NFKD", (texto or "").lower())
    sin_acentos = "".join(c for c in crudo if not unicodedata.combining(c))
    # La puntuación separa palabras: "sale borroso, casi no se lee" tiene que
    # dejar " borroso " y no " borroso, ".
    limpio = "".join(c if c.isalnum() else " " for c in sin_acentos)
    return " " + " ".join(limpio.split()) + " "


class VisualService:

    # ------------------------------------------------------------------
    # Puerta 1
    # ------------------------------------------------------------------
    @staticmethod
    def frases_del_catalogo(db: Session, sitio_id: int) -> List[str]:
        """Las frases con las que TI describió los defectos de este sitio.

        Son pocas filas y de una sola columna: no hay caché a propósito. Una
        caché aquí habría que invalidarla cada vez que un administrador edita
        una ficha, y el día que esa invalidación falle el síntoma será que el
        portal deja de reconocer algo que está escrito —sin error, sin log y
        sin nada que mirar—. Se paga la consulta.
        """
        filas = (
            db.query(FichaVisual.frases)
            .filter(FichaVisual.estado == "publicada",
                    FichaVisual.frases.isnot(None))
            .all()
        )
        frases = []
        for (crudo,) in filas:
            for trozo in str(crudo).replace("\n", ",").split(","):
                limpia = trozo.strip()
                if len(limpia) >= MINIMO_FRASE_CATALOGO:
                    frases.append(_plano(limpia).strip())
        return frases

    @staticmethod
    def describe_algo_visible(texto: str,
                              frases_catalogo: Optional[List[str]] = None) -> Tuple[bool, str]:
        """¿Esto habla de algo que se ve? Devuelve `(sí/no, motivo)`.

        El motivo viaja hasta el log y hasta la pantalla de calibración. Un
        booleano solo diría que no se activó; lo que hace falta saber es por
        qué, que es lo único sobre lo que se puede actuar.
        """
        plano = _plano(texto)

        # Señales fuertes: dicen **cómo** se ve. Ninguna ausencia las veta,
        # porque "no imprime, sale la hoja en blanco" tiene algo que mirar.
        for frase in (frases_catalogo or []):
            if frase and frase in plano:
                return True, MOTIVO_CATALOGO
        for raiz in RAICES_APARIENCIA:
            if " " + raiz in plano:
                return True, MOTIVO_APARIENCIA
        for frase in FRASES_APARIENCIA:
            if frase in plano:
                return True, MOTIVO_APARIENCIA

        # Señal débil: dice que hay un resultado, no cómo es. Vale sola; con
        # una ausencia de función al lado, no.
        debil = any(" " + v in plano for v in VERBOS_PERCEPCION)
        ausencia = any(frase in plano for frase in FRASES_AUSENCIA)

        if ausencia:
            return False, MOTIVO_AUSENCIA
        if debil:
            return True, MOTIVO_PERCEPCION
        return False, MOTIVO_NADA

    # ------------------------------------------------------------------
    # Puerta 2
    # ------------------------------------------------------------------
    @staticmethod
    def reconocer(db: Session, texto: str, sitio_id: int,
                  categoria: Optional[str] = None,
                  registrar: bool = True,
                  usuario_id: Optional[int] = None,
                  vector: Optional[List[float]] = None) -> dict:
        """Las fichas que se le pueden enseñar a quien escribió esto.

        `activado` en False significa "sigue por donde ibas": ni el chat ni
        ninguna otra pantalla debe cambiar de comportamiento. Es la respuesta
        normal, no un fallo.

        `registrar` apaga a la vez el conteo de `veces_mostrada` y la anotación
        en la bitácora. Lo usa la pantalla de calibración del administrador,
        que pregunta qué pasaría sin que a nadie se le haya enseñado nada: sin
        esto, probar el disparador veinte veces ensuciaría las dos cosas que
        sirven para decidir si una ficha está bien escrita.

        ``vector`` deja entrar un embedding ya calculado, igual que en
        `RecuperacionService.buscar` y por el mismo motivo. **Sin esto, un
        mensaje de chat que suene visual y no tenga foto se vectoriza dos
        veces**: una aquí y otra dentro del asistente de texto al que cae
        después. Medido en esta máquina, un embedding cuesta entre 74 y 579 ms
        —mediana 311—, así que es un regalo caro, y justo en el caso más
        frecuente mientras el catálogo esté a medio escribir.
        """
        texto = (texto or "").strip()
        if not texto:
            return VisualService._nada(MOTIVO_NADA)

        frases = VisualService.frases_del_catalogo(db, sitio_id)
        visible, motivo = VisualService.describe_algo_visible(texto, frases)
        if not visible:
            return VisualService._nada(motivo)

        candidatas = VisualService._buscar(db, texto, sitio_id, categoria, vector)
        if not candidatas:
            # Se dice "sin catálogo" y no "sin parecido" cuando no hay ni una
            # ficha publicada: son dos cosas distintas y llevan a dos acciones
            # distintas —documentar el defecto, o revisar cómo está escrito—.
            hay = (db.query(FichaVisual.id)
                   .filter(FichaVisual.estado == "publicada")
                   .first() is not None)

            # **Éste es el apunte que más vale de los cuatro.** Alguien acaba
            # de describir algo que se ve y el portal no tenía la foto: eso es,
            # literalmente, la lista de qué fotografiar la semana que viene, y
            # sin anotarlo aquí no queda rastro de que la consulta existió.
            if registrar:
                VisualService._anotar(db, sitio_id, usuario_id, texto, categoria,
                                      ORIGEN_SIN_FOTO)
            return VisualService._nada(MOTIVO_SIN_PARECIDO if hay else MOTIVO_SIN_CATALOGO)

        if registrar:
            for ficha, _ in candidatas:
                ficha.veces_mostrada = (ficha.veces_mostrada or 0) + 1
            db.commit()

        logger.info(
            "Reconocimiento visual activado",
            extra={"motivo": motivo, "candidatas": len(candidatas),
                   "mejor": round(candidatas[0][1], 3) if candidatas[0][1] is not None else None},
        )

        return {
            "activado": True,
            "motivo": motivo,
            "candidatas": [VisualService._resumen(f, s) for f, s in candidatas],
        }

    @staticmethod
    def _buscar(db: Session, texto: str, sitio_id: int,
                categoria: Optional[str],
                vector: Optional[List[float]] = None) -> List[Tuple[FichaVisual, Optional[float]]]:
        """Las fichas publicadas más parecidas, de más a menos.

        **Una ficha sin foto del síntoma no se puede enseñar**, así que no
        entra: la pregunta que hace todo esto es "¿se ve así?" y sin imagen no
        hay nada que señalar. No debería ocurrir —publicar exige al menos una—
        pero si alguna vez ocurre, es preferible una candidata menos que una
        tarjeta vacía en la cara del usuario.
        """
        categoria = normalizar_categoria(categoria)
        if vector is None:
            vector = ollama.generar_embedding(texto, tarea="consulta")

        if vector is None:
            return VisualService._buscar_por_frase(db, texto, sitio_id, categoria)

        try:
            consulta = db.query(
                FichaVisual,
                FichaVisual.embedding.cosine_distance(vector).label("distancia"),
            ).filter(
                FichaVisual.estado == "publicada",
                FichaVisual.embedding.isnot(None),
            )
            if categoria:
                consulta = consulta.filter(FichaVisual.categoria == categoria)
            filas = consulta.order_by("distancia").limit(
                settings.VISUAL_MAX_CANDIDATAS * 3).all()
        except Exception as exc:  # noqa: BLE001 - degradación deliberada
            logger.error("Fallo buscando en el catálogo visual",
                         extra={"error": str(exc)})
            return []

        parecidas = [(f, 1.0 - float(d)) for f, d in filas
                     if 1.0 - float(d) >= settings.VISUAL_UMBRAL]
        parecidas = [(f, s) for f, s in parecidas if VisualService._foto_sintoma(f)]
        if not parecidas:
            return []

        # Las que acompañan a la mejor tienen que estar cerca de ella. Una
        # tercera foto claramente peor no ayuda a elegir: estorba.
        piso = parecidas[0][1] - settings.VISUAL_MARGEN
        parecidas = [(f, s) for f, s in parecidas if s >= piso]
        return parecidas[:settings.VISUAL_MAX_CANDIDATAS]

    @staticmethod
    def _buscar_por_frase(db: Session, texto: str, sitio_id: int,
                          categoria: Optional[str]) -> List[Tuple[FichaVisual, None]]:
        """Sin embeddings: las fichas cuyas frases aparecen literalmente.

        Ollama caído no tiene por qué apagar esto del todo. Si TI escribió
        "sale borroso" en una ficha y la persona escribió exactamente eso, la
        coincidencia es literal y no hace falta ningún modelo para verla.

        La similitud sale en `None` y no en un número inventado: no es
        comparable con la del coseno, y rellenarla con un 1.0 haría que la
        pantalla de calibración mintiera sobre lo que de verdad se midió.
        """
        plano = _plano(texto)
        consulta = db.query(FichaVisual).filter(
            FichaVisual.estado == "publicada",
        )
        if categoria:
            consulta = consulta.filter(FichaVisual.categoria == categoria)

        aciertos = []
        for ficha in consulta.all():
            if not VisualService._foto_sintoma(ficha):
                continue
            cuantas = 0
            for trozo in str(ficha.frases or "").replace("\n", ",").split(","):
                limpia = trozo.strip()
                if len(limpia) >= MINIMO_FRASE_CATALOGO and _plano(limpia).strip() in plano:
                    cuantas += 1
            if cuantas:
                aciertos.append((cuantas, ficha))

        aciertos.sort(key=lambda par: par[0], reverse=True)
        return [(ficha, None) for _, ficha in aciertos[:settings.VISUAL_MAX_CANDIDATAS]]

    # ------------------------------------------------------------------
    # Lo que pasa después de que la persona señala una foto
    # ------------------------------------------------------------------
    @staticmethod
    def confirmar(db: Session, ficha_id: int, sitio_id: int) -> Optional[dict]:
        """La solución atada a la foto que la persona reconoció como la suya.

        Devuelve None si la ficha no existe, no es de su planta o no está
        publicada. Las tres se tratan igual —no existe— por lo mismo que en el
        resto del portal: un id ajeno no debe poder distinguirse de uno
        inventado.
        """
        ficha = VisualService._publicada(db, ficha_id, sitio_id)
        if ficha is None:
            return None

        ficha.veces_confirmada = (ficha.veces_confirmada or 0) + 1
        db.commit()
        db.refresh(ficha)

        logger.info("Ficha visual confirmada por el usuario",
                    extra={"ficha_id": ficha.id, "titulo": ficha.titulo})

        return {
            "ficha_id": ficha.id,
            "titulo": ficha.titulo,
            "categoria": ficha.categoria,
            "solucion": ficha.solucion,
            # Se enseña siempre, como en el resto del portal: es lo que evita
            # que alguien repita media hora de trabajo que ya se descartó.
            "descartado": ficha.descartado,
            # Los pasos que no se pueden explicar por escrito: dónde picar.
            "pasos": [
                {"imagen_id": img.id, "pie": img.pie, "orden": img.orden}
                for img in sorted(
                    [i for i in ficha.imagenes if i.rol == "solucion"],
                    key=lambda i: (i.orden or 0, i.id),
                )
            ],
        }

    @staticmethod
    def descartar(db: Session, ficha_ids: List[int], sitio_id: int,
                  texto: Optional[str] = None,
                  usuario_id: Optional[int] = None) -> int:
        """"No es ninguna de éstas." Se anota y se sigue por el camino normal.

        **Es la mitad valiosa de la medición, y la que se pierde si no se pide
        aquí.** Una ficha que se enseña mucho y no confirma nadie no está
        "poco usada": está emparejando con consultas que no son la suya, y eso
        sólo se ve restando. Sin este dato, `veces_mostrada` no distingue una
        ficha útil de una que estorba.

        Y el texto de la consulta se anota aparte, en la bitácora: dice **qué
        defecto falta** en el catálogo, que es una pregunta distinta de cuál de
        las fichas existentes sobra.
        """
        if not ficha_ids:
            return 0
        fichas = (
            db.query(FichaVisual)
            .filter(FichaVisual.id.in_(ficha_ids[:settings.VISUAL_MAX_CANDIDATAS]))
            .all()
        )
        for ficha in fichas:
            ficha.veces_descartada = (ficha.veces_descartada or 0) + 1
        db.commit()

        if texto:
            VisualService._anotar(db, sitio_id, usuario_id, texto, None, ORIGEN_NINGUNA,
                                  fichas=len(fichas))
        return len(fichas)

    @staticmethod
    def marcar_resultado(db: Session, ficha_id: int, sitio_id: int, resuelto: bool,
                         texto: Optional[str] = None,
                         usuario_id: Optional[int] = None) -> Optional[dict]:
        """"¿Se arregló?" — la pregunta que separa una foto buena de una útil.

        Reconocer la foto y resolver el problema son dos cosas distintas, y
        confundirlas deja escondido el peor de los dos fallos: **una ficha con
        la foto perfecta y la solución equivocada luce impecable** —todo el
        mundo la reconoce— mientras manda a la planta entera a hacer algo que
        no arregla nada.

        Devuelve None si la ficha no existe o no es de esta planta.
        """
        ficha = VisualService._publicada(db, ficha_id, sitio_id)
        if ficha is None:
            return None

        if resuelto:
            ficha.veces_resuelta = (ficha.veces_resuelta or 0) + 1
            db.commit()

        VisualService._anotar(
            db, sitio_id, usuario_id, texto or ficha.titulo, ficha.categoria,
            ORIGEN_RESUELTO if resuelto else ORIGEN_NO_ARREGLO,
            fichas=1,
        )
        logger.info("Desenlace de una ficha visual",
                    extra={"ficha_id": ficha.id, "resuelto": resuelto})
        return {"ficha_id": ficha.id, "titulo": ficha.titulo,
                "solucion": ficha.solucion, "categoria": ficha.categoria}

    @staticmethod
    def _anotar(db: Session, sitio_id: int, usuario_id: Optional[int],
                texto: str, categoria: Optional[str], origen: str,
                fichas: int = 0) -> None:
        """Deja la consulta en la bitácora de conciencia. **Nunca levanta.**

        Se reutiliza `ConcienciaService.registrar` en vez de escribir la fila a
        mano por una razón concreta: esa función ya se traga sus propios
        errores. Apuntar lo que pasó no puede impedir que pase, y aquí lo que
        pasa es que alguien está intentando arreglar una impresora.

        `fichas` es **cuántas se le enseñaron de verdad**, y va con cuidado
        porque esa cifra se pinta en la pantalla como "pasajes recuperados". Un
        hueco visual —no teníamos foto— tiene que decir cero; poner uno por
        comodidad convertiría la bitácora en un sitio que dice haber encontrado
        algo cuando no encontró nada, que es justo lo que esa pantalla existe
        para no hacer.
        """
        ConcienciaService.registrar(
            db,
            sitio_id=sitio_id,
            usuario_id=usuario_id,
            pregunta=texto,
            categoria=normalizar_categoria(categoria),
            # `fuente` en "ficha_visual" es lo que permite distinguir, en la
            # misma lista, un hueco de texto de un hueco de foto.
            resultado={
                "origen": origen,
                "fuentes": [{"fuente": "ficha_visual", "similitud": None}] * max(0, fichas),
            },
        )

    # ------------------------------------------------------------------
    # Utilidades
    # ------------------------------------------------------------------
    @staticmethod
    def _publicada(db: Session, ficha_id: int, sitio_id: int) -> Optional[FichaVisual]:
        return (
            db.query(FichaVisual)
            .filter(FichaVisual.id == ficha_id,
                    FichaVisual.estado == "publicada")
            .first()
        )

    @staticmethod
    def _foto_sintoma(ficha: FichaVisual) -> Optional[ImagenFicha]:
        """La foto con la que se pregunta "¿se ve así?"."""
        fotos = sorted(
            [i for i in ficha.imagenes if i.rol == "sintoma"],
            key=lambda i: (i.orden or 0, i.id),
        )
        return fotos[0] if fotos else None

    @staticmethod
    def _resumen(ficha: FichaVisual, similitud: Optional[float]) -> dict:
        """Lo justo para dibujar la tarjeta y preguntar.

        **La solución no viaja aquí.** Se entrega en `confirmar`, cuando la
        persona ya señaló cuál es la suya. Mandarla de una vez ahorraría una
        petición y rompería lo único que hace fiable a todo esto: que lo que se
        lee corresponde a la foto que se reconoció, y no a la que el parecido
        de texto puso primera.
        """
        principal = VisualService._foto_sintoma(ficha)
        todas = sorted(
            [i for i in ficha.imagenes if i.rol == "sintoma"],
            key=lambda i: (i.orden or 0, i.id),
        )
        return {
            "ficha_id": ficha.id,
            "titulo": ficha.titulo,
            "categoria": ficha.categoria,
            "sintoma": ficha.sintoma,
            "similitud": round(similitud, 4) if similitud is not None else None,
            "imagen_id": principal.id if principal else None,
            "pie": principal.pie if principal else None,
            # Todas las vistas del mismo defecto, la principal incluida, para
            # quien quiera mirar de cerca antes de decidir.
            "imagenes": [{"imagen_id": i.id, "pie": i.pie} for i in todas],
        }

    @staticmethod
    def _nada(motivo: str) -> dict:
        return {"activado": False, "motivo": motivo, "candidatas": []}


def texto_indexable(titulo: str, sintoma: str, frases: Optional[str],
                    categoria: Optional[str]) -> str:
    """Lo que se vectoriza de una ficha.

    **La solución no entra**, y es deliberado: lo que hay que emparejar es lo
    que la persona *ve*, no lo que hay que hacer después. Metiendo el
    procedimiento, una ficha cuya solución es "cambiar el tóner" empezaría a
    aparecer ante cualquiera que escriba "tóner", tenga o no el defecto que la
    ficha documenta.
    """
    partes = [titulo, sintoma, frases, categoria]
    return "\n".join(p.strip() for p in partes if p and p.strip())

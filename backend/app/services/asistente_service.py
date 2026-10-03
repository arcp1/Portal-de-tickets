"""El asistente que responde con lo nuestro, o no responde.

Este archivo existe para evitar una sola cosa: **que el portal conteste con
seguridad algo que no sabe.** En una planta, una respuesta inventada no es una
molestia: es un técnico desarmando una impresora que no tenía nada roto, o peor.

Todo empieza igual: **se busca en lo nuestro** —tickets resueltos, soluciones
generales y documentación de TI— y lo que se encuentre es la única fuente válida.
Lo que cambia es quién lo redacta, y eso depende de qué tan buena sea la
coincidencia.

**La escalera.** Se sube un peldaño solo cuando el anterior no alcanzó, y cada
peldaño cuesta más que el de abajo:

    Nivel 0 · DIRECTO      Hay una coincidencia clara con algo ya resuelto.
                           Se entrega esa solución tal cual. Ningún modelo
                           redacta nada. Instantáneo, gratis, y sin manera de
                           que se distorsione en el camino.

    Nivel 1 · OLLAMA       La coincidencia es parcial o hay varias fuentes que
                           conviene juntar. El modelo local redacta. Gratis y
                           dentro de la planta.

    Nivel 2 · GEMINI       Lo del nivel 1 no pasó los filtros. Redacta el
                           modelo de pago. Son las pocas consultas al mes que
                           justifican el gasto.

    Nivel 3 · EXTRACTOS    Ningún modelo disponible o ninguno produjo algo
                           utilizable. Se muestran los pasajes tal cual: menos
                           cómodo de leer, exactamente igual de cierto.

    Nivel 4 · TICKET       No hay nada parecido en el conocimiento de la
                           planta. Se dice, y se manda a levantar el ticket
                           para que lo atienda una persona.

El nivel 0 es el que más trabajo hace y el que menos se nota. Cuando alguien
escribe "me sale una raya negra" y eso ya está resuelto, no hay nada que redactar
—la respuesta ya está escrita— y meter un modelo en medio solo agrega latencia y
riesgo de que le cambie el sentido.
"""

import re
import unicodedata
from typing import List, Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import logger
from app.services.gemini_client import gemini
from app.services.ollama_client import ollama
from app.services.recuperacion_service import Pasaje, RecuperacionService

# Cómo se le pide a un modelo que redacte sin inventar.
#
# La primera versión de esto le exigía citar las fuentes con [1], [2]. Medido
# contra el modelo local: qwen2.5:3b contestaba literalmente "[1]" y nada más.
# Cumplía la regla de citar y no decía absolutamente nada.
#
# Así que se le pide lo que un modelo chico sí puede dar —los pasos, en prosa— y
# **la comprobación de que no inventó se hace aquí, no se le encarga a él**. Las
# fuentes se muestran en pantalla porque nosotros sabemos cuáles le dimos, no
# porque él las haya señalado.
PLANTILLA = """Eres el asistente de soporte técnico de una planta industrial en Querétaro.

Abajo hay notas de cómo se resolvieron antes fallas parecidas, tomadas de los
tickets de esta planta y de la documentación del área de TI.

Explica en español de México qué hacer, con los pasos de las notas. Máximo tres
pasos, directo, sin rodeos.

Reglas:
- Empieza por lo que SÍ funcionó. Si las notas dicen que algo ya se probó y no
  era, menciónalo al final para que nadie lo repita.
- No agregues pasos que no estén en las notas, aunque los sepas de otro lado.
- Si las notas no alcanzan para responder, escribe solo: NO_TENGO_INFORMACION
- Si hay que abrir un equipo o tocar instalación eléctrica, no lo expliques: di
  que lo vea TI en persona.

NOTAS:
{fragmentos}

Pregunta: {pregunta}

Qué hacer:"""

# La versión para el modelo local, y es corta a propósito.
#
# Medido sobre el mismo caso, dos intentos por formulación:
#
#   - Cuatro reglas y un preámbulo → "NO_TENGO_INFORMACION" las dos veces. El
#     modelo se acobarda teniendo la respuesta enfrente.
#   - Dos reglas, sin la de seguridad → preámbulo y paja; anclaje 0.27 y 0.39,
#     por debajo del corte.
#   - Esta → pasa las dos veces, anclaje 0.58 y 0.64, con los pasos correctos.
#
# La diferencia no es sutil ni es intuitiva: a un modelo de 3B cada regla de más
# le cuesta calidad. Si algún día se cambia el modelo local, conviene volver a
# medir esto en vez de dar por hecho que el prompt sigue siendo el bueno.
PLANTILLA_SIN_DESCARTES = """Con estas notas de soporte de la planta, explica en español qué hacer.
Máximo 3 pasos, solo con lo que digan las notas.
Si hay que abrir el equipo, di que lo vea TI en persona.
Si las notas no lo dicen, responde: NO_TENGO_INFORMACION

{fragmentos}

Pregunta: {pregunta}
Qué hacer:"""

SIN_INFORMACION = "NO_TENGO_INFORMACION"

# Palabras que no dicen nada sobre el contenido y no deben contar al medir si la
# respuesta salió de las fuentes.
VACIAS = {
    "según", "segun", "estos", "estas", "estos", "puede", "pueden", "sigue",
    "siguiente", "siguientes", "entonces", "también", "tambien", "porque",
    "cuando", "donde", "desde", "hasta", "sobre", "entre", "entrada", "notas",
    "nota", "pasos", "paso", "problema", "recomienda", "recomendable", "favor",
    "usted", "debería", "deberia", "debido", "manera", "forma", "caso",
}


class AsistenteService:

    @staticmethod
    def responder(
        db: Session,
        pregunta: str,
        sitio_id: int,
        categoria: Optional[str] = None,
        permitir_gemini: bool = True,
        pasajes: Optional[List[Pasaje]] = None,
    ) -> dict:
        """Contesta apoyado en el conocimiento de la planta.

        Siempre devuelve un dict con la misma forma. `origen` dice quién redactó
        —o si nadie lo hizo—, y `fuentes` trae de dónde salió cada cosa para que
        se pueda comprobar en pantalla.

        ``pasajes`` deja entrar una búsqueda ya hecha. Lo usa el endpoint del
        grafo, que recupera primero para poder encender el nodo del
        conocimiento antes de que el modelo empiece a redactar. Sin esto, la
        búsqueda se repetiría aquí dentro: otra vectorización y otro barrido de
        pgvector por consulta, para llegar al mismo resultado.
        """
        pregunta = (pregunta or "").strip()
        if not pregunta:
            return AsistenteService._vacio("pregunta_vacia", [])

        if pasajes is None:
            pasajes = RecuperacionService.buscar(db, pregunta, sitio_id, categoria=categoria)

        # --- Nivel 4: no hay de dónde ---
        if not pasajes:
            # Ni siquiera se llama al modelo. No hay con qué fundamentar una
            # respuesta, y un modelo al que no se le da nada, se lo inventa.
            return AsistenteService._vacio("sin_fundamento", [])

        # --- Nivel 0: la respuesta ya está escrita ---
        directo = AsistenteService._respuesta_directa(pasajes)
        if directo:
            return {
                "respuesta": directo,
                "origen": "directo",
                "fundamentada": True,
                "fuentes": [pasajes[0].a_dict()],
                "consumo": None,
                "siguiente_paso": "listo",
            }

        redaccion, origen, consumo = AsistenteService._redactar(
            pregunta, pasajes, permitir_gemini
        )

        if redaccion is None:
            # Ningún modelo disponible: se entregan los extractos tal cual.
            # Menos cómodo de leer, exactamente igual de cierto.
            return {
                "respuesta": None,
                "origen": "extractos",
                "fundamentada": True,
                "fuentes": [p.a_dict() for p in pasajes],
                "consumo": None,
                "siguiente_paso": "listo",
            }

        return {
            "respuesta": redaccion,
            "origen": origen,
            "fundamentada": True,
            # Las fuentes salen de lo que se recuperó, no de lo que el modelo
            # dijo haber usado. Un modelo puede mentir sobre su cita; el
            # recuperador no tiene cómo.
            "fuentes": [p.a_dict() for p in pasajes],
            "consumo": consumo,
            "siguiente_paso": "listo",
        }

    # ------------------------------------------------------------------
    @staticmethod
    def _respuesta_directa(pasajes: List[Pasaje]) -> Optional[str]:
        """La solución ya escrita, cuando la coincidencia no deja dudas.

        Dos condiciones, y las dos importan:

        - **Parecido alto.** Por debajo de `ASISTENTE_UMBRAL_DIRECTO` puede ser
          un problema distinto que se describe parecido.
        - **Nada distinto igual de bueno.** Si hay otro pasaje igual de bueno
          *y que dice otra cosa*, la respuesta está repartida entre los dos y sí
          hace falta juntarlos: eso es el nivel 1.

        El "y que dice otra cosa" no sobra. La misma falla se reporta tres veces
        y se resuelve igual las tres: son tres tickets, una sola respuesta. Sin
        esta comprobación, tres copias del mismo texto se tomaban por tres
        fuentes distintas y mandaban a redactar algo que ya estaba escrito.

        Cuando se cumplen, redactar solo agrega latencia y una oportunidad de
        que el modelo le cambie el sentido a algo que ya estaba bien.
        """
        if not pasajes or pasajes[0].similitud < settings.ASISTENTE_UMBRAL_DIRECTO:
            return None

        propias = AsistenteService._palabras(pasajes[0].texto)
        for otro in pasajes[1:]:
            if otro.similitud < settings.ASISTENTE_UMBRAL_DIRECTO:
                break        # vienen ordenados: los demás están aún más abajo
            ajenas = AsistenteService._palabras(otro.texto)
            if not propias or not ajenas:
                return None
            repetido = len(propias & ajenas) / min(len(propias), len(ajenas))
            if repetido < settings.ASISTENTE_DUPLICADO_MINIMO:
                return None        # dice otra cosa: hay que juntarlas

        return pasajes[0].texto.strip() or None

    @staticmethod
    def _redactar(pregunta: str, pasajes: List[Pasaje], permitir_gemini: bool):
        """Intenta redactar con el modelo más barato que alcance.

        Cada modelo recibe el contexto que puede manejar: al local se le omiten
        los descartes porque los confunde con instrucciones (ver
        `Pasaje.para_el_modelo`).
        """
        # 1. Ollama primero: corre en la planta y no cuesta.
        texto = ollama.responder_texto(
            AsistenteService._instruccion(pregunta, pasajes, con_descartes=False),
            num_predict=settings.ASISTENTE_MAX_TOKENS,
            timeout=settings.OLLAMA_TIMEOUT_ASISTENCIA,
        )
        if texto is not None:
            valido = AsistenteService._validar(texto, pasajes)
            if valido is not None:
                return valido, "ollama", None

        # 2. Gemini solo si Ollama no alcanzó y está permitido. A él sí se le
        #    pasan los descartes: sabe distinguir "esto se probó" de "haz esto".
        if permitir_gemini and gemini.configurado:
            respuesta = gemini.redactar(
                AsistenteService._instruccion(pregunta, pasajes, con_descartes=True)
            )
            if respuesta:
                valido = AsistenteService._validar(respuesta["respuesta"], pasajes)
                if valido is not None:
                    return valido, "gemini", {
                        "tokens_entrada": respuesta.get("tokens_entrada", 0),
                        "tokens_salida": respuesta.get("tokens_salida", 0),
                        "modelo": respuesta.get("modelo"),
                    }

        return None, "extractos", None

    @staticmethod
    def _instruccion(pregunta: str, pasajes: List[Pasaje], con_descartes: bool) -> str:
        fragmentos = "\n\n".join(
            p.para_el_modelo(i + 1, incluir_descarte=con_descartes)
            for i, p in enumerate(pasajes)
        )
        plantilla = PLANTILLA if con_descartes else PLANTILLA_SIN_DESCARTES
        return plantilla.format(fragmentos=fragmentos, pregunta=pregunta)

    @staticmethod
    def _validar(texto: Optional[str], pasajes: List[Pasaje]) -> Optional[str]:
        """Deja pasar la respuesta solo si de verdad salió de las fuentes.

        Tres motivos para rechazarla, y los tres significan lo mismo: el modelo
        se salió de lo que se le dio.
        """
        if not texto:
            return None
        limpio = re.sub(r"\[\d{1,2}\]", "", texto).strip()

        # 1. El modelo hizo lo correcto: dijo que no sabe.
        if SIN_INFORMACION in limpio.upper().replace(" ", "_"):
            return None

        # 2. No dijo nada. Pasó de verdad con el modelo local: contestaba "[1]".
        if len(limpio) < settings.ASISTENTE_MIN_CARACTERES:
            logger.info("Respuesta demasiado corta para servir; se muestran extractos",
                        extra={"caracteres": len(limpio)})
            return None

        # 3. Habló de otra cosa. Se mide qué tanto del vocabulario con contenido
        #    de la respuesta aparece en las fuentes que se le dieron.
        anclaje = AsistenteService._anclaje(limpio, pasajes)
        if anclaje < settings.ASISTENTE_ANCLAJE_MINIMO:
            logger.warning("Respuesta poco anclada en las fuentes; se descarta",
                           extra={"anclaje": round(anclaje, 2)})
            return None

        return limpio

    @staticmethod
    def _palabras(texto: str) -> set:
        """Palabras con contenido, recortadas a su raíz aproximada.

        Dos decisiones, las dos aprendidas midiendo:

        - **Cinco letras mínimo.** Se lleva por delante casi todas las palabras
          funcionales del español —artículos, preposiciones, conjunciones— sin
          necesidad de una lista exhaustiva.
        - **Recorte a cinco letras.** La nota dice "se limpió" y el modelo
          escribe "limpiar"; son la misma palabra y comparadas enteras no
          coinciden. Recortadas las dos a "limpi", sí. Es un derivador pobre,
          pero para medir parecido de vocabulario alcanza y no cuesta nada.
        """
        plano = unicodedata.normalize("NFKD", texto.lower())
        plano = "".join(c for c in plano if not unicodedata.combining(c))
        crudas = [p for p in re.findall(r"[a-z0-9]{5,}", plano) if p not in VACIAS]
        return {p[:5] for p in crudas}

    @staticmethod
    def anclaje_en_texto(candidato: str, original: str) -> float:
        """Qué fracción del vocabulario de `candidato` sale de `original`.

        Es `_anclaje` contra un texto suelto en vez de contra pasajes
        recuperados. La usa la normalización de descripciones, que tiene el
        mismo problema —un modelo chico reescribiendo puede meter cosas que
        nadie dijo— pero una sola fuente contra la que comparar.

        **Lo que detecta y lo que no, medido.** Contra reescrituras reales de
        qwen2.5:3b:

            reescritura fiel .......... 0,67
            reescritura correcta ...... 0,57
            inventa una frase ......... 0,50   <-- NO se separa de las buenas
            inventa el tema entero .... 0,00

        O sea: atrapa que el modelo se vaya a otro asunto, y **no** atrapa que
        cuele una frase plausible dentro de un texto por lo demás correcto —
        "el técnico de TI no pudo conectar la etiquetadora" cuando nadie
        mencionó ningún técnico—. Los 7 puntos entre 0,50 y 0,57 no dan para
        poner un corte: cualquier umbral ahí estaría ajustado a dos ejemplos y
        tiraría reescrituras buenas.

        Por eso el corte va bajo, donde hay hueco de verdad, y la defensa
        contra el caso sutil es otra: **la descripción original nunca se pisa**
        —se guarda aparte, se muestra primero en el ticket y se indexa siempre—
        así que lo que el usuario escribió sigue estando ahí para comprobarlo.
        """
        palabras = AsistenteService._palabras(candidato)
        if not palabras:
            return 0.0
        return len(palabras & AsistenteService._palabras(original)) / len(palabras)

    @staticmethod
    def _anclaje(respuesta: str, pasajes: List[Pasaje]) -> float:
        """Qué fracción del vocabulario de la respuesta viene de las fuentes.

        **Es una heurística, no una demostración.** Detecta que el modelo se fue
        por otro lado —habla de fusores y kits de mantenimiento cuando la nota
        decía rodillo—, no una tergiversación fina de lo que sí está escrito.
        Por eso las fuentes se enseñan siempre junto a la respuesta: la
        comprobación final la hace una persona, no esta función.
        """
        palabras = AsistenteService._palabras(respuesta)
        if not palabras:
            return 0.0

        fuente = set()
        for pasaje in pasajes:
            fuente |= AsistenteService._palabras(pasaje.titulo + " " + pasaje.texto)
            if pasaje.descartado:
                fuente |= AsistenteService._palabras(pasaje.descartado)

        return len(palabras & fuente) / len(palabras)

    @staticmethod
    def _vacio(motivo: str, fuentes: list) -> dict:
        return {
            "respuesta": None,
            "origen": motivo,
            "fundamentada": False,
            "fuentes": fuentes,
            "consumo": None,
            # Lo que le toca hacer a la persona. Sin esto, el "no sé" deja a
            # alguien mirando una pantalla sin saber por dónde seguir.
            "siguiente_paso": "levantar_ticket",
        }

"""Cliente de Ollama para el asistente local.

Regla única e innegociable de este módulo: **ninguna función de aquí levanta
una excepción hacia el llamador**. Si Ollama no responde, tarda de más, no
tiene el modelo cargado o devuelve basura, la función devuelve ``None`` y el
flujo de negocio continúa sin la ayuda de IA.

La IA es una mejora, no un requisito. Un fallo de Ollama nunca puede impedir
que se levante, se atienda o se cierre un ticket.
"""

import json
import re
import threading
import time
from collections import OrderedDict, deque
from typing import List, Optional

import httpx

from app.core.config import settings
from app.core.logging import logger
from app.services import cola_ia

# Las mismas seis del dropdown. El modelo clasifica dentro de esta lista o no
# clasifica: nunca inventa una categoría nueva.
CATEGORIAS_VALIDAS = ("impresora", "red", "equipo", "software", "accesos", "otro")


def normalizar_categoria(categoria):
    """La categoría en su forma canónica, o `None` si no es una de las seis.

    Vive junto a la lista que valida, no en un módulo aparte: quien añada una
    categoría a `CATEGORIAS_VALIDAS` tiene que ver esto en la misma pantalla.

    **Por qué hace falta.** `categoria` llega de parámetros de consulta y de
    cuerpos de petición sin que nadie la valide, y los filtros se escribían con
    `ILIKE`. En `ILIKE`, `%` y `_` son comodines: pedir la categoría `%`
    desactivaba el filtro sin decirlo, y `imp%` casaba con «impresora».

    Devolver `None` y no lanzar es deliberado: quien llama decide qué significa
    una categoría que no existe, y **no significa lo mismo en todas partes**.
    En una búsqueda ordenada por parecido, lo sensato es buscar en todas —
    devuelve de más, nunca de menos—. En una lista sin orden de relevancia,
    como los pasos de un checklist, buscar en todas enseñaría los pasos de otro
    problema, así que ahí lo correcto es no devolver nada.
    """
    if not categoria:
        return None
    limpia = str(categoria).strip().lower()
    return limpia if limpia in CATEGORIAS_VALIDAS else None

# Vocabulario real de la planta. Es un atajo determinista antes del modelo:
# cuando el usuario usa una de estas palabras, la categoría es inequívoca y no
# hace falta gastar 2-4 segundos de LLM para averiguarla.
#
# Esto es más rápido Y más preciso que un modelo de 3B para los casos conocidos,
# y encima es auditable: si clasifica mal, se corrige una línea de esta tabla en
# lugar de reentrenar nada.
VOCABULARIO_PLANTA = {
    "impresora": (
        "impresora", "impresoras", "etiquetadora", "etiquetadoras", "zebra",
        "toner", "tóner", "ribbon", "etiqueta", "etiquetas", "imprimir",
        "imprime", "impresion", "impresión", "atasco", "atascada", "papel",
        "codigo de barras", "código de barras", "termica", "térmica",
    ),
    "red": (
        "wifi", "wi-fi", "internet", "red", "conexion", "conexión", "cable de red",
        "ethernet", "switch", "router", "vpn", "ip", "dns", "lento el internet",
        "sin señal", "sin senal", "access point", "nodo", "rack",
        # Anadidos midiendo: "se cae la senal en embarques" no llevaba ninguna
        # palabra de la tabla y se iba al modelo, que en esta maquina cuesta
        # 9-10 s. Todos inequivocos en un contexto de soporte de TI.
        # "enlace" se descarto: en software es un hipervinculo.
        "señal", "senal", "cobertura", "antena", "lan", "wlan",
        "se desconecta", "sin internet", "sin acceso a la red",
    ),
    "equipo": (
        "laptop", "computadora", "compu", "pc", "monitor", "pantalla", "teclado",
        "mouse", "raton", "ratón", "cpu", "disco duro", "bateria", "batería",
        "cargador", "docking", "escaner", "escáner", "scanner", "no enciende",
        "se apaga", "pantalla azul", "handheld", "terminal portatil",
        "terminal portátil", "lectora",
        # Lo mismo: "la terminal del comedor no lee el gafete" y "se reinicia
        # sola" no coincidian con nada. La frase del gafete la atrapa
        # "terminal", que es el lector.
        #
        # **"gafete" NO entra**, y merece la pena dejar dicho por que: se anadio
        # y una prueba que ya existia lo tumbo. "El gafete no me abre la puerta
        # del almacen" es control de acceso fisico, no un equipo de TI. El valor
        # de esta tabla es que sus terminos son inequivocos; en cuanto entra uno
        # que no lo es, el atajo empieza a mandar incidencias a la cola
        # equivocada sin que nadie lo revise. Por lo mismo se quedaron fuera
        # "se congela" (¿la aplicacion o el equipo?) y "enlace".
        "terminal", "checador", "no reinicia", "se reinicia",
        "no prende", "no responde el equipo", "se traba el equipo",
    ),
    "software": (
        "sap", "erp", "excel", "office", "outlook", "word", "programa",
        "aplicacion", "aplicación", "sistema", "licencia", "actualizacion",
        "actualización", "windows", "navegador", "chrome", "edge", "mes",
        "scada", "error de sistema",
        # "no me carga el tablero" y "se traba al generar el reporte" tampoco
        # coincidian. Son cosas que solo existen dentro de una aplicacion.
        # "no carga" se descarto: en español es tanto "no se carga la pantalla"
        # como "no se carga la bateria", que son dos categorias distintas.
        "tablero", "reporte", "modulo", "módulo", "captura", "formulario",
        "no guarda", "se cierra solo",
    ),
    "accesos": (
        "contraseña", "contrasena", "password", "usuario bloqueado", "cuenta",
        "acceso", "accesos", "permiso", "permisos", "correo", "email",
        "no me deja entrar", "bloqueado", "bloqueada", "credenciales",
        "vpn acceso", "carpeta compartida", "unidad de red",
    ),
}

# Los prompts de sistema son **cortos a propósito, y no por estilo**.
#
# Medido en esta máquina: generar la respuesta va a ~29 tokens/s y leer el
# prompt **entre 11 y 50**, según acierte o no la caché de Ollama. En una
# consulta corta eso significa que el prompt cuesta más que la respuesta: el de
# clasificación tenía 277 tokens para producir 18.
#
# Lo que decide el precio es si la llamada anterior uso el mismo prompt:
#
#     misma instruccion seguida ..... leer a ~50 tok/s -> ~2 s
#     alternando con otra ........... leer a ~11 tok/s -> ~9 s
#
# Se probo darle a Ollama varias ranuras (`OLLAMA_NUM_PARALLEL`) para que cada
# prompt conservara la suya caliente. **No cambio nada**, medido; ver la nota
# en docker-compose.yml. Asi que lo unico que queda bajo control aqui es que el
# prompt sea corto.
#
# Regla al editarlos: cada línea que se añade aquí se paga en **cada consulta**
# que no acierte la caché. Lo que se pueda comprobar en código —que la
# categoría esté en la lista, que la confianza esté entre 0 y 1— se comprueba
# en código, que es gratis y no se le olvida al modelo. Y ojo: **acortarlos de
# mas tambien se paga.** Una version de 25 tokens acerto 0 de 4 casos contra
# 4 de 4 de la actual, y encima fue mas lenta.
PROMPT_CLASIFICACION = (
    "Clasifica la incidencia de soporte en una categoría:\n"
    "impresora, red, equipo, software, accesos, otro.\n"
    'Responde solo JSON: {"categoria": "...", "confianza": 0.0-1.0}\n'
    "Si el mensaje es vago, confianza menor a 0.5."
)

PROMPT_NORMALIZACION = (
    "Reescribe el reporte para un técnico de TI, en 2 o 3 oraciones.\n"
    "No inventes nada. Conserva equipo, área y mensajes de error.\n"
    "Mismo idioma del usuario. Solo la descripción, sin comentarios."
)


def _opciones(**extra) -> dict:
    """Las opciones de una llamada al modelo de **texto**.

    Existe para un solo motivo: que `num_thread` viaje en todas y no se quede
    en una. Repartir entre los ocho núcleos —que es lo que hace Ollama por su
    cuenta— resulta seis veces más lento para leer el prompt que usar cuatro en
    esta máquina; el porqué y los números están en `OLLAMA_HILOS_TEXTO`.

    Los embeddings **no** pasan por aquí: ahí el reparto por defecto gana.
    """
    return {"num_thread": settings.OLLAMA_HILOS_TEXTO, **extra}


def _instruir(instruccion: str, texto: str) -> str:
    """Pega las instrucciones delante del texto, en un solo `prompt`.

    **Existe por una diferencia medida, no por gusto.** Ollama admite mandar
    las instrucciones en un campo `system` aparte, que es lo que hacia este
    modulo. Medido aqui, alternando las tres operaciones del portal:

        con `system`   leer 90 tokens -> 9,8 s   (la cache no acerto nunca)
        sin `system`   leer 41 tokens -> 0,0 s   (acierto limpio)

    Con las instrucciones dentro del `prompt`, el principio del texto es
    identico en cada llamada y llama.cpp puede reutilizar lo que ya tenia
    leido. Mandandolas en `system` volvia a leerlo todo cada vez, sin excepcion.

    **No garantiza un acierto**: si entre dos llamadas iguales se cuela otra con
    una instruccion distinta, la caché se pierde igual y se vuelve a los ~9 s.
    Lo que este cambio quita es el caso en que fallaba *siempre*.

    Esa diferencia era la que hacia que la normalizacion y la clasificacion se
    pasaran de sus diez segundos de timeout y fallaran **en cada ticket**, en
    silencio, desde siempre.

    Corolario para quien edite esto: **la instruccion va primero y el texto
    variable despues**. Al reves no hay prefijo comun que cachear y se vuelve a
    pagar la lectura entera.
    """
    return f"{instruccion}\n\n{texto}"


class OllamaClient:
    """Envoltura sobre la API de Ollama con degradación silenciosa."""

    # Cuántas muestras se conservan por operación para el promedio.
    MUESTRAS_LATENCIA = 50

    def __init__(self, host: Optional[str] = None):
        self.host = (host or settings.OLLAMA_HOST).rstrip("/")
        # Latencias en memoria, por proceso. Sirven para ver si Ollama va lento
        # ahora mismo; no son un histórico y se pierden al reiniciar.
        self._latencias = {"embedding": deque(maxlen=self.MUESTRAS_LATENCIA),
                           "normalizacion": deque(maxlen=self.MUESTRAS_LATENCIA),
                           "clasificacion": deque(maxlen=self.MUESTRAS_LATENCIA),
                           "asistencia": deque(maxlen=self.MUESTRAS_LATENCIA)}
        # Vectores ya calculados, los más recientes al final. Con candado
        # porque el servidor atiende en varios hilos y un `OrderedDict` no es
        # seguro entre ellos.
        self._vectores = OrderedDict()
        self._candado_vectores = threading.Lock()

    # ------------------------------------------------------------------
    # Caché de vectores
    # ------------------------------------------------------------------
    def _recordado(self, clave):
        """El vector de esa clave, si se calculó hace poco.

        Devuelve una **copia**: el que llama puede hacer lo que quiera con la
        lista sin que eso corrompa lo guardado para el siguiente.
        """
        if settings.EMBEDDING_CACHE_MAX <= 0:
            return None
        with self._candado_vectores:
            vector = self._vectores.get(clave)
            if vector is None:
                return None
            # Recién usado, al final: lo que se cae es lo más viejo.
            self._vectores.move_to_end(clave)
            return list(vector)

    def _recordar(self, clave, vector: List[float]) -> None:
        if settings.EMBEDDING_CACHE_MAX <= 0:
            return
        with self._candado_vectores:
            self._vectores[clave] = list(vector)
            self._vectores.move_to_end(clave)
            while len(self._vectores) > settings.EMBEDDING_CACHE_MAX:
                self._vectores.popitem(last=False)

    def olvidar_vectores(self) -> None:
        """Vacía la caché. La usan las pruebas para no heredar estado.

        Es el mismo cuidado que ya se tiene con los limitadores de intentos:
        un objeto de módulo vive mientras viva el proceso, y sin limpiarlo el
        resultado de una prueba depende de las que corrieron antes.
        """
        with self._candado_vectores:
            self._vectores.clear()

    def _registrar(self, operacion: str, inicio: float):
        """Anota cuánto tardó una llamada.

        Crea el cajón si no existía. Antes reventaba con KeyError ante una
        operación nueva, y como toda esta clase atrapa excepciones para
        degradar en silencio, **la llamada se daba por fallida aunque Ollama
        hubiera contestado bien**. Llevar la cuenta de una métrica no puede
        tumbar la función que mide.
        """
        cajon = self._latencias.setdefault(operacion, deque(maxlen=self.MUESTRAS_LATENCIA))
        cajon.append((time.monotonic() - inicio) * 1000.0)

    def latencias(self) -> dict:
        """Promedio en milisegundos por operación. None si no hay muestras."""
        return {
            nombre: round(sum(muestras) / len(muestras), 1) if muestras else None
            for nombre, muestras in self._latencias.items()
        }

    # ------------------------------------------------------------------
    # Disponibilidad
    # ------------------------------------------------------------------
    def modelos(self) -> Optional[List[str]]:
        """Qué modelos tiene descargados. None si no contesta."""
        if not settings.IA_HABILITADA:
            return None
        try:
            with httpx.Client(timeout=2.0) as cliente:
                respuesta = cliente.get(self.host + "/api/tags")
                if respuesta.status_code != 200:
                    return None
                return [m.get("name", "") for m in respuesta.json().get("models", [])]
        except Exception as exc:  # noqa: BLE001 - degradación deliberada
            logger.warning(
                "Ollama no disponible",
                extra={"host": self.host, "error": str(exc)},
            )
            return None

    def faltan_modelos(self) -> List[str]:
        """Los modelos configurados que Ollama no tiene descargados."""
        descargados = self.modelos()
        if descargados is None:
            return []
        # Ollama devuelve "qwen2.5:3b"; la configuración puede traerlo sin la
        # etiqueta, así que se compara por el nombre base.
        base = {n.split(":")[0] for n in descargados}
        return [
            m for m in (settings.OLLAMA_MODELO_EMBEDDING, settings.OLLAMA_MODELO_TEXTO)
            if m.split(":")[0] not in base
        ]

    def disponible(self) -> bool:
        """True si Ollama contesta **y tiene con qué trabajar**.

        Antes bastaba con que el servicio respondiera. Eso daba una luz verde
        engañosa: un Ollama recién levantado contesta perfectamente y no tiene
        ningún modelo descargado, así que no genera embeddings, la búsqueda no
        encuentra nada, el asistente responde "sin fundamento" y Gemini —que
        solo entra cuando Ollama no alcanza— no llega a entrar nunca. Todo el
        sistema de IA muerto, y el tablero en verde. Pasó exactamente así.
        """
        if not settings.IA_HABILITADA:
            return False
        return self.modelos() is not None and not self.faltan_modelos()

    # ------------------------------------------------------------------
    # Embeddings
    # ------------------------------------------------------------------
    def generar_embedding(self, texto: str, tarea: str = "documento") -> Optional[List[float]]:
        """Devuelve el vector del texto, o None si algo falla.

        None significa "sigue sin búsqueda por similitud", no "error".

        ``tarea`` es "documento" al indexar y "consulta" al buscar.
        nomic-embed-text está entrenado con prefijos de tarea y sin ellos la
        recuperación pierde precisión; se aplican solo a ese modelo para no
        romper otros que no los esperan.

        Ojo al cambiar esto: los vectores ya guardados se generaron con el
        criterio anterior. Hay que correr `reindexar_kb.py` para que la base
        quede consistente.

        **Se recuerda lo ya calculado.** La misma frase se vectoriza varias
        veces en la misma pantalla —al escribir un ticket consultan por
        separado las sugerencias parecidas, la respuesta del asistente y el
        catálogo visual— y cada una costaba sus ~80 ms de CPU. Un embedding es
        una función pura del texto y del modelo, así que recordarlo no cambia
        ninguna respuesta: solo quita trabajo repetido. Ver `EMBEDDING_CACHE_MAX`.
        """
        if not settings.IA_HABILITADA:
            return None
        if not texto or not texto.strip():
            return None

        if "nomic" in settings.OLLAMA_MODELO_EMBEDDING.lower():
            prefijo = "search_query: " if tarea == "consulta" else "search_document: "
            texto = prefijo + texto

        # **La clave se arma después del prefijo, y eso no es un detalle.** El
        # mismo texto vectorizado como consulta y como documento da vectores
        # distintos —nomic está entrenado con esos prefijos— y confundirlos
        # devolvería el vector equivocado sin que nada fallara: la búsqueda
        # simplemente encontraría peor, en silencio. Con el prefijo ya pegado,
        # las dos formas son dos claves distintas. El modelo entra también,
        # para que cambiarlo no reutilice vectores del anterior.
        clave = (settings.OLLAMA_MODELO_EMBEDDING, texto)
        recordado = self._recordado(clave)
        if recordado is not None:
            return recordado

        inicio = time.monotonic()
        try:
            # Compuerta de embeddings, separada de la de generación: una
            # búsqueda por similitud no tiene por qué esperar detrás de una
            # redacción de cuatro segundos. Ver app/services/cola_ia.py.
            with cola_ia.embeddings.turno() as hay_turno:
                if not hay_turno:
                    return None
                with httpx.Client(timeout=settings.OLLAMA_TIMEOUT_EMBEDDING) as cliente:
                    respuesta = cliente.post(
                        self.host + "/api/embeddings",
                        json={
                            "model": settings.OLLAMA_MODELO_EMBEDDING,
                            "prompt": texto,
                            "keep_alive": settings.OLLAMA_KEEP_ALIVE,
                        },
                    )
                    respuesta.raise_for_status()
                    vector = respuesta.json().get("embedding")
            self._registrar("embedding", inicio)

            if not isinstance(vector, list) or not vector:
                logger.warning(
                    "Ollama devolvió un embedding vacío o con formato inesperado",
                    extra={"modelo": settings.OLLAMA_MODELO_EMBEDDING},
                )
                return None

            # Solo se recuerdan los aciertos. Guardar un `None` convertiría un
            # fallo momentáneo de Ollama en un fallo permanente para esa frase.
            self._recordar(clave, vector)
            return vector

        except httpx.TimeoutException:
            logger.warning(
                "Timeout generando embedding; se omite la búsqueda por similitud",
                extra={"timeout": settings.OLLAMA_TIMEOUT_EMBEDDING},
            )
            return None
        except Exception as exc:  # noqa: BLE001 - degradación deliberada
            logger.error(
                "Fallo generando embedding; el flujo continúa sin él",
                extra={"error": str(exc), "modelo": settings.OLLAMA_MODELO_EMBEDDING},
            )
            return None

    # ------------------------------------------------------------------
    # Normalización de descripción
    # ------------------------------------------------------------------
    def normalizar_descripcion(self, texto: str) -> Optional[str]:
        """Reescribe el texto libre del usuario, o None si algo falla.

        None significa "guarda solo la descripción original".
        """
        if not settings.IA_HABILITADA:
            return None
        if not texto or not texto.strip():
            return None

        inicio = time.monotonic()
        try:
            with cola_ia.generacion.turno() as hay_turno:
                if not hay_turno:
                    # Sin turno se guarda la descripción original tal cual, que
                    # es lo que ya pasaba cuando Ollama no contestaba. El
                    # ticket se levanta igual.
                    return None
                with httpx.Client(timeout=settings.OLLAMA_TIMEOUT_NORMALIZACION) as cliente:
                    respuesta = cliente.post(
                        self.host + "/api/generate",
                        json={
                            "model": settings.OLLAMA_MODELO_TEXTO,
                            # Las instrucciones van **dentro del `prompt`**, no
                            # en el campo `system`. Ver la nota de `_instruir`.
                            "prompt": _instruir(PROMPT_NORMALIZACION, texto),
                            "stream": False,
                            "keep_alive": settings.OLLAMA_KEEP_ALIVE,
                            # 150 y no 300: la instruccion pide 2-3 oraciones y
                            # lo medido son ~22 tokens. 300 no acotaba nada
                            # util, solo dejaba sitio para irse por las ramas.
                            "options": _opciones(num_predict=150, temperature=0.2),
                        },
                    )
                    respuesta.raise_for_status()
                    normalizada = (respuesta.json().get("response") or "").strip()
            self._registrar("normalizacion", inicio)

            if not normalizada:
                return None
            return normalizada

        except httpx.TimeoutException:
            logger.warning(
                "Timeout normalizando descripción; se usa la descripción original",
                extra={"timeout": settings.OLLAMA_TIMEOUT_NORMALIZACION},
            )
            return None
        except Exception as exc:  # noqa: BLE001 - degradación deliberada
            logger.error(
                "Fallo normalizando descripción; se usa la descripción original",
                extra={"error": str(exc), "modelo": settings.OLLAMA_MODELO_TEXTO},
            )
            return None

    # ------------------------------------------------------------------
    # Clasificación de categoría (chatbot)
    # ------------------------------------------------------------------
    def clasificar_categoria(self, texto: str) -> Optional[dict]:
        """Clasifica el texto en una de las seis categorías del dropdown.

        Devuelve ``{"categoria": str, "confianza": float}`` o None si algo
        falla. None significa "pide la categoría con el dropdown", nunca un
        error para el usuario.

        Ojo: esto solo elige categoría. Las reglas de negocio se evalúan
        después, en el motor de reglas — un modelo nunca decide a qué
        proveedor va una incidencia.
        """
        if not settings.IA_HABILITADA:
            return None
        if not texto or not texto.strip():
            return None

        # Un texto sin contenido suficiente no se manda al modelo: "no sirve"
        # no pertenece a ninguna categoría, pero qwen2.5:3b le asigna 0.9 de
        # confianza igual. Se corta antes de preguntar y se piden los dropdowns.
        limpio = texto.strip()
        if len(limpio) < settings.CHAT_MIN_CARACTERES or len(limpio.split()) < settings.CHAT_MIN_PALABRAS:
            logger.info(
                "Mensaje sin contenido suficiente para clasificar; se piden los dropdowns",
                extra={"caracteres": len(limpio), "palabras": len(limpio.split())},
            )
            return None

        # Atajo por vocabulario: instantáneo y sin ambigüedad.
        rapida = self.clasificar_por_vocabulario(limpio)
        if rapida is not None:
            logger.info(
                "Clasificado por vocabulario, sin llamar al modelo",
                extra={"categoria": rapida["categoria"]},
            )
            return rapida

        inicio = time.monotonic()
        try:
            with cola_ia.generacion.turno() as hay_turno:
                if not hay_turno:
                    # Sin turno se piden los dropdowns, igual que cuando el
                    # modelo no está seguro. El usuario elige y sigue.
                    return None
                with httpx.Client(timeout=settings.OLLAMA_TIMEOUT_CLASIFICACION) as cliente:
                    respuesta = cliente.post(
                        self.host + "/api/generate",
                        json={
                            "model": settings.OLLAMA_MODELO_TEXTO,
                            "prompt": _instruir(PROMPT_CLASIFICACION, texto),
                            "stream": False,
                            "keep_alive": settings.OLLAMA_KEEP_ALIVE,
                            "format": "json",
                            # 40 y no 120: la respuesta es un JSON de una linea
                            # y lo medido son 18 tokens.
                            "options": _opciones(num_predict=40, temperature=0.0),
                        },
                    )
                    respuesta.raise_for_status()
                    crudo = (respuesta.json().get("response") or "").strip()
            self._registrar("clasificacion", inicio)

            return self._parsear_clasificacion(crudo)

        except httpx.TimeoutException:
            logger.warning(
                "Timeout clasificando categoría; se piden los dropdowns",
                extra={"timeout": settings.OLLAMA_TIMEOUT_CLASIFICACION},
            )
            return None
        except Exception as exc:  # noqa: BLE001 - degradación deliberada
            logger.error(
                "Fallo clasificando categoría; se piden los dropdowns",
                extra={"error": str(exc), "modelo": settings.OLLAMA_MODELO_TEXTO},
            )
            return None

    @staticmethod
    def clasificar_por_vocabulario(texto: str) -> Optional[dict]:
        """Clasifica por palabras de la planta, sin llamar al modelo.

        Devuelve None si no hay coincidencias o si hay empate entre dos
        categorías: en la duda decide el modelo, y si tampoco puede, el usuario.
        """
        minusculas = " " + texto.lower() + " "
        puntajes = {}

        for categoria, terminos in VOCABULARIO_PLANTA.items():
            aciertos = sum(1 for termino in terminos if termino in minusculas)
            if aciertos:
                puntajes[categoria] = aciertos

        if not puntajes:
            return None

        ordenadas = sorted(puntajes.items(), key=lambda par: par[1], reverse=True)
        mejor, puntaje_mejor = ordenadas[0]

        # Empate: el texto menciona dos mundos a la vez ("la impresora no
        # aparece en la red"). No se adivina, que decida el modelo.
        if len(ordenadas) > 1 and ordenadas[1][1] == puntaje_mejor:
            return None

        # Más términos coincidentes = más señal. Se topa en 0.95 para no
        # afirmar certeza absoluta a partir de una coincidencia de texto.
        confianza = min(0.95, 0.80 + 0.05 * (puntaje_mejor - 1))
        return {"categoria": mejor, "confianza": round(confianza, 2)}

    def responder_texto(self, instruccion: str, num_predict: int = 400,
                        timeout: Optional[float] = None) -> Optional[str]:
        """Redacción libre con el modelo local. None si no está o falla.

        La usa el asistente para redactar sobre pasajes que ya se recuperaron.
        Como todo aquí: si Ollama no contesta, devuelve None y quien llama sigue
        su camino sin él.
        """
        if not settings.IA_HABILITADA or not instruccion or not instruccion.strip():
            return None

        inicio = time.monotonic()
        try:
            with cola_ia.generacion.turno() as hay_turno:
                if not hay_turno:
                    # Sin turno el asistente entrega los extractos tal cual:
                    # menos cómodo de leer, exactamente igual de cierto.
                    return None
                with httpx.Client(timeout=timeout or settings.OLLAMA_TIMEOUT_ASISTENCIA) as cliente:
                    respuesta = cliente.post(
                        self.host + "/api/generate",
                        json={
                            "model": settings.OLLAMA_MODELO_TEXTO,
                            "prompt": instruccion,
                            "stream": False,
                            "keep_alive": settings.OLLAMA_KEEP_ALIVE,
                            "options": _opciones(num_predict=num_predict, temperature=0.1),
                        },
                    )
                    respuesta.raise_for_status()
                    cuerpo = respuesta.json()
                    texto = (cuerpo.get("response") or "").strip()
            self._registrar("asistencia", inicio)
            if cuerpo.get("done_reason") == "length":
                # **Una respuesta cortada no se entrega.**
                #
                # Al chocar con `num_predict` el modelo se detiene donde iba,
                # no donde terminaba, y Ollama devuelve el trozo con un 200
                # como si fuera la respuesta entera. Medido con el tope real de
                # producción (400) y una pregunta corriente, el corte cayó en
                # «1. **Limpie la pantalla y la» — media instrucción sobre un
                # equipo físico, con aspecto de estar completa.
                #
                # Recortar hasta el último paso entero sería peor: quedaría un
                # procedimiento que se lee terminado y al que le falta el final,
                # que es justo donde suelen ir las advertencias. Devolver None
                # deja seguir a la cascada —Gemini, y si no los extractos tal
                # cual—, que es lo que ya hace este cliente cuando no alcanza.
                logger.warning(
                    "El modelo local se quedó sin espacio y la respuesta salió "
                    "cortada; se sigue sin ella",
                    extra={"num_predict": num_predict,
                           "generados": cuerpo.get("eval_count")},
                )
                return None
            return texto or None
        except Exception as exc:  # noqa: BLE001 - degradación deliberada
            logger.warning("No se pudo redactar con el modelo local; se sigue sin él",
                           extra={"error": str(exc)})
            return None

    def responder_json(self, instruccion: str, num_predict: int = 300,
                       timeout: Optional[float] = None) -> Optional[dict]:
        """Le pide al modelo un objeto JSON. Devuelve None si algo falla.

        De uso general, para tareas donde el modelo **propone** y una persona
        confirma —el mapeo de columnas de un archivo de RH, por ejemplo—. Como
        todo en este cliente: si Ollama no está, esto devuelve None y quien
        llama sigue su camino sin el modelo.
        """
        if not settings.IA_HABILITADA or not instruccion or not instruccion.strip():
            return None

        inicio = time.monotonic()
        try:
            with cola_ia.generacion.turno() as hay_turno:
                if not hay_turno:
                    return None
                with httpx.Client(timeout=timeout or settings.OLLAMA_TIMEOUT_ASISTENCIA) as cliente:
                    respuesta = cliente.post(
                        self.host + "/api/generate",
                        json={
                            "model": settings.OLLAMA_MODELO_TEXTO,
                            "prompt": instruccion,
                            "stream": False,
                            "format": "json",
                            "keep_alive": settings.OLLAMA_KEEP_ALIVE,
                            "options": _opciones(num_predict=num_predict, temperature=0.0),
                        },
                    )
                    respuesta.raise_for_status()
                    cuerpo = respuesta.json()
                    crudo = (cuerpo.get("response") or "").strip()
            self._registrar("asistencia", inicio)
            if cuerpo.get("done_reason") == "length":
                # Un JSON cortado casi siempre falla al parsear más abajo, pero
                # no siempre: el rescate por expresión regular puede pescar un
                # objeto anidado que sí cierra y devolverlo como si fuera la
                # respuesta. Cortarlo aquí evita ese caso.
                logger.warning(
                    "El modelo local se quedó sin espacio y el JSON salió "
                    "cortado; se sigue sin él",
                    extra={"num_predict": num_predict,
                           "generados": cuerpo.get("eval_count")},
                )
                return None
        except Exception as exc:  # noqa: BLE001 - degradación deliberada
            logger.warning("No se pudo consultar al modelo; se sigue sin él",
                           extra={"error": str(exc)})
            return None

        try:
            datos = json.loads(crudo)
        except (ValueError, TypeError):
            encontrado = re.search(r"\{.*\}", crudo, re.DOTALL)
            if not encontrado:
                return None
            try:
                datos = json.loads(encontrado.group(0))
            except (ValueError, TypeError):
                return None

        return datos if isinstance(datos, dict) else None

    @staticmethod
    def _parsear_clasificacion(crudo: str) -> Optional[dict]:
        """Extrae la clasificación de la respuesta del modelo.

        Un modelo pequeño a veces envuelve el JSON en texto o inventa una
        categoría. Cualquier cosa que no encaje se trata como "no clasificado".
        """
        if not crudo:
            return None

        datos = None
        try:
            datos = json.loads(crudo)
        except (ValueError, TypeError):
            # A veces el JSON viene envuelto en prosa o en un bloque de código.
            encontrado = re.search(r"\{.*\}", crudo, re.DOTALL)
            if encontrado:
                try:
                    datos = json.loads(encontrado.group(0))
                except (ValueError, TypeError):
                    datos = None

        if not isinstance(datos, dict):
            logger.warning("Clasificación no parseable", extra={"respuesta": crudo[:200]})
            return None

        categoria = str(datos.get("categoria", "")).strip().lower()
        if categoria not in CATEGORIAS_VALIDAS:
            logger.warning(
                "El modelo devolvió una categoría fuera de la lista",
                extra={"categoria": categoria},
            )
            return None

        try:
            confianza = float(datos.get("confianza"))
        except (TypeError, ValueError):
            return None

        # Una confianza fuera de rango es señal de que el modelo se inventó el
        # formato: no se confía en ella.
        if not 0.0 <= confianza <= 1.0:
            logger.warning("Confianza fuera de rango", extra={"confianza": confianza})
            return None

        return {"categoria": categoria, "confianza": confianza}


ollama = OllamaClient()

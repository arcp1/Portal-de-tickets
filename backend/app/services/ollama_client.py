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
import time
from collections import deque
from typing import List, Optional

import httpx

from app.core.config import settings
from app.core.logging import logger

# Las mismas seis del dropdown. El modelo clasifica dentro de esta lista o no
# clasifica: nunca inventa una categoría nueva.
CATEGORIAS_VALIDAS = ("impresora", "red", "equipo", "software", "accesos", "otro")

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
    ),
    "equipo": (
        "laptop", "computadora", "compu", "pc", "monitor", "pantalla", "teclado",
        "mouse", "raton", "ratón", "cpu", "disco duro", "bateria", "batería",
        "cargador", "docking", "escaner", "escáner", "scanner", "no enciende",
        "se apaga", "pantalla azul", "handheld", "terminal portatil",
        "terminal portátil", "lectora",
    ),
    "software": (
        "sap", "erp", "excel", "office", "outlook", "word", "programa",
        "aplicacion", "aplicación", "sistema", "licencia", "actualizacion",
        "actualización", "windows", "navegador", "chrome", "edge", "mes",
        "scada", "error de sistema",
    ),
    "accesos": (
        "contraseña", "contrasena", "password", "usuario bloqueado", "cuenta",
        "acceso", "accesos", "permiso", "permisos", "correo", "email",
        "no me deja entrar", "bloqueado", "bloqueada", "credenciales",
        "vpn acceso", "carpeta compartida", "unidad de red",
    ),
}

PROMPT_CLASIFICACION = (
    "Eres un clasificador de incidencias de soporte técnico de una planta industrial.\n"
    "Clasifica el mensaje del usuario en EXACTAMENTE una de estas categorías:\n"
    "- impresora: impresoras, etiquetadoras, tóner, ribbon, atascos de papel\n"
    "- red: wifi, cable de red, sin internet, lentitud de red, VPN\n"
    "- equipo: laptop, PC, monitor, teclado, hardware que falla\n"
    "- software: sistema ERP, aplicaciones, errores de programa, licencias\n"
    "- accesos: contraseñas, cuentas, permisos, correo, bloqueos de sesión\n"
    "- otro: cualquier cosa que no encaje claramente en las anteriores\n\n"
    "Responde SOLO con un objeto JSON, sin texto alrededor:\n"
    '{"categoria": "<una de la lista>", "confianza": <número entre 0 y 1>}\n\n'
    "La confianza debe reflejar qué tan seguro estás. Si el mensaje es vago, "
    "ambiguo o no describe un problema concreto, usa una confianza baja (menor a 0.5). "
    "No inventes información que el usuario no dio."
)

PROMPT_NORMALIZACION = (
    "Eres un asistente de soporte técnico. Reescribe el reporte del usuario "
    "en una descripción clara para un técnico de TI.\n"
    "Reglas estrictas:\n"
    "- Máximo 2-3 oraciones.\n"
    "- NO inventes información que el usuario no dio.\n"
    "- Si algo no está claro, dilo explícitamente en lugar de suponerlo.\n"
    "- Conserva datos concretos: número de equipo, área, mensajes de error.\n"
    "- Tono neutro y técnico.\n"
    "- Responde en el mismo idioma en que escribió el usuario.\n"
    "Devuelve solo la descripción reescrita, sin introducción ni comentarios."
)


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
    def disponible(self) -> bool:
        """True si Ollama contesta. Nunca levanta excepción."""
        if not settings.IA_HABILITADA:
            return False
        try:
            with httpx.Client(timeout=2.0) as cliente:
                respuesta = cliente.get(self.host + "/api/tags")
                return respuesta.status_code == 200
        except Exception as exc:  # noqa: BLE001 - degradación deliberada
            logger.warning(
                "Ollama no disponible",
                extra={"host": self.host, "error": str(exc)},
            )
            return False

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
        """
        if not settings.IA_HABILITADA:
            return None
        if not texto or not texto.strip():
            return None

        if "nomic" in settings.OLLAMA_MODELO_EMBEDDING.lower():
            prefijo = "search_query: " if tarea == "consulta" else "search_document: "
            texto = prefijo + texto

        inicio = time.monotonic()
        try:
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
            with httpx.Client(timeout=settings.OLLAMA_TIMEOUT_NORMALIZACION) as cliente:
                respuesta = cliente.post(
                    self.host + "/api/generate",
                    json={
                        "model": settings.OLLAMA_MODELO_TEXTO,
                        "system": PROMPT_NORMALIZACION,
                        "prompt": texto,
                        "stream": False,
                        "keep_alive": settings.OLLAMA_KEEP_ALIVE,
                        "options": {"num_predict": 300, "temperature": 0.2},
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
            with httpx.Client(timeout=settings.OLLAMA_TIMEOUT_CLASIFICACION) as cliente:
                respuesta = cliente.post(
                    self.host + "/api/generate",
                    json={
                        "model": settings.OLLAMA_MODELO_TEXTO,
                        "system": PROMPT_CLASIFICACION,
                        "prompt": texto,
                        "stream": False,
                        "keep_alive": settings.OLLAMA_KEEP_ALIVE,
                        "format": "json",
                        "options": {"num_predict": 120, "temperature": 0.0},
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
            with httpx.Client(timeout=timeout or settings.OLLAMA_TIMEOUT_ASISTENCIA) as cliente:
                respuesta = cliente.post(
                    self.host + "/api/generate",
                    json={
                        "model": settings.OLLAMA_MODELO_TEXTO,
                        "prompt": instruccion,
                        "stream": False,
                        "keep_alive": settings.OLLAMA_KEEP_ALIVE,
                        "options": {"num_predict": num_predict, "temperature": 0.1},
                    },
                )
                respuesta.raise_for_status()
                texto = (respuesta.json().get("response") or "").strip()
            self._registrar("asistencia", inicio)
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
            with httpx.Client(timeout=timeout or settings.OLLAMA_TIMEOUT_ASISTENCIA) as cliente:
                respuesta = cliente.post(
                    self.host + "/api/generate",
                    json={
                        "model": settings.OLLAMA_MODELO_TEXTO,
                        "prompt": instruccion,
                        "stream": False,
                        "format": "json",
                        "keep_alive": settings.OLLAMA_KEEP_ALIVE,
                        "options": {"num_predict": num_predict, "temperature": 0.0},
                    },
                )
                respuesta.raise_for_status()
                crudo = (respuesta.json().get("response") or "").strip()
            self._registrar("asistencia", inicio)
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

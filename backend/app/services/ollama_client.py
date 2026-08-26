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
from typing import List, Optional

import httpx

from app.core.config import settings
from app.core.logging import logger

# Las mismas seis del dropdown. El modelo clasifica dentro de esta lista o no
# clasifica: nunca inventa una categoría nueva.
CATEGORIAS_VALIDAS = ("impresora", "red", "equipo", "software", "accesos", "otro")

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

    def __init__(self, host: Optional[str] = None):
        self.host = (host or settings.OLLAMA_HOST).rstrip("/")

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
    def generar_embedding(self, texto: str) -> Optional[List[float]]:
        """Devuelve el vector del texto, o None si algo falla.

        None significa "sigue sin búsqueda por similitud", no "error".
        """
        if not settings.IA_HABILITADA:
            return None
        if not texto or not texto.strip():
            return None

        try:
            with httpx.Client(timeout=settings.OLLAMA_TIMEOUT_EMBEDDING) as cliente:
                respuesta = cliente.post(
                    self.host + "/api/embeddings",
                    json={
                        "model": settings.OLLAMA_MODELO_EMBEDDING,
                        "prompt": texto,
                    },
                )
                respuesta.raise_for_status()
                vector = respuesta.json().get("embedding")

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

        try:
            with httpx.Client(timeout=settings.OLLAMA_TIMEOUT_NORMALIZACION) as cliente:
                respuesta = cliente.post(
                    self.host + "/api/generate",
                    json={
                        "model": settings.OLLAMA_MODELO_TEXTO,
                        "system": PROMPT_NORMALIZACION,
                        "prompt": texto,
                        "stream": False,
                        "options": {"num_predict": 300, "temperature": 0.2},
                    },
                )
                respuesta.raise_for_status()
                normalizada = (respuesta.json().get("response") or "").strip()

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

        try:
            with httpx.Client(timeout=settings.OLLAMA_TIMEOUT_CLASIFICACION) as cliente:
                respuesta = cliente.post(
                    self.host + "/api/generate",
                    json={
                        "model": settings.OLLAMA_MODELO_TEXTO,
                        "system": PROMPT_CLASIFICACION,
                        "prompt": texto,
                        "stream": False,
                        "format": "json",
                        "options": {"num_predict": 120, "temperature": 0.0},
                    },
                )
                respuesta.raise_for_status()
                crudo = (respuesta.json().get("response") or "").strip()

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

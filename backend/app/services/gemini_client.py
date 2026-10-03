"""Cliente de Gemini, para lo que un modelo chico local no alcanza.

**Reparto de trabajo entre los dos modelos.** Ollama corre en el servidor de la
planta, es gratis y no manda nada a internet: se queda con todo lo que ocurre en
el camino de un ticket —clasificar, normalizar, generar embeddings—. Gemini
entra solo donde hace falta redactar de verdad sobre varios documentos a la vez:
responderle a alguien apoyándose en tickets ya resueltos, resumir un mes de
incidencias para dirección.

Ese reparto no es capricho de arquitectura, es de costo y de privacidad:

  - **Costo.** Lo que se paga por token solo se gasta en las pocas consultas que
    lo justifican, no en las cientos de clasificaciones diarias.
  - **Privacidad.** Lo que sale de la planta es una pregunta y unos extractos de
    tickets, no el padrón de personal ni los resguardos.

**El contrato de degradación es el mismo que el de Ollama y no se negocia:**
ninguna función de aquí levanta excepción. Si no hay llave, si Google no
contesta, si se agotó la cuota o si tardó demasiado, se devuelve ``None`` y quien
llama sigue su camino sin el modelo. Un ticket jamás se queda sin crearse porque
un servicio de terceros tuvo un mal día.
"""

import time
from collections import deque
from typing import List, Optional

import httpx

from app.core.config import settings
from app.core.logging import logger

# La API pública de Gemini. Se arma la URL por modelo.
BASE = "https://generativelanguage.googleapis.com/v1beta/models"

PROMPT_RESPUESTA = """Eres el asistente de soporte técnico de una planta industrial en Querétaro.

Respondes en español de México, con el tono de un compañero de TI que explica algo
en el pasillo: directo, sin rodeos y sin tecnicismos innecesarios.

Te van a dar la pregunta de una persona y extractos de tickets que ya se
resolvieron antes. Reglas, en orden de importancia:

1. Responde SOLO con lo que digan los extractos. Si no alcanzan para responder,
   dilo claramente y sugiere levantar un ticket. Inventar un procedimiento en una
   planta puede terminar en una línea parada.
2. Si la solución implica abrir un equipo, tocar instalación eléctrica o algo que
   pueda lastimar a alguien, no la expliques: di que lo vea TI en persona.
3. Sé breve. Tres o cuatro pasos numerados, no un ensayo.
4. Nunca pidas contraseñas ni datos personales."""


class GeminiClient:
    """Envoltura sobre la API de Gemini con degradación silenciosa."""

    MUESTRAS_LATENCIA = 50

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = (api_key if api_key is not None else settings.GEMINI_API_KEY) or ""
        self.modelo = settings.GEMINI_MODELO
        self._latencias = deque(maxlen=self.MUESTRAS_LATENCIA)
        # Cuando Google responde 429, no tiene caso seguir tocando la puerta en
        # cada petición: se espera a que pase el minuto.
        self._silencio_hasta = 0.0

    # ------------------------------------------------------------------
    # Estado
    # ------------------------------------------------------------------
    @property
    def configurado(self) -> bool:
        """Si hay llave. Sin llave, el portal funciona igual, solo sin Gemini."""
        return bool(self.api_key) and settings.GEMINI_HABILITADO

    def _cabeceras(self) -> dict:
        """La llave va en cabecera, **nunca en la URL**.

        Google acepta las dos formas, pero `?key=...` es una trampa: la URL
        aparece en el mensaje de cualquier excepción de httpx, en las trazas,
        en la salida capturada de las pruebas y en los registros de cualquier
        proxy por el que pase. Se comprobó de la peor manera —una prueba que
        se escapó a la red dejó la llave en claro en su log— y ese log podría
        haber acabado en un CI o en un pegado.

        En cabecera no viaja en el identificador del recurso, así que ni httpx
        ni un proxy la registran al anotar la petición.
        """
        return {"x-goog-api-key": self.api_key}

    def disponible(self) -> bool:
        """Si Gemini contesta ahora mismo. Nunca levanta excepción."""
        if not self.configurado:
            return False
        try:
            with httpx.Client(timeout=5) as cliente:
                respuesta = cliente.get(BASE, headers=self._cabeceras())
                return respuesta.status_code == 200
        except Exception:  # noqa: BLE001 - degradación deliberada
            return False

    def diagnostico(self) -> dict:
        """Qué decirle a TI en la pantalla de estado, sin filtrar la llave."""
        estado = {
            "habilitado": settings.GEMINI_HABILITADO,
            "configurado": self.configurado,
            "modelo": self.modelo,
            "llave": self._llave_ofuscada(),
            "latencia_ms": (round(sum(self._latencias) / len(self._latencias), 1)
                            if self._latencias else None),
            "en_espera": time.monotonic() < self._silencio_hasta,
        }
        estado["alcanzable"] = self.disponible() if self.configurado else False
        return estado

    def _llave_ofuscada(self) -> Optional[str]:
        """Los últimos cuatro caracteres, para saber cuál llave está puesta.

        Suficiente para distinguir entre dos llaves; inútil para usarla.
        """
        if not self.api_key:
            return None
        return "…" + self.api_key[-4:]

    # ------------------------------------------------------------------
    # Generación
    # ------------------------------------------------------------------
    def responder_con_contexto(
        self,
        pregunta: str,
        extractos: List[str],
        idioma: str = "es",
    ) -> Optional[dict]:
        """Redacta una respuesta apoyada en tickets ya resueltos.

        Devuelve ``{"respuesta": str, "tokens": int}`` o **None** si no se pudo.
        None significa "enséñale los extractos tal cual", nunca un error en
        pantalla.
        """
        if not self.configurado or not pregunta or not extractos:
            return None
        if time.monotonic() < self._silencio_hasta:
            return None

        contexto = "\n\n---\n\n".join(extractos[:settings.GEMINI_MAX_EXTRACTOS])
        instruccion = (
            f"{PROMPT_RESPUESTA}\n\n"
            f"Responde en el idioma con código '{idioma}'.\n\n"
            f"TICKETS RESUELTOS:\n{contexto}\n\n"
            f"PREGUNTA: {pregunta}"
        )
        return self._generar(instruccion, settings.GEMINI_MAX_TOKENS_RESPUESTA)

    def redactar(self, instruccion: str) -> Optional[dict]:
        """Redacta sobre una instrucción ya armada por quien llama.

        La usa el asistente, que arma su propio prompt con los pasajes que
        recuperó de la planta y sus reglas de citación. Aquí solo se manda.
        """
        if not self.configurado or not instruccion:
            return None
        if time.monotonic() < self._silencio_hasta:
            return None
        return self._generar(instruccion, settings.GEMINI_MAX_TOKENS_RESPUESTA)

    def resumir_periodo(self, datos: str) -> Optional[dict]:
        """Resume un periodo de incidencias para el reporte de dirección."""
        if not self.configurado or not datos:
            return None
        instruccion = (
            "Eres analista de operaciones de TI en una planta industrial. Con los "
            "datos de abajo, escribe un resumen ejecutivo en español de México, de "
            "máximo 200 palabras, para la dirección de la planta.\n\n"
            "Di qué pasó, qué se repite y qué conviene atender. Sin adornos, sin "
            "recomendaciones genéricas y sin inventar cifras que no estén en los "
            "datos.\n\n"
            f"DATOS:\n{datos}"
        )
        return self._generar(instruccion, settings.GEMINI_MAX_TOKENS_RESUMEN)

    # ------------------------------------------------------------------
    # Interno
    # ------------------------------------------------------------------
    def _generar(self, instruccion: str, max_tokens: int) -> Optional[dict]:
        inicio = time.monotonic()
        try:
            with httpx.Client(timeout=settings.GEMINI_TIMEOUT) as cliente:
                respuesta = cliente.post(
                    f"{BASE}/{self.modelo}:generateContent",
                    headers=self._cabeceras(),
                    json={
                        "contents": [{"parts": [{"text": instruccion}]}],
                        "generationConfig": {
                            "temperature": 0.2,
                            "maxOutputTokens": max_tokens,
                        },
                    },
                )

            # 429 = cuota agotada. Se deja de insistir un rato en vez de gastar
            # el timeout completo en cada petición que llegue.
            if respuesta.status_code == 429:
                self._silencio_hasta = time.monotonic() + settings.GEMINI_ESPERA_CUOTA
                logger.warning("Gemini: cuota agotada; se sigue sin él",
                               extra={"espera_s": settings.GEMINI_ESPERA_CUOTA})
                return None

            respuesta.raise_for_status()
            datos = respuesta.json()

            candidato = datos.get("candidates", [{}])[0]
            texto = (candidato.get("content", {})
                     .get("parts", [{}])[0]
                     .get("text", "") or "").strip()
            if not texto:
                return None

            # **El mismo cuidado que con el modelo local.**
            #
            # Al agotar `maxOutputTokens`, Google contesta 200 con el trozo que
            # llevaba escrito y lo marca en `finishReason`. Sin mirarlo, medio
            # procedimiento llega al usuario con aspecto de estar entero —y el
            # final, que es donde suelen ir las advertencias, no llega—.
            #
            # Aquí importa más que en el local: Gemini es el que se llama
            # *porque* el local no alcanzó, así que su respuesta es la que se
            # va a publicar. Devolver None deja seguir a los extractos, que
            # serán menos cómodos de leer pero están completos.
            if candidato.get("finishReason") == "MAX_TOKENS":
                logger.warning("Gemini: la respuesta salió cortada por el tope; "
                               "se sigue sin ella",
                               extra={"max_tokens": max_tokens})
                return None

            self._latencias.append((time.monotonic() - inicio) * 1000.0)
            uso = datos.get("usageMetadata", {}) or {}
            return {
                "respuesta": texto,
                "tokens_entrada": uso.get("promptTokenCount", 0),
                "tokens_salida": uso.get("candidatesTokenCount", 0),
                "modelo": self.modelo,
            }

        except httpx.TimeoutException:
            logger.warning("Gemini: se agotó el tiempo; se sigue sin él",
                           extra={"timeout": settings.GEMINI_TIMEOUT})
            return None
        except Exception as exc:  # noqa: BLE001 - degradación deliberada
            logger.error("Gemini: fallo la consulta; se sigue sin él",
                         extra={"error": str(exc), "modelo": self.modelo})
            return None


gemini = GeminiClient()

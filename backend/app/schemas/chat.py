from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class ChatMensajeRequest(BaseModel):
    # Sin espacios en los extremos: un mensaje de puros espacios pasaba el
    # mínimo y ocupaba la IA —aforo 1— para contestar a nada.
    model_config = ConfigDict(str_strip_whitespace=True)

    # **El tope no es cosmético: sin él, un mensaje largo bloquea la IA de toda
    # la planta.**
    #
    # El mensaje va al modelo dos veces —a buscar en el conocimiento y a
    # clasificar— y la generación tiene aforo 1, así que mientras dura, nadie
    # más tiene asistente. Medido en esta planta: 20 000 caracteres llenan la
    # ventana de contexto de Ollama (4096 tokens) y cuestan **150 segundos**.
    # Dos minutos y medio de IA parada, con un pegado.
    #
    # Además, pasada esa ventana Ollama **recorta en silencio**: el texto de más
    # ni siquiera se lee, así que no compra nada.
    #
    # 2000 es el mismo tope que `/asistente/preguntar` ya tenía; aquí faltaba.
    # Da para describir una avería con holgura: esto es un chat de una línea,
    # no un informe.
    mensaje: str = Field(min_length=1, max_length=2000)
    # Sin sesión se abre una nueva. El contexto no cruza entre incidencias.
    sesion_id: Optional[int] = None
    # "Ninguna de esas fotos es la mía."
    #
    # El reconocimiento visual va **antes** que todo lo demás, así que sin esta
    # bandera el mismo mensaje volvería a traer las mismas tres fotos y la
    # conversación no avanzaría nunca. La manda el frontend cuando la persona
    # ya dijo que no, y sólo apaga esa parte: el resto del flujo —buscar en el
    # conocimiento, clasificar, escalar— sigue igual.
    omitir_visual: bool = False


class ChatEscalarRequest(BaseModel):
    sesion_id: Optional[int] = None


class ChatMensajeResponse(BaseModel):
    sesion_id: Optional[int] = None
    respuesta: Optional[str] = None
    categoria: Optional[str] = None
    confianza: Optional[float] = None
    accion: str = Field(
        description=(
            "reconocer_imagen = parece un problema que se ve; se enseñan fotos y se pregunta cuál es | "
            "solucion = se encontró en el conocimiento de la planta y se responde ahí mismo | "
            "flujo_categoria = clasificado, entra al flujo de esa categoría | "
            "pedir_categoria = sin confianza, se muestran los dropdowns | "
            "crear_ticket = se agotaron los intercambios o lo pidió el usuario | "
            "no_disponible = Ollama caído, el widget se oculta"
        )
    )
    # De dónde salió la solución, para poder abrirla y comprobar.
    fuentes: List[dict] = []
    # Las fichas del catálogo visual que se le enseñan para que elija la suya.
    # Vacío en todas las demás acciones.
    fichas: List[dict] = []
    intercambios: int = 0
    # Todo lo que el usuario escribió en esta sesión, para prellenar el formulario.
    descripcion_sugerida: str = ""
    categorias: List[str] = []


class ChatEstadoResponse(BaseModel):
    # False = el widget no se dibuja. Degradación limpia.
    disponible: bool
    max_intercambios: int

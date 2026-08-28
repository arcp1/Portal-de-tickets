from typing import List, Optional

from pydantic import BaseModel, Field


class ChatMensajeRequest(BaseModel):
    mensaje: str
    # Sin sesión se abre una nueva. El contexto no cruza entre incidencias.
    sesion_id: Optional[int] = None


class ChatEscalarRequest(BaseModel):
    sesion_id: Optional[int] = None


class ChatMensajeResponse(BaseModel):
    sesion_id: Optional[int] = None
    respuesta: Optional[str] = None
    categoria: Optional[str] = None
    confianza: Optional[float] = None
    accion: str = Field(
        description=(
            "solucion = se encontró en el conocimiento de la planta y se responde ahí mismo | "
            "flujo_categoria = clasificado, entra al flujo de esa categoría | "
            "pedir_categoria = sin confianza, se muestran los dropdowns | "
            "crear_ticket = se agotaron los intercambios o lo pidió el usuario | "
            "no_disponible = Ollama caído, el widget se oculta"
        )
    )
    # De dónde salió la solución, para poder abrirla y comprobar.
    fuentes: List[dict] = []
    intercambios: int = 0
    # Todo lo que el usuario escribió en esta sesión, para prellenar el formulario.
    descripcion_sugerida: str = ""
    categorias: List[str] = []


class ChatEstadoResponse(BaseModel):
    # False = el widget no se dibuja. Degradación limpia.
    disponible: bool
    max_intercambios: int

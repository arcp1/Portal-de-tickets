from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import Optional, List
from app.schemas.auth import UserResponse
from app.schemas.comunes import FechaUTC, PlantaBreve
from app.services.ollama_client import CATEGORIAS_VALIDAS

#: Tope de los textos largos que escribe una persona: descripción, comentario,
#: solución. Una pantalla y media de texto. Sin tope entraban 200 000
#: caracteres pegados por error y se mandaban enteros a la IA y a cada
#: pantalla que pinta el ticket.
TEXTO_LARGO = 5000


class TicketCreate(BaseModel):
    # Lo que se escribe se guarda sin los espacios de los extremos, y los
    # mínimos se miden ya sin ellos: un ticket de cinco mil espacios entraba.
    model_config = ConfigDict(str_strip_whitespace=True)

    # Una de las plantas de quien lo levanta; sin ella, su principal.
    sitio_id: Optional[int] = None
    equipo_id: Optional[int] = None
    categoria: str
    subcategoria: Optional[str] = Field(default=None, max_length=50)
    # Mínimo 3, no más: un autoservicio sin descripción manda el nombre de la
    # categoría, y "Otro" tiene cuatro letras.
    descripcion_original: str = Field(min_length=3, max_length=TEXTO_LARGO)
    prioridad: str = "media"
    # Auto-resolución: el usuario resolvió solo con el checklist o con una
    # sugerencia de la base de conocimiento. Se registra como ticket ya resuelto
    # para que la tasa de deflección sea medible; sin esto una incidencia
    # resuelta sin TI no deja rastro en ningún lado.
    # Solo acepta canales de autoservicio: "checklist" o "kb".
    canal_auto_resolucion: Optional[str] = None
    solucion: Optional[str] = Field(default=None, max_length=TEXTO_LARGO)
    descartado: Optional[str] = Field(default=None, max_length=TEXTO_LARGO)
    # Sesión del chatbot que originó el ticket. Enlazarla es lo que permite
    # medir la precisión del clasificador: categoría detectada vs. la final.
    chat_sesion_id: Optional[int] = None

    @field_validator("categoria")
    @classmethod
    def _categoria_conocida(cls, valor: str) -> str:
        # Una categoría inventada no sale en ningún filtro, no tiene pasos de
        # diagnóstico ni traducción, y descuadra las métricas por categoría.
        if valor not in CATEGORIAS_VALIDAS:
            raise ValueError("no es una categoría conocida")
        return valor

class TicketUpdate(BaseModel):
    estado: Optional[str] = None
    prioridad: Optional[str] = None
    asignado_a: Optional[int] = None
    canal_resolucion: Optional[str] = None
    descripcion_normalizada: Optional[str] = Field(default=None, max_length=TEXTO_LARGO)
    # Obligatoria al pasar el ticket a resuelto o cerrado.
    solucion: Optional[str] = Field(default=None, max_length=TEXTO_LARGO)
    descartado: Optional[str] = Field(default=None, max_length=TEXTO_LARGO)

class CommentCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    # Un comentario vacío o de puros espacios entraba, avisaba por correo a
    # quien reportó y dejaba una burbuja en blanco en el hilo.
    comentario: str = Field(min_length=1, max_length=TEXTO_LARGO)
    es_interno: bool = False

class CommentResponse(BaseModel):
    id: int
    ticket_id: int
    autor_id: int
    autor: UserResponse
    comentario: str
    es_interno: bool
    creado_en: FechaUTC

    model_config = ConfigDict(from_attributes=True)

class AdjuntoResponse(BaseModel):
    id: int
    ticket_id: int
    nombre_original: str
    tipo_mime: str
    tamano_bytes: int
    creado_en: FechaUTC

    model_config = ConfigDict(from_attributes=True)

class TicketResponse(BaseModel):
    id: int
    sitio_id: int
    # Para la etiqueta de planta del tablero de TI, que ve todas.
    sitio: Optional[PlantaBreve] = None
    folio: str
    usuario_id: int
    usuario: UserResponse
    equipo_id: Optional[int] = None
    categoria: str
    subcategoria: Optional[str] = None
    descripcion_original: str
    descripcion_normalizada: Optional[str] = None
    prioridad: str
    estado: str
    asignado_a: Optional[int] = None
    asignado_usuario: Optional[UserResponse] = None
    canal_resolucion: Optional[str] = None
    solucion: Optional[str] = None
    descartado: Optional[str] = None
    indexado_kb: bool = False
    creado_en: FechaUTC
    resuelto_en: Optional[FechaUTC] = None
    tiempo_resolucion: Optional[int] = None
    # SLA: cuándo vence contando solo horas hábiles.
    vence_en: Optional[FechaUTC] = None
    # Solo si lo retiró quien lo reportó. Ver `Ticket.cancelado_en`.
    cancelado_en: Optional[FechaUTC] = None
    fuera_horario: bool = False
    # La encuesta de quien reportó, de 1 a 5. Vacía mientras no conteste.
    satisfaccion: Optional[int] = None
    satisfaccion_comentario: Optional[str] = None
    satisfaccion_en: Optional[FechaUTC] = None
    comentarios: List[CommentResponse] = []
    adjuntos: List[AdjuntoResponse] = []

    model_config = ConfigDict(from_attributes=True)


class TicketPagina(BaseModel):
    """Una página del listado, con lo necesario para pintar los controles.

    `total` y `paginas` cuentan lo que coincide con los filtros, no todos los
    tickets: son los que dicen "página 2 de 5" del filtro que se está mirando.
    """
    items: List[TicketResponse]
    total: int
    pagina: int
    por_pagina: int
    paginas: int


class SatisfaccionCreate(BaseModel):
    """La encuesta al quedar resuelto: estrellas y, si quiere, por qué."""
    model_config = ConfigDict(str_strip_whitespace=True)

    estrellas: int = Field(ge=1, le=5)
    comentario: Optional[str] = Field(default=None, max_length=1000)

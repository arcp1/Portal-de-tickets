from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
from app.schemas.auth import UserResponse
from app.schemas.comunes import FechaUTC

class TicketCreate(BaseModel):
    sitio_id: int
    equipo_id: Optional[int] = None
    categoria: str
    subcategoria: Optional[str] = None
    descripcion_original: str
    prioridad: str = "media"
    # Auto-resolución: el usuario resolvió solo con el checklist o con una
    # sugerencia de la base de conocimiento. Se registra como ticket ya resuelto
    # para que la tasa de deflección sea medible; sin esto una incidencia
    # resuelta sin TI no deja rastro en ningún lado.
    # Solo acepta canales de autoservicio: "checklist" o "kb".
    canal_auto_resolucion: Optional[str] = None
    solucion: Optional[str] = None
    # Sesión del chatbot que originó el ticket. Enlazarla es lo que permite
    # medir la precisión del clasificador: categoría detectada vs. la final.
    chat_sesion_id: Optional[int] = None

class TicketUpdate(BaseModel):
    estado: Optional[str] = None
    prioridad: Optional[str] = None
    asignado_a: Optional[int] = None
    canal_resolucion: Optional[str] = None
    descripcion_normalizada: Optional[str] = None
    # Obligatoria al pasar el ticket a resuelto o cerrado.
    solucion: Optional[str] = None

class CommentCreate(BaseModel):
    comentario: str
    es_interno: bool = False

class CommentResponse(BaseModel):
    id: int
    ticket_id: int
    autor_id: int
    autor: UserResponse
    comentario: str
    es_interno: bool
    creado_en: FechaUTC

    class Config:
        from_attributes = True

class AdjuntoResponse(BaseModel):
    id: int
    ticket_id: int
    nombre_original: str
    tipo_mime: str
    tamano_bytes: int
    creado_en: FechaUTC

    class Config:
        from_attributes = True

class TicketResponse(BaseModel):
    id: int
    sitio_id: int
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
    indexado_kb: bool = False
    creado_en: FechaUTC
    resuelto_en: Optional[FechaUTC] = None
    tiempo_resolucion: Optional[int] = None
    # SLA: cuándo vence contando solo horas hábiles.
    vence_en: Optional[FechaUTC] = None
    fuera_horario: bool = False
    comentarios: List[CommentResponse] = []
    adjuntos: List[AdjuntoResponse] = []

    class Config:
        from_attributes = True

from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
from app.schemas.auth import UserResponse

class TicketCreate(BaseModel):
    sitio_id: int
    equipo_id: Optional[int] = None
    categoria: str
    subcategoria: Optional[str] = None
    descripcion_original: str
    prioridad: str = "media"

class TicketUpdate(BaseModel):
    estado: Optional[str] = None
    prioridad: Optional[str] = None
    asignado_a: Optional[int] = None
    canal_resolucion: Optional[str] = None
    descripcion_normalizada: Optional[str] = None

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
    creado_en: datetime

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
    creado_en: datetime
    resuelto_en: Optional[datetime] = None
    tiempo_resolucion: Optional[int] = None
    comentarios: List[CommentResponse] = []

    class Config:
        from_attributes = True

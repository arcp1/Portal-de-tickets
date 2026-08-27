from typing import List, Optional

from pydantic import BaseModel, Field


# --- Pasos de checklist ---

class PasoCreate(BaseModel):
    categoria: str
    pregunta_texto: str = Field(min_length=5)
    accion_si_no: Optional[str] = None
    resuelve: bool = False
    orden: Optional[int] = None


class PasoUpdate(BaseModel):
    categoria: Optional[str] = None
    pregunta_texto: Optional[str] = None
    accion_si_no: Optional[str] = None
    resuelve: Optional[bool] = None
    orden: Optional[int] = None
    activo: Optional[bool] = None


class PasoResponse(BaseModel):
    id: int
    categoria: str
    orden: int
    pregunta_key: str
    pregunta_texto: Optional[str] = None
    accion_si_no: Optional[str] = None
    resuelve: bool
    activo: bool
    veces_resolvio: int

    class Config:
        from_attributes = True


# --- Temas recurrentes detectados ---

class SolucionPrevia(BaseModel):
    ticket_id: int
    folio: str
    similitud: float
    solucion: str


class TemaSugeridoResponse(BaseModel):
    id: int
    titulo: str
    descripcion_ejemplo: str
    categoria_sugerida: Optional[str] = None
    ocurrencias: int
    estado: str
    primera_vez: Optional[str] = None
    ultima_vez: Optional[str] = None
    soluciones_previas: List[SolucionPrevia] = []

    class Config:
        from_attributes = True


class PromoverTemaRequest(BaseModel):
    categoria: str
    pasos: List[PasoCreate] = []


# --- Entradas de la base de conocimiento ---

class EntradaKBCreate(BaseModel):
    titulo: str = Field(min_length=5, max_length=150)
    contenido: str = Field(min_length=20)
    categoria: str
    tags: Optional[str] = None


class EntradaKBUpdate(BaseModel):
    titulo: Optional[str] = None
    contenido: Optional[str] = None
    categoria: Optional[str] = None
    tags: Optional[str] = None


class EntradaKBResponse(BaseModel):
    id: int
    titulo: str
    contenido: str
    categoria: str
    tags: Optional[str] = None
    veces_sugerida: int
    veces_util: int
    ticket_origen_id: Optional[int] = None
    # None mientras no se haya mostrado nunca.
    tasa_utilidad: Optional[float] = None
    tiene_embedding: bool = False

    class Config:
        from_attributes = True

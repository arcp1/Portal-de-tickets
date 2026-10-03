from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


# --- Pasos de checklist ---

#: Lo que se escribe en estas pantallas se guarda sin los espacios de los
#: extremos, y los mínimos se miden ya sin ellos. Al editar se exigen los
#: mismos mínimos que al crear: la edición dejaba vaciar un título o un
#: contenido que el alta había exigido, y quedaba una fila sin nada que leer.
SIN_ESPACIOS = ConfigDict(str_strip_whitespace=True)


class PasoCreate(BaseModel):
    model_config = SIN_ESPACIOS

    categoria: str
    pregunta_texto: str = Field(min_length=5, max_length=1000)
    accion_si_no: Optional[str] = Field(default=None, max_length=5000)
    resuelve: bool = False
    orden: Optional[int] = None


class PasoUpdate(BaseModel):
    model_config = SIN_ESPACIOS

    categoria: Optional[str] = None
    pregunta_texto: Optional[str] = Field(default=None, min_length=5, max_length=1000)
    accion_si_no: Optional[str] = Field(default=None, max_length=5000)
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

    model_config = ConfigDict(from_attributes=True)


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

    model_config = ConfigDict(from_attributes=True)


class PromoverTemaRequest(BaseModel):
    categoria: str
    pasos: List[PasoCreate] = []


# --- Entradas de la base de conocimiento ---

class EntradaKBCreate(BaseModel):
    model_config = SIN_ESPACIOS

    titulo: str = Field(min_length=5, max_length=150)
    contenido: str = Field(min_length=20, max_length=20000)
    categoria: str
    tags: Optional[str] = Field(default=None, max_length=200)


class EntradaKBUpdate(BaseModel):
    model_config = SIN_ESPACIOS

    titulo: Optional[str] = Field(default=None, min_length=5, max_length=150)
    contenido: Optional[str] = Field(default=None, min_length=20, max_length=20000)
    categoria: Optional[str] = None
    tags: Optional[str] = Field(default=None, max_length=200)


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

    model_config = ConfigDict(from_attributes=True)

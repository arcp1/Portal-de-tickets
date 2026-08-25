from pydantic import BaseModel
from typing import Optional

class ChecklistCreate(BaseModel):
    categoria: str
    orden: int = 1
    pregunta_key: str
    accion_si_no: Optional[str] = None
    resuelve: bool = False

class ChecklistResponse(BaseModel):
    id: int
    categoria: str
    orden: int
    pregunta_key: str
    accion_si_no: Optional[str] = None
    resuelve: bool

    class Config:
        from_attributes = True

class ReglaCreate(BaseModel):
    sitio_id: int
    categoria: str
    condicion: str
    accion: str # proveedor, escalar, auto
    destinatario: Optional[str] = None
    activa: bool = True

class ReglaResponse(BaseModel):
    id: int
    sitio_id: int
    categoria: str
    condicion: str
    accion: str
    destinatario: Optional[str] = None
    activa: bool

    class Config:
        from_attributes = True

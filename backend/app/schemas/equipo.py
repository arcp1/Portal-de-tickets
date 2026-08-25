from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from app.schemas.auth import UserResponse

class EquipoCreate(BaseModel):
    sitio_id: int
    tipo: str # activo, pasivo, consumible
    categoria: str
    marca: str
    modelo: str
    numero_serie: Optional[str] = None
    ubicacion: Optional[str] = None
    estado: str = "disponible"
    asignado_a: Optional[int] = None
    notas: Optional[str] = None

class EquipoUpdate(BaseModel):
    tipo: Optional[str] = None
    categoria: Optional[str] = None
    marca: Optional[str] = None
    modelo: Optional[str] = None
    numero_serie: Optional[str] = None
    ubicacion: Optional[str] = None
    estado: Optional[str] = None
    asignado_a: Optional[int] = None
    notas: Optional[str] = None

class EquipoResponse(BaseModel):
    id: int
    sitio_id: int
    tipo: str
    categoria: str
    marca: str
    modelo: str
    numero_serie: Optional[str] = None
    ubicacion: Optional[str] = None
    estado: str
    asignado_a: Optional[int] = None
    asignado_usuario: Optional[UserResponse] = None
    fecha_asignacion: Optional[datetime] = None
    notas: Optional[str] = None

    class Config:
        from_attributes = True

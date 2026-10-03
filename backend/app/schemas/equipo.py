from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import Optional
from datetime import datetime
from app.schemas.auth import UserResponse
from app.schemas.comunes import PlantaBreve

# Los topes son los de cada columna. Sin ellos una marca de 60 letras llegaba a
# la base y salía como un 500, y una de puros espacios se guardaba en blanco y
# dejaba en el inventario una fila sin nada que leer.
CORTO = 50
MEDIO = 100
NOTAS = 2000


class EquipoCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    # Obligatoria para TI cuando hay varias plantas; con una sola, esa.
    sitio_id: Optional[int] = None
    tipo: str # activo, pasivo, consumible
    categoria: str = Field(min_length=1, max_length=CORTO)
    marca: str = Field(min_length=1, max_length=CORTO)
    modelo: str = Field(min_length=1, max_length=CORTO)
    numero_serie: Optional[str] = Field(default=None, max_length=MEDIO)
    ubicacion: Optional[str] = Field(default=None, max_length=MEDIO)
    estado: str = "disponible"
    asignado_a: Optional[int] = None
    notas: Optional[str] = Field(default=None, max_length=NOTAS)

class EquipoUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    # Para llevarlo a otra planta. Omitido, se queda donde está.
    sitio_id: Optional[int] = None
    tipo: Optional[str] = None
    categoria: Optional[str] = Field(default=None, min_length=1, max_length=CORTO)
    marca: Optional[str] = Field(default=None, min_length=1, max_length=CORTO)
    modelo: Optional[str] = Field(default=None, min_length=1, max_length=CORTO)
    numero_serie: Optional[str] = Field(default=None, max_length=MEDIO)
    ubicacion: Optional[str] = Field(default=None, max_length=MEDIO)
    estado: Optional[str] = None
    asignado_a: Optional[int] = None
    notas: Optional[str] = Field(default=None, max_length=NOTAS)

    @field_validator("tipo", "categoria", "marca", "modelo", "estado")
    @classmethod
    def _no_se_borra(cls, valor):
        # Omitirlo es no cambiarlo; mandarlo en null era vaciar una columna
        # obligatoria, y eso la base lo rechazaba con un error interno.
        if valor is None:
            raise ValueError("no puede quedar vacío")
        return valor

class EquipoResponse(BaseModel):
    id: int
    sitio_id: int
    sitio: Optional[PlantaBreve] = None
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

    model_config = ConfigDict(from_attributes=True)

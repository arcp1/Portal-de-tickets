from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.comunes import FechaUTC


class ImagenBreve(BaseModel):
    """Lo que la pantalla necesita para pintar una imagen del conocimiento.

    Viaja dentro de los pasos, las entradas de la base de conocimiento y el
    ticket, así que el listado ya sabe qué imágenes hay sin pedir una por una.
    El archivo se descarga aparte, por `GET /api/imagenes/{id}`.
    """
    id: int
    orden: int
    pie: Optional[str] = None
    nombre_original: str
    tipo_mime: str
    tamano_bytes: int
    creado_en: Optional[FechaUTC] = None

    model_config = ConfigDict(from_attributes=True)


class ImagenUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    pie: Optional[str] = Field(default=None, max_length=300)
    orden: Optional[int] = Field(default=None, ge=1, le=1000)


def breves(imagenes) -> list:
    """Las imágenes de un dueño, ya en la forma de la API.

    Para los listados que se arman a mano como diccionario —la base de
    conocimiento— y no pasan por `from_attributes`.
    """
    return [ImagenBreve.model_validate(i).model_dump() for i in (imagenes or [])]

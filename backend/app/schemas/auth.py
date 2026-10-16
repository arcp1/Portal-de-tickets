from app.schemas.comunes import FechaUTC, PlantaBreve
from pydantic import BaseModel, ConfigDict
from typing import List, Optional

class LoginRequest(BaseModel):
    # Se conserva el nombre "email" por compatibilidad con lo ya construido,
    # pero acepta número de empleado o correo: en planta mucha gente no tiene
    # correo corporativo. Por eso es str y no EmailStr.
    email: str
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: "SesionResponse"

class UserResponse(BaseModel):
    id: int
    # La planta principal; vacía para TI, que atiende a todas.
    sitio_id: Optional[int] = None
    # Lo pinta la barra de navegación. Ver `Usuario.sitio_nombre`.
    sitio_nombre: Optional[str] = None
    nombre: str
    numero_empleado: Optional[str] = None
    email: Optional[str] = None
    rol: str
    area: Optional[str] = None
    idioma_preferido: str = "es"
    activo: bool
    # "Nuevo ticket" no ofrece alta ni crítica a quien la tiene revocada.
    puede_usar_prioridad_alta: bool = True
    # Multi-planta: TI es global y no tiene plantas; una persona de planta
    # tiene una o varias, y solo ve y elige equipos y tickets de esas.
    es_ti_global: bool = False
    plantas: List[PlantaBreve] = []

    model_config = ConfigDict(from_attributes=True)


class SesionResponse(UserResponse):
    """La persona que tiene la sesión, con lo que solo le importa a ella.

    Va en el login, la activación, `/me`, el cambio de contraseña y la
    aceptación de los términos; no en `UserResponse`, que también sale anidado
    en tickets y comentarios ajenos, donde la fecha en que alguien aceptó los
    términos no tiene nada que hacer.
    """
    # Si aceptó la versión vigente de los Términos y Condiciones. Mientras sea
    # falso, la pantalla muestra la puerta de aceptación y la API responde 403.
    terminos_vigentes: bool = False
    terminos_version: Optional[str] = None
    terminos_aceptados_en: Optional[FechaUTC] = None
    # Si ya entró con su cuenta de Microsoft (migración 0032). Lo enseña el
    # menú de la cuenta.
    microsoft_vinculada: bool = False


# `TokenResponse` nombra a `SesionResponse` antes de que exista.
TokenResponse.model_rebuild()

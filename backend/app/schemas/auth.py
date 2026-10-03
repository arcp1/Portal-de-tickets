from app.schemas.comunes import PlantaBreve
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
    user: "UserResponse"

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


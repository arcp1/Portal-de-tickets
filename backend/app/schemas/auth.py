from pydantic import BaseModel, EmailStr
from typing import Optional

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
    sitio_id: int
    nombre: str
    numero_empleado: Optional[str] = None
    email: Optional[str] = None
    rol: str
    area: Optional[str] = None
    idioma_preferido: str = "es"
    activo: bool

    class Config:
        from_attributes = True


from pydantic import BaseModel, EmailStr
from typing import Optional

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: "UserResponse"

class UserResponse(BaseModel):
    id: int
    sitio_id: int
    nombre: str
    email: str
    rol: str
    area: Optional[str] = None
    idioma_preferido: str = "es"
    activo: bool

    class Config:
        from_attributes = True

class UserCreate(BaseModel):
    sitio_id: int
    nombre: str
    email: EmailStr
    password: str
    rol: str = "usuario"
    area: Optional[str] = None
    idioma_preferido: str = "es"

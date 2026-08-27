from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from app.core.db import get_db
from app.core.security import verify_password, create_access_token
from app.models import Usuario
from app.schemas.auth import LoginRequest, TokenResponse, UserResponse
from app.api.deps import get_current_user, get_current_admin
from app.core.limitador import limitador_login
from app.core.logging import logger
from app.services.auditoria_service import ip_de
from app.services.cuentas_service import CuentasService

router = APIRouter(prefix="/auth", tags=["Auth"])

@router.post("/login", response_model=TokenResponse)
def login(request: LoginRequest, peticion: Request, db: Session = Depends(get_db)):
    # Se limita por IP y por correo a la vez: por IP frena a quien prueba muchos
    # usuarios desde un equipo, y por correo frena a quien ataca una cuenta
    # concreta desde varios.
    origen = ip_de(peticion) or "desconocida"
    for clave in (f"ip:{origen}", f"correo:{request.email.lower()}"):
        if not limitador_login.permitido(clave):
            espera = limitador_login.segundos_restantes(clave)
            logger.warning("Demasiados intentos de inicio de sesión",
                           extra={"clave": clave, "espera_s": espera})
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Demasiados intentos. Espere {espera} segundos.",
                headers={"Retry-After": str(espera)},
            )

    # Acepta número de empleado o correo: la gente teclea lo que recuerda.
    user = CuentasService.buscar_por_identificador(db, request.email)
    if not user or not verify_password(request.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password"
        )
    if not user.activo:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La cuenta está desactivada. Contacte al área de TI."
        )
    if user.estado_cuenta != "activa":
        # Todavía no define su contraseña: se le dice qué hacer en vez de
        # dejarlo intentando con una que no existe.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Su cuenta aún no está activada. Use «Activar mi cuenta» con el código que le dio TI."
        )

    user.ultimo_acceso = datetime.utcnow()
    db.commit()

    # Quien entró bien no arrastra el conteo de intentos previos.
    limitador_login.limpiar(f"ip:{origen}")
    limitador_login.limpiar(f"correo:{request.email.lower()}")

    access_token = create_access_token(subject=user.id)
    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        user=user
    )

@router.post("/login/form", response_model=TokenResponse)
def login_form(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(Usuario).filter(Usuario.email == form_data.username).first()
    if not user or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password"
        )
    
    access_token = create_access_token(subject=user.id)
    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        user=user
    )

@router.get("/me", response_model=UserResponse)
def read_current_user(current_user: Usuario = Depends(get_current_user)):
    return current_user

@router.get("/usuarios", response_model=List[UserResponse])
def listar_usuarios(
    solo_activos: bool = True,
    db: Session = Depends(get_db),
    admin: Usuario = Depends(get_current_admin),
):
    """Personas del sitio del admin.

    Lo consume el formulario de emisión de resguardos y el expediente. Solo
    admin: la lista de empleados no es información que un usuario cualquiera
    necesite para usar el portal.
    """
    consulta = db.query(Usuario).filter(Usuario.sitio_id == admin.sitio_id)
    if solo_activos:
        consulta = consulta.filter(Usuario.activo.is_(True))
    return consulta.order_by(Usuario.nombre).all()

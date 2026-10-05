from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from app.core.db import get_db
from app.core.security import (
    HASH_SENUELO, HashOcupado, create_access_token, respuesta_ocupado, turno_de_hash,
    verify_password,
)
from app.models import Usuario
from app.schemas.auth import LoginRequest, SesionResponse, TokenResponse, UserResponse
from app.api.deps import get_current_user, get_current_admin, oauth2_scheme
from app.core import sesiones
from app.core.config import settings
import jwt
from app.core.limitador import (
    clave_de_cuenta, es_publico, frenar, freno_por_ip, limitador_login, limitador_login_ip,
)
from app.core.logging import logger
from app.services.cuentas_service import CuentasService

router = APIRouter(prefix="/auth", tags=["Auth"])

#: Ver `HASH_SENUELO` en core/security.py: vive alli porque la activacion
#: necesita el mismo.
_HASH_SENUELO = HASH_SENUELO

@router.post("/login", response_model=TokenResponse)
def login(request: LoginRequest, peticion: Request, db: Session = Depends(get_db)):
    # Acepta número de empleado o correo: la gente teclea lo que recuerda.
    user = CuentasService.buscar_por_identificador(db, request.email)

    # Dos frenos: por IP, contra quien barre muchas cuentas, y por cuenta,
    # contra quien ataca a una persona desde varios sitios. El de cuenta se
    # aplica a la cuenta encontrada y no al texto tecleado; ver
    # `clave_de_cuenta`. Va antes de bcrypt, que es lo caro.
    # La IP de la planta no lleva freno por IP: ver `freno_por_ip`.
    cuenta = clave_de_cuenta(user, request.email, publico=es_publico(peticion))
    por_ip = freno_por_ip(limitador_login_ip, peticion)
    frenar(*por_ip, (limitador_login, cuenta))

    # Una sola respuesta para todos los fracasos.
    #
    # Antes se distinguia: 401 si no existia o la contrasena estaba mal, 400 si
    # la cuenta estaba desactivada y 409 si faltaba activarla. Los dos ultimos
    # **confirmaban que la cuenta existe** y en que estado esta, asi que la
    # pantalla de entrada servia para averiguar quien trabaja aqui. Con numeros
    # de empleado consecutivos eso es recorrer un rango y quedarse con el padron.
    #
    # El texto sigue siendo util para quien si es de la casa: le dice que hacer
    # en su primera entrada sin revelarle nada a quien va de pesca.
    generico = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=("No pudimos iniciar sesión. Revise sus datos. Si es su primera "
                "vez, use «Activar mi cuenta»; si su cuenta fue dada de baja, "
                "contacte al área de TI."),
    )

    # La comparacion se hace SIEMPRE, exista la cuenta o no.
    #
    # `verify_password` devuelve False de inmediato cuando no hay hash —una
    # cuenta sin activar no tiene—, mientras que una cuenta real gasta los
    # ~250 ms de bcrypt. Esa diferencia se mide desde fuera y delata que
    # cuentas existen. Comparando siempre contra algo, todos los caminos
    # cuestan lo mismo.
    hash_a_comparar = (user.password_hash if user else None) or _HASH_SENUELO
    try:
        # En fila con los demás bcrypt: ver `turno_de_hash`.
        with turno_de_hash():
            coincide = verify_password(request.password, hash_a_comparar)
    except HashOcupado:
        # No se llegó a comparar nada: el intento no cuenta contra nadie.
        for limitador, clave in (*por_ip, (limitador_login, cuenta)):
            limitador.descontar(clave)
        raise respuesta_ocupado()

    if not user or not coincide or not user.activo or user.estado_cuenta != "activa":
        raise generico

    user.ultimo_acceso = datetime.utcnow()
    db.commit()

    # Quien entró bien no arrastra sus intentos previos. De la IP solo se
    # descuenta este acierto: los fallos de otros siguen contando.
    limitador_login.limpiar(cuenta)
    for limitador, clave in por_ip:
        limitador.descontar(clave)

    access_token = create_access_token(subject=user.id, version_token=user.version_token)
    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        user=user
    )

@router.post("/login/form", response_model=TokenResponse)
def login_form(
    peticion: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    """Mismo inicio de sesion que `/login`, en el formato que pide Swagger.

    Existe solo para el boton «Authorize» de /docs. **Delega en `login`**: antes
    era una puerta paralela que se saltaba el limite de intentos, la
    comprobacion de cuenta activa y la de cuenta ya activada, asi que servia
    para probar contrasenas sin freno. Una sola implementacion, una sola regla.
    """
    return login(
        LoginRequest(email=form_data.username, password=form_data.password),
        peticion,
        db,
    )

@router.get("/me", response_model=SesionResponse)
def read_current_user(current_user: Usuario = Depends(get_current_user)):
    return current_user


@router.post("/logout")
def cerrar_sesion(
    current_user: Usuario = Depends(get_current_user),
    token: str = Depends(oauth2_scheme),
):
    """Revoca esta sesión —y sus renovaciones— hasta que venza sola.

    `revocada` dice si quedó anotada en Redis. Si no hay Redis es False y el
    frontend solo olvida el token, que es lo que hacía siempre.
    """
    try:
        sid = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM],
                         options={"verify_exp": False}).get("sid")
    except jwt.PyJWTError:
        sid = None
    revocada = sesiones.revocar(sid)
    logger.info("Sesión cerrada", extra={"usuario_id": current_user.id, "revocada": revocada})
    return {"ok": True, "revocada": revocada}

@router.get("/usuarios", response_model=List[UserResponse])
def listar_usuarios(
    solo_activos: bool = True,
    db: Session = Depends(get_db),
    admin: Usuario = Depends(get_current_admin),
):
    """Personas de todas las plantas (TI es global).

    Lo consume el formulario de emisión de resguardos y el expediente. Solo
    admin: la lista de empleados no es información que un usuario cualquiera
    necesite para usar el portal.
    """
    # Los eliminados no salen ni pidiendo `solo_activos=false`: no se le puede
    # asignar un ticket ni emitir un resguardo a alguien que ya no está.
    # TI es global: las personas de todas las plantas.
    consulta = db.query(Usuario).filter(Usuario.eliminado_en.is_(None))
    if solo_activos:
        consulta = consulta.filter(Usuario.activo.is_(True))
    return consulta.order_by(Usuario.nombre).all()

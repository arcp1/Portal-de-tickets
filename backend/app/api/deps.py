import time

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
import jwt
from sqlalchemy.orm import Session
from app.core.config import settings
from app.core.security import create_access_token
from app.core.db import get_db
from app.core import sesiones
from app.core.limitador import frenar, limitador_ia
from app.models import Usuario

oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_STR}/auth/login")

def usuario_desde_token(db: Session, token: str) -> Usuario:
    """Valida un token y devuelve su dueño, o levanta 401.

    Vive aparte de `get_current_user` porque hay un sitio donde no se puede
    usar `Depends`: el WebSocket del grafo, donde el token no viaja en una
    cabecera sino en el primer mensaje (ver `api/conciencia.py`).

    **Y por eso está aquí y no copiado allá.** Debajo hay dos comprobaciones de
    seguridad —la version del token y la cuenta activa— que tienen que valer
    para todas las puertas del portal a la vez. Una copia se queda atrás el día
    que se añada la tercera, y esa clase de hueco no da la cara: la puerta
    vieja sigue abriendo.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="La sesión no es válida. Inicie sesión de nuevo.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        # `exp` y `sub` obligatorios. PyJWT comprueba el vencimiento solo si
        # el token lo trae: uno firmado sin `exp` valía para siempre.
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM],
                             options={"require": ["exp", "sub"]})
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
        # Tokens viejos, de antes de que existiera el versionado, no traen
        # `ver`. Se les asigna la version 1, que es donde arrancan todas las
        # cuentas: siguen valiendo hasta que su dueño cambie la contraseña.
        version_token = int(payload.get("ver", 1))
        sid = payload.get("sid")
    except (jwt.PyJWTError, TypeError, ValueError):
        raise credentials_exception

    # Cerró sesión con este token (o con uno de su misma sesión).
    if sesiones.revocada(sid):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="La sesión se cerró. Inicie sesión de nuevo.",
                            headers={"WWW-Authenticate": "Bearer"})

    try:
        identificador = int(user_id)
    except (TypeError, ValueError):
        raise credentials_exception

    user = db.query(Usuario).filter(Usuario.id == identificador).first()
    if user is None or not user.activo:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="La sesión no es válida. Inicie sesión de nuevo.")

    # Revocación. Si la cuenta subió de versión —cambio de contraseña,
    # restablecimiento, activación asistida— todo token emitido antes deja de
    # servir en el acto, aunque le queden horas de vigencia.
    if int(user.version_token or 1) != version_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="La sesión expiró porque las credenciales de la cuenta cambiaron.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def get_current_user(
    peticion: Request,
    db: Session = Depends(get_db),
    token: str = Depends(oauth2_scheme)
) -> Usuario:
    usuario = usuario_desde_token(db, token)
    _renovar_si_hace_falta(peticion, token, usuario)
    return usuario


def _renovar_si_hace_falta(peticion: Request, token: str, usuario: Usuario) -> None:
    """**La sesión no caduca mientras se está trabajando.**

    El token vive `ACCESS_TOKEN_EXPIRE_MINUTES` (8 h) desde que se entra, y
    antes caducaba a esa hora aunque la persona llevara toda la mañana
    usándolo: el turno largo de TI se topaba con el login a media tarde, y
    justo al pulsar "Guardar". Pasada la mitad de su vida, la respuesta trae
    uno nuevo en `X-Token-Renovado` y el frontend lo guarda. Quien deja de
    usar el portal sigue caducando a su hora.

    No toca la revocación: el token nuevo lleva la misma versión de cuenta, y
    un cambio de contraseña lo invalida igual que al viejo. La cabecera la
    pone `EntregaTokenRenovado` en main.py.

    **Pero no para siempre** (auditoría de seguridad, 2026-10-03). Sin tope,
    un token copiado —de una computadora compartida, de un respaldo del
    navegador— vivía indefinidamente con solo usarlo una vez cada pocas horas,
    hasta que su dueño cerrara sesión o cambiara la contraseña. Pasadas
    `SESION_MAXIMA_HORAS` desde que se entró (`ini`, que heredan las
    renovaciones) ya no se renueva: el último token vence a su hora y hay que
    volver a entrar.
    """
    try:
        datos = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM],
                           options={"verify_exp": False})
        vence = float(datos["exp"])
        # Los tokens de antes del tope no traen `ini`: cuentan desde su emisión.
        inicio = float(datos.get("ini") or datos.get("iat") or time.time())
    except (jwt.PyJWTError, KeyError, TypeError, ValueError):
        return
    if time.time() - inicio > settings.SESION_MAXIMA_HORAS * 3600:
        return
    if vence - time.time() < settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60 / 2:
        # La misma sesión: cerrar sesión tiene que alcanzar también al token
        # renovado, y la vida máxima se sigue contando desde la entrada.
        peticion.state.token_renovado = create_access_token(
            subject=usuario.id, version_token=usuario.version_token,
            sesion=datos.get("sid"), inicio=inicio)


def get_current_admin(
    current_user: Usuario = Depends(get_current_user)
) -> Usuario:
    if current_user.rol != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Esta operación es solo para el equipo de TI."
        )
    return current_user


def usuario_con_cupo_ia(current_user: Usuario = Depends(get_current_user)) -> Usuario:
    """`get_current_user` más el cupo de consultas a la IA de esa persona.

    Para los endpoints que mandan texto al modelo. Ver
    `IA_PETICIONES_POR_MINUTO`: la compuerta protege al modelo; esto, a los
    demás de quien la acapare.
    """
    frenar((limitador_ia, f"ia:{current_user.id}"), motivo="Demasiadas consultas seguidas")
    return current_user

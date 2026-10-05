import secrets
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Optional, Any, Union
import jwt
import bcrypt
from app.core.config import settings

def verify_password(plain_password: str, hashed_password: str) -> bool:
    # Una cuenta dada de alta y sin activar no tiene hash: no hay contra qué
    # comparar, así que no coincide con nada.
    if not hashed_password:
        return False
    try:
        pwd_bytes = plain_password.encode('utf-8')[:72]
        hash_bytes = hashed_password.encode('utf-8')
        return bcrypt.checkpw(pwd_bytes, hash_bytes)
    except Exception:
        return False

def get_password_hash(password: str) -> str:
    pwd_bytes = password.encode('utf-8')[:72]
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(pwd_bytes, salt).decode('utf-8')

#: Hash contra el que se compara cuando no hay nada real que comparar: la
#: cuenta no existe, no tiene contrasena todavia o no tiene codigo. No
#: corresponde a ninguna clave util; su unico proposito es que fallar cueste lo
#: mismo que acertar, para que el tiempo de respuesta no delate que cuentas
#: existen. Lo usan el inicio de sesion y la activacion. Se calcula una vez.
HASH_SENUELO = get_password_hash(secrets.token_urlsafe(32))


class HashOcupado(Exception):
    """No hubo turno para un bcrypt a tiempo: el servidor está saturado de
    intentos de entrada. Quien lo recibe contesta 503 y no cobra el intento."""


#: Cuántos bcrypt corren a la vez como mucho. Ver `turno_de_hash`.
_turnos_hash = threading.BoundedSemaphore(max(1, settings.HASH_EN_PARALELO))
_cola_hash = threading.Lock()
_esperando_hash = 0


@contextmanager
def turno_de_hash():
    """Un turno para comparar o calcular un bcrypt; `HashOcupado` si no lo hay.

    **Por qué** (auditoría para internet abierto, 2026-10-04). Cada intento de
    entrar cuesta ~170 ms de CPU, a propósito, y se hace siempre —exista la
    cuenta o no— para no delatar cuáles existen. Repartido entre muchas IP,
    unos cien intentos por segundo acaparan los 16 núcleos y los 40 hilos del
    backend, y con ellos cae **todo** el portal, no solo la entrada: los
    frenos por IP y por cuenta no ven un ataque que llega de mil sitios a la
    vez contra mil cuentas.

    Con esto, como mucho `HASH_EN_PARALELO` bcrypt corren a la vez y, como
    mucho, `HASH_COLA_MAXIMA` esperan; quien llega con la fila llena o no
    consigue turno en `HASH_ESPERA_S` se va al instante. Durante un ataque
    entrar puede costar un reintento, pero el resto del portal sigue
    contestando: o se sirve pronto, o se dice que no pronto (la misma regla
    que la cola de la IA, services/cola_ia.py).

    Solo para lo que llega de fuera —entrar, activar, cambiar la
    contraseña—. Las altas de TI y la importación no pasan por aquí: no
    deben fallar a medias porque alguien esté atacando la puerta.
    """
    global _esperando_hash
    with _cola_hash:
        if _esperando_hash >= settings.HASH_COLA_MAXIMA:
            raise HashOcupado()
        _esperando_hash += 1
    try:
        conseguido = _turnos_hash.acquire(timeout=settings.HASH_ESPERA_S)
    finally:
        with _cola_hash:
            _esperando_hash -= 1
    if not conseguido:
        raise HashOcupado()
    try:
        yield
    finally:
        _turnos_hash.release()


def respuesta_ocupado():
    """El 503 de quien no consiguió turno. Lleva `Retry-After`: es un "vuelva en
    un momento", no un error de la persona."""
    from fastapi import HTTPException, status

    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="El portal está atendiendo muchos intentos de entrada. Intente de nuevo en unos segundos.",
        headers={"Retry-After": "3"},
    )

def create_access_token(
    subject: Union[str, Any],
    expires_delta: Optional[timedelta] = None,
    version_token: int = 1,
    sesion: Optional[str] = None,
    inicio: Optional[float] = None,
) -> str:
    """Token de sesion.

    Lleva `ver`, la version de la cuenta en el momento de emitirlo. Al validar
    se compara con la que tiene la cuenta ahora: si no coinciden, el token es
    de antes de un cambio de contrasena o de un restablecimiento y ya no vale.
    Es lo que permite revocar de verdad, en vez de solo borrar el token del
    navegador y confiar en que nadie tenga una copia.
    """
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode = {
        "exp": expire,
        "sub": str(subject),
        "ver": int(version_token),
        # Momento de emision: sirve para auditar y para descartar tokens
        # fabricados con una fecha futura.
        "iat": datetime.utcnow(),
        # La sesión: nace al entrar y la heredan las renovaciones. Es lo que
        # se revoca al cerrar sesión (ver core/sesiones.py); el token entero
        # cambia cada pocas horas, la sesión no.
        "sid": sesion or secrets.token_hex(16),
        # Cuándo se entró, en segundos. Lo heredan las renovaciones, como el
        # `sid`, y es lo que pone fin a una sesión que se renueva sin parar:
        # ver `SESION_MAXIMA_HORAS` y `_renovar_si_hace_falta`.
        "ini": int(inicio if inicio is not None else time.time()),
    }
    encoded_jwt = jwt.encode(to_encode, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    return encoded_jwt

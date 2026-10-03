import secrets
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

def create_access_token(
    subject: Union[str, Any],
    expires_delta: Optional[timedelta] = None,
    version_token: int = 1,
    sesion: Optional[str] = None,
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
    }
    encoded_jwt = jwt.encode(to_encode, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    return encoded_jwt

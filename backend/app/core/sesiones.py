"""Cerrar sesión de verdad.

Un token firmado vale hasta que vence: borrarlo del navegador no impide que
otra copia —la de una computadora compartida de planta, la de un respaldo del
navegador— siga entrando hasta 8 horas. Cada token lleva un ``sid`` (la
sesión, que heredan sus renovaciones); al cerrar sesión ese ``sid`` se anota en
Redis como revocado hasta que ya no pueda existir ningún token suyo vigente.

**Sin Redis no hay lista**, y cerrar sesión vuelve a ser solo olvidar el token
en el navegador, como antes. Lo que no depende de Redis sigue intacto: un
cambio de contraseña sube la versión de la cuenta y tumba todos sus tokens
(ver ``usuario_desde_token``).
"""

from typing import Optional

from app.core import redis_cliente
from app.core.config import settings


def _clave(sid: str) -> str:
    return f"sesion:revocada:{sid}"


def revocar(sid: Optional[str]) -> bool:
    """True si quedó anotada; False si no hay Redis (o el token no traía sesión)."""
    if not sid:
        return False
    # Ningún token de esta sesión vive más que esto desde ahora: el más nuevo
    # se emitió como mucho ahora mismo.
    ttl = int(settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60) + 60
    return redis_cliente.usar(lambda r: bool(r.set(_clave(sid), "1", ex=ttl)), False)


def revocada(sid: Optional[str]) -> bool:
    if not sid:
        return False
    return redis_cliente.usar(lambda r: bool(r.exists(_clave(sid))), False)

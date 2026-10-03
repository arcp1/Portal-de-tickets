"""Redis, si lo hay. Y si se cae, que no se lleve el portal con él.

Lo usan los limitadores, la revocación de sesiones, el puente de avisos en
vivo y la cola de tareas. **Ninguno lo necesita para funcionar**: cada uno tiene
su camino en memoria, el mismo que el portal usaba antes de Redis. Este módulo
decide cuándo se usa cada camino.

**El cortacircuitos.** Si Redis no contesta, cada petición que lo consultara
pagaría el tiempo de espera completo antes de caer a memoria: medio segundo por
limitador, y un login pasa por dos. Tras un fallo se le deja de preguntar
`PAUSA_TRAS_FALLO_S` segundos y todo va directo a memoria; luego se vuelve a
probar. Un Redis caído cuesta un aviso en el registro cada tanto, no lentitud
en cada clic.

**Lo que se pierde en memoria**, para que nadie se sorprenda: los limitadores
cuentan por proceso (con un solo proceso de uvicorn da igual), cerrar sesión
solo olvida el token en el navegador, y el worker y el receptor de sensores no
pueden avisar a las pantallas —que se ponen al día en su siguiente consulta—.
"""

import threading
import time
from typing import Any, Callable, Optional, TypeVar

from app.core.config import settings
from app.core.logging import logger

try:  # Dependencia opcional: la suite de pruebas y un despliegue sin Redis no la usan.
    import redis as _redis
except ImportError:  # pragma: no cover
    _redis = None

T = TypeVar("T")

#: Cuánto se deja de preguntar tras un fallo.
PAUSA_TRAS_FALLO_S = 15
#: Lo que se espera a Redis antes de darlo por caído. En la misma red de
#: compose contesta en menos de un milisegundo: medio segundo es una eternidad.
ESPERA_S = 0.5


class _Conexion:
    def __init__(self) -> None:
        self._cliente = None
        self._caido_hasta = 0.0
        self._candado = threading.Lock()
        self._caido = False

    def cliente(self):
        if not settings.REDIS_URL or _redis is None:
            return None
        if time.monotonic() < self._caido_hasta:
            return None
        if self._cliente is None:
            with self._candado:
                if self._cliente is None:
                    self._cliente = _redis.Redis.from_url(
                        settings.REDIS_URL,
                        socket_timeout=ESPERA_S,
                        socket_connect_timeout=ESPERA_S,
                        health_check_interval=30,
                        decode_responses=True,
                    )
        return self._cliente

    def fallo(self, exc: Exception) -> None:
        self._caido_hasta = time.monotonic() + PAUSA_TRAS_FALLO_S
        if not self._caido:
            self._caido = True
            logger.warning("Redis no responde; el portal sigue en memoria",
                           extra={"error": str(exc)})

    def recuperado(self) -> None:
        if self._caido:
            self._caido = False
            logger.info("Redis volvió a responder")

    def reiniciar(self) -> None:
        """Para las pruebas."""
        self._cliente = None
        self._caido_hasta = 0.0
        self._caido = False


conexion = _Conexion()


def usar(operacion: Callable[[Any], T], sin_redis: T) -> T:
    """Corre `operacion(cliente)`, o devuelve `sin_redis` si no hay Redis o falla.

    Quien llama decide qué significa `sin_redis` —normalmente un valor que le
    dice "haz lo de memoria"—.
    """
    cliente = conexion.cliente()
    if cliente is None:
        return sin_redis
    try:
        resultado = operacion(cliente)
    except Exception as exc:  # noqa: BLE001 - RedisError y fallos de red por igual
        conexion.fallo(exc)
        return sin_redis
    conexion.recuperado()
    return resultado


def disponible() -> bool:
    """Si Redis contesta ahora mismo. Para la página de estado."""
    return usar(lambda c: bool(c.ping()), False)


def activo() -> Optional[bool]:
    """None si no está configurado; si no, si contesta."""
    if not settings.REDIS_URL:
        return None
    return disponible()

"""La cola de tareas: lo lento sale de la petición.

Cerrar un ticket lo indexa en la base de conocimiento, y eso es una llamada a
Ollama que en esta CPU tarda segundos. Mandar un correo espera al servidor
SMTP hasta 10. Las dos cosas pasaban **dentro** de la petición: TI pulsaba
"Resolver" y esperaba a que el modelo terminara.

Con ``REDIS_URL`` se encolan en Arq y las hace el contenedor ``worker`` (ver
``app/worker.py``), que además corre los vigilantes programados —SLA,
sensores sin señal, purga de lecturas—. **Sin Redis, o si encolar falla, quien
llama lo hace ahí mismo**, como antes: ``encolar`` devuelve False y nada se
pierde.
"""

import asyncio
from typing import Optional

from app.core.config import settings
from app.core.logging import logger

#: Lo que se espera a que Redis acepte el trabajo antes de hacerlo en la petición.
ESPERA_ENCOLAR_S = 2

_pool = None
_bucle: Optional[asyncio.AbstractEventLoop] = None


async def iniciar(bucle: asyncio.AbstractEventLoop) -> None:
    """Abre la conexión a la cola. La llama el arranque del backend."""
    global _pool, _bucle
    _bucle = bucle
    if not settings.REDIS_URL:
        return
    try:
        from arq import create_pool
        from arq.connections import RedisSettings

        ajustes = RedisSettings.from_dsn(settings.REDIS_URL)
        ajustes.conn_timeout = 1
        ajustes.conn_retries = 1
        _pool = await asyncio.wait_for(create_pool(ajustes), timeout=5)
        logger.info("Cola de tareas conectada")
    except Exception as exc:  # noqa: BLE001
        _pool = None
        logger.warning("Sin cola de tareas: lo lento se hará dentro de la petición",
                       extra={"error": str(exc)})


async def cerrar() -> None:
    global _pool
    if _pool is not None:
        try:
            await _pool.aclose()
        except Exception:  # noqa: BLE001
            pass
        _pool = None


def encolar(funcion: str, *args, id_trabajo: Optional[str] = None) -> bool:
    """Manda `funcion(*args)` al worker. False si hay que hacerlo aquí.

    `id_trabajo` evita encolar dos veces lo mismo mientras siga pendiente
    (Arq no acepta un segundo trabajo con el mismo id): cuenta como encolado.

    Se llama desde rutas síncronas, que corren en hilos del *pool*: el trabajo
    se le pasa al bucle del backend con `run_coroutine_threadsafe` y se espera
    la confirmación de Redis. Desde dentro del bucle no se puede esperar sin
    bloquearlo, así que ahí se lanza y se da por encolado.
    """
    pool, bucle = _pool, _bucle
    if pool is None or bucle is None or bucle.is_closed():
        return False
    corrutina = pool.enqueue_job(funcion, *args, _job_id=id_trabajo)
    try:
        en_el_bucle = asyncio.get_running_loop() is bucle
    except RuntimeError:
        en_el_bucle = False
    if en_el_bucle:
        bucle.create_task(corrutina)
        return True
    futuro = asyncio.run_coroutine_threadsafe(corrutina, bucle)
    try:
        trabajo = futuro.result(timeout=ESPERA_ENCOLAR_S)
    except Exception as exc:  # noqa: BLE001
        futuro.cancel()
        logger.warning("No se pudo encolar; se hace en la petición",
                       extra={"funcion": funcion, "error": str(exc)})
        return False
    return trabajo is not None or id_trabajo is not None


def conectada() -> bool:
    return _pool is not None

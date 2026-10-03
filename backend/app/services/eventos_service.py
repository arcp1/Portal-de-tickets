"""Aviso de que algo cambió, para que las pantallas no vivan de una foto.

**El problema.** El tablero se carga una vez y se queda ahí. Si un técnico
mueve un ticket, el otro no se entera hasta que recarga a mano — y con dos
personas en la misma cola eso significa trabajo duplicado y, peor, la
sensación de estar mirando algo muerto.

**El flujo no lleva datos.** Un evento es literalmente ``tickets`` y nada más:
ni folio, ni título, ni quién. El cliente recibe el empujón y vuelve a pedir su
lista por el camino normal, que ya comprueba permisos. Con esto, abrir el flujo
no puede filtrar la existencia de un ticket que no te toca ver — que es
exactamente lo que pasaría si el evento trajera el id. Cuesta una petición
extra por aviso y compra que este canal no sea una vía paralela a la
autorización.

**El puente de Redis.** Las pantallas se conectan al proceso de uvicorn, pero
ya no es el único que tiene algo que decir: el worker abre alertas de SLA y el
receptor de sensores recibe lecturas, y los dos son procesos aparte. Con
``REDIS_URL`` todo aviso va por el canal ``portal:eventos`` y un oyente dentro
del backend lo reparte a sus pantallas; el worker y el receptor publican en el
mismo canal y llegan igual. Sirve también el día que se pongan varios
``--workers`` de uvicorn: cada uno escucha el canal y reparte a los suyos.

Sin Redis —o con el oyente desconectado— el backend reparte en memoria, como
siempre; lo que publiquen el worker y el receptor se pierde, y las pantallas
lo ven en su siguiente consulta. Nunca se reparte dos veces: si el oyente está
conectado, el aviso solo entra por él.
"""

import asyncio
import json
import logging
from typing import Optional, Set

from app.core import redis_cliente
from app.core.config import settings

logger = logging.getLogger("portal_tickets")

#: El canal de Redis por el que viajan los avisos entre procesos.
CANAL = "portal:eventos"
#: Cuánto se espera antes de reconectar el oyente tras perder Redis.
REINTENTO_S = 5

#: Cuántos avisos se le guardan a un cliente antes de empezar a tirarlos. Es
#: pequeño a propósito: si alguien va tan atrasado, lo que necesita no son
#: quince avisos pendientes sino uno solo que le diga "vuelve a preguntar".
COLA_MAXIMA = 4


class Difusor:
    """Reparte avisos a las pantallas abiertas."""

    def __init__(self) -> None:
        self._suscriptores: Set[asyncio.Queue] = set()
        self._bucle: Optional[asyncio.AbstractEventLoop] = None
        # True mientras el oyente del canal de Redis esté suscrito.
        self._oyendo = False

    def iniciar(self, bucle: asyncio.AbstractEventLoop) -> None:
        """Guarda el bucle de eventos. Lo llama el arranque de la aplicación."""
        self._bucle = bucle

    # ------------------------------------------------------------------
    # Lado del cliente
    # ------------------------------------------------------------------
    def suscribir(self) -> asyncio.Queue:
        cola: asyncio.Queue = asyncio.Queue(maxsize=COLA_MAXIMA)
        self._suscriptores.add(cola)
        return cola

    def cancelar(self, cola: asyncio.Queue) -> None:
        self._suscriptores.discard(cola)

    @property
    def conectados(self) -> int:
        return len(self._suscriptores)

    # ------------------------------------------------------------------
    # Lado del que publica
    # ------------------------------------------------------------------
    def publicar(self, sitio_id: Optional[int], tipo: str) -> None:
        """Avisa de que algo del tipo dado cambió en un sitio.

        ``sitio_id`` vacío es "de todas las plantas" (las alertas de TI, por
        ejemplo): le llega a todo el que pueda ver ese tipo de aviso.

        **Se puede llamar desde cualquier hilo.** Las rutas de FastAPI que son
        ``def`` y no ``async def`` corren en un hilo del *pool*, y una
        ``asyncio.Queue`` no es segura entre hilos: meter ahí un elemento
        directamente es una carrera silenciosa que un día deja de entregar
        avisos sin dar la cara. ``call_soon_threadsafe`` es la única forma
        soportada de cruzar esa frontera, y funciona igual si quien llama ya
        está dentro del bucle.
        """
        mensaje = json.dumps({"s": sitio_id, "t": tipo})
        enviado = redis_cliente.usar(lambda r: r.publish(CANAL, mensaje) is not None, False)
        if enviado and self._oyendo:
            return  # Lo reparte el oyente, a este proceso y a los demás.
        self._local(sitio_id, tipo)

    def _local(self, sitio_id: Optional[int], tipo: str) -> None:
        bucle = self._bucle
        if bucle is None or bucle.is_closed():
            return
        try:
            bucle.call_soon_threadsafe(self._repartir, sitio_id, tipo)
        except RuntimeError:
            # El bucle se está cerrando: la aplicación se apaga y no hay a
            # quién avisar. No es un error que merezca ruido.
            pass

    # ------------------------------------------------------------------
    # El oyente del canal de Redis
    # ------------------------------------------------------------------
    async def escuchar(self) -> None:
        """Reparte lo que llegue por el canal. Corre mientras viva el backend.

        Se reconecta solo: si Redis se cae, mientras tanto se reparte en
        memoria (``_oyendo`` en False) y al volver se retoma el canal.
        """
        if not settings.REDIS_URL:
            return
        import redis.asyncio as aioredis

        while True:
            cliente = None
            try:
                cliente = aioredis.from_url(settings.REDIS_URL, decode_responses=True,
                                            socket_keepalive=True, health_check_interval=30)
                pubsub = cliente.pubsub(ignore_subscribe_messages=True)
                await pubsub.subscribe(CANAL)
                self._oyendo = True
                logger.info("Avisos en vivo por Redis", extra={"canal": CANAL})
                async for mensaje in pubsub.listen():
                    if mensaje.get("type") != "message":
                        continue
                    try:
                        datos = json.loads(mensaje["data"])
                        sitio = datos.get("s")
                        self._repartir(int(sitio) if sitio is not None else None, str(datos["t"]))
                    except (ValueError, KeyError, TypeError):
                        continue
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                if self._oyendo:
                    logger.warning("Se perdió el canal de avisos; se sigue en memoria",
                                   extra={"error": str(exc)})
            finally:
                self._oyendo = False
                if cliente is not None:
                    try:
                        await cliente.aclose()
                    except Exception:  # noqa: BLE001
                        pass
            await asyncio.sleep(REINTENTO_S)

    def _repartir(self, sitio_id: Optional[int], tipo: str) -> None:
        for cola in list(self._suscriptores):
            try:
                cola.put_nowait((sitio_id, tipo))
            except asyncio.QueueFull:
                # Cliente lento. Se pierde el aviso, no el dato: la próxima vez
                # que reciba uno volverá a pedir la lista completa y verá
                # también lo que se perdió.
                pass


#: Instancia única. Es estado de proceso, igual que los limitadores.
difusor = Difusor()


def publicar(sitio_id: Optional[int], tipo: str) -> None:
    """Atajo, para que quien publica no tenga que importar la clase."""
    difusor.publicar(sitio_id, tipo)

"""La traza en vivo de una consulta: qué nodo se encendió y cuándo.

Esto es lo que alimenta el grafo de la pantalla. Cada vez que una consulta pasa
por una etapa —se vectoriza, se busca en el conocimiento, redacta el modelo
local— se emite un paso, y el navegador enciende ese nodo y traza la línea que
lleva hasta él.

**Para qué sirve de verdad.** No es un adorno. Cuando alguien dice "el portal
está lento", la pregunta cara de contestar es *dónde*: ¿no encuentra nada y por
eso tarda, o encuentra y el modelo está encolado? El grafo lo enseña en el
momento y sin entrar a los registros — se ve el nodo que se queda encendido.

**Tres reglas de las que depende que esto sea seguro.**

1. **Cada quien ve su propia traza y nada más.** Las colas van indexadas por
   ``usuario_id`` y un paso solo se entrega a quien originó la consulta. El
   canal de eventos del portal —``eventos_service``— reparte a todo un sitio y
   por eso no puede llevar datos; éste va a una sola persona, así que puede
   llevar el detalle de su propia búsqueda, que es información que esa persona
   está recibiendo igualmente en la respuesta.

2. **Nunca texto recuperado.** Los pasos llevan números —cuántos pasajes, qué
   similitud, cuántos milisegundos— y el nombre del nodo. Nunca el contenido de
   un ticket ni de un documento. Así, aunque mañana alguien amplíe el reparto,
   por aquí no se escapa nada que no fuera un contador.

3. **Perder un paso no rompe nada.** Si la cola de una pantalla está llena, el
   paso se tira. La respuesta viaja por su camino normal, el HTTP de siempre;
   esto solo cuenta lo que va pasando. Una animación incompleta es un defecto
   cosmético — que la respuesta dependiera de este canal sería un defecto de
   diseño.

**Estado de proceso**, con la misma advertencia que ``eventos_service``: con
varios *workers* de uvicorn, cada proceso tendría sus propios suscriptores y la
traza de una consulta atendida por el worker B no llegaría a la pantalla
conectada al worker A. La salida entonces es ``LISTEN/NOTIFY`` de Postgres.
"""

import asyncio
import time
import uuid
from typing import Any, Dict, Optional, Set

from app.core.config import settings
from app.core.logging import logger

#: Los nodos del grafo. El frontend dibuja exactamente estos y en este orden;
#: si se añade uno aquí hay que añadirlo también en `GrafoConciencia.jsx`.
#:
#: `embedding` e `ia_local` son el mismo Ollama haciendo dos trabajos muy
#: distintos —vectorizar cuesta ~80 ms, redactar ~4 s— y se separan justo por
#: eso: mezclados, el nodo lento escondería al rápido y el grafo no diría nada.
NODOS = ("usuario", "embedding", "conocimiento", "ia_local", "gemini", "respuesta")

#: Estados que puede tener un nodo. `omitido` no es un fallo: es la escalera del
#: asistente funcionando —si la coincidencia fue directa, no se redacta nada y
#: el nodo del modelo se queda apagado a propósito—.
ESTADOS = ("activo", "listo", "omitido", "error")


class Traza:
    """Los pasos de una consulta concreta, con su reloj propio.

    Se crea una por consulta. Lleva el identificador que agrupa los pasos en la
    pantalla —si alguien lanza dos consultas seguidas, el grafo no mezcla los
    de una con los de la otra— y el instante de inicio, para que cada paso diga
    cuántos milisegundos van desde que empezó todo.
    """

    def __init__(self, usuario_id: int):
        self.id = uuid.uuid4().hex[:12]
        self.usuario_id = usuario_id
        self._inicio = time.monotonic()
        self._ultimo_nodo = "usuario"

    def transcurrido_ms(self) -> int:
        return int((time.monotonic() - self._inicio) * 1000)

    def paso(
        self,
        nodo: str,
        estado: str = "activo",
        desde: Optional[str] = None,
        **detalle: Any,
    ) -> None:
        """Enciende un nodo del grafo.

        ``desde`` es el nodo del que viene la línea. Si no se dice, se usa el
        último que se encendió, que es lo que hace que el camino se dibuje solo
        sin que cada llamada tenga que repetir de dónde venía.

        **No levanta nunca.** Contar lo que pasa no puede tumbar lo que pasa.
        """
        try:
            if nodo not in NODOS or estado not in ESTADOS:
                logger.warning("Paso de traza desconocido",
                               extra={"nodo": nodo, "estado": estado})
                return

            origen = desde if desde is not None else self._ultimo_nodo
            # Solo avanza el cursor cuando el nodo queda listo: mientras está
            # `activo` el siguiente paso todavía viene del anterior.
            if estado in ("listo", "omitido"):
                self._ultimo_nodo = nodo

            difusor_traza.publicar(
                self.usuario_id,
                {
                    "traza": self.id,
                    "nodo": nodo,
                    "estado": estado,
                    "desde": origen if origen != nodo else None,
                    "ms": self.transcurrido_ms(),
                    # Solo números y banderas. Nunca texto recuperado: ver la
                    # regla 2 en la cabecera de este archivo.
                    "detalle": {k: v for k, v in detalle.items() if v is not None},
                },
            )
        except Exception as exc:  # noqa: BLE001 - la traza jamás rompe la consulta
            logger.warning("No se pudo emitir un paso de la traza",
                           extra={"error": str(exc)})


class DifusorTraza:
    """Reparte pasos, cada uno solo a quien lo originó."""

    def __init__(self) -> None:
        self._suscriptores: Dict[int, Set[asyncio.Queue]] = {}
        self._bucle: Optional[asyncio.AbstractEventLoop] = None

    def iniciar(self, bucle: asyncio.AbstractEventLoop) -> None:
        self._bucle = bucle

    # ------------------------------------------------------------------
    def suscribir(self, usuario_id: int) -> asyncio.Queue:
        cola: asyncio.Queue = asyncio.Queue(maxsize=settings.TRAZA_COLA_MAXIMA)
        self._suscriptores.setdefault(usuario_id, set()).add(cola)
        return cola

    def cancelar(self, usuario_id: int, cola: asyncio.Queue) -> None:
        colas = self._suscriptores.get(usuario_id)
        if not colas:
            return
        colas.discard(cola)
        # Sin esto el diccionario crece con una entrada vacía por cada persona
        # que haya abierto el portal alguna vez desde el último reinicio.
        if not colas:
            self._suscriptores.pop(usuario_id, None)

    @property
    def conectados(self) -> int:
        return sum(len(c) for c in self._suscriptores.values())

    def hay_alguien(self, usuario_id: int) -> bool:
        """True si esa persona tiene el grafo abierto.

        Quien emite lo consulta para no armar el detalle de un paso que nadie
        va a mirar. Es barato, pero se llama varias veces por consulta.
        """
        return bool(self._suscriptores.get(usuario_id))

    # ------------------------------------------------------------------
    def publicar(self, usuario_id: int, evento: dict) -> None:
        """Entrega un paso. Se puede llamar desde cualquier hilo.

        Igual que en ``eventos_service``: las rutas ``def`` corren en un hilo
        del *pool* y una ``asyncio.Queue`` no es segura entre hilos. Meter ahí
        un elemento directamente es una carrera silenciosa que un día deja de
        entregar sin dar la cara. ``call_soon_threadsafe`` es la única forma
        soportada de cruzar esa frontera, y funciona igual si quien llama ya
        está dentro del bucle.
        """
        bucle = self._bucle
        if bucle is None or bucle.is_closed():
            return
        if not self._suscriptores.get(usuario_id):
            return
        try:
            bucle.call_soon_threadsafe(self._repartir, usuario_id, evento)
        except RuntimeError:
            # El bucle se está cerrando: la aplicación se apaga.
            pass

    def _repartir(self, usuario_id: int, evento: dict) -> None:
        for cola in list(self._suscriptores.get(usuario_id, ())):
            try:
                cola.put_nowait(evento)
            except asyncio.QueueFull:
                # Pantalla lenta. Se pierde un fotograma de la animación, no la
                # respuesta: ésa va por HTTP y no depende de esto.
                pass


#: Instancia única, estado de proceso — igual que el difusor de eventos.
difusor_traza = DifusorTraza()


def abrir(usuario_id: int) -> Traza:
    """Empieza a contar una consulta."""
    return Traza(usuario_id)

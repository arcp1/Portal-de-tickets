"""Quién puede usar la CPU ahora mismo, y quién se queda fuera.

**El problema, con números.** qwen2.5:3b corre aquí sin GPU: la generación se
come los ocho núcleos del Ryzen y va a ~12 tokens/s. Dos generaciones a la vez
no van a 12 cada una — van a ~5, porque lo que se satura no es el reloj sino el
ancho de banda a la RAM. El trabajo total baja. Cinco a la vez es peor todavía:
nadie termina, todos esperan, y el portal entero parece caído aunque esté
perfectamente vivo.

Así que el aforo de generación es **uno**. No es una limitación: es la
configuración que más trabajo saca de esta máquina.

**Y la sala de espera también se acota.** Medido aquí: cinco consultas a la vez,
sin compuerta, y el último recibió su respuesta **72 segundos** después. Para una
ayuda opcional que aparece mientras alguien llena un formulario, eso no es
servir tarde: es no servir. A los 72 s el ticket ya se envió — y por el camino
la gente recarga la página, lo que vuelve a encolar la consulta y lo empeora.

**La regla: o se sirve pronto, o se dice que no pronto. Nunca esperar y luego
fallar.** Esperar y acabar sin nada es pagar el costo de la cola sin llevarse
nada a cambio, y es el peor de los resultados posibles.

**Y por eso la puerta no la decide un cronómetro, la decide una estimación.**
Esto se intentó primero con un plazo fijo —"espera ocho segundos y ríndete"— y
falló dos veces seguidas por la misma razón: *el plazo fijo no sabe cuánto
tarda una generación, y una generación no tarda siempre lo mismo*. Medido en
esta máquina, la misma consulta tardó 14 s una vez y 21 s la siguiente, según
lo que estuviera haciendo el resto del equipo. Con el plazo en 8 s se rendían
todos justo antes de que les tocara; al subirlo a 20 s, la generación de 20.7 s
volvió a dejar a alguien esperando en balde. Cualquier constante que se elija
la gana una generación lenta.

Así que se mide. La compuerta lleva la cuenta de lo que tardan de verdad las
últimas generaciones y, cuando alguien llega, calcula lo que le tocaría esperar:

    espera estimada ≈ (cuántos hay delante / aforo) × lo que tardó la última vez

Si eso pasa del presupuesto, **se le dice que no en el acto** —cero segundos
perdidos—. Y si cabe, se le admite con la promesa de servirle: quien entra a la
cola espera lo que haga falta, hasta un techo holgado que solo existe para que
una generación colgada no retenga a nadie para siempre.

La diferencia práctica: el plazo fijo hacía esperar para después fallar; la
estimación falla antes de hacer esperar. Se ajusta sola cuando el modelo cambia
de velocidad —otro modelo, una GPU, una máquina más ocupada— sin que nadie
tenga que recalibrar una constante.

Decir que no aquí no cuesta nada, y ésa es la pieza que hace que todo esto
funcione: todo este módulo devuelve ``None`` cuando no hay turno, que es
exactamente lo que ``ollama_client`` ya sabe manejar desde el primer día. Sin
turno, el ticket se levanta igual, sin normalizar; la búsqueda se hace igual,
por similitud de lo ya indexado; el chat pide los dropdowns. El usuario ve el
portal un poco más tonto durante diez segundos, no un portal detenido.

**Por qué con primitivas de hilos y no de asyncio.** ``ollama_client`` es
síncrono y lo llaman rutas ``def``, que Starlette ejecuta en el *pool* de hilos.
Un ``asyncio.Semaphore`` ahí no sirve —no es seguro entre hilos— y convertir
todo el cliente a asíncrono sería reescribir lo que ya funciona. Con
``threading`` esto vale para los dos mundos: las rutas ``async`` entran por
``asyncio.to_thread``, que también es un hilo del *pool*.

**Esto es estado de proceso**, igual que el difusor de eventos y los
limitadores. Con varios *workers* de uvicorn cada uno tendría su propio aforo y
el total sería el aforo por el número de procesos — que es justo lo que este
módulo existe para evitar. El ``CMD`` del Dockerfile levanta uno solo; quien le
ponga ``--workers`` tiene que mover esto a un semáforo compartido (Redis, o el
propio Postgres con ``pg_advisory_lock``).
"""

import threading
import time
from collections import deque
from contextlib import contextmanager
from typing import Dict, Iterator, Optional

from app.core.config import settings
from app.core.logging import logger


class Compuerta:
    """Deja pasar a unos cuantos, hace esperar a unos pocos y rechaza al resto.

    Cuatro números, cada uno con su pregunta:

    - ``aforo``: cuántos trabajan a la vez. Lo fija el hardware.
    - ``sala``: tope duro de cuántos pueden estar esperando. Es un límite de
      memoria e hilos, no de paciencia: de la paciencia se encarga el siguiente.
    - ``espera_maxima``: el **presupuesto** de espera. Si lo que se estima que
      va a esperar alguien lo rebasa, no entra a la cola: se le contesta ya.
    - ``duracion_inicial``: cuánto se supone que tarda un trabajo mientras no
      haya ninguno medido. A partir del primero, manda lo medido.

    El tiempo de trabajo **no** se cuenta aquí: de eso ya se encargan los
    ``timeout`` de httpx que ``ollama_client`` le pasa a cada llamada.
    """

    #: Cuántas muestras se conservan de esperas y duraciones. Ventana móvil, no
    #: histórico: se pierde al reiniciar.
    MUESTRAS = 50

    #: Cuánto más del presupuesto se tolera antes de soltar a alguien que ya
    #: fue admitido. Existe solo para que una generación colgada no retenga a
    #: nadie para siempre; en operación normal no se llega nunca, porque la
    #: admisión ya descartó a quien no cabía.
    HOLGURA_TECHO = 3.0

    def __init__(self, nombre: str, aforo: int, sala: int, espera_maxima: float,
                 duracion_inicial: float = 15.0):
        self.nombre = nombre
        self.aforo = max(1, int(aforo))
        self.sala = max(0, int(sala))
        self.espera_maxima = float(espera_maxima)
        self.duracion_inicial = float(duracion_inicial)

        self._condicion = threading.Condition()
        self._en_curso = 0
        self._esperando = 0

        # Contadores desde el arranque. Sirven para contestar "¿se está
        # rechazando gente?" sin tener que reproducir la carga.
        self._admitidos = 0
        self._rechazados_sala = 0
        self._rechazados_espera = 0
        self._esperas = deque(maxlen=self.MUESTRAS)
        #: Lo que tardaron de verdad los últimos trabajos. Es lo que convierte
        #: la admisión en una estimación en vez de una apuesta.
        self._duraciones = deque(maxlen=self.MUESTRAS)

    # ------------------------------------------------------------------
    def _duracion(self) -> float:
        """Lo que se espera que tarde un trabajo, en segundos.

        Se usa la **mediana** y no el promedio: una sola generación lenta
        —porque alguien estaba compilando en la misma máquina— arrastraría el
        promedio hacia arriba y haría rechazar gente que sí cabía. La mediana
        aguanta ese caso sin despeinarse.
        """
        if not self._duraciones:
            return self.duracion_inicial
        ordenadas = sorted(self._duraciones)
        return ordenadas[len(ordenadas) // 2]

    def _espera_estimada(self) -> float:
        """Cuánto tendría que esperar alguien que llegara ahora mismo.

        Los que hay delante son los que están trabajando más los que ya
        esperan. Se divide entre el aforo porque con varias plazas la fila
        avanza en paralelo, y se redondea hacia arriba: con aforo 2 y tres
        delante, el que llega espera dos turnos, no uno y medio.
        """
        delante = self._en_curso + self._esperando
        if delante < self.aforo:
            return 0.0
        turnos = -(-delante // self.aforo)      # división entera hacia arriba
        return turnos * self._duracion()

    # ------------------------------------------------------------------
    @contextmanager
    def turno(self, espera_maxima: Optional[float] = None) -> Iterator[bool]:
        """Pide turno. El valor del ``with`` dice si lo hubo.

        Se usa siempre igual, y el ``if`` no es opcional::

            with compuerta.turno() as hay_turno:
                if not hay_turno:
                    return None          # degradar, nunca esperar más
                ...trabajo...

        Devolver ``False`` en vez de levantar una excepción es deliberado:
        quedarse sin turno **no es un error**. Es el sistema funcionando como
        se diseñó, y quien llama ya tiene escrito el camino sin IA.
        """
        presupuesto = self.espera_maxima if espera_maxima is None else float(espera_maxima)
        inicio = time.monotonic()

        with self._condicion:
            # --- La admisión, que es donde vive toda la gracia de esto ---
            #
            # Se decide **antes** de hacer esperar a nadie. Un "no" aquí cuesta
            # cero segundos; un "no" después de la cola cuesta la cola entera y
            # no entrega nada.
            if self._en_curso >= self.aforo:
                estimada = self._espera_estimada()

                if self._esperando >= self.sala or estimada > presupuesto:
                    self._rechazados_sala += 1
                    logger.info(
                        "Sin turno de IA: no cabe en el presupuesto de espera",
                        extra={"compuerta": self.nombre,
                               "en_curso": self._en_curso,
                               "esperando": self._esperando,
                               "espera_estimada_s": round(estimada, 1),
                               "presupuesto_s": round(presupuesto, 1)},
                    )
                    yield False
                    return

            self._esperando += 1
            try:
                # Admitido es admitido: se espera lo que haga falta. El techo
                # solo está para que una generación colgada no retenga a nadie
                # indefinidamente — no es el plazo normal, es el freno de
                # emergencia, y llegar a él significa que algo va mal.
                techo = presupuesto * self.HOLGURA_TECHO
                while self._en_curso >= self.aforo:
                    restante = techo - (time.monotonic() - inicio)
                    if restante <= 0 or not self._condicion.wait(restante):
                        # `wait` con timeout devuelve False al agotarse. Se
                        # vuelve a comprobar la condición porque un despertar
                        # espurio también devuelve el control aquí.
                        if self._en_curso >= self.aforo:
                            self._rechazados_espera += 1
                            logger.warning(
                                "Sin turno de IA tras esperar el techo completo: "
                                "alguna generación se está eternizando",
                                extra={"compuerta": self.nombre,
                                       "techo_s": round(techo, 1)},
                            )
                            yield False
                            return
            finally:
                self._esperando -= 1

            self._en_curso += 1
            self._admitidos += 1
            espera_ms = (time.monotonic() - inicio) * 1000.0
            self._esperas.append(espera_ms)

        arranque = time.monotonic()
        try:
            yield True
        finally:
            with self._condicion:
                # Lo que tardó de verdad, que es lo que hará acertar a la
                # siguiente estimación. Se anota también si el trabajo reventó:
                # una llamada que falla a los 30 s ocupó la plaza esos 30 s, y
                # esconder eso haría admitir de más justo cuando peor va todo.
                self._duraciones.append(time.monotonic() - arranque)
                self._en_curso -= 1
                # `notify` y no `notify_all`: se libera **una** plaza, así que
                # despertar a todos los que esperan solo provoca que compitan
                # por ella y se vuelvan a dormir todos menos uno.
                self._condicion.notify()

    # ------------------------------------------------------------------
    def metricas(self) -> dict:
        """Foto del estado, para la pantalla de Estado del sistema."""
        with self._condicion:
            esperas = list(self._esperas)
            return {
                "aforo": self.aforo,
                "sala": self.sala,
                "en_curso": self._en_curso,
                "esperando": self._esperando,
                "admitidos": self._admitidos,
                "rechazados_sala": self._rechazados_sala,
                # Este debería quedarse en cero. Si sube, hay generaciones que
                # duran mucho más de lo que la mediana predice y la admisión
                # está calculando mal: es la señal de que algo va raro, no de
                # que haya mucha carga.
                "rechazados_espera": self._rechazados_espera,
                "espera_promedio_ms": (
                    round(sum(esperas) / len(esperas), 1) if esperas else None
                ),
                "espera_maxima_ms": round(max(esperas), 1) if esperas else None,
                # Lo que tarda una generación ahora mismo, medido. Es el número
                # con el que se decide a quién se admite, así que verlo explica
                # por qué se está rechazando a quien se rechaza.
                "duracion_mediana_s": round(self._duracion(), 1),
                "espera_estimada_s": round(self._espera_estimada(), 1),
            }

    def saturada(self) -> bool:
        """True si ahora mismo hay alguien esperando turno."""
        with self._condicion:
            return self._esperando > 0 or self._en_curso >= self.aforo


# ----------------------------------------------------------------------
# Las dos compuertas del portal, y por qué son dos y no una
# ----------------------------------------------------------------------
#
# Meter embeddings y generación en la misma cola sería un error caro. Un
# embedding de nomic-embed-text tarda ~80 ms; una generación de qwen2.5:3b
# tarda ~4 s, o sea cincuenta veces más. Con una sola cola, cada búsqueda por
# similitud —que es barata y la hace todo el mundo todo el rato— quedaría
# atrapada detrás de una redacción larga, y la parte del portal que **sí**
# escala bien heredaría la latencia de la que no.
#
# Separadas, la recuperación sigue respondiendo en milisegundos aunque el
# modelo de texto esté ocupado. Que es exactamente lo que se quiere: el RAG
# encuentra, y si no hay turno para redactar, se muestran los extractos.

#: Generación de texto: normalizar, clasificar, redactar. Aforo uno.
generacion = Compuerta(
    "generacion",
    aforo=settings.IA_AFORO_GENERACION,
    sala=settings.IA_SALA_GENERACION,
    espera_maxima=settings.IA_ESPERA_MAXIMA_GENERACION,
    duracion_inicial=settings.IA_DURACION_INICIAL_GENERACION,
)

#: Embeddings: indexar y buscar. Baratos, así que caben varios y la sala es
#: amplia — aquí esperar medio segundo es preferible a perder la búsqueda.
embeddings = Compuerta(
    "embedding",
    aforo=settings.IA_AFORO_EMBEDDING,
    sala=settings.IA_SALA_EMBEDDING,
    espera_maxima=settings.IA_ESPERA_MAXIMA_EMBEDDING,
    # Décimas de segundo, no segundos: aquí la cola casi nunca llega a formarse.
    duracion_inicial=0.3,
)


def metricas() -> Dict[str, dict]:
    """Lo que ve TI en la pantalla de Estado."""
    return {"generacion": generacion.metricas(), "embeddings": embeddings.metricas()}

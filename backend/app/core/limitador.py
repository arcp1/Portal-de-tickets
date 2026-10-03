"""Freno a los intentos de inicio de sesión.

Sin esto, cualquiera en la red de la planta puede probar contraseñas contra
`/api/auth/login` a la velocidad que quiera. El bloqueo de cuenta por intentos
fallidos que ya existe en el dominio no ayuda contra alguien que prueba una
contraseña común contra muchos usuarios distintos.

**Con Redis o en memoria.** Con ``REDIS_URL`` la ventana vive en Redis (un
conjunto ordenado por clave, con un guion Lua para que comprobar y anotar sea
una sola operación): vale para todos los procesos y sobrevive a un reinicio del
backend, así que reiniciar ya no es una forma de borrar el freno. Sin Redis —o
si se cae— cada proceso cuenta en memoria, como antes; con una sola instancia
del backend, que es el caso de la planta, alcanza.
"""

import time
import uuid
from collections import defaultdict, deque
from threading import Lock
from typing import Deque, Dict

from app.core import redis_cliente
from app.core.config import settings
from app.core.logging import logger

#: Comprobar y anotar en un solo paso. Con dos órdenes sueltas, cien peticiones
#: en paralelo leerían todas "hay cupo" antes de que la primera anotara.
_LUA_PERMITIDO = """
local clave = KEYS[1]
local ahora = tonumber(ARGV[1])
local ventana = tonumber(ARGV[2])
local maximo = tonumber(ARGV[3])
redis.call('ZREMRANGEBYSCORE', clave, '-inf', ahora - ventana)
if redis.call('ZCARD', clave) >= maximo then
  return 0
end
redis.call('ZADD', clave, ahora, ARGV[4])
redis.call('EXPIRE', clave, math.ceil(ventana) + 1)
return 1
"""

#: Lo que devuelve `redis_cliente.usar` cuando hay que hacerlo en memoria.
_EN_MEMORIA = object()


class Limitador:
    """Ventana deslizante de intentos por clave (IP o correo)."""

    #: Cada cuantas comprobaciones se barren las claves ya vencidas. `purgar()`
    #: existia desde el principio pero **nadie lo llamaba**, asi que el
    #: diccionario solo crecia: bastaba con enviar identificadores distintos
    #: —un correo inventado por peticion— para agotar la memoria del proceso.
    #: Barrer cada tanto sale practicamente gratis y cierra esa via.
    BARRIDO_CADA = 500

    def __init__(self, maximo: int, ventana_segundos: int, nombre: str = "general"):
        self.maximo = maximo
        self.ventana = ventana_segundos
        self.nombre = nombre
        self._intentos: Dict[str, Deque[float]] = defaultdict(deque)
        # Uvicorn atiende peticiones en varios hilos: el diccionario se toca
        # desde más de uno.
        self._candado = Lock()
        self._desde_el_ultimo_barrido = 0

    def _clave_redis(self, clave: str) -> str:
        return f"lim:{self.nombre}:{clave}"

    def permitido(self, clave: str) -> bool:
        """True si puede intentar. Registra el intento si lo permite."""
        en_redis = redis_cliente.usar(
            lambda r: bool(r.eval(_LUA_PERMITIDO, 1, self._clave_redis(clave), time.time(),
                                  self.ventana, self.maximo, uuid.uuid4().hex)),
            _EN_MEMORIA)
        if en_redis is not _EN_MEMORIA:
            return en_redis
        ahora = time.monotonic()
        barrer = False
        with self._candado:
            cola = self._intentos[clave]
            # Se descartan los intentos que ya salieron de la ventana.
            while cola and ahora - cola[0] > self.ventana:
                cola.popleft()

            self._desde_el_ultimo_barrido += 1
            if self._desde_el_ultimo_barrido >= self.BARRIDO_CADA:
                self._desde_el_ultimo_barrido = 0
                barrer = True

            if len(cola) >= self.maximo:
                permitido = False
            else:
                cola.append(ahora)
                permitido = True

        # Fuera del candado: `purgar` toma el suyo.
        if barrer:
            self.purgar()
        return permitido

    def segundos_restantes(self, clave: str) -> int:
        def _de_redis(r):
            primero = r.zrange(self._clave_redis(clave), 0, 0, withscores=True)
            if not primero:
                return 0
            return max(0, int(self.ventana - (time.time() - primero[0][1])))
        en_redis = redis_cliente.usar(_de_redis, _EN_MEMORIA)
        if en_redis is not _EN_MEMORIA:
            return en_redis
        with self._candado:
            cola = self._intentos.get(clave)
            if not cola:
                return 0
            return max(0, int(self.ventana - (time.monotonic() - cola[0])))

    def descontar(self, clave: str):
        """Quita el intento más reciente de `clave`.

        El intento se anota *antes* de comprobar la contraseña —si se anotara
        después, cien peticiones en paralelo pasarían todas el filtro antes de
        que la primera contara—. Cuando sale bien, se descuenta: en el freno
        por IP solo deben pesar los fallos, porque esa IP puede ser la de toda
        la planta y los aciertos de un cambio de turno la agotarían.
        """
        if redis_cliente.usar(lambda r: r.zpopmax(self._clave_redis(clave)) or True,
                              _EN_MEMORIA) is not _EN_MEMORIA:
            return
        with self._candado:
            cola = self._intentos.get(clave)
            if cola:
                cola.pop()

    def limpiar(self, clave: str):
        """Tras un inicio de sesión exitoso: quien entró bien no arrastra
        el conteo de sus intentos fallidos."""
        if redis_cliente.usar(lambda r: r.delete(self._clave_redis(clave)) or True,
                              _EN_MEMORIA) is not _EN_MEMORIA:
            return
        with self._candado:
            self._intentos.pop(clave, None)

    def purgar(self):
        """Quita las claves que ya no tienen intentos vigentes.

        Sin esto el diccionario crece sin límite en un proceso de larga vida.
        """
        ahora = time.monotonic()
        with self._candado:
            vacias = [
                clave for clave, cola in self._intentos.items()
                if not cola or ahora - cola[-1] > self.ventana
            ]
            for clave in vacias:
                del self._intentos[clave]
        if vacias:
            logger.debug("Limitador purgado", extra={"claves": len(vacias)})


limitador_login = Limitador(
    maximo=settings.LOGIN_MAX_INTENTOS,
    ventana_segundos=settings.LOGIN_VENTANA_SEGUNDOS,
    nombre="login",
)
limitador_login_ip = Limitador(
    maximo=settings.LOGIN_MAX_INTENTOS_POR_IP,
    ventana_segundos=settings.LOGIN_VENTANA_SEGUNDOS,
    nombre="login_ip",
)
limitador_activacion = Limitador(
    maximo=settings.ACTIVACION_FRENO_POR_CUENTA,
    ventana_segundos=settings.ACTIVACION_FRENO_VENTANA_SEGUNDOS,
    nombre="activacion",
)
limitador_activacion_ip = Limitador(
    maximo=settings.ACTIVACION_FRENO_POR_IP,
    ventana_segundos=settings.ACTIVACION_FRENO_VENTANA_SEGUNDOS,
    nombre="activacion_ip",
)

limitador_ia = Limitador(maximo=settings.IA_PETICIONES_POR_MINUTO, ventana_segundos=60,
                         nombre="ia")


def clave_de_cuenta(usuario, identificador: str) -> str:
    """La clave del freno por cuenta: la cuenta, no lo que se tecleó.

    Antes era el texto tal cual, y la búsqueda le quita los espacios: "67",
    " 67", "67 " y el correo de esa misma persona eran cuatro contadores
    distintos contra una sola cuenta —intentos ilimitados con solo variar
    los espacios—. Si no hay cuenta, se normaliza igual que la búsqueda.
    """
    if usuario is not None:
        return f"cuenta:{usuario.id}"
    return f"id:{(identificador or '').strip().lower()}"


def frenar(*pares, motivo: str = "Demasiados intentos") -> None:
    """Anota un intento en cada `(limitador, clave)`; 429 si alguno se pasó.

    Si uno rechaza, se descuentan los que ya habían anotado: un intento que
    no llegó a hacerse no debe gastar el cupo de los demás frenos.
    """
    from fastapi import HTTPException, status

    anotados = []
    for limitador, clave in pares:
        if limitador.permitido(clave):
            anotados.append((limitador, clave))
            continue
        for previo, clave_previa in anotados:
            previo.descontar(clave_previa)
        espera = limitador.segundos_restantes(clave)
        logger.warning("Demasiados intentos", extra={"clave": clave, "espera_s": espera})
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"{motivo}. Espere {espera} segundos.",
            headers={"Retry-After": str(espera)},
        )

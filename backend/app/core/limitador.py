"""Freno a los intentos de inicio de sesión.

Sin esto, cualquiera en la red de la planta puede probar contraseñas contra
`/api/auth/login` a la velocidad que quiera. El bloqueo de cuenta por intentos
fallidos que ya existe en el dominio no ayuda contra alguien que prueba una
contraseña común contra muchos usuarios distintos.

Es un limitador en memoria, por proceso. Con una sola instancia del backend
—que es el caso de la planta— alcanza. Si algún día hay varias réplicas detrás
de NGINX, esto se cambia por Redis; el punto de cambio es una sola clase.
"""

import time
from collections import defaultdict, deque
from threading import Lock
from typing import Deque, Dict

from app.core.config import settings
from app.core.logging import logger


class Limitador:
    """Ventana deslizante de intentos por clave (IP o correo)."""

    def __init__(self, maximo: int, ventana_segundos: int):
        self.maximo = maximo
        self.ventana = ventana_segundos
        self._intentos: Dict[str, Deque[float]] = defaultdict(deque)
        # Uvicorn atiende peticiones en varios hilos: el diccionario se toca
        # desde más de uno.
        self._candado = Lock()

    def permitido(self, clave: str) -> bool:
        """True si puede intentar. Registra el intento si lo permite."""
        ahora = time.monotonic()
        with self._candado:
            cola = self._intentos[clave]
            # Se descartan los intentos que ya salieron de la ventana.
            while cola and ahora - cola[0] > self.ventana:
                cola.popleft()

            if len(cola) >= self.maximo:
                return False

            cola.append(ahora)
            return True

    def segundos_restantes(self, clave: str) -> int:
        with self._candado:
            cola = self._intentos.get(clave)
            if not cola:
                return 0
            return max(0, int(self.ventana - (time.monotonic() - cola[0])))

    def limpiar(self, clave: str):
        """Tras un inicio de sesión exitoso: quien entró bien no arrastra
        el conteo de sus intentos fallidos."""
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
)

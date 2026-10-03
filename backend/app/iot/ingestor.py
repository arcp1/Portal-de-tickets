"""El receptor de telemetría: escucha a Mosquitto y guarda lo que mandan los ESP32.

Corre en su propio contenedor (``ingestor`` en docker-compose), con la misma
imagen y el mismo código que el backend:

    python -m app.iot.ingestor

**Un proceso aparte a propósito.** Un cliente MQTT es una conexión que vive
para siempre con su propio hilo de red; dentro de uvicorn compartiría el
proceso con las peticiones, y un sensor que manda basura a toda velocidad
competiría por la CPU con quien intenta levantar un ticket. Aparte, si se cae
o se reinicia, el portal no se entera.

**Qué hace con cada mensaje:** se lo pasa a ``IoTService.procesar`` —que decide
todo y se prueba sin broker— y, si cambió algo, avisa por Redis a las
pantallas de TI (``iot`` para la gráfica, ``alertas`` para la campana).

**No pierde lecturas en un reinicio corto.** Se conecta con identificador fijo
y sesión persistente (``clean_session=False``) y se suscribe con QoS 1:
mientras está caído, Mosquitto le guarda los mensajes y se los entrega al
volver.
"""

import signal
import sys
import time

import paho.mqtt.client as mqtt

from app.core.config import settings
from app.core.db import SessionLocal
from app.core.logging import logger, setup_logging
from app.services import eventos_service as eventos
from app.services.iot_service import IoTService

#: Cada cuánto, como mucho, se avisa a las pantallas de que hay lecturas
#: nuevas. Con diez equipos cada 5 s serían dos avisos por segundo y cada uno
#: hace que la pantalla vuelva a pedir la gráfica.
AVISO_IOT_CADA_S = 5


class Receptor:
    def __init__(self) -> None:
        self._ultimo_aviso = 0.0
        self.recibidos = 0
        self.guardados = 0
        self.cliente = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id="portal-ingestor",
            clean_session=False,
        )
        if settings.MQTT_USUARIO:
            self.cliente.username_pw_set(settings.MQTT_USUARIO, settings.MQTT_PASSWORD or None)
        self.cliente.on_connect = self._al_conectar
        self.cliente.on_disconnect = self._al_desconectar
        self.cliente.on_message = self._al_recibir
        self.cliente.reconnect_delay_set(min_delay=1, max_delay=30)

    # -- Conexión -----------------------------------------------------------
    def _al_conectar(self, cliente, _datos, _banderas, codigo, _propiedades=None):
        if codigo.is_failure:
            logger.error("Mosquitto rechazó la conexión", extra={"codigo": str(codigo)})
            return
        cliente.subscribe(settings.MQTT_TEMA_TELEMETRIA, qos=1)
        logger.info("Receptor conectado a Mosquitto",
                    extra={"host": settings.MQTT_HOST, "tema": settings.MQTT_TEMA_TELEMETRIA})

    def _al_desconectar(self, _cliente, _datos, _banderas, codigo, _propiedades=None):
        logger.warning("Receptor desconectado de Mosquitto; reintentando",
                       extra={"codigo": str(codigo)})

    # -- Mensajes -------------------------------------------------------------
    def _al_recibir(self, _cliente, _datos, mensaje):
        self.recibidos += 1
        db = SessionLocal()
        try:
            resultado = IoTService.procesar(db, mensaje.topic, mensaje.payload)
        except Exception as exc:  # noqa: BLE001 - un mensaje malo no tumba el receptor
            db.rollback()
            logger.error("No se pudo guardar una lectura",
                         extra={"tema": mensaje.topic, "error": str(exc)})
            return
        finally:
            db.close()

        if resultado["resultado"] != "guardado":
            logger.debug("Lectura descartada",
                         extra={"tema": mensaje.topic, "motivo": resultado.get("motivo")})
            return
        self.guardados += 1
        if resultado.get("alertas"):
            eventos.publicar(resultado.get("sitio_id"), "alertas")
        ahora = time.monotonic()
        if resultado.get("nuevo") or ahora - self._ultimo_aviso >= AVISO_IOT_CADA_S:
            self._ultimo_aviso = ahora
            eventos.publicar(resultado.get("sitio_id"), "iot")

    # -- Bucle ---------------------------------------------------------------
    def correr(self) -> None:
        self.cliente.connect_async(settings.MQTT_HOST, settings.MQTT_PUERTO, keepalive=30)
        self.cliente.loop_forever(retry_first_connection=True)

    def parar(self, *_):
        logger.info("Receptor detenido", extra={"recibidos": self.recibidos,
                                                "guardados": self.guardados})
        self.cliente.disconnect()


def main() -> int:
    setup_logging()
    if not settings.MQTT_PASSWORD:
        logger.error("Falta MQTT_PASSWORD en el .env: el receptor no arranca.")
        # No es un fallo que se arregle reiniciando; esperar evita que Docker
        # lo relance en bucle llenando el registro.
        time.sleep(300)
        return 1
    receptor = Receptor()
    signal.signal(signal.SIGTERM, receptor.parar)
    signal.signal(signal.SIGINT, receptor.parar)
    receptor.correr()
    return 0


if __name__ == "__main__":
    sys.exit(main())

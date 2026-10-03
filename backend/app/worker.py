"""El worker: lo que el portal hace sin que nadie esté esperando la respuesta.

Corre en su propio contenedor (``worker`` en docker-compose) con Arq sobre
Redis:

    arq app.worker.WorkerSettings

**Trabajos que le manda el backend** (``core/tareas.encolar``):

  * ``indexar_ticket`` — al cerrar un ticket, meterlo en la base de
    conocimiento. Es una llamada a Ollama de varios segundos.
  * ``enviar_correo`` — los avisos por SMTP.

**Trabajos programados:**

  * ``vigilar_sla`` — cada minuto. Alerta a TI de los tickets cuyo SLA vence
    en menos de ``SLA_AVISO_MINUTOS`` y de los ya vencidos.
  * ``vigilar_sensores`` — cada 5 minutos. Alerta de los ESP32 que dejaron de
    reportar.
  * ``reindexar_pendientes`` — dos veces por hora. Lo que no se pudo indexar
    al cerrar porque Ollama estaba caído; antes se quedaba así hasta que
    alguien corría el script a mano.
  * ``purgar_lecturas`` — una vez al día, las lecturas más viejas que
    ``IOT_RETENCION_DIAS``.

Todo lo que toca la base es síncrono (SQLAlchemy) y va en ``to_thread`` para no
bloquear el bucle de Arq. Las alertas avisan a las pantallas por Redis.

**El worker no migra.** Lo hace el backend al arrancar; si el worker llega
antes y falta una tabla, el trabajo falla, queda en el registro y la siguiente
pasada —un minuto después— ya la encuentra.
"""

import asyncio
import logging
from typing import Callable

from arq import cron
from arq.connections import RedisSettings

from app.core.config import settings
from app.core.db import SessionLocal
from app.core.logging import logger, setup_logging
from app.models import Ticket
from app.services import eventos_service as eventos
from app.services.alertas_service import AlertasService
from app.services.iot_service import IoTService
from app.services.kb_service import CANALES_AUTOSERVICIO, KBService, solucion_es_valida
from app.services.notificaciones_service import NotificacionesService

#: Cuántos tickets pendientes se indexan por pasada. Cada uno ocupa a Ollama
#: unos segundos; sin tope, una cola de 300 lo tendría ocupado media hora
#: mientras la gente espera al asistente.
REINDEXAR_POR_PASADA = 20


def _con_sesion(funcion: Callable):
    db = SessionLocal()
    try:
        return funcion(db)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Trabajos que manda el backend
# ---------------------------------------------------------------------------

def _indexar(db, ticket_id: int) -> bool:
    ticket = db.get(Ticket, ticket_id)
    if ticket is None or ticket.estado not in ("resuelto", "cerrado") or ticket.indexado_kb:
        return False
    indexado = KBService.indexar_ticket(db, ticket)
    if indexado:
        eventos.publicar(ticket.sitio_id, "tickets")
    return indexado


async def indexar_ticket(ctx, ticket_id: int) -> bool:
    return await asyncio.to_thread(_con_sesion, lambda db: _indexar(db, ticket_id))


async def enviar_correo(ctx, destino: str, asunto: str, cuerpo: str) -> bool:
    return await asyncio.to_thread(NotificacionesService.enviar_ahora, destino, asunto, cuerpo)


# ---------------------------------------------------------------------------
# Trabajos programados
# ---------------------------------------------------------------------------

async def vigilar_sla(ctx) -> dict:
    resultado = await asyncio.to_thread(_con_sesion, AlertasService.vigilar_sla)
    if resultado["abiertas"] or resultado["cerradas"]:
        logger.info("Vigilante del SLA", extra=resultado)
    return resultado


async def vigilar_sensores(ctx) -> int:
    abiertas = await asyncio.to_thread(_con_sesion, IoTService.vigilar_senal)
    if abiertas:
        eventos.publicar(None, "alertas")
        logger.info("Sensores sin señal", extra={"alertas": abiertas})
    return abiertas


def _pendientes(db) -> int:
    pendientes = (db.query(Ticket)
                  .filter(Ticket.estado.in_(("resuelto", "cerrado")),
                          Ticket.indexado_kb.is_(False),
                          Ticket.canal_resolucion.notin_(CANALES_AUTOSERVICIO))
                  .order_by(Ticket.resuelto_en.desc())
                  .limit(REINDEXAR_POR_PASADA).all())
    hechos = 0
    for ticket in pendientes:
        if solucion_es_valida(ticket.solucion) and KBService.indexar_ticket(db, ticket):
            hechos += 1
    return hechos


async def reindexar_pendientes(ctx) -> int:
    hechos = await asyncio.to_thread(_con_sesion, _pendientes)
    if hechos:
        logger.info("Tickets pendientes indexados", extra={"cantidad": hechos})
    return hechos


async def purgar_lecturas(ctx) -> int:
    borradas = await asyncio.to_thread(_con_sesion, IoTService.purgar)
    if borradas:
        logger.info("Lecturas viejas purgadas",
                    extra={"cantidad": borradas, "dias": settings.IOT_RETENCION_DIAS})
    return borradas


async def al_arrancar(ctx) -> None:
    setup_logging()
    # Arq trae su propio manejador de texto y además propaga a la raíz, que
    # ya escribe JSON: cada línea salía dos veces. Se queda solo el JSON,
    # que es lo que lee todo lo demás del portal.
    for manejador in list(logging.getLogger("arq").handlers):
        logging.getLogger("arq").removeHandler(manejador)
    logger.info("Worker en marcha", extra={"redis": settings.REDIS_URL.split("@")[-1]})


class WorkerSettings:
    functions = [indexar_ticket, enviar_correo]
    cron_jobs = [
        cron(vigilar_sla, second=0, run_at_startup=True),
        cron(vigilar_sensores, minute=set(range(0, 60, 5)), second=30),
        cron(reindexar_pendientes, minute={7, 37}),
        # 03:30 hora de planta (UTC-6): nadie está mirando las gráficas.
        cron(purgar_lecturas, hour=9, minute=30),
    ]
    on_startup = al_arrancar
    redis_settings = RedisSettings.from_dsn(settings.REDIS_URL or "redis://redis:6379/0")
    # Ollama atiende de uno en uno (OLLAMA_NUM_PARALLEL=1): más trabajos a la
    # vez solo harían cola allí.
    max_jobs = 4
    # El latido que lee `arq --check` (el healthcheck del contenedor). Con el
    # valor por defecto, una hora, un worker colgado seguía "sano" 60 minutos.
    health_check_interval = 60
    job_timeout = 300
    keep_result = 60
    # Un correo que falla no se reintenta en bucle: queda en el registro.
    max_tries = 3

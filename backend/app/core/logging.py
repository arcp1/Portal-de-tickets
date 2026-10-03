import logging
import json
import sys
from datetime import datetime
from app.core.config import settings

#: Los atributos que `logging` pone en todos los registros. Lo que aparezca
#: fuera de esta lista lo puso quien escribió la llamada, con `extra=`.
#:
#: Se calcula a partir de un registro de verdad en vez de escribir la lista a
#: mano: así no se queda corta si una versión de Python añade atributos —le
#: pasó a `taskName` en la 3.12— y no hay que mantener nada.
_ATRIBUTOS_ESTANDAR = frozenset(
    vars(logging.LogRecord("", 0, "", 0, "", (), None))
) | {"message", "asctime", "taskName"}


class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_obj = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
            "filename": record.filename,
            "lineno": record.lineno,
        }

        # **El contexto de `extra=` va en el registro, no en `record.extra`.**
        #
        # Esto miraba `record.extra`, que **no existe**: `logger.warning(msg,
        # extra={"error": ...})` no crea ese diccionario, copia cada clave
        # como atributo suelto del registro. La condición nunca se cumplía, así
        # que los 79 sitios del portal que pasan contexto lo estaban perdiendo
        # entero: se veía «No se pudo redactar con el modelo local» y nunca el
        # error que lo causó, ni el modelo, ni el tiempo de espera.
        #
        # Justo lo que hace falta para diagnosticar, y justo lo que no llegaba.
        for clave, valor in record.__dict__.items():
            if clave not in _ATRIBUTOS_ESTANDAR and not clave.startswith("_"):
                log_obj[clave] = valor

        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)
        # `default=str` para que un valor que no sabe volverse JSON —una fecha,
        # una excepción— no tire la línea entera del registro. Perder el
        # formato de un dato es molesto; perder el aviso es lo que se estaba
        # arreglando.
        return json.dumps(log_obj, ensure_ascii=False, default=str)

def setup_logging():
    log_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
    logger = logging.getLogger()
    logger.setLevel(log_level)
    
    # Remove existing handlers
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
        
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())
    logger.addHandler(handler)

    # Silence verbose third-party loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

logger = logging.getLogger("portal_tickets")

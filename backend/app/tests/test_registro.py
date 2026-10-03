"""El registro: que lo que se escribe llegue, y con lo que hace falta.

**Por qué esto merece pruebas.** Este portal degrada en silencio a propósito:
si Ollama no contesta se sigue sin él, si Gemini no tiene cuota se sigue sin
él, si una respuesta del modelo sale cortada se descarta. En todos esos casos
el usuario ve algo razonable y **la única señal de que algo va mal es el
registro**. Un registro roto no rompe nada: deja el portal tonto y sin forma de
enterarse.

Se encontraron dos averías ahí, las dos de nacimiento y las dos invisibles:
migrar al arrancar desactivaba el logger entero (ver `test_arranque.py`), y el
formateador tiraba todo el contexto de `extra=`.
"""

import json
import logging

from app.core.logging import JSONFormatter


def _formatear(**kwargs):
    """Una línea de registro como la produciría el portal, ya en JSON."""
    registro = logging.LogRecord(
        name="portal_tickets", level=logging.WARNING, pathname="prueba.py",
        lineno=1, msg=kwargs.pop("msg", "un aviso"), args=(), exc_info=None,
    )
    for clave, valor in kwargs.items():
        setattr(registro, clave, valor)      # es lo que hace `extra=`
    return json.loads(JSONFormatter().format(registro))


def test_el_contexto_de_extra_llega_al_registro():
    """La regresión que hay que impedir.

    El formateador miraba `record.extra`, que **no existe**: `logger.warning(
    msg, extra={...})` no crea ese diccionario, copia cada clave como atributo
    suelto del registro. La condición no se cumplía nunca, así que los 79
    sitios del portal que pasan contexto lo perdían entero.

    Se veía «No se pudo redactar con el modelo local; se sigue sin él» y jamás
    el error que lo causó. Ese mensaje sin su `error` no dice nada accionable:
    ¿estaba caído, se pasó del tiempo, se quedó sin memoria?
    """
    linea = _formatear(msg="No se pudo redactar", error="connection refused",
                       modelo="qwen2.5:3b", timeout=30)
    assert linea["error"] == "connection refused"
    assert linea["modelo"] == "qwen2.5:3b"
    assert linea["timeout"] == 30


def test_los_campos_de_siempre_siguen_estando():
    """El contrapeso: que el contexto entre no puede tapar lo básico."""
    linea = _formatear(msg="algo pasó")
    assert linea["message"] == "algo pasó"
    assert linea["level"] == "WARNING"
    assert linea["logger"] == "portal_tickets"
    assert "timestamp" in linea and linea["timestamp"].endswith("Z")
    # Y nada de la fontanería de `logging` se cuela como si fuera contexto.
    for interno in ("msg", "args", "levelno", "pathname", "created", "thread"):
        assert interno not in linea, f"«{interno}» es de logging, no del aviso"


def test_un_valor_que_no_sabe_volverse_json_no_tira_la_linea():
    """Perder el formato de un dato es molesto; perder el aviso, no vale.

    Una fecha o una excepción en el contexto reventaban `json.dumps`, y con
    ella la línea entera —el aviso incluido—.
    """
    from datetime import datetime

    linea = _formatear(msg="con fecha", cuando=datetime(2026, 9, 17, 12, 0),
                       fallo=ValueError("algo"))
    assert linea["message"] == "con fecha"
    assert "2026-09-17" in linea["cuando"]
    assert "algo" in linea["fallo"]

"""Las comprobaciones que impiden que el portal arranque mal configurado.

**Por qué merecen prueba propia.** Son controles de seguridad que no se ven:
si dejan de ejecutarse, el portal sigue levantando y atendiendo con
normalidad. No hay pantalla en rojo, ni error en el registro, ni ticket. La
única señal de que `revisar_secreto` dejó de correr sería que alguien firmara
un token de administrador con un secreto que está publicado en el repositorio.

Y no las cubría nada: el `TestClient` de `conftest` se usa sin gestor de
contexto, y así **Starlette no ejecuta los manejadores de arranque**. O sea que
en toda la batería estas funciones no llegaban a correr ni una vez. Se prueban
como funciones, que es lo que son, y así la prueba no depende de cómo se
enganchen al ciclo de vida de la aplicación.
"""

import pytest

from app.core.config import settings
from app.main import revisar_base_configurada, revisar_secreto


# ----------------------------------------------------------------------
# El secreto de firma
# ----------------------------------------------------------------------

def test_en_produccion_un_secreto_de_ejemplo_impide_arrancar(monkeypatch):
    """Lo que separa una sesión legítima de una falsificada.

    Los valores de la plantilla los conoce cualquiera que haya visto el
    proyecto, así que valen tanto como no tener secreto. Se prefiere un
    contenedor que no levanta a uno que atiende y firma con eso.
    """
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    for secreto in settings.SECRETOS_PROHIBIDOS:
        monkeypatch.setattr(settings, "JWT_SECRET", secreto)
        with pytest.raises(RuntimeError) as fallo:
            revisar_secreto()
        # El mensaje tiene que decir cómo arreglarlo, no solo que está mal.
        assert "JWT_SECRET" in str(fallo.value)
        assert "token_urlsafe" in str(fallo.value)


def test_fuera_de_produccion_avisa_pero_deja_arrancar(monkeypatch):
    """En desarrollo el mismo secreto no puede bloquear el trabajo.

    Levantar el proyecto por primera vez con el `.env.example` tiene que
    funcionar; el aviso queda en el registro.
    """
    monkeypatch.setattr(settings, "JWT_SECRET", settings.SECRETOS_PROHIBIDOS[0])
    for entorno in ("development", "dev", "local", "test"):
        monkeypatch.setattr(settings, "ENVIRONMENT", entorno)
        revisar_secreto()          # no levanta


def test_un_secreto_propio_pasa_sin_ruido(monkeypatch):
    """El contrapeso: sin esto, la prueba de arriba se cumpliría con una
    función que no dejara arrancar nunca."""
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "JWT_SECRET",
                        "3f9c1a7e5d2b8460af13c7e9b204d85176ea3c9f0b7d4e21")
    revisar_secreto()


# ----------------------------------------------------------------------
# La base de datos
# ----------------------------------------------------------------------

def test_sin_url_de_base_no_arranca(monkeypatch):
    """Es la contraparte de haber quitado la URL por defecto de `config.py`.

    Ahí vivía la contraseña de la base escrita en el repositorio: si el `.env`
    se rompía, el portal seguía levantando contra `localhost` con esa
    credencial conocida. Ahora no levanta, y el mensaje dice qué poner.
    """
    monkeypatch.setattr(settings, "DATABASE_URL", "")
    with pytest.raises(RuntimeError) as fallo:
        revisar_base_configurada()
    assert "DATABASE_URL" in str(fallo.value)


def test_con_url_de_base_arranca(monkeypatch):
    monkeypatch.setattr(settings, "DATABASE_URL",
                        "postgresql://u:p@db:5432/portal_tickets")
    revisar_base_configurada()


# ----------------------------------------------------------------------
# Que estén enganchadas de verdad
# ----------------------------------------------------------------------

def test_las_comprobaciones_corren_al_arrancar_la_aplicacion(monkeypatch):
    """Que la función exista y funcione no sirve si nadie la llama.

    Las pruebas de arriba comprueban las funciones; ésta comprueba el cable.
    Sin ella, mover estas comprobaciones de sitio —de `on_event` a un ciclo de
    vida, por ejemplo— podría dejarlas colgando sin que nada fallara: el portal
    seguiría levantando, sólo que sin revisar el secreto con el que firma.

    Hay que usar el `TestClient` **como gestor de contexto**; si no, Starlette
    no ejecuta el arranque. Es justo lo que hace el `client` de `conftest`, y
    por eso allí estas funciones no llegan a correr.
    """
    from fastapi.testclient import TestClient
    from app.main import app

    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "JWT_SECRET", settings.SECRETOS_PROHIBIDOS[0])

    with pytest.raises(RuntimeError) as fallo:
        with TestClient(app):
            pass
    assert "JWT_SECRET" in str(fallo.value)


def test_al_arrancar_el_difusor_recibe_su_bucle():
    """El otro manejador de arranque, que no falla: reparte el bucle.

    `publicar()` entrega los avisos desde hilos del *pool*, así que necesita el
    bucle de la aplicación. Sin él no hay error: los avisos se pierden en
    silencio y el tablero deja de refrescarse solo, que es como se descubrió.
    """
    from fastapi.testclient import TestClient
    from app.main import app
    from app.services.eventos_service import difusor
    from app.services.traza_service import difusor_traza

    with TestClient(app):
        assert difusor._bucle is not None, "el difusor de eventos se quedó sin bucle"
        assert difusor_traza._bucle is not None, "el difusor de la traza se quedó sin bucle"


# ----------------------------------------------------------------------
# El arranque no puede dejar mudo al portal
# ----------------------------------------------------------------------

def test_migrar_al_arrancar_no_desactiva_el_registro():
    """La regresión más cara de todas las que se han encontrado aquí.

    `alembic/env.py` llama a `fileConfig(alembic.ini)`, y `fileConfig`
    **desactiva por defecto todo logger que no esté declarado en ese .ini**.
    Como el arranque aplica las migraciones dentro del mismo proceso que luego
    atiende el portal, `portal_tickets` quedaba con `disabled = True` para el
    resto de la vida del proceso.

    El síntoma era casi invisible: «Aplicando migraciones…» se veía en el log y
    «Esquema al día», tres líneas después y del mismo logger, ya no. A partir
    de ahí ni un `logger.warning` ni un `logger.error` de la aplicación llegaba
    a ninguna parte.

    Lo que lo vuelve caro es **de qué** deja sin señal. Este portal degrada en
    silencio a propósito: si Ollama no contesta se sigue sin él, si Gemini no
    tiene cuota se sigue sin él, si una respuesta sale cortada se descarta. En
    todos esos casos el usuario ve algo razonable y lo único que decía que algo
    va mal era el registro. Sin él, el portal no se rompe: se queda tonto, y no
    hay forma de enterarse.
    """
    import logging
    from fastapi.testclient import TestClient
    from app.core.logging import logger
    from app.main import app

    with TestClient(app):
        assert not logger.disabled, (
            "el arranque dejó `portal_tickets` desactivado: la aplicación "
            "corre sin registro y sus avisos de degradación no llegan a nadie"
        )
        assert logger.isEnabledFor(logging.WARNING), (
            "`portal_tickets` no deja pasar los avisos"
        )
        # Los de uvicorn también: sin ellos no hay ni registro de acceso.
        assert not logging.getLogger("uvicorn.error").disabled
        assert not logging.getLogger("uvicorn.access").disabled


# ----------------------------------------------------------------------
# La documentación interactiva del API
# ----------------------------------------------------------------------

@pytest.mark.parametrize("entorno, activa", [
    ("development", True), ("desarrollo", True), (" Dev ", True), ("local", True),
    ("production", False), ("produccion", False), ("test", False), ("", False),
    (None, False),   # sin la variable: cerrada, aunque ENVIRONMENT tenga un valor por defecto
])
def test_la_documentacion_solo_se_abre_en_desarrollo(entorno, activa):
    """Swagger y el esquema son el plano entero del sistema, sin pedir sesión."""
    from app.core.config import documentacion_api_activa
    assert documentacion_api_activa(entorno) is activa


@pytest.mark.parametrize("ruta", ["/docs", "/redoc", "/openapi.json"])
def test_las_rutas_de_documentacion_siguen_al_entorno(client, ruta):
    """Lo que de verdad sirve la aplicación, con el entorno con que arrancó."""
    r = client.get(ruta)
    if settings.DOCUMENTACION_API:
        assert r.status_code == 200
    else:
        assert r.status_code == 404
        assert "openapi" not in r.text.lower()

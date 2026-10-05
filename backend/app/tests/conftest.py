import os

# **Nunca la Redis de producción.** Las pruebas corren dentro del contenedor
# del backend, que trae REDIS_URL del .env: sin esto, los frenos de login de
# las pruebas —cuentas 1 y 2— se anotarían en los de las cuentas reales.
os.environ["REDIS_URL"] = ""
# **Ni la base de producción.** Por lo mismo: el `DATABASE_URL` del contenedor
# es el real. Las pruebas usan SQLite (`get_db` sustituido); lo que se salte
# esa puerta —el arranque que migra, un `SessionLocal()` suelto en una tarea de
# fondo— tiene que fallar contra una dirección que no existe, no escribir en
# producción. Y el arranque migra en modo "sql": recorre las migraciones —y el
# `fileConfig` de env.py, que es lo que vigila test_arranque— sin conectarse.
os.environ["DATABASE_URL"] = "postgresql://pruebas:pruebas@127.0.0.1:9/sin_base"
os.environ["MIGRAR_AL_ARRANCAR"] = "sql"

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.core.db import Base, get_db
from app.main import app
from app.core.security import get_password_hash
from app.models import Sitio, Usuario

SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"


@pytest.fixture(autouse=True)
def limitadores_limpios():
    """Cada prueba arranca con los contadores de intentos en cero.

    Los limitadores son objetos de modulo: viven mientras viva el proceso, asi
    que sin esto los intentos de una prueba se le cargan a la siguiente y el
    resultado depende del orden en que corran los archivos. Se noto al juntar
    test_seguridad.py con test_cuentas.py: por separado pasaban los dos, juntos
    caian 28. Una suite de seguridad que cambia de veredicto segun el orden no
    sirve para lo que existe.
    """
    from app.core.limitador import (
        limitador_activacion, limitador_activacion_ip, limitador_ia, limitador_login,
        limitador_login_ip,
    )

    for limitador in (limitador_login, limitador_login_ip,
                      limitador_activacion, limitador_activacion_ip, limitador_ia):
        with limitador._candado:
            limitador._intentos.clear()
    yield


@pytest.fixture(autouse=True)
def sin_vectores_heredados():
    """Cada prueba arranca sin vectores recordados de la anterior.

    Mismo motivo que los limitadores de arriba: el cliente de Ollama es un
    objeto de módulo y su caché vive mientras viva el proceso. Sin esto, una
    prueba que vectorice "la impresora saca una raya negra" le deja el
    resultado servido a la siguiente, y la que comprueba que **no** se
    vectoriza —porque la compuerta está cerrada, o porque Ollama está
    caído— pasaría o fallaría según el orden en que corran los archivos.
    """
    from app.services.ollama_client import ollama

    ollama.olvidar_vectores()
    yield
    ollama.olvidar_vectores()


@pytest.fixture(autouse=True)
def archivos_en_carpeta_temporal(monkeypatch, tmp_path):
    """Lo que las pruebas suben se queda en una carpeta suya.

    La suite corre dentro del contenedor del backend, y ahí `/app/adjuntos`
    es el volumen de producción. Cada prueba que subía un archivo tenía que
    acordarse de cambiar la ruta; una que no se acordó dejó tres PNG de prueba
    entre las fotos reales, sin fila en la base que los explicara. Las que
    cambian la ruta por su cuenta siguen funcionando: su `monkeypatch` va
    después de éste.
    """
    monkeypatch.setattr(settings, "ADJUNTOS_RUTA", str(tmp_path / "adjuntos"))
    monkeypatch.setattr(settings, "VISUAL_RUTA", str(tmp_path / "adjuntos" / "visual"))
    monkeypatch.setattr(settings, "DOCUMENTOS_RUTA", str(tmp_path / "documentos"))


@pytest.fixture(autouse=True)
def ia_desactivada_por_defecto(monkeypatch):
    """La suite no toca la red, y ahora de verdad.

    Antes esto solo apagaba `IA_HABILITADA`, y el comentario afirmaba algo que
    no era cierto: **Gemini se manda por otra bandera**, `GEMINI_HABILITADO`,
    así que seguía vivo. El resultado fue una prueba que salía a internet de
    verdad —a la API de pago, y dejando la llave en claro en su log capturado—
    sin que nadie lo notara hasta que empezó a fallar.

    La garantía no se pone apagando banderas —se intentó, y deja fuera de
    juego a las ocho pruebas que sí ejercitan Gemini con dobles—, sino
    **cortando el transporte real de httpx**. Ese corte es lo que convierte el
    problema en visible: una prueba que se escape ya no cuelga, ni gasta
    cuota, ni filtra nada; revienta en el sitio y dice qué URL intentó abrir.
    Se bloquea `HTTPTransport`, que es el que abre sockets, y no
    `httpx.Client`: el `TestClient` de FastAPI también es httpx, pero va por
    un transporte ASGI en memoria y tiene que seguir funcionando.

    Las pruebas que necesitan ejercitar la degradación de Ollama vuelven a
    activarla apuntando a un host muerto (ver test_ia_nunca_bloquea.py), y esas
    llegan aquí igual: el fallo del transporte es la caída que quieren probar.
    """
    monkeypatch.setattr(settings, "IA_HABILITADA", False)

    def sin_red(self, peticion, *args, **kwargs):
        raise httpx.ConnectError(
            "La suite no sale a la red. Alguien intentó abrir %s: "
            "sustituya esa llamada en la prueba." % peticion.url
        )

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", sin_red)

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@event.listens_for(engine, "connect")
def _llaves_foraneas(conexion, _registro):
    """SQLite ignora las llaves foráneas si no se le pide lo contrario.

    Sin esto la suite no veía lo que Postgres sí rechaza: borrar una entrada de
    la base de conocimiento que ya se le había sugerido a alguien pasaba en
    verde aquí y en producción respondía 409 —"choca con datos ya
    registrados"— sin que nadie entendiera por qué.
    """
    cursor = conexion.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()

def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "terminos_pendientes: las cuentas que cree la prueba nacen sin los Términos aceptados",
    )


@pytest.fixture(autouse=True)
def terminos_aceptados_por_omision(request):
    """Toda cuenta que crea una prueba nace con los Términos y Condiciones
    vigentes aceptados, salvo en las pruebas marcadas `terminos_pendientes`.

    Sin esto, desde que la API exige la aceptación (api/deps.py) cada prueba
    que usa una sesión recibiría 403: la regla se prueba en test_terminos.py,
    y el resto de la suite sigue probando lo suyo como antes. Va con un oyente
    de SQLAlchemy y no en el `db_session` porque muchas cuentas no se crean
    ahí: las dan de alta las propias pruebas, por la API o la importación.
    """
    if request.node.get_closest_marker("terminos_pendientes"):
        yield
        return
    from datetime import datetime
    from app.core import terminos

    def aceptar(_mapper, _conexion, usuario):
        if usuario.terminos_version is None:
            usuario.terminos_version = terminos.version_vigente()
            usuario.terminos_aceptados_en = datetime.utcnow()

    event.listen(Usuario, "before_insert", aceptar)
    yield
    event.remove(Usuario, "before_insert", aceptar)


@pytest.fixture(scope="function")
def db_session():
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    
    # Create seed site
    site = Sitio(clave="QRO", nombre="Planta Querétaro", pais="México", activo=True)
    db.add(site)
    db.commit()
    db.refresh(site)

    # TI es global: sin planta, como lo deja la migración 0025.
    admin = Usuario(
        sitio_id=None,
        nombre="Admin Test",
        email="admin@test.com",
        numero_empleado="1001",
        password_hash=get_password_hash("Secret123!"),
        rol="admin",
        activo=True,
        estado_cuenta="activa"
    )
    # Create user
    user = Usuario(
        sitio_id=site.id,
        nombre="User Test",
        email="user@test.com",
        numero_empleado="1002",
        password_hash=get_password_hash("Secret123!"),
        rol="usuario",
        activo=True,
        estado_cuenta="activa"
    )
    user.plantas = [site]
    db.add_all([admin, user])
    db.commit()

    try:
        yield db
    finally:
        db.close()
        # SQLite borra cada tabla con un DELETE implícito, y una llave
        # `ON DELETE RESTRICT` —las carpetas del directorio, que cuelgan unas
        # de otras— lo rechaza a mitad si quedaron filas. Las llaves se
        # apagan solo para tirar las tablas; fuera de un BEGIN, que es donde
        # SQLite admite el PRAGMA.
        with engine.connect() as conexion:
            conexion.exec_driver_sql("PRAGMA foreign_keys=OFF")
            Base.metadata.drop_all(bind=conexion)
            conexion.commit()
            conexion.exec_driver_sql("PRAGMA foreign_keys=ON")

@pytest.fixture(scope="function")
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def otra_planta(db_session):
    """Una segunda planta de verdad, para las pruebas de "no cruza de sitio".

    Antes se usaba `sitio_id=999`, que no existe: con las llaves foráneas
    apagadas pasaba, y la prueba demostraba el aislamiento con datos que la
    base real nunca aceptaría.
    """
    sitio = Sitio(clave="MTY", nombre="Planta Monterrey", pais="México", activo=True)
    db_session.add(sitio)
    db_session.commit()
    db_session.refresh(sitio)
    return sitio

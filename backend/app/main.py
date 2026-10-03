import asyncio
import io
from contextlib import asynccontextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from app.core.config import settings
from app.core.limite_cuerpo import LimiteDeCuerpo
from app.core.token_renovado import EntregaTokenRenovado
from app.core.errores import registrar_manejadores
from app.services.eventos_service import difusor
from app.core import tareas
from app.services.traza_service import difusor_traza
from app.core.logging import setup_logging, logger
from app.core.db import engine
from app.api.router import api_router

# Initialize JSON logging
setup_logging()

@asynccontextmanager
async def ciclo_de_vida(app: FastAPI):
    """Lo que hay que comprobar y preparar antes de atender la primera petición.

    **Por qué aquí y no con `@app.on_event("startup")`.** Ese decorador está
    deprecado y FastAPI lo quitará; el día que lo haga, estas cuatro
    comprobaciones dejarían de correr **sin que nada fallara**: el portal
    seguiría levantando, sólo que sin revisar el secreto con el que firma las
    sesiones. Un ciclo de vida explícito no puede quedarse colgando: si no está
    enganchado, la aplicación no arranca.

    **El orden es el que era, y es deliberado.** Primero se comprueba la
    configuración —secreto y base—, porque si algo de eso está mal no tiene
    sentido migrar nada; después se reparte el bucle a los difusores; y al final
    las migraciones, que son lo caro. Las funciones siguen siendo funciones
    sueltas y con nombre, así que se pueden probar una a una sin levantar la
    aplicación: `app/tests/test_arranque.py`.
    """
    revisar_secreto()
    revisar_algoritmo_jwt()
    revisar_base_configurada()
    await startup_eventos()
    startup_db()
    # Con Redis: el oyente que trae los avisos del worker y del receptor de
    # sensores, y la conexión a la cola de tareas. Sin Redis no hacen nada.
    oyente = asyncio.create_task(difusor.escuchar())
    await tareas.iniciar(asyncio.get_running_loop())
    yield
    oyente.cancel()
    await tareas.cerrar()
    # Lo demás no se cierra: el motor de SQLAlchemy y los difusores viven lo
    # que viva el proceso, y las conexiones las devuelve cada dependencia.


app = FastAPI(
    lifespan=ciclo_de_vida,
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    # Cerrados en producción: ver `documentacion_api_activa` en core/config.py.
    # Sin esquema tampoco hay Swagger ni ReDoc, pero se apagan los tres a la
    # vista para que nadie tenga que saberlo.
    openapi_url="/openapi.json" if settings.DOCUMENTACION_API else None,
    docs_url="/docs" if settings.DOCUMENTACION_API else None,
    redoc_url="/redoc" if settings.DOCUMENTACION_API else None,
)

# CORS.
#
# El portal se sirve desde el mismo origen que la API (NGINX pone las dos cosas
# detras del mismo host), asi que el navegador no necesita CORS para nada. La
# lista abierta `["*"]` con `allow_credentials=True` ademas es contradictoria:
# el propio estandar la prohibe y los navegadores la rechazan.
#
# Se deja solo lo que de verdad se usa: el Vite de desarrollo en el puerto 3000
# y los origenes que se declaren en ORIGENES_PERMITIDOS del .env (por ejemplo
# la URL publica de Tailscale Funnel).
_origenes = [o.strip() for o in settings.ORIGENES_PERMITIDOS.split(",") if o.strip()]

# Antes que CORS, para que CORS la envuelva y también el 413 lleve sus
# cabeceras. Ver core/limite_cuerpo.py.
app.add_middleware(LimiteDeCuerpo, maximo_bytes=settings.CUERPO_JSON_MAX_KB * 1024)
app.add_middleware(EntregaTokenRenovado)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origenes,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # Sin esto el navegador esconde la cabecera a un origen cruzado —el Vite
    # de desarrollo— y la sesión caducaría ahí aunque se estuviera usando.
    expose_headers=["X-Token-Renovado", "X-Enlace-QR"],
)

# Todo error sale con la misma forma: ver app/core/errores.py.
registrar_manejadores(app)

def revisar_secreto():
    """El portal no arranca en producción con el secreto de desarrollo puesto.

    `JWT_SECRET` es lo único que separa una sesión legítima de una falsificada:
    quien lo conozca se firma un token de administrador. Los valores de la
    plantilla del repositorio los conoce cualquiera que haya visto el proyecto,
    así que valen tanto como no tener secreto.

    Se falla ruidosamente en vez de arrancar inseguro y en silencio, que es como
    estas cosas llegan a producción y ahí se quedan.
    """
    if settings.JWT_SECRET not in settings.SECRETOS_PROHIBIDOS:
        return

    mensaje = (
        "JWT_SECRET tiene un valor de ejemplo, conocido por cualquiera que haya "
        "visto el repositorio. Genere uno con:\n"
        "    python -c \"import secrets; print(secrets.token_urlsafe(48))\"\n"
        "y póngalo en el .env. Al cambiarlo se cierran las sesiones abiertas."
    )

    if settings.ENVIRONMENT.lower() in ("development", "dev", "local", "test"):
        logger.warning("INSEGURO: " + mensaje.replace("\n", " "))
        return

    raise RuntimeError(mensaje)


#: Los únicos que tienen sentido con un secreto compartido.
ALGORITMOS_JWT = ("HS256", "HS384", "HS512")


def revisar_algoritmo_jwt():
    """`JWT_ALGORITHM` sale del .env, y un valor raro no falla: cambia la regla.

    Con `none` un token sin firma sería válido; con uno asimétrico (`RS256`)
    el secreto se usaría como si fuera una llave pública. Ninguno de los dos se
    pide nunca a propósito, así que el portal no arranca con ellos en vez de
    arrancar confiando en tokens que cualquiera fabrica.
    """
    if settings.JWT_ALGORITHM not in ALGORITMOS_JWT:
        raise RuntimeError(
            f"JWT_ALGORITHM={settings.JWT_ALGORITHM!r} no es válido. "
            f"Use uno de: {', '.join(ALGORITMOS_JWT)} (lo normal es HS256)."
        )


def revisar_base_configurada():
    """Sin DATABASE_URL el portal no arranca, y se dice por que.

    Es la contraparte de haber quitado la URL por defecto de `config.py`: ahi
    vivia la contrasena de la base, escrita en el repositorio, y si el .env se
    rompia el portal seguia levantando contra `localhost` con esa credencial
    conocida. Preferimos un contenedor que no levanta a uno que atiende con la
    base equivocada.
    """
    if not settings.DATABASE_URL:
        raise RuntimeError(
            "Falta DATABASE_URL. Poner en el .env, por ejemplo:\n"
            "    DATABASE_URL=postgresql://cgr_user:<contrasena>@db:5432/portal_tickets\n"
            "Si la contrasena lleva caracteres como @ / * hay que escribirlos "
            "codificados (%40, %2F, %2A)."
        )


async def startup_eventos():
    """Le da al difusor el bucle de eventos en el que corre la aplicación.

    Tiene que ser `async def`: los manejadores síncronos de arranque los
    ejecuta Starlette en un hilo del *pool*, y ahí no hay bucle que capturar.
    Sin esta referencia, `publicar()` no tiene a dónde entregar y los avisos
    se pierden en silencio, que es la peor forma de fallar.

    El difusor de la traza —el que alimenta el grafo— necesita lo mismo y por
    la misma razón: los pasos se publican desde hilos del *pool*, así que hace
    falta un bucle al que entregárselos.
    """
    bucle = asyncio.get_running_loop()
    difusor.iniciar(bucle)
    difusor_traza.iniciar(bucle)


def startup_db():
    """Pone el esquema al día con Alembic.

    Antes esto llamaba a ``Base.metadata.create_all()``, que creaba las tablas
    faltantes pero **no** agregaba columnas nuevas a tablas existentes. Eso
    dejaba dos fuentes de verdad compitiendo y ya causó una falla real: una
    migración no se aplicó y el arranque quedó con el esquema a medias.

    Ahora Alembic manda. Si las migraciones fallan, la aplicación **no arranca**:
    es preferible un contenedor que no levanta a uno que atiende peticiones
    contra un esquema equivocado y corrompe datos.
    """
    modo = (settings.MIGRAR_AL_ARRANCAR or "si").strip().lower()
    if modo == "no":
        logger.info("Migraciones al arrancar desactivadas (MIGRAR_AL_ARRANCAR=no).")
        return
    # "sql": recorre todas las migraciones generando el SQL **sin conectarse**
    # a nada. Es el modo de la suite de pruebas, que corre dentro del mismo
    # contenedor que producción y hereda su DATABASE_URL: con el modo normal,
    # cada `with TestClient(app)` migraba la base real —así se aplicaron la
    # 0025 y la 0026 en producción el 2026-10-02, antes de desplegar el código
    # que las necesitaba—.
    fuera_de_linea = modo == "sql"
    logger.info("Aplicando migraciones de base de datos...")

    try:
        if fuera_de_linea:
            raise RuntimeError("modo sin conexión")
        with engine.connect() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
            conn.commit()
    except Exception as exc:  # noqa: BLE001
        # pgvector puede no estar en un Postgres genérico; la migración lo
        # vuelve a intentar y ahí sí es determinante.
        logger.warning(f"No se pudo crear la extensión vector todavía: {exc}")

    config = Config(str(Path(__file__).resolve().parent.parent / "alembic.ini"),
                    output_buffer=io.StringIO())
    config.set_main_option("script_location", str(Path(__file__).resolve().parent.parent / "alembic"))
    # El `%` se duplica porque el .ini de Alembic lo lee un ConfigParser, y ahi
    # `%` es sintaxis de interpolacion. Una contrasena con caracteres especiales
    # llega URL-codificada (`@` -> `%40`) y el arranque reventaba con
    # "invalid interpolation syntax". Escaparlo es la forma soportada.
    config.set_main_option("sqlalchemy.url", settings.DATABASE_URL.replace("%", "%%"))
    # **Que Alembic no reconfigure el logging de este proceso.**
    #
    # `env.py` llama a `fileConfig(alembic.ini)`, y eso hace dos cosas malas
    # aquí: desactiva todo logger no declarado en ese .ini —`portal_tickets`
    # entre ellos, que se quedaba mudo para el resto de la vida del proceso— y
    # le cambia a la raíz el manejador JSON por el de texto plano de Alembic.
    #
    # Migrar desde la línea de comandos sigue teniendo su logging: la bandera
    # solo la pone quien migra desde dentro de la aplicación.
    config.attributes["configurar_logging"] = False
    if fuera_de_linea:
        # De "head" a "head": pasa por env.py —y su `fileConfig`, que es lo que
        # vigila test_arranque— sin ejecutar ninguna migración. Varias
        # inspeccionan la base para decidir y no se pueden recorrer sin ella.
        command.upgrade(config, "head:head", sql=True)
    else:
        command.upgrade(config, "head")

    logger.info("Esquema de base de datos al día.")

app.include_router(api_router)

@app.get("/")
def root():
    return {
        "status": "online",
        "app": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "docs": "/docs"
    }

@app.get("/health")
def health_check():
    return {"status": "healthy"}

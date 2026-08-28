from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from app.core.config import settings
from app.core.logging import setup_logging, logger
from app.core.db import engine
from app.api.router import api_router

# Initialize JSON logging
setup_logging()

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    openapi_url="/openapi.json",
    docs_url="/docs"
)

# Set CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
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


@app.on_event("startup")
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
    logger.info("Aplicando migraciones de base de datos...")

    try:
        with engine.connect() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
            conn.commit()
    except Exception as exc:  # noqa: BLE001
        # pgvector puede no estar en un Postgres genérico; la migración lo
        # vuelve a intentar y ahí sí es determinante.
        logger.warning(f"No se pudo crear la extensión vector todavía: {exc}")

    config = Config(str(Path(__file__).resolve().parent.parent / "alembic.ini"))
    config.set_main_option("script_location", str(Path(__file__).resolve().parent.parent / "alembic"))
    config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)
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

from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context
from app.core.config import settings
from app.core.db import Base
from app.models import *

config = context.config
# Mismo escape que en app/main.py: el ConfigParser del .ini trata `%` como
# interpolacion, y una contrasena URL-codificada lo trae.
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL.replace("%", "%%"))

# `config.attributes` es el canal que Alembic ofrece para que quien lo invoca
# por API le diga cosas a este archivo. `main.py` pone esta bandera en False
# porque la aplicación ya configuró su propio logging —JSON, a stdout— y no
# quiere que nadie se lo cambie a media vida.
if config.attributes.get("configurar_logging", True) and config.config_file_name:
    # **`disable_existing_loggers=False` no es un detalle: sin él, el portal se
    # queda mudo.**
    #
    # `fileConfig` desactiva por defecto todo logger que no esté declarado en
    # el .ini, y `alembic.ini` solo declara `root`, `sqlalchemy` y `alembic`.
    # Como `main.py` aplica las migraciones **dentro del proceso** que luego
    # atiende el portal, esta línea corría en cada arranque y dejaba
    # `portal_tickets` —y los de uvicorn— con `disabled = True` para el resto
    # de la vida del proceso.
    #
    # El efecto medido: «Aplicando migraciones…» se veía y «Esquema al día»,
    # tres líneas después y del mismo logger, ya no. A partir de ahí, ni un
    # `logger.warning` ni un `logger.error` de la aplicación llegaba a ninguna
    # parte. Este proyecto degrada en silencio a propósito —Ollama caído,
    # Gemini sin cuota, una respuesta cortada— y **el registro era la única
    # señal de que eso estaba pasando**. Llevaba sin funcionar desde siempre.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata

def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

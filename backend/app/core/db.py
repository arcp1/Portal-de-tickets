from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from app.core.config import settings

# Sin DATABASE_URL no se inventa una conexion.
#
# Antes `config.py` traia por defecto una URL con la contrasena escrita dentro,
# o sea publicada en el repositorio, y ademas hacia que un .env roto pasara
# desapercibido: el portal arrancaba contra `localhost` con una credencial
# conocida en vez de avisar.
#
# Ahora, si falta, se construye un motor de mentira que no apunta a ningun dato
# real —hace falta uno para poder importar el modulo— y `main.py` se niega a
# arrancar. Las pruebas importan igual porque sustituyen `get_db` por el suyo.
_SIN_CONFIGURAR = "sqlite://"

if settings.DATABASE_URL:
    engine = create_engine(
        settings.DATABASE_URL,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
    )
else:
    engine = create_engine(_SIN_CONFIGURAR)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

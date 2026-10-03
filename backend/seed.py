"""Arranque de una instalación nueva: la planta y su primer administrador.

**Nada más, a propósito.** Hasta septiembre de 2026 esto también plantaba tres
equipos de ejemplo —una laptop HP, una impresora Zebra y un switch Cisco—, un
operador ficticio ("Juan Pérez") con la laptop a su nombre, cinco pasos de
checklist y una regla que mandaba las fallas de impresora a
`soporte@zebra-mexico.com`. Todo se escribía en la base de verdad, así que el
inventario de producción enseñaba equipos que no existen y la regla esperaba a
que alguien configurara el correo para empezar a mandarle tickets de la planta
a una dirección que nadie eligió.

Lo que el portal necesita para arrancar es una planta y alguien que la
administre. Lo demás lo da de alta TI desde el portal:

  - Equipos: Inventario → Registrar equipo.
  - Personas: Personas → Dar de alta, o Importar personal.
  - Reglas: Reglas de negocio.
  - Pasos de diagnóstico y conocimiento de arranque: `seed_temas.py`, que es
    contenido escrito para la planta, no datos de ejemplo.

Los datos salen del entorno (ver `.env.example`, sección "Siembra"). Correrlo
dos veces no duplica nada ni toca lo que ya existe.
"""

import os
import secrets

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.db import SessionLocal, Base, engine
from app.core.logging import logger
from app.core.security import get_password_hash
from app.models import Sitio, Usuario
from app.services.cuentas_service import validar_password


def _password_de_siembra(variable: str) -> str:
    """Contrasena inicial de una cuenta sembrada.

    Sale de la variable de entorno indicada. Si no esta puesta se **genera una
    al azar y se imprime una sola vez**, en vez de plantar una escrita en el
    repositorio.

    El motivo: las que habia —"Admin123!", "User123!"— estan en el codigo, o
    sea que las conoce cualquiera que haya visto el proyecto, y ademas ni
    siquiera cumplian la politica del propio portal (nueve caracteres contra un
    minimo de diez), porque la siembra escribia el hash sin pasar por
    `validar_password`. En un portal que da a internet eso es una cuenta de
    administrador regalada.
    """
    valor = os.getenv(variable)
    if valor:
        problema = validar_password(valor)
        if problema:
            raise SystemExit(f"{variable}: {problema}")
        return valor

    generada = secrets.token_urlsafe(15)
    print(f"  [siembra] {variable} no estaba puesta. Contrasena generada: {generada}")
    print("  [siembra] Anotela ahora: no se vuelve a mostrar y no queda en ningun lado.")
    return generada


def _entorno(variable: str, reserva: str = "") -> str:
    return (os.getenv(variable) or reserva).strip()


def seed_db():
    logger.info("Starting database seeding...")
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
        conn.commit()
    Base.metadata.create_all(bind=engine)
    db: Session = SessionLocal()

    try:
        # 1. La planta. La clave va en los folios (TICK-QRO-2026-0001), así
        #    que conviene no cambiarla una vez que haya tickets.
        clave = _entorno("SEED_SITIO_CLAVE", "QRO").upper()
        site = db.query(Sitio).filter(Sitio.clave == clave).first()
        if not site:
            site = Sitio(
                clave=clave,
                nombre=_entorno("SEED_SITIO_NOMBRE", "Planta Querétaro"),
                pais=_entorno("SEED_SITIO_PAIS", "México"),
                activo=True,
            )
            db.add(site)
            db.commit()
            db.refresh(site)
            logger.info(f"Created site: {site.nombre}")

        # 2. El primer administrador. Se le reconoce por su número de
        #    empleado, que es con lo que entra.
        numero = _entorno("SEED_ADMIN_NUMERO", "10001")
        admin_user = db.query(Usuario).filter(Usuario.numero_empleado == numero).first()
        if not admin_user:
            admin_user = Usuario(
                sitio_id=site.id,
                nombre=_entorno("SEED_ADMIN_NOMBRE", "Administrador de TI"),
                # Opcional, como en cualquier alta: sin correo entra con su número.
                email=_entorno("SEED_ADMIN_EMAIL").lower() or None,
                numero_empleado=numero,
                password_hash=get_password_hash(_password_de_siembra("SEED_ADMIN_PASSWORD")),
                estado_cuenta="activa",
                rol="admin",
                area="Sistemas / TI",
                idioma_preferido="es",
                activo=True
            )
            db.add(admin_user)
            db.commit()
            db.refresh(admin_user)
            logger.info(f"Created admin user: {admin_user.numero_empleado}")
        else:
            # **No se toca la contraseña de una cuenta que ya existe.**
            #
            # Antes cada corrida la reponía a la del repositorio. En un portal
            # que ya está en uso eso es un secuestro de cuenta con una sola
            # orden: quien pudiera lanzar la semilla se quedaba con el admin, y
            # el dueño legítimo perdía la suya sin enterarse.
            logger.info("El admin ya existe: no se toca su contraseña")

        logger.info("Database seeding completed successfully.")

    except Exception as e:
        logger.error(f"Error during database seed: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    seed_db()

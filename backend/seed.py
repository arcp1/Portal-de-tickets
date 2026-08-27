from sqlalchemy import text
from sqlalchemy.orm import Session
from app.core.db import SessionLocal, Base, engine
from app.core.security import get_password_hash
from app.models import Sitio, Usuario, Equipo, Checklist, ReglaNegocio
from app.core.logging import logger

def seed_db():
    logger.info("Starting database seeding...")
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
        conn.commit()
    Base.metadata.create_all(bind=engine)
    db: Session = SessionLocal()

    try:
        # 1. Create default Site
        site = db.query(Sitio).filter(Sitio.clave == "QRO").first()
        if not site:
            site = Sitio(
                clave="QRO",
                nombre="Planta Querétaro",
                pais="México",
                activo=True
            )
            db.add(site)
            db.commit()
            db.refresh(site)
            logger.info(f"Created site: {site.nombre}")

        # 2. Create Admin & Standard Users
        admin_user = db.query(Usuario).filter(Usuario.email == "admin@cgr.mx").first()
        if not admin_user:
            admin_user = Usuario(
                sitio_id=site.id,
                nombre="Alex Ríos Carballo (IT Admin)",
                email="admin@cgr.mx",
                numero_empleado="10001",
                password_hash=get_password_hash("Admin123!"),
                estado_cuenta="activa",
                rol="admin",
                area="Sistemas / TI",
                idioma_preferido="es",
                activo=True
            )
            db.add(admin_user)
            db.commit()
            db.refresh(admin_user)
            logger.info(f"Created admin user: {admin_user.email}")
        else:
            admin_user.password_hash = get_password_hash("Admin123!")
            # La migración 0008 dejó un número provisional TMP-xxxxx en las
            # cuentas que ya existían. La semilla corrige las suyas.
            if not admin_user.numero_empleado or admin_user.numero_empleado.startswith("TMP-"):
                admin_user.numero_empleado = "10001"
            db.commit()
            logger.info("Updated admin password hash")

        normal_user = db.query(Usuario).filter(Usuario.email == "operador@cgr.mx").first()
        if not normal_user:
            normal_user = Usuario(
                sitio_id=site.id,
                nombre="Juan Pérez (Operador)",
                email="operador@cgr.mx",
                numero_empleado="10002",
                password_hash=get_password_hash("User123!"),
                estado_cuenta="activa",
                rol="usuario",
                area="Producción",
                idioma_preferido="es",
                activo=True
            )
            db.add(normal_user)
            db.commit()
            db.refresh(normal_user)
            logger.info(f"Created standard user: {normal_user.email}")
        else:
            normal_user.password_hash = get_password_hash("User123!")
            if not normal_user.numero_empleado or normal_user.numero_empleado.startswith("TMP-"):
                normal_user.numero_empleado = "10002"
            db.commit()
            logger.info("Updated standard user password hash")

        # 3. Create Sample Equipment
        if db.query(Equipo).count() == 0:
            equipos_data = [
                Equipo(
                    sitio_id=site.id,
                    tipo="activo",
                    categoria="Laptop",
                    marca="HP",
                    modelo="ProBook 440 G8",
                    numero_serie="HP-QRO-9941",
                    ubicacion="Línea 1 - Ensamble",
                    estado="asignado",
                    asignado_a=normal_user.id,
                    notas="Laptop de planta para control de calidad"
                ),
                Equipo(
                    sitio_id=site.id,
                    tipo="activo",
                    categoria="Impresora",
                    marca="Zebra",
                    modelo="ZT230 Industrial",
                    numero_serie="ZEB-QRO-3301",
                    ubicacion="Almacén de Embarques",
                    estado="disponible",
                    notas="Impresora de etiquetas con soporte directo de fábrica"
                ),
                Equipo(
                    sitio_id=site.id,
                    tipo="pasivo",
                    categoria="Red",
                    marca="Cisco",
                    modelo="Catalyst 2960",
                    numero_serie="CIS-QRO-1022",
                    ubicacion="IDC Principal",
                    estado="disponible",
                    notas="Switch de distribución de planta"
                )
            ]
            db.add_all(equipos_data)
            db.commit()
            logger.info("Created initial equipment items.")

        # 4. Create Checklists by Category
        if db.query(Checklist).count() == 0:
            checklists = [
                Checklist(
                    categoria="impresora",
                    orden=1,
                    pregunta_key="checklists.impresora.encendida",
                    accion_si_no="Verifique que el cable de corriente y el LED de encendido estén activos.",
                    resuelve=False
                ),
                Checklist(
                    categoria="impresora",
                    orden=2,
                    pregunta_key="checklists.impresora.papel_toner",
                    accion_si_no="Asegúrese de que la bandeja tenga etiquetas/papel y el ribbon no esté agotado.",
                    resuelve=False
                ),
                Checklist(
                    categoria="impresora",
                    orden=3,
                    pregunta_key="checklists.impresora.reinicio",
                    accion_si_no="Apague la impresora durante 10 segundos y vuelva a encenderla.",
                    resuelve=True
                ),
                Checklist(
                    categoria="red",
                    orden=1,
                    pregunta_key="checklists.red.cable",
                    accion_si_no="Verifique que el cable de red ethernet esté firmemente conectado.",
                    resuelve=False
                ),
                Checklist(
                    categoria="red",
                    orden=2,
                    pregunta_key="checklists.red.wifi",
                    accion_si_no="Compruebe si la red 'CGR_PLANTA' está visible y conectada.",
                    resuelve=True
                )
            ]
            db.add_all(checklists)
            db.commit()
            logger.info("Created static checklists.")

        # 5. Create Business Rules
        if db.query(ReglaNegocio).count() == 0:
            regla_impresora = ReglaNegocio(
                sitio_id=site.id,
                categoria="impresora",
                condicion="hardware",
                accion="proveedor",
                destinatario="soporte@zebra-mexico.com",
                activa=True
            )
            db.add(regla_impresora)
            db.commit()
            logger.info("Created default business rules.")

        logger.info("Database seeding completed successfully.")

    except Exception as e:
        logger.error(f"Error during database seed: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    seed_db()

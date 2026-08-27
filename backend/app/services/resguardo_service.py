"""Resguardos de equipo: emisión, firma, devolución y su PDF.

Un resguardo es la constancia de que una persona recibió un activo de la planta
y responde por él. Es el documento que se pide en una auditoría de inventario,
así que tiene reglas más estrictas que un ticket:

  - **No se borra.** Un equipo devuelto cierra su resguardo; no lo elimina. El
    historial de quién respondió por qué activo es el punto entero.
  - **Las condiciones se copian, no se referencian.** Si mañana cambia el texto
    de las condiciones, lo que la persona aceptó no puede cambiar solo.
  - **La firma deja rastro**: nombre tecleado, IP y momento exacto.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.core.logging import logger
from app.models import Equipo, MovimientoEquipo, Resguardo, Sitio, Usuario

# Estados del ciclo de vida.
BORRADOR = "borrador"
PENDIENTE_FIRMA = "pendiente_firma"
FIRMADO = "firmado"
DEVUELTO = "devuelto"
CANCELADO = "cancelado"

ESTADOS_ACTIVOS = (BORRADOR, PENDIENTE_FIRMA, FIRMADO)

# Texto por defecto. Se copia en cada resguardo al emitirlo, de modo que
# cambiarlo aquí no altera los ya firmados.
CONDICIONES_POR_DEFECTO = """1. El equipo descrito es propiedad de CGR de México y se entrega en calidad de
   resguardo para el desempeño de las funciones del colaborador.

2. El resguardante se compromete a darle uso exclusivamente laboral, a
   conservarlo en buen estado y a no cederlo, prestarlo ni modificarlo sin
   autorización escrita del área de TI.

3. Cualquier falla, robo, extravío o daño debe reportarse al área de TI el
   mismo día en que ocurra, a través del Portal de Tickets.

4. El equipo no debe salir de las instalaciones de la planta salvo autorización
   expresa del jefe de área y del área de TI.

5. La información almacenada en el equipo es propiedad de la empresa. El área de
   TI puede solicitar su revisión conforme a las políticas internas.

6. Al término de la relación laboral, cambio de puesto o a solicitud del área de
   TI, el resguardante devolverá el equipo con todos sus accesorios en las
   condiciones en que lo recibió, salvo el desgaste normal de uso.

7. El daño o extravío atribuible a negligencia comprobada podrá dar lugar a la
   reposición del equipo conforme a las políticas de la empresa."""


def generar_folio(db: Session, sitio_id: int) -> str:
    sitio = db.query(Sitio).filter(Sitio.id == sitio_id).first()
    clave = sitio.clave if sitio else "PLANT"
    anio = datetime.utcnow().strftime("%Y")
    # Se cuenta por sitio y año para que el folio sea legible y no un UUID.
    consecutivo = db.query(Resguardo).filter(
        Resguardo.sitio_id == sitio_id,
        Resguardo.folio.like(f"RES-{clave}-{anio}-%"),
    ).count() + 1
    return f"RES-{clave}-{anio}-{consecutivo:04d}"


class ResguardoService:

    @staticmethod
    def resguardo_activo(db: Session, equipo_id: int) -> Optional[Resguardo]:
        """El resguardo vigente de un equipo, si lo tiene."""
        return (
            db.query(Resguardo)
            .filter(Resguardo.equipo_id == equipo_id, Resguardo.estado.in_(ESTADOS_ACTIVOS))
            .order_by(Resguardo.creado_en.desc())
            .first()
        )

    @staticmethod
    def emitir(
        db: Session,
        equipo: Equipo,
        usuario: Usuario,
        emisor: Usuario,
        accesorios: Optional[str] = None,
        observaciones: Optional[str] = None,
        condiciones: Optional[str] = None,
    ) -> Resguardo:
        """Emite un resguardo y deja el equipo asignado.

        Levanta ValueError si el equipo ya tiene uno vigente: un activo no puede
        estar bajo la responsabilidad de dos personas a la vez.
        """
        vigente = ResguardoService.resguardo_activo(db, equipo.id)
        if vigente:
            raise ValueError(
                f"El equipo ya tiene el resguardo {vigente.folio} vigente a nombre de "
                f"{vigente.usuario.nombre}. Regístrese primero la devolución."
            )

        ahora = datetime.utcnow()
        resguardo = Resguardo(
            folio=generar_folio(db, equipo.sitio_id),
            sitio_id=equipo.sitio_id,
            usuario_id=usuario.id,
            equipo_id=equipo.id,
            creado_por=emisor.id,
            estado=PENDIENTE_FIRMA,
            # Copia, no referencia: lo aceptado queda congelado.
            condiciones=condiciones or CONDICIONES_POR_DEFECTO,
            accesorios=accesorios,
            observaciones_entrega=observaciones,
            entregado_en=ahora,
            creado_en=ahora,
        )
        db.add(resguardo)
        db.flush()

        estado_anterior = equipo.estado
        equipo.asignado_a = usuario.id
        equipo.fecha_asignacion = ahora
        equipo.estado = "asignado"

        db.add(MovimientoEquipo(
            equipo_id=equipo.id,
            tipo="asignacion",
            usuario_id=usuario.id,
            resguardo_id=resguardo.id,
            estado_anterior=estado_anterior,
            estado_nuevo="asignado",
            nota=f"Resguardo {resguardo.folio} emitido",
            realizado_por=emisor.id,
            creado_en=ahora,
        ))

        db.commit()
        db.refresh(resguardo)
        logger.info("Resguardo emitido",
                    extra={"folio": resguardo.folio, "equipo_id": equipo.id, "usuario_id": usuario.id})
        return resguardo

    @staticmethod
    def firmar(db: Session, resguardo: Resguardo, quien: Usuario, nombre: str, ip: Optional[str]) -> Resguardo:
        """Registra la aceptación del resguardante.

        Solo la propia persona puede firmar lo suyo: que un admin firme por
        alguien más anularía el valor del documento.
        """
        if resguardo.usuario_id != quien.id:
            raise PermissionError("Solo el resguardante puede firmar su propio resguardo.")
        if resguardo.estado != PENDIENTE_FIRMA:
            raise ValueError(f"El resguardo está en estado '{resguardo.estado}' y no admite firma.")
        if not nombre or len(nombre.strip()) < 3:
            raise ValueError("Debe escribir su nombre completo para firmar.")

        resguardo.estado = FIRMADO
        resguardo.firmado_en = datetime.utcnow()
        resguardo.firma_nombre = nombre.strip()[:150]
        resguardo.firma_ip = ip
        db.commit()
        db.refresh(resguardo)
        logger.info("Resguardo firmado", extra={"folio": resguardo.folio, "usuario_id": quien.id})
        return resguardo

    @staticmethod
    def devolver(
        db: Session,
        resguardo: Resguardo,
        receptor: Usuario,
        observaciones: Optional[str] = None,
        estado_equipo: str = "disponible",
    ) -> Resguardo:
        """Cierra el resguardo y libera el equipo."""
        if resguardo.estado not in (PENDIENTE_FIRMA, FIRMADO):
            raise ValueError(f"El resguardo está en estado '{resguardo.estado}' y no admite devolución.")

        ahora = datetime.utcnow()
        resguardo.estado = DEVUELTO
        resguardo.devuelto_en = ahora
        resguardo.recibido_por = receptor.id
        resguardo.observaciones_devolucion = observaciones

        equipo = db.query(Equipo).filter(Equipo.id == resguardo.equipo_id).first()
        estado_anterior = equipo.estado if equipo else None
        if equipo:
            equipo.asignado_a = None
            equipo.fecha_asignacion = None
            equipo.estado = estado_equipo

        db.add(MovimientoEquipo(
            equipo_id=resguardo.equipo_id,
            tipo="devolucion",
            usuario_id=resguardo.usuario_id,
            resguardo_id=resguardo.id,
            estado_anterior=estado_anterior,
            estado_nuevo=estado_equipo,
            nota=observaciones or f"Devolución del resguardo {resguardo.folio}",
            realizado_por=receptor.id,
            creado_en=ahora,
        ))

        db.commit()
        db.refresh(resguardo)
        logger.info("Resguardo devuelto", extra={"folio": resguardo.folio})
        return resguardo

    @staticmethod
    def cancelar(db: Session, resguardo: Resguardo, quien: Usuario, motivo: str) -> Resguardo:
        """Anula un resguardo emitido por error.

        Solo antes de firmar: uno ya firmado se cierra con una devolución, que
        deja constancia, no con una cancelación que lo borra de la historia.
        """
        if resguardo.estado != PENDIENTE_FIRMA:
            raise ValueError("Solo se puede cancelar un resguardo que aún no se ha firmado.")

        ahora = datetime.utcnow()
        resguardo.estado = CANCELADO
        resguardo.observaciones_devolucion = motivo

        equipo = db.query(Equipo).filter(Equipo.id == resguardo.equipo_id).first()
        if equipo:
            equipo.asignado_a = None
            equipo.fecha_asignacion = None
            equipo.estado = "disponible"

        db.add(MovimientoEquipo(
            equipo_id=resguardo.equipo_id,
            tipo="devolucion",
            usuario_id=resguardo.usuario_id,
            resguardo_id=resguardo.id,
            estado_nuevo="disponible",
            nota=f"Resguardo {resguardo.folio} cancelado: {motivo}",
            realizado_por=quien.id,
            creado_en=ahora,
        ))

        db.commit()
        db.refresh(resguardo)
        return resguardo

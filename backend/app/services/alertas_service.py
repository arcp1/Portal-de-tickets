"""Alertas para TI: lo que hay que mirar ya, aunque nadie tenga la pantalla abierta.

Las abren procesos sin persona delante —el vigilante del SLA en el worker, el
receptor de sensores, la encuesta de satisfacción— y salen en la campana del
tablero de TI en vivo (aviso ``alertas`` del flujo de eventos).

**Una alerta por cosa.** ``(tipo, clave)`` es único en la base:

  * Las de SLA usan el ticket como clave y **no se repiten nunca**: el
    vigilante pasa cada minuto y, sin eso, un ticket vencido avisaría 60 veces
    por hora. Atenderla no la reabre al minuto siguiente.
  * Las de sensores son **por episodio**: mientras la temperatura siga alta
    hay una sola abierta; cuando vuelve a la normalidad se cierra sola, y su
    clave se libera (se le añade ``#id``) para que el próximo episodio abra
    otra.
"""

from datetime import datetime, timedelta
from typing import List, Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import logger
from app.models import Alerta, Ticket, Usuario
from app.services import eventos_service as eventos

SLA_POR_VENCER = "sla_por_vencer"
SLA_VENCIDO = "sla_vencido"
SATISFACCION_BAJA = "satisfaccion_baja"
IOT_UMBRAL = "iot_umbral"
IOT_SIN_SENAL = "iot_sin_senal"

TIPOS = (SLA_POR_VENCER, SLA_VENCIDO, SATISFACCION_BAJA, IOT_UMBRAL, IOT_SIN_SENAL)
#: Las que se cierran solas al pasar y dejan abrir otra después.
POR_EPISODIO = (IOT_UMBRAL, IOT_SIN_SENAL)

#: Los estados en que el SLA corre. "En proveedor" no: el tiempo ya no
#: depende de TI, y avisar de algo que no se puede acelerar solo enseña a
#: ignorar la campana.
ESTADOS_CON_SLA = ("abierto", "en_proceso")


class AlertasService:

    @staticmethod
    def abrir(db: Session, tipo: str, clave: str, titulo: str, *,
              detalle: Optional[str] = None, datos: Optional[dict] = None,
              sitio_id: Optional[int] = None, ticket_id: Optional[int] = None,
              dispositivo_id: Optional[int] = None, avisar: bool = True) -> Optional[Alerta]:
        """La abre si no existe ya una con ese `(tipo, clave)`. None si ya estaba."""
        if db.query(Alerta.id).filter(Alerta.tipo == tipo, Alerta.clave == clave).first():
            return None
        alerta = Alerta(tipo=tipo, clave=clave[:120], titulo=titulo[:200], detalle=detalle,
                        datos=datos, sitio_id=sitio_id, ticket_id=ticket_id,
                        dispositivo_id=dispositivo_id, creado_en=datetime.utcnow())
        try:
            # Punto de guardado: si otro proceso la abrió entre la consulta y
            # aquí, el único de la base la rechaza y no se tira lo demás.
            with db.begin_nested():
                db.add(alerta)
            db.commit()
        except IntegrityError:
            db.rollback()
            return None
        logger.info("Alerta abierta", extra={"tipo": tipo, "clave": clave, "sitio_id": sitio_id})
        if avisar:
            eventos.publicar(sitio_id, "alertas")
        return alerta

    @staticmethod
    def cerrar(db: Session, alerta: Alerta, usuario: Optional[Usuario] = None,
               nota: Optional[str] = None) -> Alerta:
        """La da por atendida. Sin `usuario`, la cerró el sistema (se normalizó)."""
        if alerta.atendida_en is None:
            alerta.atendida_en = datetime.utcnow()
            alerta.atendida_por = usuario.id if usuario else None
            if nota:
                alerta.detalle = f"{alerta.detalle}\n{nota}" if alerta.detalle else nota
            if alerta.tipo in POR_EPISODIO and "#" not in alerta.clave:
                # Libera la clave para el próximo episodio.
                alerta.clave = f"{alerta.clave}#{alerta.id}"[:120]
        return alerta

    @staticmethod
    def abierta(db: Session, tipo: str, clave: str) -> Optional[Alerta]:
        return db.query(Alerta).filter(Alerta.tipo == tipo, Alerta.clave == clave,
                                       Alerta.atendida_en.is_(None)).first()

    # ------------------------------------------------------------------
    # El vigilante del SLA (lo corre el worker cada minuto)
    # ------------------------------------------------------------------
    @staticmethod
    def vigilar_sla(db: Session, ahora: Optional[datetime] = None) -> dict:
        """Abre las de "por vencer" y "vencido"; cierra las de tickets ya resueltos."""
        ahora = ahora or datetime.utcnow()
        limite = ahora + timedelta(minutes=settings.SLA_AVISO_MINUTOS)
        abiertas: List[Alerta] = []

        proximos = (
            db.query(Ticket)
            .filter(Ticket.estado.in_(ESTADOS_CON_SLA), Ticket.vence_en.isnot(None),
                    Ticket.vence_en <= limite)
            .all()
        )
        for ticket in proximos:
            vencido = ticket.vence_en <= ahora
            minutos = int(abs((ticket.vence_en - ahora).total_seconds()) // 60)
            tipo = SLA_VENCIDO if vencido else SLA_POR_VENCER
            titulo = (f"{ticket.folio}: SLA vencido hace {minutos} min" if vencido
                      else f"{ticket.folio}: el SLA vence en {minutos} min")
            alerta = AlertasService.abrir(
                db, tipo, f"ticket:{ticket.id}", titulo,
                datos={"folio": ticket.folio, "minutos": minutos, "prioridad": ticket.prioridad,
                       "vence_en": ticket.vence_en.isoformat() + "Z"},
                sitio_id=ticket.sitio_id, ticket_id=ticket.id, avisar=False)
            if alerta:
                abiertas.append(alerta)

        # Las de tickets que ya no corren (resueltos, cancelados, en proveedor)
        # se cierran solas: ya no hay nada que hacer con ellas.
        cerradas = 0
        pendientes = (
            db.query(Alerta).join(Ticket, Alerta.ticket_id == Ticket.id)
            .filter(Alerta.tipo.in_((SLA_POR_VENCER, SLA_VENCIDO)),
                    Alerta.atendida_en.is_(None),
                    Ticket.estado.notin_(ESTADOS_CON_SLA))
            .all()
        )
        for alerta in pendientes:
            AlertasService.cerrar(db, alerta, nota="El ticket salió de la cola.")
            cerradas += 1
        if cerradas:
            db.commit()

        if abiertas or cerradas:
            # Un solo aviso por pasada, no uno por alerta.
            eventos.publicar(None, "alertas")
        return {"abiertas": len(abiertas), "cerradas": cerradas}

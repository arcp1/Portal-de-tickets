"""Bitácora de acciones administrativas (spec §12).

Qué se registra: lo que afecta a otros — cambios de estado, asignaciones,
edición de reglas, de pasos de checklist y de la base de conocimiento.

Qué NO se registra: lecturas. Auditar consultas llena la tabla de ruido y
entierra lo que sí importa.

Como el resto de los servicios accesorios, un fallo aquí nunca tumba la
operación auditada: es preferible perder una línea de bitácora que impedir que
un técnico cierre un ticket.
"""

from datetime import datetime
from typing import Optional

from fastapi import Request
from sqlalchemy.orm import Session

from app.core.logging import logger
from app.models import Auditoria, Usuario

# Acciones conocidas. Es una lista, no un enum de base de datos, para no
# necesitar una migración cada vez que se audita algo nuevo.
TICKET_ESTADO = "ticket.estado"
TICKET_ASIGNADO = "ticket.asignado"
TICKET_SOLUCION = "ticket.solucion"
TICKET_PRIORIDAD = "ticket.prioridad"
REGLA_CREADA = "regla.creada"
REGLA_BORRADA = "regla.borrada"
PASO_CREADO = "paso.creado"
PASO_EDITADO = "paso.editado"
PASO_BAJA = "paso.baja"
KB_CREADA = "kb.creada"
KB_EDITADA = "kb.editada"
KB_BORRADA = "kb.borrada"
TEMA_PROMOVIDO = "tema.promovido"
TEMA_DESCARTADO = "tema.descartado"


def ip_de(peticion: Optional[Request]) -> Optional[str]:
    """IP real del cliente, respetando el proxy de NGINX."""
    if peticion is None:
        return None
    reenviada = peticion.headers.get("x-forwarded-for")
    if reenviada:
        # El primero de la lista es el cliente original.
        return reenviada.split(",")[0].strip()[:45]
    return peticion.client.host[:45] if peticion.client else None


class AuditoriaService:

    @staticmethod
    def registrar(
        db: Session,
        usuario: Usuario,
        accion: str,
        entidad: str,
        entidad_id: Optional[int] = None,
        detalle: Optional[dict] = None,
        peticion: Optional[Request] = None,
    ) -> bool:
        """Deja constancia. Devuelve False si no se pudo, nunca levanta."""
        try:
            db.add(Auditoria(
                usuario_id=usuario.id,
                accion=accion,
                entidad=entidad,
                entidad_id=entidad_id,
                detalle=detalle,
                ip=ip_de(peticion),
                creado_en=datetime.utcnow(),
            ))
            db.commit()
            return True
        except Exception as exc:  # noqa: BLE001 - degradación deliberada
            db.rollback()
            logger.error(
                "No se pudo escribir en la bitácora; la operación siguió igual",
                extra={"accion": accion, "entidad": entidad, "error": str(exc)},
            )
            return False

    @staticmethod
    def cambio(antes, despues) -> dict:
        """Formato uniforme para un cambio de valor."""
        return {"antes": antes, "despues": despues}

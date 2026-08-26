"""Reindexa en la base de conocimiento los tickets resueltos que quedaron fuera.

Sirve para dos casos:
  - Tickets cerrados en la Fase 1, antes de que existiera el campo `solucion`.
  - Tickets cerrados mientras Ollama estaba caído (el cierre nunca se bloquea,
    así que quedan con `indexado_kb = False` esperando este script).

Uso:
    python reindexar_kb.py
"""

from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.core.logging import logger
from app.models import Ticket
from app.services.kb_service import KBService, solucion_es_valida
from app.services.ollama_client import ollama


def reindexar():
    if not ollama.disponible():
        logger.error("Ollama no responde. Levántalo antes de reindexar.")
        return

    db: Session = SessionLocal()
    indexados = sin_solucion = fallidos = 0

    try:
        pendientes = (
            db.query(Ticket)
            .filter(
                Ticket.estado.in_(["resuelto", "cerrado"]),
                Ticket.indexado_kb.is_(False),
            )
            .all()
        )
        logger.info(f"Tickets pendientes de indexar: {len(pendientes)}")

        for ticket in pendientes:
            if not solucion_es_valida(ticket.solucion):
                # No se inventa una solución: el ticket se queda fuera y hay que
                # documentarlo a mano.
                sin_solucion += 1
                continue

            if KBService.indexar_ticket(db, ticket):
                indexados += 1
            else:
                fallidos += 1

        logger.info(
            "Reindexación terminada",
            extra={
                "indexados": indexados,
                "sin_solucion": sin_solucion,
                "fallidos": fallidos,
            },
        )
        print(f"Indexados: {indexados}")
        print(f"Sin solución documentada (requieren captura manual): {sin_solucion}")
        print(f"Fallidos: {fallidos}")

    except Exception as exc:  # noqa: BLE001
        logger.error(f"Error durante la reindexación: {exc}")
        db.rollback()
    finally:
        db.close()


if __name__ == "__main__":
    reindexar()

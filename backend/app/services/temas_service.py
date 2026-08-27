"""Detección de problemas recurrentes que el portal no tiene contemplados.

La idea: nadie puede prever todas las fallas de una planta. Cuando alguien
reporta algo que no encaja, en vez de perderse en un ticket suelto se agrupa
con lo parecido que ya se reportó. Si el mismo problema vuelve, deja de ser
anécdota y se le propone al admin convertirlo en tema con su checklist.

Igual que el resto del módulo de IA: si Ollama no está, esto no hace nada y
nadie se entera. Nunca bloquea la creación de un ticket.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import logger
from app.models import BaseConocimiento, TemaSugerido, Ticket
from app.services.ollama_client import ollama


class TemasService:

    @staticmethod
    def registrar_incidencia(db: Session, ticket: Ticket) -> Optional[TemaSugerido]:
        """Agrupa el ticket con problemas parecidos ya reportados.

        Devuelve el tema al que se sumó, o None si no aplica o falló algo.
        Nunca levanta: el ticket ya está creado y su suerte no depende de esto.
        """
        if ticket.categoria != "otro":
            return None

        texto = ticket.descripcion_normalizada or ticket.descripcion_original
        if not texto or len(texto.strip()) < 15:
            return None

        try:
            embedding = ollama.generar_embedding(texto, tarea="documento")
            if embedding is None:
                return None

            # ¿Ya se reportó algo así?
            candidato = (
                db.query(
                    TemaSugerido,
                    TemaSugerido.embedding.cosine_distance(embedding).label("distancia"),
                )
                .filter(
                    TemaSugerido.sitio_id == ticket.sitio_id,
                    TemaSugerido.embedding.isnot(None),
                    TemaSugerido.estado.in_(["pendiente", "listo"]),
                )
                .order_by("distancia")
                .first()
            )

            ahora = datetime.utcnow()

            if candidato and (1.0 - float(candidato.distancia)) >= settings.TEMA_UMBRAL_AGRUPACION:
                tema = candidato[0]
                tema.ocurrencias += 1
                tema.ultima_vez = ahora
                if tema.ocurrencias >= settings.TEMA_MIN_OCURRENCIAS:
                    tema.estado = "listo"
                db.commit()
                db.refresh(tema)
                logger.info(
                    "Incidencia agrupada en un tema recurrente",
                    extra={"tema_id": tema.id, "ocurrencias": tema.ocurrencias},
                )
                return tema

            # Primera vez que se ve algo así.
            tema = TemaSugerido(
                sitio_id=ticket.sitio_id,
                titulo=texto.strip()[:200],
                descripcion_ejemplo=texto.strip(),
                categoria_sugerida="otro",
                embedding=embedding,
                ocurrencias=1,
                estado="pendiente",
                primera_vez=ahora,
                ultima_vez=ahora,
            )
            db.add(tema)
            db.commit()
            db.refresh(tema)
            return tema

        except Exception as exc:  # noqa: BLE001 - degradación deliberada
            db.rollback()
            logger.error(
                "Fallo agrupando la incidencia en temas recurrentes",
                extra={"ticket_id": ticket.id, "error": str(exc)},
            )
            return None

    @staticmethod
    def soluciones_propuestas(db: Session, tema: TemaSugerido) -> list:
        """Qué hicieron los técnicos ante problemas realmente parecidos a este.

        Se consulta contra los vectores que ya están en base_conocimiento en
        lugar de re-embeber tickets uno por uno: es una sola consulta a pgvector
        en vez de decenas de llamadas a Ollama.

        El umbral es el de agrupación (más estricto que el de sugerencias), no
        el de la búsqueda del usuario. Aquí una solución equivocada es peor que
        ninguna: el admin escribiría el checklist a partir de un caso que no
        tiene nada que ver.
        """
        if tema.embedding is None:
            return []

        try:
            filas = (
                db.query(
                    Ticket,
                    BaseConocimiento.embedding.cosine_distance(tema.embedding).label("distancia"),
                )
                .join(BaseConocimiento, BaseConocimiento.ticket_origen_id == Ticket.id)
                .filter(
                    BaseConocimiento.sitio_id == tema.sitio_id,
                    BaseConocimiento.embedding.isnot(None),
                    Ticket.solucion.isnot(None),
                )
                .order_by("distancia")
                .limit(3)
                .all()
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Fallo buscando soluciones previas", extra={"error": str(exc)})
            return []

        propuestas = []
        for ticket, distancia in filas:
            similitud = 1.0 - float(distancia)
            if similitud < settings.TEMA_UMBRAL_AGRUPACION:
                continue
            propuestas.append(
                {
                    "ticket_id": ticket.id,
                    "folio": ticket.folio,
                    "similitud": round(similitud, 4),
                    "solucion": ticket.solucion,
                }
            )
        return propuestas

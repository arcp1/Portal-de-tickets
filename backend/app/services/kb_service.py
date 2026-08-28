"""Base de conocimiento: indexación, búsqueda por similitud y utilidad.

Dos invariantes:

1. Solo se indexan tickets con solución escrita. Un ticket cerrado sin explicar
   cómo se resolvió no aporta nada y ensucia la búsqueda.
2. Nada de aquí puede tumbar una petición. Si Ollama o pgvector fallan, la
   búsqueda devuelve vacío y el flujo sigue al siguiente nivel.
"""

from datetime import datetime
from typing import List, Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import logger
from app.models import BaseConocimiento, SugerenciaKB, Ticket
from app.services.horario_service import HorarioService
from app.services.ollama_client import ollama


def solucion_es_valida(solucion: Optional[str]) -> bool:
    """Una solución sirve si explica algo. 'ok' o 'listo' no explican nada."""
    return bool(solucion and len(solucion.strip()) >= settings.SOLUCION_MIN_LONGITUD)


def construir_texto_indexable(ticket: Ticket) -> str:
    """categoría + descripción + solución + lo que se descartó.

    El descarte entra en el texto indexado a propósito: quien reporte la misma
    falla debe encontrar el ticket aunque su síntoma se parezca más a lo que se
    probó y no era, que a la solución final.
    """
    descripcion = ticket.descripcion_normalizada or ticket.descripcion_original
    partes = [ticket.categoria, ticket.subcategoria, descripcion, ticket.solucion]
    if ticket.descartado and ticket.descartado.strip():
        partes.append("Se descartó: " + ticket.descartado.strip())
    return "\n".join(parte.strip() for parte in partes if parte and parte.strip())


class KBService:

    # ------------------------------------------------------------------
    # Indexación
    # ------------------------------------------------------------------
    @staticmethod
    def indexar_ticket(db: Session, ticket: Ticket) -> bool:
        """Convierte un ticket resuelto en una entrada de la base de conocimiento.

        Devuelve True si quedó indexado. False significa "todavía no" —nunca es
        un error para el llamador—: puede ser que no haya solución, que Ollama
        esté caído o que ya estuviera indexado. En todos esos casos el cierre
        del ticket sigue siendo válido.
        """
        if ticket.indexado_kb:
            return False

        if not solucion_es_valida(ticket.solucion):
            logger.info(
                "Ticket sin solución documentada: no se indexa",
                extra={"ticket_id": ticket.id, "folio": ticket.folio},
            )
            return False

        texto = construir_texto_indexable(ticket)
        embedding = ollama.generar_embedding(texto, tarea="documento")

        if embedding is None:
            # Ollama no está. El ticket queda cerrado igual y sin indexar;
            # el script de reindexación lo recoge después.
            logger.warning(
                "No se pudo generar embedding: el ticket queda pendiente de indexar",
                extra={"ticket_id": ticket.id, "folio": ticket.folio},
            )
            return False

        try:
            entrada = BaseConocimiento(
                sitio_id=ticket.sitio_id,
                titulo=(ticket.descripcion_normalizada or ticket.descripcion_original)[:150],
                contenido=texto,
                categoria=ticket.categoria,
                tags=ticket.subcategoria,
                descartado=ticket.descartado,
                embedding=embedding,
                ticket_origen_id=ticket.id,
                creado_en=datetime.utcnow(),
            )
            db.add(entrada)
            ticket.indexado_kb = True
            db.commit()
            logger.info(
                "Ticket indexado en base de conocimiento",
                extra={"ticket_id": ticket.id, "folio": ticket.folio},
            )
            return True
        except Exception as exc:  # noqa: BLE001 - degradación deliberada
            db.rollback()
            logger.error(
                "Fallo indexando ticket; el cierre no se ve afectado",
                extra={"ticket_id": ticket.id, "error": str(exc)},
            )
            return False

    # ------------------------------------------------------------------
    # Búsqueda por similitud
    # ------------------------------------------------------------------
    @staticmethod
    def buscar_similares(
        db: Session,
        texto: str,
        sitio_id: int,
        categoria: Optional[str] = None,
        usuario_id: Optional[int] = None,
        ticket_id: Optional[int] = None,
    ) -> dict:
        """Busca incidencias parecidas ya resueltas.

        Devuelve siempre un dict válido. ``degradado=True`` significa que la
        búsqueda no se pudo hacer; el llamador debe continuar al siguiente nivel
        del flujo sin mostrar ningún error de IA al usuario.
        """
        vacio = {
            "resultados": [],
            "umbral_usado": settings.KB_UMBRAL_SIMILITUD,
            "degradado": True,
        }

        embedding = ollama.generar_embedding(texto, tarea="consulta")
        if embedding is None:
            return vacio

        try:
            consulta = db.query(
                BaseConocimiento,
                BaseConocimiento.embedding.cosine_distance(embedding).label("distancia"),
            ).filter(
                BaseConocimiento.sitio_id == sitio_id,
                BaseConocimiento.embedding.isnot(None),
            )
            if categoria:
                consulta = consulta.filter(BaseConocimiento.categoria.ilike(categoria))

            # Fuera de horario se muestran mas sugerencias antes de rendirse:
            # no hay personal a quien escalar hasta el dia siguiente, asi que
            # vale la pena que el usuario tenga mas de donde escoger.
            cuantas = (
                settings.KB_MAX_SUGERENCIAS
                if HorarioService.es_horario_laboral()
                else settings.KB_MAX_SUGERENCIAS_FUERA_HORARIO
            )
            filas = consulta.order_by("distancia").limit(cuantas).all()
        except Exception as exc:  # noqa: BLE001 - degradación deliberada
            logger.error(
                "Fallo consultando la base de conocimiento; se omite la sugerencia",
                extra={"sitio_id": sitio_id, "error": str(exc)},
            )
            return vacio

        resultados = []
        ahora = datetime.utcnow()

        for entrada, distancia in filas:
            similitud = 1.0 - float(distancia)
            if similitud < settings.KB_UMBRAL_SIMILITUD:
                continue

            # Cada sugerencia mostrada se registra. Sin esto no hay forma de
            # calibrar el umbral con datos reales.
            sugerencia = SugerenciaKB(
                ticket_id=ticket_id,
                kb_id=entrada.id,
                usuario_id=usuario_id,
                similitud=similitud,
                fue_util=None,
                creado_en=ahora,
            )
            db.add(sugerencia)
            entrada.veces_sugerida = (entrada.veces_sugerida or 0) + 1
            entrada.ultima_sugerencia = ahora
            db.flush()

            resultados.append(
                {
                    "sugerencia_id": sugerencia.id,
                    "kb_id": entrada.id,
                    "titulo": entrada.titulo,
                    "contenido": entrada.contenido,
                    "categoria": entrada.categoria,
                    "similitud": round(similitud, 4),
                    "ticket_origen_id": entrada.ticket_origen_id,
                }
            )

        try:
            db.commit()
        except Exception as exc:  # noqa: BLE001 - degradación deliberada
            db.rollback()
            logger.error(
                "Fallo registrando sugerencias mostradas",
                extra={"error": str(exc)},
            )
            return vacio

        return {
            "resultados": resultados,
            "umbral_usado": settings.KB_UMBRAL_SIMILITUD,
            "degradado": False,
        }

    # ------------------------------------------------------------------
    # Feedback de utilidad
    # ------------------------------------------------------------------
    @staticmethod
    def registrar_feedback(db: Session, sugerencia_id: int, fue_util: bool) -> Optional[SugerenciaKB]:
        """Guarda la respuesta al '¿te sirvió?'.

        Devuelve None si la sugerencia no existe. Responder dos veces la misma
        sugerencia actualiza la respuesta sin volver a contarla.
        """
        sugerencia = db.query(SugerenciaKB).filter(SugerenciaKB.id == sugerencia_id).first()
        if not sugerencia:
            return None

        anterior = sugerencia.fue_util
        sugerencia.fue_util = fue_util

        entrada = db.query(BaseConocimiento).filter(BaseConocimiento.id == sugerencia.kb_id).first()
        if entrada:
            delta = (1 if fue_util else 0) - (1 if anterior else 0)
            if delta:
                entrada.veces_util = max(0, (entrada.veces_util or 0) + delta)

        db.commit()
        db.refresh(sugerencia)

        logger.info(
            "Feedback de sugerencia registrado",
            extra={
                "sugerencia_id": sugerencia.id,
                "kb_id": sugerencia.kb_id,
                "fue_util": fue_util,
            },
        )
        return sugerencia

    # ------------------------------------------------------------------
    # Métricas
    # ------------------------------------------------------------------
    @staticmethod
    def metricas(db: Session, sitio_id: int) -> dict:
        """Tasa de utilidad = veces_util / veces_sugerida. Es lo que calibra el umbral."""
        entradas = db.query(BaseConocimiento).filter(BaseConocimiento.sitio_id == sitio_id).all()

        sugeridas = sum(entrada.veces_sugerida or 0 for entrada in entradas)
        utiles = sum(entrada.veces_util or 0 for entrada in entradas)

        respondidas = (
            db.query(SugerenciaKB)
            .join(BaseConocimiento, SugerenciaKB.kb_id == BaseConocimiento.id)
            .filter(
                BaseConocimiento.sitio_id == sitio_id,
                SugerenciaKB.fue_util.isnot(None),
            )
            .count()
        )

        return {
            "entradas_kb": len(entradas),
            "sugerencias_mostradas": sugeridas,
            "sugerencias_utiles": utiles,
            "sugerencias_respondidas": respondidas,
            # None y no 0: sin sugerencias mostradas la tasa no existe todavía.
            "tasa_utilidad": round(utiles / sugeridas, 4) if sugeridas else None,
            "umbral_actual": settings.KB_UMBRAL_SIMILITUD,
            "tickets_pendientes_indexar": db.query(Ticket)
            .filter(
                Ticket.sitio_id == sitio_id,
                Ticket.estado.in_(["resuelto", "cerrado"]),
                Ticket.indexado_kb.is_(False),
            )
            .count(),
        }

"""Métricas del portal.

Cubre lo que piden la spec §13 (deflección, canales, tiempos, top 10) y la
Fase 2 §9 (normalización, sugerencias, utilidad, chatbot, latencia de Ollama).

Todo se calcula por sitio: un admin solo ve su planta.
"""

from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import BaseConocimiento, ChatSesion, SugerenciaKB, Ticket
from app.services.ollama_client import ollama

# Canales en los que la incidencia se resolvió sin que un técnico interviniera.
CANALES_DEFLECTADOS = ("checklist", "kb", "ia")


def _porcentaje(parte: int, total: int) -> Optional[float]:
    """None y no 0 cuando no hay datos: un cero falso se lee como mal resultado."""
    if not total:
        return None
    return round(100.0 * parte / total, 1)


class MetricasService:

    @staticmethod
    def resumen(db: Session, sitio_id: int, dias: int = 30) -> dict:
        desde = datetime.utcnow() - timedelta(days=dias)
        base = db.query(Ticket).filter(Ticket.sitio_id == sitio_id)

        total = base.count()
        total_periodo = base.filter(Ticket.creado_en >= desde).count()
        ultima_semana = base.filter(
            Ticket.creado_en >= datetime.utcnow() - timedelta(days=7)
        ).count()

        # --- Distribución por canal (la métrica más importante de la spec) ---
        por_canal = dict(
            db.query(Ticket.canal_resolucion, func.count(Ticket.id))
            .filter(Ticket.sitio_id == sitio_id)
            .group_by(Ticket.canal_resolucion)
            .all()
        )
        por_canal = {(k or "sin_canal"): v for k, v in por_canal.items()}
        deflectados = sum(por_canal.get(c, 0) for c in CANALES_DEFLECTADOS)

        # --- Por categoría: el "top 10 de incidencias recurrentes" ---
        por_categoria = [
            {"categoria": cat, "total": n}
            for cat, n in db.query(Ticket.categoria, func.count(Ticket.id))
            .filter(Ticket.sitio_id == sitio_id)
            .group_by(Ticket.categoria)
            .order_by(func.count(Ticket.id).desc())
            .limit(10)
            .all()
        ]

        # --- Tiempo de resolución (solo los cerrados por un técnico) ---
        promedio_minutos = (
            db.query(func.avg(Ticket.tiempo_resolucion))
            .filter(
                Ticket.sitio_id == sitio_id,
                Ticket.tiempo_resolucion.isnot(None),
                Ticket.canal_resolucion.notin_(CANALES_DEFLECTADOS),
            )
            .scalar()
        )

        # --- Fase 2: normalización ---
        normalizados = base.filter(Ticket.descripcion_normalizada.isnot(None)).count()

        return {
            "sitio_id": sitio_id,
            "periodo_dias": dias,
            "tickets_total": total,
            "tickets_periodo": total_periodo,
            "tickets_ultima_semana": ultima_semana,
            "por_canal": por_canal,
            "por_categoria": por_categoria,
            # La métrica estrella. None mientras no haya un solo ticket.
            "tasa_deflexion": _porcentaje(deflectados, total),
            "tickets_deflectados": deflectados,
            "tiempo_resolucion_promedio_min": round(float(promedio_minutos), 1) if promedio_minutos else None,
            "tickets_abiertos": base.filter(
                Ticket.estado.in_(["abierto", "en_proceso", "espera_proveedor"])
            ).count(),
            "descripcion_normalizada": normalizados,
            "tasa_normalizacion": _porcentaje(normalizados, total),
        }

    @staticmethod
    def base_conocimiento(db: Session, sitio_id: int) -> dict:
        entradas = db.query(BaseConocimiento).filter(BaseConocimiento.sitio_id == sitio_id).all()
        sugeridas = sum(e.veces_sugerida or 0 for e in entradas)
        utiles = sum(e.veces_util or 0 for e in entradas)

        respondidas = (
            db.query(SugerenciaKB)
            .join(BaseConocimiento, SugerenciaKB.kb_id == BaseConocimiento.id)
            .filter(
                BaseConocimiento.sitio_id == sitio_id,
                SugerenciaKB.fue_util.isnot(None),
            )
            .count()
        )

        hace_una_semana = datetime.utcnow() - timedelta(days=7)
        sugeridas_semana = (
            db.query(SugerenciaKB)
            .join(BaseConocimiento, SugerenciaKB.kb_id == BaseConocimiento.id)
            .filter(
                BaseConocimiento.sitio_id == sitio_id,
                SugerenciaKB.creado_en >= hace_una_semana,
            )
            .count()
        )

        resueltas_por_kb = (
            db.query(Ticket)
            .filter(Ticket.sitio_id == sitio_id, Ticket.canal_resolucion == "kb")
            .count()
        )

        return {
            "entradas_kb": len(entradas),
            "sugerencias_mostradas": sugeridas,
            "sugerencias_mostradas_semana": sugeridas_semana,
            "sugerencias_utiles": utiles,
            "sugerencias_respondidas": respondidas,
            # veces_util / veces_sugerida: lo que calibra el umbral.
            "tasa_utilidad": _porcentaje(utiles, sugeridas),
            "incidencias_resueltas_por_kb": resueltas_por_kb,
            "umbral_actual": settings.KB_UMBRAL_SIMILITUD,
            "tickets_pendientes_indexar": db.query(Ticket)
            .filter(
                Ticket.sitio_id == sitio_id,
                Ticket.estado.in_(["resuelto", "cerrado"]),
                Ticket.indexado_kb.is_(False),
                # Las auto-resoluciones no se indexan a propósito: el checklist
                # ya existe y la sugerencia de KB ya estaba indexada.
                Ticket.canal_resolucion.notin_(CANALES_DEFLECTADOS),
            )
            .count(),
        }

    @staticmethod
    def chatbot(db: Session, sitio_id: int) -> dict:
        """Sesiones, cuántas acabaron en ticket, y precisión del clasificador."""
        sesiones = (
            db.query(ChatSesion)
            .join(Ticket, ChatSesion.ticket_id == Ticket.id, isouter=True)
            .filter(
                # Solo sesiones cuyo ticket es de este sitio, o sin ticket aún.
                (Ticket.sitio_id == sitio_id) | (ChatSesion.ticket_id.is_(None))
            )
            .all()
        )

        total = len(sesiones)
        con_ticket = [s for s in sesiones if s.ticket_id is not None]

        # Precisión: categoría que detectó el modelo vs. la que quedó en el ticket.
        comparables = aciertos = 0
        for sesion in con_ticket:
            if not sesion.categoria_detectada:
                continue
            ticket = db.query(Ticket).filter(Ticket.id == sesion.ticket_id).first()
            if not ticket:
                continue
            comparables += 1
            if ticket.categoria == sesion.categoria_detectada:
                aciertos += 1

        return {
            "sesiones_iniciadas": total,
            "sesiones_con_ticket": len(con_ticket),
            "porcentaje_termino_en_ticket": _porcentaje(len(con_ticket), total),
            "clasificaciones_comparables": comparables,
            "precision_clasificacion": _porcentaje(aciertos, comparables),
            "umbral_confianza": settings.CHAT_UMBRAL_CONFIANZA,
            "max_intercambios": settings.CHAT_MAX_INTERCAMBIOS,
        }

    @staticmethod
    def ollama_estado() -> dict:
        """Disponibilidad y latencia de Ollama.

        Las latencias son de este proceso desde el último arranque: sirven para
        ver si Ollama va lento ahora, no como histórico.
        """
        return {
            "disponible": ollama.disponible(),
            "ia_habilitada": settings.IA_HABILITADA,
            "modelo_embedding": settings.OLLAMA_MODELO_EMBEDDING,
            "modelo_texto": settings.OLLAMA_MODELO_TEXTO,
            "latencias_ms": ollama.latencias(),
        }

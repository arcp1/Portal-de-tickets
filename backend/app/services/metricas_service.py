"""Métricas del portal.

Cubre lo que piden la spec §13 (deflección, canales, tiempos, top 10) y la
Fase 2 §9 (normalización, sugerencias, utilidad, chatbot, latencia de Ollama).

Todo se calcula por sitio: un admin solo ve su planta.
"""

from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.plantas import de_planta
from app.models import (CANCELADO, Alerta, BaseConocimiento, ChatSesion, DispositivoIoT, SugerenciaKB,
                        Ticket, Usuario)
from app.services.ollama_client import ollama

# Canales en los que la incidencia se resolvió sin que un técnico interviniera.
#
# "visual" es el catálogo de fotos. Cuenta aquí por el mismo motivo que los
# demás —nadie de TI tocó la incidencia— y es donde se ve si documentar un
# defecto con foto valió la pena: si sube el recuento de este canal, hay tantos
# tickets menos.
CANALES_DEFLECTADOS = ("checklist", "kb", "ia", "visual")


def _porcentaje(parte: int, total: int) -> Optional[float]:
    """None y no 0 cuando no hay datos: un cero falso se lee como mal resultado."""
    if not total:
        return None
    return round(100.0 * parte / total, 1)


class MetricasService:

    @staticmethod
    def resumen(db: Session, sitio_id: Optional[int], dias: int = 30) -> dict:
        desde = datetime.utcnow() - timedelta(days=dias)
        del_sitio = db.query(Ticket).filter(de_planta(Ticket.sitio_id, sitio_id))
        # **Los cancelados no entran en nada de lo que mide la atención.** Los
        # retiró quien los reportó: nadie los resolvió —ni TI ni el
        # autoservicio—, así que contarlos bajaría la deflexión y engordaría
        # el total con trabajo que no hubo. Se cuentan aparte, abajo.
        base = del_sitio.filter(Ticket.estado != CANCELADO)
        cancelados = del_sitio.filter(Ticket.estado == CANCELADO)

        total = base.count()
        total_periodo = base.filter(Ticket.creado_en >= desde).count()
        ultima_semana = base.filter(
            Ticket.creado_en >= datetime.utcnow() - timedelta(days=7)
        ).count()

        # --- Distribución por canal (la métrica más importante de la spec) ---
        por_canal = dict(
            db.query(Ticket.canal_resolucion, func.count(Ticket.id))
            .filter(de_planta(Ticket.sitio_id, sitio_id), Ticket.estado != CANCELADO)
            .group_by(Ticket.canal_resolucion)
            .all()
        )
        por_canal = {(k or "sin_canal"): v for k, v in por_canal.items()}
        deflectados = sum(por_canal.get(c, 0) for c in CANALES_DEFLECTADOS)

        # --- Por categoría: el "top 10 de incidencias recurrentes" ---
        por_categoria = [
            {"categoria": cat, "total": n}
            for cat, n in db.query(Ticket.categoria, func.count(Ticket.id))
            .filter(de_planta(Ticket.sitio_id, sitio_id), Ticket.estado != CANCELADO)
            .group_by(Ticket.categoria)
            .order_by(func.count(Ticket.id).desc())
            .limit(10)
            .all()
        ]

        # --- Tiempo de resolución (solo los cerrados por un técnico) ---
        promedio_minutos = (
            db.query(func.avg(Ticket.tiempo_resolucion))
            .filter(
                de_planta(Ticket.sitio_id, sitio_id),
                Ticket.tiempo_resolucion.isnot(None),
                Ticket.canal_resolucion.notin_(CANALES_DEFLECTADOS),
            )
            .scalar()
        )

        # --- Fase 2: normalización ---
        normalizados = base.filter(Ticket.descripcion_normalizada.isnot(None)).count()

        # --- Satisfacción: lo que dijo quien reportó, de 1 a 5 ---
        # Es lo que el tiempo de resolución no cuenta: rápido no es lo mismo
        # que bien resuelto.
        por_estrellas = dict(
            db.query(Ticket.satisfaccion, func.count(Ticket.id))
            .filter(de_planta(Ticket.sitio_id, sitio_id), Ticket.satisfaccion.isnot(None),
                    Ticket.satisfaccion_en >= desde)
            .group_by(Ticket.satisfaccion).all()
        )
        respuestas = sum(por_estrellas.values())
        resueltos_periodo = base.filter(Ticket.estado.in_(["resuelto", "cerrado"]),
                                        Ticket.resuelto_en >= desde).count()
        satisfaccion = {
            "respuestas": respuestas,
            "promedio": (round(sum(k * v for k, v in por_estrellas.items()) / respuestas, 2)
                         if respuestas else None),
            "distribucion": {str(k): por_estrellas.get(k, 0) for k in range(1, 6)},
            # Cuántos de los resueltos en el periodo contestaron.
            "tasa_respuesta": _porcentaje(respuestas, resueltos_periodo),
        }

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
            "satisfaccion": satisfaccion,
            "descripcion_normalizada": normalizados,
            "tasa_normalizacion": _porcentaje(normalizados, total),
            # Aparte y fuera de todo lo anterior: ver `base`.
            "tickets_cancelados": cancelados.count(),
            "tickets_cancelados_periodo": cancelados.filter(Ticket.creado_en >= desde).count(),
        }

    @staticmethod
    def base_conocimiento(db: Session, sitio_id: Optional[int]) -> dict:
        # Sumado en la base. Antes se traía cada entrada entera —con su vector
        # de 768 números— solo para sumar dos contadores en Python.
        n_entradas, sugeridas, utiles = (
            db.query(
                func.count(BaseConocimiento.id),
                func.coalesce(func.sum(BaseConocimiento.veces_sugerida), 0),
                func.coalesce(func.sum(BaseConocimiento.veces_util), 0),
            )
            .filter(de_planta(BaseConocimiento.sitio_id, sitio_id))
            .one()
        )
        sugeridas, utiles = int(sugeridas), int(utiles)

        respondidas = (
            db.query(SugerenciaKB)
            .join(BaseConocimiento, SugerenciaKB.kb_id == BaseConocimiento.id)
            .filter(
                de_planta(BaseConocimiento.sitio_id, sitio_id),
                SugerenciaKB.fue_util.isnot(None),
            )
            .count()
        )

        hace_una_semana = datetime.utcnow() - timedelta(days=7)
        sugeridas_semana = (
            db.query(SugerenciaKB)
            .join(BaseConocimiento, SugerenciaKB.kb_id == BaseConocimiento.id)
            .filter(
                de_planta(BaseConocimiento.sitio_id, sitio_id),
                SugerenciaKB.creado_en >= hace_una_semana,
            )
            .count()
        )

        resueltas_por_kb = (
            db.query(Ticket)
            .filter(de_planta(Ticket.sitio_id, sitio_id), Ticket.canal_resolucion == "kb")
            .count()
        )

        return {
            "entradas_kb": n_entradas,
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
                de_planta(Ticket.sitio_id, sitio_id),
                Ticket.estado.in_(["resuelto", "cerrado"]),
                Ticket.indexado_kb.is_(False),
                # Las auto-resoluciones no se indexan a propósito: el checklist
                # ya existe y la sugerencia de KB ya estaba indexada.
                Ticket.canal_resolucion.notin_(CANALES_DEFLECTADOS),
            )
            .count(),
        }

    @staticmethod
    def chatbot(db: Session, sitio_id: Optional[int]) -> dict:
        """Sesiones, cuántas acabaron en ticket, y precisión del clasificador.

        **La sesión es de la planta de quien chateó.** Antes se filtraba por
        el sitio del ticket "o sin ticket todavía", y las sesiones sin ticket
        no tienen sitio: entraban las de todas las plantas. Además se leía cada
        sesión entera y se pedía su ticket uno por uno; ahora son dos conteos.
        """
        de_la_planta = (
            db.query(ChatSesion)
            .join(Usuario, ChatSesion.usuario_id == Usuario.id)
            .filter(de_planta(Usuario.sitio_id, sitio_id))
        )
        total = de_la_planta.count()
        con_ticket = de_la_planta.filter(ChatSesion.ticket_id.isnot(None)).count()

        # Precisión: categoría que detectó el modelo vs. la que quedó en el ticket.
        comparables, aciertos = (
            db.query(
                func.count(ChatSesion.id),
                func.coalesce(func.sum(case(
                    (Ticket.categoria == ChatSesion.categoria_detectada, 1), else_=0)), 0),
            )
            .join(Usuario, ChatSesion.usuario_id == Usuario.id)
            .join(Ticket, ChatSesion.ticket_id == Ticket.id)
            .filter(de_planta(Usuario.sitio_id, sitio_id), ChatSesion.categoria_detectada.isnot(None))
            .one()
        )
        aciertos = int(aciertos)

        return {
            "sesiones_iniciadas": total,
            "sesiones_con_ticket": con_ticket,
            "porcentaje_termino_en_ticket": _porcentaje(con_ticket, total),
            "clasificaciones_comparables": comparables,
            "precision_clasificacion": _porcentaje(aciertos, comparables),
            "umbral_confianza": settings.CHAT_UMBRAL_CONFIANZA,
            "max_intercambios": settings.CHAT_MAX_INTERCAMBIOS,
        }

    @staticmethod
    def sensores(db: Session, sitio_id: Optional[int], dias: int = 30) -> dict:
        """Los ESP32 de las plantas, en resumen: cuántos reportan ahora y
        cuántas alertas dieron en el periodo. El detalle vive en Monitoreo.

        «En línea» es lo mismo que dice Monitoreo (`api/iot.py`): activo y con
        un reporte más reciente que `IOT_SIN_SENAL_MINUTOS`.
        """
        ahora = datetime.utcnow()
        activos = db.query(DispositivoIoT).filter(
            DispositivoIoT.activo.is_(True), de_planta(DispositivoIoT.sitio_id, sitio_id))
        total = activos.count()
        en_linea = activos.filter(
            DispositivoIoT.ultimo_contacto >= ahora - timedelta(minutes=settings.IOT_SIN_SENAL_MINUTOS)
        ).count()
        tipos = ("iot_umbral", "iot_sin_senal")
        por_tipo = dict(
            db.query(Alerta.tipo, func.count(Alerta.id))
            .filter(Alerta.tipo.in_(tipos), de_planta(Alerta.sitio_id, sitio_id),
                    Alerta.creado_en >= ahora - timedelta(days=dias))
            .group_by(Alerta.tipo).all()
        )
        pendientes = (db.query(Alerta)
                      .filter(Alerta.tipo.in_(tipos), de_planta(Alerta.sitio_id, sitio_id),
                              Alerta.atendida_en.is_(None)).count())
        return {
            "dispositivos": total,
            "en_linea": en_linea,
            "alertas_periodo": sum(por_tipo.values()),
            "alertas_por_tipo": {t: por_tipo.get(t, 0) for t in tipos},
            "alertas_pendientes": pendientes,
            "sin_senal_minutos": settings.IOT_SIN_SENAL_MINUTOS,
            "periodo_dias": dias,
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

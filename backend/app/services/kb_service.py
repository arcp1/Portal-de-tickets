"""Base de conocimiento: indexación, búsqueda por similitud y utilidad.

Tres invariantes:

1. Solo se indexan tickets con solución escrita. Un ticket cerrado sin explicar
   cómo se resolvió no aporta nada y ensucia la búsqueda.
2. **Un ticket que el usuario resolvió solo no es conocimiento nuevo.** El
   checklist que lo resolvió ya existe y la sugerencia de KB que lo resolvió ya
   está indexada; volver a guardarlo duplica lo que ya había.
3. Nada de aquí puede tumbar una petición. Si Ollama o pgvector fallan, la
   búsqueda devuelve vacío y el flujo sigue al siguiente nivel.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import logger
from app.models import BaseConocimiento, SugerenciaKB, Ticket
from app.schemas.imagenes import breves
from app.services.horario_service import HorarioService
from app.services.ollama_client import normalizar_categoria, ollama


def titulo_de(texto: str, tope: int) -> str:
    """Un título de a lo más `tope` caracteres, cortado entre palabras.

    El título de lo que se indexa sale de la descripción, que es más larga que
    la columna: cortado a pelo quedaba "…la foto del problema y el m" en la
    lista de conocimiento. Se corta en el último espacio y el "…" avisa que
    el texto sigue.
    """
    texto = " ".join((texto or "").split())
    if len(texto) <= tope:
        return texto
    corte = texto[: tope - 1]
    espacio = corte.rfind(" ")
    if espacio > tope // 2:
        corte = corte[:espacio]
    return corte.rstrip(" ,;:.") + "…"


#: Canales en los que el propio usuario declara haberse resuelto la incidencia.
#:
#: Vive aquí, en el servicio, y no en la ruta que crea tickets — que es donde
#: estaba. **Esa es la corrección, no un detalle de organización.** La regla
#: "esto no se indexa" la aplicaba el llamador, así que `reindexar_kb.py`, que
#: llama por otro camino, no la conocía y sí los indexaba. Un ticket deflectado
#: por checklist no trae descripción del problema —lleva el nombre de la
#: categoría— y su "solución" dice literalmente que lo resolvió el checklist:
#: indexarlo mete en la base de conocimiento una entrada titulada "Impresora /
#: Etiquetadora" que no le contesta nada a nadie. Pasó exactamente así.
#:
#: Una regla que vive en quien llama es una regla que el siguiente que llame va
#: a saltarse sin enterarse.
# "visual" es el catálogo de fotos: la persona reconoció su defecto en una
# imagen y siguió la solución atada a ella. No se indexa, por lo mismo que
# los otros dos: la ficha ya está escrita y ya contesta.
CANALES_AUTOSERVICIO = ("checklist", "kb", "visual")


def solucion_es_valida(solucion: Optional[str]) -> bool:
    """Una solución sirve si explica algo. 'ok' o 'listo' no explican nada."""
    return bool(solucion and len(solucion.strip()) >= settings.SOLUCION_MIN_LONGITUD)


def construir_texto_indexable(ticket: Ticket) -> str:
    """categoría + descripción + solución + lo que se descartó.

    El descarte entra en el texto indexado a propósito: quien reporte la misma
    falla debe encontrar el ticket aunque su síntoma se parezca más a lo que se
    probó y no era, que a la solución final.
    """
    # **Las dos descripciones, no una u otra.**
    #
    # Antes la reescrita sustituia a la original, y eso apostaba la unica copia
    # indexada a que el modelo no hubiera metido nada de su cosecha. Con la
    # original dentro, aunque la reescritura invente una frase, lo que el
    # usuario dijo de verdad sigue estando en el texto que se busca — y encima
    # se recupera mejor, porque la gente pregunta con las palabras de la planta
    # ("no jala") y no con las del modelo ("no funciona correctamente").
    partes = [ticket.categoria, ticket.subcategoria, ticket.descripcion_original]
    if ticket.descripcion_normalizada:
        partes.append(ticket.descripcion_normalizada)
    partes.append(ticket.solucion)
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

        # El usuario se lo resolvió solo. La deflexión ya quedó contada al
        # crear el ticket; lo que resolvió —el paso del checklist, la entrada
        # de KB— ya estaba escrito antes. Aquí no hay conocimiento nuevo.
        if ticket.canal_resolucion in CANALES_AUTOSERVICIO:
            logger.info(
                "Ticket resuelto por autoservicio: no se indexa",
                extra={"ticket_id": ticket.id, "folio": ticket.folio,
                       "canal": ticket.canal_resolucion},
            )
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
                titulo=titulo_de(ticket.descripcion_normalizada or ticket.descripcion_original, 150),
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
                BaseConocimiento.embedding.isnot(None),
            )
            # Igual que en `RecuperacionService`: si la categoría no es una de
            # las seis, se busca en todas. Esto va ordenado por parecido y con
            # umbral, así que mirar de más no mete ruido —y una categoría
            # inventada dejaba la lista vacía, que el usuario lee como «no hay
            # nada escrito de esto» cuando sí lo hay.
            categoria_util = normalizar_categoria(categoria)
            if categoria_util:
                consulta = consulta.filter(BaseConocimiento.categoria == categoria_util)

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
                    # Pocas por búsqueda (KB_MAX_SUGERENCIAS): cargarlas una a
                    # una cuesta menos que traerlas para todas las candidatas,
                    # que el umbral descarta casi siempre.
                    # Las suyas y las de la solución del ticket del que
                    # salió, que la entrada enlaza.
                    "imagenes": breves(list(entrada.imagenes) + entrada.imagenes_de_ticket),
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
        # Agregado en la base: antes se traían las entradas enteras —cada una
        # con su vector de 768 números— solo para sumar dos contadores. Con
        # unas miles de entradas eran decenas de MB por cada vez que se abría
        # la pantalla.
        cuantas, sugeridas, utiles = db.query(
            func.count(BaseConocimiento.id),
            func.coalesce(func.sum(BaseConocimiento.veces_sugerida), 0),
            func.coalesce(func.sum(BaseConocimiento.veces_util), 0),
        ).one()
        sugeridas, utiles = int(sugeridas), int(utiles)

        respondidas = (
            db.query(SugerenciaKB)
            .join(BaseConocimiento, SugerenciaKB.kb_id == BaseConocimiento.id)
            .filter(
                SugerenciaKB.fue_util.isnot(None),
            )
            .count()
        )

        return {
            "entradas_kb": cuantas,
            "sugerencias_mostradas": sugeridas,
            "sugerencias_utiles": utiles,
            "sugerencias_respondidas": respondidas,
            # None y no 0: sin sugerencias mostradas la tasa no existe todavía.
            "tasa_utilidad": round(utiles / sugeridas, 4) if sugeridas else None,
            "umbral_actual": settings.KB_UMBRAL_SIMILITUD,
            "tickets_pendientes_indexar": db.query(Ticket)
            .filter(
                Ticket.estado.in_(["resuelto", "cerrado"]),
                Ticket.indexado_kb.is_(False),
            )
            .count(),
        }

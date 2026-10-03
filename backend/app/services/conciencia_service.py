"""Qué sabe la planta, cómo lo está aprendiendo y qué se le está escapando.

Las métricas que ya existían miden **lo que funcionó**: sugerencias útiles,
tickets deflectados, checklists que resolvieron. Todas contestan "¿está
sirviendo?". Ninguna contesta la pregunta anterior, que es la que de verdad
gobierna si puede servir: **¿de qué sabe algo el portal, y de qué no?**

Este módulo contesta esa, en tres niveles que van de lo general a lo particular:

    1. PANORAMA   — qué sabe la planta, por categoría. Dónde hay conocimiento y
                    dónde hay un hueco. Es el nivel que dice qué escribir.
    2. APRENDIZAJE— cómo entra ese conocimiento: ticket resuelto → indexado →
                    agrupado en procedimiento → tema nuevo. Y dónde se atasca
                    la tubería.
    3. CONSULTAS  — qué se preguntó de verdad y qué se recuperó para cada una.
                    Aquí se ven los fallos uno por uno.

**Por qué el orden importa.** Una respuesta mala del asistente se diagnostica al
revés de como se mira: parece un problema del modelo, y casi siempre es que no
había nada que recuperar. Con este orden, antes de tocar un umbral se ve si el
hueco era de conocimiento — que es lo que pasaba en esta planta el día que se
escribió esto: tres entradas en toda la base de conocimiento, las tres marcadas
como "impresora", y una de ellas hablando en realidad de una cuenta bloqueada.
Ningún ajuste de recuperación arregla eso.
"""

from collections import defaultdict
from datetime import datetime, timedelta
from typing import List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.plantas import de_planta
from app.models import (
    BaseConocimiento, ConsultaAsistente, DocumentoTI, SolucionGeneral,
    SugerenciaKB, TemaSugerido, Ticket,
)
from app.services.kb_service import CANALES_AUTOSERVICIO
from app.services.ollama_client import CATEGORIAS_VALIDAS, OllamaClient, normalizar_categoria

#: Los orígenes que significan "no se pudo contestar bien".
#:
#: `sin_fundamento` es un hueco limpio: no había nada parecido y el portal lo
#: dijo. `extractos` es más sutil y a menudo peor: **sí** se recuperó algo, pero
#: ningún modelo pudo fundamentar una respuesta encima — que suele ser señal de
#: un pasaje que empareja de refilón. Los dos piden documentación; el segundo,
#: además, gasta CPU antes de rendirse.
#:
#: Los tres `visual_*` son los mismos huecos del catálogo de fotos, y piden el
#: mismo trabajo por caminos distintos:
#:
#:   visual_sin_foto ..... describió algo que se ve y no teníamos foto de eso
#:   visual_ninguna ...... se le enseñaron fotos y ninguna era la suya
#:   visual_no_arreglo ... reconoció la foto y la solución no le funcionó
#:
#: Están escritos a mano y no importados de `visual_service` a propósito: ese
#: módulo importa **éste** para poder anotar, y traerse sus constantes cerraría
#: el círculo. Si se cambia el nombre de un origen allí, se cambia aquí.
ORIGENES_FALLIDOS = (
    "sin_fundamento", "extractos",
    "visual_sin_foto", "visual_ninguna", "visual_no_arreglo",
)


class ConcienciaService:

    # ------------------------------------------------------------------
    # Nivel 1 · PANORAMA — qué sabe la planta
    # ------------------------------------------------------------------
    @staticmethod
    def panorama(db: Session, sitio_id: Optional[int], dias: int = 30) -> dict:
        """El mapa del conocimiento, por categoría.

        Cada categoría trae dos cosas que hay que leer juntas: **cuánto sabe** y
        **cuánto le preguntan**. Una categoría con muchas consultas y poco
        conocimiento es el hueco más caro que tiene el portal, y es invisible en
        cualquier otra pantalla.
        """
        desde = datetime.utcnow() - timedelta(days=dias)

        # Se cuenta cada fuente por separado y después se junta por categoría.
        # Son cuatro consultas agregadas en vez de una con varios `join`: con
        # estos volúmenes da igual el costo, y así cada número se puede leer y
        # comprobar por su cuenta.
        kb = dict(
            db.query(BaseConocimiento.categoria, func.count(BaseConocimiento.id))
            .filter(de_planta(BaseConocimiento.sitio_id, sitio_id))
            .group_by(BaseConocimiento.categoria).all()
        )
        soluciones = dict(
            db.query(SolucionGeneral.categoria, func.count(SolucionGeneral.id))
            .filter(de_planta(SolucionGeneral.sitio_id, sitio_id),
                    SolucionGeneral.estado == "publicada")
            .group_by(SolucionGeneral.categoria).all()
        )
        documentos = dict(
            db.query(DocumentoTI.categoria, func.count(DocumentoTI.id))
            .filter(de_planta(DocumentoTI.sitio_id, sitio_id))
            .group_by(DocumentoTI.categoria).all()
        )
        resueltos = dict(
            db.query(Ticket.categoria, func.count(Ticket.id))
            .filter(de_planta(Ticket.sitio_id, sitio_id),
                    Ticket.estado.in_(("resuelto", "cerrado")))
            .group_by(Ticket.categoria).all()
        )
        consultas = dict(
            db.query(ConsultaAsistente.categoria, func.count(ConsultaAsistente.id))
            .filter(de_planta(ConsultaAsistente.sitio_id, sitio_id),
                    ConsultaAsistente.creado_en >= desde)
            .group_by(ConsultaAsistente.categoria).all()
        )
        fallidas = dict(
            db.query(ConsultaAsistente.categoria, func.count(ConsultaAsistente.id))
            .filter(de_planta(ConsultaAsistente.sitio_id, sitio_id),
                    ConsultaAsistente.creado_en >= desde,
                    ConsultaAsistente.origen.in_(ORIGENES_FALLIDOS))
            .group_by(ConsultaAsistente.categoria).all()
        )

        def normaliza(mapa: dict) -> dict:
            """Agrupa sin que mayúsculas o nulos partan una categoría en dos."""
            salida = defaultdict(int)
            for clave, valor in mapa.items():
                salida[(clave or "otro").strip().lower()] += valor
            return salida

        kb, soluciones = normaliza(kb), normaliza(soluciones)
        documentos, resueltos = normaliza(documentos), normaliza(resueltos)
        consultas, fallidas = normaliza(consultas), normaliza(fallidas)

        # Las seis del formulario **siempre** salen, tengan datos o no. Una
        # categoría vacía que no se dibuja es un hueco que nadie ve; dibujada en
        # cero, es una tarea. Es la diferencia entre una gráfica y una lista de
        # pendientes.
        nombres = set(CATEGORIAS_VALIDAS) | set(kb) | set(soluciones) | set(documentos)

        filas = []
        for nombre in sorted(nombres):
            sabe = kb[nombre] + soluciones[nombre] + documentos[nombre]
            preguntado = consultas[nombre]
            filas.append({
                "categoria": nombre,
                "conocimiento": sabe,
                "kb": kb[nombre],
                "soluciones": soluciones[nombre],
                "documentos": documentos[nombre],
                "tickets_resueltos": resueltos[nombre],
                "consultas": preguntado,
                "consultas_fallidas": fallidas[nombre],
                "estado": ConcienciaService._estado_categoria(
                    sabe, preguntado, fallidas[nombre]
                ),
            })

        total_sabe = sum(f["conocimiento"] for f in filas)
        return {
            "dias": dias,
            "categorias": filas,
            "total": {
                "conocimiento": total_sabe,
                "kb": sum(f["kb"] for f in filas),
                "soluciones": sum(f["soluciones"] for f in filas),
                "documentos": sum(f["documentos"] for f in filas),
                "consultas": sum(f["consultas"] for f in filas),
                "consultas_fallidas": sum(f["consultas_fallidas"] for f in filas),
                "categorias_vacias": sum(1 for f in filas if f["conocimiento"] == 0),
            },
        }

    @staticmethod
    def _estado_categoria(sabe: int, preguntado: int, fallidas: int) -> str:
        """Qué tan mal está una categoría, en una palabra.

        El orden de las comprobaciones es el mensaje: lo primero que se mira no
        es si acierta, es **si tiene con qué**.
        """
        if sabe == 0:
            # Sin nada escrito. Que además le pregunten lo vuelve urgente: cada
            # consulta que cae aquí es una persona que no recibió ayuda.
            return "hueco" if preguntado else "vacio"
        if preguntado and fallidas / preguntado >= 0.5:
            # Hay conocimiento y aun así falla la mitad de las veces: o no es el
            # conocimiento que hace falta, o está mal etiquetado.
            return "flojo"
        return "cubierto"

    # ------------------------------------------------------------------
    # Nivel 2 · APRENDIZAJE — cómo entra el conocimiento
    # ------------------------------------------------------------------
    @staticmethod
    def aprendizaje(db: Session, sitio_id: Optional[int], dias: int = 30) -> dict:
        """La tubería por la que el portal aprende, y dónde se atasca.

        El recorrido es: **un ticket se resuelve → se indexa → varios parecidos
        se consolidan en un procedimiento → lo que no encaja en ninguna
        categoría se propone como tema nuevo.** Cada etapa puede atascarse por
        su cuenta, y atascada no avisa: simplemente el portal deja de aprender y
        nadie se entera hasta que alguien pregunta por qué el asistente no sabe
        nada nuevo desde hace tres meses.
        """
        desde = datetime.utcnow() - timedelta(days=dias)

        # **Material del que se puede aprender**, que no es lo mismo que
        # "tickets resueltos".
        #
        # Un ticket que el usuario se resolvió solo con el checklist no trae
        # conocimiento nuevo: el paso que lo resolvió ya estaba escrito, y el
        # ticket ni siquiera lleva descripción del problema —lleva el nombre de
        # la categoría—. Contarlo aquí haría que la tubería pidiera para
        # siempre indexar algo que, con razón, nunca se va a indexar. Ver
        # `CANALES_AUTOSERVICIO` en `kb_service`.
        indexables = (
            de_planta(Ticket.sitio_id, sitio_id),
            Ticket.estado.in_(("resuelto", "cerrado")),
            Ticket.canal_resolucion.notin_(CANALES_AUTOSERVICIO)
            | Ticket.canal_resolucion.is_(None),
        )

        resueltos = db.query(func.count(Ticket.id)).filter(*indexables).scalar() or 0

        indexados = db.query(func.count(BaseConocimiento.id)).filter(
            de_planta(BaseConocimiento.sitio_id, sitio_id),
            BaseConocimiento.ticket_origen_id.isnot(None),
        ).scalar() or 0

        # Tickets resueltos que se quedaron fuera de la base de conocimiento.
        #
        # El cierre de un ticket **nunca se bloquea** por culpa de la IA: si
        # Ollama estaba caído en ese momento, el ticket se cierra igual y queda
        # con `indexado_kb = False` esperando a `reindexar_kb.py`. El diseño lo
        # previó; lo que faltaba era que alguien se enterara de que hay cola
        # esperando, porque el portal no lo dice por su cuenta y el
        # conocimiento de esos tickets simplemente no existe para nadie.
        pendientes_indexar = db.query(func.count(Ticket.id)).filter(
            *indexables, Ticket.indexado_kb.is_(False)
        ).scalar() or 0

        # Sin embedding no participa en ninguna búsqueda: está guardado y es
        # como si no existiera. Pasa cuando Ollama estaba caído al indexar, y no
        # se arregla solo — hay que correr `reindexar_kb.py`.
        sin_vector = db.query(func.count(BaseConocimiento.id)).filter(
            de_planta(BaseConocimiento.sitio_id, sitio_id),
            BaseConocimiento.embedding.is_(None),
        ).scalar() or 0

        borradores = db.query(func.count(SolucionGeneral.id)).filter(
            de_planta(SolucionGeneral.sitio_id, sitio_id),
            SolucionGeneral.estado == "borrador",
        ).scalar() or 0
        publicadas = db.query(func.count(SolucionGeneral.id)).filter(
            de_planta(SolucionGeneral.sitio_id, sitio_id),
            SolucionGeneral.estado == "publicada",
        ).scalar() or 0

        temas_listos = db.query(func.count(TemaSugerido.id)).filter(
            de_planta(TemaSugerido.sitio_id, sitio_id),
            TemaSugerido.estado == "listo",
        ).scalar() or 0
        temas_pendientes = db.query(func.count(TemaSugerido.id)).filter(
            de_planta(TemaSugerido.sitio_id, sitio_id),
            TemaSugerido.estado == "pendiente",
        ).scalar() or 0

        # --- El lazo de realimentación: ¿lo que se sugiere, sirve? ---
        #
        # Dos `count` con filtro en vez de sumar un booleano convertido a
        # entero: la conversión se escribe distinto en Postgres y en SQLite —y
        # las pruebas corren sobre SQLite—, mientras que contar filas que
        # cumplen una condición significa lo mismo en los dos.
        def _votos(condicion):
            return db.query(func.count(SugerenciaKB.id)).join(
                BaseConocimiento, BaseConocimiento.id == SugerenciaKB.kb_id
            ).filter(
                de_planta(BaseConocimiento.sitio_id, sitio_id), condicion
            ).scalar() or 0

        votados = _votos(SugerenciaKB.fue_util.isnot(None))
        utiles = _votos(SugerenciaKB.fue_util.is_(True))

        consultas_total = db.query(func.count(ConsultaAsistente.id)).filter(
            de_planta(ConsultaAsistente.sitio_id, sitio_id),
            ConsultaAsistente.creado_en >= desde,
        ).scalar() or 0
        consultas_fallidas = db.query(func.count(ConsultaAsistente.id)).filter(
            de_planta(ConsultaAsistente.sitio_id, sitio_id),
            ConsultaAsistente.creado_en >= desde,
            ConsultaAsistente.origen.in_(ORIGENES_FALLIDOS),
        ).scalar() or 0

        return {
            "dias": dias,
            # Las etapas, en el orden en que ocurren. `atasco` marca la primera
            # que no está dejando pasar nada — que es por donde hay que empezar.
            "etapas": [
                {
                    "clave": "resueltos",
                    "valor": resueltos,
                    "de": None,
                },
                {
                    "clave": "indexados",
                    "valor": indexados,
                    "de": resueltos,
                    "atasco": resueltos > 0 and indexados == 0,
                },
                {
                    "clave": "procedimientos",
                    "valor": publicadas,
                    "de": indexados,
                    # Hace falta un mínimo de tickets del mismo problema para
                    # que haya patrón. Por debajo de eso no es que falle: es
                    # que todavía no toca.
                    "atasco": indexados >= settings.SOLUCION_GENERAL_MIN_TICKETS
                              and publicadas == 0 and borradores == 0,
                },
                {
                    "clave": "temas",
                    "valor": temas_listos,
                    "de": temas_pendientes + temas_listos,
                },
            ],
            "pendientes_indexar": pendientes_indexar,
            "pendiente_de_revision": borradores,
            "temas_pendientes": temas_pendientes,
            "sin_vector": sin_vector,
            "realimentacion": {
                "votados": votados,
                "utiles": utiles,
                "ratio": round(utiles / votados, 3) if votados else None,
            },
            "consultas": {
                "total": consultas_total,
                "fallidas": consultas_fallidas,
                "ratio_fallo": (round(consultas_fallidas / consultas_total, 3)
                                if consultas_total else None),
            },
            "avisos": ConcienciaService.avisos_de_calidad(db, sitio_id),
        }

    # ------------------------------------------------------------------
    @staticmethod
    def avisos_de_calidad(db: Session, sitio_id: Optional[int], limite: int = 20) -> List[dict]:
        """Entradas de conocimiento cuya etiqueta no concuerda con su texto.

        **Esto encontró un error real el día que se escribió.** La base tenía
        tres entradas, las tres marcadas como `impresora`; una hablaba de una
        cuenta bloqueada por intentos fallidos. Con el filtro por categoría
        funcionando *correctamente*, esa entrada salía como respuesta a
        preguntas sobre impresoras — y el síntoma parecía un fallo del modelo.

        La comprobación es deliberadamente tonta: se pasa el texto por
        ``VOCABULARIO_PLANTA``, la misma tabla de palabras con la que el chat
        clasifica sin llamar a ningún modelo. Es determinista, cuesta
        milisegundos y se corrige editando una línea de esa tabla si se
        equivoca. Un modelo aquí sería más caro, menos auditable, y estaríamos
        usando IA para arreglar los datos con los que se alimenta la IA.

        Solo señala. **No corrige nada**: una etiqueta la cambia una persona,
        porque el vocabulario acierta en lo evidente y no en lo ambiguo ("la
        impresora no aparece en la red" es las dos cosas).
        """
        entradas = db.query(BaseConocimiento).filter(
            de_planta(BaseConocimiento.sitio_id, sitio_id)
        ).all()

        avisos = []
        for entrada in entradas:
            etiqueta = (entrada.categoria or "").strip().lower()
            voto = OllamaClient.clasificar_por_vocabulario(
                f"{entrada.titulo} {entrada.contenido}"
            )
            # Sin voto no hay discrepancia que señalar: el vocabulario no
            # reconoció nada, o hubo empate. En la duda se calla.
            if not voto or voto["categoria"] == etiqueta:
                continue
            avisos.append({
                "tipo": "categoria_dudosa",
                "kb_id": entrada.id,
                "titulo": entrada.titulo,
                "etiqueta": etiqueta,
                "sugerida": voto["categoria"],
                "confianza": voto["confianza"],
            })
            if len(avisos) >= limite:
                break

        return avisos

    # ------------------------------------------------------------------
    # Nivel 3 · CONSULTAS — qué se preguntó y qué se encontró
    # ------------------------------------------------------------------
    @staticmethod
    def consultas(
        db: Session,
        sitio_id: int,
        dias: int = 30,
        solo_fallidas: bool = False,
        categoria: Optional[str] = None,
        limite: int = 50,
    ) -> dict:
        """Las consultas recientes, de la más nueva a la más vieja.

        `solo_fallidas` deja las que no se pudieron contestar, que es la lista
        con la que se decide qué documentar el lunes.
        """
        desde = datetime.utcnow() - timedelta(days=dias)

        consulta = db.query(ConsultaAsistente).filter(
            de_planta(ConsultaAsistente.sitio_id, sitio_id),
            ConsultaAsistente.creado_en >= desde,
        )
        if solo_fallidas:
            consulta = consulta.filter(ConsultaAsistente.origen.in_(ORIGENES_FALLIDOS))
        if categoria:
            consulta = consulta.filter(
                ConsultaAsistente.categoria == (normalizar_categoria(categoria) or ""))

        filas = consulta.order_by(
            ConsultaAsistente.creado_en.desc()
        ).limit(min(limite, 200)).all()

        por_origen = dict(
            db.query(ConsultaAsistente.origen, func.count(ConsultaAsistente.id))
            .filter(de_planta(ConsultaAsistente.sitio_id, sitio_id),
                    ConsultaAsistente.creado_en >= desde)
            .group_by(ConsultaAsistente.origen).all()
        )

        return {
            "dias": dias,
            "por_origen": por_origen,
            "consultas": [
                {
                    "id": c.id,
                    "pregunta": c.pregunta,
                    "categoria": c.categoria,
                    "pasajes": c.pasajes,
                    "mejor_similitud": (round(c.mejor_similitud, 3)
                                        if c.mejor_similitud is not None else None),
                    "mejor_fuente": c.mejor_fuente,
                    "origen": c.origen,
                    "duracion_ms": c.duracion_ms,
                    "creado_en": c.creado_en.isoformat() if c.creado_en else None,
                }
                for c in filas
            ],
        }

    # ------------------------------------------------------------------
    @staticmethod
    def registrar(
        db: Session,
        sitio_id: int,
        usuario_id: Optional[int],
        pregunta: str,
        categoria: Optional[str],
        resultado: dict,
        duracion_ms: Optional[int] = None,
    ) -> None:
        """Deja constancia de una consulta. **Nunca levanta.**

        Apuntar lo que pasó no puede impedir que pase. Si esto falla, la
        persona recibe su respuesta igual y lo único que se pierde es una fila
        de una bitácora, que es exactamente el orden de prioridades correcto.
        """
        try:
            fuentes = resultado.get("fuentes") or []
            mejor = fuentes[0] if fuentes else None

            db.add(ConsultaAsistente(
                sitio_id=sitio_id,
                usuario_id=usuario_id,
                # Se recorta al límite de lo que el formulario acepta: una
                # bitácora no tiene por qué guardar más de lo que se pudo pedir.
                pregunta=(pregunta or "")[:2000],
                categoria=(categoria or None),
                pasajes=len(fuentes),
                mejor_similitud=mejor.get("similitud") if mejor else None,
                mejor_fuente=mejor.get("fuente") if mejor else None,
                origen=resultado.get("origen") or "desconocido",
                duracion_ms=duracion_ms,
            ))
            db.commit()
        except Exception:  # noqa: BLE001 - la bitácora jamás rompe la consulta
            db.rollback()
            # Sin `logger.error`: si la base está caída, esto se dispararía en
            # cada consulta y llenaría el disco de registros sobre no poder
            # escribir registros.

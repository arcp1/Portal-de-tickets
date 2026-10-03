"""De dónde sale lo que el asistente sabe.

**No lo sabe el modelo. Lo sabe la planta.**

Un modelo de lenguaje, por bueno que sea, no tiene forma de saber que en esta
planta la raya negra de la impresora del almacén es el rodillo y no el tóner. Eso
no está en internet: está en los tickets que TI ya resolvió y en la documentación
que TI ya escribió. Si se le pregunta a Gemini a secas, va a inventar una
respuesta genérica y plausible, que es la peor clase de respuesta equivocada.

Por eso el orden es al revés de lo que parece:

    1. Se busca en lo nuestro.   ← aquí, este archivo
    2. Si no hay nada parecido, NO se le pregunta a ningún modelo.
    3. Si sí hay, el modelo solo redacta lo encontrado y cita de dónde salió.

Este módulo hace el paso 1: busca por significado en las **dos** fuentes propias
—tickets resueltos y documentación de TI— y devuelve pasajes con su procedencia,
para que después se pueda enseñar en pantalla de dónde salió cada cosa.

Buscar "por significado" quiere decir que "sale una raya negra al imprimir"
encuentra el ticket que decía "línea vertical oscura en las hojas", aunque no
compartan ninguna palabra. Eso lo hace el modelo de embeddings local, gratis y
sin que nada salga de la planta.
"""

from dataclasses import dataclass, field
from typing import List, Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import logger
from app.models import BaseConocimiento, DocumentoTI, SolucionGeneral, Ticket
from app.services.ollama_client import normalizar_categoria, ollama


@dataclass
class Pasaje:
    """Un fragmento de conocimiento propio, con su procedencia.

    La procedencia no es un adorno: es lo que permite que el técnico abra el
    ticket original y compruebe. Una respuesta sin fuente no se puede verificar,
    y lo que no se puede verificar no se debería seguir en una planta.
    """
    fuente: str              # "ticket" | "documento"
    referencia_id: int
    titulo: str
    texto: str
    similitud: float
    categoria: Optional[str] = None
    descartado: Optional[str] = None      # lo que ya se probó y no sirvió
    etiquetas: List[str] = field(default_factory=list)

    def a_dict(self) -> dict:
        return {
            "fuente": self.fuente,
            "referencia_id": self.referencia_id,
            "titulo": self.titulo,
            "texto": self.texto,
            "similitud": round(self.similitud, 4),
            "categoria": self.categoria,
            "descartado": self.descartado,
        }

    def para_el_modelo(self, numero: int, incluir_descarte: bool = True) -> str:
        """Cómo se le presenta al modelo.

        `incluir_descarte` existe por un fallo real y medido. Con el descarte en
        el contexto, qwen2.5:3b leyó "se cambió el tóner y no era eso" y escribió
        como paso 3: *"cambiar el tóner completo nuevamente"*. Invirtió el
        sentido y recomendó justo lo que no sirve.

        Un modelo chico no distingue de forma confiable entre "esto se probó" y
        "esto se hace". Los grandes sí. Así que **al local no se le da el
        descarte y al de pago sí**; a la persona se le muestra siempre, junto a
        la fuente, donde no hay modelo que pueda invertirlo.
        """
        cabecera = f"[{numero}] {self.titulo}"
        cuerpo = self.texto.strip()
        if incluir_descarte and self.descartado:
            cuerpo += f"\n\nYa se probó y NO era la causa: {self.descartado.strip()}"
        return f"{cabecera}\n{cuerpo}"


def ajuste_por_utilidad(veces_util: Optional[int], veces_sugerida: Optional[int]) -> float:
    """Cuánto sube o baja un pasaje según le haya servido a la gente.

    El portal lleva años preguntando "¿te sirvió?" bajo cada sugerencia y
    guardando la respuesta en ``veces_util`` / ``veces_sugerida``. Hasta ahora
    eso solo alimentaba una métrica en una pantalla: **la búsqueda no se
    enteraba**. Un pasaje que ya resolvió el problema a cinco personas se
    ordenaba igual que uno que nunca le sirvió a nadie.

    **Suavizado, porque con pocos datos esto es ruido.** Un "sí me sirvió" de
    una sola sugerencia no es evidencia de nada; si se tomara al pie de la
    letra, el primer voto mandaría un pasaje al principio de la lista para
    siempre. La regla de Laplace —sumar un acierto y un fallo imaginarios—
    arranca en 0,5 con cero votos, que da un ajuste de exactamente cero, y hace
    falta acumular votos para moverse de ahí:

        0 de 0 votos  ->  0,50  ->  sin cambio
        1 de 1        ->  0,67  ->  +1/3 del peso
        5 de 5        ->  0,86  ->  +5/7 del peso
        0 de 5        ->  0,14  ->  -5/7 del peso

    **Y el peso es pequeño a propósito.** Es una preferencia, no un veto: nunca
    debe poder rescatar un pasaje que no habla del tema ni hundir al único que
    sí. Por eso vale menos que la ventaja que ya tenían las soluciones
    generales (0,05): que a alguien le sirviera es señal más débil que estar
    escrito para responder justo esa clase de pregunta.
    """
    sugeridas = max(0, veces_sugerida or 0)
    utiles = min(max(0, veces_util or 0), sugeridas)

    utilidad = (utiles + 1) / (sugeridas + 2)
    # De [0, 1] a [-1, 1], y de ahí a [-peso, +peso].
    return settings.RECUPERACION_PESO_UTILIDAD * (2 * utilidad - 1)


class RecuperacionService:

    @staticmethod
    def _categoria_util(categoria: Optional[str]) -> Optional[str]:
        """La categoría, si es una de las de verdad; si no, ninguna.

        **Por qué hace falta.** `categoria` llega del cuerpo de la petición sin
        validar, y antes se aplicaba con `ILIKE`. Tres consecuencias, las tres
        silenciosas:

        - `%` es un comodín de LIKE: pedir la categoría `%` desactivaba el
          filtro sin que nada lo dijera.
        - `imp%` casaba con «impresora». Un filtro que casa de más no es un
          filtro.
        - Una categoría inventada no casaba con nada, la búsqueda volvía vacía
          y el asistente contestaba «de esto no tenemos nada escrito» — una
          respuesta falsa, y de las peores, porque suena a respuesta.

        **Por qué se ignora en vez de rechazar.** Devolver un 422 rompería una
        pantalla por un filtro, que es un detalle de la consulta. Buscar en
        todo devuelve de más, no de menos, y el orden por parecido ya pone
        delante lo que toca. Queda anotado para quien mire el registro.
        """
        limpia = normalizar_categoria(categoria)
        if categoria and limpia is None:
            logger.warning("Categoría desconocida en una búsqueda; se busca en todas",
                           extra={"categoria": str(categoria)[:50]})
        return limpia

    @staticmethod
    def buscar(
        db: Session,
        texto: str,
        sitio_id: int,
        categoria: Optional[str] = None,
        limite: Optional[int] = None,
        umbral: Optional[float] = None,
        incluir_documentacion: bool = True,
        vector: Optional[List[float]] = None,
    ) -> List[Pasaje]:
        """Los pasajes propios más parecidos a la pregunta, de más a menos.

        Devuelve una lista vacía si no hay nada suficientemente parecido o si el
        modelo de embeddings no está disponible. **La lista vacía es una
        respuesta legítima**, no un error: significa "de esto no tenemos nada
        escrito", y quien llama debe decirlo tal cual en vez de inventar.

        ``vector`` deja pasar un embedding ya calculado. Lo usa el endpoint que
        alimenta el grafo, que necesita cronometrar la vectorización y la
        búsqueda por separado para poder encender un nodo distinto en cada una.
        Sin esto tendría que vectorizar dos veces la misma pregunta — ~80 ms de
        CPU regalados por consulta, en la máquina donde la CPU es el recurso
        escaso.
        """
        limite = limite or settings.RECUPERACION_MAX_PASAJES
        umbral = umbral if umbral is not None else settings.RECUPERACION_UMBRAL
        # Se normaliza aquí, una vez, y no en cada consulta: así todo lo de
        # abajo trabaja con una categoría de verdad o con ninguna.
        categoria = RecuperacionService._categoria_util(categoria)

        if vector is None:
            vector = ollama.generar_embedding(texto, tarea="consulta")
        if vector is None:
            logger.warning("Sin embeddings no hay recuperación; se sigue sin asistente")
            return []

        pasajes: List[Pasaje] = []
        pasajes += RecuperacionService._de_soluciones(db, vector, sitio_id, limite)
        pasajes += RecuperacionService._de_tickets(db, vector, sitio_id, categoria, limite)
        if incluir_documentacion:
            pasajes += RecuperacionService._de_documentacion(db, vector, sitio_id, limite)

        # Se mezclan las dos fuentes y gana la similitud, no el origen: si la
        # documentación explica mejor el problema que un ticket viejo, debe ir
        # primero.
        pasajes = [p for p in pasajes if p.similitud >= umbral]
        pasajes.sort(key=lambda p: p.similitud, reverse=True)
        if not pasajes:
            return []

        # --- Corte relativo, y es el que de verdad quita el ruido ---
        #
        # Un umbral fijo no alcanza. Medido con datos reales: la pregunta "me
        # sale una línea oscura al imprimir" trae el ticket correcto al 69%,
        # pero también "cuenta bloqueada por intentos fallidos" al 64%. Los dos
        # pasan cualquier umbral que deje pasar al bueno.
        #
        # Lo que los separa no es el número absoluto sino la distancia entre
        # ellos: había cinco puntos entre el bueno y el ruido, así que el corte
        # va en cuatro. Y si dos pasajes empatan arriba, los dos sirven.
        # Cuántos candidatos plausibles había **antes** de aplicar el corte
        # relativo. Se guarda ahora porque el corte de más abajo lo necesita, y
        # después de filtrar ya no se puede saber.
        candidatos = len(pasajes)

        mejor = pasajes[0].similitud
        piso = mejor - settings.RECUPERACION_MARGEN
        pasajes = [p for p in pasajes if p.similitud >= piso]

        # --- Cuando no hubo NADA con qué comparar, el listón sube ---
        #
        # El corte de arriba funciona midiendo **distancias entre candidatos**.
        # Si solo apareció un candidato en toda la búsqueda, no hay distancia
        # que medir: el mejor es también el peor y pasa por definición.
        #
        # Ese es el caso de una base de conocimiento pequeña. Medido aquí: "el
        # escáner del andén 3 no manda nada al sistema" recuperó **un** pasaje
        # al 66% sobre una cuenta bloqueada. Pasó el umbral general por cuatro
        # puntos, se le dieron 27 segundos de CPU al modelo para redactar sobre
        # él, la comprobación de anclaje lo rechazó —correctamente— y la
        # persona acabó viendo un extracto que no tenía nada que ver.
        #
        # **La condición es `candidatos`, no `len(pasajes)`, y la diferencia
        # importa.** Escrito sobre los que sobreviven al corte relativo, esto
        # rompía un caso que el portal resolvía bien: tres candidatos al 69, 64
        # y 62 por ciento, de los que el corte deja uno. Ahí sí hubo
        # comparación y el ganador le sacó cinco puntos a dos rivales — eso es
        # evidencia, y descartarla confunde "no había con qué comparar" con
        # "hubo comparación y ganó uno claramente". Lo atrapó
        # `test_lo_que_queda_muy_por_debajo_del_mejor_se_descarta`, que existía
        # desde antes.
        #
        # **Tampoco es lo mismo que subir `RECUPERACION_UMBRAL`.** Ese umbral
        # se aplicaría también cuando varios pasajes se refuerzan entre sí, que
        # es donde el sistema acierta. Lo que se endurece aquí es la ausencia
        # de corroboración, no la búsqueda entera.
        if candidatos < 2 and pasajes[0].similitud < settings.RECUPERACION_UMBRAL_SOLITARIO:
            logger.info(
                "Un solo pasaje y sin corroboración: no alcanza para responder",
                extra={"similitud": round(pasajes[0].similitud, 3),
                       "minimo": settings.RECUPERACION_UMBRAL_SOLITARIO,
                       "fuente": pasajes[0].fuente},
            )
            return []

        return pasajes[:limite]

    # ------------------------------------------------------------------
    @staticmethod
    def _de_soluciones(db, vector, sitio_id, limite) -> List[Pasaje]:
        """Los procedimientos consolidados y ya revisados por TI.

        Llevan una ventaja deliberada sobre las demás fuentes: están escritas
        para responder justo esta clase de pregunta, mientras que un ticket
        cuenta lo que pasó un día concreto. Cuando existe una solución general
        del problema, es la que debe contestar.

        Solo las publicadas. Un borrador sin revisar no le contesta a nadie.
        """
        try:
            filas = db.query(
                SolucionGeneral,
                SolucionGeneral.embedding.cosine_distance(vector).label("distancia"),
            ).filter(
                SolucionGeneral.estado == "publicada",
                SolucionGeneral.embedding.isnot(None),
            ).order_by("distancia").limit(limite).all()
        except Exception as exc:  # noqa: BLE001 - degradación deliberada
            logger.error("Fallo buscando en las soluciones generales",
                         extra={"error": str(exc)})
            return []

        return [
            Pasaje(
                fuente="solucion_general",
                referencia_id=sol.id,
                titulo=sol.titulo,
                texto=sol.contenido,
                # La ventaja va aquí y no en el orden, para que un ticket
                # claramente mejor todavía pueda ganarle. Se suma también lo
                # que la gente haya dicho de esta solución en concreto.
                similitud=min(1.0, (1.0 - float(distancia))
                              + settings.RECUPERACION_VENTAJA_GENERAL
                              + ajuste_por_utilidad(sol.veces_util, sol.veces_sugerida)),
                categoria=sol.categoria,
                descartado=sol.descartado,
            )
            for sol, distancia in filas
        ]

    @staticmethod
    def _de_tickets(db, vector, sitio_id, categoria, limite) -> List[Pasaje]:
        """Lo que ya se resolvió alguna vez, con su solución."""
        try:
            # Se trae también la solución del ticket de origen. La búsqueda usa
            # el texto completo —categoría, descripción y solución— porque así
            # encuentra mejor; pero lo que se le enseña a la persona y lo que se
            # le da al modelo es **solo la solución**. Lo demás es el reporte del
            # problema, que quien pregunta ya conoce: repetírselo estorba.
            consulta = db.query(
                BaseConocimiento,
                BaseConocimiento.embedding.cosine_distance(vector).label("distancia"),
                Ticket.solucion,
            ).outerjoin(
                Ticket, Ticket.id == BaseConocimiento.ticket_origen_id
            ).filter(
                BaseConocimiento.embedding.isnot(None),
            )
            if categoria:
                # Igualdad y no `ilike`: la categoría ya viene normalizada por
                # `_categoria_util`, así que no hay nada que interpretar. De
                # paso el filtro pasa a usar el índice `(sitio_id, categoria)`
                # en vez de traerse todo el sitio y descartar después —medido
                # con 5000 entradas: 833 filas leídas en vez de 1666—.
                consulta = consulta.filter(BaseConocimiento.categoria == categoria)
            filas = consulta.order_by("distancia").limit(limite * 2).all()
        except Exception as exc:  # noqa: BLE001 - degradación deliberada
            logger.error("Fallo buscando en la base de conocimiento",
                         extra={"error": str(exc)})
            return []

        return [
            Pasaje(
                fuente="ticket",
                referencia_id=entrada.id,
                titulo=entrada.titulo,
                texto=(solucion or entrada.contenido).strip(),
                similitud=min(1.0, (1.0 - float(distancia))
                              + ajuste_por_utilidad(entrada.veces_util,
                                                    entrada.veces_sugerida)),
                categoria=entrada.categoria,
                descartado=getattr(entrada, "descartado", None),
                etiquetas=(entrada.tags or "").split(","),
            )
            for entrada, distancia, solucion in filas
        ]

    @staticmethod
    def _de_documentacion(db, vector, sitio_id, limite) -> List[Pasaje]:
        """Los procedimientos que TI escribió a mano.

        Se excluye lo marcado como sensible: credenciales y direccionamiento no
        tienen por qué acabar en la respuesta de un chat, y menos si esa
        respuesta va a pasar por un servicio de terceros.
        """
        try:
            filas = db.query(
                DocumentoTI,
                DocumentoTI.embedding.cosine_distance(vector).label("distancia"),
            ).filter(
                DocumentoTI.embedding.isnot(None),
                DocumentoTI.sensible.is_(False),
            ).order_by("distancia").limit(limite * 2).all()
        except Exception as exc:  # noqa: BLE001 - degradación deliberada
            logger.error("Fallo buscando en la documentación de TI",
                         extra={"error": str(exc)})
            return []

        return [
            Pasaje(
                fuente="documento",
                referencia_id=doc.id,
                titulo=doc.titulo,
                texto=doc.contenido,
                similitud=1.0 - float(distancia),
                categoria=doc.categoria,
                etiquetas=(doc.etiquetas or "").split(","),
            )
            for doc, distancia in filas
        ]

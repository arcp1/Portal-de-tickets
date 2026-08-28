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
from app.services.ollama_client import ollama


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


class RecuperacionService:

    @staticmethod
    def buscar(
        db: Session,
        texto: str,
        sitio_id: int,
        categoria: Optional[str] = None,
        limite: Optional[int] = None,
        umbral: Optional[float] = None,
        incluir_documentacion: bool = True,
    ) -> List[Pasaje]:
        """Los pasajes propios más parecidos a la pregunta, de más a menos.

        Devuelve una lista vacía si no hay nada suficientemente parecido o si el
        modelo de embeddings no está disponible. **La lista vacía es una
        respuesta legítima**, no un error: significa "de esto no tenemos nada
        escrito", y quien llama debe decirlo tal cual en vez de inventar.
        """
        limite = limite or settings.RECUPERACION_MAX_PASAJES
        umbral = umbral if umbral is not None else settings.RECUPERACION_UMBRAL

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
        mejor = pasajes[0].similitud
        piso = mejor - settings.RECUPERACION_MARGEN
        pasajes = [p for p in pasajes if p.similitud >= piso]

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
                SolucionGeneral.sitio_id == sitio_id,
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
                # claramente mejor todavía pueda ganarle.
                similitud=min(1.0, (1.0 - float(distancia)) + settings.RECUPERACION_VENTAJA_GENERAL),
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
                BaseConocimiento.sitio_id == sitio_id,
                BaseConocimiento.embedding.isnot(None),
            )
            if categoria:
                consulta = consulta.filter(BaseConocimiento.categoria.ilike(categoria))
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
                similitud=1.0 - float(distancia),
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
                DocumentoTI.sitio_id == sitio_id,
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

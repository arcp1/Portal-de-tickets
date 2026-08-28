"""De muchos tickets parecidos, un solo procedimiento.

**El problema que resuelve.** Diez tickets sobre la misma impresora dejan diez
soluciones parecidas y ninguna completa. Cada una cuenta lo que pasó ese día; el
técnico nuevo tiene que leerlas todas y deducir el patrón. Lo que hace falta es un
solo texto que diga: *esto es lo que suele ser, esto se revisa primero, esto ya se
descartó*.

**Aquí es donde el modelo de pago se gana el sueldo.** Redactar sobre diez tickets
a la vez, encontrando el patrón y no repitiendo lo mismo tres veces, es
exactamente lo que un modelo de 3B no puede hacer. Y es una consulta **por
problema y por mes**, no una por ticket: el gasto no escala con el uso del portal.

**Nada se publica solo.** La máquina propone el borrador; TI lo lee, lo corrige y
lo publica. Un procedimiento equivocado en una planta se paga caro, y la firma de
una persona es lo único que separa un procedimiento de una sugerencia.

Una vez publicada, la solución general entra en la búsqueda del asistente como
una fuente más —y normalmente gana, porque está escrita para responder justo esa
pregunta—.
"""

from datetime import datetime
from typing import List, Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import logger
from app.models import BaseConocimiento, SolucionGeneral, Usuario
from app.services.gemini_client import gemini
from app.services.ollama_client import ollama

BORRADOR = "borrador"
PUBLICADA = "publicada"
ARCHIVADA = "archivada"

PROMPT = """Eres un técnico de soporte de TI con años en una planta industrial.

Abajo hay varios tickets que ya se resolvieron y que tratan del MISMO problema.
Cada uno cuenta lo que pasó ese día. Tu trabajo es escribir el procedimiento
único que le sirva al que venga después.

Escribe en español de México, en este formato exacto:

SÍNTOMA: una línea. Cómo se ve el problema desde fuera.
CAUSA MÁS COMÚN: una línea. La que más veces resultó ser, según los tickets.
QUÉ HACER: pasos numerados, máximo cinco, en el orden en que conviene probarlos.
YA SE DESCARTÓ: lo que los tickets dicen que se probó y no era. Si ninguno lo
dice, escribe "nada registrado".

Reglas:
- Solo lo que digan los tickets. No agregues pasos de tu experiencia general.
- No repitas el mismo paso con otras palabras.
- Si los tickets se contradicen, di cuál pasó más veces.

TICKETS:
{tickets}"""

# Para el modelo local: sin la sección de descartes, porque no la sabe usar.
# Medido: con los descartes en contexto, qwen2.5:3b escribió como paso 2 "se
# cambia el toner completo" —justo lo que los tickets decían que NO era—.
PROMPT_SIN_DESCARTES = """Eres un técnico de soporte de TI con años en una planta industrial.

Abajo hay varios tickets ya resueltos del MISMO problema. Escribe el
procedimiento único que le sirva al que venga después, en español de México:

SÍNTOMA: una línea. Cómo se ve el problema desde fuera.
CAUSA MÁS COMÚN: una línea. Qué resultó ser, según los tickets.
QUÉ HACER: pasos numerados, máximo cinco, en el orden de probarlos.

Solo lo que digan los tickets. No repitas el mismo paso con otras palabras.

TICKETS:
{tickets}"""


class SolucionesService:

    # ------------------------------------------------------------------
    # Encontrar de qué vale la pena escribir
    # ------------------------------------------------------------------
    @staticmethod
    def agrupar(db: Session, sitio_id: int,
                minimo: Optional[int] = None) -> List[dict]:
        """Grupos de tickets resueltos que hablan del mismo problema.

        Se agrupa por parecido entre los embeddings que ya existen: no hay que
        volver a llamar a ningún modelo, la comparación es aritmética sobre
        vectores que ya están guardados.

        Devuelve los grupos que llegan al mínimo de ocurrencias, del más grande
        al más chico. Los de una sola aparición no son un patrón, son un caso.
        """
        minimo = minimo or settings.SOLUCION_GENERAL_MIN_TICKETS

        entradas = db.query(BaseConocimiento).filter(
            BaseConocimiento.sitio_id == sitio_id,
            BaseConocimiento.embedding.isnot(None),
        ).all()
        if len(entradas) < minimo:
            return []

        # Agrupación simple por vecindad: se toma una entrada, se le pegan todas
        # las que se le parezcan por encima del umbral, y esas ya no se vuelven a
        # considerar. Con cientos de tickets alcanza y se entiende de un vistazo;
        # si algún día son decenas de miles, aquí es donde habría que cambiar a
        # un algoritmo de verdad.
        usadas = set()
        grupos = []

        for ancla in entradas:
            if ancla.id in usadas:
                continue
            grupo = [ancla]
            usadas.add(ancla.id)

            for otra in entradas:
                if otra.id in usadas:
                    continue
                if SolucionesService._parecido(ancla.embedding, otra.embedding) \
                        >= settings.SOLUCION_GENERAL_UMBRAL:
                    grupo.append(otra)
                    usadas.add(otra.id)

            if len(grupo) >= minimo:
                grupos.append({
                    "titulo": ancla.titulo,
                    "categoria": ancla.categoria,
                    "entradas": grupo,
                    "ocurrencias": len(grupo),
                })

        grupos.sort(key=lambda g: g["ocurrencias"], reverse=True)
        return grupos

    @staticmethod
    def _tickets(entradas, con_descartes: bool) -> str:
        return "\n\n---\n\n".join(
            f"TICKET {i + 1}\n{e.contenido.strip()}"
            + (f"\nSe probó y NO era: {e.descartado.strip()}"
               if con_descartes and e.descartado else "")
            for i, e in enumerate(entradas)
        )

    @staticmethod
    def _anclaje(borrador: str, entradas) -> float:
        """Qué fracción del vocabulario del borrador viene de los tickets.

        Se reutiliza el mismo medidor del asistente para no tener dos formas
        distintas de contestar la misma pregunta.
        """
        from app.services.asistente_service import AsistenteService

        palabras = AsistenteService._palabras(borrador)
        if not palabras:
            return 0.0

        fuente = set()
        for e in entradas:
            fuente |= AsistenteService._palabras(f"{e.titulo} {e.contenido}")
            if e.descartado:
                fuente |= AsistenteService._palabras(e.descartado)
        return len(palabras & fuente) / len(palabras)

    @staticmethod
    def _parecido(a, b) -> float:
        """Coseno entre dos vectores ya normalizados por el modelo."""
        if a is None or b is None:
            return 0.0
        producto = sum(x * y for x, y in zip(a, b))
        na = sum(x * x for x in a) ** 0.5
        nb = sum(y * y for y in b) ** 0.5
        return producto / (na * nb) if na and nb else 0.0

    # ------------------------------------------------------------------
    # Redactar el borrador
    # ------------------------------------------------------------------
    @staticmethod
    def redactar_borrador(db: Session, grupo: dict, sitio_id: int) -> Optional[SolucionGeneral]:
        """Escribe el borrador de un grupo. None si ningún modelo pudo.

        None no es un error: significa "hoy no se pudo redactar". TI puede
        escribir la solución general a mano, que es lo que hacía antes de que
        existiera esto.
        """
        entradas = grupo["entradas"][:settings.SOLUCION_GENERAL_MAX_TICKETS]

        # Gemini primero, y es la única parte del portal donde eso pasa: aquí el
        # trabajo es sintetizar sobre muchos documentos, que es justo lo que un
        # modelo chico no hace bien. Aun así, si no está, se intenta con el local.
        texto, redactor = None, None
        if gemini.configurado:
            respuesta = gemini.redactar(
                PROMPT.format(tickets=SolucionesService._tickets(entradas, con_descartes=True))
            )
            if respuesta:
                texto, redactor = respuesta["respuesta"], "gemini"

        if not texto:
            # Sin descartes para el local, y por el mismo motivo medido en el
            # asistente: leyó "se cambió el tóner y no era" y escribió como paso
            # "se cambia el toner completo". Lo que no puede leer, no lo invierte.
            texto = ollama.responder_texto(
                PROMPT_SIN_DESCARTES.format(
                    tickets=SolucionesService._tickets(entradas, con_descartes=False)),
                num_predict=700, timeout=120,
            )
            redactor = "ollama" if texto else None

        if not texto or len(texto.strip()) < settings.SOLUCION_GENERAL_MIN_CARACTERES:
            logger.info("No se pudo redactar la solución general; queda para escribirla a mano",
                        extra={"titulo": grupo["titulo"]})
            return None

        # El mismo filtro que en el asistente, y aquí hace más falta todavía:
        # un borrador se lee una vez y se publica. Medido, el modelo local sacó
        # un procedimiento con pasos que ningún ticket menciona —revisar el cable
        # de corriente, revisar el papel— porque son lo que "suena" a impresora.
        #
        # Si el borrador no sale de los tickets, no hay borrador. TI lo escribe a
        # mano, que es lo que hacía antes, y sabe que lo está escribiendo.
        anclaje = SolucionesService._anclaje(texto, entradas)
        if anclaje < settings.SOLUCION_GENERAL_ANCLAJE_MINIMO:
            logger.warning("El borrador se salió de los tickets; se descarta",
                           extra={"titulo": grupo["titulo"], "anclaje": round(anclaje, 2),
                                  "redactor": redactor})
            return None

        descartes = [e.descartado.strip() for e in entradas if e.descartado]

        solucion = SolucionGeneral(
            sitio_id=sitio_id,
            titulo=grupo["titulo"][:200],
            categoria=grupo.get("categoria"),
            contenido=texto.strip(),
            descartado="\n".join(dict.fromkeys(descartes)) or None,
            estado=BORRADOR,
            tickets_origen=grupo["ocurrencias"],
            redactada_por=redactor,
            creado_en=datetime.utcnow(),
        )
        db.add(solucion)
        db.commit()
        db.refresh(solucion)
        return solucion

    # ------------------------------------------------------------------
    # Publicar
    # ------------------------------------------------------------------
    @staticmethod
    def publicar(db: Session, solucion: SolucionGeneral, quien: Usuario) -> SolucionGeneral:
        """La firma una persona y entra en las respuestas del asistente.

        El embedding se calcula aquí y no antes: mientras es borrador no debe
        aparecer en las búsquedas, porque nadie la ha revisado todavía.
        """
        solucion.embedding = ollama.generar_embedding(
            f"{solucion.titulo}\n{solucion.contenido}", tarea="documento"
        )
        solucion.estado = PUBLICADA
        solucion.revisada_por = quien.id
        solucion.publicado_en = datetime.utcnow()
        db.commit()
        db.refresh(solucion)

        logger.info("Solución general publicada",
                    extra={"id": solucion.id, "titulo": solucion.titulo,
                           "revisada_por": quien.id})
        return solucion

    @staticmethod
    def reindexar(db: Session, solucion: SolucionGeneral) -> None:
        """Después de editar el texto, el embedding queda viejo."""
        if solucion.estado != PUBLICADA:
            return
        nuevo = ollama.generar_embedding(
            f"{solucion.titulo}\n{solucion.contenido}", tarea="documento"
        )
        if nuevo is not None:
            solucion.embedding = nuevo
            db.commit()

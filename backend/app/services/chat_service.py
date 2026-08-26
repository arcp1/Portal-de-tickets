"""Chatbot flotante: clasifica texto libre hacia una categoría.

El chat **solo sustituye el paso de elegir categoría**. A partir de ahí es el
mismo flujo de siempre: reglas de negocio -> checklist -> similitud -> ticket.
Un modelo nunca decide reglas de negocio ni resuelve por su cuenta.

Tres límites que vienen del diseño, no del código:
  - Máximo 3 intercambios. Al cuarto se escala a ticket.
  - El contexto vive dentro de la sesión, no entre incidencias distintas.
  - Si Ollama no está, el widget se oculta. Nunca se muestra un error de IA.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.config import settings
from app.core.logging import logger
from app.models import ChatSesion, Usuario
from app.services.ollama_client import CATEGORIAS_VALIDAS, ollama

# Acciones que el frontend sabe interpretar.
ACCION_FLUJO = "flujo_categoria"      # clasificado: entra al flujo de esa categoría
ACCION_PEDIR = "pedir_categoria"      # sin confianza: se muestran los dropdowns
ACCION_TICKET = "crear_ticket"        # se agotaron los intercambios o lo pidió el usuario
ACCION_NO_DISPONIBLE = "no_disponible"  # Ollama caído: el widget se oculta


class ChatService:

    @staticmethod
    def _cargar_sesion(db: Session, usuario: Usuario, sesion_id: Optional[int]) -> Optional[ChatSesion]:
        """Recupera la sesión del usuario. None si no existe, no es suya o ya cerró.

        Que no sea suya se trata igual que que no exista: una sesión ajena no se
        lee ni se continúa.
        """
        if sesion_id is None:
            return None
        sesion = db.query(ChatSesion).filter(ChatSesion.id == sesion_id).first()
        if not sesion or sesion.usuario_id != usuario.id or sesion.cerrada:
            return None
        return sesion

    @staticmethod
    def _contexto(sesion: ChatSesion, mensaje: str) -> str:
        """Todo lo que el usuario ha escrito en esta incidencia.

        Da contexto a la clasificación sin arrastrar nada de incidencias
        anteriores: solo se leen los mensajes de esta sesión.
        """
        previos = [
            m.get("texto", "")
            for m in (sesion.mensajes or [])
            if m.get("rol") == "usuario"
        ]
        return "\n".join([*previos, mensaje]).strip()

    @staticmethod
    def procesar_mensaje(
        db: Session,
        usuario: Usuario,
        mensaje: str,
        sesion_id: Optional[int] = None,
    ) -> dict:
        """Procesa un mensaje del chat y decide qué sigue.

        Nunca levanta por un fallo de IA: si Ollama no responde devuelve
        ``ACCION_NO_DISPONIBLE`` y el widget se oculta solo.
        """
        sesion = ChatService._cargar_sesion(db, usuario, sesion_id)

        if sesion is None:
            sesion = ChatSesion(
                usuario_id=usuario.id,
                mensajes=[],
                cerrada=False,
                creado_en=datetime.utcnow(),
            )
            db.add(sesion)
            db.flush()

        contexto = ChatService._contexto(sesion, mensaje)

        # La clasificación devuelve None ante cualquier fallo de Ollama.
        clasificacion = ollama.clasificar_categoria(contexto)

        if clasificacion is None and not ollama.disponible():
            # Se guarda lo que el usuario escribió para no perderlo, pero no se
            # inventa respuesta: el widget se oculta y queda el formulario.
            ChatService._añadir(db, sesion, "usuario", mensaje)
            db.commit()
            return {
                "sesion_id": sesion.id,
                "respuesta": None,
                "categoria": None,
                "confianza": None,
                "accion": ACCION_NO_DISPONIBLE,
                "intercambios": ChatService._intercambios(sesion),
                "descripcion_sugerida": contexto,
                "categorias": list(CATEGORIAS_VALIDAS),
            }

        ChatService._añadir(db, sesion, "usuario", mensaje)
        intercambios = ChatService._intercambios(sesion)

        categoria = clasificacion["categoria"] if clasificacion else None
        confianza = clasificacion["confianza"] if clasificacion else None
        hay_confianza = confianza is not None and confianza >= settings.CHAT_UMBRAL_CONFIANZA

        if hay_confianza:
            accion = ACCION_FLUJO
            sesion.categoria_detectada = categoria
            sesion.confianza = confianza
            sesion.cerrada = True
        elif intercambios >= settings.CHAT_MAX_INTERCAMBIOS:
            # A la tercera sin clasificar, se levanta ticket. Nadie se queda
            # dando vueltas con un bot.
            accion = ACCION_TICKET
            sesion.cerrada = True
            # Se guarda la mejor sospecha aunque no alcanzara el umbral: sirve
            # para medir la precisión del clasificador contra la categoría final.
            sesion.categoria_detectada = categoria
            sesion.confianza = confianza
        else:
            accion = ACCION_PEDIR

        ChatService._añadir(db, sesion, "asistente", None, accion=accion, categoria=categoria)
        db.commit()
        db.refresh(sesion)

        logger.info(
            "Mensaje de chat procesado",
            extra={
                "sesion_id": sesion.id,
                "accion": accion,
                "categoria": categoria,
                "confianza": confianza,
                "intercambios": intercambios,
            },
        )

        return {
            "sesion_id": sesion.id,
            # El texto lo pone el frontend desde i18n: el backend decide la
            # acción, no las palabras. Así el chat habla los tres idiomas.
            "respuesta": None,
            "categoria": categoria if hay_confianza else None,
            "confianza": confianza,
            "accion": accion,
            "intercambios": intercambios,
            "descripcion_sugerida": contexto,
            "categorias": list(CATEGORIAS_VALIDAS),
        }

    @staticmethod
    def escalar_a_tecnico(db: Session, usuario: Usuario, sesion_id: Optional[int]) -> dict:
        """El usuario pidió hablar con un técnico. Se cierra la sesión y se va al formulario."""
        sesion = ChatService._cargar_sesion(db, usuario, sesion_id)
        if sesion:
            sesion.cerrada = True
            ChatService._añadir(db, sesion, "asistente", None, accion=ACCION_TICKET)
            db.commit()
            db.refresh(sesion)

        return {
            "sesion_id": sesion.id if sesion else None,
            "respuesta": None,
            "categoria": sesion.categoria_detectada if sesion else None,
            "confianza": None,
            "accion": ACCION_TICKET,
            "intercambios": ChatService._intercambios(sesion) if sesion else 0,
            "descripcion_sugerida": ChatService._contexto(sesion, "") if sesion else "",
            "categorias": list(CATEGORIAS_VALIDAS),
        }

    # ------------------------------------------------------------------
    # Utilidades internas
    # ------------------------------------------------------------------
    @staticmethod
    def _intercambios(sesion: ChatSesion) -> int:
        return sum(1 for m in (sesion.mensajes or []) if m.get("rol") == "usuario")

    @staticmethod
    def _añadir(db: Session, sesion: ChatSesion, rol: str, texto: Optional[str], **extra):
        historial = list(sesion.mensajes or [])
        entrada = {"rol": rol, "texto": texto, "creado_en": datetime.utcnow().isoformat()}
        entrada.update({k: v for k, v in extra.items() if v is not None})
        historial.append(entrada)
        sesion.mensajes = historial
        # La columna JSON se reasigna entera; sin esto SQLAlchemy no siempre
        # detecta el cambio de una lista mutable.
        flag_modified(sesion, "mensajes")

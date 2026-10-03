"""Avisos por correo.

Hoy el usuario tiene que entrar al portal a ver si le respondieron. Con esto se
entera solo.

Dos reglas, iguales a las del resto del sistema:

1. **Un fallo de correo nunca rompe una operación.** Si el servidor SMTP no
   responde, el ticket se crea o se cierra igual y el aviso simplemente no sale.
2. **Sin configurar, no hace nada.** Si no hay `SMTP_HOST`, el servicio queda
   inactivo en silencio en lugar de llenar los logs de errores.
"""

import smtplib
from email.message import EmailMessage

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import logger
from app.models import Ticket, Usuario


def _plantilla(titulo: str, cuerpo: str, folio: str) -> str:
    """Correo en texto plano. En planta se lee desde el teléfono y muchos
    clientes bloquean HTML: el texto siempre llega."""
    return (
        f"{titulo}\n"
        f"{'=' * len(titulo)}\n\n"
        f"{cuerpo}\n\n"
        f"Ticket: {folio}\n"
        f"Portal: {settings.PORTAL_URL}\n\n"
        f"-- \nPortal de Tickets TI · CGR de México\n"
        f"Este es un mensaje automático; no hace falta responderlo."
    )


class NotificacionesService:

    @staticmethod
    def activo() -> bool:
        return bool(settings.SMTP_HOST and settings.NOTIFICACIONES_ACTIVAS)

    @staticmethod
    def _enviar(destino: str, asunto: str, cuerpo: str) -> bool:
        """Lo manda al worker si hay cola; si no, lo envía aquí. Nunca levanta.

        Encolado cuenta como enviado: el correo sale en segundos y la petición
        no espera los hasta 10 del servidor SMTP.
        """
        if not NotificacionesService.activo() or not destino:
            return False
        from app.core import tareas
        if tareas.encolar("enviar_correo", destino, asunto, cuerpo):
            return True
        return NotificacionesService.enviar_ahora(destino, asunto, cuerpo)

    @staticmethod
    def enviar_ahora(destino: str, asunto: str, cuerpo: str) -> bool:
        """Devuelve True si salió. Nunca levanta. Lo usa también el worker."""
        if not NotificacionesService.activo():
            return False
        if not destino:
            return False

        mensaje = EmailMessage()
        mensaje["From"] = settings.SMTP_REMITENTE or settings.SMTP_USUARIO
        mensaje["To"] = destino
        mensaje["Subject"] = asunto
        mensaje.set_content(cuerpo)

        try:
            if settings.SMTP_SSL:
                servidor = smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PUERTO, timeout=10)
            else:
                servidor = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PUERTO, timeout=10)
                if settings.SMTP_STARTTLS:
                    servidor.starttls()

            with servidor:
                if settings.SMTP_USUARIO:
                    servidor.login(settings.SMTP_USUARIO, settings.SMTP_PASSWORD)
                servidor.send_message(mensaje)

            logger.info("Aviso enviado", extra={"destino": destino, "asunto": asunto})
            return True

        except Exception as exc:  # noqa: BLE001 - degradación deliberada
            # Que no salga el correo no puede tumbar la operación que lo originó.
            logger.error(
                "No se pudo enviar el aviso; la operación siguió igual",
                extra={"destino": destino, "error": str(exc)},
            )
            return False

    # ------------------------------------------------------------------
    # Eventos
    # ------------------------------------------------------------------
    @staticmethod
    def ticket_creado(db: Session, ticket: Ticket, fuera_horario: bool) -> bool:
        """Acuse de recibo. Fuera de horario dice cuándo lo van a ver."""
        usuario = db.query(Usuario).filter(Usuario.id == ticket.usuario_id).first()
        if not usuario:
            return False

        cuando = ""
        if fuera_horario:
            cuando = (
                "\nEn este momento no hay personal de TI. Su ticket quedó registrado "
                "y lo atenderán en cuanto entren."
            )

        return NotificacionesService._enviar(
            usuario.email,
            f"[{ticket.folio}] Su reporte quedó registrado",
            _plantilla(
                "Reporte registrado",
                f"Registramos su reporte de {ticket.categoria}.\n\n"
                f"Descripción: {ticket.descripcion_original[:300]}\n"
                f"Prioridad: {ticket.prioridad}{cuando}",
                ticket.folio,
            ),
        )

    @staticmethod
    def ticket_a_proveedor(db: Session, ticket: Ticket, destinatario: str) -> bool:
        """Aviso al proveedor externo al que una regla de negocio derivó el ticket.

        Existe porque la pantalla de reglas promete «Enrutar a Proveedor
        Externo» y pide un correo: sin esto el correo se guardaba y el
        proveedor nunca se enteraba de nada. El ticket quedaba en
        `espera_proveedor` esperando a alguien que no sabía que lo esperaban.
        """
        if not destinatario:
            return False

        usuario = db.query(Usuario).filter(Usuario.id == ticket.usuario_id).first()
        contacto = usuario.nombre if usuario else "—"

        return NotificacionesService._enviar(
            destinatario,
            f"[{ticket.folio}] Solicitud de servicio · CGR de México",
            _plantilla(
                "Solicitud de servicio",
                f"Se le deriva una incidencia de {ticket.categoria}.\n\n"
                f"Descripción: {ticket.descripcion_original[:500]}\n"
                f"Prioridad: {ticket.prioridad}\n"
                f"Reportado por: {contacto}",
                ticket.folio,
            ),
        )

    @staticmethod
    def ticket_asignado(db: Session, ticket: Ticket) -> bool:
        """Aviso al técnico que recibe el ticket."""
        tecnico = db.query(Usuario).filter(Usuario.id == ticket.asignado_a).first()
        if not tecnico:
            return False

        return NotificacionesService._enviar(
            tecnico.email,
            f"[{ticket.folio}] Se le asignó un ticket",
            _plantilla(
                "Ticket asignado",
                f"Categoría: {ticket.categoria}\n"
                f"Prioridad: {ticket.prioridad}\n\n"
                f"{ticket.descripcion_normalizada or ticket.descripcion_original}",
                ticket.folio,
            ),
        )

    @staticmethod
    def ticket_resuelto(db: Session, ticket: Ticket) -> bool:
        """Aviso a quien lo reportó, con la solución."""
        usuario = db.query(Usuario).filter(Usuario.id == ticket.usuario_id).first()
        if not usuario:
            return False

        return NotificacionesService._enviar(
            usuario.email,
            f"[{ticket.folio}] Su reporte fue resuelto",
            _plantilla(
                "Reporte resuelto",
                f"Su reporte de {ticket.categoria} quedó resuelto.\n\n"
                f"Qué se hizo:\n{ticket.solucion or 'Sin detalle.'}\n\n"
                f"¿Cómo lo atendimos? Califíquenos en un clic: "
                f"{settings.PORTAL_URL.rstrip('/')}/tickets/{ticket.id}\n\n"
                f"Si el problema vuelve, puede levantar un reporte nuevo.",
                ticket.folio,
            ),
        )

    @staticmethod
    def comentario_nuevo(db: Session, ticket: Ticket, autor: Usuario, texto: str) -> bool:
        """Aviso de respuesta. Solo a la otra parte, y nunca de notas internas."""
        usuario = db.query(Usuario).filter(Usuario.id == ticket.usuario_id).first()
        if not usuario or usuario.id == autor.id:
            # Quien escribió no necesita que le avisen de su propio comentario.
            return False

        return NotificacionesService._enviar(
            usuario.email,
            f"[{ticket.folio}] Respuesta de soporte",
            _plantilla(
                "Nueva respuesta",
                f"{autor.nombre} escribió:\n\n{texto[:500]}",
                ticket.folio,
            ),
        )

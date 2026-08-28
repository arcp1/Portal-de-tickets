from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime
import random

from app.core.db import get_db
from app.models import Ticket, TicketComentario, Sitio, Usuario, ChatSesion
from app.schemas.ticket import TicketCreate, TicketUpdate, TicketResponse, CommentCreate, CommentResponse
from app.api.deps import get_current_user
from app.services.rules_engine import RulesEngine
from app.services.kb_service import KBService, solucion_es_valida
from app.services.temas_service import TemasService
from app.services.horario_service import HorarioService
from app.services.notificaciones_service import NotificacionesService
from app.services.auditoria_service import AuditoriaService, TICKET_ASIGNADO, TICKET_ESTADO, TICKET_PRIORIDAD, TICKET_SOLUCION
from app.services.ollama_client import ollama
from app.core.config import settings
from app.core.logging import logger

router = APIRouter(prefix="/tickets", tags=["Tickets"])

# Estados que exigen una solución documentada para poder entrar en ellos.
ESTADOS_DE_CIERRE = ("resuelto", "cerrado")

# Canales que el propio usuario puede reportar al crear el ticket. Son los
# niveles de autoservicio del flujo; "tecnico" y "proveedor" los decide el
# sistema, nunca quien reporta.
CANALES_AUTOSERVICIO = ("checklist", "kb")

def generate_folio(db: Session, sitio_id: int) -> str:
    sitio = db.query(Sitio).filter(Sitio.id == sitio_id).first()
    clave = sitio.clave if sitio else "PLANT"
    year = datetime.utcnow().strftime("%Y")
    count = db.query(Ticket).filter(Ticket.sitio_id == sitio_id).count() + 1
    return f"TICK-{clave}-{year}-{count:04d}"

@router.get("", response_model=List[TicketResponse])
def list_tickets(
    estado: Optional[str] = None,
    categoria: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    query = db.query(Ticket)
    
    # Non-admin users only see their own tickets
    if current_user.rol != "admin":
        query = query.filter(Ticket.usuario_id == current_user.id)
    else:
        # Admin sees tickets for their site by default
        query = query.filter(Ticket.sitio_id == current_user.sitio_id)
        
    if estado:
        query = query.filter(Ticket.estado == estado)
    if categoria:
        query = query.filter(Ticket.categoria == categoria)
        
    return query.order_by(Ticket.creado_en.desc()).all()

@router.post("", response_model=TicketResponse, status_code=status.HTTP_201_CREATED)
def create_ticket(
    ticket_in: TicketCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    ahora = datetime.utcnow()
    folio = generate_folio(db, ticket_in.sitio_id)
    
    # Evaluate business rules
    rule_eval = RulesEngine.evaluate_and_apply_rules(
        db=db,
        sitio_id=ticket_in.sitio_id,
        categoria=ticket_in.categoria,
        descripcion=ticket_in.descripcion_original
    )
    
    estado = rule_eval["estado"] if rule_eval["matched"] else "abierto"
    canal_resolucion = rule_eval["canal_resolucion"] if rule_eval["matched"] else "tecnico"

    # Auto-resolución declarada por el usuario (checklist o base de conocimiento).
    # Se guarda como ticket ya resuelto: es la única forma de medir la tasa de
    # deflección. No se indexa en la KB —el checklist ya existe y la sugerencia
    # de KB ya está indexada—, solo se registra el canal.
    auto_resuelto = False
    if ticket_in.canal_auto_resolucion is not None:
        if ticket_in.canal_auto_resolucion not in CANALES_AUTOSERVICIO:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "Canal de auto-resolución inválido. Solo se acepta: "
                    + ", ".join(CANALES_AUTOSERVICIO)
                ),
            )
        if not solucion_es_valida(ticket_in.solucion):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "Una auto-resolución debe indicar qué resolvió el problema "
                    f"(mínimo {settings.SOLUCION_MIN_LONGITUD} caracteres)."
                ),
            )
        auto_resuelto = True
        estado = "resuelto"
        canal_resolucion = ticket_in.canal_auto_resolucion

    # Normalización de la descripción: es una mejora, no un requisito.
    # Si Ollama no responde o tarda de más, descripcion_normalizada queda en
    # None y el ticket se crea igual con la descripción original. El usuario
    # ni se entera.
    descripcion_normalizada = ollama.normalizar_descripcion(ticket_in.descripcion_original)

    new_ticket = Ticket(
        sitio_id=ticket_in.sitio_id,
        folio=folio,
        usuario_id=current_user.id,
        equipo_id=ticket_in.equipo_id,
        categoria=ticket_in.categoria,
        subcategoria=ticket_in.subcategoria,
        descripcion_original=ticket_in.descripcion_original,
        descripcion_normalizada=descripcion_normalizada,
        prioridad=ticket_in.prioridad,
        estado=estado,
        canal_resolucion=canal_resolucion,
        solucion=ticket_in.solucion if auto_resuelto else None,
        creado_en=ahora,
        resuelto_en=ahora if auto_resuelto else None,
        tiempo_resolucion=0 if auto_resuelto else None,
        # El SLA cuenta solo horas hábiles y, si entra de madrugada, empieza a
        # correr cuando abren. Una auto-resolución ya está cerrada: no vence.
        vence_en=None if auto_resuelto else HorarioService.calcular_vencimiento(ticket_in.prioridad, ahora),
        fuera_horario=not HorarioService.es_horario_laboral(ahora),
    )
    db.add(new_ticket)
    db.commit()
    db.refresh(new_ticket)
    
    if rule_eval["matched"] and rule_eval["nota"]:
        system_comment = TicketComentario(
            ticket_id=new_ticket.id,
            autor_id=current_user.id,
            comentario=f"[SISTEMA] {rule_eval['nota']}",
            es_interno=True,
            creado_en=datetime.utcnow()
        )
        db.add(system_comment)
        db.commit()
        db.refresh(new_ticket)

    # Enlaza la sesión de chat que originó el ticket. Solo la del propio
    # usuario, y solo si aún no está enlazada.
    if ticket_in.chat_sesion_id is not None:
        sesion = db.query(ChatSesion).filter(
            ChatSesion.id == ticket_in.chat_sesion_id,
            ChatSesion.usuario_id == current_user.id,
            ChatSesion.ticket_id.is_(None),
        ).first()
        if sesion:
            sesion.ticket_id = new_ticket.id
            db.commit()

    # Un problema que no encaja en las categorias se agrupa con lo parecido
    # ya reportado. Si se repite, se le propone al admin como tema nuevo.
    # Nunca levanta: el ticket ya esta creado.
    TemasService.registrar_incidencia(db, new_ticket)

    # Acuse de recibo. Si el correo falla, el ticket ya esta creado y no pasa nada.
    NotificacionesService.ticket_creado(db, new_ticket, new_ticket.fuera_horario)

    logger.info("Ticket created", extra={"ticket_id": new_ticket.id, "folio": folio, "usuario_id": current_user.id})
    return new_ticket

@router.get("/{ticket_id}", response_model=TicketResponse)
def get_ticket(
    ticket_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    if current_user.rol != "admin" and ticket.usuario_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to view this ticket")
    return ticket

@router.patch("/{ticket_id}", response_model=TicketResponse)
def update_ticket(
    ticket_id: int,
    ticket_in: TicketUpdate,
    peticion: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    if current_user.rol != "admin" and ticket.usuario_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to modify this ticket")

    # Resolver, cerrar y documentar la solución es trabajo del equipo de TI.
    # La solución no se queda en el ticket: alimenta la base de conocimiento
    # (services/kb_service.py) y se le ofrece como sugerencia al resto de la
    # planta, así que la escribe quien resolvió la incidencia y no quien la
    # reportó. El dueño del ticket conserva los demás campos.
    #
    # Va antes de validar la solución a propósito: a quien no puede cerrar se
    # le responde que no puede, no que le falta documentarla.
    if current_user.rol != "admin":
        if ticket_in.estado is not None and ticket_in.estado in ESTADOS_DE_CIERRE:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Solo el equipo de TI puede resolver o cerrar un ticket.",
            )
        if ticket_in.solucion is not None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Solo el equipo de TI puede documentar la solución de un ticket.",
            )

    # La solución puede venir en esta misma petición o estar ya documentada.
    # Se valida antes de tocar el objeto para que un rechazo no deje nada
    # a medias en la sesión.
    # Valores previos, para dejar constancia de que cambio exactamente.
    estado_previo = ticket.estado
    prioridad_previa = ticket.prioridad
    asignado_previo = ticket.asignado_a
    tenia_solucion = bool(ticket.solucion)

    solucion_efectiva = ticket_in.solucion if ticket_in.solucion is not None else ticket.solucion
    se_esta_cerrando = ticket_in.estado is not None and ticket_in.estado in ESTADOS_DE_CIERRE

    if se_esta_cerrando and not solucion_es_valida(solucion_efectiva):
        # Sin esto no se puede indexar el ticket, y una base de conocimiento
        # llena de cierres sin explicación es peor que una base vacía.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Debe documentar la solución para cerrar el ticket "
                f"(mínimo {settings.SOLUCION_MIN_LONGITUD} caracteres)."
            ),
        )

    if ticket_in.solucion is not None:
        ticket.solucion = ticket_in.solucion
    # Lo que se probó y no era. Opcional: no todo ticket tiene descartes, pero
    # cuando los tiene valen tanto como la solución.
    if ticket_in.descartado is not None:
        ticket.descartado = ticket_in.descartado.strip() or None

    if ticket_in.estado is not None:
        ticket.estado = ticket_in.estado
        if ticket_in.estado in ESTADOS_DE_CIERRE and not ticket.resuelto_en:
            ticket.resuelto_en = datetime.utcnow()
            diff = (ticket.resuelto_en - ticket.creado_en).total_seconds() / 60.0
            ticket.tiempo_resolucion = int(diff)

    if ticket_in.prioridad is not None:
        ticket.prioridad = ticket_in.prioridad
        # Cambiar la prioridad cambia el compromiso: se recalcula desde que se
        # creó el ticket, no desde ahora, para no regalar tiempo.
        if ticket.estado not in ESTADOS_DE_CIERRE:
            ticket.vence_en = HorarioService.calcular_vencimiento(ticket.prioridad, ticket.creado_en)
    asignado_cambio = False
    if ticket_in.asignado_a is not None:
        asignado_cambio = ticket.asignado_a != ticket_in.asignado_a
        ticket.asignado_a = ticket_in.asignado_a
    if ticket_in.canal_resolucion is not None:
        ticket.canal_resolucion = ticket_in.canal_resolucion
    if ticket_in.descripcion_normalizada is not None:
        ticket.descripcion_normalizada = ticket_in.descripcion_normalizada

    db.commit()
    db.refresh(ticket)

    # Indexación en la base de conocimiento. Va después del commit y nunca
    # levanta: si Ollama está caído el ticket queda cerrado igual, solo
    # pendiente de indexar.
    # Bitacora de lo que cambio (spec 12).
    if ticket_in.estado is not None and ticket_in.estado != estado_previo:
        AuditoriaService.registrar(db, current_user, TICKET_ESTADO, "ticket", ticket.id,
                                   AuditoriaService.cambio(estado_previo, ticket.estado), peticion)
    if ticket_in.prioridad is not None and ticket_in.prioridad != prioridad_previa:
        AuditoriaService.registrar(db, current_user, TICKET_PRIORIDAD, "ticket", ticket.id,
                                   AuditoriaService.cambio(prioridad_previa, ticket.prioridad), peticion)
    if asignado_cambio:
        AuditoriaService.registrar(db, current_user, TICKET_ASIGNADO, "ticket", ticket.id,
                                   AuditoriaService.cambio(asignado_previo, ticket.asignado_a), peticion)
    if ticket_in.solucion is not None:
        AuditoriaService.registrar(db, current_user, TICKET_SOLUCION, "ticket", ticket.id,
                                   {"documentada_por_primera_vez": not tenia_solucion}, peticion)

    if se_esta_cerrando:
        KBService.indexar_ticket(db, ticket)
        db.refresh(ticket)
        NotificacionesService.ticket_resuelto(db, ticket)

    if asignado_cambio:
        NotificacionesService.ticket_asignado(db, ticket)

    return ticket

@router.post("/{ticket_id}/comments", response_model=CommentResponse, status_code=status.HTTP_201_CREATED)
def add_comment(
    ticket_id: int,
    comment_in: CommentCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    if current_user.rol != "admin" and ticket.usuario_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to comment on this ticket")

    comment = TicketComentario(
        ticket_id=ticket.id,
        autor_id=current_user.id,
        comentario=comment_in.comentario,
        es_interno=comment_in.es_interno if current_user.rol == "admin" else False,
        creado_en=datetime.utcnow()
    )
    db.add(comment)
    db.commit()
    db.refresh(comment)

    # Las notas internas son para el equipo de TI: al usuario no se le avisan.
    if not comment.es_interno:
        NotificacionesService.comentario_nuevo(db, ticket, current_user, comment.comentario)

    return comment

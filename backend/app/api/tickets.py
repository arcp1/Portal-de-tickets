from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime
import random

from app.core.db import get_db
from app.models import Ticket, TicketComentario, Sitio, Usuario
from app.schemas.ticket import TicketCreate, TicketUpdate, TicketResponse, CommentCreate, CommentResponse
from app.api.deps import get_current_user
from app.services.rules_engine import RulesEngine
from app.core.logging import logger

router = APIRouter(prefix="/tickets", tags=["Tickets"])

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
    
    new_ticket = Ticket(
        sitio_id=ticket_in.sitio_id,
        folio=folio,
        usuario_id=current_user.id,
        equipo_id=ticket_in.equipo_id,
        categoria=ticket_in.categoria,
        subcategoria=ticket_in.subcategoria,
        descripcion_original=ticket_in.descripcion_original,
        prioridad=ticket_in.prioridad,
        estado=estado,
        canal_resolucion=canal_resolucion,
        creado_en=datetime.utcnow()
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
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    if current_user.rol != "admin" and ticket.usuario_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to modify this ticket")
        
    if ticket_in.estado is not None:
        ticket.estado = ticket_in.estado
        if ticket_in.estado in ["resuelto", "cerrado"] and not ticket.resuelto_en:
            ticket.resuelto_en = datetime.utcnow()
            diff = (ticket.resuelto_en - ticket.creado_en).total_seconds() / 60.0
            ticket.tiempo_resolucion = int(diff)
            
    if ticket_in.prioridad is not None:
        ticket.prioridad = ticket_in.prioridad
    if ticket_in.asignado_a is not None:
        ticket.asignado_a = ticket_in.asignado_a
    if ticket_in.canal_resolucion is not None:
        ticket.canal_resolucion = ticket_in.canal_resolucion
    if ticket_in.descripcion_normalizada is not None:
        ticket.descripcion_normalizada = ticket_in.descripcion_normalizada

    db.commit()
    db.refresh(ticket)
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
    return comment

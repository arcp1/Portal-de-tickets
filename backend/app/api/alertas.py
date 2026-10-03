"""La campana de TI: alertas de SLA, de satisfacción y de sensores.

Solo TI, y de todas las plantas (su alcance es global); se puede filtrar a una.
Las abre el sistema —ver `services/alertas_service.py`—; aquí solo se leen y
se atienden.
"""

from datetime import datetime
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.api.deps import get_current_admin
from app.core.db import get_db
from app.models import Alerta, Usuario
from app.schemas.comunes import FechaUTC, PlantaBreve
from app.services import eventos_service as eventos
from app.services.alertas_service import TIPOS, AlertasService
from app.services.auditoria_service import ALERTA_ATENDIDA, AuditoriaService

router = APIRouter(prefix="/admin/alertas", tags=["Alertas"])


class AlertaResponse(BaseModel):
    id: int
    tipo: str
    titulo: str
    detalle: Optional[str] = None
    datos: Optional[dict] = None
    sitio: Optional[PlantaBreve] = None
    ticket_id: Optional[int] = None
    dispositivo_id: Optional[int] = None
    creado_en: FechaUTC
    atendida_en: Optional[FechaUTC] = None
    atendida_por: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)


class ResumenAlertas(BaseModel):
    pendientes: int
    por_tipo: Dict[str, int]


def _filtradas(db: Session, sitio_id: Optional[int], tipo: Optional[str]):
    consulta = db.query(Alerta)
    if sitio_id is not None:
        consulta = consulta.filter(Alerta.sitio_id == sitio_id)
    if tipo:
        if tipo not in TIPOS:
            raise HTTPException(status_code=422, detail="Tipo de alerta desconocido.")
        consulta = consulta.filter(Alerta.tipo == tipo)
    return consulta


@router.get("", response_model=List[AlertaResponse])
def listar(
    pendientes: bool = True,
    tipo: Optional[str] = None,
    sitio_id: Optional[int] = Query(None, ge=1, le=2**31 - 1),
    limite: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
    admin: Usuario = Depends(get_current_admin),
):
    consulta = _filtradas(db, sitio_id, tipo).options(joinedload(Alerta.sitio))
    if pendientes:
        consulta = consulta.filter(Alerta.atendida_en.is_(None))
    return consulta.order_by(Alerta.creado_en.desc(), Alerta.id.desc()).limit(limite).all()


@router.get("/resumen", response_model=ResumenAlertas)
def resumen(
    sitio_id: Optional[int] = Query(None, ge=1, le=2**31 - 1),
    db: Session = Depends(get_db),
    admin: Usuario = Depends(get_current_admin),
):
    """Lo que pinta el número de la campana: un conteo, sin traer filas."""
    filas = (_filtradas(db, sitio_id, None)
             .filter(Alerta.atendida_en.is_(None))
             .with_entities(Alerta.tipo, func.count(Alerta.id))
             .group_by(Alerta.tipo).all())
    por_tipo = {t: n for t, n in filas}
    return ResumenAlertas(pendientes=sum(por_tipo.values()), por_tipo=por_tipo)


@router.post("/{alerta_id}/atender", response_model=AlertaResponse)
def atender(
    alerta_id: int,
    peticion: Request,
    db: Session = Depends(get_db),
    admin: Usuario = Depends(get_current_admin),
):
    alerta = (db.query(Alerta).filter(Alerta.id == alerta_id)
              .with_for_update().populate_existing().first()
              if 0 < alerta_id < 2**31 else None)
    if not alerta:
        raise HTTPException(status_code=404, detail="Alerta no encontrada")
    ya_estaba = alerta.atendida_en is not None
    AlertasService.cerrar(db, alerta, admin)
    db.commit()
    if not ya_estaba:
        AuditoriaService.registrar(db, admin, ALERTA_ATENDIDA, "alerta", alerta.id,
                                   {"tipo": alerta.tipo}, peticion)
        eventos.publicar(None, "alertas")
    return db.query(Alerta).options(joinedload(Alerta.sitio)).filter(Alerta.id == alerta_id).one()


@router.post("/atender-todas")
def atender_todas(
    peticion: Request,
    tipo: Optional[str] = None,
    sitio_id: Optional[int] = Query(None, ge=1, le=2**31 - 1),
    db: Session = Depends(get_db),
    admin: Usuario = Depends(get_current_admin),
):
    """Vaciar la campana (o un tipo de ella) de una vez."""
    pendientes = (_filtradas(db, sitio_id, tipo)
                  .filter(Alerta.atendida_en.is_(None)).with_for_update().all())
    for alerta in pendientes:
        AlertasService.cerrar(db, alerta, admin)
    db.commit()
    if pendientes:
        AuditoriaService.registrar(db, admin, ALERTA_ATENDIDA, "alerta", None,
                                   {"tipo": tipo, "cantidad": len(pendientes)}, peticion)
        eventos.publicar(None, "alertas")
    return {"atendidas": len(pendientes), "en": datetime.utcnow().isoformat() + "Z"}

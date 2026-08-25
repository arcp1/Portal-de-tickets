from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel

from app.core.db import get_db
from app.models import Sitio

router = APIRouter(prefix="/sitios", tags=["Sitios"])

class SitioResponse(BaseModel):
    id: int
    clave: str
    nombre: str
    pais: str
    activo: bool

    class Config:
        from_attributes = True

@router.get("", response_model=List[SitioResponse])
def list_sitios(db: Session = Depends(get_db)):
    return db.query(Sitio).filter(Sitio.activo == True).all()

"""El asistente que responde con el conocimiento de la planta.

Una sola operación, porque una sola cosa hace: buscar en lo que TI ya resolvió y
ya escribió, y redactar sobre eso citando de dónde salió.

**Lo que no hace, y es lo importante:** no le pregunta a ningún modelo cuando no
encontró nada parecido. En ese caso contesta que no tiene información y sugiere
levantar un ticket. Es preferible un "no sé" a un procedimiento inventado que
mande a alguien a desarmar una impresora sana.
"""

from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.db import get_db
from app.models import Usuario
from app.services.asistente_service import AsistenteService
from app.services.recuperacion_service import RecuperacionService

router = APIRouter(prefix="/asistente", tags=["Asistente"])


class PreguntaRequest(BaseModel):
    texto: str = Field(min_length=1, max_length=2000)
    categoria: Optional[str] = None


@router.post("/preguntar")
def preguntar(
    peticion: PreguntaRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """Responde con lo que la planta ya sabe, o dice que no sabe.

    En `origen` viene quién contestó:

      - `ollama`  — redactó el modelo local, gratis.
      - `gemini`  — redactó Gemini, porque el local no alcanzó.
      - `extractos` — no había modelo disponible; van los pasajes tal cual.
      - `sin_fundamento` — no hay nada parecido en el conocimiento de la planta.
        **No se consultó a ningún modelo.**

    En `fuentes` viene de dónde salió cada cosa, para poder abrir el ticket
    original y comprobar.
    """
    return AsistenteService.responder(
        db,
        pregunta=peticion.texto,
        sitio_id=current_user.sitio_id,
        categoria=peticion.categoria,
    )


@router.post("/buscar")
def buscar(
    peticion: PreguntaRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """Solo la búsqueda, sin redactar. Útil para ver qué encontraría."""
    pasajes = RecuperacionService.buscar(
        db, peticion.texto, current_user.sitio_id, categoria=peticion.categoria
    )
    return {"resultados": [p.a_dict() for p in pasajes], "total": len(pasajes)}

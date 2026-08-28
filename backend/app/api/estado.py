"""Estado operativo del portal: horario de TI, SLA y salud de los servicios.

Dos superficies:

  - `/estado/horario`, para cualquier usuario. Le dice la verdad sobre cuándo lo
    van a atender, en vez de dejarlo esperando una respuesta que no llega hasta
    mañana.
  - `/admin/estado/sistema`, solo TI. Contesta de un vistazo la pregunta que
    siempre se hace a mano: **¿está todo arriba?** Y sobre todo, deja comprobar
    que la llave de Gemini quedó bien puesta sin que nadie tenga que enseñarla.
"""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin, get_current_user
from app.core.config import settings
from app.core.db import get_db
from app.models import Ticket, Usuario
from app.services.gemini_client import gemini
from app.services.horario_service import HorarioService
from app.services.ollama_client import ollama

router = APIRouter(tags=["Estado"])
admin_router = APIRouter(prefix="/admin/estado", tags=["Estado"])


@router.get("/estado/horario")
def horario(current_user: Usuario = Depends(get_current_user)):
    contexto = HorarioService.contexto()
    return {
        **contexto,
        "sla_horas": {
            "critica": settings.SLA_HORAS_CRITICA,
            "alta": settings.SLA_HORAS_ALTA,
            "media": settings.SLA_HORAS_MEDIA,
            "baja": settings.SLA_HORAS_BAJA,
        },
    }


@admin_router.get("/sistema")
def sistema(db: Session = Depends(get_db), admin: Usuario = Depends(get_current_admin)):
    """Salud de los servicios de los que depende el portal.

    Lo importante de esta pantalla no es que todo salga en verde: es que cuando
    algo sale en rojo, **el portal siga funcionando**. Ollama y Gemini son ayudas;
    la base de datos es lo único cuya caída sí para el servicio, y por eso se
    distingue `critico` de `opcional`.
    """
    servicios = []

    # --- Base de datos: lo único que sí es crítico ---
    try:
        db.execute(func.now())
        servicios.append({"nombre": "Base de datos", "clave": "db",
                          "estado": "arriba", "critico": True,
                          "detalle": "PostgreSQL con pgvector"})
    except Exception as exc:  # noqa: BLE001
        servicios.append({"nombre": "Base de datos", "clave": "db",
                          "estado": "abajo", "critico": True,
                          "detalle": str(exc)[:200]})

    # --- Ollama: si se cae, el portal pierde ayudas, no funciones ---
    latencias = ollama.latencias()
    ollama_arriba = ollama.disponible() if settings.IA_HABILITADA else False
    servicios.append({
        "nombre": "Ollama (asistente local)",
        "clave": "ollama",
        "estado": ("arriba" if ollama_arriba
                   else "apagado" if not settings.IA_HABILITADA else "abajo"),
        "critico": False,
        "detalle": (f"{settings.OLLAMA_MODELO_TEXTO} · {settings.OLLAMA_MODELO_EMBEDDING}"),
        "latencias_ms": latencias,
        "degradacion": ("Sin Ollama los tickets se crean igual, con la descripción "
                        "original y sin sugerencias."),
    })

    # --- Gemini: opcional y ajeno. Se informa sin filtrar la llave ---
    diag = gemini.diagnostico()
    servicios.append({
        "nombre": "Gemini (respuestas con contexto)",
        "clave": "gemini",
        "estado": ("arriba" if diag["alcanzable"]
                   else "sin_llave" if not diag["configurado"]
                   else "en_espera" if diag["en_espera"] else "abajo"),
        "critico": False,
        "detalle": f"{diag['modelo']}" + (f" · llave {diag['llave']}" if diag["llave"] else ""),
        "latencias_ms": {"gemini": diag["latencia_ms"]},
        "degradacion": ("Sin Gemini el portal enseña los tickets parecidos tal cual, "
                        "sin redactar una respuesta."),
    })

    hace_24h = datetime.utcnow() - timedelta(hours=24)
    return {
        "servicios": servicios,
        # Que el portal atienda es lo que importa; que la IA responda, no.
        "operativo": all(s["estado"] == "arriba" for s in servicios if s["critico"]),
        "horario": HorarioService.contexto(),
        "actividad_24h": {
            "tickets_creados": db.query(func.count(Ticket.id))
                .filter(Ticket.creado_en >= hace_24h).scalar() or 0,
            "usuarios_activos": db.query(func.count(Usuario.id))
                .filter(Usuario.ultimo_acceso >= hace_24h).scalar() or 0,
        },
    }

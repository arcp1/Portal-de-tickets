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
from pathlib import Path

from cryptography import x509
from cryptography.x509.oid import NameOID
from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin, get_current_user
from app.core.config import settings
from app.core.db import get_db
from app.models import Ticket, Usuario
from app.services import cola_ia
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


def _estado_certificado() -> dict:
    """Cuánto le queda al certificado TLS. Sin TLS, se dice y ya."""
    ruta = Path(settings.RUTA_CERTIFICADO)
    base = {"nombre": "Certificado TLS", "clave": "certificado", "critico": False}

    # `is_file` y no `exists`: cuando el .crt no existe en el host, Docker crea
    # un **directorio** en su lugar al montarlo. Con `exists()` eso pasaba el
    # filtro, fallaba al leerlo y la pantalla de Estado marcaba el certificado
    # como "Caído" —rojo, alarmante— cuando en realidad solo no hay TLS puesto.
    if not ruta.is_file():
        return {**base, "estado": "apagado",
                "detalle": "El portal responde por HTTP",
                "degradacion": ("Sin TLS, las contraseñas y los códigos de activación "
                                "viajan en claro por la red de planta.")}

    try:
        with open(ruta, "rb") as archivo:
            cert = x509.load_pem_x509_certificate(archivo.read())
        vence = cert.not_valid_after_utc.replace(tzinfo=None)
        dias = (vence - datetime.utcnow()).days
        emisor = next(
            (a.value for a in cert.issuer if a.oid == NameOID.COMMON_NAME), "desconocido"
        )
    except Exception as exc:  # noqa: BLE001
        return {**base, "estado": "abajo",
                "detalle": f"No se pudo leer el certificado: {str(exc)[:120]}"}

    if dias < 0:
        estado = "abajo"
    elif dias <= settings.CERTIFICADO_AVISO_DIAS:
        estado = "en_espera"      # amarillo: hay que renovarlo ya
    else:
        estado = "arriba"

    return {
        **base,
        "estado": estado,
        "detalle": f"{emisor} · vence en {dias} día(s)",
        "dias_restantes": dias,
        "degradacion": ("Un certificado vencido no degrada nada: el navegador "
                        "simplemente no deja entrar. Renuévelo antes de que llegue "
                        "a cero."),
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
    faltan = ollama.faltan_modelos() if settings.IA_HABILITADA else []
    ollama_arriba = ollama.disponible() if settings.IA_HABILITADA else False

    # Un Ollama sin modelos contesta perfectamente y no sirve para nada: no
    # genera embeddings, la busqueda no encuentra nada y el asistente responde
    # "sin fundamento". Merece su propio estado, no un verde que engaña.
    if not settings.IA_HABILITADA:
        estado_ollama = "apagado"
        detalle = "Desactivado por configuración"
    elif faltan:
        estado_ollama = "en_espera"
        detalle = "Faltan modelos: " + ", ".join(faltan)
    elif ollama_arriba:
        estado_ollama = "arriba"
        detalle = f"{settings.OLLAMA_MODELO_TEXTO} · {settings.OLLAMA_MODELO_EMBEDDING}"
    else:
        estado_ollama = "abajo"
        detalle = "No responde"

    servicios.append({
        "nombre": "Ollama (asistente local)",
        "clave": "ollama",
        "estado": estado_ollama,
        "critico": False,
        "detalle": detalle,
        "latencias_ms": latencias,
        # Cuánta cola hay para la CPU. Es lo que separa dos quejas que desde
        # fuera suenan igual: "el asistente tarda" porque el modelo piensa
        # despacio —latencias altas, cola en cero— o porque hay tres personas
        # delante —latencias normales, cola llena—. La primera se arregla con
        # un modelo más chico; la segunda, subiendo el aforo o aceptando que
        # esta máquina da lo que da. Sin este dato las dos se diagnostican
        # igual de mal.
        #
        # `rechazados_sala` es el número a vigilar: si sube seguido, hay gente
        # quedándose sin ayuda de IA de forma rutinaria y toca revisar
        # IA_SALA_GENERACION o el tamaño del modelo.
        "cola": cola_ia.metricas(),
        "degradacion": (
            "Descárguelos con:  docker compose exec ollama ollama pull "
            + " && ollama pull ".join(faltan)
            if faltan else
            "Sin Ollama los tickets se crean igual, con la descripción "
            "original y sin sugerencias."
        ),
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

    # --- El certificado: caduca sin avisar y tumba el portal entero ---
    #
    # Un certificado vencido no degrada nada: el navegador simplemente no deja
    # entrar. Y vence en silencio, un martes cualquiera. Por eso se vigila aquí
    # y no en la cabeza de nadie.
    servicios.append(_estado_certificado())

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

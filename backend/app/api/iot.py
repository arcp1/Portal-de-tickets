"""Monitoreo ESP32: los sensores, su última lectura y su historial. Solo TI.

Las lecturas no entran por aquí sino por MQTT (ver ``app/iot/ingestor.py``):
este API solo las enseña y deja a TI ponerle nombre, planta y umbrales a cada
equipo, o desactivarlo.
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session, joinedload

from app.api.deps import get_current_admin
from app.core import plantas
from app.core.config import settings
from app.core.db import get_db
from app.models import DispositivoIoT, Usuario
from app.schemas.comunes import FechaUTC, PlantaBreve
from app.services.auditoria_service import DISPOSITIVO_EDITADO, AuditoriaService
from app.services.iot_service import MAGNITUDES, IoTService, umbrales_de

router = APIRouter(prefix="/admin/iot", tags=["Monitoreo ESP32"])


class LecturaResponse(BaseModel):
    temperatura: Optional[float] = None
    humedad: Optional[float] = None
    calidad_aire: Optional[float] = None
    extra: Optional[dict] = None
    registrado_en: FechaUTC

    model_config = ConfigDict(from_attributes=True)


class DispositivoResponse(BaseModel):
    id: int
    clave: str
    nombre: Optional[str] = None
    ubicacion: Optional[str] = None
    sitio: Optional[PlantaBreve] = None
    activo: bool
    ultimo_contacto: Optional[FechaUTC] = None
    creado_en: FechaUTC
    en_linea: bool = False
    umbrales: Dict[str, float] = {}
    umbrales_propios: Optional[dict] = None
    ultima: Optional[LecturaResponse] = None
    alertas_abiertas: int = 0


class EditarDispositivo(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    nombre: Optional[str] = Field(default=None, min_length=1, max_length=100)
    ubicacion: Optional[str] = Field(default=None, max_length=100)
    sitio_id: Optional[int] = None
    activo: Optional[bool] = None
    # {"temperatura": 30} fija ese; {"temperatura": null} vuelve al general.
    umbrales: Optional[Dict[str, Optional[float]]] = None

    @field_validator("umbrales")
    @classmethod
    def _umbrales_validos(cls, valor):
        if valor is None:
            return valor
        for magnitud, limite in valor.items():
            if magnitud not in MAGNITUDES:
                raise ValueError(f"magnitud desconocida: {magnitud}")
            if limite is not None:
                _, minimo, maximo = MAGNITUDES[magnitud]
                if not (minimo <= limite <= maximo):
                    raise ValueError(f"el umbral de {magnitud} debe estar entre {minimo:g} y {maximo:g}")
        return valor


def _respuesta(d: DispositivoIoT, ultima, alertas: int, ahora: datetime) -> DispositivoResponse:
    en_linea = bool(d.activo and d.ultimo_contacto and
                    ahora - d.ultimo_contacto < timedelta(minutes=settings.IOT_SIN_SENAL_MINUTOS))
    return DispositivoResponse(
        id=d.id, clave=d.clave, nombre=d.nombre, ubicacion=d.ubicacion,
        sitio=PlantaBreve.model_validate(d.sitio) if d.sitio else None,
        activo=d.activo, ultimo_contacto=d.ultimo_contacto, creado_en=d.creado_en,
        en_linea=en_linea, umbrales=umbrales_de(d), umbrales_propios=d.umbrales or None,
        ultima=LecturaResponse.model_validate(ultima) if ultima else None,
        alertas_abiertas=alertas,
    )


def _buscar(db: Session, dispositivo_id: int) -> DispositivoIoT:
    d = (db.query(DispositivoIoT).options(joinedload(DispositivoIoT.sitio))
         .filter(DispositivoIoT.id == dispositivo_id).first()
         if 0 < dispositivo_id < 2**31 else None)
    if not d:
        raise HTTPException(status_code=404, detail="Sensor no encontrado")
    return d


@router.get("/dispositivos", response_model=List[DispositivoResponse])
def listar(
    sitio_id: Optional[int] = Query(None, ge=1, le=2**31 - 1),
    db: Session = Depends(get_db),
    admin: Usuario = Depends(get_current_admin),
):
    consulta = db.query(DispositivoIoT).options(joinedload(DispositivoIoT.sitio))
    if sitio_id is not None:
        consulta = consulta.filter(DispositivoIoT.sitio_id == sitio_id)
    dispositivos = consulta.order_by(DispositivoIoT.activo.desc(), DispositivoIoT.nombre).all()
    ids = [d.id for d in dispositivos]
    ultimas = IoTService.ultimas(db, ids)
    alertas = IoTService.alertas_abiertas(db, ids)
    ahora = datetime.utcnow()
    return [_respuesta(d, ultimas.get(d.id), alertas.get(d.id, 0), ahora) for d in dispositivos]


@router.get("/dispositivos/{dispositivo_id}/lecturas")
def lecturas(
    dispositivo_id: int,
    horas: int = Query(24, ge=1, le=24 * 31),
    puntos: int = Query(120, ge=10, le=500),
    db: Session = Depends(get_db),
    admin: Usuario = Depends(get_current_admin),
):
    """La gráfica: promedios por tramo en las últimas `horas`."""
    d = _buscar(db, dispositivo_id)
    return {"dispositivo_id": d.id, **IoTService.serie(db, d.id, horas, puntos)}


@router.patch("/dispositivos/{dispositivo_id}", response_model=DispositivoResponse)
def editar(
    dispositivo_id: int,
    cambios: EditarDispositivo,
    peticion: Request,
    db: Session = Depends(get_db),
    admin: Usuario = Depends(get_current_admin),
):
    d = _buscar(db, dispositivo_id)
    datos = cambios.model_dump(exclude_unset=True)
    if "sitio_id" in datos and datos["sitio_id"] is not None:
        d.sitio_id = plantas.planta_para(db, admin, datos["sitio_id"])
    for campo in ("nombre", "ubicacion", "activo"):
        if campo in datos and (datos[campo] is not None or campo == "ubicacion"):
            setattr(d, campo, datos[campo] or (None if campo == "ubicacion" else datos[campo]))
    if datos.get("umbrales") is not None:
        propios = dict(d.umbrales or {})
        for magnitud, limite in datos["umbrales"].items():
            if limite is None:
                propios.pop(magnitud, None)
            else:
                propios[magnitud] = float(limite)
        d.umbrales = propios or None
    db.commit()
    AuditoriaService.registrar(db, admin, DISPOSITIVO_EDITADO, "dispositivo_iot", d.id,
                               {k: v for k, v in datos.items()}, peticion)
    d = _buscar(db, dispositivo_id)
    ultima = IoTService.ultimas(db, [d.id]).get(d.id)
    return _respuesta(d, ultima, IoTService.alertas_abiertas(db, [d.id]).get(d.id, 0),
                      datetime.utcnow())


@router.delete("/dispositivos/{dispositivo_id}")
def eliminar(
    dispositivo_id: int,
    peticion: Request,
    db: Session = Depends(get_db),
    admin: Usuario = Depends(get_current_admin),
):
    """Lo borra con sus lecturas y alertas. Para equipos de prueba o retirados.

    Si vuelve a publicar, se registra otra vez como nuevo: para callarlo de
    verdad hay que desactivarlo, no borrarlo.
    """
    d = _buscar(db, dispositivo_id)
    clave = d.clave
    db.delete(d)
    db.commit()
    AuditoriaService.registrar(db, admin, DISPOSITIVO_EDITADO, "dispositivo_iot", dispositivo_id,
                               {"eliminado": clave}, peticion)
    return {"ok": True}


@router.get("/conexion")
def conexion(admin: Usuario = Depends(get_current_admin)):
    """Lo que hace falta para programar un ESP32 nuevo (sin la contraseña).

    La contraseña de los equipos vive en el .env (`MQTT_DISPOSITIVO_PASSWORD`)
    y no sale por el API: quien programa los ESP32 la toma de ahí.
    """
    return {
        "puerto": settings.MQTT_PUERTO,
        "usuario_dispositivos": "sensor",
        "tema": "portal/<CLAVE_PLANTA>/sensores/<CLAVE_EQUIPO>/telemetria",
        "ejemplo": {"temperatura": 24.6, "humedad": 41.2, "calidad_aire": 412},
        "intervalo_minimo_s": settings.IOT_INTERVALO_MINIMO_S,
        "sin_senal_minutos": settings.IOT_SIN_SENAL_MINUTOS,
        "umbrales_generales": {
            "temperatura": settings.IOT_TEMPERATURA_MAX,
            "humedad": settings.IOT_HUMEDAD_MAX,
            "calidad_aire": settings.IOT_CALIDAD_AIRE_MAX,
        },
    }

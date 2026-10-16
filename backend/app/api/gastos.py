"""Gastos de TI: registro, expediente, presupuesto, resumen y exportación.

**Solo TI**, que es global: ve los gastos de todas las plantas. Cada alta,
edición, pago, borrado, comprobante y cambio de presupuesto deja su fila en
la bitácora (`auditoria`, entidad `gasto` o `gasto_presupuesto`); el
historial de un gasto se lee de ahí, y sobrevive al borrado del gasto.

Lo que no depende de HTTP —importes, CFDI, resumen, exportación— está en
`services/gastos_service.py`.
"""

from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Dict, Iterable, List, Literal, Optional

from fastapi import (APIRouter, Depends, File, Form, HTTPException, Query, Request,
                     UploadFile, status)
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload
from starlette.concurrency import run_in_threadpool

from app.api.deps import get_current_admin
from app.core.config import settings
from app.core.db import get_db
from app.core.logging import logger
from app.core.metadatos import LIMPIABLES, limpiar_subida
from app.models import (Auditoria, Equipo, Gasto, GastoCategoria, GastoComprobante,
                        GastoPresupuesto, GastoProveedor, Sitio, Ticket, Usuario)
from app.services import directorio_service as dsrv
from app.services import gastos_service as srv
from app.services.auditoria_service import AuditoriaService

router = APIRouter(prefix="/gastos", tags=["Gastos de TI"])

_ID = dict(ge=1, le=2**31 - 1)
_MAX = Decimal("999999999999.99")
_TROZO = 1024 * 1024

GASTO_CREADO = "gasto.creado"
GASTO_EDITADO = "gasto.editado"
GASTO_PAGADO = "gasto.pagado"
GASTO_BORRADO = "gasto.borrado"
COMPROBANTE_SUBIDO = "gasto.comprobante_subido"
COMPROBANTE_BORRADO = "gasto.comprobante_borrado"
PRESUPUESTO_EDITADO = "gasto_presupuesto.editado"
CATEGORIA_CREADA = "gasto_categoria.creada"
CATEGORIA_EDITADA = "gasto_categoria.editada"
PROVEEDOR_CREADO = "gasto_proveedor.creado"
PROVEEDOR_EDITADO = "gasto_proveedor.editado"
PROVEEDOR_BORRADO = "gasto_proveedor.borrado"


# ----------------------------------------------------------------------
# Esquemas
# ----------------------------------------------------------------------

class GastoEntrada(BaseModel):
    fecha: date
    concepto: str = Field(min_length=1, max_length=200)
    categoria_id: int = Field(**_ID)
    # El proveedor de la lista, o uno nuevo por nombre (y RFC): se busca por
    # RFC, después por nombre, y si no está se da de alta.
    proveedor_id: Optional[int] = Field(None, **_ID)
    proveedor_nombre: Optional[str] = Field(None, max_length=150)
    proveedor_rfc: Optional[str] = Field(None, max_length=20)
    tipo_compra: Literal["proveedor", "linea"] = "proveedor"
    referencia: Optional[str] = Field(None, max_length=60)
    cantidad: Decimal = Field(Decimal("1"), gt=0, le=Decimal("999999"), decimal_places=2)
    moneda: Literal["MXN", "USD"] = "MXN"
    tipo_cambio: Optional[Decimal] = Field(None, gt=0, le=Decimal("10000"), decimal_places=6)
    # Uno de los dos: el subtotal (antes de impuestos) o el total pagado.
    subtotal: Optional[Decimal] = Field(None, ge=0, le=_MAX, decimal_places=2)
    total: Optional[Decimal] = Field(None, ge=0, le=_MAX, decimal_places=2)
    tasa_iva: Decimal = Decimal("0.16")
    # El IVA exacto de un CFDI; si no viene, se calcula.
    iva: Optional[Decimal] = Field(None, ge=0, le=_MAX, decimal_places=2)
    retenciones: Decimal = Field(Decimal("0"), ge=0, le=_MAX, decimal_places=2)
    estado: Literal["pendiente", "pagado"] = "pendiente"
    fecha_pago: Optional[date] = None
    centro_costo: Optional[str] = Field(None, max_length=60)
    notas: Optional[str] = Field(None, max_length=2000)
    sitio_id: Optional[int] = Field(None, **_ID)
    equipo_id: Optional[int] = Field(None, **_ID)
    ticket_id: Optional[int] = Field(None, **_ID)
    responsable_id: Optional[int] = Field(None, **_ID)

    @field_validator("tasa_iva")
    @classmethod
    def _tasa(cls, v: Decimal) -> Decimal:
        if v not in srv.TASAS_IVA:
            raise ValueError("La tasa de IVA tiene que ser 0, 8 o 16 %.")
        return v

    @field_validator("fecha", "fecha_pago")
    @classmethod
    def _anio(cls, v: Optional[date]) -> Optional[date]:
        if v is not None and not 2000 <= v.year <= 2100:
            raise ValueError("La fecha está fuera de rango.")
        return v


class PagoEntrada(BaseModel):
    fecha_pago: Optional[date] = None


class CategoriaEntrada(BaseModel):
    nombre: Optional[str] = Field(None, min_length=1, max_length=80)
    activa: Optional[bool] = None


class ProveedorEntrada(BaseModel):
    nombre: Optional[str] = Field(None, min_length=1, max_length=150)
    rfc: Optional[str] = Field(None, max_length=20)


class MontoPresupuesto(BaseModel):
    categoria_id: int = Field(**_ID)
    monto: Decimal = Field(ge=0, le=_MAX, decimal_places=2)


class PresupuestoEntrada(BaseModel):
    categorias: List[MontoPresupuesto] = Field(max_length=500)


# ----------------------------------------------------------------------
# Salidas
# ----------------------------------------------------------------------

def _iso(fecha: Optional[datetime]) -> Optional[str]:
    if fecha is None:
        return None
    return fecha.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


def _n(valor) -> Optional[float]:
    return float(valor) if valor is not None else None


def _numeros(obj):
    """Los `Decimal` del resumen, a números de JSON."""
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, dict):
        return {k: _numeros(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_numeros(v) for v in obj]
    return obj


def _etiqueta_equipo(e: Equipo) -> str:
    texto = f"{e.marca} {e.modelo}".strip()
    return f"{texto} · {e.numero_serie}" if e.numero_serie else texto


def _salida(g: Gasto, tipos: Iterable[str] = (), comprobantes_n: int = 0) -> dict:
    tipos = list(tipos)
    return {
        "id": g.id,
        "fecha": g.fecha.isoformat(),
        "concepto": g.concepto,
        "cantidad": _n(g.cantidad),
        "tipo_compra": g.tipo_compra,
        "referencia": g.referencia,
        "categoria": {"id": g.categoria_id, "nombre": g.categoria.nombre if g.categoria else None},
        "proveedor": ({"id": g.proveedor.id, "nombre": g.proveedor.nombre, "rfc": g.proveedor.rfc}
                      if g.proveedor else None),
        "moneda": g.moneda,
        "tipo_cambio": _n(g.tipo_cambio),
        "subtotal": _n(g.subtotal),
        "tasa_iva": _n(g.tasa_iva),
        "iva": _n(g.iva),
        "retenciones": _n(g.retenciones),
        "total": _n(g.total),
        "total_mxn": _n(g.total_mxn),
        "estado": g.estado,
        "fecha_pago": g.fecha_pago.isoformat() if g.fecha_pago else None,
        "centro_costo": g.centro_costo,
        "notas": g.notas,
        "planta": ({"id": g.sitio.id, "clave": g.sitio.clave, "nombre": g.sitio.nombre} if g.sitio else None),
        "equipo": ({"id": g.equipo.id, "etiqueta": _etiqueta_equipo(g.equipo)} if g.equipo else None),
        "ticket": ({"id": g.ticket.id, "folio": g.ticket.folio} if g.ticket else None),
        "responsable": ({"id": g.responsable.id, "nombre": g.responsable.nombre} if g.responsable else None),
        "expediente": srv.etapas(g.tipo_compra, tipos),
        "comprobantes_n": comprobantes_n,
        "creado_en": _iso(g.creado_en),
        "actualizado_en": _iso(g.actualizado_en),
    }


def _salida_comprobante(c: GastoComprobante, autores: Optional[Dict[int, str]] = None) -> dict:
    return {
        "id": c.id, "tipo": c.tipo, "folio": c.folio,
        "fecha": c.fecha.isoformat() if c.fecha else None,
        "cfdi_uuid": c.cfdi_uuid, "nombre": c.nombre, "tipo_mime": c.tipo_mime,
        "tamano_bytes": c.tamano_bytes, "creado_en": _iso(c.creado_en),
        "subido_por": (autores or {}).get(c.subido_por),
    }


def _tipos_de(db: Session, ids: List[int]) -> Dict[int, set]:
    tipos: Dict[int, set] = {}
    conteo: Dict[int, int] = {}
    if not ids:
        return tipos
    for gasto_id, tipo in db.query(GastoComprobante.gasto_id, GastoComprobante.tipo).filter(
            GastoComprobante.gasto_id.in_(ids)):
        tipos.setdefault(gasto_id, set()).add(tipo)
        conteo[gasto_id] = conteo.get(gasto_id, 0) + 1
    tipos["_conteo"] = conteo  # type: ignore[index]
    return tipos


def _salidas(db: Session, gastos: List[Gasto]) -> List[dict]:
    tipos = _tipos_de(db, [g.id for g in gastos])
    conteo = tipos.pop("_conteo", {}) if tipos else {}
    return [_salida(g, tipos.get(g.id, ()), conteo.get(g.id, 0)) for g in gastos]


# ----------------------------------------------------------------------
# Consultas
# ----------------------------------------------------------------------

def _con_vinculos(consulta):
    return consulta.options(
        selectinload(Gasto.categoria), selectinload(Gasto.proveedor), selectinload(Gasto.sitio),
        selectinload(Gasto.equipo), selectinload(Gasto.ticket), selectinload(Gasto.responsable),
    )


class Filtros:
    def __init__(
        self,
        anio: Optional[int] = Query(None, ge=2000, le=2100),
        mes: Optional[int] = Query(None, ge=1, le=12),
        categoria_id: Optional[int] = Query(None, **_ID),
        proveedor_id: Optional[int] = Query(None, **_ID),
        estado: Optional[Literal["pendiente", "pagado"]] = None,
        tipo_compra: Optional[Literal["proveedor", "linea"]] = None,
        moneda: Optional[Literal["MXN", "USD"]] = None,
        # 0 = los que no tienen planta.
        sitio_id: Optional[int] = Query(None, ge=0, le=2**31 - 1),
        equipo_id: Optional[int] = Query(None, **_ID),
        ticket_id: Optional[int] = Query(None, **_ID),
        q: Optional[str] = Query(None, max_length=100),
    ):
        self.anio = anio or srv.hoy_local().year
        self.mes, self.categoria_id, self.proveedor_id = mes, categoria_id, proveedor_id
        self.estado, self.tipo_compra, self.moneda = estado, tipo_compra, moneda
        self.sitio_id, self.equipo_id, self.ticket_id = sitio_id, equipo_id, ticket_id
        self.q = (q or "").strip()


def _consulta(db: Session, f: Filtros):
    desde, hasta = srv.rango_de(f.anio, f.mes)
    consulta = db.query(Gasto).filter(Gasto.fecha >= desde, Gasto.fecha < hasta)
    if f.categoria_id:
        consulta = consulta.filter(Gasto.categoria_id == f.categoria_id)
    if f.proveedor_id:
        consulta = consulta.filter(Gasto.proveedor_id == f.proveedor_id)
    if f.estado:
        consulta = consulta.filter(Gasto.estado == f.estado)
    if f.tipo_compra:
        consulta = consulta.filter(Gasto.tipo_compra == f.tipo_compra)
    if f.moneda:
        consulta = consulta.filter(Gasto.moneda == f.moneda)
    if f.sitio_id is not None:
        consulta = consulta.filter(Gasto.sitio_id.is_(None) if f.sitio_id == 0 else Gasto.sitio_id == f.sitio_id)
    if f.equipo_id:
        consulta = consulta.filter(Gasto.equipo_id == f.equipo_id)
    if f.ticket_id:
        consulta = consulta.filter(Gasto.ticket_id == f.ticket_id)
    if f.q:
        patron = f"%{f.q}%"
        consulta = consulta.outerjoin(GastoProveedor, Gasto.proveedor_id == GastoProveedor.id).filter(or_(
            Gasto.concepto.ilike(patron), Gasto.notas.ilike(patron), Gasto.referencia.ilike(patron),
            Gasto.centro_costo.ilike(patron), GastoProveedor.nombre.ilike(patron),
            GastoProveedor.rfc.ilike(patron),
            Gasto.comprobantes.any(or_(GastoComprobante.folio.ilike(patron),
                                       GastoComprobante.cfdi_uuid.ilike(patron))),
        ))
    return consulta


def _gasto_o_404(db: Session, gasto_id: int) -> Gasto:
    gasto = _con_vinculos(db.query(Gasto)).filter(Gasto.id == gasto_id).first()
    if gasto is None:
        raise HTTPException(status_code=404, detail="Gasto no encontrado.")
    return gasto


def _422(texto: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=texto)


# ----------------------------------------------------------------------
# Catálogos
# ----------------------------------------------------------------------

def _salida_proveedor(p: GastoProveedor, cuentas: Dict[int, tuple], habitual: Dict[int, tuple]) -> dict:
    n, total = cuentas.get(p.id, (0, Decimal(0)))
    cat = habitual.get(p.id)
    return {"id": p.id, "nombre": p.nombre, "rfc": p.rfc, "n": n, "total_mxn": _n(total),
            "categoria_habitual": {"id": cat[0], "nombre": cat[1]} if cat else None}


def _proveedores(db: Session) -> List[dict]:
    cuentas = {pid: (n, total or Decimal(0)) for pid, n, total in db.query(
        Gasto.proveedor_id, func.count(Gasto.id), func.sum(Gasto.total_mxn)).filter(
        Gasto.proveedor_id.isnot(None)).group_by(Gasto.proveedor_id)}
    # La categoría habitual de cada proveedor: la de su gasto más reciente.
    # Es la que se propone al elegirlo en el formulario.
    habitual = {}
    for pid, cid, nombre in (db.query(Gasto.proveedor_id, Gasto.categoria_id, GastoCategoria.nombre)
                             .join(GastoCategoria, GastoCategoria.id == Gasto.categoria_id)
                             .filter(Gasto.proveedor_id.isnot(None))
                             .order_by(Gasto.fecha.asc(), Gasto.id.asc())):
        habitual[pid] = (cid, nombre)
    return [_salida_proveedor(p, cuentas, habitual)
            for p in db.query(GastoProveedor).order_by(func.lower(GastoProveedor.nombre))]


@router.get("/catalogos")
def catalogos(db: Session = Depends(get_db), admin: Usuario = Depends(get_current_admin)):
    """Lo que llena los desplegables del formulario."""
    usos = dict(db.query(Gasto.categoria_id, func.count(Gasto.id)).group_by(Gasto.categoria_id))
    categorias = [{"id": c.id, "nombre": c.nombre, "activa": c.activa, "n": usos.get(c.id, 0)}
                  for c in db.query(GastoCategoria).order_by(func.lower(GastoCategoria.nombre))]
    # «Responsable de TI»: el equipo de TI con acceso.
    responsables = [{"id": u.id, "nombre": u.nombre} for u in db.query(Usuario).filter(
        Usuario.rol == "admin", Usuario.activo.is_(True), Usuario.eliminado_en.is_(None)
    ).order_by(Usuario.nombre)]
    return {
        "categorias": categorias,
        "proveedores": _proveedores(db),
        "responsables": responsables,
        "tasas_iva": [float(t) for t in srv.TASAS_IVA],
        "tipos_comprobante": list(srv.TIPOS_COMPROBANTE),
        "etapas": {k: list(v) for k, v in srv.ETAPAS.items()},
        "max_mb": settings.GASTOS_MAX_MB,
    }


@router.post("/categorias", status_code=status.HTTP_201_CREATED)
def crear_categoria(datos: CategoriaEntrada, peticion: Request, db: Session = Depends(get_db),
                    admin: Usuario = Depends(get_current_admin)):
    nombre = (datos.nombre or "").strip()
    if not nombre:
        raise _422("Falta el nombre de la categoría.")
    existente = db.query(GastoCategoria).filter(func.lower(GastoCategoria.nombre) == nombre.lower()).first()
    if existente is not None:
        if existente.activa:
            raise HTTPException(status_code=409, detail="Ya existe una categoría con ese nombre.")
        # Retirada: vuelve, con su historia.
        existente.activa = True
        db.commit()
        AuditoriaService.registrar(db, admin, CATEGORIA_EDITADA, "gasto_categoria", existente.id,
                                   {"activa": AuditoriaService.cambio(False, True)}, peticion)
        return {"id": existente.id, "nombre": existente.nombre, "activa": True}
    categoria = GastoCategoria(nombre=nombre, activa=True)
    db.add(categoria)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Ya existe una categoría con ese nombre.")
    AuditoriaService.registrar(db, admin, CATEGORIA_CREADA, "gasto_categoria", categoria.id,
                               {"nombre": nombre}, peticion)
    return {"id": categoria.id, "nombre": categoria.nombre, "activa": True}


@router.patch("/categorias/{categoria_id:int}")
def editar_categoria(categoria_id: int, datos: CategoriaEntrada, peticion: Request,
                     db: Session = Depends(get_db), admin: Usuario = Depends(get_current_admin)):
    """Renombrar, retirar o devolver. **No se borra**: sus gastos y sus
    presupuestos de otros años la siguen nombrando."""
    categoria = db.get(GastoCategoria, categoria_id)
    if categoria is None:
        raise HTTPException(status_code=404, detail="Categoría no encontrada.")
    cambios = {}
    if datos.nombre is not None and datos.nombre.strip() != categoria.nombre:
        nombre = datos.nombre.strip()
        otra = db.query(GastoCategoria).filter(func.lower(GastoCategoria.nombre) == nombre.lower(),
                                               GastoCategoria.id != categoria.id).first()
        if otra is not None:
            raise HTTPException(status_code=409, detail="Ya existe una categoría con ese nombre.")
        cambios["nombre"] = AuditoriaService.cambio(categoria.nombre, nombre)
        categoria.nombre = nombre
    if datos.activa is not None and datos.activa != categoria.activa:
        cambios["activa"] = AuditoriaService.cambio(categoria.activa, datos.activa)
        categoria.activa = datos.activa
    if cambios:
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(status_code=409, detail="Ya existe una categoría con ese nombre.")
        AuditoriaService.registrar(db, admin, CATEGORIA_EDITADA, "gasto_categoria", categoria.id,
                                   cambios, peticion)
    return {"id": categoria.id, "nombre": categoria.nombre, "activa": categoria.activa}


def _rfc_o_422(rfc: Optional[str]) -> Optional[str]:
    try:
        return srv.rfc_limpio(rfc)
    except ValueError as exc:
        raise _422(str(exc))


def _proveedor_duplicado(db: Session, nombre: str, rfc: Optional[str], excepto: Optional[int] = None):
    condiciones = [func.lower(GastoProveedor.nombre) == nombre.lower()]
    if rfc:
        condiciones.append(GastoProveedor.rfc == rfc)
    consulta = db.query(GastoProveedor).filter(or_(*condiciones))
    if excepto:
        consulta = consulta.filter(GastoProveedor.id != excepto)
    return consulta.first()


@router.post("/proveedores", status_code=status.HTTP_201_CREATED)
def crear_proveedor(datos: ProveedorEntrada, peticion: Request, db: Session = Depends(get_db),
                    admin: Usuario = Depends(get_current_admin)):
    nombre = (datos.nombre or "").strip()
    if not nombre:
        raise _422("Falta el nombre del proveedor.")
    rfc = _rfc_o_422(datos.rfc)
    if _proveedor_duplicado(db, nombre, rfc):
        raise HTTPException(status_code=409, detail="Ya existe un proveedor con ese nombre o ese RFC.")
    proveedor = GastoProveedor(nombre=nombre, rfc=rfc)
    db.add(proveedor)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Ya existe un proveedor con ese nombre o ese RFC.")
    AuditoriaService.registrar(db, admin, PROVEEDOR_CREADO, "gasto_proveedor", proveedor.id,
                               {"nombre": nombre, "rfc": rfc}, peticion)
    return _salida_proveedor(proveedor, {}, {})


@router.patch("/proveedores/{proveedor_id:int}")
def editar_proveedor(proveedor_id: int, datos: ProveedorEntrada, peticion: Request,
                     db: Session = Depends(get_db), admin: Usuario = Depends(get_current_admin)):
    proveedor = db.get(GastoProveedor, proveedor_id)
    if proveedor is None:
        raise HTTPException(status_code=404, detail="Proveedor no encontrado.")
    nombre = (datos.nombre or proveedor.nombre).strip()
    rfc = _rfc_o_422(datos.rfc) if datos.rfc is not None else proveedor.rfc
    if _proveedor_duplicado(db, nombre, rfc, excepto=proveedor.id):
        raise HTTPException(status_code=409, detail="Ya existe otro proveedor con ese nombre o ese RFC.")
    cambios = {}
    if nombre != proveedor.nombre:
        cambios["nombre"] = AuditoriaService.cambio(proveedor.nombre, nombre)
        proveedor.nombre = nombre
    if rfc != proveedor.rfc:
        cambios["rfc"] = AuditoriaService.cambio(proveedor.rfc, rfc)
        proveedor.rfc = rfc
    if cambios:
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(status_code=409, detail="Ya existe otro proveedor con ese nombre o ese RFC.")
        AuditoriaService.registrar(db, admin, PROVEEDOR_EDITADO, "gasto_proveedor", proveedor.id,
                                   cambios, peticion)
    return next(p for p in _proveedores(db) if p["id"] == proveedor.id)


@router.delete("/proveedores/{proveedor_id:int}")
def borrar_proveedor(proveedor_id: int, peticion: Request, db: Session = Depends(get_db),
                     admin: Usuario = Depends(get_current_admin)):
    proveedor = db.get(GastoProveedor, proveedor_id)
    if proveedor is None:
        raise HTTPException(status_code=404, detail="Proveedor no encontrado.")
    if db.query(Gasto.id).filter(Gasto.proveedor_id == proveedor.id).first():
        raise HTTPException(status_code=409, detail="El proveedor tiene gastos registrados; no se puede quitar.")
    huella = {"nombre": proveedor.nombre, "rfc": proveedor.rfc}
    db.delete(proveedor)
    db.commit()
    AuditoriaService.registrar(db, admin, PROVEEDOR_BORRADO, "gasto_proveedor", proveedor_id, huella, peticion)
    return {"borrado": True}


# ----------------------------------------------------------------------
# Lectura del CFDI para llenar el formulario
# ----------------------------------------------------------------------

class _Demasiado(Exception):
    pass


async def _leer_todo(subida: UploadFile) -> bytes:
    tope = settings.GASTOS_MAX_MB * 1024 * 1024
    contenido = await subida.read(tope + 1)
    if len(contenido) > tope:
        raise _Demasiado()
    return contenido


def _demasiado() -> HTTPException:
    return HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                         detail=f"El archivo supera {settings.GASTOS_MAX_MB} MB.")


def _proveedor_del_cfdi(db: Session, cfdi: dict) -> Optional[GastoProveedor]:
    if cfdi.get("emisor_rfc"):
        p = db.query(GastoProveedor).filter(GastoProveedor.rfc == cfdi["emisor_rfc"]).first()
        if p:
            return p
    if cfdi.get("emisor_nombre"):
        return db.query(GastoProveedor).filter(
            func.lower(GastoProveedor.nombre) == cfdi["emisor_nombre"].lower()).first()
    return None


@router.post("/cfdi/analizar")
async def analizar_cfdi(archivo: UploadFile = File(...), db: Session = Depends(get_db),
                        admin: Usuario = Depends(get_current_admin)):
    """Lee el XML de un CFDI y devuelve los datos para llenar el formulario.

    No guarda nada: el archivo se adjunta al expediente después de guardar el
    gasto, con la subida normal. Avisa si esa factura ya está registrada.
    Solo XML: los datos del PDF habría que adivinarlos, y el original lo
    hacía con expresiones regulares que fallaban en cuanto cambiaba el
    formato del emisor.
    """
    try:
        nombre = dsrv.nombre_limpio(archivo.filename, 255)
        if dsrv.extension(nombre) != ".xml":
            raise dsrv.ArchivoRechazado("Para llenar el formulario se necesita el XML del CFDI.")
        cfdi = await run_in_threadpool(srv.leer_cfdi, await _leer_todo(archivo))
    except _Demasiado:
        raise _demasiado()
    except dsrv.ArchivoRechazado as exc:
        raise _422(str(exc))

    proveedor = _proveedor_del_cfdi(db, cfdi)
    categoria = None
    if proveedor is not None:
        ultimo = (db.query(Gasto.categoria_id).filter(Gasto.proveedor_id == proveedor.id)
                  .order_by(Gasto.fecha.desc(), Gasto.id.desc()).first())
        categoria = ultimo[0] if ultimo else None
    duplicado = None
    if cfdi["uuid"]:
        previo = db.query(GastoComprobante).filter(GastoComprobante.cfdi_uuid == cfdi["uuid"]).first()
        if previo is not None:
            duplicado = {"gasto_id": previo.gasto_id, "concepto": previo.gasto.concepto}
    return _numeros({
        **cfdi,
        "proveedor_id": proveedor.id if proveedor else None,
        "proveedor_nombre": proveedor.nombre if proveedor else cfdi["emisor_nombre"],
        "categoria_id": categoria,
        "duplicado": duplicado,
    })


# ----------------------------------------------------------------------
# Búsqueda de vínculos: activo y ticket
# ----------------------------------------------------------------------

@router.get("/vinculos")
def buscar_vinculo(tipo: Literal["equipo", "ticket"], q: str = Query(..., min_length=1, max_length=60),
                   db: Session = Depends(get_db), admin: Usuario = Depends(get_current_admin)):
    """Hasta doce activos o tickets que coincidan, para el buscador del
    formulario. TI es global: de todas las plantas."""
    patron = f"%{q.strip()}%"
    if tipo == "equipo":
        filas = (db.query(Equipo).filter(or_(
            Equipo.marca.ilike(patron), Equipo.modelo.ilike(patron), Equipo.numero_serie.ilike(patron),
            Equipo.categoria.ilike(patron), Equipo.ubicacion.ilike(patron)))
            .order_by(Equipo.id.desc()).limit(12).all())
        return [{"id": e.id, "etiqueta": _etiqueta_equipo(e), "sitio_id": e.sitio_id,
                 "detalle": e.categoria} for e in filas]
    condiciones = [Ticket.folio.ilike(patron), Ticket.descripcion_original.ilike(patron)]
    if q.strip().isdigit():
        condiciones.append(Ticket.id == int(q.strip()))
    filas = db.query(Ticket).filter(or_(*condiciones)).order_by(Ticket.id.desc()).limit(12).all()
    return [{"id": t.id, "etiqueta": t.folio, "sitio_id": t.sitio_id,
             "detalle": (t.descripcion_original or "")[:80]} for t in filas]


# ----------------------------------------------------------------------
# Presupuesto
# ----------------------------------------------------------------------

@router.get("/presupuesto/{anio:int}")
def leer_presupuesto(anio: int, db: Session = Depends(get_db), admin: Usuario = Depends(get_current_admin)):
    if not 2000 <= anio <= 2100:
        raise HTTPException(status_code=404, detail="Año fuera de rango.")
    montos = {p.categoria_id: p.monto for p in db.query(GastoPresupuesto).filter(GastoPresupuesto.anio == anio)}
    desde, hasta = srv.rango_de(anio)
    gastado = dict(db.query(Gasto.categoria_id, func.sum(Gasto.total_mxn)).filter(
        Gasto.fecha >= desde, Gasto.fecha < hasta).group_by(Gasto.categoria_id))
    filas = []
    for c in db.query(GastoCategoria).order_by(func.lower(GastoCategoria.nombre)):
        if not c.activa and not montos.get(c.id) and not gastado.get(c.id):
            continue
        filas.append({"categoria_id": c.id, "nombre": c.nombre, "activa": c.activa,
                      "monto": _n(montos.get(c.id, Decimal(0))), "gastado": _n(gastado.get(c.id) or Decimal(0))})
    return {"anio": anio, "categorias": filas, "total": _n(sum(montos.values(), Decimal(0)))}


@router.put("/presupuesto/{anio:int}")
def guardar_presupuesto(anio: int, datos: PresupuestoEntrada, peticion: Request,
                        db: Session = Depends(get_db), admin: Usuario = Depends(get_current_admin)):
    if not 2000 <= anio <= 2100:
        raise HTTPException(status_code=404, detail="Año fuera de rango.")
    ids = {m.categoria_id for m in datos.categorias}
    existentes = {c.id: c for c in db.query(GastoCategoria).filter(GastoCategoria.id.in_(ids))}
    if len(existentes) != len(ids):
        raise _422("Alguna categoría no existe.")
    actuales = {p.categoria_id: p for p in db.query(GastoPresupuesto).filter(GastoPresupuesto.anio == anio)}
    cambios = {}
    ahora = datetime.utcnow()
    for m in datos.categorias:
        monto = srv.centavos(m.monto)
        fila = actuales.get(m.categoria_id)
        antes = fila.monto if fila else Decimal(0)
        if srv.centavos(antes) == monto:
            continue
        cambios[existentes[m.categoria_id].nombre] = AuditoriaService.cambio(str(srv.centavos(antes)), str(monto))
        if fila is None:
            db.add(GastoPresupuesto(anio=anio, categoria_id=m.categoria_id, monto=monto,
                                    actualizado_por=admin.id, actualizado_en=ahora))
        else:
            fila.monto, fila.actualizado_por, fila.actualizado_en = monto, admin.id, ahora
    if cambios:
        db.commit()
        AuditoriaService.registrar(db, admin, PRESUPUESTO_EDITADO, "gasto_presupuesto", anio,
                                   {"anio": anio, "cambios": cambios}, peticion)
    return leer_presupuesto(anio, db, admin)


# ----------------------------------------------------------------------
# Resumen y exportación
# ----------------------------------------------------------------------

@router.get("/resumen")
def resumen(anio: Optional[int] = Query(None, ge=2000, le=2100),
            sitio_id: Optional[int] = Query(None, ge=0, le=2**31 - 1),
            db: Session = Depends(get_db), admin: Usuario = Depends(get_current_admin)):
    """Los indicadores del año. Con una planta elegida, el presupuesto no se
    compara: es de toda el área de TI, no de una planta."""
    hoy = srv.hoy_local()
    anio = anio or hoy.year
    desde, hasta = srv.rango_de(anio)

    def del_rango(d, h):
        consulta = db.query(Gasto).filter(Gasto.fecha >= d, Gasto.fecha < h)
        if sitio_id is not None:
            consulta = consulta.filter(Gasto.sitio_id.is_(None) if sitio_id == 0 else Gasto.sitio_id == sitio_id)
        return consulta

    gastos = del_rango(desde, hasta).all()
    filas = [{"id": g.id, "fecha": g.fecha, "concepto": g.concepto, "categoria_id": g.categoria_id,
              "proveedor_id": g.proveedor_id, "sitio_id": g.sitio_id, "total_mxn": srv.centavos(g.total_mxn),
              "total": srv.centavos(g.total), "moneda": g.moneda, "estado": g.estado,
              "tipo_compra": g.tipo_compra} for g in gastos]
    # El año anterior, hasta el mismo día: comparar todo 2025 contra medio
    # 2026 diría siempre que se gasta menos.
    if anio == hoy.year:
        tope_anterior = srv.mismo_dia_del_anio_anterior(hoy)
        tope_anterior = date.fromordinal(tope_anterior.toordinal() + 1)
    else:
        tope_anterior = date(anio, 1, 1)
    anterior = sum((srv.centavos(g.total_mxn) for g in del_rango(date(anio - 1, 1, 1), tope_anterior)),
                   Decimal(0)) if anio <= hoy.year else None

    categorias = {c.id: {"nombre": c.nombre, "activa": c.activa} for c in db.query(GastoCategoria)}
    presupuestos = {p.categoria_id: srv.centavos(p.monto)
                    for p in db.query(GastoPresupuesto).filter(GastoPresupuesto.anio == anio)}
    proveedores = dict(db.query(GastoProveedor.id, GastoProveedor.nombre))
    plantas = {s.id: {"clave": s.clave, "nombre": s.nombre} for s in db.query(Sitio)}
    tipos = _tipos_de(db, [g.id for g in gastos])
    tipos.pop("_conteo", None)
    datos = srv.resumir(filas, categorias, presupuestos, proveedores, plantas, tipos, anio, hoy,
                        anterior or None, con_presupuesto=sitio_id is None)
    return _numeros(datos)


@router.get("/exportar")
def exportar(formato: Literal["csv", "xlsx"] = "csv", idioma: str = Query("es", max_length=5),
             f: Filtros = Depends(), db: Session = Depends(get_db),
             admin: Usuario = Depends(get_current_admin)):
    """Los gastos que dejan ver los filtros, en CSV o en Excel."""
    gastos = (_con_vinculos(_consulta(db, f)).options(selectinload(Gasto.comprobantes))
              .order_by(Gasto.fecha.asc(), Gasto.id.asc()).limit(20000).all())
    filas = []
    for g in gastos:
        tipos = {c.tipo for c in g.comprobantes}
        facturas = [c for c in g.comprobantes if c.tipo == "factura"]
        exp = srv.etapas(g.tipo_compra, tipos)
        filas.append({
            "id": g.id, "fecha": g.fecha.isoformat(),
            "tipo_compra": srv.valor_traducido(g.tipo_compra, idioma),
            "concepto": g.concepto, "cantidad": g.cantidad,
            "proveedor": g.proveedor.nombre if g.proveedor else None,
            "rfc": g.proveedor.rfc if g.proveedor else None,
            "categoria": g.categoria.nombre if g.categoria else None,
            "planta": g.sitio.nombre if g.sitio else None,
            "activo": _etiqueta_equipo(g.equipo) if g.equipo else None,
            "ticket": g.ticket.folio if g.ticket else None,
            "responsable": g.responsable.nombre if g.responsable else None,
            "moneda": g.moneda, "tipo_cambio": g.tipo_cambio,
            "subtotal": g.subtotal, "iva": g.iva, "retenciones": g.retenciones,
            "total": g.total, "total_mxn": g.total_mxn,
            "estado": srv.valor_traducido(g.estado, idioma),
            "fecha_pago": g.fecha_pago.isoformat() if g.fecha_pago else None,
            "referencia": g.referencia,
            "folios": " | ".join(c.folio for c in facturas if c.folio) or None,
            "uuid": " | ".join(c.cfdi_uuid for c in facturas if c.cfdi_uuid) or None,
            "expediente": (srv.valor_traducido("completo", idioma) if exp["completo"]
                           else f"{exp['hechas']}/{exp['total']}"),
            "centro_costo": g.centro_costo, "notas": g.notas,
        })
    nombre = f"gastos-ti-{f.anio}" + (f"-{f.mes:02d}" if f.mes else "")
    if formato == "xlsx":
        contenido = srv.a_xlsx(filas, idioma, hoja=str(f.anio))
        tipo = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    else:
        contenido = srv.a_csv(filas, idioma)
        tipo = "text/csv; charset=utf-8"
    return Response(content=contenido, media_type=tipo, headers={
        "Content-Disposition": f'attachment; filename="{nombre}.{formato}"',
        "Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff",
    })


# ----------------------------------------------------------------------
# Comprobantes: descargar y borrar (por id de comprobante)
# ----------------------------------------------------------------------

@router.get("/comprobantes/{comprobante_id:int}/descarga")
def descargar_comprobante(comprobante_id: int, descargar: bool = False, db: Session = Depends(get_db),
                          admin: Usuario = Depends(get_current_admin)):
    c = db.get(GastoComprobante, comprobante_id)
    if c is None:
        raise HTTPException(status_code=404, detail="Comprobante no encontrado.")
    ruta = srv.carpeta_en_disco() / c.nombre_guardado
    if not ruta.exists():
        raise HTTPException(status_code=410, detail="El archivo ya no está disponible en el servidor.")
    en_linea = c.tipo_mime in srv.EN_LINEA and not descargar
    return FileResponse(
        path=str(ruta), media_type=c.tipo_mime, filename=c.nombre,
        content_disposition_type="inline" if en_linea else "attachment",
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"},
    )


@router.delete("/comprobantes/{comprobante_id:int}")
def borrar_comprobante(comprobante_id: int, peticion: Request, db: Session = Depends(get_db),
                       admin: Usuario = Depends(get_current_admin)):
    c = db.get(GastoComprobante, comprobante_id)
    if c is None:
        raise HTTPException(status_code=404, detail="Comprobante no encontrado.")
    huella = {"tipo": c.tipo, "nombre": c.nombre, "folio": c.folio, "uuid": c.cfdi_uuid,
              "comprobante_id": c.id}
    gasto_id, guardado = c.gasto_id, c.nombre_guardado
    db.delete(c)
    db.commit()
    srv.borrar_binarios([guardado])
    AuditoriaService.registrar(db, admin, COMPROBANTE_BORRADO, "gasto", gasto_id, huella, peticion)
    return {"borrado": True}


# ----------------------------------------------------------------------
# Gastos
# ----------------------------------------------------------------------

@router.get("")
def listar(f: Filtros = Depends(), limite: int = Query(1000, ge=1, le=5000),
           db: Session = Depends(get_db), admin: Usuario = Depends(get_current_admin)):
    """Los gastos del año (o del mes) con los filtros, del más reciente al
    más viejo, con el avance del expediente y lo que suman en pesos."""
    consulta = _consulta(db, f)
    suma, pendiente, total = (consulta.with_entities(
        func.coalesce(func.sum(Gasto.total_mxn), 0),
        func.coalesce(func.sum(Gasto.total_mxn).filter(Gasto.estado == "pendiente"), 0),
        func.count(Gasto.id)).one())
    gastos = (_con_vinculos(consulta).order_by(Gasto.fecha.desc(), Gasto.id.desc()).limit(limite).all())
    return {"anio": f.anio, "mes": f.mes, "total": total, "suma_mxn": _n(srv.centavos(suma)),
            "pendiente_mxn": _n(srv.centavos(pendiente)), "gastos": _salidas(db, gastos)}


def _vinculo(db: Session, modelo, ident: Optional[int], texto: str):
    if ident is None:
        return None
    fila = db.get(modelo, ident)
    if fila is None:
        raise _422(texto)
    return fila


def _proveedor_para(db: Session, datos: GastoEntrada) -> tuple:
    """(id del proveedor, el proveedor si se acaba de dar de alta).

    El alta no se anota aquí: la bitácora hace `commit`, y a media edición
    eso guardaría el gasto a medio aplicar. La anota quien guarda, después."""
    if datos.proveedor_id:
        proveedor = db.get(GastoProveedor, datos.proveedor_id)
        if proveedor is None:
            raise _422("El proveedor no existe.")
        # El RFC que no tenía, si viene (de un CFDI) y nadie más lo usa.
        rfc = _rfc_o_422(datos.proveedor_rfc)
        if rfc and not proveedor.rfc and not db.query(GastoProveedor.id).filter(GastoProveedor.rfc == rfc).first():
            proveedor.rfc = rfc
        return proveedor.id, None
    nombre = (datos.proveedor_nombre or "").strip()
    if not nombre:
        return None, None
    rfc = _rfc_o_422(datos.proveedor_rfc)
    proveedor = None
    if rfc:
        proveedor = db.query(GastoProveedor).filter(GastoProveedor.rfc == rfc).first()
    if proveedor is None:
        proveedor = db.query(GastoProveedor).filter(func.lower(GastoProveedor.nombre) == nombre.lower()).first()
        if proveedor is not None and rfc and not proveedor.rfc:
            proveedor.rfc = rfc
    if proveedor is None:
        proveedor = GastoProveedor(nombre=nombre, rfc=rfc)
        db.add(proveedor)
        db.flush()
        return proveedor.id, proveedor
    return proveedor.id, None


def _anotar_proveedor_nuevo(db: Session, nuevo: Optional[GastoProveedor], admin: Usuario,
                            peticion: Request) -> None:
    if nuevo is not None:
        AuditoriaService.registrar(db, admin, PROVEEDOR_CREADO, "gasto_proveedor", nuevo.id,
                                   {"nombre": nuevo.nombre, "rfc": nuevo.rfc, "desde": "gasto"}, peticion)


def _aplicar(db: Session, gasto: Gasto, datos: GastoEntrada) -> Optional[GastoProveedor]:
    """Pasa los datos al gasto, validados. Devuelve el proveedor si hubo que
    darlo de alta."""
    categoria = _vinculo(db, GastoCategoria, datos.categoria_id, "La categoría no existe.")
    if not categoria.activa and gasto.categoria_id != categoria.id:
        raise _422("Esa categoría está retirada. Elija otra o vuelva a activarla en Presupuesto.")
    sitio = _vinculo(db, Sitio, datos.sitio_id, "La planta no existe.")
    equipo = _vinculo(db, Equipo, datos.equipo_id, "El activo no existe.")
    ticket = _vinculo(db, Ticket, datos.ticket_id, "El ticket no existe.")
    responsable = _vinculo(db, Usuario, datos.responsable_id, "El responsable no existe.")
    if responsable is not None and (responsable.rol != "admin" or responsable.eliminado_en is not None):
        raise _422("El responsable tiene que ser alguien del equipo de TI.")
    if datos.moneda == "USD" and not datos.tipo_cambio:
        raise _422("Un gasto en dólares necesita el tipo de cambio.")
    tipo_cambio = datos.tipo_cambio if datos.moneda == "USD" else Decimal(1)
    try:
        importes = srv.calcular_importes(subtotal=datos.subtotal, total=datos.total, tasa_iva=datos.tasa_iva,
                                         iva=datos.iva, retenciones=datos.retenciones)
    except srv.ImporteInvalido as exc:
        raise _422(str(exc))
    if importes["total"] > _MAX:
        raise _422("El importe es demasiado grande.")

    gasto.fecha = datos.fecha
    gasto.concepto = datos.concepto.strip()
    gasto.categoria_id = categoria.id
    gasto.proveedor_id, nuevo = _proveedor_para(db, datos)
    gasto.tipo_compra = datos.tipo_compra
    gasto.referencia = (datos.referencia or "").strip() or None
    gasto.cantidad = srv.centavos(datos.cantidad)
    gasto.moneda = datos.moneda
    gasto.tipo_cambio = tipo_cambio
    gasto.tasa_iva = datos.tasa_iva
    gasto.subtotal, gasto.iva = importes["subtotal"], importes["iva"]
    gasto.retenciones, gasto.total = importes["retenciones"], importes["total"]
    gasto.total_mxn = srv.a_pesos(importes["total"], datos.moneda, tipo_cambio)
    gasto.estado = datos.estado
    # Pagado sin fecha: la del gasto. Pendiente: sin fecha de pago.
    gasto.fecha_pago = (datos.fecha_pago or datos.fecha) if datos.estado == "pagado" else None
    gasto.centro_costo = (datos.centro_costo or "").strip() or None
    gasto.notas = (datos.notas or "").strip() or None
    # Sin planta pero con activo o ticket: la de ellos.
    gasto.sitio_id = (sitio.id if sitio else (equipo.sitio_id if equipo else (ticket.sitio_id if ticket else None)))
    gasto.equipo_id = equipo.id if equipo else None
    gasto.ticket_id = ticket.id if ticket else None
    gasto.responsable_id = responsable.id if responsable else None
    gasto.actualizado_en = datetime.utcnow()
    return nuevo


_CAMPOS = ("fecha", "concepto", "categoria_id", "proveedor_id", "tipo_compra", "referencia", "cantidad",
           "moneda", "tipo_cambio", "subtotal", "tasa_iva", "iva", "retenciones", "total", "total_mxn",
           "estado", "fecha_pago", "centro_costo", "notas", "sitio_id", "equipo_id", "ticket_id",
           "responsable_id")


def _foto(g: Gasto) -> dict:
    def texto(v):
        if v is None:
            return None
        if isinstance(v, Decimal):
            return str(srv.centavos(v)) if v == srv.centavos(v) else str(v.normalize())
        if isinstance(v, date):
            return v.isoformat()
        return v
    return {c: texto(getattr(g, c)) for c in _CAMPOS}


def _huella(g: Gasto) -> dict:
    """Lo que se guarda en la bitácora de un gasto: legible sin la base."""
    return {
        "concepto": g.concepto, "fecha": g.fecha.isoformat(), "total": str(g.total), "moneda": g.moneda,
        "total_mxn": str(g.total_mxn), "estado": g.estado,
        "proveedor": g.proveedor.nombre if g.proveedor else None,
        "categoria": g.categoria.nombre if g.categoria else None,
    }


@router.post("", status_code=status.HTTP_201_CREATED)
def crear(datos: GastoEntrada, peticion: Request, db: Session = Depends(get_db),
          admin: Usuario = Depends(get_current_admin)):
    gasto = Gasto(creado_por=admin.id, creado_en=datetime.utcnow())
    nuevo = _aplicar(db, gasto, datos)
    db.add(gasto)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="No se pudo guardar: algún dato choca con otro registro.")
    _anotar_proveedor_nuevo(db, nuevo, admin, peticion)
    gasto = _gasto_o_404(db, gasto.id)
    AuditoriaService.registrar(db, admin, GASTO_CREADO, "gasto", gasto.id, _huella(gasto), peticion)
    logger.info("Gasto registrado", extra={"gasto_id": gasto.id})
    return _salida(gasto)


@router.get("/{gasto_id:int}")
def ver(gasto_id: int, db: Session = Depends(get_db), admin: Usuario = Depends(get_current_admin)):
    """El gasto con sus comprobantes y su historial (de la bitácora)."""
    gasto = _gasto_o_404(db, gasto_id)
    comprobantes = (db.query(GastoComprobante).filter(GastoComprobante.gasto_id == gasto.id)
                    .order_by(GastoComprobante.creado_en, GastoComprobante.id).all())
    historial = (db.query(Auditoria, Usuario.nombre)
                 .outerjoin(Usuario, Usuario.id == Auditoria.usuario_id)
                 .filter(Auditoria.entidad == "gasto", Auditoria.entidad_id == gasto.id)
                 .order_by(Auditoria.id.desc()).limit(100).all())
    autores = dict(db.query(Usuario.id, Usuario.nombre).filter(
        Usuario.id.in_({c.subido_por for c in comprobantes if c.subido_por})))
    return {
        **_salida(gasto, {c.tipo for c in comprobantes}, len(comprobantes)),
        "comprobantes": [_salida_comprobante(c, autores) for c in comprobantes],
        "historial": [{"accion": a.accion, "creado_en": _iso(a.creado_en), "usuario": nombre,
                       "detalle": a.detalle} for a, nombre in historial],
    }


@router.put("/{gasto_id:int}")
def editar(gasto_id: int, datos: GastoEntrada, peticion: Request, db: Session = Depends(get_db),
           admin: Usuario = Depends(get_current_admin)):
    gasto = _gasto_o_404(db, gasto_id)
    antes = _foto(gasto)
    nuevo = _aplicar(db, gasto, datos)
    despues = _foto(gasto)
    cambios = {c: AuditoriaService.cambio(antes[c], despues[c]) for c in _CAMPOS if antes[c] != despues[c]}
    if not cambios:
        db.rollback()
        return _salidas(db, [_gasto_o_404(db, gasto_id)])[0]
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="No se pudo guardar: algún dato choca con otro registro.")
    _anotar_proveedor_nuevo(db, nuevo, admin, peticion)
    gasto = _gasto_o_404(db, gasto_id)
    accion = GASTO_PAGADO if antes["estado"] == "pendiente" and despues["estado"] == "pagado" else GASTO_EDITADO
    AuditoriaService.registrar(db, admin, accion, "gasto", gasto.id,
                               {"concepto": gasto.concepto, "cambios": cambios}, peticion)
    return _salidas(db, [gasto])[0]


@router.post("/{gasto_id:int}/pagar")
def pagar(gasto_id: int, peticion: Request, datos: Optional[PagoEntrada] = None,
          db: Session = Depends(get_db), admin: Usuario = Depends(get_current_admin)):
    gasto = _gasto_o_404(db, gasto_id)
    if gasto.estado != "pagado":
        gasto.estado = "pagado"
        gasto.fecha_pago = (datos.fecha_pago if datos and datos.fecha_pago else srv.hoy_local())
        gasto.actualizado_en = datetime.utcnow()
        db.commit()
        AuditoriaService.registrar(db, admin, GASTO_PAGADO, "gasto", gasto.id,
                                   {"concepto": gasto.concepto, "fecha_pago": gasto.fecha_pago.isoformat(),
                                    "total_mxn": str(gasto.total_mxn)}, peticion)
    return _salidas(db, [_gasto_o_404(db, gasto_id)])[0]


@router.delete("/{gasto_id:int}")
def borrar(gasto_id: int, peticion: Request, db: Session = Depends(get_db),
           admin: Usuario = Depends(get_current_admin)):
    """Borra el gasto y sus comprobantes. **La bitácora conserva** lo que era
    y su historia: el original, al borrar, se llevaba también su línea de
    tiempo."""
    gasto = _gasto_o_404(db, gasto_id)
    huella = _huella(gasto)
    guardados = [c.nombre_guardado for c in gasto.comprobantes]
    huella["comprobantes"] = [{"tipo": c.tipo, "nombre": c.nombre, "folio": c.folio, "uuid": c.cfdi_uuid}
                              for c in gasto.comprobantes]
    db.delete(gasto)
    db.commit()
    srv.borrar_binarios(guardados)
    AuditoriaService.registrar(db, admin, GASTO_BORRADO, "gasto", gasto_id, huella, peticion)
    return {"borrado": True}


async def _guardar_comprobante(subida: UploadFile) -> dict:
    """Valida y escribe un comprobante. `ArchivoRechazado` si no entra,
    `_Demasiado` si se pasa del tope. Mismas reglas que el directorio: el tipo
    lo decide la extensión y lo confirman los primeros bytes; las fotos se
    guardan sin metadatos (ni GPS, ni cámara)."""
    nombre = dsrv.nombre_limpio(subida.filename, 255)
    mime, familia = srv.tipo_de_archivo(nombre)
    tope = settings.GASTOS_MAX_MB * 1024 * 1024
    base = srv.carpeta_en_disco()
    guardado = srv.nuevo_nombre_guardado()
    parcial = base / f".{guardado}.parcial"
    cfdi = None
    try:
        if familia == "xml" or mime in LIMPIABLES:
            contenido = await _leer_todo(subida)
            if familia == "xml":
                cfdi = await run_in_threadpool(srv.leer_cfdi, contenido)
            else:
                parcial.write_bytes(contenido)
                await run_in_threadpool(dsrv.comprobar, parcial, familia)
                try:
                    contenido = await limpiar_subida(contenido, mime)
                except HTTPException as exc:
                    if exc.status_code == 503:
                        raise
                    raise dsrv.ArchivoRechazado(str(exc.detail))
            parcial.write_bytes(contenido)
        else:
            total = 0
            with parcial.open("wb") as destino:
                while True:
                    trozo = await subida.read(_TROZO)
                    if not trozo:
                        break
                    total += len(trozo)
                    if total > tope:
                        raise _Demasiado()
                    destino.write(trozo)
            await run_in_threadpool(dsrv.comprobar, parcial, familia)
        sha = await run_in_threadpool(dsrv.sha256_de, parcial)
        tamano = parcial.stat().st_size
        parcial.rename(base / guardado)
        return {"nombre": nombre, "tipo_mime": mime, "tamano_bytes": tamano, "sha256": sha,
                "nombre_guardado": guardado, "cfdi": cfdi}
    finally:
        parcial.unlink(missing_ok=True)


@router.post("/{gasto_id:int}/comprobantes", status_code=status.HTTP_201_CREATED)
async def subir_comprobante(
    gasto_id: int, peticion: Request,
    archivo: UploadFile = File(...),
    tipo: Literal["cotizacion", "orden_compra", "factura", "albaran", "pago", "pedido"] = Form(...),
    folio: Optional[str] = Form(None, max_length=60),
    fecha: Optional[date] = Form(None),
    db: Session = Depends(get_db), admin: Usuario = Depends(get_current_admin),
):
    """Un documento al expediente. Con el XML del CFDI, el folio, la fecha y
    el folio fiscal salen de él; si esa factura ya está en otro gasto, no
    entra. Un comprobante de pago marca el gasto como pagado."""
    gasto = _gasto_o_404(db, gasto_id)
    try:
        datos = await _guardar_comprobante(archivo)
    except _Demasiado:
        raise _demasiado()
    except dsrv.ArchivoRechazado as exc:
        raise _422(str(exc))

    cfdi = datos.pop("cfdi")
    avisos = list(cfdi["avisos"]) if cfdi else []
    folio_fiscal = cfdi["uuid"] if cfdi else None
    if folio_fiscal:
        previo = db.query(GastoComprobante).filter(GastoComprobante.cfdi_uuid == folio_fiscal).first()
        if previo is not None:
            srv.borrar_binarios([datos["nombre_guardado"]])
            raise HTTPException(status_code=409,
                                detail=f"Esa factura (UUID {folio_fiscal}) ya está en el gasto #{previo.gasto_id}.")
    fecha_cfdi = date.fromisoformat(cfdi["fecha"]) if cfdi and cfdi["fecha"] else None
    comprobante = GastoComprobante(
        gasto_id=gasto.id, tipo=tipo,
        folio=(folio or "").strip() or (cfdi["folio"] if cfdi else None),
        fecha=fecha or fecha_cfdi, cfdi_uuid=folio_fiscal,
        subido_por=admin.id, creado_en=datetime.utcnow(), **datos,
    )
    db.add(comprobante)
    pagado_ahora = False
    if tipo == "pago" and gasto.estado != "pagado":
        gasto.estado = "pagado"
        gasto.fecha_pago = comprobante.fecha or srv.hoy_local()
        gasto.actualizado_en = datetime.utcnow()
        pagado_ahora = True
    if cfdi and tipo == "factura" and cfdi["moneda"] == gasto.moneda and abs(cfdi["total"] - gasto.total) >= 1:
        avisos.append("total_distinto")
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        srv.borrar_binarios([datos["nombre_guardado"]])
        raise HTTPException(status_code=409, detail="Esa factura ya está registrada en otro gasto.")
    db.refresh(comprobante)
    AuditoriaService.registrar(db, admin, COMPROBANTE_SUBIDO, "gasto", gasto.id,
                               {"tipo": tipo, "nombre": comprobante.nombre, "folio": comprobante.folio,
                                "uuid": folio_fiscal, "tamano_bytes": comprobante.tamano_bytes,
                                "comprobante_id": comprobante.id}, peticion)
    if pagado_ahora:
        AuditoriaService.registrar(db, admin, GASTO_PAGADO, "gasto", gasto.id,
                                   {"concepto": gasto.concepto, "fecha_pago": gasto.fecha_pago.isoformat(),
                                    "por_comprobante": comprobante.id}, peticion)
    return {"comprobante": _salida_comprobante(comprobante, {admin.id: admin.nombre}), "avisos": avisos,
            "gasto": _salidas(db, [_gasto_o_404(db, gasto.id)])[0]}

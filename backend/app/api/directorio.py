"""El directorio de documentos: carpetas, archivos, versiones y papelera.

Escribe solo TI; lee quien la carpeta deje (ver `services/directorio_service`).
Lo que no se alcanza —otra visibilidad, la papelera, un id que no existe—
responde 404 igual, para no confirmar que existe.

No se mezcla con el expediente (`api/documentos.py`): aquello son los papeles
de una persona; esto, los de la empresa.
"""

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Literal, Optional

from fastapi import (APIRouter, Depends, File, Form, HTTPException, Query, Request,
                     UploadFile, status)
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import Text, func, literal, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.api.deps import get_current_admin, get_current_user
from app.core import plantas as plantas_mod
from app.core.config import settings
from app.core.db import get_db
from app.core.logging import logger
from app.core.metadatos import LIMPIABLES, limpiar_subida
from app.models import Archivo, ArchivoVersion, Carpeta, Usuario
from app.services import directorio_service as srv
from app.services.auditoria_service import AuditoriaService

router = APIRouter(prefix="/directorio", tags=["Directorio"])

PROFUNDIDAD_MAX = 8
_TROZO = 1024 * 1024
_ID = dict(ge=1, le=2**31 - 1)


# ----------------------------------------------------------------------
# Esquemas
# ----------------------------------------------------------------------

class CarpetaCrear(BaseModel):
    nombre: str = Field(min_length=1, max_length=120)
    padre_id: Optional[int] = Field(None, **_ID)
    visibilidad: Optional[Literal["ti", "todos", "plantas"]] = None
    sitio_ids: List[int] = Field(default_factory=list, max_length=200)
    descripcion: Optional[str] = Field(None, max_length=2000)


class CarpetaEditar(BaseModel):
    nombre: Optional[str] = Field(None, min_length=1, max_length=120)
    # Presente y nulo = mover al primer nivel; ausente = no se mueve.
    padre_id: Optional[int] = Field(None, **_ID)
    visibilidad: Optional[Literal["ti", "todos", "plantas"]] = None
    sitio_ids: Optional[List[int]] = Field(None, max_length=200)
    descripcion: Optional[str] = Field(None, max_length=2000)


class ArchivoEditar(BaseModel):
    nombre: Optional[str] = Field(None, min_length=1, max_length=255)
    descripcion: Optional[str] = Field(None, max_length=2000)
    carpeta_id: Optional[int] = Field(None, **_ID)


# ----------------------------------------------------------------------
# Salidas
# ----------------------------------------------------------------------

def _iso(fecha: Optional[datetime]) -> Optional[str]:
    if fecha is None:
        return None
    return fecha.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


def _persona(u: Optional[Usuario]) -> Optional[dict]:
    return {"id": u.id, "nombre": u.nombre} if u else None


def _salida_archivo(a: Archivo) -> dict:
    return {
        "id": a.id,
        "carpeta_id": a.carpeta_id,
        "nombre": a.nombre,
        "extension": srv.extension(a.nombre).lstrip("."),
        "tipo_mime": a.tipo_mime,
        "tamano_bytes": a.tamano_bytes,
        "sha256": a.sha256,
        "version": a.version,
        "descripcion": a.descripcion,
        "subido_por": _persona(a.autor),
        "creado_en": _iso(a.creado_en),
        "actualizado_en": _iso(a.actualizado_en),
        "en_linea": a.tipo_mime in srv.EN_LINEA,
    }


def _salida_carpeta(c: Carpeta, cuentas: Optional[dict] = None) -> dict:
    sub, arch = (cuentas or {}).get(c.id, (0, 0))
    return {
        "id": c.id,
        "padre_id": c.padre_id,
        "nombre": c.nombre,
        "descripcion": c.descripcion,
        "profundidad": c.profundidad,
        "visibilidad": c.visibilidad,
        "creado_en": _iso(c.creado_en),
        "actualizado_en": _iso(c.actualizado_en),
        "subcarpetas": sub,
        "archivos": arch,
    }


def _cuentas(db: Session, ids: List[int]) -> dict:
    """Subcarpetas y archivos vivos directamente dentro de cada carpeta."""
    if not ids:
        return {}
    sub = dict(db.query(Carpeta.padre_id, func.count(Carpeta.id))
               .filter(Carpeta.padre_id.in_(ids), Carpeta.eliminado_en.is_(None))
               .group_by(Carpeta.padre_id).all())
    arch = dict(db.query(Archivo.carpeta_id, func.count(Archivo.id))
                .filter(Archivo.carpeta_id.in_(ids), Archivo.eliminado_en.is_(None))
                .group_by(Archivo.carpeta_id).all())
    return {i: (sub.get(i, 0), arch.get(i, 0)) for i in ids}


def _migas(db: Session, carpeta: Carpeta) -> List[dict]:
    cadena = srv.ids_de_ruta(carpeta.ruta)
    nombres = dict(db.query(Carpeta.id, Carpeta.nombre).filter(Carpeta.id.in_(cadena)).all())
    return [{"id": i, "nombre": nombres.get(i, "")} for i in cadena]


def _raiz_de(db: Session, carpeta: Carpeta) -> Carpeta:
    return carpeta if carpeta.padre_id is None else db.get(Carpeta, srv.ids_de_ruta(carpeta.ruta)[0])


# ----------------------------------------------------------------------
# Búsqueda de lo que se alcanza
# ----------------------------------------------------------------------

def _carpeta_o_404(db: Session, usuario: Usuario, carpeta_id: int, con_papelera: bool = False) -> Carpeta:
    carpeta = db.get(Carpeta, carpeta_id) if 0 < carpeta_id < 2**31 else None
    if not srv.alcanzable(db, usuario, carpeta, con_papelera=con_papelera):
        raise HTTPException(status_code=404, detail="Carpeta no encontrada")
    return carpeta


def _archivo_o_404(db: Session, usuario: Usuario, archivo_id: int, para_editar: bool = False) -> Archivo:
    consulta = db.query(Archivo).filter(Archivo.id == archivo_id)
    if para_editar:
        consulta = consulta.with_for_update()
    archivo = consulta.first() if 0 < archivo_id < 2**31 else None
    if (archivo is None or archivo.eliminado_en is not None
            or not srv.alcanzable(db, usuario, archivo.carpeta)):
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    return archivo


def _nombre_carpeta_libre(db: Session, padre_id: Optional[int], nombre: str,
                          excepto: Optional[int] = None) -> None:
    consulta = db.query(Carpeta.id).filter(
        func.coalesce(Carpeta.padre_id, 0) == (padre_id or 0),
        func.lower(Carpeta.nombre) == nombre.lower(),
        Carpeta.eliminado_en.is_(None))
    if excepto:
        consulta = consulta.filter(Carpeta.id != excepto)
    if consulta.first():
        raise HTTPException(status_code=409, detail=f"Ya hay una carpeta «{nombre}» en ese lugar.")


def _nombre_archivo_libre(db: Session, carpeta_id: int, nombre: str,
                          excepto: Optional[int] = None) -> bool:
    consulta = db.query(Archivo.id).filter(
        Archivo.carpeta_id == carpeta_id,
        func.lower(Archivo.nombre) == nombre.lower(),
        Archivo.eliminado_en.is_(None))
    if excepto:
        consulta = consulta.filter(Archivo.id != excepto)
    return consulta.first() is None


def _plantas_de(db: Session, sitio_ids: List[int]):
    vistas, salida = set(), []
    for sid in sitio_ids:
        if sid in vistas:
            continue
        sitio = plantas_mod.planta_valida(db, sid)
        if sitio is None:
            raise HTTPException(status_code=422, detail="Una de las plantas no existe.")
        vistas.add(sid)
        salida.append(sitio)
    return salida


def _nombre_o_422(nombre: str, maximo: int) -> str:
    try:
        return srv.nombre_limpio(nombre, maximo)
    except srv.ArchivoRechazado as exc:
        raise HTTPException(status_code=422, detail=str(exc))


def _comprometer(db: Session, conflicto: str) -> None:
    """Commit, y 409 si la base dice que el nombre ya está: entre la
    comprobación y el commit pudo entrar otra petición con el mismo."""
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail=conflicto)


# ----------------------------------------------------------------------
# Lectura
# ----------------------------------------------------------------------

def _contenido(db: Session, usuario: Usuario, carpeta: Optional[Carpeta]) -> dict:
    es_ti = usuario.rol == "admin"
    if carpeta is None:
        raices = srv.raices_visibles(db, usuario)
        consulta = db.query(Carpeta).filter(Carpeta.padre_id.is_(None), Carpeta.eliminado_en.is_(None))
        if raices is not None:
            consulta = consulta.filter(Carpeta.id.in_(sorted(raices) or [0]))
        hijas = consulta.order_by(func.lower(Carpeta.nombre)).all()
        archivos = []
        cabecera, migas = None, []
    else:
        hijas = (db.query(Carpeta).filter(Carpeta.padre_id == carpeta.id, Carpeta.eliminado_en.is_(None))
                 .order_by(func.lower(Carpeta.nombre)).all())
        archivos = (db.query(Archivo).filter(Archivo.carpeta_id == carpeta.id, Archivo.eliminado_en.is_(None))
                    .order_by(func.lower(Archivo.nombre)).all())
        raiz = _raiz_de(db, carpeta)
        cabecera = _salida_carpeta(carpeta, _cuentas(db, [carpeta.id]))
        cabecera["visibilidad_efectiva"] = raiz.visibilidad
        if es_ti:
            cabecera["plantas"] = [{"id": p.id, "clave": p.clave, "nombre": p.nombre} for p in raiz.plantas]
            cabecera["raiz_id"] = raiz.id
        migas = _migas(db, carpeta)
    cuentas = _cuentas(db, [h.id for h in hijas])
    salida_hijas = []
    for h in hijas:
        fila = _salida_carpeta(h, cuentas)
        if es_ti and h.padre_id is None:
            fila["plantas"] = [{"id": p.id, "clave": p.clave, "nombre": p.nombre} for p in h.plantas]
        salida_hijas.append(fila)
    return {
        "carpeta": cabecera,
        "migas": migas,
        "carpetas": salida_hijas,
        "archivos": [_salida_archivo(a) for a in archivos],
        "puede_editar": es_ti,
    }


@router.get("/raiz")
def raiz(db: Session = Depends(get_db), usuario: Usuario = Depends(get_current_user)):
    return _contenido(db, usuario, None)


@router.get("/carpetas/{carpeta_id}")
def ver_carpeta(carpeta_id: int, db: Session = Depends(get_db),
                usuario: Usuario = Depends(get_current_user)):
    return _contenido(db, usuario, _carpeta_o_404(db, usuario, carpeta_id))


@router.get("/arbol")
def arbol(db: Session = Depends(get_db), usuario: Usuario = Depends(get_current_user)):
    """Todas las carpetas que la persona puede abrir, planas: el árbol lo arma
    la pantalla con `padre_id`."""
    filas = srv.vivas_alcanzables(db, usuario)
    filas.sort(key=lambda c: (c.profundidad, c.nombre.lower()))
    return [{"id": c.id, "padre_id": c.padre_id, "nombre": c.nombre,
             "profundidad": c.profundidad, "visibilidad": c.visibilidad} for c in filas]


@router.get("/buscar")
def buscar(q: str = Query(..., min_length=2, max_length=100),
           db: Session = Depends(get_db), usuario: Usuario = Depends(get_current_user)):
    """Carpetas y archivos por nombre (y archivos también por descripción),
    solo entre lo que la persona alcanza."""
    vivas = srv.vivas_alcanzables(db, usuario)
    if not vivas:
        return {"carpetas": [], "archivos": []}
    por_id = {c.id: c for c in vivas}
    patron = "%" + q.strip().lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"

    def ubicacion(carpeta_id):
        c = por_id.get(carpeta_id)
        return [por_id[i].nombre for i in srv.ids_de_ruta(c.ruta) if i in por_id] if c else []

    carpetas = [c for c in vivas if q.strip().lower() in c.nombre.lower()][:50]
    archivos = (db.query(Archivo)
                .filter(Archivo.carpeta_id.in_(list(por_id)), Archivo.eliminado_en.is_(None),
                        or_(func.lower(Archivo.nombre).like(patron, escape="\\"),
                            func.lower(func.coalesce(Archivo.descripcion, "")).like(patron, escape="\\")))
                .order_by(func.lower(Archivo.nombre)).limit(50).all())
    return {
        "carpetas": [{**_salida_carpeta(c), "ubicacion": ubicacion(c.padre_id)} for c in carpetas],
        "archivos": [{**_salida_archivo(a), "ubicacion": ubicacion(a.carpeta_id)} for a in archivos],
    }


def _servir(ruta: Path, mime: str, nombre: str, descargar: bool) -> FileResponse:
    if not ruta.exists():
        raise HTTPException(status_code=410, detail="El archivo ya no está disponible en el servidor.")
    en_linea = mime in srv.EN_LINEA and not descargar
    return FileResponse(
        path=str(ruta), media_type=mime, filename=nombre,
        content_disposition_type="inline" if en_linea else "attachment",
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"},
    )


@router.get("/archivos/{archivo_id}/descarga")
def descargar(archivo_id: int, descargar: bool = False, db: Session = Depends(get_db),
              usuario: Usuario = Depends(get_current_user)):
    """El archivo. PDF e imágenes se pueden ver en el navegador; todo lo demás
    sale siempre como descarga, y con `descargar=true` también aquellos."""
    a = _archivo_o_404(db, usuario, archivo_id)
    return _servir(srv.carpeta_en_disco() / a.nombre_guardado, a.tipo_mime, a.nombre, descargar)


@router.get("/archivos/{archivo_id}/versiones")
def versiones(archivo_id: int, db: Session = Depends(get_db),
              usuario: Usuario = Depends(get_current_user)):
    a = _archivo_o_404(db, usuario, archivo_id)
    actual = {"version": a.version, "tamano_bytes": a.tamano_bytes, "sha256": a.sha256,
              "tipo_mime": a.tipo_mime, "subido_por": _persona(a.autor),
              "creado_en": _iso(a.actualizado_en), "vigente": True}
    anteriores = [{"version": v.version, "tamano_bytes": v.tamano_bytes, "sha256": v.sha256,
                   "tipo_mime": v.tipo_mime, "subido_por": _persona(v.autor),
                   "creado_en": _iso(v.creado_en), "vigente": False} for v in a.versiones]
    return [actual, *anteriores]


@router.get("/archivos/{archivo_id}/versiones/{version}")
def descargar_version(archivo_id: int, version: int, descargar: bool = False,
                      db: Session = Depends(get_db), usuario: Usuario = Depends(get_current_user)):
    a = _archivo_o_404(db, usuario, archivo_id)
    if version == a.version:
        return _servir(srv.carpeta_en_disco() / a.nombre_guardado, a.tipo_mime, a.nombre, descargar)
    v = next((x for x in a.versiones if x.version == version), None)
    if v is None:
        raise HTTPException(status_code=404, detail="Versión no encontrada")
    base, ext = a.nombre[:-len(srv.extension(a.nombre)) or None], srv.extension(a.nombre)
    return _servir(srv.carpeta_en_disco() / v.nombre_guardado, v.tipo_mime,
                   f"{base} (v{v.version}){ext}", descargar)


# ----------------------------------------------------------------------
# Carpetas (solo TI)
# ----------------------------------------------------------------------

@router.post("/carpetas", status_code=status.HTTP_201_CREATED)
def crear_carpeta(datos: CarpetaCrear, peticion: Request, db: Session = Depends(get_db),
                  admin: Usuario = Depends(get_current_admin)):
    nombre = _nombre_o_422(datos.nombre, 120)
    padre = _carpeta_o_404(db, admin, datos.padre_id) if datos.padre_id else None
    if padre and padre.profundidad >= PROFUNDIDAD_MAX:
        raise HTTPException(status_code=422, detail=f"No caben más de {PROFUNDIDAD_MAX} niveles de carpetas.")
    if padre and datos.visibilidad:
        raise HTTPException(status_code=422,
                            detail="La visibilidad se define en la carpeta de primer nivel; esta la hereda.")
    visibilidad = None if padre else (datos.visibilidad or "ti")
    sitios = []
    if visibilidad == "plantas":
        sitios = _plantas_de(db, datos.sitio_ids)
        if not sitios:
            raise HTTPException(status_code=422, detail="Elija al menos una planta.")
    _nombre_carpeta_libre(db, padre.id if padre else None, nombre)

    ahora = datetime.utcnow()
    carpeta = Carpeta(padre_id=padre.id if padre else None, nombre=nombre, ruta="/",
                      profundidad=(padre.profundidad + 1) if padre else 1,
                      visibilidad=visibilidad, descripcion=(datos.descripcion or "").strip() or None,
                      creado_por=admin.id, creado_en=ahora, actualizado_en=ahora)
    carpeta.plantas = sitios
    db.add(carpeta)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail=f"Ya hay una carpeta «{nombre}» en ese lugar.")
    carpeta.ruta = f"{padre.ruta if padre else '/'}{carpeta.id}/"
    _comprometer(db, f"Ya hay una carpeta «{nombre}» en ese lugar.")
    AuditoriaService.registrar(db, admin, "carpeta.creada", "carpeta", carpeta.id,
                               {"nombre": nombre, "padre_id": carpeta.padre_id,
                                "visibilidad": visibilidad}, peticion)
    return _salida_carpeta(carpeta)


@router.patch("/carpetas/{carpeta_id}")
def editar_carpeta(carpeta_id: int, datos: CarpetaEditar, peticion: Request,
                   db: Session = Depends(get_db), admin: Usuario = Depends(get_current_admin)):
    carpeta = _carpeta_o_404(db, admin, carpeta_id)
    campos = datos.model_fields_set
    cambios = {}

    # Mover: un UPDATE del prefijo de la ruta para todo el subárbol.
    if "padre_id" in campos and datos.padre_id != carpeta.padre_id:
        nuevo = _carpeta_o_404(db, admin, datos.padre_id) if datos.padre_id else None
        vieja = carpeta.ruta
        if nuevo is not None and nuevo.ruta.startswith(vieja):
            raise HTTPException(status_code=409, detail="Una carpeta no puede ir dentro de sí misma.")
        nueva = f"{nuevo.ruta if nuevo else '/'}{carpeta.id}/"
        delta = ((nuevo.profundidad + 1) if nuevo else 1) - carpeta.profundidad
        mas_honda = (db.query(func.max(Carpeta.profundidad))
                     .filter(Carpeta.ruta.like(vieja + "%")).scalar()) or carpeta.profundidad
        if mas_honda + delta > PROFUNDIDAD_MAX:
            raise HTTPException(status_code=422,
                                detail=f"Ahí no cabe: quedarían más de {PROFUNDIDAD_MAX} niveles de carpetas.")
        _nombre_carpeta_libre(db, nuevo.id if nuevo else None, datos.nombre or carpeta.nombre, excepto=carpeta.id)
        cambios["padre_id"] = {"antes": carpeta.padre_id, "despues": nuevo.id if nuevo else None}
        carpeta.padre_id = nuevo.id if nuevo else None
        if nuevo is None:
            # Al subir al primer nivel necesita visibilidad propia: la más
            # cerrada, salvo que se diga otra cosa.
            carpeta.visibilidad = datos.visibilidad or "ti"
        else:
            carpeta.visibilidad = None
            carpeta.plantas = []
        db.flush()
        (db.query(Carpeta).filter(Carpeta.ruta.like(vieja + "%"))
         .update({Carpeta.ruta: literal(nueva, Text) + func.substr(Carpeta.ruta, len(vieja) + 1),
                  Carpeta.profundidad: Carpeta.profundidad + delta},
                 synchronize_session=False))
        db.expire_all()
        carpeta = db.get(Carpeta, carpeta_id)

    if datos.nombre is not None:
        nombre = _nombre_o_422(datos.nombre, 120)
        if nombre != carpeta.nombre:
            _nombre_carpeta_libre(db, carpeta.padre_id, nombre, excepto=carpeta.id)
            cambios["nombre"] = {"antes": carpeta.nombre, "despues": nombre}
            carpeta.nombre = nombre

    if "descripcion" in campos:
        carpeta.descripcion = (datos.descripcion or "").strip() or None

    if datos.visibilidad is not None or datos.sitio_ids is not None:
        if carpeta.padre_id is not None:
            raise HTTPException(status_code=422,
                                detail="La visibilidad se define en la carpeta de primer nivel; esta la hereda.")
        visibilidad = datos.visibilidad or carpeta.visibilidad
        if visibilidad == "plantas":
            sitios = _plantas_de(db, datos.sitio_ids) if datos.sitio_ids is not None else list(carpeta.plantas)
            if not sitios:
                raise HTTPException(status_code=422, detail="Elija al menos una planta.")
            carpeta.plantas = sitios
        else:
            carpeta.plantas = []
        if visibilidad != carpeta.visibilidad:
            cambios["visibilidad"] = {"antes": carpeta.visibilidad, "despues": visibilidad}
        carpeta.visibilidad = visibilidad

    carpeta.actualizado_en = datetime.utcnow()
    _comprometer(db, "Ya hay una carpeta con ese nombre en ese lugar.")
    if cambios:
        accion = "carpeta.movida" if "padre_id" in cambios else "carpeta.editada"
        AuditoriaService.registrar(db, admin, accion, "carpeta", carpeta.id, cambios, peticion)
    return _salida_carpeta(carpeta, _cuentas(db, [carpeta.id]))


@router.delete("/carpetas/{carpeta_id}")
def borrar_carpeta(carpeta_id: int, peticion: Request, db: Session = Depends(get_db),
                   admin: Usuario = Depends(get_current_admin)):
    """A la papelera, con todo lo que tiene dentro. Se puede restaurar durante
    `DIRECTORIO_PAPELERA_DIAS`."""
    carpeta = _carpeta_o_404(db, admin, carpeta_id)
    carpeta.eliminado_en = datetime.utcnow()
    carpeta.eliminado_por = admin.id
    db.commit()
    AuditoriaService.registrar(db, admin, "carpeta.eliminada", "carpeta", carpeta.id,
                               {"nombre": carpeta.nombre}, peticion)
    return {"ok": True, "purga_en": _iso(carpeta.eliminado_en + timedelta(days=settings.DIRECTORIO_PAPELERA_DIAS))}


# ----------------------------------------------------------------------
# Archivos (solo TI)
# ----------------------------------------------------------------------

class _Demasiado(Exception):
    pass


async def _guardar(subida: UploadFile, presupuesto: int) -> dict:
    """Valida y escribe una subida en disco. Devuelve lo que hay que guardar
    en la fila. Lanza `ArchivoRechazado` (el archivo no entra) o `_Demasiado`
    (la petición entera se pasa del tope)."""
    nombre = srv.nombre_limpio(subida.filename, 255)
    mime, familia = srv.tipo_de(nombre)
    base = srv.carpeta_en_disco()
    guardado = uuid.uuid4().hex
    parcial = base / f".{guardado}.parcial"
    try:
        if mime in LIMPIABLES:
            contenido = await subida.read(presupuesto + 1)
            if len(contenido) > presupuesto:
                raise _Demasiado()
            parcial.write_bytes(contenido)
            await run_in_threadpool(srv.comprobar, parcial, familia)
            # Sin metadatos: ni GPS, ni cámara, ni fecha (core/metadatos.py).
            try:
                contenido = await limpiar_subida(contenido, mime)
            except HTTPException as exc:
                if exc.status_code == 503:
                    raise
                raise srv.ArchivoRechazado(str(exc.detail))
            parcial.write_bytes(contenido)
        else:
            total = 0
            with parcial.open("wb") as f:
                while True:
                    trozo = await subida.read(_TROZO)
                    if not trozo:
                        break
                    total += len(trozo)
                    if total > presupuesto:
                        raise _Demasiado()
                    f.write(trozo)
            await run_in_threadpool(srv.comprobar, parcial, familia)
        sha = await run_in_threadpool(srv.sha256_de, parcial)
        tamano = parcial.stat().st_size
        parcial.rename(base / guardado)
        return {"nombre": nombre, "tipo_mime": mime, "tamano_bytes": tamano,
                "sha256": sha, "nombre_guardado": guardado}
    finally:
        parcial.unlink(missing_ok=True)


def _demasiado() -> HTTPException:
    return HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                         detail=f"La subida supera {settings.DIRECTORIO_MAX_MB} MB.")


@router.post("/carpetas/{carpeta_id}/archivos", status_code=status.HTTP_201_CREATED)
async def subir(carpeta_id: int, peticion: Request,
                archivos: List[UploadFile] = File(...),
                descripcion: Optional[str] = Form(None, max_length=2000),
                db: Session = Depends(get_db), admin: Usuario = Depends(get_current_admin)):
    """Uno o varios archivos a una carpeta. Los que no entran se devuelven en
    `rechazados` con su motivo y no impiden que entren los demás; si no entra
    ninguno, 422."""
    carpeta = _carpeta_o_404(db, admin, carpeta_id)
    if len(archivos) > settings.DIRECTORIO_MAX_ARCHIVOS:
        raise HTTPException(status_code=422,
                            detail=f"Se suben como mucho {settings.DIRECTORIO_MAX_ARCHIVOS} archivos a la vez.")
    presupuesto = settings.DIRECTORIO_MAX_MB * 1024 * 1024
    listos, rechazados, vistos = [], [], set()
    try:
        for subida in archivos:
            nombre_mostrado = (subida.filename or "")[-255:] or "(sin nombre)"
            try:
                nombre = srv.nombre_limpio(subida.filename, 255)
                if nombre.lower() in vistos or not _nombre_archivo_libre(db, carpeta.id, nombre):
                    raise srv.ArchivoRechazado(
                        f"Ya hay un archivo «{nombre}» en esta carpeta. Para cambiar su contenido, "
                        "súbalo como versión nueva.")
                datos = await _guardar(subida, presupuesto)
            except srv.ArchivoRechazado as exc:
                rechazados.append({"nombre": nombre_mostrado, "motivo": str(exc)})
                continue
            vistos.add(datos["nombre"].lower())
            presupuesto -= datos["tamano_bytes"]
            listos.append(datos)
    except _Demasiado:
        srv.borrar_binarios(d["nombre_guardado"] for d in listos)
        raise _demasiado()
    except BaseException:
        srv.borrar_binarios(d["nombre_guardado"] for d in listos)
        raise

    if not listos:
        primero = rechazados[0] if rechazados else {"nombre": "", "motivo": "No llegó ningún archivo."}
        raise HTTPException(status_code=422, detail=f"{primero['nombre']}: {primero['motivo']}")

    ahora = datetime.utcnow()
    filas = [Archivo(carpeta_id=carpeta.id, descripcion=(descripcion or "").strip() or None,
                     subido_por=admin.id, creado_en=ahora, actualizado_en=ahora, version=1, **d)
             for d in listos]
    db.add_all(filas)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        srv.borrar_binarios(d["nombre_guardado"] for d in listos)
        raise HTTPException(status_code=409, detail="Otro archivo con el mismo nombre entró a la vez. Intente de nuevo.")
    for a in filas:
        db.refresh(a)
        AuditoriaService.registrar(db, admin, "archivo.subido", "archivo", a.id,
                                   {"nombre": a.nombre, "carpeta_id": carpeta.id,
                                    "tamano_bytes": a.tamano_bytes}, peticion)
    logger.info("Archivos subidos al directorio",
                extra={"carpeta_id": carpeta.id, "subidos": len(filas), "rechazados": len(rechazados)})
    return {"subidos": [_salida_archivo(a) for a in filas], "rechazados": rechazados}


@router.put("/archivos/{archivo_id}/contenido")
async def reemplazar(archivo_id: int, peticion: Request, archivo: UploadFile = File(...),
                     db: Session = Depends(get_db), admin: Usuario = Depends(get_current_admin)):
    """Una versión nueva del mismo archivo. La anterior pasa al historial; se
    guardan diez en total, contando la vigente."""
    a = _archivo_o_404(db, admin, archivo_id, para_editar=True)
    try:
        nombre_nuevo = srv.nombre_limpio(archivo.filename, 255)
    except srv.ArchivoRechazado as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if srv.extension(nombre_nuevo) != srv.extension(a.nombre):
        raise HTTPException(status_code=422,
                            detail=f"La versión nueva tiene que ser del mismo tipo ({srv.extension(a.nombre)}).")
    try:
        datos = await _guardar(archivo, settings.DIRECTORIO_MAX_MB * 1024 * 1024)
    except srv.ArchivoRechazado as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except _Demasiado:
        raise _demasiado()
    if datos["sha256"] == a.sha256:
        srv.borrar_binarios([datos["nombre_guardado"]])
        raise HTTPException(status_code=409, detail="Es idéntico a la versión vigente.")

    db.add(ArchivoVersion(archivo_id=a.id, version=a.version, nombre_guardado=a.nombre_guardado,
                          tipo_mime=a.tipo_mime, tamano_bytes=a.tamano_bytes, sha256=a.sha256,
                          subido_por=a.subido_por, creado_en=a.actualizado_en))
    anterior = a.version
    a.version = anterior + 1
    a.nombre_guardado = datos["nombre_guardado"]
    a.tipo_mime = datos["tipo_mime"]
    a.tamano_bytes = datos["tamano_bytes"]
    a.sha256 = datos["sha256"]
    a.subido_por = admin.id
    a.actualizado_en = datetime.utcnow()
    db.flush()
    sobran = srv.recortar_versiones(db, a)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        srv.borrar_binarios([datos["nombre_guardado"]])
        raise HTTPException(status_code=409, detail="Otra versión entró a la vez. Intente de nuevo.")
    srv.borrar_binarios(sobran)
    db.refresh(a)
    AuditoriaService.registrar(db, admin, "archivo.reemplazado", "archivo", a.id,
                               {"nombre": a.nombre, "version": {"antes": anterior, "despues": a.version}},
                               peticion)
    return _salida_archivo(a)


@router.patch("/archivos/{archivo_id}")
def editar_archivo(archivo_id: int, datos: ArchivoEditar, peticion: Request,
                   db: Session = Depends(get_db), admin: Usuario = Depends(get_current_admin)):
    a = _archivo_o_404(db, admin, archivo_id)
    cambios = {}
    destino_id = a.carpeta_id
    if datos.carpeta_id is not None and datos.carpeta_id != a.carpeta_id:
        destino_id = _carpeta_o_404(db, admin, datos.carpeta_id).id
    nombre = a.nombre
    if datos.nombre is not None:
        nombre = _nombre_o_422(datos.nombre, 255)
        # La extensión decide cómo se abre en el equipo de quien lo descarga:
        # no se cambia renombrando (un .txt que pasa a .html).
        if srv.extension(nombre) != srv.extension(a.nombre):
            raise HTTPException(status_code=422,
                                detail=f"El nombre tiene que conservar la extensión {srv.extension(a.nombre)}.")
    if (nombre != a.nombre or destino_id != a.carpeta_id) and not _nombre_archivo_libre(
            db, destino_id, nombre, excepto=a.id):
        raise HTTPException(status_code=409, detail=f"Ya hay un archivo «{nombre}» en esa carpeta.")
    if nombre != a.nombre:
        cambios["nombre"] = {"antes": a.nombre, "despues": nombre}
        a.nombre = nombre
    if destino_id != a.carpeta_id:
        cambios["carpeta_id"] = {"antes": a.carpeta_id, "despues": destino_id}
        a.carpeta_id = destino_id
    if "descripcion" in datos.model_fields_set:
        a.descripcion = (datos.descripcion or "").strip() or None
    _comprometer(db, "Ya hay un archivo con ese nombre en esa carpeta.")
    if cambios:
        accion = "archivo.movido" if "carpeta_id" in cambios else "archivo.editado"
        AuditoriaService.registrar(db, admin, accion, "archivo", a.id, cambios, peticion)
    db.refresh(a)
    return _salida_archivo(a)


@router.delete("/archivos/{archivo_id}")
def borrar_archivo(archivo_id: int, peticion: Request, db: Session = Depends(get_db),
                   admin: Usuario = Depends(get_current_admin)):
    a = _archivo_o_404(db, admin, archivo_id)
    a.eliminado_en = datetime.utcnow()
    a.eliminado_por = admin.id
    db.commit()
    AuditoriaService.registrar(db, admin, "archivo.eliminado", "archivo", a.id,
                               {"nombre": a.nombre, "carpeta_id": a.carpeta_id}, peticion)
    return {"ok": True, "purga_en": _iso(a.eliminado_en + timedelta(days=settings.DIRECTORIO_PAPELERA_DIAS))}


# ----------------------------------------------------------------------
# Papelera (solo TI)
# ----------------------------------------------------------------------

@router.get("/papelera")
def papelera(db: Session = Depends(get_db), admin: Usuario = Depends(get_current_admin)):
    dias = settings.DIRECTORIO_PAPELERA_DIAS
    carpetas = db.query(Carpeta).filter(Carpeta.eliminado_en.isnot(None)).all()
    archivos = db.query(Archivo).filter(Archivo.eliminado_en.isnot(None)).all()
    ids = set()
    for c in carpetas:
        ids.update(srv.ids_de_ruta(c.ruta))
    for a in archivos:
        ids.update(srv.ids_de_ruta(a.carpeta.ruta))
    info = {i: (n, e) for i, n, e in db.query(Carpeta.id, Carpeta.nombre, Carpeta.eliminado_en)
            .filter(Carpeta.id.in_(sorted(ids) or [0])).all()}
    quienes = dict(db.query(Usuario.id, Usuario.nombre).filter(Usuario.id.in_(
        sorted({x.eliminado_por for x in [*carpetas, *archivos] if x.eliminado_por}) or [0])).all())

    def fila(tipo, x, cadena):
        # Restaurable si nada por encima sigue en la papelera.
        return {
            "tipo": tipo, "id": x.id, "nombre": x.nombre,
            "ubicacion": [info[i][0] for i in cadena if i in info],
            "eliminado_en": _iso(x.eliminado_en),
            "eliminado_por": quienes.get(x.eliminado_por),
            "purga_en": _iso(x.eliminado_en + timedelta(days=dias)),
            "restaurable": not any(info.get(i, (None, None))[1] for i in cadena),
            **({"tamano_bytes": x.tamano_bytes, "extension": srv.extension(x.nombre).lstrip(".")}
               if tipo == "archivo" else {}),
        }

    salida = [fila("carpeta", c, srv.ids_de_ruta(c.ruta)[:-1]) for c in carpetas]
    salida += [fila("archivo", a, srv.ids_de_ruta(a.carpeta.ruta)) for a in archivos]
    salida.sort(key=lambda f: f["eliminado_en"], reverse=True)
    return salida


@router.post("/papelera/{tipo}/{item_id}/restaurar")
def restaurar(tipo: Literal["carpeta", "archivo"], item_id: int, peticion: Request,
              db: Session = Depends(get_db), admin: Usuario = Depends(get_current_admin)):
    if not 0 < item_id < 2**31:
        raise HTTPException(status_code=404, detail="No está en la papelera")
    if tipo == "carpeta":
        x = db.get(Carpeta, item_id)
        if x is None or x.eliminado_en is None:
            raise HTTPException(status_code=404, detail="No está en la papelera")
        arriba = srv.ids_de_ruta(x.ruta)[:-1]
        nombre_libre = lambda: _nombre_carpeta_libre(db, x.padre_id, x.nombre)  # noqa: E731
    else:
        x = db.get(Archivo, item_id)
        if x is None or x.eliminado_en is None:
            raise HTTPException(status_code=404, detail="No está en la papelera")
        arriba = srv.ids_de_ruta(x.carpeta.ruta)

        def nombre_libre():
            if not _nombre_archivo_libre(db, x.carpeta_id, x.nombre):
                raise HTTPException(status_code=409,
                                    detail=f"Ya hay otro «{x.nombre}» en esa carpeta. Renómbrelo antes de restaurar.")
    bloqueo = srv.eliminadas(db, arriba)
    if bloqueo:
        primera = db.get(Carpeta, min(bloqueo, key=lambda i: arriba.index(i)))
        raise HTTPException(status_code=409,
                            detail=f"Está dentro de «{primera.nombre}», que también está en la papelera. "
                                   "Restaure primero esa carpeta.")
    nombre_libre()
    x.eliminado_en = None
    x.eliminado_por = None
    _comprometer(db, "Ya hay otro elemento con ese nombre en ese lugar.")
    AuditoriaService.registrar(db, admin, f"{tipo}.restaurada" if tipo == "carpeta" else "archivo.restaurado",
                               tipo, x.id, {"nombre": x.nombre}, peticion)
    return {"ok": True}

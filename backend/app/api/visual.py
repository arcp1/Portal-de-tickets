"""Catálogo visual: las fotos del problema y las de la solución.

Dos puertas distintas sobre la misma tabla:

  * `/visual/...`        — lo que usa quien tiene el problema. Sólo lee fichas
    publicadas de su propia planta, y lo único que puede escribir son los tres
    contadores que dicen si una ficha acierta.
  * `/admin/visual/...`  — donde TI documenta: la ficha, sus fotos y el momento
    en que deja de ser un borrador y empieza a contestarle a la gente.

**Publicar es un acto con consecuencias**, igual que en las soluciones
generales: mientras es borrador no se le enseña a nadie, y al publicar hace
falta al menos una foto del síntoma. Una ficha sin foto no puede hacer la única
pregunta que justifica todo esto —"¿se ve así?"— y publicarla sólo conseguiría
que un usuario recibiera una tarjeta vacía.
"""

import mimetypes
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin, get_current_user, usuario_con_cupo_ia
from app.core.archivos import contenido_coincide
from app.core.metadatos import limpiar_subida
from app.core.config import settings
from app.core.db import get_db
from app.core.logging import logger
from app.models import FichaVisual, ImagenFicha, Ticket, TicketAdjunto, Usuario
from app.services.auditoria_service import AuditoriaService
from app.services.kb_service import solucion_es_valida
from app.services.ollama_client import CATEGORIAS_VALIDAS, ollama
from app.services.visual_service import VisualService, texto_indexable

router = APIRouter(prefix="/visual", tags=["Catálogo visual"])
admin_router = APIRouter(prefix="/admin/visual", tags=["Catálogo visual (admin)"])

# Sólo imágenes. Aquí no caben PDF ni texto: lo que se guarda es **cómo se ve**
# un problema, y eso o es una foto o no es nada. Un PDF en una tarjeta que
# pregunta "¿se ve así?" no se puede mirar de un vistazo, que es justo lo que
# tiene que poder hacerse.
TIPOS_IMAGEN = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/heic": ".heic",
}

ROLES = ("sintoma", "solucion")
ESTADOS = ("borrador", "publicada", "archivada")

FICHA_CREADA = "visual.creada"
FICHA_EDITADA = "visual.editada"
FICHA_BORRADA = "visual.borrada"
FICHA_PUBLICADA = "visual.publicada"
IMAGEN_SUBIDA = "visual.imagen_subida"
IMAGEN_BORRADA = "visual.imagen_borrada"
FICHA_DESDE_TICKET = "visual.desde_ticket"


def _carpeta() -> Path:
    ruta = Path(settings.VISUAL_RUTA)
    ruta.mkdir(parents=True, exist_ok=True)
    return ruta


# ---------------------------------------------------------------------------
# Lo que ve quien tiene el problema
# ---------------------------------------------------------------------------
class ReconocerRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    texto: str = Field(min_length=1, max_length=2000)
    categoria: Optional[str] = None


class ConfirmarRequest(BaseModel):
    ficha_id: int


class DescartarRequest(BaseModel):
    ficha_ids: List[int] = []
    # Lo que la persona había escrito. Sin esto se sabe que ninguna ficha era
    # la suya y **no sobre qué**, que es la mitad que sirve para escribir la
    # ficha que falta.
    consulta: Optional[str] = Field(default=None, max_length=2000)


class ResultadoRequest(BaseModel):
    ficha_id: int
    resuelto: bool
    consulta: Optional[str] = Field(default=None, max_length=2000)


@router.post("/reconocer")
def reconocer(
    peticion: ReconocerRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(usuario_con_cupo_ia),
):
    """¿Esto es un problema que se reconoce mirándolo? Si lo es, qué enseñarle.

    `activado: false` es la respuesta normal y significa "sigue por donde
    ibas": la inmensa mayoría de las incidencias no son visuales y no deben
    notar que esto existe. En `motivo` viene por qué, que es lo que se puede
    depurar después.
    """
    return VisualService.reconocer(
        db, peticion.texto, current_user.sitio_id, categoria=peticion.categoria,
        usuario_id=current_user.id,
    )


@router.post("/confirmar")
def confirmar(
    peticion: ConfirmarRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """"Sí, es ésta." Devuelve la solución atada a esa foto, y sus pasos."""
    resultado = VisualService.confirmar(db, peticion.ficha_id, current_user.sitio_id)
    if resultado is None:
        raise HTTPException(status_code=404, detail="Ficha no encontrada")
    return resultado


@router.post("/descartar")
def descartar(
    peticion: DescartarRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """"No es ninguna de éstas." Se anota, y quien llama sigue con su flujo."""
    return {"anotadas": VisualService.descartar(
        db, peticion.ficha_ids, current_user.sitio_id,
        texto=peticion.consulta, usuario_id=current_user.id,
    )}


@router.post("/resultado")
def resultado(
    peticion: ResultadoRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """"¿Se arregló?" — el desenlace, que es lo que de verdad hay que medir.

    Reconocer la foto ya quedó contado en `/confirmar`. Esto cuenta otra cosa:
    si la solución atada a esa foto **funcionó**. Una ficha con la foto
    perfecta y la solución equivocada la reconoce todo el mundo y no arregla a
    nadie; sin esta pregunta, en el tablero luce igual que la mejor del
    catálogo.
    """
    salida = VisualService.marcar_resultado(
        db, peticion.ficha_id, current_user.sitio_id, peticion.resuelto,
        texto=peticion.consulta, usuario_id=current_user.id,
    )
    if salida is None:
        raise HTTPException(status_code=404, detail="Ficha no encontrada")
    return salida


@router.get("/fichas/{ficha_id}/imagenes/{imagen_id}")
def ver_imagen(
    ficha_id: int,
    imagen_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """La foto, en línea.

    Un administrador ve también las de sus borradores: si no, no habría manera
    de revisar una ficha antes de publicarla, que es justo lo que hay que hacer
    antes de publicarla.
    """
    ficha = db.query(FichaVisual).filter(
        FichaVisual.id == ficha_id,
    ).first()
    # El rol de admin no cruza de planta: el filtro por sitio va arriba, para
    # todos. Lo que el rol añade es ver lo que todavía no está publicado.
    if not ficha or (ficha.estado != "publicada" and current_user.rol != "admin"):
        raise HTTPException(status_code=404, detail="Imagen no encontrada")

    imagen = db.query(ImagenFicha).filter(
        ImagenFicha.id == imagen_id,
        ImagenFicha.ficha_id == ficha.id,
    ).first()
    if not imagen:
        raise HTTPException(status_code=404, detail="Imagen no encontrada")

    ruta = _carpeta() / imagen.nombre_guardado
    if not ruta.exists():
        # La fila está y el archivo no: pasa al restaurar la base sin el
        # volumen. Se dice claro en vez de devolver un 500.
        raise HTTPException(status_code=410,
                            detail="La imagen ya no está disponible en el servidor.")

    return FileResponse(
        path=str(ruta),
        media_type=imagen.tipo_mime,
        filename=imagen.nombre_original,
        content_disposition_type="inline",
    )


# ---------------------------------------------------------------------------
# Donde TI documenta
# ---------------------------------------------------------------------------
class FichaCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    titulo: str = Field(min_length=4, max_length=200)
    sintoma: str = Field(min_length=10, max_length=5000)
    # **El mismo mínimo que el portal le exige a cualquier solución**, y no uno
    # propio más flojo. Cuando alguien reconoce su defecto en la foto y dice
    # que se arregló, esto se guarda como la solución de un ticket
    # auto-resuelto; con un mínimo menor, esa ficha creaba fichas que después
    # el alta de ticket rechazaba con un 422 que nadie veía —el registro de la
    # deflexión se perdía en silencio y la métrica quedaba corta sin que nada
    # lo dijera—.
    solucion: str = Field(min_length=settings.SOLUCION_MIN_LONGITUD, max_length=5000)
    categoria: Optional[str] = None
    frases: Optional[str] = Field(default=None, max_length=5000)
    descartado: Optional[str] = Field(default=None, max_length=5000)


class FichaUpdate(BaseModel):
    # Los mismos mínimos que al crear. Editar dejaba vaciar el título, el
    # síntoma o la solución de una ficha ya publicada: la foto seguía
    # reconociéndose y la persona recibía una respuesta en blanco.
    model_config = ConfigDict(str_strip_whitespace=True)

    titulo: Optional[str] = Field(default=None, min_length=4, max_length=200)
    sintoma: Optional[str] = Field(default=None, min_length=10, max_length=5000)
    solucion: Optional[str] = Field(default=None, min_length=settings.SOLUCION_MIN_LONGITUD,
                                    max_length=5000)
    categoria: Optional[str] = None
    frases: Optional[str] = None
    descartado: Optional[str] = None


class ImagenUpdate(BaseModel):
    pie: Optional[str] = None
    orden: Optional[int] = None
    rol: Optional[str] = None


class ProbarRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    texto: str = Field(min_length=1, max_length=2000)
    categoria: Optional[str] = None


def _validar(categoria: Optional[str], rol: Optional[str] = None):
    if categoria and categoria not in CATEGORIAS_VALIDAS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Categoría inválida. Se acepta: " + ", ".join(CATEGORIAS_VALIDAS),
        )
    if rol is not None and rol not in ROLES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="El rol de una imagen es 'sintoma' o 'solucion'.",
        )


def _ficha_del_sitio(db: Session, ficha_id: int, admin: Usuario) -> FichaVisual:
    ficha = db.query(FichaVisual).filter(
        FichaVisual.id == ficha_id,
    ).first()
    if not ficha:
        raise HTTPException(status_code=404, detail="Ficha no encontrada")
    return ficha


def _salida(ficha: FichaVisual) -> dict:
    imagenes = sorted(ficha.imagenes, key=lambda i: (i.rol, i.orden or 0, i.id))
    return {
        "id": ficha.id,
        "titulo": ficha.titulo,
        "sintoma": ficha.sintoma,
        "solucion": ficha.solucion,
        "descartado": ficha.descartado,
        "frases": ficha.frases,
        "categoria": ficha.categoria,
        "estado": ficha.estado,
        "ticket_origen_id": ficha.ticket_origen_id,
        # **Publicada y sin vector es un estado real**, no un imposible: si
        # Ollama estaba caído al guardar, la ficha sólo se encuentra por sus
        # frases literales. La pantalla lo enseña para que se pueda reindexar
        # en vez de quedarse pensando que la búsqueda "a veces no la halla".
        "indexada": ficha.embedding is not None,
        "veces_mostrada": ficha.veces_mostrada or 0,
        "veces_confirmada": ficha.veces_confirmada or 0,
        "veces_descartada": ficha.veces_descartada or 0,
        "veces_resuelta": ficha.veces_resuelta or 0,
        "creado_en": ficha.creado_en,
        "actualizado_en": ficha.actualizado_en,
        "autor_nombre": ficha.autor.nombre if ficha.autor else None,
        "imagenes": [
            {
                "id": i.id, "rol": i.rol, "orden": i.orden, "pie": i.pie,
                "nombre_original": i.nombre_original, "tamano_bytes": i.tamano_bytes,
            }
            for i in imagenes
        ],
    }


def _reindexar(ficha: FichaVisual) -> bool:
    """Regenera el vector de la ficha. False si Ollama no pudo.

    No levanta: una ficha sin vector se sigue pudiendo escribir, leer y
    publicar. Lo que pierde es aparecer en la búsqueda por significado, y eso
    se arregla reindexando cuando Ollama vuelva.
    """
    vector = ollama.generar_embedding(
        texto_indexable(ficha.titulo, ficha.sintoma, ficha.frases, ficha.categoria),
        tarea="documento",
    )
    if vector is None:
        return False
    ficha.embedding = vector
    return True


@admin_router.get("")
def listar(
    estado: Optional[str] = None,
    categoria: Optional[str] = None,
    buscar: Optional[str] = None,
    db: Session = Depends(get_db),
    admin: Usuario = Depends(get_current_admin),
):
    consulta = db.query(FichaVisual)
    if estado:
        consulta = consulta.filter(FichaVisual.estado == estado)
    if categoria:
        consulta = consulta.filter(FichaVisual.categoria == categoria)
    if buscar:
        patron = f"%{buscar.strip()}%"
        consulta = consulta.filter(or_(
            FichaVisual.titulo.ilike(patron),
            FichaVisual.sintoma.ilike(patron),
            FichaVisual.frases.ilike(patron),
        ))
    filas = consulta.order_by(FichaVisual.estado, FichaVisual.titulo).all()
    return [_salida(f) for f in filas]


@admin_router.post("", status_code=status.HTTP_201_CREATED)
def crear(
    datos: FichaCreate,
    peticion: Request,
    db: Session = Depends(get_db),
    admin: Usuario = Depends(get_current_admin),
):
    """Crea la ficha. Nace como borrador: todavía no tiene foto."""
    _validar(datos.categoria)

    ficha = FichaVisual(
        sitio_id=admin.sitio_id,
        titulo=datos.titulo.strip(),
        sintoma=datos.sintoma.strip(),
        solucion=datos.solucion.strip(),
        descartado=(datos.descartado or "").strip() or None,
        frases=(datos.frases or "").strip() or None,
        # En blanco es «sin categoría», no una categoría llamada "".
        categoria=datos.categoria or None,
        estado="borrador",
        creado_por=admin.id,
        creado_en=datetime.utcnow(),
    )
    _reindexar(ficha)
    db.add(ficha)
    db.commit()
    db.refresh(ficha)

    AuditoriaService.registrar(db, admin, FICHA_CREADA, "ficha_visual", ficha.id,
                               {"titulo": ficha.titulo}, peticion)
    return _salida(ficha)


@admin_router.patch("/{ficha_id}")
def editar(
    ficha_id: int,
    cambios: FichaUpdate,
    peticion: Request,
    db: Session = Depends(get_db),
    admin: Usuario = Depends(get_current_admin),
):
    ficha = _ficha_del_sitio(db, ficha_id, admin)
    _validar(cambios.categoria)

    cambio_texto = False
    for campo in ("titulo", "sintoma", "solucion", "descartado", "frases", "categoria"):
        valor = getattr(cambios, campo)
        if valor is None:
            continue
        if campo == "categoria":
            valor = valor.strip() or None
        setattr(ficha, campo, valor.strip() if isinstance(valor, str) else valor)
        # La solución no se vectoriza —ver `texto_indexable`—, así que
        # corregirla no obliga a rehacer el vector.
        if campo in ("titulo", "sintoma", "frases", "categoria"):
            cambio_texto = True

    if cambio_texto and not _reindexar(ficha):
        logger.warning("Ficha visual editada sin poder regenerar su vector",
                       extra={"ficha_id": ficha.id})

    ficha.actualizado_por = admin.id
    ficha.actualizado_en = datetime.utcnow()
    db.commit()
    db.refresh(ficha)

    AuditoriaService.registrar(db, admin, FICHA_EDITADA, "ficha_visual", ficha.id,
                               {"titulo": ficha.titulo}, peticion)
    return _salida(ficha)


@admin_router.post("/{ficha_id}/estado/{nuevo}")
def cambiar_estado(
    ficha_id: int,
    nuevo: str,
    peticion: Request,
    db: Session = Depends(get_db),
    admin: Usuario = Depends(get_current_admin),
):
    """Publica, archiva o devuelve a borrador.

    **Publicar exige una foto del síntoma.** Sin ella la ficha no puede hacer
    la pregunta que la justifica y el usuario recibiría una tarjeta vacía; es
    la misma idea que impide publicar una solución general sin revisar.
    """
    if nuevo not in ESTADOS:
        raise HTTPException(status_code=422, detail="Estado inválido: " + ", ".join(ESTADOS))

    ficha = _ficha_del_sitio(db, ficha_id, admin)

    if nuevo == "publicada":
        if not any(i.rol == "sintoma" for i in ficha.imagenes):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Para publicar hace falta al menos una foto de cómo se ve el problema.",
            )
        if ficha.embedding is None:
            # No se bloquea: se intenta una vez más y, si tampoco, se publica
            # igual. Una ficha sin vector todavía se encuentra por sus frases
            # literales, y lo contrario —no poder publicar nada mientras Ollama
            # esté caído— deja a TI sin poder trabajar por un servicio opcional.
            if not _reindexar(ficha):
                logger.warning("Ficha publicada sin vector: sólo se hallará por sus frases",
                               extra={"ficha_id": ficha.id})

    ficha.estado = nuevo
    ficha.actualizado_por = admin.id
    ficha.actualizado_en = datetime.utcnow()
    db.commit()
    db.refresh(ficha)

    AuditoriaService.registrar(db, admin, FICHA_PUBLICADA, "ficha_visual", ficha.id,
                               {"titulo": ficha.titulo, "estado": nuevo}, peticion)
    return _salida(ficha)


@admin_router.post("/{ficha_id}/reindexar")
def reindexar(
    ficha_id: int,
    db: Session = Depends(get_db),
    admin: Usuario = Depends(get_current_admin),
):
    """Vuelve a vectorizar la ficha. Para las que se guardaron con Ollama caído."""
    ficha = _ficha_del_sitio(db, ficha_id, admin)
    hecho = _reindexar(ficha)
    db.commit()
    return {"indexada": hecho}


@admin_router.delete("/{ficha_id}", status_code=status.HTTP_204_NO_CONTENT)
def borrar(
    ficha_id: int,
    peticion: Request,
    db: Session = Depends(get_db),
    admin: Usuario = Depends(get_current_admin),
):
    ficha = _ficha_del_sitio(db, ficha_id, admin)

    # Los archivos se van con la fila. A diferencia de un adjunto de ticket,
    # una foto de ficha no es constancia de nada: si la ficha desaparece, la
    # imagen no pertenece a ningún sitio. Se borran **después** del commit:
    # si fallara con los archivos ya borrados, la ficha quedaría sin fotos.
    archivos = [_carpeta() / imagen.nombre_guardado for imagen in ficha.imagenes]

    AuditoriaService.registrar(db, admin, FICHA_BORRADA, "ficha_visual", ficha.id,
                               {"titulo": ficha.titulo}, peticion)
    db.delete(ficha)
    db.commit()
    for archivo in archivos:
        try:
            archivo.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("No se pudo borrar la imagen en disco",
                           extra={"imagen": archivo.name, "error": str(exc)})
    return None


@admin_router.post("/{ficha_id}/imagenes", status_code=status.HTTP_201_CREATED)
async def subir_imagen(
    ficha_id: int,
    peticion: Request,
    archivo: UploadFile = File(...),
    rol: str = Form("sintoma"),
    pie: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    admin: Usuario = Depends(get_current_admin),
):
    """Sube una foto: del defecto, o del paso que lo arregla.

    `rol` es lo que decide en qué mitad de la ficha cae, y las dos hacen falta:
    con la de síntoma se pregunta, con las de solución se explica dónde picar
    sin escribir un párrafo que nadie va a seguir.
    """
    ficha = _ficha_del_sitio(db, ficha_id, admin)
    _validar(None, rol)

    cuantas = db.query(ImagenFicha).filter(ImagenFicha.ficha_id == ficha.id).count()
    if cuantas >= settings.VISUAL_MAX_IMAGENES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Máximo {settings.VISUAL_MAX_IMAGENES} imágenes por ficha.",
        )

    tipo = (archivo.content_type or "").split(";")[0].strip().lower()
    if tipo not in TIPOS_IMAGEN:
        adivinado = mimetypes.guess_type(archivo.filename or "")[0]
        if adivinado in TIPOS_IMAGEN:
            tipo = adivinado
        else:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Aquí sólo caben imágenes: JPG, PNG, WEBP, GIF o HEIC.",
            )

    # Acotado al leer: sin esto un archivo enorme se carga entero en memoria
    # antes de poder rechazarlo.
    limite = settings.VISUAL_MAX_MB * 1024 * 1024
    contenido = await archivo.read(limite + 1)
    if len(contenido) > limite:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"La imagen supera {settings.VISUAL_MAX_MB} MB.",
        )
    if not contenido:
        raise HTTPException(status_code=422, detail="El archivo está vacío.")
    if not contenido_coincide(contenido, tipo):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="El contenido del archivo no corresponde a su tipo.",
        )

    # Sin metadatos: ni GPS, ni cámara, ni fecha (ver core/metadatos.py). Va
    # antes de escribir, para que el tamaño guardado sea el del archivo limpio.
    contenido = await limpiar_subida(contenido, tipo)

    # Nombre generado: el del usuario nunca toca el sistema de archivos.
    nombre_guardado = f"{uuid.uuid4().hex}{TIPOS_IMAGEN[tipo]}"
    (_carpeta() / nombre_guardado).write_bytes(contenido)

    ultimo = max(
        [i.orden or 0 for i in ficha.imagenes if i.rol == rol] or [0]
    )
    imagen = ImagenFicha(
        ficha_id=ficha.id,
        rol=rol,
        orden=ultimo + 1,
        pie=(pie or "").strip()[:300] or None,
        nombre_original=(archivo.filename or "imagen")[:255],
        nombre_guardado=nombre_guardado,
        tipo_mime=tipo,
        tamano_bytes=len(contenido),
        subido_por=admin.id,
        creado_en=datetime.utcnow(),
    )
    db.add(imagen)
    db.commit()
    db.refresh(ficha)

    AuditoriaService.registrar(db, admin, IMAGEN_SUBIDA, "ficha_visual", ficha.id,
                               {"rol": rol, "archivo": imagen.nombre_original}, peticion)
    logger.info("Imagen de ficha visual subida",
                extra={"ficha_id": ficha.id, "rol": rol, "bytes": imagen.tamano_bytes})
    return _salida(ficha)


@admin_router.patch("/{ficha_id}/imagenes/{imagen_id}")
def editar_imagen(
    ficha_id: int,
    imagen_id: int,
    cambios: ImagenUpdate,
    db: Session = Depends(get_db),
    admin: Usuario = Depends(get_current_admin),
):
    """El pie de foto, el orden de los pasos o de qué mitad es la imagen."""
    ficha = _ficha_del_sitio(db, ficha_id, admin)
    imagen = db.query(ImagenFicha).filter(
        ImagenFicha.id == imagen_id,
        ImagenFicha.ficha_id == ficha.id,
    ).first()
    if not imagen:
        raise HTTPException(status_code=404, detail="Imagen no encontrada")

    if cambios.rol is not None:
        _validar(None, cambios.rol)
        imagen.rol = cambios.rol
    if cambios.pie is not None:
        imagen.pie = cambios.pie.strip()[:300] or None
    if cambios.orden is not None:
        imagen.orden = max(1, int(cambios.orden))

    db.commit()
    db.refresh(ficha)
    return _salida(ficha)


@admin_router.delete("/{ficha_id}/imagenes/{imagen_id}")
def borrar_imagen(
    ficha_id: int,
    imagen_id: int,
    peticion: Request,
    db: Session = Depends(get_db),
    admin: Usuario = Depends(get_current_admin),
):
    ficha = _ficha_del_sitio(db, ficha_id, admin)
    imagen = db.query(ImagenFicha).filter(
        ImagenFicha.id == imagen_id,
        ImagenFicha.ficha_id == ficha.id,
    ).first()
    if not imagen:
        raise HTTPException(status_code=404, detail="Imagen no encontrada")

    # Quitar la última foto del síntoma deja a la ficha sin poder preguntar
    # nada. En vez de dejarla publicada y muda, vuelve a borrador: es visible
    # en la pantalla y se arregla subiendo otra foto.
    quedan = [i for i in ficha.imagenes if i.rol == "sintoma" and i.id != imagen.id]
    if ficha.estado == "publicada" and imagen.rol == "sintoma" and not quedan:
        ficha.estado = "borrador"
        logger.info("Ficha devuelta a borrador: se quedó sin foto del síntoma",
                    extra={"ficha_id": ficha.id})

    archivo = _carpeta() / imagen.nombre_guardado
    AuditoriaService.registrar(db, admin, IMAGEN_BORRADA, "ficha_visual", ficha.id,
                               {"archivo": imagen.nombre_original}, peticion)
    db.delete(imagen)
    db.commit()
    # Después del commit, por la misma razón que al borrar la ficha.
    try:
        archivo.unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("No se pudo borrar la imagen en disco",
                       extra={"imagen": archivo.name, "error": str(exc)})
    db.refresh(ficha)
    return _salida(ficha)


@admin_router.post("/desde-ticket/{ticket_id}", status_code=status.HTTP_201_CREATED)
def desde_ticket(
    ticket_id: int,
    peticion: Request,
    db: Session = Depends(get_db),
    admin: Usuario = Depends(get_current_admin),
):
    """Convierte un ticket ya resuelto en una ficha, con sus fotos.

    **Las fotos del problema ya existen.** La gente las adjunta a sus tickets
    desde que hay adjuntos: la hoja con la raya, la pantalla con el error, el
    LED en rojo. Pedirle a TI que vuelva a fotografiar el mismo defecto para
    documentarlo —o que lo descargue y lo vuelva a subir a mano— es pedir dos
    veces un trabajo ya hecho, y el trabajo que se pide dos veces no se hace
    ninguna.

    Nace **en borrador**, como todo lo demás: lo que se hereda del ticket es el
    material en bruto —la descripción tal como la escribió quien lo reportó, la
    solución tal como la escribió quien lo cerró— y eso todavía no está
    redactado para contestarle a nadie. Alguien tiene que leerlo, ponerle
    título, escribir las frases con las que la gente lo dice y publicarlo.

    Pulsarlo dos veces no crea dos fichas: la segunda devuelve la que ya hay.
    """
    # TI es global: cualquier ticket. La ficha guarda la planta de origen.
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket no encontrado")

    ya = db.query(FichaVisual).filter(
        FichaVisual.ticket_origen_id == ticket.id,
    ).first()
    if ya:
        return _salida(ya)

    if not solucion_es_valida(ticket.solucion):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=("Este ticket todavía no dice cómo se resolvió. "
                    "Una ficha sin solución no le sirve a nadie."),
        )

    # Sólo imágenes: un PDF adjunto no responde a "¿se ve así?".
    fotos = [
        a for a in db.query(TicketAdjunto)
        .filter(TicketAdjunto.ticket_id == ticket.id)
        .order_by(TicketAdjunto.creado_en).all()
        if (a.tipo_mime or "").startswith("image/")
    ][:settings.VISUAL_MAX_IMAGENES]

    # El título sale del folio y no de la descripción recortada: un título
    # cortado a mitad de frase se queda así para siempre porque nadie lo
    # reescribe. Con el folio delante, quien revise el borrador sabe que tiene
    # que ponerle nombre y de dónde sacarlo.
    ficha = FichaVisual(
        sitio_id=ticket.sitio_id,
        titulo=f"Por revisar: {ticket.folio}"[:200],
        sintoma=(ticket.descripcion_original or "").strip() or ticket.folio,
        solucion=ticket.solucion.strip(),
        descartado=(ticket.descartado or "").strip() or None,
        categoria=ticket.categoria,
        estado="borrador",
        ticket_origen_id=ticket.id,
        creado_por=admin.id,
        creado_en=datetime.utcnow(),
    )
    _reindexar(ficha)
    db.add(ficha)
    db.flush()

    # **Se copia el archivo, no se enlaza al del ticket.** Si mañana alguien
    # borra ese adjunto —o el ticket entero— la ficha no puede quedarse muda:
    # es conocimiento de la planta, no una vista del ticket.
    copiadas = 0
    for orden, adjunto in enumerate(fotos, start=1):
        origen = Path(settings.ADJUNTOS_RUTA) / adjunto.nombre_guardado
        if not origen.exists():
            logger.warning("Adjunto sin archivo en disco; no se copia a la ficha",
                           extra={"adjunto_id": adjunto.id})
            continue
        destino_nombre = f"{uuid.uuid4().hex}{Path(adjunto.nombre_guardado).suffix}"
        (_carpeta() / destino_nombre).write_bytes(origen.read_bytes())
        db.add(ImagenFicha(
            ficha_id=ficha.id,
            rol="sintoma",
            orden=orden,
            pie=None,
            nombre_original=adjunto.nombre_original,
            nombre_guardado=destino_nombre,
            tipo_mime=adjunto.tipo_mime,
            tamano_bytes=adjunto.tamano_bytes,
            subido_por=admin.id,
            creado_en=datetime.utcnow(),
        ))
        copiadas += 1

    db.commit()
    db.refresh(ficha)

    AuditoriaService.registrar(db, admin, FICHA_DESDE_TICKET, "ficha_visual", ficha.id,
                               {"ticket": ticket.folio, "fotos": copiadas}, peticion)
    logger.info("Ficha visual creada desde un ticket",
                extra={"ficha_id": ficha.id, "ticket_id": ticket.id, "fotos": copiadas})
    return _salida(ficha)


@admin_router.post("/probar")
def probar(
    peticion: ProbarRequest,
    db: Session = Depends(get_db),
    admin: Usuario = Depends(get_current_admin),
):
    """Qué haría el portal con esa frase, sin que a nadie se le enseñe nada.

    **Es la pantalla que hace mantenible todo esto.** El disparador se puede
    equivocar de dos maneras y ninguna se reporta sola: enseñando fotos a quien
    preguntó por la red —que molesta y nadie avisa— y no enseñándolas a quien
    sí tenía el defecto —que no se nota nunca—. Aquí se teclea la frase y se ve
    la decisión con su motivo.

    No cuenta como "mostrada": probar veinte veces no debe ensuciar la métrica
    que sirve para saber si una ficha está bien escrita.
    """
    salida = VisualService.reconocer(
        db, peticion.texto, admin.sitio_id,
        categoria=peticion.categoria, registrar=False,
    )
    salida["umbral"] = settings.VISUAL_UMBRAL
    return salida

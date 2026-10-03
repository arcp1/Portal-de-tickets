"""Administración de temas: pasos de checklist, base de conocimiento y
problemas recurrentes detectados.

Todo aquí es solo para admin.
"""

from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.orm import Session, defer, selectinload

from app.api.deps import get_current_admin
from app.core.db import get_db
from app.core.logging import logger
from app.api.imagenes import borrar_archivos
from app.schemas.imagenes import breves
from app.models import BaseConocimiento, Checklist, SugerenciaKB, TemaSugerido, Ticket, Usuario
from app.schemas.temas import (
    EntradaKBCreate,
    EntradaKBResponse,
    EntradaKBUpdate,
    PasoCreate,
    PasoResponse,
    PasoUpdate,
    PromoverTemaRequest,
    TemaSugeridoResponse,
)
from app.services.ollama_client import CATEGORIAS_VALIDAS, normalizar_categoria, ollama
from app.services.temas_service import TemasService

router = APIRouter(prefix="/admin", tags=["Administración de temas"])


def _validar_categoria(categoria: str):
    if categoria not in CATEGORIAS_VALIDAS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Categoría inválida. Debe ser una de: " + ", ".join(CATEGORIAS_VALIDAS),
        )


# ======================================================================
# Pasos de checklist
# ======================================================================

@router.get("/pasos", response_model=List[PasoResponse])
def listar_pasos(
    categoria: Optional[str] = None,
    incluir_inactivos: bool = Query(False),
    db: Session = Depends(get_db),
    admin: Usuario = Depends(get_current_admin),
):
    consulta = db.query(Checklist).options(selectinload(Checklist.imagenes))
    if categoria:
        # Exacta: `%` como categoría no puede desactivar el filtro.
        consulta = consulta.filter(
            Checklist.categoria == (normalizar_categoria(categoria) or ""))
    if not incluir_inactivos:
        consulta = consulta.filter(Checklist.activo.is_(True))
    return consulta.order_by(Checklist.categoria, Checklist.orden).all()


@router.post("/pasos", response_model=PasoResponse, status_code=status.HTTP_201_CREATED)
def crear_paso(
    paso_in: PasoCreate,
    db: Session = Depends(get_db),
    admin: Usuario = Depends(get_current_admin),
):
    _validar_categoria(paso_in.categoria)

    if paso_in.orden is None:
        ultimo = (
            db.query(func.max(Checklist.orden))
            .filter(Checklist.categoria == paso_in.categoria)
            .scalar()
        )
        orden = (ultimo or 0) + 1
    else:
        orden = paso_in.orden

    paso = Checklist(
        categoria=paso_in.categoria,
        orden=orden,
        # Los pasos creados desde el portal guardan el texto directo. La llave
        # se conserva por compatibilidad con los sembrados, que sí traducen.
        pregunta_key=f"custom.{paso_in.categoria}.{orden}",
        pregunta_texto=paso_in.pregunta_texto,
        accion_si_no=paso_in.accion_si_no,
        resuelve=paso_in.resuelve,
        activo=True,
        creado_en=datetime.utcnow(),
    )
    db.add(paso)
    db.commit()
    db.refresh(paso)
    logger.info("Paso de checklist creado", extra={"paso_id": paso.id, "admin": admin.id})
    return paso


@router.patch("/pasos/{paso_id}", response_model=PasoResponse)
def actualizar_paso(
    paso_id: int,
    cambios: PasoUpdate,
    db: Session = Depends(get_db),
    admin: Usuario = Depends(get_current_admin),
):
    paso = db.query(Checklist).filter(Checklist.id == paso_id).first()
    if not paso:
        raise HTTPException(status_code=404, detail="Paso no encontrado")

    if cambios.categoria is not None:
        _validar_categoria(cambios.categoria)
        paso.categoria = cambios.categoria
    for campo in ("pregunta_texto", "accion_si_no", "resuelve", "orden", "activo"):
        valor = getattr(cambios, campo)
        if valor is not None:
            setattr(paso, campo, valor)

    db.commit()
    db.refresh(paso)
    return paso


@router.delete("/pasos/{paso_id}", status_code=status.HTTP_204_NO_CONTENT)
def borrar_paso(
    paso_id: int,
    db: Session = Depends(get_db),
    admin: Usuario = Depends(get_current_admin),
):
    """Baja lógica.

    No se borra la fila: `veces_resolvio` es historial, y perderlo dejaría las
    métricas mintiendo sobre cuánto absorbió el checklist.
    """
    paso = db.query(Checklist).filter(Checklist.id == paso_id).first()
    if not paso:
        raise HTTPException(status_code=404, detail="Paso no encontrado")
    paso.activo = False
    db.commit()
    return None


# ======================================================================
# Base de conocimiento
# ======================================================================

def _con_tasa(entrada: BaseConocimiento, tiene_embedding: Optional[bool] = None) -> dict:
    sugerida = entrada.veces_sugerida or 0
    if tiene_embedding is None:
        tiene_embedding = entrada.embedding is not None
    return {
        "id": entrada.id,
        "titulo": entrada.titulo,
        "contenido": entrada.contenido,
        "categoria": entrada.categoria,
        "tags": entrada.tags,
        "veces_sugerida": sugerida,
        "veces_util": entrada.veces_util or 0,
        "ticket_origen_id": entrada.ticket_origen_id,
        "tasa_utilidad": round(100.0 * (entrada.veces_util or 0) / sugerida, 1) if sugerida else None,
        "tiene_embedding": tiene_embedding,
        "imagenes": breves(entrada.imagenes),
        "imagenes_ticket": breves(entrada.imagenes_de_ticket),
    }


@router.get("/kb", response_model=List[EntradaKBResponse])
def listar_kb(
    categoria: Optional[str] = None,
    db: Session = Depends(get_db),
    admin: Usuario = Depends(get_current_admin),
):
    # Sin traer los vectores: la lista solo dice si la entrada tiene uno, y
    # cada vector son 768 números que viajaban por cada fila sin usarse.
    consulta = (db.query(BaseConocimiento, BaseConocimiento.embedding.isnot(None))
                .options(defer(BaseConocimiento.embedding),
                         selectinload(BaseConocimiento.imagenes),
                         selectinload(BaseConocimiento.ticket_origen)
                         .selectinload(Ticket.imagenes_solucion)))
    if categoria:
        consulta = consulta.filter(
            BaseConocimiento.categoria == (normalizar_categoria(categoria) or ""))
    return [_con_tasa(e, bool(tiene))
            for e, tiene in consulta.order_by(BaseConocimiento.creado_en.desc()).all()]


@router.post("/kb", response_model=EntradaKBResponse, status_code=status.HTTP_201_CREATED)
def crear_entrada_kb(
    entrada_in: EntradaKBCreate,
    db: Session = Depends(get_db),
    admin: Usuario = Depends(get_current_admin),
):
    """Alta manual de conocimiento, sin esperar a que ocurra un ticket.

    Si Ollama no está, la entrada se guarda igual pero sin vector: no aparecerá
    en las búsquedas hasta que `reindexar_kb.py` la procese.
    """
    _validar_categoria(entrada_in.categoria)

    texto = f"{entrada_in.categoria}\n{entrada_in.titulo}\n{entrada_in.contenido}"
    embedding = ollama.generar_embedding(texto, tarea="documento")

    entrada = BaseConocimiento(
        sitio_id=admin.sitio_id,
        titulo=entrada_in.titulo,
        contenido=entrada_in.contenido,
        categoria=entrada_in.categoria,
        tags=entrada_in.tags,
        embedding=embedding,
        creado_en=datetime.utcnow(),
    )
    db.add(entrada)
    db.commit()
    db.refresh(entrada)
    return _con_tasa(entrada)


@router.patch("/kb/{entrada_id}", response_model=EntradaKBResponse)
def actualizar_entrada_kb(
    entrada_id: int,
    cambios: EntradaKBUpdate,
    db: Session = Depends(get_db),
    admin: Usuario = Depends(get_current_admin),
):
    entrada = db.query(BaseConocimiento).filter(
        BaseConocimiento.id == entrada_id,
    ).first()
    if not entrada:
        raise HTTPException(status_code=404, detail="Entrada no encontrada")

    if cambios.categoria is not None:
        _validar_categoria(cambios.categoria)

    cambio_texto = False
    for campo in ("titulo", "contenido", "categoria", "tags"):
        valor = getattr(cambios, campo)
        if valor is not None:
            setattr(entrada, campo, valor)
            if campo in ("titulo", "contenido", "categoria"):
                cambio_texto = True

    # Si cambió el texto, el vector viejo ya no lo representa.
    if cambio_texto:
        texto = f"{entrada.categoria}\n{entrada.titulo}\n{entrada.contenido}"
        nuevo = ollama.generar_embedding(texto, tarea="documento")
        if nuevo is not None:
            entrada.embedding = nuevo
        else:
            logger.warning(
                "Entrada editada sin poder regenerar su vector; queda desactualizado",
                extra={"entrada_id": entrada.id},
            )

    db.commit()
    db.refresh(entrada)
    return _con_tasa(entrada)


@router.delete("/kb/{entrada_id}", status_code=status.HTTP_204_NO_CONTENT)
def borrar_entrada_kb(
    entrada_id: int,
    db: Session = Depends(get_db),
    admin: Usuario = Depends(get_current_admin),
):
    entrada = db.query(BaseConocimiento).filter(
        BaseConocimiento.id == entrada_id,
    ).first()
    if not entrada:
        raise HTTPException(status_code=404, detail="Entrada no encontrada")

    # **Una entrada que ya se sugirió no se podía borrar.** Cada vez que se
    # le enseña a alguien queda una fila en `sugerencias_kb` que apunta a
    # ella, y la base rechazaba el borrado: TI veía "choca con datos ya
    # registrados" justo con las entradas que más se usan. Ese historial es de
    # la entrada —cuántas veces se mostró y si sirvió— y se va con ella.
    db.query(SugerenciaKB).filter(SugerenciaKB.kb_id == entrada.id).delete(
        synchronize_session=False)

    # Si salió de un ticket, ese ticket vuelve a poder indexarse: con la marca
    # puesta, el botón "Indexar en la base de conocimiento" no volvía a salir.
    if entrada.ticket_origen_id:
        db.query(Ticket).filter(Ticket.id == entrada.ticket_origen_id).update(
            {Ticket.indexado_kb: False}, synchronize_session=False)

    # Sus imágenes se van con ella: las filas las borra la base en cascada y
    # los archivos se retiran después del commit, para no dejar en pantalla
    # una imagen que ya no abre si el commit fallara.
    archivos = [i.nombre_guardado for i in entrada.imagenes]

    db.delete(entrada)
    db.commit()
    borrar_archivos(archivos)
    return None


# ======================================================================
# Temas recurrentes detectados
# ======================================================================

@router.get("/temas-sugeridos", response_model=List[TemaSugeridoResponse])
def listar_temas_sugeridos(
    estado: Optional[str] = None,
    db: Session = Depends(get_db),
    admin: Usuario = Depends(get_current_admin),
):
    """Problemas que la gente reporta y el portal no tiene contemplados."""
    consulta = db.query(TemaSugerido)
    if estado:
        consulta = consulta.filter(TemaSugerido.estado == estado)
    else:
        consulta = consulta.filter(TemaSugerido.estado.in_(["pendiente", "listo"]))

    temas = consulta.order_by(TemaSugerido.ocurrencias.desc()).all()

    salida = []
    for tema in temas:
        datos = {
            "id": tema.id,
            "titulo": tema.titulo,
            "descripcion_ejemplo": tema.descripcion_ejemplo,
            "categoria_sugerida": tema.categoria_sugerida,
            "ocurrencias": tema.ocurrencias,
            "estado": tema.estado,
            "primera_vez": tema.primera_vez.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z") if tema.primera_vez else None,
            "ultima_vez": tema.ultima_vez.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z") if tema.ultima_vez else None,
            # Solo para los que ya alcanzaron el umbral: buscar soluciones
            # previas cuesta varias llamadas a Ollama.
            "soluciones_previas": (
                TemasService.soluciones_propuestas(db, tema) if tema.estado == "listo" else []
            ),
        }
        salida.append(datos)
    return salida


@router.post("/temas-sugeridos/{tema_id}/promover", status_code=status.HTTP_201_CREATED)
def promover_tema(
    tema_id: int,
    peticion: PromoverTemaRequest,
    db: Session = Depends(get_db),
    admin: Usuario = Depends(get_current_admin),
):
    """Convierte un problema recurrente en tema con su checklist."""
    tema = db.query(TemaSugerido).filter(
        TemaSugerido.id == tema_id,
    ).first()
    if not tema:
        raise HTTPException(status_code=404, detail="Tema no encontrado")

    _validar_categoria(peticion.categoria)

    ultimo = (
        db.query(func.max(Checklist.orden))
        .filter(Checklist.categoria == peticion.categoria)
        .scalar()
    ) or 0

    creados = []
    for i, paso_in in enumerate(peticion.pasos, start=1):
        paso = Checklist(
            categoria=peticion.categoria,
            orden=ultimo + i,
            pregunta_key=f"custom.{peticion.categoria}.{ultimo + i}",
            pregunta_texto=paso_in.pregunta_texto,
            accion_si_no=paso_in.accion_si_no,
            resuelve=paso_in.resuelve,
            activo=True,
            creado_en=datetime.utcnow(),
        )
        db.add(paso)
        creados.append(paso)

    tema.estado = "promovido"
    tema.categoria_sugerida = peticion.categoria
    db.commit()

    logger.info(
        "Tema recurrente promovido a checklist",
        extra={"tema_id": tema.id, "pasos": len(creados), "admin": admin.id},
    )
    return {"ok": True, "pasos_creados": len(creados), "categoria": peticion.categoria}


@router.post("/temas-sugeridos/{tema_id}/descartar", status_code=status.HTTP_200_OK)
def descartar_tema(
    tema_id: int,
    db: Session = Depends(get_db),
    admin: Usuario = Depends(get_current_admin),
):
    tema = db.query(TemaSugerido).filter(
        TemaSugerido.id == tema_id,
    ).first()
    if not tema:
        raise HTTPException(status_code=404, detail="Tema no encontrado")
    tema.estado = "descartado"
    db.commit()
    return {"ok": True}

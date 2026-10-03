"""Importación masiva de personal.

Con 300+ empleados, dar de alta uno por uno no es viable. RH ya tiene la lista
en Excel; esto la convierte en cuentas.

El flujo es de dos pasos a propósito: primero **analizar** (dice qué pasaría sin
escribir nada) y luego **importar**. Nadie debería cargar 300 filas a ciegas.
"""

import json
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin
from app.core import plantas
from app.core.db import get_db
from app.models import Usuario
from app.services.auditoria_service import AuditoriaService
from app.services.importacion_service import ImportacionService

router = APIRouter(prefix="/admin/importacion", tags=["Importación masiva"])

IMPORTACION_REALIZADA = "usuarios.importacion"

MAX_MB = 5

# Qué dato se le va a pedir a la persona para que se active sola.
DATOS_VERIFICACION = ("numero_epp", "fecha_nacimiento", "fecha_ingreso")


def _mapeo(crudo: str | None) -> dict | None:
    """El mapeo de columnas que corrigió el admin, si mandó alguno."""
    if not crudo or not crudo.strip():
        return None
    try:
        datos = json.loads(crudo)
    except (ValueError, TypeError):
        raise HTTPException(status_code=422, detail="El mapeo de columnas no es válido.")
    if not isinstance(datos, dict):
        raise HTTPException(status_code=422, detail="El mapeo de columnas no es válido.")
    return datos


async def _leer(archivo: UploadFile) -> bytes:
    limite = MAX_MB * 1024 * 1024
    contenido = await archivo.read(limite + 1)
    if len(contenido) > limite:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"El archivo supera {MAX_MB} MB.",
        )
    if not contenido:
        raise HTTPException(status_code=422, detail="El archivo está vacío.")
    return contenido


@router.get("/plantilla")
def plantilla(admin: Usuario = Depends(get_current_admin)):
    """CSV de ejemplo con los encabezados que el importador reconoce."""
    return Response(
        content=ImportacionService.plantilla_csv(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="plantilla-personal.csv"'},
    )


@router.post("/analizar")
async def analizar(
    archivo: UploadFile = File(...),
    mapeo: str = Form(None),
    sitio_id: Optional[int] = Form(None),
    db: Session = Depends(get_db),
    admin: Usuario = Depends(get_current_admin),
):
    """Vista previa: qué se importaría y qué filas tienen problema.

    No escribe nada. Se corre siempre antes de importar.

    Si el archivo trae encabezados que no se reconocen, la respuesta viene con
    `necesita_mapeo` y una `sugerencia` —propuesta por el modelo si está
    disponible— para que el admin diga qué columna es cuál y vuelva a analizar.
    """
    contenido = await _leer(archivo)
    sitio_id = plantas.planta_para(db, admin, sitio_id)
    return ImportacionService.analizar(db, contenido, sitio_id, _mapeo(mapeo))


@router.post("/importar")
async def importar(
    archivo: UploadFile = File(...),
    modo_activacion: str = Form("codigo"),
    dato_verificacion: str = Form("fecha_nacimiento"),
    dias_ventana: int = Form(0),
    mapeo: str = Form(None),
    sitio_id: Optional[int] = Form(None),
    db: Session = Depends(get_db),
    admin: Usuario = Depends(get_current_admin),
    peticion: Request = None,
):
    """Crea las cuentas. O entran todas las filas válidas, o ninguna.

    `modo_activacion`:
      - **codigo**: uno por persona, para imprimir y repartir. Más seguro;
        razonable para altas de pocas personas.
      - **verificacion**: la persona activa con su número de empleado y su
        fecha de nacimiento. Es lo que hace viable una carga inicial de 300, y
        se apoya en un dato que la gente sí recuerda.
    """
    if modo_activacion not in ("codigo", "verificacion"):
        raise HTTPException(status_code=422, detail="Modo de activación inválido.")
    if dato_verificacion not in DATOS_VERIFICACION:
        raise HTTPException(status_code=422, detail="Dato de verificación inválido.")

    contenido = await _leer(archivo)
    # La planta en la que entran las personas importadas: la que se elija en
    # la pantalla, o la única que haya.
    sitio_id = plantas.planta_para(db, admin, sitio_id)
    resultado = ImportacionService.importar(
        db, contenido, sitio_id,
        modo_activacion=modo_activacion,
        dato_verificacion=dato_verificacion,
        dias_ventana=dias_ventana or None,
        mapeo=_mapeo(mapeo),
    )

    if resultado.get("importadas"):
        AuditoriaService.registrar(
            db, admin, IMPORTACION_REALIZADA, "usuario", None,
            {"importadas": resultado["importadas"], "modo": modo_activacion,
             "con_error": resultado.get("con_error", 0)},
            peticion,
        )
    return resultado


@router.post("/codigos-csv")
def codigos_csv(
    filas: list[dict],
    area: str = None,
    admin: Usuario = Depends(get_current_admin),
):
    """Convierte el resultado de una importación en un CSV imprimible.

    Se genera aquí y no se guarda: los códigos no viven en el servidor más allá
    de su hash, así que este archivo es la única copia. Quien lo descargue es
    responsable de resguardarlo hasta repartirlo.

    Con `area` sale solo la gente de esa área: así el reparto se delega en cada
    supervisor y TI no anda entregando 300 papelitos.
    """
    nombre = "codigos-activacion.csv"
    if area:
        limpio = "".join(c if c.isalnum() else "-" for c in area.lower())[:40]
        nombre = f"codigos-{limpio}.csv"
    return Response(
        content=ImportacionService.csv_de_codigos(filas, area),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{nombre}"'},
    )

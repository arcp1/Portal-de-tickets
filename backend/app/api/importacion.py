"""Importación masiva de personal.

Con 300+ empleados, dar de alta uno por uno no es viable. RH ya tiene la lista
en Excel; esto la convierte en cuentas.

El flujo es de dos pasos a propósito: primero **analizar** (dice qué pasaría sin
escribir nada) y luego **importar**. Nadie debería cargar 300 filas a ciegas.
"""

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin
from app.core.db import get_db
from app.models import Usuario
from app.services.auditoria_service import AuditoriaService
from app.services.importacion_service import ImportacionService

router = APIRouter(prefix="/admin/importacion", tags=["Importación masiva"])

IMPORTACION_REALIZADA = "usuarios.importacion"

MAX_MB = 5


async def _leer(archivo: UploadFile) -> bytes:
    limite = MAX_MB * 1024 * 1024
    contenido = await archivo.read(limite + 1)
    if len(contenido) > limite:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
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
    db: Session = Depends(get_db),
    admin: Usuario = Depends(get_current_admin),
):
    """Vista previa: qué se importaría y qué filas tienen problema.

    No escribe nada. Se corre siempre antes de importar.
    """
    contenido = await _leer(archivo)
    return ImportacionService.analizar(db, contenido, admin.sitio_id)


@router.post("/importar")
async def importar(
    archivo: UploadFile = File(...),
    modo_activacion: str = Form("codigo"),
    dias_ventana: int = Form(0),
    db: Session = Depends(get_db),
    admin: Usuario = Depends(get_current_admin),
    peticion: Request = None,
):
    """Crea las cuentas. O entran todas las filas válidas, o ninguna.

    `modo_activacion`:
      - **codigo**: uno por persona, para imprimir y repartir. Más seguro;
        razonable para altas de pocas personas.
      - **verificacion**: la persona activa con su número de empleado y su
        fecha de ingreso. Es lo que hace viable una carga inicial de 300.
    """
    if modo_activacion not in ("codigo", "verificacion"):
        raise HTTPException(status_code=422, detail="Modo de activación inválido.")

    contenido = await _leer(archivo)
    resultado = ImportacionService.importar(
        db, contenido, admin.sitio_id,
        modo_activacion=modo_activacion,
        dias_ventana=dias_ventana or None,
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
    admin: Usuario = Depends(get_current_admin),
):
    """Convierte el resultado de una importación en un CSV imprimible.

    Se genera aquí y no se guarda: los códigos no viven en el servidor más allá
    de su hash, así que este archivo es la única copia. Quien lo descargue es
    responsable de resguardarlo hasta repartirlo.
    """
    return Response(
        content=ImportacionService.csv_de_codigos(filas),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="codigos-activacion.csv"'},
    )

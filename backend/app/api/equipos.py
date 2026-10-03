import re

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session, joinedload
from typing import List, Optional
from datetime import datetime, timezone

from app.core import plantas
from app.core.db import get_db
from app.models import ESTADOS_TERMINADOS, Equipo, Usuario, Ticket
from app.schemas.equipo import EquipoCreate, EquipoUpdate, EquipoResponse
from app.api.deps import get_current_user, get_current_admin

router = APIRouter(prefix="/equipos", tags=["Equipos"])

# Los valores que el modelo admite de verdad. Los guarda como texto libre y
# nadie los comprobaba: un `estado` inventado no rompe nada visiblemente, pero
# el equipo deja de aparecer donde se le busca —el formulario de resguardos
# solo lista los "disponible"— y la insignia del inventario se queda en blanco.
# Un equipo que desaparece de la lista sin haberse dado de baja es de lo peor
# que puede pasarle a un inventario.
TIPOS_VALIDOS = ("activo", "pasivo", "consumible")
ESTADOS_VALIDOS = ("disponible", "asignado", "mantenimiento", "baja")


def _serie_normalizada(valor):
    """La serie en blanco es "no se registró", y eso en la base es NULL.

    Un formulario web manda la cadena vacía, no `None`. Guardarla tal cual
    llenaba el inventario de equipos que comparten la serie "" y ademas choca
    con el índice único, que a propósito solo mira las series de verdad.
    """
    if valor is None:
        return None
    limpio = valor.strip()
    return limpio or None


def _serie_libre(db: Session, sitio_id: int, serie, equipo_id=None):
    """Que no haya ya otro activo con esa serie en la misma planta.

    La restricción vive en la base (índice `ix_equipos_serie_unica_por_sitio`),
    que es donde tiene que estar para que nadie la esquive. Esto se comprueba
    antes solo para poder responder con un mensaje que se entienda y decir con
    cuál choca, en vez de soltar el error de integridad como un 500.
    """
    if not serie:
        return
    consulta = db.query(Equipo).filter(
        Equipo.sitio_id == sitio_id,
        Equipo.numero_serie == serie,
    )
    if equipo_id is not None:
        consulta = consulta.filter(Equipo.id != equipo_id)
    choque = consulta.first()
    if choque:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Ya hay un equipo registrado con el número de serie {serie}: "
                f"{choque.marca} {choque.modelo}. El número de serie identifica "
                "una sola pieza; si es otro equipo, revise la etiqueta."
            ),
        )


def _validar(db: Session, sitio_id: int, tipo=None, estado=None, asignado_a=None):
    """Comprobaciones comunes al alta y a la edición de un equipo."""
    if tipo is not None and tipo not in TIPOS_VALIDOS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Tipo inválido. Se acepta: " + ", ".join(TIPOS_VALIDOS),
        )
    if estado is not None and estado not in ESTADOS_VALIDOS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Estado inválido. Se acepta: " + ", ".join(ESTADOS_VALIDOS),
        )
    # Sin esto el id viajaba tal cual a la clave foránea y la violación salía
    # como un 500. Además se comprueba la planta: el resguardo de un equipo lo
    # firma alguien de su propio sitio.
    if asignado_a is not None:
        persona = db.query(Usuario).filter(Usuario.id == asignado_a).first()
        # Alguien que trabaja en esa planta, o de TI (global).
        if not persona or persona.eliminado_en or not plantas.alcanza(persona, sitio_id):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="La persona asignada no existe o pertenece a otro sitio.",
            )

def _como_lo_ve(equipo: Equipo, usuario: Usuario) -> EquipoResponse:
    """El equipo tal como puede verlo quien pregunta.

    **El inventario lo ve toda la planta, el padrón no.** Cada equipo asignado
    traía a su persona entera —correo, número de empleado, área—, así que el
    listado que cualquiera abre desde el menú era también el directorio de la
    planta. A quien no es de TI se le dice que el equipo está ocupado (el
    `estado` sigue ahí), no quién lo tiene; salvo que lo tenga él.
    """
    respuesta = EquipoResponse.model_validate(equipo)
    if usuario.rol != "admin" and equipo.asignado_a != usuario.id:
        respuesta.asignado_a = None
        respuesta.asignado_usuario = None
        respuesta.fecha_asignacion = None
    return respuesta


@router.get("", response_model=List[EquipoResponse])
def list_equipos(
    tipo: Optional[str] = None,
    estado: Optional[str] = None,
    sitio_id: Optional[int] = Query(None, ge=1, le=2**31 - 1),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    # La persona asignada —y su planta, que `UserResponse` enseña— en la misma
    # consulta. Sin esto eran dos consultas más por equipo asignado.
    #
    # Cada quien ve los equipos de sus plantas; TI, los de todas, y puede
    # pedir los de una. Pedir una planta que no es suya no amplía nada: el
    # filtro de plantas va primero.
    query = plantas.filtrar(
        db.query(Equipo).options(joinedload(Equipo.sitio),
                                 joinedload(Equipo.asignado_usuario).joinedload(Usuario.sitio)),
        Equipo.sitio_id, current_user)
    if sitio_id is not None:
        query = query.filter(Equipo.sitio_id == sitio_id)
    if tipo:
        query = query.filter(Equipo.tipo == tipo)
    if estado:
        query = query.filter(Equipo.estado == estado)
    return [_como_lo_ve(e, current_user) for e in query.order_by(Equipo.id).all()]

@router.post("", response_model=EquipoResponse, status_code=status.HTTP_201_CREATED)
def create_equipo(
    equipo_in: EquipoCreate,
    db: Session = Depends(get_db),
    admin: Usuario = Depends(get_current_admin)
):
    # TI es global: el equipo va a la planta que se indique.
    sitio_id = plantas.planta_para(db, admin, equipo_in.sitio_id)
    _validar(db, sitio_id, equipo_in.tipo, equipo_in.estado, equipo_in.asignado_a)
    serie = _serie_normalizada(equipo_in.numero_serie)
    _serie_libre(db, sitio_id, serie)

    equipo = Equipo(
        sitio_id=sitio_id,
        tipo=equipo_in.tipo,
        categoria=equipo_in.categoria,
        marca=equipo_in.marca,
        modelo=equipo_in.modelo,
        numero_serie=serie,
        ubicacion=equipo_in.ubicacion,
        estado=equipo_in.estado,
        asignado_a=equipo_in.asignado_a,
        fecha_asignacion=datetime.utcnow() if equipo_in.asignado_a else None,
        notas=equipo_in.notas
    )
    db.add(equipo)
    db.commit()
    db.refresh(equipo)
    return equipo

@router.get("/{equipo_id}", response_model=EquipoResponse)
def get_equipo(
    equipo_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    equipo = db.query(Equipo).filter(Equipo.id == equipo_id).first()
    if not equipo or not plantas.alcanza(current_user, equipo.sitio_id):
        # Mismo 404 para "no existe" y "es de otra planta": no hay por que
        # confirmarle a nadie que un equipo ajeno existe.
        raise HTTPException(status_code=404, detail="Equipo no encontrado.")
    return _como_lo_ve(equipo, current_user)

@router.patch("/{equipo_id}", response_model=EquipoResponse)
def update_equipo(
    equipo_id: int,
    equipo_in: EquipoUpdate,
    db: Session = Depends(get_db),
    admin: Usuario = Depends(get_current_admin)
):
    equipo = db.query(Equipo).filter(Equipo.id == equipo_id).first()
    if not equipo or not plantas.alcanza(admin, equipo.sitio_id):
        raise HTTPException(status_code=404, detail="Equipo no encontrado.")

    # Puede cambiar de planta: un equipo que se lleva a otra nave. Lo demás se
    # valida contra la planta a la que va, no contra la que deja.
    destino = (plantas.planta_para(db, admin, equipo_in.sitio_id)
               if equipo_in.sitio_id is not None else equipo.sitio_id)
    asignado = equipo_in.asignado_a if "asignado_a" in equipo_in.model_fields_set else equipo.asignado_a
    _validar(db, destino, equipo_in.tipo, equipo_in.estado, asignado)

    cambios = equipo_in.model_dump(exclude_unset=True)
    if "numero_serie" in cambios:
        cambios["numero_serie"] = _serie_normalizada(cambios["numero_serie"])
    if "numero_serie" in cambios or destino != equipo.sitio_id:
        _serie_libre(db, destino, cambios.get("numero_serie", equipo.numero_serie),
                     equipo_id=equipo.id)
    cambios["sitio_id"] = destino

    for field, value in cambios.items():
        if field == "asignado_a" and value != equipo.asignado_a:
            equipo.fecha_asignacion = datetime.utcnow() if value else None
        setattr(equipo, field, value)

    db.commit()
    db.refresh(equipo)
    return equipo


@router.get("/{equipo_id}/historial")
def historial_del_equipo(
    equipo_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Todos los tickets de este equipo.

    Es lo que revela cuál impresora conviene cambiar en vez de seguir
    reparándola: si un solo equipo concentra veinte incidencias, el problema
    no es de soporte, es de compras.
    """
    equipo = db.query(Equipo).filter(Equipo.id == equipo_id).first()
    if not equipo or not plantas.alcanza(current_user, equipo.sitio_id):
        raise HTTPException(status_code=404, detail="Equipo no encontrado")

    consulta = db.query(Ticket).filter(Ticket.equipo_id == equipo_id)
    # **TI ve el historial entero; los demás, solo sus tickets.** Antes
    # cualquiera recibía folio, estado y solución de todos los tickets de ese
    # equipo, fueran de quien fueran: con recorrer ids se leía lo que le había
    # pasado a cada compañero. Es la misma regla que el listado de tickets.
    if current_user.rol != "admin":
        consulta = consulta.filter(Ticket.usuario_id == current_user.id)
    tickets = consulta.order_by(Ticket.creado_en.desc()).all()

    resueltos = [t for t in tickets if t.tiempo_resolucion is not None]
    return {
        "equipo_id": equipo_id,
        "total_tickets": len(tickets),
        "abiertos": sum(1 for t in tickets if t.estado not in ESTADOS_TERMINADOS),
        "tiempo_promedio_min": (
            round(sum(t.tiempo_resolucion for t in resueltos) / len(resueltos), 1)
            if resueltos else None
        ),
        "tickets": [
            {
                "id": t.id,
                "folio": t.folio,
                "categoria": t.categoria,
                "estado": t.estado,
                "prioridad": t.prioridad,
                "creado_en": t.creado_en.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z") if t.creado_en else None,
                "solucion": t.solucion,
            }
            for t in tickets
        ],
    }


@router.get("/{equipo_id}/etiqueta.png")
def etiqueta_qr(
    equipo_id: int,
    db: Session = Depends(get_db),
    admin: Usuario = Depends(get_current_admin),
):
    """La etiqueta para imprimir y pegar: QR a «Nuevo ticket» con el equipo ya puesto.

    Ver `services/etiqueta_service.py` para qué lleva el QR y por qué ese tamaño.
    """
    from app.services.etiqueta_service import enlace_de, generar_png

    equipo = (db.query(Equipo).options(joinedload(Equipo.sitio))
              .filter(Equipo.id == equipo_id).first() if 0 < equipo_id < 2**31 else None)
    if not equipo or not plantas.alcanza(admin, equipo.sitio_id):
        raise HTTPException(status_code=404, detail="Equipo no encontrado")
    nombre = re.sub(r"[^A-Za-z0-9_-]+", "-", f"etiqueta-{equipo.id}-{equipo.modelo or ''}").strip("-")
    return Response(
        content=generar_png(equipo),
        media_type="image/png",
        headers={
            "Content-Disposition": f'inline; filename="{nombre}.png"',
            # El enlace que lleva, para que la pantalla lo enseñe y se pueda probar.
            "X-Enlace-QR": enlace_de(equipo),
            "Cache-Control": "no-store",
        },
    )

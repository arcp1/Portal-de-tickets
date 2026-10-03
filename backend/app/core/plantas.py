"""Quién alcanza qué planta. La única puerta para esa pregunta.

**Las reglas** (2026-10-02, multi-planta):

  * **TI es global.** Una cuenta con rol ``admin`` no tiene planta: ve y
    administra los tickets, equipos y personas de todas. Su ``sitio_id`` está
    vacío y ``plantas_ids`` devuelve ``None``, que aquí significa "sin límite".
  * **Una persona de planta** trabaja en una o varias (``usuario_sitios``) y
    solo ve y elige equipos y tickets de esas. Su ``sitio_id`` es la principal,
    la que se le propone al levantar un ticket.

**Por qué un módulo y no comparaciones sueltas.** Antes cada ruta hacía su
``obj.sitio_id != admin.sitio_id`` y eran 87; con dos reglas distintas según
el rol, cada copia era una oportunidad de equivocarse en una sola de ellas y
abrir —o cerrar— una planta entera sin que nada lo dijera. Aquí se decide una
vez y las rutas preguntan.

Lo que no alcanza se responde **404**, nunca 403: un 403 confirma que el id
existe en otra planta (ver la memoria "el rol de admin no cruza de planta",
que con TI global pasa a aplicar a las personas de planta).
"""

from typing import Iterable, Optional, Set

from fastapi import HTTPException
from sqlalchemy import true
from sqlalchemy.orm import Session

from app.models import Sitio, Usuario


def ids(usuario: Usuario) -> Optional[Set[int]]:
    """Las plantas que alcanza, o ``None`` si alcanza todas."""
    return usuario.plantas_ids


def alcanza(usuario: Usuario, sitio_id: Optional[int]) -> bool:
    """Si la persona puede ver algo de esa planta.

    Lo que no tiene planta (``None``: conocimiento general, cosas de TI) lo
    alcanza todo el mundo que llegue hasta aquí; los permisos por rol se
    revisan aparte.
    """
    if sitio_id is None:
        return True
    plantas = ids(usuario)
    return plantas is None or sitio_id in plantas


def exigir(usuario: Usuario, sitio_id: Optional[int], que: str = "Recurso") -> None:
    """404 si no la alcanza. Para las rutas que reciben un id."""
    if not alcanza(usuario, sitio_id):
        raise HTTPException(status_code=404, detail=f"{que} no encontrado")


def filtrar(consulta, columna, usuario: Usuario, incluir_generales: bool = False):
    """La consulta limitada a las plantas de la persona; intacta para TI.

    ``incluir_generales`` deja pasar también las filas sin planta.
    """
    plantas = ids(usuario)
    if plantas is None:
        return consulta
    condicion = columna.in_(sorted(plantas))
    if incluir_generales:
        condicion = condicion | columna.is_(None)
    return consulta.filter(condicion)


def de_planta(columna, sitio_id: Optional[int]):
    """La condición "de esta planta", o ninguna si no se pidió una.

    Para tableros de TI —métricas, conciencia—, que ven todas las plantas
    juntas salvo que se filtren a una.
    """
    return true() if sitio_id is None else columna == sitio_id


def planta_valida(db: Session, sitio_id: Optional[int]) -> Optional[Sitio]:
    if sitio_id is None or not (0 < sitio_id < 2**31):
        return None
    sitio = db.get(Sitio, sitio_id)
    return sitio if sitio and sitio.activo else None


def planta_para(db: Session, usuario: Usuario, pedida: Optional[int]) -> int:
    """La planta de algo que esta persona da de alta: un ticket, un equipo, una regla.

    * Si pidió una, tiene que existir, estar activa y alcanzarla.
    * Si no pidió: una persona de planta usa su principal; TI, la única planta
      que haya. Con varias plantas TI tiene que decir cuál —no hay una que
      sea "la suya"—, y se le pide en vez de adivinar.
    """
    if pedida is not None:
        sitio = planta_valida(db, pedida)
        if not sitio or not alcanza(usuario, sitio.id):
            raise HTTPException(status_code=422, detail="La planta indicada no existe o no es suya.")
        return sitio.id
    if usuario.sitio_id:
        return usuario.sitio_id
    plantas = ids(usuario)
    if plantas:
        return min(plantas)
    activas = [s.id for s in db.query(Sitio.id).filter(Sitio.activo.is_(True)).all()]
    if len(activas) == 1:
        return activas[0]
    raise HTTPException(status_code=422, detail="Indique la planta.")


def asignar_plantas(db: Session, usuario: Usuario, sitio_ids: Iterable[int]) -> None:
    """Deja a la persona exactamente en esas plantas (al menos una).

    La primera de la lista queda como principal si la que tenía ya no está.
    A TI no se le asignan: su alcance es por rol.
    """
    if usuario.es_ti_global:
        usuario.plantas = []
        usuario.sitio_id = None
        return
    pedidas = list(dict.fromkeys(int(s) for s in sitio_ids))
    sitios = [planta_valida(db, s) for s in pedidas]
    if not pedidas or any(s is None for s in sitios):
        raise HTTPException(status_code=422, detail="Indique al menos una planta válida.")
    usuario.plantas = sitios
    if usuario.sitio_id not in pedidas:
        usuario.sitio_id = pedidas[0]

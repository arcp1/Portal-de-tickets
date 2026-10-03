"""El siguiente folio legible de una serie: TICK-QRO-2026-0042.

**Se parte del mayor folio de la serie, no de cuántos hay.** Antes se contaban
las filas y se sumaba uno, y eso falla de dos maneras con un índice único
encima:

  - Si alguna vez se borra un registro, el conteo baja y el siguiente folio
    repite uno que ya existe: el alta revienta con un 500.
  - El conteo no separaba por año aunque el año va en el folio, así que el
    primer ticket de enero seguía la numeración de diciembre.

Dos altas simultáneas pueden seguir calculando el mismo número —las dos ven el
mismo máximo—; eso lo resuelve quien inserta, reintentando cuando el índice
único rechaza el segundo. Ver `create_ticket`.
"""

from sqlalchemy import func
from sqlalchemy.orm import Session


def siguiente_folio(db: Session, modelo, prefijo: str) -> str:
    # Por longitud primero: como texto, "9999" va después que "10000".
    ultimo = (
        db.query(modelo.folio)
        .filter(modelo.folio.startswith(prefijo, autoescape=True))
        .order_by(func.length(modelo.folio).desc(), modelo.folio.desc())
        .first()
    )
    consecutivo = 1
    if ultimo:
        cola = ultimo[0][len(prefijo):]
        consecutivo = int(cola) + 1 if cola.isdigit() else consecutivo
    return f"{prefijo}{consecutivo:04d}"

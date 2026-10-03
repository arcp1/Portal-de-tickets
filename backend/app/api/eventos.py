"""El canal por el que el portal avisa de que algo cambió.

Server-Sent Events y no WebSocket: el tráfico va en una sola dirección —del
servidor a la pantalla— y SSE es HTTP normal. Eso significa que pasa por el
mismo nginx, el mismo TLS y la misma cabecera de autorización que el resto del
portal, sin abrir una segunda superficie que auditar. Un WebSocket habría que
protegerlo aparte.
"""

import asyncio
import logging

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.db import get_db
from app.models import Usuario
from app.services.eventos_service import difusor

logger = logging.getLogger("portal_tickets")

router = APIRouter(prefix="/eventos", tags=["eventos"])

#: Cada cuánto se manda un comentario vacío si no ha pasado nada. Sin esto, un
#: intermediario que no ve tráfico da la conexión por muerta y la corta; el
#: cliente reconecta, y el portal acaba abriendo conexiones en bucle.
LATIDO_S = 20



#: Tipos de aviso que solo le interesan —y solo puede ver— TI.
SOLO_TI = {"alertas", "iot"}

@router.get("/flujo")
async def flujo(
    usuario: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Avisos en vivo para el sitio del usuario.

    **`async def` y no `def`.** Una ruta síncrona ocupa un hilo del *pool*
    mientras dure, y ésta dura lo que el usuario tenga la pestaña abierta. Con
    el *pool* por defecto, sesenta pantallas abiertas dejarían al portal sin
    hilos para atender peticiones normales: el portal entero se colgaría por
    tener éxito.

    **Y por lo mismo hay que soltar la conexión a la base.** Una dependencia
    con `yield` no se cierra al devolver la respuesta sino al terminarla, y
    ésta no termina hasta que el usuario cierra la pestaña. `get_current_user`
    ya consultó `usuarios`, o sea que había una transacción de lectura abierta
    —y una conexión del *pool* retenida— por cada pantalla conectada, durante
    horas.

    Dos consecuencias reales, las dos vistas: con treinta pestañas abiertas el
    *pool* se agota y el portal deja de atender a todo el mundo; y mientras
    tanto ninguna migración que toque `usuarios` puede correr, porque un
    `ALTER TABLE` necesita un bloqueo exclusivo y se queda esperando detrás de
    esas lecturas —con todas las consultas nuevas encoladas detrás de él—.
    """
    cola = difusor.suscribir()
    # Se lee **antes** de cerrar: después la instancia queda desacoplada y
    # cualquier atributo que no estuviera cargado dispararía una consulta
    # contra una sesión que ya no existe.
    # `None` = TI, que recibe los de todas las plantas.
    plantas_del_usuario = usuario.plantas_ids
    es_ti = usuario.rol == "admin"
    # A partir de aquí el flujo no vuelve a tocar la base. La sesión se
    # devuelve al *pool* —con su transacción deshecha— en vez de quedarse
    # retenida mientras dure la conexión. El `close()` de `get_db` sigue
    # estando y no molesta: cerrar dos veces no hace nada.
    db.close()

    async def generar():
        try:
            # Primer byte inmediato: hasta que no llega algo, el cliente no
            # considera abierta la conexión y no puede pintar el indicador.
            yield ": conectado\n\n"
            while True:
                try:
                    sitio_id, tipo = await asyncio.wait_for(cola.get(), timeout=LATIDO_S)
                except asyncio.TimeoutError:
                    yield ": latido\n\n"
                    continue
                # El filtro por planta va aquí y no en quien publica: así un
                # evento se emite una sola vez y cada conexión decide. Las
                # alertas y los sensores son solo para TI.
                if tipo in SOLO_TI and not es_ti:
                    continue
                if (plantas_del_usuario is None or sitio_id is None
                        or sitio_id in plantas_del_usuario):
                    yield f"event: {tipo}\ndata: 1\n\n"
        except asyncio.CancelledError:
            # El cliente cerró. Es lo normal, no un fallo.
            raise
        finally:
            difusor.cancelar(cola)

    return StreamingResponse(
        generar(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            # nginx almacena las respuestas del backend antes de reenviarlas,
            # y con eso un flujo continuo no llega nunca. Esta cabecera lo
            # desactiva **solo para esta respuesta**: tocar `proxy_buffering`
            # en la configuración lo apagaría para toda la API, que es una
            # regresión de rendimiento a cambio de nada.
            "X-Accel-Buffering": "no",
        },
    )

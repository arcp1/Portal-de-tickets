"""El grafo: ver por dónde va una consulta mientras va.

Dos puertas que se usan juntas:

  - ``WS  /api/conciencia/flujo``     — la traza en vivo. La pantalla se
    conecta una vez y recibe un paso cada vez que un nodo se enciende.
  - ``POST /api/conciencia/consultar`` — la consulta RAG, asíncrona, que va
    emitiendo esos pasos mientras trabaja.

**Por qué aquí sí un WebSocket, si el resto del portal usa SSE.** El canal de
avisos (``api/eventos.py``) va en una sola dirección y por eso SSE le sobra
—es HTTP normal, pasa por el mismo nginx y la misma cabecera de autorización—.
Aquí hay un segundo sentido que importa: la pantalla dice qué consulta está
mirando y cuándo deja de mirarla, y con eso el backend no arma el detalle de
pasos que nadie va a leer. Con SSE eso serían peticiones sueltas contra el
mismo estado, que es reinventar el WebSocket peor.

**Cómo se autentica, y por qué no por la URL.** El token va en el **primer
mensaje**, nunca en la dirección. Un ``?token=...`` acabaría en el registro de
accesos de nginx, en el historial del navegador y en cualquier traza — el mismo
error que ya costó una llave de Gemini en claro. El navegador no deja poner
cabeceras al abrir un WebSocket, así que el primer mensaje es el sitio que
queda.

Eso tiene además una consecuencia buena que conviene dejar dicha: los
WebSocket **no** los protege CORS, así que cualquier página de internet puede
abrir uno contra este portal. Aquí no le sirve de nada. La sesión vive en
``localStorage`` y no en una *cookie*, o sea que no hay credencial ambiental
que el navegador adjunte solo: esa página tendría que conocer el token, y si lo
conoce ya perdimos por otro lado. La comprobación de ``Origin`` de más abajo es
un cinturón sobre los tirantes, no lo que sostiene esto.
"""

import asyncio
from typing import List, Optional
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from fastapi import status as http_status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin, usuario_con_cupo_ia, usuario_desde_token
from app.core.config import settings
from app.core.db import SessionLocal, get_db
from app.models import Usuario
from app.services import cola_ia, traza_service
from app.services.asistente_service import AsistenteService
from app.services.conciencia_service import ConcienciaService
from app.services.ollama_client import ollama
from app.services.recuperacion_service import Pasaje, RecuperacionService

# Se usa `AsistenteService._vacio` a pesar del guion bajo, y a proposito: es la
# **misma** forma de respuesta que devuelve `/asistente/preguntar` cuando no hay
# nada que citar. Escribir aqui una copia del diccionario significaria que el
# dia que a esa respuesta se le anada un campo, esta ruta seguiria devolviendo
# la version vieja — y el frontend, que trata las dos igual, empezaria a leer
# un campo que unas veces esta y otras no.

router = APIRouter(prefix="/conciencia", tags=["Conciencia"])
#: Lo que solo ve TI: el panorama del conocimiento y la bitacora de
#: consultas. Va con `get_current_admin` y bajo /admin, igual que el resto
#: de superficies administrativas del portal.
admin_router = APIRouter(prefix="/admin/conciencia", tags=["Conciencia"])

#: Códigos de cierre. 1008 es "violación de política" en el estándar de
#: WebSocket; es lo que le corresponde a un token que no vale.
CIERRE_NO_AUTORIZADO = http_status.WS_1008_POLICY_VIOLATION


def _origen_permitido(websocket: WebSocket) -> bool:
    """Deja fuera a las páginas de otro sitio que abran un WebSocket aquí.

    Sin ``Origin`` se deja pasar: los clientes que no son un navegador —una
    prueba con ``websockets``, un ``curl``— no lo mandan, y no son el problema
    que esta comprobación resuelve.
    """
    origen = websocket.headers.get("origin")
    if not origen:
        return True

    permitidos = {o.strip() for o in settings.ORIGENES_PERMITIDOS.split(",") if o.strip()}
    if origen in permitidos:
        return True

    # Mismo host que sirvió la página. Es el caso normal en producción: el
    # portal y la API van detrás del mismo nginx, así que el `Origin` coincide
    # con el `Host` sin que haya que declararlo en ninguna lista.
    anfitrion = websocket.headers.get("host", "")
    return bool(anfitrion) and urlsplit(origen).netloc == anfitrion


async def _autenticar(websocket: WebSocket) -> Optional[Usuario]:
    """Espera el primer mensaje con el token y devuelve a su dueño.

    Devuelve ``None`` y deja la conexión cerrada si algo no cuadra.
    """
    try:
        primero = await asyncio.wait_for(
            websocket.receive_json(), timeout=settings.TRAZA_ESPERA_AUTENTICACION
        )
    except asyncio.TimeoutError:
        # Se abrió y no se identificó. No tiene por qué ocupar sitio.
        await websocket.close(code=CIERRE_NO_AUTORIZADO, reason="sin identificar")
        return None
    except WebSocketDisconnect:
        # El cliente ya se fue: no hay a quién cerrarle nada, e intentarlo
        # levantaría sobre una conexión que ya no existe.
        return None
    except (ValueError, TypeError):
        # Llegó algo que no es JSON. El cliente **sigue ahí**, así que se le
        # cierra con un motivo en vez de cortar en seco: un cierre abrupto
        # (1006) no lleva explicación, y quien esté depurando su cliente no
        # tiene forma de distinguirlo de una caída de red.
        await websocket.close(code=CIERRE_NO_AUTORIZADO, reason="se esperaba JSON")
        return None

    token = (primero or {}).get("token") if isinstance(primero, dict) else None
    if not token or not isinstance(token, str):
        await websocket.close(code=CIERRE_NO_AUTORIZADO, reason="falta el token")
        return None

    # Sesión corta y a mano, **no** `Depends(get_db)`.
    #
    # Una dependencia con `yield` no se cierra al devolver la respuesta sino al
    # terminarla, y esta conexión no termina hasta que el usuario cierra la
    # pestaña: sería una conexión del *pool* retenida durante horas por cada
    # pantalla abierta. Es exactamente el fallo que `api/eventos.py` documenta
    # y que ya se pagó una vez —*pool* agotado y migraciones esperando detrás
    # de lecturas que no terminaban nunca—.
    db = SessionLocal()
    try:
        usuario = usuario_desde_token(db, token)
        # Se leen aquí, con la sesión viva: después la instancia queda
        # desacoplada y tocar un atributo no cargado dispararía una consulta
        # contra una sesión que ya no existe.
        _ = usuario.id, usuario.sitio_id
        return usuario
    except Exception:  # noqa: BLE001 - un token que no vale no es un error del servidor
        await websocket.close(code=CIERRE_NO_AUTORIZADO, reason="credenciales no válidas")
        return None
    finally:
        db.close()


@router.websocket("/flujo")
async def flujo(websocket: WebSocket):
    """La traza en vivo de las consultas de quien se conecta. Solo las suyas."""
    if not _origen_permitido(websocket):
        # Se rechaza antes del apretón de manos: ni se acepta la conexión.
        await websocket.close(code=CIERRE_NO_AUTORIZADO, reason="origen no permitido")
        return

    await websocket.accept()

    usuario = await _autenticar(websocket)
    if usuario is None:
        return

    cola = traza_service.difusor_traza.suscribir(usuario.id)

    async def escuchar_cierre():
        """Se entera de que el cliente se fue.

        Sin esto, una pantalla cerrada de golpe —la pestaña, no la red— no se
        detecta hasta el siguiente envío, y mientras tanto su cola sigue
        suscrita acumulando pasos que no lee nadie.
        """
        try:
            while True:
                await websocket.receive_text()
        except Exception:  # noqa: BLE001 - cualquier fin de conexión sirve
            return

    vigilante = asyncio.create_task(escuchar_cierre())
    try:
        await websocket.send_json({"tipo": "listo", "nodos": list(traza_service.NODOS)})

        while not vigilante.done():
            try:
                paso = await asyncio.wait_for(
                    cola.get(), timeout=settings.TRAZA_LATIDO_SEGUNDOS
                )
            except asyncio.TimeoutError:
                # Latido. Sin tráfico, un intermediario da la conexión por
                # muerta y la corta; el cliente reconecta, y el portal acaba
                # abriendo conexiones en bucle.
                await websocket.send_json({"tipo": "latido"})
                continue
            await websocket.send_json({"tipo": "paso", **paso})

    except (WebSocketDisconnect, RuntimeError):
        # El cliente cerró, o se intentó escribir sobre una conexión ya
        # cerrada. Las dos cosas son el fin normal de una pantalla.
        pass
    except asyncio.CancelledError:
        raise
    finally:
        vigilante.cancel()
        traza_service.difusor_traza.cancelar(usuario.id, cola)


# ----------------------------------------------------------------------
# La consulta
# ----------------------------------------------------------------------

class ConsultaRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    texto: str = Field(min_length=1, max_length=2000)
    categoria: Optional[str] = None


async def _anotar(db, usuario, texto, categoria, resultado, traza) -> None:
    """Apunta la consulta en la bitácora, sin bloquear ni romper nada.

    **En un hilo**, porque escribir en Postgres es bloqueante y esta ruta es
    `async`: hacerlo en el bucle congelaría el portal entero durante la
    escritura, para todo el mundo. Es el mismo motivo por el que la búsqueda y
    la redacción van en `to_thread`.

    Y va **después** de que la respuesta esté armada, no antes: si apuntar
    fallara, la persona ya tiene lo que pidió. `ConcienciaService.registrar`
    además se traga sus propios errores — la bitácora existe para explicar
    fallos, no para causarlos.
    """
    await asyncio.to_thread(
        ConcienciaService.registrar,
        db,
        sitio_id=usuario.sitio_id,
        usuario_id=usuario.id,
        pregunta=texto,
        categoria=categoria,
        resultado=resultado,
        duracion_ms=traza.transcurrido_ms(),
    )


@router.post("/consultar")
async def consultar(
    peticion: ConsultaRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(usuario_con_cupo_ia),
):
    """La misma respuesta que `/asistente/preguntar`, contando por dónde va.

    **`async def` y todo el trabajo pesado en un hilo.** Es lo que hace que
    cinco personas a la vez no se estorben. Si esta ruta fuera `def`, cada
    consulta ocuparía un hilo del *pool* durante los segundos que tarde Ollama
    —y con el aforo de generación en uno, cuatro de esos hilos estarían
    esperando turno sin hacer nada—. Siendo `async`, el bucle queda libre entre
    etapa y etapa para atender al resto del portal: los tableros, los tickets,
    todo lo que no es IA sigue respondiendo en milisegundos mientras el modelo
    trabaja.

    Cada `to_thread` de abajo es una llamada bloqueante —pgvector o httpx
    contra Ollama— sacada del bucle de eventos. Sin ellos, `async def` sería
    peor que `def`: un solo `httpx.Client` síncrono dentro del bucle congela el
    portal entero para todo el mundo.

    La forma de la respuesta es idéntica a la de `/asistente/preguntar`, más un
    `traza` con el identificador que agrupa los pasos del grafo.
    """
    texto = peticion.texto.strip()
    traza = traza_service.abrir(current_user.id)
    sitio_id = current_user.sitio_id

    traza.paso("usuario", "listo", caracteres=len(texto))

    # --- Vectorizar la pregunta -------------------------------------
    traza.paso("embedding", "activo", modelo=settings.OLLAMA_MODELO_EMBEDDING)
    vector: Optional[List[float]] = await asyncio.to_thread(
        ollama.generar_embedding, texto, "consulta"
    )

    if vector is None:
        # Sin vector no hay búsqueda por similitud, y sin búsqueda no se le
        # pregunta a ningún modelo: se contesta que no hay nada escrito. Es la
        # misma degradación de siempre, ahora visible en el grafo.
        traza.paso("embedding", "error")
        traza.paso("conocimiento", "omitido", desde="embedding")
        traza.paso("ia_local", "omitido", motivo="sin_fundamento")
        traza.paso("respuesta", "listo", origen="sin_fundamento")
        vacio = AsistenteService._vacio("sin_fundamento", [])
        await _anotar(db, current_user, texto, peticion.categoria, vacio, traza)
        return {**vacio, "traza": traza.id}

    traza.paso("embedding", "listo", dimensiones=len(vector))

    # --- Buscar en lo nuestro ---------------------------------------
    traza.paso("conocimiento", "activo")
    # Por nombre y no por posición: `buscar` tiene ocho parámetros y varios
    # opcionales en medio. Pasarlos posicionalmente aquí significa que el día
    # que alguien inserte uno, esta llamada sigue compilando y empieza a
    # mandar la categoría donde iba el umbral.
    pasajes: List[Pasaje] = await asyncio.to_thread(
        RecuperacionService.buscar,
        db,
        texto,
        sitio_id,
        categoria=peticion.categoria,
        vector=vector,
    )

    traza.paso(
        "conocimiento",
        "listo" if pasajes else "omitido",
        pasajes=len(pasajes),
        similitud=round(pasajes[0].similitud, 3) if pasajes else None,
        fuentes=sorted({p.fuente for p in pasajes}) or None,
    )

    if not pasajes:
        traza.paso("ia_local", "omitido", motivo="sin_fundamento")
        traza.paso("respuesta", "listo", origen="sin_fundamento")
        vacio = AsistenteService._vacio("sin_fundamento", [])
        await _anotar(db, current_user, texto, peticion.categoria, vacio, traza)
        return {**vacio, "traza": traza.id}

    # --- Redactar, si hace falta ------------------------------------
    #
    # Estos tres números son los que convierten el grafo en una herramienta de
    # diagnóstico. Cuando alguien dice "está lento", contestan cuál de las dos
    # cosas distintas está pasando:
    #
    #   duracion_mediana alta, cola vacía  → el modelo piensa despacio. Se
    #                                        arregla con un modelo más chico.
    #   duracion normal, cola con gente    → hay fila. Se arregla con más
    #                                        aforo, o aceptando que la máquina
    #                                        da lo que da.
    #
    # `espera_estimada_s` es además lo que la pantalla puede decirle a la
    # persona antes de que se canse: "hay cola, esto puede tardar medio minuto"
    # es una espera; una ruedita sin explicación es una avería.
    espera = cola_ia.generacion.metricas()
    traza.paso(
        "ia_local", "activo",
        modelo=settings.OLLAMA_MODELO_TEXTO,
        en_cola=espera["esperando"],
        en_curso=espera["en_curso"],
        espera_estimada_s=espera["espera_estimada_s"] or None,
        duracion_mediana_s=espera["duracion_mediana_s"],
    )

    resultado = await asyncio.to_thread(
        AsistenteService.responder,
        db,
        pregunta=texto,
        sitio_id=sitio_id,
        categoria=peticion.categoria,
        pasajes=pasajes,
    )

    origen = resultado.get("origen")

    # Cada origen cuenta una historia distinta y el grafo la dibuja:
    #
    #   directo   — la respuesta ya estaba escrita; ningún modelo redactó nada
    #               y el nodo se queda apagado. Es la escalera funcionando.
    #   ollama    — redactó el local.
    #   gemini    — el local no alcanzó y subió un peldaño.
    #   extractos — ningún modelo disponible o ninguno pasó los filtros; van
    #               los pasajes tal cual.
    if origen == "directo":
        traza.paso("ia_local", "omitido", motivo="coincidencia_directa")
    elif origen == "ollama":
        traza.paso("ia_local", "listo")
    elif origen == "gemini":
        traza.paso("ia_local", "omitido", motivo="no_paso_filtros")
        traza.paso("gemini", "listo", desde="ia_local")
    else:
        traza.paso("ia_local", "omitido", motivo="sin_redaccion")

    traza.paso(
        "respuesta", "listo",
        desde="gemini" if origen == "gemini" else "ia_local",
        origen=origen,
        fuentes=len(resultado.get("fuentes") or []),
    )

    await _anotar(db, current_user, texto, peticion.categoria, resultado, traza)
    return {**resultado, "traza": traza.id}


# `GET /carga` vivía aquí y se quitó. Devolvía `cola_ia.metricas()` para que una
# pantalla avisara de la cola **antes** de preguntar, y esa pantalla nunca se
# hizo: ninguna llamaba a esta ruta.
#
# No se hizo porque no hacía falta. Durante la espera, la traza ya manda
# `en_cola` y `espera_estimada_s` por el WebSocket y el grafo lo pinta en el
# nodo del modelo; y para diagnosticar, la misma `cola_ia.metricas()` viaja
# dentro de `/admin/estado/sistema`, donde Estado del Sistema la enseña —que es
# la pantalla donde alguien puede hacer algo con el dato—.
#
# Queda escrito para que no se vuelva a añadir: el problema que resolvía ya
# estaba resuelto en dos sitios mejores.


# ----------------------------------------------------------------------
# Lo que solo ve TI: de lo general a lo particular
# ----------------------------------------------------------------------
#
# Tres rutas y el orden en que se leen **es** el diseño de la pantalla:
#
#   /panorama    ¿De qué sabe la planta y de qué no?      ← se mira primero
#   /aprendizaje ¿Está entrando conocimiento nuevo?
#   /consultas   ¿Qué se preguntó y qué se encontró?      ← el detalle
#
# Van separadas y no en un solo endpoint gordo porque se refrescan a ritmos
# distintos: el panorama cambia cuando alguien escribe documentación —días—, y
# la lista de consultas cambia cada vez que alguien usa el portal. Juntarlas
# obligaría a recalcular lo caro para refrescar lo barato.


#: Diez años: más de lo que el portal lleva vivo. Sin tope, un `dias` de veinte
#: cifras desbordaba la resta de fechas y salía como un error interno.
DIAS_MAXIMOS = 3650


@admin_router.get("/panorama")
def panorama(
    dias: int = Query(30, ge=1, le=DIAS_MAXIMOS),
    sitio_id: Optional[int] = Query(None, ge=1, le=2**31 - 1),
    db: Session = Depends(get_db),
    admin: Usuario = Depends(get_current_admin),
):
    """Nivel 1. Qué sabe la planta, por categoría, y dónde están los huecos.

    `estado` resume cada categoría en una palabra:

      - `vacio`    — no hay nada escrito, y tampoco se lo han preguntado.
      - `hueco`    — no hay nada escrito **y se lo están preguntando**. Es el
                     más caro de todos: cada consulta ahí es alguien que se
                     quedó sin ayuda.
      - `flojo`    — hay conocimiento y aun así falla la mitad de las veces.
                     Suele ser conocimiento mal etiquetado, no insuficiente.
      - `cubierto` — funciona.
    """
    return ConcienciaService.panorama(db, sitio_id, dias=dias)


@admin_router.get("/aprendizaje")
def aprendizaje(
    dias: int = Query(30, ge=1, le=DIAS_MAXIMOS),
    sitio_id: Optional[int] = Query(None, ge=1, le=2**31 - 1),
    db: Session = Depends(get_db),
    admin: Usuario = Depends(get_current_admin),
):
    """Nivel 2. La tubería por la que entra el conocimiento, y dónde se atasca.

    Un ticket se resuelve, se indexa, varios parecidos se consolidan en un
    procedimiento, y lo que no encaja en ninguna categoría se propone como tema
    nuevo. Cada etapa puede pararse por su cuenta y **parada no avisa**: el
    portal simplemente deja de aprender.

    En `avisos` van las entradas cuya etiqueta no concuerda con su propio texto.
    Solo se señalan; corregir una etiqueta es cosa de una persona.
    """
    return ConcienciaService.aprendizaje(db, sitio_id, dias=dias)


@admin_router.get("/consultas")
def consultas(
    dias: int = Query(30, ge=1, le=DIAS_MAXIMOS),
    sitio_id: Optional[int] = Query(None, ge=1, le=2**31 - 1),
    solo_fallidas: bool = False,
    categoria: Optional[str] = None,
    limite: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
    admin: Usuario = Depends(get_current_admin),
):
    """Nivel 3. Qué se preguntó de verdad y qué se recuperó para cada consulta.

    Con `solo_fallidas` queda la lista que de verdad se usa: lo que el portal no
    supo contestar, que es la lista de lo que hay que documentar.
    """
    return ConcienciaService.consultas(
        db, sitio_id, dias=dias, solo_fallidas=solo_fallidas,
        categoria=categoria, limite=limite,
    )

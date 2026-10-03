from fastapi import BackgroundTasks, APIRouter, Depends, Header, HTTPException, Query, Request, status
from sqlalchemy import or_, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, selectinload
from typing import Optional
import re
from datetime import datetime
from math import ceil

from app.core import plantas
from app.core.db import SessionLocal, get_db
from app.models import (
    CANCELADO, ESTADOS_TERMINADOS, PRIORIDADES_ALTAS, ChatSesion, Equipo, Sitio, Ticket,
    TicketComentario, Usuario,
)
from app.schemas.ticket import (
    CommentCreate, CommentResponse, SatisfaccionCreate, TicketCreate, TicketPagina,
    TicketResponse, TicketUpdate,
)
from app.api.deps import get_current_user
from app.services import eventos_service as eventos
from app.services.rules_engine import RulesEngine
from app.services.asistente_service import AsistenteService
from app.services.kb_service import (
    CANALES_AUTOSERVICIO, KBService, solucion_es_valida)
from app.services.folios import siguiente_folio
from app.services.temas_service import TemasService
from app.services.horario_service import HorarioService
from app.services.notificaciones_service import NotificacionesService
from app.services.auditoria_service import (
    TICKET_ASIGNADO, TICKET_CALIFICADO, TICKET_CANCELADO, TICKET_ESTADO, TICKET_PRIORIDAD,
    TICKET_SOLUCION, AuditoriaService,
)
from app.services.alertas_service import SATISFACCION_BAJA, AlertasService
from app.services.metricas_service import CANALES_DEFLECTADOS
from app.core import tareas
from app.services.ollama_client import ollama
from app.core.config import settings
from app.core.logging import logger

router = APIRouter(prefix="/tickets", tags=["Tickets"])

# Estados que exigen una solución documentada para poder entrar en ellos.
ESTADOS_DE_CIERRE = ("resuelto", "cerrado")

# Canales que el propio usuario puede reportar al crear el ticket. Son los
# niveles de autoservicio del flujo; "tecnico" y "proveedor" los decide el
# sistema, nunca quien reporta.
#
# Se importa de `kb_service` en vez de definirse aquí: la misma lista decide
# qué se acepta al crear y qué **no** se indexa, y tenerla en dos sitios ya
# costó una entrada basura en la base de conocimiento.

# Los valores que estas tres columnas admiten. Son enumeraciones de hecho
# —el modelo las guarda como texto libre— y hasta ahora nadie las comprobaba
# al editar: `PATCH` escribia lo que llegara. Un `estado` inventado deja al
# ticket fuera de todas las pestanas del tablero, que filtran por estos
# mismos nombres, asi que el ticket desaparece de la vista sin borrarse.
# "cancelado" no está a propósito: cancelar lo hace quien reportó, por su
# propia ruta (`cancelar_ticket`). TI cierra con solución; no cancela.
ESTADOS_VALIDOS = ("abierto", "en_proceso", "espera_proveedor", "resuelto", "cerrado")
PRIORIDADES_VALIDAS = ("baja", "media", "alta", "critica")
# Incluye los del sistema: aqui se valida **que** el valor exista, y aparte
# se comprueba **quien** puede ponerlo.
CANALES_VALIDOS = ("checklist", "kb", "ia", "visual", "tecnico", "proveedor")

def _ticket_visible(ticket: Ticket, usuario: Usuario) -> bool:
    """Su propio ticket, o cualquiera si es de TI.

    TI es global desde la versión multi-planta (ver app/core/plantas.py): ve
    los tickets de todas las plantas. Una persona de planta, solo los suyos.
    """
    if ticket.usuario_id == usuario.id:
        return True
    return usuario.rol == "admin" and plantas.alcanza(usuario, ticket.sitio_id)


def _sin_notas_internas(ticket: Ticket, usuario: Usuario) -> Ticket:
    """Quita del ticket las notas que son solo para TI.

    La casilla al pie del comentario dice, con todas sus letras, «Nota interna
    (solo visibles para TI)», y el backend ya cuidaba la mitad de esa promesa:
    un usuario no puede *crear* una nota interna —`es_interno` se fuerza a
    False si no es admin— y las notas internas no disparan el aviso por correo
    a quien reporto.

    La otra mitad faltaba. `comentarios` sale de la relacion del ORM tal cual,
    sin mirar quien pregunta, asi que el dueño del ticket recibia las notas
    internas en la misma lista que las suyas y la pantalla se las pintaba. Ahi
    es donde un tecnico escribe lo que cuesta la pieza, lo que sospecha antes
    de confirmarlo o lo que no quiere decirle todavia a la persona.

    Se filtra en la respuesta y no en la consulta a proposito: la relacion se
    usa tambien para indexar y para las metricas, y ahi las notas internas si
    cuentan. Lo que cambia es lo que sale por la API.

    **Y se filtra sobre la respuesta, nunca sobre el objeto del ORM.** Antes se
    reasignaba `ticket.comentarios`, y esa relacion lleva
    `cascade="all, delete-orphan"`: para SQLAlchemy, las notas que quedaban
    fuera de la lista eran huerfanas y se **borraban** en el siguiente commit
    de la sesion. No llego a pasar solo porque ninguna ruta hacia commit
    despues de filtrar; `test_consultas_por_listado.py` lo reproduce.
    """
    respuesta = TicketResponse.model_validate(ticket)
    if usuario.rol != "admin":
        respuesta.comentarios = [c for c in respuesta.comentarios if not c.es_interno]
    return respuesta


def _con_todo(consulta):
    """Todo lo que `TicketResponse` pinta, en consultas fijas.

    Sin esto cada ticket del tablero costaba cinco viajes más a la base —quien
    lo reporta, a quién se asignó, sus comentarios, el autor de cada uno, sus
    adjuntos—: medido, 8 consultas con un ticket y 28 con cinco. El tablero se
    vuelve a pedir en cada pantalla abierta cada vez que alguien mueve un
    ticket, así que eso se multiplicaba por el número de gente mirando.
    """
    return consulta.options(
        joinedload(Ticket.sitio),
        joinedload(Ticket.usuario).joinedload(Usuario.sitio),
        joinedload(Ticket.asignado_usuario).joinedload(Usuario.sitio),
        selectinload(Ticket.comentarios)
        .joinedload(TicketComentario.autor).joinedload(Usuario.sitio),
        selectinload(Ticket.adjuntos),
        selectinload(Ticket.imagenes_solucion),
    )


def generate_folio(db: Session, sitio_id: int) -> str:
    sitio = db.get(Sitio, sitio_id)
    clave = sitio.clave if sitio else "PLANT"
    year = datetime.utcnow().strftime("%Y")
    return siguiente_folio(db, Ticket, f"TICK-{clave}-{year}-")


#: Veces que se recalcula el folio si otro ticket se lo gana en paralelo.
INTENTOS_FOLIO = 3

#: Ver la migración 0024: letras, dígitos y guiones, como un UUID.
CLAVE_ENVIO = re.compile(r"[A-Za-z0-9_-]{8,64}")


def _clave_de_envio(valor: Optional[str]) -> Optional[str]:
    """La `Idempotency-Key` del formulario, o None si no vino. 422 si vino mal."""
    if valor is None or not valor.strip():
        return None
    valor = valor.strip()
    if not CLAVE_ENVIO.fullmatch(valor):
        raise HTTPException(status_code=422, detail="La clave de envío no es válida.")
    return valor


def _ya_enviado(db: Session, usuario: Usuario, clave: Optional[str]) -> Optional[Ticket]:
    if not clave:
        return None
    return db.query(Ticket).filter(Ticket.usuario_id == usuario.id,
                                   Ticket.clave_envio == clave).first()


def _turno_de_folio(db: Session, sitio_id: int) -> None:
    """Pone en fila las altas de una misma planta mientras se calcula su folio.

    **Reintentar no bastaba.** Medido con diez tickets levantados a la vez:
    seis entraron y cuatro devolvieron un 500, porque los diez veían el mismo
    máximo, chocaban en el índice único y los reintentos volvían a chocar entre
    ellos. Un candado de Postgres por planta, que se suelta solo con el commit,
    hace que cada alta calcule su folio cuando la anterior ya lo guardó. Dura
    lo que tarda un INSERT; las plantas distintas no se esperan entre sí.

    En SQLite —las pruebas— no existe y no hace falta: no hay concurrencia.
    """
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(:clave)"), {"clave": 7_310_000 + sitio_id})

#: Tickets por página si no se pide otra cosa, y el tope de lo que se puede
#: pedir. El tope importa: sin él, `por_pagina=100000` devolvía la tabla
#: entera, que es justo lo que la paginación existe para evitar.
POR_PAGINA = 20
POR_PAGINA_MAXIMO = 100
#: Ninguna planta va a tener cien mil páginas de tickets. El tope está para que
#: una página absurda en la URL sea un 422 y no un desplazamiento que no cabe
#: en un entero de la base —que antes salía como 500—.
PAGINA_MAXIMA = 100_000


@router.get("", response_model=TicketPagina)
def list_tickets(
    estado: Optional[str] = None,
    categoria: Optional[str] = None,
    buscar: Optional[str] = Query(None, max_length=100),
    sitio_id: Optional[int] = Query(None, ge=1, le=2**31 - 1),
    pagina: int = Query(1, ge=1, le=PAGINA_MAXIMA),
    por_pagina: int = Query(POR_PAGINA, ge=1, le=POR_PAGINA_MAXIMO),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """El tablero, una página a la vez.

    **Antes devolvía todos los tickets de la planta en cada petición**, con sus
    comentarios y adjuntos, y el tablero se vuelve a pedir en cada pantalla
    abierta cada vez que alguien mueve un ticket. Con la planta entera eso son
    miles de tickets por refresco.

    **La búsqueda se hace aquí y no en el navegador.** Antes filtraba lo que ya
    había llegado; con páginas, eso solo buscaría en la página visible y
    "no hay resultados" mentiría. Se busca por folio y por lo que escribió la
    persona, sin distinguir mayúsculas, y con `%` y `_` tomados como letras.
    """
    query = db.query(Ticket)

    # Quien reporta ve los suyos; TI, los de todas las plantas, y puede
    # quedarse con una (la etiqueta de planta de cada tarjeta dice cuál es).
    if current_user.rol != "admin":
        query = query.filter(Ticket.usuario_id == current_user.id)
    elif sitio_id is not None:
        query = query.filter(Ticket.sitio_id == sitio_id)

    if estado:
        query = query.filter(Ticket.estado == estado)
    if categoria:
        query = query.filter(Ticket.categoria == categoria)
    texto = (buscar or "").strip()
    if texto:
        query = query.filter(or_(
            Ticket.folio.icontains(texto, autoescape=True),
            Ticket.descripcion_original.icontains(texto, autoescape=True),
        ))

    total = query.count()
    # Por fecha y, a igualdad, por id: sin un desempate fijo, dos tickets del
    # mismo instante pueden salir en las dos páginas o en ninguna.
    tickets = (
        _con_todo(query)
        .order_by(Ticket.creado_en.desc(), Ticket.id.desc())
        .offset((pagina - 1) * por_pagina)
        .limit(por_pagina)
        .all()
    )
    return {
        "items": [_sin_notas_internas(t, current_user) for t in tickets],
        "total": total,
        "pagina": pagina,
        "por_pagina": por_pagina,
        "paginas": max(1, ceil(total / por_pagina)),
    }

def _normalizar_despues(ticket_id: int, descripcion: str) -> None:
    """Reescribe la descripción del ticket cuando la respuesta ya salió.

    **Sesión propia y no la de la petición.** La de la petición se cierra al
    terminar la respuesta, y esto corre justo después: reutilizarla daría un
    `DetachedInstanceError` el día que alguien mire los registros.

    No levanta nunca. Si Ollama no está, si tarda de más o si el ticket se
    borró mientras tanto, el ticket se queda con la descripción que escribió el
    usuario — que es exactamente lo que pasaba antes, solo que ahora sin
    hacerle esperar diez segundos para llegar a lo mismo.
    """
    try:
        texto = ollama.normalizar_descripcion(descripcion)
        if not texto:
            return

        # ¿La reescritura habla de lo mismo que el reporte?
        #
        # Un modelo de 3B reescribiendo a veces se va a otro asunto. Esto lo
        # atrapa; lo que **no** atrapa es que cuele una frase plausible dentro
        # de un texto por lo demás correcto — medido, eso puntúa igual que una
        # reescritura buena (ver `anclaje_en_texto`). El corte va bajo a
        # propósito, en el hueco que la medición sí separa: invención total
        # contra cualquier cosa anclada.
        #
        # La defensa contra el caso sutil no es este número: es que
        # `descripcion_original` no se pisa nunca, se muestra primero en el
        # ticket y se indexa siempre junto a la reescrita.
        anclaje = AsistenteService.anclaje_en_texto(texto, descripcion)
        if anclaje < settings.NORMALIZACION_ANCLAJE_MINIMO:
            logger.info(
                "La descripción reescrita habla de otra cosa: se descarta",
                extra={"ticket_id": ticket_id, "anclaje": round(anclaje, 2)},
            )
            return

        db = SessionLocal()
        try:
            ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
            if ticket is None:
                return
            ticket.descripcion_normalizada = texto
            db.commit()
        finally:
            db.close()
    except Exception as exc:  # noqa: BLE001 - jamas rompe nada: la respuesta ya se envio
        logger.warning("No se pudo normalizar la descripción en segundo plano",
                       extra={"ticket_id": ticket_id, "error": str(exc)})


@router.post("", response_model=TicketResponse, status_code=status.HTTP_201_CREATED)
def create_ticket(
    ticket_in: TicketCreate,
    tareas: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
    clave_envio: Optional[str] = Header(default=None, alias="Idempotency-Key"),
):
    # **Un reintento no crea un segundo ticket.** Si la red se cortó después
    # de crearlo y antes de que llegara la respuesta, el formulario vuelve a
    # mandar la misma clave y recibe el que ya existe. Ver migración 0024.
    clave_envio = _clave_de_envio(clave_envio)
    previo = _ya_enviado(db, current_user, clave_envio)
    if previo:
        return _sin_notas_internas(previo, current_user)

    ahora = datetime.utcnow()

    # **La planta del ticket es una de las de quien lo levanta.** Quien
    # trabaja en dos plantas elige en cuál; una planta que no es suya se
    # rechaza: tomaría el folio de esa planta y caería en su cola.
    sitio_id = plantas.planta_para(db, current_user, ticket_in.sitio_id)

    # El equipo, si se indica, tiene que existir y ser de la planta. Antes un
    # id inexistente llegaba a la clave foránea y salía como 500, y uno de otra
    # planta entraba sin más: el ticket quedaba ligado al equipo de otro sitio.
    if ticket_in.equipo_id is not None:
        equipo = (db.get(Equipo, ticket_in.equipo_id)
                  if 0 < ticket_in.equipo_id < 2 ** 31 else None)
        if not equipo or equipo.sitio_id != sitio_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="El equipo indicado no existe en esa planta.",
            )

    # La prioridad que se pide tiene que existir. Antes no se comprobaba al
    # crear —solo al editar— y una inventada caía en "media" sin decirlo al
    # calcular el vencimiento, pero quedaba escrita tal cual en el ticket.
    if ticket_in.prioridad not in PRIORIDADES_VALIDAS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Prioridad inválida. Se acepta: " + ", ".join(PRIORIDADES_VALIDAS),
        )
    # **Prioridad alta revocada: el ticket nace en "media".** No se rechaza:
    # la persona tiene un problema y el ticket tiene que existir igual. La
    # pantalla ya no le ofrece alta ni crítica, así que llegar aquí con una es
    # haber pasado por encima de la pantalla. Queda nota interna para TI de lo
    # que se pidió, que es justo lo que hace falta para revisar la sanción.
    prioridad_pedida = ticket_in.prioridad
    degradada = (current_user.rol != "admin"
                 and not current_user.puede_usar_prioridad_alta
                 and prioridad_pedida in PRIORIDADES_ALTAS)
    if degradada:
        ticket_in.prioridad = "media"

    folio = generate_folio(db, sitio_id)

    # Evaluate business rules
    rule_eval = RulesEngine.evaluate_and_apply_rules(
        db=db,
        sitio_id=sitio_id,
        categoria=ticket_in.categoria,
        descripcion=ticket_in.descripcion_original
    )

    estado = rule_eval["estado"] if rule_eval["matched"] else "abierto"
    canal_resolucion = rule_eval["canal_resolucion"] if rule_eval["matched"] else "tecnico"
    # Una regla puede imponer prioridad (escalar) y dejar la solucion escrita
    # (auto). Fuera de eso manda lo que eligio quien reporta.
    prioridad = ticket_in.prioridad
    solucion_regla = None
    if rule_eval["matched"]:
        if rule_eval["prioridad"]:
            prioridad = rule_eval["prioridad"]
        solucion_regla = rule_eval["solucion"]
    # Un cierre por regla es un cierre: lleva su marca de tiempo y no vence.
    cerrado_por_regla = bool(solucion_regla) and estado in ESTADOS_DE_CIERRE

    # Auto-resolución declarada por el usuario (checklist o base de conocimiento).
    # Se guarda como ticket ya resuelto: es la única forma de medir la tasa de
    # deflección. No se indexa en la KB —el checklist ya existe y la sugerencia
    # de KB ya está indexada—, solo se registra el canal.
    auto_resuelto = False
    if ticket_in.canal_auto_resolucion is not None:
        if ticket_in.canal_auto_resolucion not in CANALES_AUTOSERVICIO:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=(
                    "Canal de auto-resolución inválido. Solo se acepta: "
                    + ", ".join(CANALES_AUTOSERVICIO)
                ),
            )
        if not solucion_es_valida(ticket_in.solucion):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=(
                    "Una auto-resolución debe indicar qué resolvió el problema "
                    f"(mínimo {settings.SOLUCION_MIN_LONGITUD} caracteres)."
                ),
            )
        auto_resuelto = True
        estado = "resuelto"
        canal_resolucion = ticket_in.canal_auto_resolucion

    # La descripción se normaliza **después de responder**, no aquí.
    #
    # Era el único trabajo de IA en el camino crítico de crear un ticket, y
    # costaba lo que tardara el modelo —medido: entre 7 y 10 segundos— antes de
    # que el usuario viera su folio. Peor todavía: con el timeout en 10 s
    # normalmente ni siquiera terminaba, así que esos segundos se gastaban para
    # acabar guardando la descripción original de todos modos.
    #
    # Reescribir el reporte es una comodidad para quien lo lea luego; nadie la
    # necesita en el instante de levantarlo. Ahora el ticket se crea al momento
    # y el texto se mejora unos segundos después, por detrás. Ver `_normalizar_despues`.
    descripcion_normalizada = None

    # Un ticket que nace cerrado —lo declare el usuario o una regla— lleva su
    # hora de resolucion y no tiene compromiso pendiente. Sin esto un cierre
    # por regla salia "resuelto" pero con SLA corriendo y ya vencido.
    nace_cerrado = auto_resuelto or cerrado_por_regla

    new_ticket = Ticket(
        sitio_id=sitio_id,
        folio=folio,
        usuario_id=current_user.id,
        equipo_id=ticket_in.equipo_id,
        categoria=ticket_in.categoria,
        subcategoria=ticket_in.subcategoria,
        descripcion_original=ticket_in.descripcion_original,
        descripcion_normalizada=descripcion_normalizada,
        prioridad=prioridad,
        estado=estado,
        canal_resolucion=canal_resolucion,
        solucion=ticket_in.solucion if auto_resuelto else solucion_regla,
        # Lo que ya se probó y no era: opcional, pero cuando lo hay vale tanto
        # como la solución. Antes se aceptaba en el cuerpo y se tiraba.
        descartado=(ticket_in.descartado or "").strip() or None,
        creado_en=ahora,
        resuelto_en=ahora if nace_cerrado else None,
        tiempo_resolucion=0 if nace_cerrado else None,
        # El SLA cuenta solo horas hábiles y, si entra de madrugada, empieza a
        # correr cuando abren. Una auto-resolución ya está cerrada: no vence.
        vence_en=None if nace_cerrado else HorarioService.calcular_vencimiento(prioridad, ahora),
        fuera_horario=not HorarioService.es_horario_laboral(ahora),
    )
    # Dos tickets levantados a la vez calculan el mismo folio: los dos ven el
    # mismo máximo. El índice único rechaza al segundo, y en vez de devolverle
    # un 500 a esa persona se recalcula y se vuelve a intentar.
    new_ticket.clave_envio = clave_envio
    for intento in range(INTENTOS_FOLIO):
        _turno_de_folio(db, sitio_id)
        new_ticket.folio = folio = generate_folio(db, sitio_id)
        db.add(new_ticket)
        try:
            db.commit()
            break
        except IntegrityError:
            db.rollback()
            # El reintento llegó mientras el primer envío aún se guardaba: el
            # índice de la clave rechazó a este, y el bueno es el otro.
            previo = _ya_enviado(db, current_user, clave_envio)
            if previo:
                return _sin_notas_internas(previo, current_user)
            if intento == INTENTOS_FOLIO - 1:
                raise
    db.refresh(new_ticket)

    if rule_eval["matched"] and rule_eval["nota"]:
        system_comment = TicketComentario(
            ticket_id=new_ticket.id,
            autor_id=current_user.id,
            comentario=f"[SISTEMA] {rule_eval['nota']}",
            es_interno=True,
            creado_en=datetime.utcnow()
        )
        db.add(system_comment)
        db.commit()
        db.refresh(new_ticket)

    if degradada:
        db.add(TicketComentario(
            ticket_id=new_ticket.id,
            autor_id=current_user.id,
            comentario=(f"[SISTEMA] Se pidió prioridad «{prioridad_pedida}» y se registró como "
                        "«media»: esta cuenta tiene revocado el uso de prioridad alta."),
            es_interno=True,
            creado_en=datetime.utcnow(),
        ))
        db.commit()
        db.refresh(new_ticket)

    # Enlaza la sesión de chat que originó el ticket. Solo la del propio
    # usuario, y solo si aún no está enlazada.
    if ticket_in.chat_sesion_id is not None:
        sesion = db.query(ChatSesion).filter(
            ChatSesion.id == ticket_in.chat_sesion_id,
            ChatSesion.usuario_id == current_user.id,
            ChatSesion.ticket_id.is_(None),
        ).first()
        if sesion:
            sesion.ticket_id = new_ticket.id
            db.commit()

    # Reescribir la descripción, ya con el folio entregado.
    tareas.add_task(_normalizar_despues, new_ticket.id, ticket_in.descripcion_original)

    # Un problema que no encaja en las categorias se agrupa con lo parecido
    # ya reportado. Si se repite, se le propone al admin como tema nuevo.
    # Nunca levanta: el ticket ya esta creado.
    TemasService.registrar_incidencia(db, new_ticket)

    # Acuse de recibo. Si el correo falla, el ticket ya esta creado y no pasa nada.
    NotificacionesService.ticket_creado(db, new_ticket, new_ticket.fuera_horario)

    # Si una regla lo derivo a un proveedor, se le avisa. La pantalla de reglas
    # pide ese correo desde siempre; hasta ahora solo se guardaba.
    if rule_eval["matched"] and rule_eval["accion"] == "proveedor" and rule_eval["destinatario"]:
        NotificacionesService.ticket_a_proveedor(db, new_ticket, rule_eval["destinatario"])

    logger.info("Ticket created", extra={"ticket_id": new_ticket.id, "folio": folio, "usuario_id": current_user.id})

    # Aviso a las pantallas abiertas. Va al final, despues de que el ticket
    # este guardado y notificado: si algo de lo anterior fallara, no tiene
    # sentido haber mandado a nadie a refrescar.
    eventos.publicar(new_ticket.sitio_id, "tickets")
    # Como en cualquier otra respuesta: las notas que el sistema dejó al
    # crear —la de la regla aplicada, la de la prioridad degradada— son de TI.
    return _sin_notas_internas(new_ticket, current_user)

@router.get("/{ticket_id}", response_model=TicketResponse)
def get_ticket(
    ticket_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    ticket = _con_todo(db.query(Ticket)).filter(Ticket.id == ticket_id).first()
    if not ticket or not _ticket_visible(ticket, current_user):
        # Mismo 404 para "no existe" y "es de otra planta": no hay por que
        # confirmarle a nadie que un ticket ajeno existe.
        raise HTTPException(status_code=404, detail="Ticket no encontrado.")
    return _sin_notas_internas(ticket, current_user)

@router.patch("/{ticket_id}", response_model=TicketResponse)
def update_ticket(
    ticket_id: int,
    ticket_in: TicketUpdate,
    peticion: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    # Bloqueada hasta el commit, como al cancelar: dos cierres a la vez
    # indexaban el ticket dos veces en la base de conocimiento.
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).with_for_update().first()
    if not ticket or not _ticket_visible(ticket, current_user):
        raise HTTPException(status_code=404, detail="Ticket no encontrado.")

    # **Un ticket lo edita el equipo de TI, nadie más.** Quien lo reporta lo
    # crea, lo sigue y lo comenta; moverlo es atenderlo.
    #
    # Hasta 2026-09-30 el dueño conservaba parte de la edición —subir la
    # prioridad, pasarlo a "en proceso" o "en proveedor"— y se le fueron
    # cerrando por separado los campos que resultaron peligrosos: resolver y
    # cerrar, la solución (alimenta la base de conocimiento), el canal (es la
    # tasa de deflexión del panel), la asignación (repartía trabajo de TI y
    # mandaba correos) y la descripción normalizada (se indexa al cerrar). La
    # regla de negocio pasó a ser que prioridad y estado son exclusivos de
    # Soporte, y con eso no queda nada que el dueño pueda editar: se dice una
    # vez, aquí, en vez de campo por campo. La pantalla nunca le enseñó estos
    # controles; el API ahora tampoco los acepta.
    #
    # Va antes de cualquier validación a propósito: a quien no puede editar se
    # le responde que no puede, no que el valor que mandó es inválido.
    if current_user.rol != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=("Solo el equipo de TI puede modificar un ticket. "
                    "Si hay algo que añadir, escríbalo como comentario."),
        )

    # Cancelado es final. Lo retiró quien lo reportó, y moverlo ahora —
    # reabrirlo, subirle la prioridad— haría correr un SLA que ya se detuvo
    # sobre algo que nadie está esperando. Si el problema volvió, es otro
    # ticket. Los comentarios siguen abiertos.
    if ticket.estado == CANCELADO:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=("Este ticket lo canceló quien lo reportó y ya no se modifica. "
                    "Si el problema sigue, hay que levantar uno nuevo."),
        )

    # Las tres enumeraciones, comprobadas antes de tocar nada. El modelo las
    # guarda como texto y sin esto entraba cualquier cosa: un `estado` que no
    # existe saca al ticket de todos los filtros del tablero, y una
    # `prioridad` desconocida recalcula el vencimiento cayendo en "media" sin
    # decirlo.
    if ticket_in.estado is not None and ticket_in.estado not in ESTADOS_VALIDOS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Estado inválido. Se acepta: " + ", ".join(ESTADOS_VALIDOS),
        )
    if ticket_in.prioridad is not None and ticket_in.prioridad not in PRIORIDADES_VALIDAS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Prioridad inválida. Se acepta: " + ", ".join(PRIORIDADES_VALIDAS),
        )
    if ticket_in.canal_resolucion is not None and ticket_in.canal_resolucion not in CANALES_VALIDOS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Canal de resolución inválido. Se acepta: " + ", ".join(CANALES_VALIDOS),
        )

    # A quién se asigna: tiene que existir y ser de la misma planta. Sin esta
    # comprobación el id viajaba tal cual a la clave foránea y la violación
    # salía como un 500 —error del servidor por un dato del cliente—, además
    # de dejar la puerta a asignarle trabajo a alguien de otro sitio.
    #
    # **Y tiene que ser de TI, con la cuenta abierta.** Se aceptaba a cualquiera
    # de la planta: el selector de la ficha ofrecía la plantilla entera —quien
    # reportó incluido— y el ticket podía quedar "asignado" a alguien que ni
    # ve la cola ni puede cambiarle el estado. Nadie lo atendía y en el
    # tablero parecía atendido.
    if ticket_in.asignado_a is not None:
        destinatario = (db.get(Usuario, ticket_in.asignado_a)
                        if 0 < ticket_in.asignado_a < 2 ** 31 else None)
        if not destinatario or destinatario.eliminado_en:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="La persona asignada no existe.",
            )
        if destinatario.rol != "admin" or not destinatario.activo:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Solo se puede asignar a alguien de TI con la cuenta activa.",
            )

    # La solución puede venir en esta misma petición o estar ya documentada.
    # Se valida antes de tocar el objeto para que un rechazo no deje nada
    # a medias en la sesión.
    # Valores previos, para dejar constancia de que cambio exactamente.
    estado_previo = ticket.estado
    prioridad_previa = ticket.prioridad
    asignado_previo = ticket.asignado_a
    tenia_solucion = bool(ticket.solucion)

    solucion_efectiva = ticket_in.solucion if ticket_in.solucion is not None else ticket.solucion
    se_esta_cerrando = ticket_in.estado is not None and ticket_in.estado in ESTADOS_DE_CIERRE

    if se_esta_cerrando and not solucion_es_valida(solucion_efectiva):
        # Sin esto no se puede indexar el ticket, y una base de conocimiento
        # llena de cierres sin explicación es peor que una base vacía.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                "Debe documentar la solución para cerrar el ticket "
                f"(mínimo {settings.SOLUCION_MIN_LONGITUD} caracteres)."
            ),
        )

    if ticket_in.solucion is not None:
        ticket.solucion = ticket_in.solucion
    # Lo que se probó y no era. Opcional: no todo ticket tiene descartes, pero
    # cuando los tiene valen tanto como la solución.
    if ticket_in.descartado is not None:
        ticket.descartado = ticket_in.descartado.strip() or None

    if ticket_in.estado is not None:
        ticket.estado = ticket_in.estado
        if ticket_in.estado in ESTADOS_DE_CIERRE and not ticket.resuelto_en:
            ticket.resuelto_en = datetime.utcnow()
            diff = (ticket.resuelto_en - ticket.creado_en).total_seconds() / 60.0
            ticket.tiempo_resolucion = int(diff)

    if ticket_in.prioridad is not None:
        ticket.prioridad = ticket_in.prioridad
        # Cambiar la prioridad cambia el compromiso: se recalcula desde que se
        # creó el ticket, no desde ahora, para no regalar tiempo.
        if ticket.estado not in ESTADOS_DE_CIERRE:
            ticket.vence_en = HorarioService.calcular_vencimiento(ticket.prioridad, ticket.creado_en)
    # **Distinguir "no lo mandes" de "déjalo en nadie".** El resto del cuerpo
    # usa `is not None` como "este campo no viene", y con eso `asignado_a` se
    # volvió de una sola dirección: una vez asignado un ticket, elegir «Sin
    # asignar» mandaba `null`, el endpoint respondía 200 —así que la pantalla
    # daba el cambio por hecho— y el ticket seguía asignado al recargar. El
    # `model_fields_set` de Pydantic sí separa el campo ausente del campo
    # puesto a null, que es la única forma de expresar "quítaselo a todos".
    asignado_cambio = False
    if "asignado_a" in ticket_in.model_fields_set:
        asignado_cambio = ticket.asignado_a != ticket_in.asignado_a
        ticket.asignado_a = ticket_in.asignado_a
    if ticket_in.canal_resolucion is not None:
        ticket.canal_resolucion = ticket_in.canal_resolucion
    if ticket_in.descripcion_normalizada is not None:
        ticket.descripcion_normalizada = ticket_in.descripcion_normalizada

    db.commit()
    db.refresh(ticket)

    # Indexación en la base de conocimiento. Va después del commit y nunca
    # levanta: si Ollama está caído el ticket queda cerrado igual, solo
    # pendiente de indexar.
    # Bitacora de lo que cambio (spec 12).
    if ticket_in.estado is not None and ticket_in.estado != estado_previo:
        AuditoriaService.registrar(db, current_user, TICKET_ESTADO, "ticket", ticket.id,
                                   AuditoriaService.cambio(estado_previo, ticket.estado), peticion)
    if ticket_in.prioridad is not None and ticket_in.prioridad != prioridad_previa:
        AuditoriaService.registrar(db, current_user, TICKET_PRIORIDAD, "ticket", ticket.id,
                                   AuditoriaService.cambio(prioridad_previa, ticket.prioridad), peticion)
    if asignado_cambio:
        AuditoriaService.registrar(db, current_user, TICKET_ASIGNADO, "ticket", ticket.id,
                                   AuditoriaService.cambio(asignado_previo, ticket.asignado_a), peticion)
    if ticket_in.solucion is not None:
        AuditoriaService.registrar(db, current_user, TICKET_SOLUCION, "ticket", ticket.id,
                                   {"documentada_por_primera_vez": not tenia_solucion}, peticion)

    if se_esta_cerrando:
        # Al worker, si lo hay: indexar es una llamada a Ollama de varios
        # segundos y TI no tiene por qué esperarla con el botón pulsado. Sin
        # cola, aquí mismo, como siempre. El id evita indexar dos veces.
        if not tareas.encolar("indexar_ticket", ticket.id, id_trabajo=f"indexar:{ticket.id}"):
            KBService.indexar_ticket(db, ticket)
            db.refresh(ticket)
        NotificacionesService.ticket_resuelto(db, ticket)

    if asignado_cambio:
        NotificacionesService.ticket_asignado(db, ticket)

    eventos.publicar(ticket.sitio_id, "tickets")
    # Solo TI llega aquí, y TI ve las notas internas; pasa por el mismo filtro
    # que el detalle igualmente, para que la regla no dependa de quién edita.
    return _sin_notas_internas(ticket, current_user)

@router.post("/{ticket_id}/cancelar", response_model=TicketResponse)
def cancelar_ticket(
    ticket_id: int,
    peticion: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Quien reportó el ticket lo retira: ya no necesita que TI lo atienda.

    Lo único que alguien que no es de TI puede cambiar de su ticket, y solo
    mientras siga en la cola: uno resuelto, cerrado o ya cancelado no vuelve
    atrás por aquí.

    **El reloj del SLA se detiene en el acto** —`vence_en` queda vacío—, así
    que el ticket deja de contar como vencido o por vencer en cualquier lado.
    Y no pasa por `resuelto_en`: se guarda en `cancelado_en`, para que no
    entre en el tiempo de resolución ni en la deflexión (ver `MetricasService`).

    **La fila se bloquea antes de mirar el estado.** Medido con diez
    cancelaciones a la vez del mismo ticket: nueve respondían "cancelado" y
    dejaban nueve notas y nueve entradas de bitácora, porque todas leían
    "abierto" antes de que la primera guardara. Con el bloqueo, la segunda ya
    lee "cancelado" y recibe su 409.
    """
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).with_for_update().first()
    if not ticket or not _ticket_visible(ticket, current_user):
        raise HTTPException(status_code=404, detail="Ticket no encontrado.")
    # TI ve los tickets de toda su planta, pero cancelar es retirar la propia
    # petición: el de otra persona se cierra, con su solución.
    if ticket.usuario_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo quien reportó el ticket puede cancelarlo.",
        )
    if ticket.estado in ESTADOS_TERMINADOS:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"El ticket ya está {ticket.estado.replace('_', ' ')}: no se puede cancelar.",
        )

    ahora = datetime.utcnow()
    estado_previo = ticket.estado
    ticket.estado = CANCELADO
    ticket.cancelado_en = ahora
    ticket.vence_en = None
    # A la vista de los dos: TI tiene que saber por qué desapareció de su cola.
    db.add(TicketComentario(
        ticket_id=ticket.id,
        autor_id=current_user.id,
        comentario="[SISTEMA] Quien reportó el ticket lo canceló.",
        es_interno=False,
        creado_en=ahora,
    ))
    db.commit()
    db.refresh(ticket)

    AuditoriaService.registrar(db, current_user, TICKET_CANCELADO, "ticket", ticket.id,
                               AuditoriaService.cambio(estado_previo, CANCELADO), peticion)
    eventos.publicar(ticket.sitio_id, "tickets")
    return _sin_notas_internas(ticket, current_user)


def no_admite_cambios_de_quien_reporta(ticket: Ticket, usuario: Usuario) -> None:
    """Resuelto, cerrado o cancelado, el ticket es de solo lectura para quien
    lo reportó: ni comentarios ni archivos nuevos, ni quitar los que había.

    Quedaba abierto a todo: en un ticket resuelto se podía borrar la foto que
    lo explicaba, y un comentario nuevo avisaba por correo a TI sobre algo que
    ya no está en la cola —nadie lo iba a leer ahí—. Si el problema vuelve, lo
    que corresponde es un ticket nuevo, que sí entra a la cola y tiene SLA.
    TI conserva todo: puede reabrirlo cambiando el estado.
    """
    if usuario.rol != "admin" and ticket.estado in ESTADOS_TERMINADOS:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="Este ticket ya está cerrado y no admite cambios. Si el problema volvió, levante un ticket nuevo.")


@router.post("/{ticket_id}/satisfaccion", response_model=TicketResponse)
def calificar_atencion(
    ticket_id: int,
    datos: SatisfaccionCreate,
    peticion: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """La encuesta de 1 a 5 estrellas al quedar resuelto. Una vez, y solo quien reportó.

    No se califica lo que resolvió el autoservicio —checklist, base de
    conocimiento, asistente, catálogo visual—: ahí no hubo atención de TI que
    medir, y mezclarlo bajaría o subiría el promedio por algo que TI no hizo.

    Una calificación baja (``SATISFACCION_ALERTA_MAXIMA``, 2 por defecto) abre
    una alerta para TI: es la queja que nadie escribe en un comentario.
    """
    # Bloqueada: dos envíos a la vez (doble clic, dos pestañas) no pueden
    # calificar dos veces.
    ticket = (db.query(Ticket).filter(Ticket.id == ticket_id)
              .with_for_update().populate_existing().first())
    if not ticket or not _ticket_visible(ticket, current_user):
        raise HTTPException(status_code=404, detail="Ticket no encontrado.")
    if ticket.usuario_id != current_user.id:
        raise HTTPException(status_code=403,
                            detail="Solo quien reportó el ticket puede calificar la atención.")
    if ticket.estado not in ESTADOS_DE_CIERRE:
        raise HTTPException(status_code=409, detail="Solo se califica un ticket ya resuelto.")
    if ticket.canal_resolucion in CANALES_DEFLECTADOS:
        raise HTTPException(status_code=409,
                            detail="Este ticket se resolvió con autoservicio: no hay atención que calificar.")
    if ticket.satisfaccion is not None:
        raise HTTPException(status_code=409, detail="Este ticket ya fue calificado.")

    ticket.satisfaccion = datos.estrellas
    ticket.satisfaccion_comentario = datos.comentario or None
    ticket.satisfaccion_en = datetime.utcnow()
    db.commit()

    AuditoriaService.registrar(db, current_user, TICKET_CALIFICADO, "ticket", ticket.id,
                               {"estrellas": datos.estrellas}, peticion)
    if datos.estrellas <= settings.SATISFACCION_ALERTA_MAXIMA:
        AlertasService.abrir(
            db, SATISFACCION_BAJA, f"ticket:{ticket.id}",
            f"{ticket.folio}: calificado con {datos.estrellas} de 5",
            detalle=ticket.satisfaccion_comentario,
            datos={"folio": ticket.folio, "estrellas": datos.estrellas},
            sitio_id=ticket.sitio_id, ticket_id=ticket.id)
    eventos.publicar(ticket.sitio_id, "tickets")

    ticket = _con_todo(db.query(Ticket)).filter(Ticket.id == ticket_id).first()
    return _sin_notas_internas(ticket, current_user)


@router.post("/{ticket_id}/comments", response_model=CommentResponse, status_code=status.HTTP_201_CREATED)
def add_comment(
    ticket_id: int,
    comment_in: CommentCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket or not _ticket_visible(ticket, current_user):
        raise HTTPException(status_code=404, detail="Ticket no encontrado.")
    no_admite_cambios_de_quien_reporta(ticket, current_user)

    comment = TicketComentario(
        ticket_id=ticket.id,
        autor_id=current_user.id,
        comentario=comment_in.comentario,
        es_interno=comment_in.es_interno if current_user.rol == "admin" else False,
        creado_en=datetime.utcnow()
    )
    db.add(comment)
    db.commit()
    db.refresh(comment)

    # Las notas internas son para el equipo de TI: al usuario no se le avisan.
    if not comment.es_interno:
        NotificacionesService.comentario_nuevo(db, ticket, current_user, comment.comentario)

    # Tambien las notas internas: quien las ve es el equipo de TI, y el aviso
    # solo dice "vuelve a preguntar" — quien no pueda verlas, no las vera.
    eventos.publicar(ticket.sitio_id, "tickets")
    return comment

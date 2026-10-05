from datetime import datetime
from sqlalchemy import (
    CheckConstraint, Column, Integer, String, Boolean, DateTime, Text, ForeignKey, Float, JSON,
    Index, Table, UniqueConstraint, text, BigInteger, SmallInteger, CHAR, func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from pgvector.sqlalchemy import Vector
from app.core.db import Base

# jsonb en Postgres, json genérico en SQLite (pruebas).
JSONFlexible = JSON().with_variant(JSONB, "postgresql")

class Sitio(Base):
    __tablename__ = "sitios"

    id = Column(Integer, primary_key=True)
    clave = Column(String(10), unique=True, index=True, nullable=False)
    nombre = Column(String(100), nullable=False)
    pais = Column(String(50), nullable=False, default="México")
    activo = Column(Boolean, default=True)

    usuarios = relationship("Usuario", back_populates="sitio")
    equipos = relationship("Equipo", back_populates="sitio")
    tickets = relationship("Ticket", back_populates="sitio")
    reglas = relationship("ReglaNegocio", back_populates="sitio")

#: **Las plantas de cada persona.** Una persona de planta puede trabajar en una
#: o en varias —quien cubre dos turnos en dos naves, un supervisor regional—, y
#: ve los equipos y levanta tickets de todas las suyas. TI no aparece aquí: su
#: alcance es global por rol, no por asignación (ver `app/core/plantas.py`).
usuario_sitios = Table(
    "usuario_sitios",
    Base.metadata,
    Column("usuario_id", Integer, ForeignKey("usuarios.id", ondelete="CASCADE"), primary_key=True),
    Column("sitio_id", Integer, ForeignKey("sitios.id"), primary_key=True),
)


class Usuario(Base):
    __tablename__ = "usuarios"

    id = Column(Integer, primary_key=True)
    # La planta **principal**: la que se propone al levantar un ticket y la que
    # dice la barra. Las demás están en `plantas`. Vacía para TI, que no tiene
    # una: atiende a todas (migración 0025).
    sitio_id = Column(Integer, ForeignKey("sitios.id"), nullable=True)
    # Identificador principal. En planta no todo el mundo tiene correo
    # corporativo —un operador de línea normalmente no— pero **todos** tienen
    # número de empleado. Hacer del correo la llave dejaría fuera a la mayoría.
    numero_empleado = Column(String(20), unique=True, index=True, nullable=True)
    nombre = Column(String(100), nullable=False)
    # Opcional a propósito: sin correo la cuenta funciona igual, solo que esa
    # persona no recibe avisos.
    email = Column(String(100), unique=True, index=True, nullable=True)
    rol = Column(String(20), nullable=False, default="usuario") # admin, usuario
    area = Column(String(50), nullable=True)
    # Datos de verificación para la activación masiva: algo que la persona
    # sabe y que no está a la vista de sus compañeros.
    #
    # La de **nacimiento** es la que se usa en la práctica: buena parte de la
    # plantilla lleva años aquí y no se acuerda de en qué mes entró, pero de su
    # cumpleaños se acuerda todo el mundo. La de ingreso queda como alternativa.
    #
    # El de EPP son los cuatro dígitos con los que la persona saca su equipo de
    # protección. Lo usa seguido, así que se lo sabe; y como no está impreso en
    # el gafete, no basta con ver a alguien de lejos para conocerlo. Sin índice
    # único a propósito: es un dato de verificación, no una llave de acceso.
    numero_epp = Column(String(10), nullable=True)
    fecha_nacimiento = Column(DateTime, nullable=True)
    fecha_ingreso = Column(DateTime, nullable=True)
    idioma_preferido = Column(String(5), default="es")
    activo = Column(Boolean, default=True)
    # Vacío mientras la cuenta no se ha activado: TI da de alta a la persona
    # sin conocer nunca su contraseña.
    password_hash = Column(String(255), nullable=True)

    # pendiente_activacion | activa | bloqueada
    estado_cuenta = Column(String(25), default="pendiente_activacion", nullable=False, index=True)
    # Hash del código de un solo uso que TI le entrega a la persona. Se guarda
    # hasheado por lo mismo que una contraseña: quien lea la base no debe poder
    # activar cuentas ajenas.
    codigo_activacion_hash = Column(String(255), nullable=True)
    codigo_expira = Column(DateTime, nullable=True)
    # Se marca cuando TI restablece la contraseña: la temporal sirve una vez.
    debe_cambiar_password = Column(Boolean, default=False, nullable=False)
    # Sube cada vez que hay que echar fuera a quien estuviera dentro: cambio de
    # contraseña, restablecimiento, activación asistida. El número viaja dentro
    # del token, así que subirlo invalida de golpe todo lo emitido antes. Sin
    # esto, un token robado seguía sirviendo sus ocho horas aunque la persona
    # cambiara la contraseña.
    version_token = Column(Integer, default=1, nullable=False, server_default="1")
    # Activaciones fallidas seguidas. A los cinco se cierra la via de los datos
    # personales para esta cuenta y solo entra con un codigo de TI: es lo que
    # convierte "adivinar un cumpleaños" en algo con probabilidad despreciable.
    intentos_activacion = Column(Integer, default=0, nullable=False, server_default="0")
    verificacion_bloqueada = Column(Boolean, default=False, nullable=False,
                                    server_default=text("false"))
    # **Eliminación definitiva: se marca, no se borra la fila.**
    #
    # Diecinueve columnas de otras tablas apuntan a `usuarios.id`, y once son
    # `NOT NULL`: los tickets que levantó, los comentarios que escribió, los
    # resguardos que firmó, los documentos que subió. Un `DELETE` de verdad
    # obliga a elegir entre arrastrar todo eso o dejar la base rota, y las dos
    # cosas contradicen lo que se pide de esta operación: que el historial
    # quede intacto.
    #
    # Así que se vacía la cuenta —contraseña, código, correo, número de
    # empleado, datos de verificación— y se marca aquí. Queda el nombre, que
    # es lo que hace legible el historial: un ticket "reportado por" nadie no
    # le sirve a quien lo lea dentro de un año. La persona desaparece de todas
    # las listas y selectores, su número de empleado queda libre para otra
    # alta, y no hay forma de volver a entrar con esa cuenta.
    eliminado_en = Column(DateTime, nullable=True, index=True)
    # **Términos y Condiciones** (migración 0031): la versión que aceptó y
    # cuándo. Vacíos hasta que acepta; con una versión vieja, también le toca
    # aceptar la nueva (ver `terminos_vigentes`). La constancia completa —IP y
    # huella del texto que vio— queda en la bitácora, no aquí.
    terminos_version = Column(String(20), nullable=True)
    terminos_aceptados_en = Column(DateTime, nullable=True)
    # **Si puede pedir prioridad alta o crítica al levantar un ticket.** Quien
    # reporta indica la urgencia inicial —la conoce mejor que nadie—, pero es
    # la única palanca que tiene sobre la cola de TI y se puede abusar de ella.
    # TI la revoca desde Personas; con ella revocada, el ticket nace en
    # "media" aunque se pida más (ver `create_ticket`). No toca a TI.
    puede_usar_prioridad_alta = Column(Boolean, default=True, nullable=False,
                                       server_default=text("true"))

    ultimo_acceso = Column(DateTime, nullable=True)
    creado_en = Column(DateTime, default=datetime.utcnow)

    sitio = relationship("Sitio", back_populates="usuarios")
    plantas = relationship("Sitio", secondary=usuario_sitios, lazy="selectin",
                           order_by="Sitio.nombre")
    tickets_creados = relationship("Ticket", foreign_keys="Ticket.usuario_id", back_populates="usuario")
    tickets_asignados = relationship("Ticket", foreign_keys="Ticket.asignado_a", back_populates="asignado_usuario")
    equipos = relationship("Equipo", back_populates="asignado_usuario")

    @property
    def terminos_vigentes(self) -> bool:
        """Si aceptó la versión vigente de los Términos y Condiciones.

        Mientras no, la API le responde 403 `terminos_pendientes` a todo salvo
        a su sesión y a los términos (ver `get_current_user`).
        """
        from app.core import terminos
        return bool(self.terminos_version) and self.terminos_version == terminos.version_vigente()

    @property
    def sitio_nombre(self):
        """La planta de esta persona, para decirla en pantalla.

        Estaba escrita en las traducciones —"Planta Querétaro"—, así que quien
        entrara desde otra planta leía la de Querétaro en la barra y en los
        avisos. Sale de aquí para que la diga la base, no el frontend.
        """
        return self.sitio.nombre if self.sitio else None

    @property
    def es_ti_global(self) -> bool:
        """TI atiende a todas las plantas: su alcance es por rol."""
        return self.rol == "admin"

    @property
    def plantas_ids(self):
        """Las plantas que alcanza esta persona, o None si alcanza todas (TI)."""
        if self.es_ti_global:
            return None
        ids = {p.id for p in self.plantas}
        if self.sitio_id:
            ids.add(self.sitio_id)
        return ids

    @property
    def plantas_resumen(self):
        """Para la API: id, clave y nombre de cada planta de la persona."""
        return [{"id": p.id, "clave": p.clave, "nombre": p.nombre} for p in self.plantas]

class Equipo(Base):
    __tablename__ = "equipos"

    id = Column(Integer, primary_key=True)
    sitio_id = Column(Integer, ForeignKey("sitios.id"), nullable=False)
    tipo = Column(String(20), nullable=False) # activo, pasivo, consumible
    categoria = Column(String(50), nullable=False)
    marca = Column(String(50), nullable=False)
    modelo = Column(String(50), nullable=False)
    numero_serie = Column(String(100), nullable=True, index=True)
    ubicacion = Column(String(100), nullable=True)
    estado = Column(String(20), default="disponible") # disponible, asignado, mantenimiento, baja
    asignado_a = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    fecha_asignacion = Column(DateTime, nullable=True)
    notas = Column(Text, nullable=True)

    sitio = relationship("Sitio", back_populates="equipos")
    asignado_usuario = relationship("Usuario", back_populates="equipos")
    tickets = relationship("Ticket", back_populates="equipo")
    resguardos = relationship("Resguardo", back_populates="equipo")
    movimientos = relationship("MovimientoEquipo", back_populates="equipo", order_by="MovimientoEquipo.creado_en.desc()")

class Ticket(Base):
    __tablename__ = "tickets"

    id = Column(Integer, primary_key=True)
    sitio_id = Column(Integer, ForeignKey("sitios.id"), nullable=False)
    folio = Column(String(30), unique=True, index=True, nullable=False)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    equipo_id = Column(Integer, ForeignKey("equipos.id"), nullable=True)
    categoria = Column(String(50), nullable=False) # impresora, red, equipo, software, accesos, otro
    subcategoria = Column(String(50), nullable=True)
    descripcion_original = Column(Text, nullable=False)
    descripcion_normalizada = Column(Text, nullable=True)
    prioridad = Column(String(20), default="media") # baja, media, alta, critica
    estado = Column(String(30), default="abierto") # abierto, en_proceso, espera_proveedor, resuelto, cerrado, cancelado
    asignado_a = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    canal_resolucion = Column(String(30), nullable=True) # checklist, kb, ia, tecnico, proveedor
    # Obligatorio al pasar a resuelto/cerrado. Se valida en la API, no en la BD,
    # porque los tickets anteriores a este campo no la tienen.
    solucion = Column(Text, nullable=True)
    # Lo que se probó y NO era. Media hora de un técnico se va en repetir lo que
    # alguien ya descartó; guardarlo se la ahorra al siguiente.
    descartado = Column(Text, nullable=True)
    indexado_kb = Column(Boolean, default=False, nullable=False)
    creado_en = Column(DateTime, default=datetime.utcnow)
    resuelto_en = Column(DateTime, nullable=True)
    tiempo_resolucion = Column(Integer, nullable=True) # in minutes
    # Cuándo vence el SLA, contando solo horas hábiles. Un ticket abierto el
    # viernes a las 16:50 vence el lunes, no el sábado de madrugada.
    vence_en = Column(DateTime, nullable=True)
    # Se levantó cuando no había personal de TI. Sirve para no culpar al equipo
    # de un tiempo de respuesta que empezó a correr a las 2 de la mañana.
    fuera_horario = Column(Boolean, default=False, nullable=False)
    # Cuándo lo retiró quien lo reportó. Va aparte de `resuelto_en` a
    # propósito: un ticket cancelado no se resolvió, y mezclarlos inflaría el
    # tiempo de resolución y la tasa de deflexión con incidencias que nadie
    # atendió.
    cancelado_en = Column(DateTime, nullable=True)
    # Clave que manda el formulario en cada intento de envío: si la red se
    # corta después de crear el ticket, el reintento devuelve este mismo en
    # vez de crear otro. Única por persona, solo cuando viene (migración 0024).
    clave_envio = Column(String(64), nullable=True)
    # Encuesta al resolverse: de 1 a 5 estrellas y, si quiere, un comentario.
    # La responde solo quien reportó, una vez (migración 0026).
    satisfaccion = Column(Integer, nullable=True)
    satisfaccion_comentario = Column(Text, nullable=True)
    satisfaccion_en = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("ux_tickets_usuario_clave_envio", "usuario_id", "clave_envio", unique=True,
              postgresql_where=text("clave_envio IS NOT NULL"),
              sqlite_where=text("clave_envio IS NOT NULL")),
        # Ya existía en la base (migración 0026) y faltaba aquí: un
        # `--autogenerate` la habría propuesto como "sobrante" y borrado.
        CheckConstraint("satisfaccion IS NULL OR satisfaccion BETWEEN 1 AND 5",
                        name="ck_tickets_satisfaccion_1_a_5"),
    )

    sitio = relationship("Sitio", back_populates="tickets")
    usuario = relationship("Usuario", foreign_keys=[usuario_id], back_populates="tickets_creados")
    asignado_usuario = relationship("Usuario", foreign_keys=[asignado_a], back_populates="tickets_asignados")
    equipo = relationship("Equipo", back_populates="tickets")
    comentarios = relationship("TicketComentario", back_populates="ticket", cascade="all, delete-orphan")
    adjuntos = relationship("TicketAdjunto", back_populates="ticket", cascade="all, delete-orphan")
    # Las capturas con que TI explica cómo lo resolvió. No son `adjuntos`: esos
    # los sube quien reporta para contar el problema; éstas cuentan el arreglo.
    # Ver `ImagenConocimiento`.
    imagenes_solucion = relationship(
        "ImagenConocimiento", order_by="ImagenConocimiento.orden",
        cascade="all, delete-orphan", passive_deletes=True)

#: Estados en los que un ticket ya no está en la cola de nadie. Cuentan para
#: "tickets abiertos" de una persona, la carta de no adeudo y el historial
#: de un equipo: cualquier cosa que no esté aquí es trabajo pendiente.
ESTADOS_TERMINADOS = ("resuelto", "cerrado", "cancelado")
#: Lo retiró quien lo reportó. No es una resolución: ver `Ticket.cancelado_en`.
CANCELADO = "cancelado"
#: Las que se pueden revocar a quien abusa de ellas (`puede_usar_prioridad_alta`).
PRIORIDADES_ALTAS = ("alta", "critica")


class TicketComentario(Base):
    __tablename__ = "ticket_comentarios"

    id = Column(Integer, primary_key=True)
    ticket_id = Column(Integer, ForeignKey("tickets.id"), nullable=False)
    autor_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    comentario = Column(Text, nullable=False)
    es_interno = Column(Boolean, default=False)
    creado_en = Column(DateTime, default=datetime.utcnow)

    ticket = relationship("Ticket", back_populates="comentarios")
    autor = relationship("Usuario")

class TicketAdjunto(Base):
    """Foto o archivo asociado a un ticket.

    Los binarios viven en disco, no en la base: una foto de teléfono son varios
    MB y meterlos en Postgres infla los respaldos sin ganar nada. La fila solo
    guarda dónde está y qué es.
    """
    __tablename__ = "ticket_adjuntos"

    id = Column(Integer, primary_key=True)
    ticket_id = Column(Integer, ForeignKey("tickets.id"), nullable=False)
    subido_por = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    nombre_original = Column(String(255), nullable=False)
    nombre_guardado = Column(String(255), nullable=False, unique=True)
    tipo_mime = Column(String(100), nullable=False)
    tamano_bytes = Column(Integer, nullable=False)
    creado_en = Column(DateTime, default=datetime.utcnow)

    ticket = relationship("Ticket", back_populates="adjuntos")
    autor = relationship("Usuario")

class Resguardo(Base):
    """Constancia de que una persona recibió un equipo y responde por él.

    No es un archivo suelto: es un documento con folio, condiciones aceptadas y
    constancia de quién firmó, cuándo y desde dónde. Cuando el equipo se
    devuelve, el resguardo se cierra pero **no se borra**: es el historial de
    responsabilidad del activo, y en una auditoría es lo primero que piden.

    Ciclo de vida:
        borrador -> pendiente_firma -> firmado -> devuelto
                                    \\-> cancelado
    """
    __tablename__ = "resguardos"

    id = Column(Integer, primary_key=True)
    folio = Column(String(30), unique=True, nullable=False)
    sitio_id = Column(Integer, ForeignKey("sitios.id"), nullable=False, index=True)
    # Quien resguarda el equipo.
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False, index=True)
    equipo_id = Column(Integer, ForeignKey("equipos.id"), nullable=False, index=True)
    # Quien lo emitió, del equipo de TI.
    creado_por = Column(Integer, ForeignKey("usuarios.id"), nullable=False)

    estado = Column(String(20), default="pendiente_firma", nullable=False, index=True)

    # Texto de las condiciones tal como estaban al firmar. Se guarda copia y no
    # una referencia: si mañana cambian las condiciones, lo que la persona
    # aceptó no puede cambiar de forma retroactiva.
    condiciones = Column(Text, nullable=False)
    accesorios = Column(Text, nullable=True)
    observaciones_entrega = Column(Text, nullable=True)
    observaciones_devolucion = Column(Text, nullable=True)

    entregado_en = Column(DateTime, nullable=True)
    firmado_en = Column(DateTime, nullable=True)
    # Constancia de la aceptación: nombre tecleado, IP y momento.
    firma_nombre = Column(String(150), nullable=True)
    firma_ip = Column(String(45), nullable=True)

    devuelto_en = Column(DateTime, nullable=True)
    recibido_por = Column(Integer, ForeignKey("usuarios.id"), nullable=True)

    creado_en = Column(DateTime, default=datetime.utcnow)

    sitio = relationship("Sitio")
    usuario = relationship("Usuario", foreign_keys=[usuario_id])
    emisor = relationship("Usuario", foreign_keys=[creado_por])
    receptor = relationship("Usuario", foreign_keys=[recibido_por])
    equipo = relationship("Equipo", back_populates="resguardos")
    documentos = relationship("DocumentoUsuario", back_populates="resguardo")

class MovimientoEquipo(Base):
    """Bitácora de vida de un activo: quién lo tuvo y por qué cambió de manos.

    El campo `asignado_a` del equipo dice dónde está *hoy*. Esto dice dónde
    estuvo. Sin el historial, un equipo que rota entre cinco personas en un año
    no deja rastro de por dónde pasó.
    """
    __tablename__ = "movimientos_equipo"

    id = Column(Integer, primary_key=True)
    equipo_id = Column(Integer, ForeignKey("equipos.id"), nullable=False, index=True)
    # alta | asignacion | devolucion | mantenimiento | baja | traslado
    tipo = Column(String(20), nullable=False, index=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    resguardo_id = Column(Integer, ForeignKey("resguardos.id"), nullable=True)
    estado_anterior = Column(String(20), nullable=True)
    estado_nuevo = Column(String(20), nullable=True)
    nota = Column(Text, nullable=True)
    realizado_por = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    creado_en = Column(DateTime, default=datetime.utcnow, index=True)

    equipo = relationship("Equipo", back_populates="movimientos")
    usuario = relationship("Usuario", foreign_keys=[usuario_id])
    autor = relationship("Usuario", foreign_keys=[realizado_por])

class DocumentoUsuario(Base):
    """Expediente de una persona: resguardos firmados, responsivas, políticas.

    Los binarios van a disco igual que los adjuntos de tickets. Un documento
    puede colgar de un resguardo (el PDF firmado escaneado) o vivir suelto
    (una carta responsiva, una política aceptada).
    """
    __tablename__ = "documentos_usuario"

    id = Column(Integer, primary_key=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False, index=True)
    # La planta principal de la persona; vacía si es de TI.
    sitio_id = Column(Integer, ForeignKey("sitios.id"), nullable=True)
    # resguardo | responsiva | politica | contrato | identificacion | otro
    tipo = Column(String(30), nullable=False, index=True)
    titulo = Column(String(200), nullable=False)
    descripcion = Column(Text, nullable=True)
    resguardo_id = Column(Integer, ForeignKey("resguardos.id"), nullable=True)

    nombre_original = Column(String(255), nullable=False)
    nombre_guardado = Column(String(255), nullable=False, unique=True)
    tipo_mime = Column(String(100), nullable=False)
    tamano_bytes = Column(Integer, nullable=False)

    # Para documentos que caducan (una política que se firma cada año).
    vigente_hasta = Column(DateTime, nullable=True)
    subido_por = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    creado_en = Column(DateTime, default=datetime.utcnow)

    usuario = relationship("Usuario", foreign_keys=[usuario_id])
    autor = relationship("Usuario", foreign_keys=[subido_por])
    resguardo = relationship("Resguardo", back_populates="documentos")

class BaseConocimiento(Base):
    __tablename__ = "base_conocimiento"

    id = Column(Integer, primary_key=True)
    # Planta de origen, o vacía si es general. El conocimiento se comparte entre plantas: TI es una sola.
    sitio_id = Column(Integer, ForeignKey("sitios.id"), nullable=True)
    titulo = Column(String(150), nullable=False)
    contenido = Column(Text, nullable=False)
    categoria = Column(String(50), nullable=False)
    tags = Column(String(200), nullable=True)
    # Se arrastra del ticket de origen: el asistente lo cita para que nadie
    # repita lo que ya se descartó.
    descartado = Column(Text, nullable=True)
    embedding = Column(Vector(768), nullable=True)
    ticket_origen_id = Column(Integer, ForeignKey("tickets.id"), nullable=True)
    # Contadores de utilidad. veces_util / veces_sugerida es la métrica que calibra el umbral.
    veces_sugerida = Column(Integer, default=0, nullable=False)
    veces_util = Column(Integer, default=0, nullable=False)
    ultima_sugerencia = Column(DateTime, nullable=True)
    creado_en = Column(DateTime, default=datetime.utcnow)

    imagenes = relationship(
        "ImagenConocimiento", order_by="ImagenConocimiento.orden",
        cascade="all, delete-orphan", passive_deletes=True)
    ticket_origen = relationship("Ticket", foreign_keys=[ticket_origen_id])

    @property
    def imagenes_de_ticket(self):
        """Las capturas de la solución del ticket del que salió esta entrada.

        **Enlazadas, no copiadas.** La entrada se crea en el worker, que no
        monta el volumen de archivos, y las capturas del cierre se suben
        justo después de guardar la solución: una copia dependería de quién
        llega primero. Enlazadas no hay carrera ni duplicados, y si TI corrige
        una captura en el ticket, se corrige también aquí.
        """
        return list(self.ticket_origen.imagenes_solucion) if self.ticket_origen else []

class SugerenciaKB(Base):
    """Una fila por sugerencia mostrada al usuario. fue_util queda en NULL
    hasta que responde el botón de '¿te sirvió?'."""
    __tablename__ = "sugerencias_kb"

    id = Column(Integer, primary_key=True)
    ticket_id = Column(Integer, ForeignKey("tickets.id"), nullable=True)
    kb_id = Column(Integer, ForeignKey("base_conocimiento.id"), nullable=False)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    similitud = Column(Float, nullable=False)
    fue_util = Column(Boolean, nullable=True)
    creado_en = Column(DateTime, default=datetime.utcnow)

    kb = relationship("BaseConocimiento")

class Checklist(Base):
    """Un paso de diagnóstico dentro de una categoría.

    `pregunta_key` guarda una llave de traducción cuando el paso viene sembrado
    (así funciona en los tres idiomas). Los pasos que crea el admin desde el
    portal guardan el texto directo en `pregunta_texto`, porque no hay forma de
    pedirle a alguien que escriba en tres idiomas cada vez.
    """
    __tablename__ = "checklists"

    id = Column(Integer, primary_key=True)
    categoria = Column(String(50), nullable=False)
    orden = Column(Integer, default=1)
    pregunta_key = Column(String(100), nullable=False)
    pregunta_texto = Column(Text, nullable=True)
    accion_si_no = Column(Text, nullable=True)
    resuelve = Column(Boolean, default=False)
    activo = Column(Boolean, default=True, nullable=False)
    # Cuántas veces este paso concreto resolvió la incidencia. Le dice al admin
    # qué pasos sirven y cuáles solo estorban.
    veces_resolvio = Column(Integer, default=0, nullable=False)
    creado_en = Column(DateTime, default=datetime.utcnow)

    imagenes = relationship(
        "ImagenConocimiento", order_by="ImagenConocimiento.orden",
        cascade="all, delete-orphan", passive_deletes=True)

class TemaSugerido(Base):
    """Un problema recurrente que el portal todavía no tiene contemplado.

    Cuando alguien reporta algo que no encaja en las categorías, se agrupa por
    similitud con lo ya reportado. Si el mismo problema aparece varias veces,
    deja de ser un caso suelto y se le propone al admin convertirlo en tema con
    su propio checklist.
    """
    __tablename__ = "temas_sugeridos"

    id = Column(Integer, primary_key=True)
    sitio_id = Column(Integer, ForeignKey("sitios.id"), nullable=False)
    titulo = Column(String(200), nullable=False)
    descripcion_ejemplo = Column(Text, nullable=False)
    categoria_sugerida = Column(String(50), nullable=True)
    embedding = Column(Vector(768), nullable=True)
    ocurrencias = Column(Integer, default=1, nullable=False)
    # pendiente = aún no llega al umbral | listo = ya se puede promover
    # promovido = el admin lo convirtió en tema | descartado = no aplica
    estado = Column(String(20), default="pendiente", nullable=False)
    primera_vez = Column(DateTime, default=datetime.utcnow)
    ultima_vez = Column(DateTime, default=datetime.utcnow)

class ReglaNegocio(Base):
    __tablename__ = "reglas_negocio"

    id = Column(Integer, primary_key=True)
    sitio_id = Column(Integer, ForeignKey("sitios.id"), nullable=False)
    categoria = Column(String(50), nullable=False)
    condicion = Column(String(100), nullable=False)
    accion = Column(String(30), nullable=False) # proveedor, escalar, auto
    destinatario = Column(String(100), nullable=True)
    activa = Column(Boolean, default=True)

    sitio = relationship("Sitio", back_populates="reglas")

class ChatSesion(Base):
    """Una conversación del chatbot flotante.

    El contexto vive dentro de la sesión y no se comparte entre incidencias
    distintas: cada incidencia nueva abre una sesión nueva.
    """
    __tablename__ = "chat_sesiones"

    id = Column(Integer, primary_key=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    ticket_id = Column(Integer, ForeignKey("tickets.id"), nullable=True)
    categoria_detectada = Column(String(50), nullable=True)
    confianza = Column(Float, nullable=True)
    # [{"rol": "usuario"|"asistente", "texto": ..., "creado_en": ...}, ...]
    mensajes = Column(JSONFlexible, nullable=False, default=list)
    cerrada = Column(Boolean, default=False, nullable=False)
    creado_en = Column(DateTime, default=datetime.utcnow)

    usuario = relationship("Usuario")

class SolucionGeneral(Base):
    """Un procedimiento consolidado a partir de varios tickets del mismo problema.

    Diez tickets sobre la misma impresora dejan diez soluciones parecidas y
    ninguna completa. Esto es el paso siguiente: qué revisar primero, qué suele
    ser, qué ya se descartó.

    **El borrador lo escribe la máquina; la publicación la firma una persona.**
    Mientras es borrador no tiene embedding y por lo tanto no aparece en ninguna
    búsqueda: un procedimiento sin revisar no debería contestarle a nadie.
    """
    __tablename__ = "soluciones_generales"

    id = Column(Integer, primary_key=True)
    # Planta de origen, o vacía si es general. El conocimiento se comparte entre plantas: TI es una sola.
    sitio_id = Column(Integer, ForeignKey("sitios.id"), nullable=True, index=True)
    titulo = Column(String(200), nullable=False)
    categoria = Column(String(50), nullable=True)
    contenido = Column(Text, nullable=False)
    descartado = Column(Text, nullable=True)
    # borrador | publicada | archivada
    estado = Column(String(20), default="borrador", nullable=False, index=True)
    # De cuántos tickets salió: es lo que dice si vale la pena leerla.
    tickets_origen = Column(Integer, default=0, nullable=False)
    redactada_por = Column(String(20), nullable=True)   # gemini | ollama | persona
    revisada_por = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    embedding = Column(Vector(768), nullable=True)
    veces_sugerida = Column(Integer, default=0, nullable=False)
    veces_util = Column(Integer, default=0, nullable=False)
    creado_en = Column(DateTime, default=datetime.utcnow)
    publicado_en = Column(DateTime, nullable=True)

    imagenes = relationship(
        "ImagenConocimiento", order_by="ImagenConocimiento.orden",
        cascade="all, delete-orphan", passive_deletes=True)


class DocumentoTI(Base):
    """Documentación operativa interna del área de TI.

    Procedimientos, direccionamiento IP, VLANs, credenciales de servicios,
    contactos de proveedor. Lo que hoy vive en la cabeza de dos personas y en
    un Excel que nadie encuentra.

    **Nunca es visible para usuarios normales.** Es el único contenido del
    portal con ese nivel de restricción, y por eso `sensible` marca lo que
    además conviene no dejar a la vista en un listado.
    """
    __tablename__ = "documentos_ti"

    id = Column(Integer, primary_key=True)
    # Planta de origen, o vacía si es general. El conocimiento se comparte entre plantas: TI es una sola.
    sitio_id = Column(Integer, ForeignKey("sitios.id"), nullable=True, index=True)
    # procedimiento | red | inventario_logico | proveedor | credenciales | otro
    categoria = Column(String(40), nullable=False, index=True)
    titulo = Column(String(200), nullable=False)
    contenido = Column(Text, nullable=False)
    etiquetas = Column(String(300), nullable=True)
    # Marca lo que no debe leerse de reojo por encima del hombro.
    sensible = Column(Boolean, default=False, nullable=False)
    # Búsqueda por similitud dentro de la documentación de TI.
    embedding = Column(Vector(768), nullable=True)
    creado_por = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    actualizado_por = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    creado_en = Column(DateTime, default=datetime.utcnow)
    actualizado_en = Column(DateTime, nullable=True)

    autor = relationship("Usuario", foreign_keys=[creado_por])
    editor = relationship("Usuario", foreign_keys=[actualizado_por])

class FichaVisual(Base):
    """Un problema que se reconoce mirándolo, con la foto de cómo se ve.

    **Por qué no basta con la base de conocimiento.** Un ticket cuenta lo que
    pasó y una solución general cuenta qué hacer; las dos están escritas en
    prosa y las dos sirven cuando el problema se puede *nombrar*. Pero una copia
    borrosa, una copia con sombra doble y una copia con una raya fina se
    describen las tres igual —"sale mal"— y se arreglan de tres maneras
    distintas. Ahí el texto no separa nada. La foto sí.

    Así que el orden se invierte: en vez de contestar, el portal **enseña y
    pregunta**. Muestra las fotos de los defectos que se parecen a lo que la
    persona escribió y le deja señalar el suyo. Lo que devuelve después es la
    solución atada a la foto que esa persona eligió, no la que el parecido de
    texto creyó más probable.

    **Ningún modelo mira las fotos.** La imagen no se interpreta: la etiqueta
    quien la sube, que es quien estuvo delante de la impresora. Lo único que
    hace el modelo es emparejar el texto del usuario con el texto que TI
    escribió en `sintoma` y `frases`. Un modelo de visión aquí solo añadiría
    una forma nueva de equivocarse sobre algo que ya estaba escrito.

    `frases` es cómo lo dice la gente, y no es decoración: además de mejorar la
    búsqueda, **es lo que enseña al disparador a reconocer problemas visuales
    que nadie previó en el código**. Ver `visual_service.py`.
    """
    __tablename__ = "fichas_visuales"

    id = Column(Integer, primary_key=True)
    # Planta de origen, o vacía si es general. El conocimiento se comparte entre plantas: TI es una sola.
    sitio_id = Column(Integer, ForeignKey("sitios.id"), nullable=True, index=True)
    categoria = Column(String(50), nullable=True, index=True)
    titulo = Column(String(200), nullable=False)
    # Cómo se ve el defecto, descrito por TI. Es lo que se compara contra lo
    # que escribe el usuario.
    sintoma = Column(Text, nullable=False)
    # Cómo lo dice la gente, separado por comas: "sale borroso", "se ve
    # despintado", "queda tenue".
    frases = Column(Text, nullable=True)
    # Qué hacer cuando es ésta. Las fotos con rol "solucion" son los pasos que
    # no se pueden explicar por escrito: dónde hay que picar.
    solucion = Column(Text, nullable=False)
    # Lo que ya se probó y no era, igual que en el resto del conocimiento.
    descartado = Column(Text, nullable=True)

    # borrador | publicada | archivada. Un borrador no se le enseña a nadie:
    # sin embedding no aparece en ninguna búsqueda.
    estado = Column(String(20), default="borrador", nullable=False, index=True)
    embedding = Column(Vector(768), nullable=True)

    # Las cuatro cuentan la historia completa de una ficha, y hacen falta las
    # cuatro porque separan dos fallos que piden dos arreglos distintos:
    #
    #   mostrada  -> se ofreció
    #   confirmada-> alguien dijo "sí, es ésta" mirando la foto
    #   descartada-> dijo que no era ninguna de las que se le enseñaron
    #   resuelta  -> además, la solución le funcionó
    #
    # `confirmada / mostrada` dice si la **foto** está bien elegida.
    # `resuelta / confirmada` dice si la **solución** está bien escrita. Sin la
    # última, una ficha puede lucir un 90 % de reconocimiento mientras manda a
    # todo el mundo a hacer algo que no arregla nada.
    veces_mostrada = Column(Integer, default=0, nullable=False)
    veces_confirmada = Column(Integer, default=0, nullable=False)
    veces_descartada = Column(Integer, default=0, nullable=False)
    veces_resuelta = Column(Integer, default=0, nullable=False, server_default="0")

    # De qué ticket salió, cuando salió de uno. Las fotos del problema ya
    # existen —la gente las adjunta a sus tickets— y volver a pedirlas para
    # documentar el mismo defecto es pedir dos veces un trabajo ya hecho.
    ticket_origen_id = Column(Integer, ForeignKey("tickets.id"), nullable=True)

    creado_por = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    actualizado_por = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    creado_en = Column(DateTime, default=datetime.utcnow)
    actualizado_en = Column(DateTime, nullable=True)

    autor = relationship("Usuario", foreign_keys=[creado_por])
    editor = relationship("Usuario", foreign_keys=[actualizado_por])
    imagenes = relationship(
        "ImagenFicha",
        back_populates="ficha",
        cascade="all, delete-orphan",
        order_by="ImagenFicha.orden",
    )


class ImagenFicha(Base):
    """Una foto de una ficha visual: o el defecto, o dónde hay que picar.

    `rol` es lo que separa las dos mitades de la pantalla, y las dos hacen
    falta:

      - **sintoma**  — cómo se ve el problema. Es la que se enseña para
        preguntar "¿es esto lo que le pasa?".
      - **solucion** — dónde está el botón, qué casilla hay que destildar, qué
        palanca se levanta. Hay problemas que se arreglan con dos clics y
        explicarlos por escrito cuesta un párrafo que nadie sigue; señalados
        sobre la captura, cuestan una mirada.

    El binario va a disco, como los adjuntos de tickets y los documentos del
    expediente. La fila solo guarda dónde está y qué es.
    """
    __tablename__ = "imagenes_ficha"

    id = Column(Integer, primary_key=True)
    ficha_id = Column(Integer, ForeignKey("fichas_visuales.id"), nullable=False, index=True)
    # sintoma | solucion
    rol = Column(String(20), nullable=False, default="sintoma")
    orden = Column(Integer, default=1, nullable=False)
    # El pie de foto. En las de solución es el paso: "destilde 'Ahorro de
    # tóner' y acepte".
    pie = Column(String(300), nullable=True)

    nombre_original = Column(String(255), nullable=False)
    nombre_guardado = Column(String(255), nullable=False, unique=True)
    tipo_mime = Column(String(100), nullable=False)
    tamano_bytes = Column(Integer, nullable=False)
    subido_por = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    creado_en = Column(DateTime, default=datetime.utcnow)

    ficha = relationship("FichaVisual", back_populates="imagenes")
    autor = relationship("Usuario")


class ImagenConocimiento(Base):
    """Una captura o foto que acompaña a un texto del conocimiento.

    **Para qué.** Los pasos de diagnóstico, las entradas de la base de
    conocimiento y la solución de un ticket eran texto puro. "Pulse el botón de
    reinicio de la parte trasera" obliga a buscar un botón; con la foto de dónde
    está, se pulsa a la primera. Y la solución de un ticket es lo que la
    persona abre para ver cómo le arreglaron su problema: una captura de la
    configuración que se cambió dice más que el párrafo que la describe.

    **Por qué una tabla y no cuatro.** Pasos, entradas, soluciones de ticket
    y procedimientos de Soluciones generales guardan lo mismo —un archivo, su
    pie de foto y su orden— y se suben, se validan y se sirven igual. Lo
    único que cambia es a quién pertenecen, y eso lo dicen columnas con llave
    foránea de verdad en vez de un par "tipo + id" que la base no podría
    comprobar. La restricción de abajo exige que haya exactamente una.

    **Por qué no son `ImagenFicha`.** Una ficha visual pregunta con la foto
    ("¿se ve así?") y su imagen tiene dos papeles; aquí la imagen solo ilustra
    un texto que ya contesta. Mezclarlas obligaría a cada consulta de fichas a
    saltarse las que no son suyas.

    El binario va a disco, en ``ADJUNTOS_RUTA/conocimiento``; la fila solo
    guarda dónde está y qué es. Al borrar el dueño la base borra las filas
    (``ON DELETE CASCADE``); los archivos los retira quien borra, después del
    commit, como en el resto del portal.
    """
    __tablename__ = "imagenes_conocimiento"

    id = Column(Integer, primary_key=True)
    paso_id = Column(Integer, ForeignKey("checklists.id", ondelete="CASCADE"),
                     nullable=True, index=True)
    kb_id = Column(Integer, ForeignKey("base_conocimiento.id", ondelete="CASCADE"),
                   nullable=True, index=True)
    ticket_id = Column(Integer, ForeignKey("tickets.id", ondelete="CASCADE"),
                       nullable=True, index=True)
    # Un procedimiento de Soluciones generales (migración 0029).
    solucion_id = Column(Integer, ForeignKey("soluciones_generales.id", ondelete="CASCADE"),
                         nullable=True, index=True)
    orden = Column(Integer, default=1, nullable=False)
    # Qué se ve en la foto: "el botón está bajo la tapa, a la izquierda".
    pie = Column(String(300), nullable=True)

    nombre_original = Column(String(255), nullable=False)
    nombre_guardado = Column(String(255), nullable=False, unique=True)
    tipo_mime = Column(String(100), nullable=False)
    tamano_bytes = Column(Integer, nullable=False)
    subido_por = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    creado_en = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        CheckConstraint(
            "(CASE WHEN paso_id IS NULL THEN 0 ELSE 1 END)"
            " + (CASE WHEN kb_id IS NULL THEN 0 ELSE 1 END)"
            " + (CASE WHEN ticket_id IS NULL THEN 0 ELSE 1 END)"
            " + (CASE WHEN solucion_id IS NULL THEN 0 ELSE 1 END) = 1",
            name="ck_imagenes_conocimiento_un_dueno",
        ),
    )

    autor = relationship("Usuario")


class Auditoria(Base):
    """Bitácora de acciones administrativas (spec §12).

    Registra quién hizo qué y cuándo sobre lo que afecta a otros: cambios de
    estado, asignaciones, edición de reglas y de temas. No registra lecturas —
    eso solo llenaría la tabla sin decir nada.

    Es append-only por diseño: una bitácora que se puede editar no sirve como
    bitácora.
    """
    __tablename__ = "auditoria"

    id = Column(Integer, primary_key=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False, index=True)
    accion = Column(String(50), nullable=False, index=True)
    entidad = Column(String(50), nullable=False)
    entidad_id = Column(Integer, nullable=True)
    # Qué cambió exactamente: {"campo": {"antes": x, "despues": y}}
    detalle = Column(JSONFlexible, nullable=True)
    ip = Column(String(45), nullable=True)
    creado_en = Column(DateTime, default=datetime.utcnow, index=True)

    usuario = relationship("Usuario")

class ConsumoIA(Base):
    __tablename__ = "consumo_ia"

    id = Column(Integer, primary_key=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    ticket_id = Column(Integer, ForeignKey("tickets.id"), nullable=True)
    tokens_entrada = Column(Integer, default=0)
    tokens_salida = Column(Integer, default=0)
    modelo = Column(String(50), nullable=False)
    costo_estimado = Column(Float, default=0.0)
    creado_en = Column(DateTime, default=datetime.utcnow)

class ConsultaAsistente(Base):
    """Una fila por consulta al asistente: que se pregunto y que se encontro.

    **Sin esto no se puede contestar la pregunta que de verdad importa: que le
    estan preguntando al portal que no sabe contestar.** El resto de metricas
    miden lo que si funciono —sugerencias utiles, tickets deflectados—; esta
    tabla es la unica que guarda los fallos, y los fallos son los que dicen que
    documentacion falta escribir.

    `pregunta` se guarda entera y a proposito. Sin el texto se sabe que hubo
    doce consultas sin respuesta y no sobre que, que no sirve para nada. Es
    coherente con lo que el portal ya conserva —`tickets.descripcion_original`,
    `temas_sugeridos.descripcion_ejemplo`, las conversaciones del chat— y solo
    la ve un administrador, igual que la documentacion de TI.

    No lleva embedding: no se busca por similitud aqui dentro. Es una bitacora,
    no una fuente de conocimiento — si alguna vez contesta preguntas, estaria
    respondiendo con preguntas de otros en vez de con soluciones revisadas.
    """
    __tablename__ = "consultas_asistente"

    id = Column(Integer, primary_key=True)
    # La planta de quien preguntó; vacía si fue alguien de TI.
    sitio_id = Column(Integer, ForeignKey("sitios.id"), nullable=True, index=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    pregunta = Column(Text, nullable=False)
    # La que traia el formulario, no una que adivine ningun modelo.
    categoria = Column(String(50), nullable=True, index=True)

    # Que se recupero. `mejor_similitud` en NULL significa que no se recupero
    # nada: ni un pasaje paso el umbral.
    pasajes = Column(Integer, default=0, nullable=False)
    mejor_similitud = Column(Float, nullable=True)
    # De donde salio el mejor pasaje: ticket | documento | solucion_general.
    mejor_fuente = Column(String(30), nullable=True)

    # directo | ollama | gemini | extractos | sin_fundamento
    #
    # Es la columna que se mira primero. `sin_fundamento` es un hueco de
    # conocimiento; `extractos` es que se encontro algo pero ningun modelo pudo
    # fundamentar una respuesta encima, que suele ser un pasaje que empareja de
    # refilon. Los dos piden documentacion, por motivos distintos.
    origen = Column(String(20), nullable=False, index=True)
    duracion_ms = Column(Integer, nullable=True)
    creado_en = Column(DateTime, default=datetime.utcnow, index=True)


class Alerta(Base):
    """Algo que TI tiene que mirar ya, aunque nadie haya abierto la pantalla.

    La generan procesos en segundo plano —el vigilante del SLA, la telemetría
    de los sensores— y salen en la campana del tablero de TI en vivo. Una por
    cosa: el índice único de `(tipo, clave)` impide que el vigilante, que pasa
    cada minuto, avise diez veces del mismo ticket (migración 0026).
    """
    __tablename__ = "alertas"
    __table_args__ = (UniqueConstraint("tipo", "clave", name="uq_alertas_tipo_clave"),)

    id = Column(Integer, primary_key=True)
    # sla_por_vencer | sla_vencido | iot_umbral | iot_sin_senal
    tipo = Column(String(30), nullable=False, index=True)
    # Lo que la hace única: "ticket:12", "dispositivo:3:temperatura:2026-10-02T14".
    clave = Column(String(120), nullable=False)
    sitio_id = Column(Integer, ForeignKey("sitios.id"), nullable=True, index=True)
    ticket_id = Column(Integer, ForeignKey("tickets.id", ondelete="CASCADE"), nullable=True)
    dispositivo_id = Column(Integer, ForeignKey("dispositivos_iot.id", ondelete="CASCADE"), nullable=True)
    titulo = Column(String(200), nullable=False)
    detalle = Column(Text, nullable=True)
    # Lo que la pantalla necesita para redactarla en el idioma de quien la lee
    # (folio, minutos, valor y umbral...). `titulo` queda como texto de reserva.
    datos = Column(JSON, nullable=True)
    creado_en = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    atendida_en = Column(DateTime, nullable=True)
    atendida_por = Column(Integer, ForeignKey("usuarios.id"), nullable=True)

    sitio = relationship("Sitio")
    ticket = relationship("Ticket")
    dispositivo = relationship("DispositivoIoT")


class DispositivoIoT(Base):
    """Un ESP32 que manda telemetría por MQTT.

    Se registra solo con su primer mensaje: su `clave` es el identificador que
    lleva en el tema (`portal/<planta>/sensores/<clave>/telemetria`). TI le pone
    después nombre, ubicación y umbrales desde Monitoreo ESP32 (migraciones 0026
    y 0027).
    """
    __tablename__ = "dispositivos_iot"

    id = Column(Integer, primary_key=True)
    clave = Column(String(64), unique=True, nullable=False, index=True)
    nombre = Column(String(100), nullable=True)
    ubicacion = Column(String(100), nullable=True)
    sitio_id = Column(Integer, ForeignKey("sitios.id"), nullable=True, index=True)
    activo = Column(Boolean, default=True, nullable=False, server_default=text("true"))
    ultimo_contacto = Column(DateTime, nullable=True)
    creado_en = Column(DateTime, default=datetime.utcnow, nullable=False)
    # Umbrales propios: {"temperatura": 30, "humedad": 60, "calidad_aire": 800}.
    # Lo que falte se toma de IOT_*_MAX. Un cuarto de servidores no aguanta lo
    # que aguanta una nave de producción.
    umbrales = Column(JSON, nullable=True)

    sitio = relationship("Sitio")


class LecturaIoT(Base):
    """Una lectura de un sensor. Se purgan las de más de `IOT_RETENCION_DIAS`."""
    __tablename__ = "lecturas_iot"
    __table_args__ = (
        Index("ix_lecturas_iot_dispositivo_fecha", "dispositivo_id", "registrado_en"),
    )

    id = Column(Integer, primary_key=True)
    dispositivo_id = Column(Integer, ForeignKey("dispositivos_iot.id", ondelete="CASCADE"),
                            nullable=False)
    temperatura = Column(Float, nullable=True)
    humedad = Column(Float, nullable=True)
    calidad_aire = Column(Float, nullable=True)
    # Lo demás que mande el firmware y que el portal todavía no interpreta.
    extra = Column(JSON, nullable=True)
    registrado_en = Column(DateTime, default=datetime.utcnow, nullable=False)



# ----------------------------------------------------------------------
# Directorio de documentos (migración 0030)
# ----------------------------------------------------------------------

carpeta_plantas = Table(
    "carpeta_plantas",
    Base.metadata,
    Column("carpeta_id", Integer, ForeignKey("carpetas.id", ondelete="CASCADE"), primary_key=True),
    Column("sitio_id", Integer, ForeignKey("sitios.id"), primary_key=True),
)


class Carpeta(Base):
    """Una carpeta del directorio de documentos.

    `ruta` son los ids desde la raíz, materializados: `/1/7/12/`. Lo que está
    debajo de una carpeta es lo que empieza por su ruta. La visibilidad
    (`ti`, `todos`, `plantas`) solo la llevan las de primer nivel; las demás
    la heredan de su raíz —el primer id de la ruta—. Ver la migración 0030.
    """
    __tablename__ = "carpetas"
    __table_args__ = (
        CheckConstraint("profundidad BETWEEN 1 AND 8", name="ck_carpetas_profundidad"),
        CheckConstraint("visibilidad IN ('ti', 'todos', 'plantas')", name="ck_carpetas_visibilidad"),
        CheckConstraint("(padre_id IS NULL) = (visibilidad IS NOT NULL)",
                        name="ck_carpetas_visibilidad_solo_raiz"),
    )

    id = Column(Integer, primary_key=True)
    padre_id = Column(Integer, ForeignKey("carpetas.id", ondelete="RESTRICT"), nullable=True, index=True)
    nombre = Column(String(120), nullable=False)
    ruta = Column(Text, nullable=False)
    profundidad = Column(SmallInteger, nullable=False)
    visibilidad = Column(String(10), nullable=True)
    descripcion = Column(Text, nullable=True)
    creado_por = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    creado_en = Column(DateTime, default=datetime.utcnow, nullable=False)
    actualizado_en = Column(DateTime, default=datetime.utcnow, nullable=False)
    # Papelera: se marca y el worker la purga a los DIRECTORIO_PAPELERA_DIAS.
    eliminado_en = Column(DateTime, nullable=True)
    eliminado_por = Column(Integer, ForeignKey("usuarios.id"), nullable=True)

    plantas = relationship("Sitio", secondary=carpeta_plantas)
    autor = relationship("Usuario", foreign_keys=[creado_por])


Index("ux_carpetas_padre_nombre", func.coalesce(Carpeta.padre_id, 0), func.lower(Carpeta.nombre),
      unique=True, postgresql_where=Carpeta.eliminado_en.is_(None),
      sqlite_where=Carpeta.eliminado_en.is_(None))
Index("ix_carpetas_ruta", Carpeta.ruta, postgresql_ops={"ruta": "text_pattern_ops"})


class Archivo(Base):
    """Un archivo del directorio, en su versión vigente.

    Las anteriores viven en `archivo_versiones`. El binario va a disco con un
    nombre sin extensión (`nombre_guardado`, un uuid): el nombre con que se
    descarga es `nombre`, y el tipo con que se sirve, `tipo_mime`, lo decide
    el portal al subirlo, no el navegador de quien lo subió.
    """
    __tablename__ = "archivos"

    id = Column(Integer, primary_key=True)
    carpeta_id = Column(Integer, ForeignKey("carpetas.id", ondelete="RESTRICT"), nullable=False, index=True)
    nombre = Column(String(255), nullable=False)
    tipo_mime = Column(String(100), nullable=False)
    tamano_bytes = Column(BigInteger, nullable=False)
    sha256 = Column(CHAR(64), nullable=False)
    nombre_guardado = Column(String(64), nullable=False, unique=True)
    version = Column(Integer, nullable=False, default=1, server_default=text("1"))
    descripcion = Column(Text, nullable=True)
    subido_por = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    creado_en = Column(DateTime, default=datetime.utcnow, nullable=False)
    actualizado_en = Column(DateTime, default=datetime.utcnow, nullable=False)
    eliminado_en = Column(DateTime, nullable=True)
    eliminado_por = Column(Integer, ForeignKey("usuarios.id"), nullable=True)

    carpeta = relationship("Carpeta")
    autor = relationship("Usuario", foreign_keys=[subido_por])
    versiones = relationship("ArchivoVersion", back_populates="archivo",
                             cascade="all, delete-orphan", passive_deletes=True,
                             order_by="ArchivoVersion.version.desc()")


Index("ux_archivos_carpeta_nombre", Archivo.carpeta_id, func.lower(Archivo.nombre),
      unique=True, postgresql_where=Archivo.eliminado_en.is_(None),
      sqlite_where=Archivo.eliminado_en.is_(None))


class ArchivoVersion(Base):
    """Una versión anterior de un archivo. Se guardan las últimas
    `DIRECTORIO_MAX_VERSIONES - 1`: con la vigente, son diez."""
    __tablename__ = "archivo_versiones"
    __table_args__ = (
        UniqueConstraint("archivo_id", "version", name="uq_archivo_versiones_archivo_version"),
    )

    id = Column(Integer, primary_key=True)
    archivo_id = Column(Integer, ForeignKey("archivos.id", ondelete="CASCADE"), nullable=False)
    version = Column(Integer, nullable=False)
    nombre_guardado = Column(String(64), nullable=False, unique=True)
    tipo_mime = Column(String(100), nullable=False)
    tamano_bytes = Column(BigInteger, nullable=False)
    sha256 = Column(CHAR(64), nullable=False)
    subido_por = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    creado_en = Column(DateTime, default=datetime.utcnow, nullable=False)

    archivo = relationship("Archivo", back_populates="versiones")
    autor = relationship("Usuario", foreign_keys=[subido_por])

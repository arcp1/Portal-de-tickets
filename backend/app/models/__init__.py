from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, ForeignKey, Float, JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from pgvector.sqlalchemy import Vector
from app.core.db import Base

# jsonb en Postgres, json genérico en SQLite (pruebas).
JSONFlexible = JSON().with_variant(JSONB, "postgresql")

class Sitio(Base):
    __tablename__ = "sitios"

    id = Column(Integer, primary_key=True, index=True)
    clave = Column(String(10), unique=True, index=True, nullable=False)
    nombre = Column(String(100), nullable=False)
    pais = Column(String(50), nullable=False, default="México")
    activo = Column(Boolean, default=True)

    usuarios = relationship("Usuario", back_populates="sitio")
    equipos = relationship("Equipo", back_populates="sitio")
    tickets = relationship("Ticket", back_populates="sitio")
    reglas = relationship("ReglaNegocio", back_populates="sitio")

class Usuario(Base):
    __tablename__ = "usuarios"

    id = Column(Integer, primary_key=True, index=True)
    sitio_id = Column(Integer, ForeignKey("sitios.id"), nullable=False)
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
    ultimo_acceso = Column(DateTime, nullable=True)
    creado_en = Column(DateTime, default=datetime.utcnow)

    sitio = relationship("Sitio", back_populates="usuarios")
    tickets_creados = relationship("Ticket", foreign_keys="Ticket.usuario_id", back_populates="usuario")
    tickets_asignados = relationship("Ticket", foreign_keys="Ticket.asignado_a", back_populates="asignado_usuario")
    equipos = relationship("Equipo", back_populates="asignado_usuario")

class Equipo(Base):
    __tablename__ = "equipos"

    id = Column(Integer, primary_key=True, index=True)
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

    id = Column(Integer, primary_key=True, index=True)
    sitio_id = Column(Integer, ForeignKey("sitios.id"), nullable=False)
    folio = Column(String(30), unique=True, index=True, nullable=False)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    equipo_id = Column(Integer, ForeignKey("equipos.id"), nullable=True)
    categoria = Column(String(50), nullable=False) # impresora, red, equipo, software, accesos, otro
    subcategoria = Column(String(50), nullable=True)
    descripcion_original = Column(Text, nullable=False)
    descripcion_normalizada = Column(Text, nullable=True)
    prioridad = Column(String(20), default="media") # baja, media, alta, critica
    estado = Column(String(30), default="abierto") # abierto, en_proceso, espera_proveedor, resuelto, cerrado
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

    sitio = relationship("Sitio", back_populates="tickets")
    usuario = relationship("Usuario", foreign_keys=[usuario_id], back_populates="tickets_creados")
    asignado_usuario = relationship("Usuario", foreign_keys=[asignado_a], back_populates="tickets_asignados")
    equipo = relationship("Equipo", back_populates="tickets")
    comentarios = relationship("TicketComentario", back_populates="ticket", cascade="all, delete-orphan")
    adjuntos = relationship("TicketAdjunto", back_populates="ticket", cascade="all, delete-orphan")

class TicketComentario(Base):
    __tablename__ = "ticket_comentarios"

    id = Column(Integer, primary_key=True, index=True)
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

    id = Column(Integer, primary_key=True, index=True)
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

    id = Column(Integer, primary_key=True, index=True)
    folio = Column(String(30), unique=True, index=True, nullable=False)
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

    id = Column(Integer, primary_key=True, index=True)
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

    id = Column(Integer, primary_key=True, index=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False, index=True)
    sitio_id = Column(Integer, ForeignKey("sitios.id"), nullable=False)
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

    id = Column(Integer, primary_key=True, index=True)
    sitio_id = Column(Integer, ForeignKey("sitios.id"), nullable=False)
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

class SugerenciaKB(Base):
    """Una fila por sugerencia mostrada al usuario. fue_util queda en NULL
    hasta que responde el botón de '¿te sirvió?'."""
    __tablename__ = "sugerencias_kb"

    id = Column(Integer, primary_key=True, index=True)
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

    id = Column(Integer, primary_key=True, index=True)
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

class TemaSugerido(Base):
    """Un problema recurrente que el portal todavía no tiene contemplado.

    Cuando alguien reporta algo que no encaja en las categorías, se agrupa por
    similitud con lo ya reportado. Si el mismo problema aparece varias veces,
    deja de ser un caso suelto y se le propone al admin convertirlo en tema con
    su propio checklist.
    """
    __tablename__ = "temas_sugeridos"

    id = Column(Integer, primary_key=True, index=True)
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

    id = Column(Integer, primary_key=True, index=True)
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

    id = Column(Integer, primary_key=True, index=True)
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

    id = Column(Integer, primary_key=True, index=True)
    sitio_id = Column(Integer, ForeignKey("sitios.id"), nullable=False, index=True)
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

    id = Column(Integer, primary_key=True, index=True)
    sitio_id = Column(Integer, ForeignKey("sitios.id"), nullable=False, index=True)
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

class Auditoria(Base):
    """Bitácora de acciones administrativas (spec §12).

    Registra quién hizo qué y cuándo sobre lo que afecta a otros: cambios de
    estado, asignaciones, edición de reglas y de temas. No registra lecturas —
    eso solo llenaría la tabla sin decir nada.

    Es append-only por diseño: una bitácora que se puede editar no sirve como
    bitácora.
    """
    __tablename__ = "auditoria"

    id = Column(Integer, primary_key=True, index=True)
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

    id = Column(Integer, primary_key=True, index=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    ticket_id = Column(Integer, ForeignKey("tickets.id"), nullable=True)
    tokens_entrada = Column(Integer, default=0)
    tokens_salida = Column(Integer, default=0)
    modelo = Column(String(50), nullable=False)
    costo_estimado = Column(Float, default=0.0)
    creado_en = Column(DateTime, default=datetime.utcnow)

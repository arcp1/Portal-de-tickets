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
    nombre = Column(String(100), nullable=False)
    email = Column(String(100), unique=True, index=True, nullable=False)
    rol = Column(String(20), nullable=False, default="usuario") # admin, usuario
    area = Column(String(50), nullable=True)
    idioma_preferido = Column(String(5), default="es")
    activo = Column(Boolean, default=True)
    password_hash = Column(String(255), nullable=False)

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
    indexado_kb = Column(Boolean, default=False, nullable=False)
    creado_en = Column(DateTime, default=datetime.utcnow)
    resuelto_en = Column(DateTime, nullable=True)
    tiempo_resolucion = Column(Integer, nullable=True) # in minutes

    sitio = relationship("Sitio", back_populates="tickets")
    usuario = relationship("Usuario", foreign_keys=[usuario_id], back_populates="tickets_creados")
    asignado_usuario = relationship("Usuario", foreign_keys=[asignado_a], back_populates="tickets_asignados")
    equipo = relationship("Equipo", back_populates="tickets")
    comentarios = relationship("TicketComentario", back_populates="ticket", cascade="all, delete-orphan")

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

class BaseConocimiento(Base):
    __tablename__ = "base_conocimiento"

    id = Column(Integer, primary_key=True, index=True)
    sitio_id = Column(Integer, ForeignKey("sitios.id"), nullable=False)
    titulo = Column(String(150), nullable=False)
    contenido = Column(Text, nullable=False)
    categoria = Column(String(50), nullable=False)
    tags = Column(String(200), nullable=True)
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
    __tablename__ = "checklists"

    id = Column(Integer, primary_key=True, index=True)
    categoria = Column(String(50), nullable=False)
    orden = Column(Integer, default=1)
    pregunta_key = Column(String(100), nullable=False)
    accion_si_no = Column(Text, nullable=True)
    resuelve = Column(Boolean, default=False)

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

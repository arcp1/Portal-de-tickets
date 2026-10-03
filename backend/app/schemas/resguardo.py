from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.auth import UserResponse
from app.schemas.comunes import FechaUTC


class EquipoResumen(BaseModel):
    id: int
    tipo: str
    categoria: str
    marca: str
    modelo: str
    numero_serie: Optional[str] = None
    ubicacion: Optional[str] = None
    estado: str

    model_config = ConfigDict(from_attributes=True)


class ResguardoCreate(BaseModel):
    equipo_id: int
    usuario_id: int
    accesorios: Optional[str] = None
    observaciones: Optional[str] = None
    # Permite condiciones especiales para un caso concreto. Si no se manda, se
    # usan las estándar.
    condiciones: Optional[str] = None


class FirmaRequest(BaseModel):
    # Se pide teclear el nombre completo: convierte el clic en un acto
    # deliberado y deja constancia de qué escribió la persona.
    nombre_completo: str = Field(min_length=3, max_length=150)
    acepto: bool


class DevolucionRequest(BaseModel):
    observaciones: Optional[str] = None
    # Estado en que queda el equipo: puede volver directo a mantenimiento.
    estado_equipo: str = "disponible"


class CancelacionRequest(BaseModel):
    motivo: str = Field(min_length=5)


class ResguardoResponse(BaseModel):
    id: int
    folio: str
    sitio_id: int
    estado: str
    usuario_id: int
    usuario: Optional[UserResponse] = None
    equipo_id: int
    equipo: Optional[EquipoResumen] = None
    emisor: Optional[UserResponse] = None
    receptor: Optional[UserResponse] = None

    condiciones: str
    accesorios: Optional[str] = None
    observaciones_entrega: Optional[str] = None
    observaciones_devolucion: Optional[str] = None

    entregado_en: Optional[FechaUTC] = None
    firmado_en: Optional[FechaUTC] = None
    firma_nombre: Optional[str] = None
    devuelto_en: Optional[FechaUTC] = None
    creado_en: FechaUTC

    model_config = ConfigDict(from_attributes=True)


class MovimientoResponse(BaseModel):
    id: int
    tipo: str
    usuario: Optional[UserResponse] = None
    autor: Optional[UserResponse] = None
    resguardo_id: Optional[int] = None
    estado_anterior: Optional[str] = None
    estado_nuevo: Optional[str] = None
    nota: Optional[str] = None
    creado_en: FechaUTC

    model_config = ConfigDict(from_attributes=True)


# --- Documentos del expediente ---

TIPOS_DOCUMENTO = ("resguardo", "responsiva", "politica", "contrato", "identificacion", "otro")


class DocumentoResponse(BaseModel):
    id: int
    usuario_id: int
    tipo: str
    titulo: str
    descripcion: Optional[str] = None
    resguardo_id: Optional[int] = None
    nombre_original: str
    tipo_mime: str
    tamano_bytes: int
    vigente_hasta: Optional[FechaUTC] = None
    creado_en: FechaUTC
    autor: Optional[UserResponse] = None
    # Calculado: un documento con vigencia pasada.
    vencido: bool = False

    model_config = ConfigDict(from_attributes=True)


class ExpedienteResponse(BaseModel):
    """Todo lo de una persona en un solo lugar."""
    usuario: UserResponse
    equipos_a_cargo: List[EquipoResumen] = []
    resguardos: List[ResguardoResponse] = []
    documentos: List[DocumentoResponse] = []
    resguardos_pendientes_firma: int = 0
    documentos_vencidos: int = 0

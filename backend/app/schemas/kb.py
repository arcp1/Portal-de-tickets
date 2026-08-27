from typing import List, Optional

from pydantic import BaseModel, Field


class NormalizarRequest(BaseModel):
    texto: str


class NormalizarResponse(BaseModel):
    texto_normalizado: str
    # 0.0 = Ollama no respondió y se devuelve el texto original tal cual.
    confianza: float
    degradado: bool = False


class SimilaresRequest(BaseModel):
    texto: str
    sitio_id: int
    categoria: Optional[str] = None
    # Si se manda, la sugerencia queda ligada al ticket que la originó.
    ticket_id: Optional[int] = None


class SugerenciaResponse(BaseModel):
    sugerencia_id: int
    kb_id: int
    titulo: str
    contenido: str
    categoria: str
    similitud: float
    ticket_origen_id: Optional[int] = None


class SimilaresResponse(BaseModel):
    resultados: List[SugerenciaResponse] = []
    umbral_usado: float
    # True = la búsqueda no se pudo hacer. El frontend simplemente no muestra
    # nada; nunca un error de IA al usuario.
    degradado: bool = False


class FeedbackRequest(BaseModel):
    sugerencia_id: int
    fue_util: bool


class FeedbackResponse(BaseModel):
    ok: bool
    sugerencia_id: int
    fue_util: bool


class IndexarResponse(BaseModel):
    ok: bool
    embedding_generado: bool
    motivo: Optional[str] = None


class MetricasKBResponse(BaseModel):
    entradas_kb: int
    sugerencias_mostradas: int
    sugerencias_utiles: int
    sugerencias_respondidas: int
    tasa_utilidad: Optional[float] = Field(
        default=None,
        description="veces_util / veces_sugerida. None mientras no haya sugerencias mostradas.",
    )
    umbral_actual: float
    tickets_pendientes_indexar: int

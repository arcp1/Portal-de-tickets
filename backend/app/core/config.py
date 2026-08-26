import os
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    PROJECT_NAME: str = "Portal de Tickets TI — CGR de México"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api"

    DATABASE_URL: str = os.getenv(
        "DATABASE_URL", 
        "postgresql://cgr_user:cgr_secure_password@localhost:5432/portal_tickets"
    )
    
    JWT_SECRET: str = os.getenv("JWT_SECRET", "dev_secret_key_cgr_queretaro_2026")
    JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "480"))

    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    OLLAMA_HOST: str = os.getenv("OLLAMA_HOST", "http://host.docker.internal:11434")
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")

    # --- Fase 2: asistente local ---
    # Interruptor general. En off el portal funciona igual, solo sin ayudas de IA.
    IA_HABILITADA: bool = os.getenv("IA_HABILITADA", "true").lower() == "true"
    OLLAMA_MODELO_EMBEDDING: str = os.getenv("OLLAMA_MODELO_EMBEDDING", "nomic-embed-text")
    OLLAMA_MODELO_TEXTO: str = os.getenv("OLLAMA_MODELO_TEXTO", "qwen2.5:3b")
    # Si se rebasan, se abandona la operación y el flujo continúa sin ella.
    OLLAMA_TIMEOUT_NORMALIZACION: float = float(os.getenv("OLLAMA_TIMEOUT_NORMALIZACION", "10"))
    OLLAMA_TIMEOUT_EMBEDDING: float = float(os.getenv("OLLAMA_TIMEOUT_EMBEDDING", "5"))

    # Distancia coseno. Se calibra con veces_util / veces_sugerida.
    KB_UMBRAL_SIMILITUD: float = float(os.getenv("KB_UMBRAL_SIMILITUD", "0.75"))
    KB_MAX_SUGERENCIAS: int = int(os.getenv("KB_MAX_SUGERENCIAS", "3"))
    # Longitud mínima de una solución para que sirva de algo en la base de conocimiento.
    SOLUCION_MIN_LONGITUD: int = int(os.getenv("SOLUCION_MIN_LONGITUD", "20"))

    # --- Chatbot flotante ---
    # Debajo de este valor no se confía en la clasificación y se piden los
    # dropdowns en lugar de adivinar.
    CHAT_UMBRAL_CONFIANZA: float = float(os.getenv("CHAT_UMBRAL_CONFIANZA", "0.7"))
    # A la cuarta, ticket. Corta la conversación circular.
    CHAT_MAX_INTERCAMBIOS: int = int(os.getenv("CHAT_MAX_INTERCAMBIOS", "3"))
    OLLAMA_TIMEOUT_CLASIFICACION: float = float(os.getenv("OLLAMA_TIMEOUT_CLASIFICACION", "10"))

    model_config = SettingsConfigDict(case_sensitive=True, env_file=".env", extra="ignore")

settings = Settings()

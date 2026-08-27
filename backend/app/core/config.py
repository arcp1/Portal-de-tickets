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

    # Similitud coseno mínima para sugerir una entrada de la base de conocimiento.
    # La spec propone 0.75 y pide ajustarlo con datos reales. Medido contra
    # nomic-embed-text: una paráfrasis del mismo incidente da ~0.70 y una
    # incidencia no relacionada ~0.49, así que 0.75 dejaba fuera casos buenos.
    # 0.65 los recupera y mantiene separación holgada del ruido.
    # Recalibrar con veces_util / veces_sugerida cuando haya ~100 casos.
    KB_UMBRAL_SIMILITUD: float = float(os.getenv("KB_UMBRAL_SIMILITUD", "0.65"))
    KB_MAX_SUGERENCIAS: int = int(os.getenv("KB_MAX_SUGERENCIAS", "3"))
    # Longitud mínima de una solución para que sirva de algo en la base de conocimiento.
    SOLUCION_MIN_LONGITUD: int = int(os.getenv("SOLUCION_MIN_LONGITUD", "20"))

    # --- Chatbot flotante ---
    # Debajo de este valor no se confía en la clasificación y se piden los
    # dropdowns en lugar de adivinar.
    CHAT_UMBRAL_CONFIANZA: float = float(os.getenv("CHAT_UMBRAL_CONFIANZA", "0.7"))
    # Mínimo de contenido antes de pedirle una categoría al modelo.
    # Medido con qwen2.5:3b: a "no sirve" y "ya no jala" les asigna 0.9 de
    # confianza en la categoría "equipo". La confianza que se auto-reporta un
    # modelo de 3B no distingue lo que sabe de lo que supone, así que el corte
    # tiene que ser determinista y anterior a la llamada.
    CHAT_MIN_PALABRAS: int = int(os.getenv("CHAT_MIN_PALABRAS", "4"))
    CHAT_MIN_CARACTERES: int = int(os.getenv("CHAT_MIN_CARACTERES", "20"))

    # --- Cuentas de acceso ---
    # Dominios de correo aceptados al dar de alta a alguien. Vacio = sin
    # restriccion. Evita registrar correos personales por equivocacion.
    DOMINIOS_PERMITIDOS: str = os.getenv("DOMINIOS_PERMITIDOS", "cgr.mx")
    # Cuanto vive el codigo de activacion que TI le entrega a la persona.
    CODIGO_ACTIVACION_HORAS: int = int(os.getenv("CODIGO_ACTIVACION_HORAS", "168"))
    # La longitud es lo que mas aporta a una contrasena y lo que la gente si
    # cumple sin apuntarla en un papel pegado al monitor.
    PASSWORD_MIN_LONGITUD: int = int(os.getenv("PASSWORD_MIN_LONGITUD", "10"))

    # --- Limite de intentos de inicio de sesion ---
    # Frena la prueba de contrasenas contra el portal. Se aplica por IP y por
    # correo a la vez.
    LOGIN_MAX_INTENTOS: int = int(os.getenv("LOGIN_MAX_INTENTOS", "8"))
    LOGIN_VENTANA_SEGUNDOS: int = int(os.getenv("LOGIN_VENTANA_SEGUNDOS", "300"))

    # --- Avisos por correo ---
    # Sin SMTP_HOST el servicio queda inactivo en silencio: el portal funciona
    # igual, solo que el usuario tiene que entrar a ver si le respondieron.
    NOTIFICACIONES_ACTIVAS: bool = os.getenv("NOTIFICACIONES_ACTIVAS", "true").lower() == "true"
    SMTP_HOST: str = os.getenv("SMTP_HOST", "")
    SMTP_PUERTO: int = int(os.getenv("SMTP_PUERTO", "587"))
    SMTP_USUARIO: str = os.getenv("SMTP_USUARIO", "")
    SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD", "")
    SMTP_REMITENTE: str = os.getenv("SMTP_REMITENTE", "")
    SMTP_STARTTLS: bool = os.getenv("SMTP_STARTTLS", "true").lower() == "true"
    SMTP_SSL: bool = os.getenv("SMTP_SSL", "false").lower() == "true"
    PORTAL_URL: str = os.getenv("PORTAL_URL", "http://localhost")

    # --- Horario del equipo de TI ---
    # No hay personal después de las 17:00 ni en fin de semana. El portal no
    # finge que sí: le dice al usuario cuándo lo van a atender de verdad, y
    # fuera de horario el asistente se esfuerza más antes de levantar ticket.
    HORARIO_INICIO: int = int(os.getenv("HORARIO_INICIO", "8"))
    HORARIO_FIN: int = int(os.getenv("HORARIO_FIN", "17"))
    # 0=lunes ... 6=domingo
    DIAS_LABORALES: str = os.getenv("DIAS_LABORALES", "0,1,2,3,4")
    # Zona horaria de la planta, en horas respecto a UTC. Querétaro = UTC-6.
    HUSO_HORARIO_OFFSET: int = int(os.getenv("HUSO_HORARIO_OFFSET", "-6"))

    # Fuera de horario el asistente muestra más sugerencias antes de rendirse:
    # no hay nadie a quien escalar, así que vale la pena intentarlo.
    KB_MAX_SUGERENCIAS_FUERA_HORARIO: int = int(os.getenv("KB_MAX_SUGERENCIAS_FUERA_HORARIO", "5"))

    # --- SLA por prioridad, en horas hábiles ---
    # Se cuentan solo horas de trabajo: un ticket abierto el viernes a las 16:00
    # con SLA de 8 horas vence el lunes, no el sábado.
    SLA_HORAS_CRITICA: float = float(os.getenv("SLA_HORAS_CRITICA", "2"))
    SLA_HORAS_ALTA: float = float(os.getenv("SLA_HORAS_ALTA", "8"))
    SLA_HORAS_MEDIA: float = float(os.getenv("SLA_HORAS_MEDIA", "24"))
    SLA_HORAS_BAJA: float = float(os.getenv("SLA_HORAS_BAJA", "72"))

    # --- Adjuntos ---
    # Una foto del error o del LED parpadeando ahorra media conversación.
    ADJUNTOS_RUTA: str = os.getenv("ADJUNTOS_RUTA", "/app/adjuntos")
    ADJUNTOS_MAX_MB: int = int(os.getenv("ADJUNTOS_MAX_MB", "10"))
    ADJUNTOS_MAX_POR_TICKET: int = int(os.getenv("ADJUNTOS_MAX_POR_TICKET", "5"))

    # --- Documentos del expediente ---
    # Resguardos firmados escaneados, responsivas, politicas. Van a disco, no a
    # la base: un PDF escaneado son varios MB y no aportan nada dentro de Postgres.
    DOCUMENTOS_RUTA: str = os.getenv("DOCUMENTOS_RUTA", "/app/documentos")
    DOCUMENTOS_MAX_MB: int = int(os.getenv("DOCUMENTOS_MAX_MB", "20"))

    # --- Temas recurrentes ---
    # Qué tan parecidas deben ser dos incidencias para contarlas como el mismo
    # problema. Más alto que el umbral de sugerencias: aquí se agrupa, y agrupar
    # de más mezcla problemas distintos bajo un mismo tema.
    TEMA_UMBRAL_AGRUPACION: float = float(os.getenv("TEMA_UMBRAL_AGRUPACION", "0.78"))
    # Cuántas veces tiene que repetirse antes de proponerlo como tema propio.
    TEMA_MIN_OCURRENCIAS: int = int(os.getenv("TEMA_MIN_OCURRENCIAS", "3"))
    # A la cuarta, ticket. Corta la conversación circular.
    CHAT_MAX_INTERCAMBIOS: int = int(os.getenv("CHAT_MAX_INTERCAMBIOS", "3"))
    OLLAMA_TIMEOUT_CLASIFICACION: float = float(os.getenv("OLLAMA_TIMEOUT_CLASIFICACION", "10"))
    # Cuánto mantiene Ollama el modelo cargado en RAM tras la última petición.
    # Sin esto lo descarga a los 5 minutos y la siguiente consulta paga la
    # recarga completa: varios segundos que el usuario siente como "está trabado".
    # A cambio, qwen2.5:3b ocupa ~2 GB de RAM de forma permanente.
    OLLAMA_KEEP_ALIVE: str = os.getenv("OLLAMA_KEEP_ALIVE", "30m")

    model_config = SettingsConfigDict(case_sensitive=True, env_file=".env", extra="ignore")

settings = Settings()

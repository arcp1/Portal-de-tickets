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
    # Secretos que alguna vez estuvieron en el repo o en la plantilla del .env.
    # Quien los conozca puede firmarse un token de administrador, asi que en
    # produccion el portal se niega a arrancar con ellos puestos.
    SECRETOS_PROHIBIDOS: tuple = (
        "dev_secret_key_cgr_queretaro_2026",
        "cambiar_esta_clave_secreta_en_produccion_123456789",
        "changeme", "secret", "cambiar",
    )
    JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "480"))

    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    OLLAMA_HOST: str = os.getenv("OLLAMA_HOST", "http://host.docker.internal:11434")
    # --- Gemini (Fase 3) ---
    # La llave se pone en el .env y NUNCA en el repositorio. Sin llave, el
    # portal funciona igual: Ollama se queda con todo y Gemini no se usa.
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    # Interruptor aparte de la llave: permite apagarlo sin borrarla, por
    # ejemplo si se dispara el gasto y hay que frenar mientras se revisa.
    GEMINI_HABILITADO: bool = os.getenv("GEMINI_HABILITADO", "true").lower() == "true"
    # Flash es el que corresponde a este uso: respuestas cortas sobre extractos
    # ya recuperados. Pro cuesta varias veces mas y aqui no aporta.
    GEMINI_MODELO: str = os.getenv("GEMINI_MODELO", "gemini-2.5-flash")
    GEMINI_TIMEOUT: float = float(os.getenv("GEMINI_TIMEOUT", "20"))
    # Cuantos tickets resueltos se le mandan como contexto. Cada uno cuesta
    # tokens de entrada: cinco alcanzan y el gasto se mantiene predecible.
    GEMINI_MAX_EXTRACTOS: int = int(os.getenv("GEMINI_MAX_EXTRACTOS", "5"))
    GEMINI_MAX_TOKENS_RESPUESTA: int = int(os.getenv("GEMINI_MAX_TOKENS_RESPUESTA", "600"))
    GEMINI_MAX_TOKENS_RESUMEN: int = int(os.getenv("GEMINI_MAX_TOKENS_RESUMEN", "500"))
    # Al recibir un 429 se deja de insistir este rato, en vez de gastar el
    # timeout completo en cada peticion que llegue.
    GEMINI_ESPERA_CUOTA: float = float(os.getenv("GEMINI_ESPERA_CUOTA", "60"))

    # --- Fase 2: asistente local ---
    # Interruptor general. En off el portal funciona igual, solo sin ayudas de IA.
    IA_HABILITADA: bool = os.getenv("IA_HABILITADA", "true").lower() == "true"
    OLLAMA_MODELO_EMBEDDING: str = os.getenv("OLLAMA_MODELO_EMBEDDING", "nomic-embed-text")
    OLLAMA_MODELO_TEXTO: str = os.getenv("OLLAMA_MODELO_TEXTO", "qwen2.5:3b")
    # Si se rebasan, se abandona la operación y el flujo continúa sin ella.
    OLLAMA_TIMEOUT_NORMALIZACION: float = float(os.getenv("OLLAMA_TIMEOUT_NORMALIZACION", "10"))
    # Tareas de una sola vez donde alguien esta esperando delante de la pantalla
    # (proponer el mapeo de un archivo de RH). Se aguanta mas que en el flujo de
    # un ticket, porque si el modelo estaba dormido la primera respuesta tarda.
    OLLAMA_TIMEOUT_ASISTENCIA: float = float(os.getenv("OLLAMA_TIMEOUT_ASISTENCIA", "30"))
    OLLAMA_TIMEOUT_EMBEDDING: float = float(os.getenv("OLLAMA_TIMEOUT_EMBEDDING", "5"))

    # Similitud coseno mínima para sugerir una entrada de la base de conocimiento.
    # La spec propone 0.75 y pide ajustarlo con datos reales. Medido contra
    # nomic-embed-text: una paráfrasis del mismo incidente da ~0.70 y una
    # incidencia no relacionada ~0.49, así que 0.75 dejaba fuera casos buenos.
    # 0.65 los recupera y mantiene separación holgada del ruido.
    # Recalibrar con veces_util / veces_sugerida cuando haya ~100 casos.
    KB_UMBRAL_SIMILITUD: float = float(os.getenv("KB_UMBRAL_SIMILITUD", "0.65"))
    KB_MAX_SUGERENCIAS: int = int(os.getenv("KB_MAX_SUGERENCIAS", "3"))

    # --- Recuperacion: de donde sale lo que el asistente "sabe" ---
    # Cuantos pasajes propios se le dan al modelo como unica fuente. Mas
    # pasajes no es mejor: diluyen la pregunta y encarecen la consulta.
    RECUPERACION_MAX_PASAJES: int = int(os.getenv("RECUPERACION_MAX_PASAJES", "5"))
    # Por debajo de esto no se considera parecido, y si no queda nada NO se le
    # pregunta a ningun modelo. Es el corte que mas previene inventos.
    RECUPERACION_UMBRAL: float = float(os.getenv("RECUPERACION_UMBRAL", "0.62"))
    # Tope de la redaccion del asistente. Nadie lee mas en una pantalla de
    # soporte, y acota lo que se paga cuando redacta Gemini.
    ASISTENTE_MAX_TOKENS: int = int(os.getenv("ASISTENTE_MAX_TOKENS", "400"))
    # Cuanto peor que el mejor resultado puede ser un pasaje y aun asi mostrarse.
    # Es lo que de verdad quita el ruido: medido, la pregunta de la raya negra
    # trae el ticket correcto al 69% y uno de "cuenta bloqueada" al 64%. Los dos
    # pasan cualquier umbral fijo; lo que los separa es la distancia entre ellos.
    RECUPERACION_MARGEN: float = float(os.getenv("RECUPERACION_MARGEN", "0.04"))
    # Una respuesta que solo trae la cita ("[1]") cumple la regla y no dice
    # nada. El corte es contra el vacio, no contra la brevedad: "Reinicie la
    # impresora [1]." son 22 caracteres y es una respuesta perfectamente util.
    ASISTENTE_MIN_CARACTERES: int = int(os.getenv("ASISTENTE_MIN_CARACTERES", "15"))
    # Que fraccion del vocabulario con contenido de la respuesta tiene que venir
    # de las fuentes. Es la red que atrapa al modelo cuando se va por otro lado.
    # Heuristica, no demostracion: por eso las fuentes se enseñan siempre.
    # Medido: una respuesta buena del modelo local queda cerca de 0.5 —parte de
    # su vocabulario es relleno ("es posible que", "se debe verificar")— y una
    # que se fue por otro lado queda cerca de 0. El corte va en medio.
    ASISTENTE_ANCLAJE_MINIMO: float = float(os.getenv("ASISTENTE_ANCLAJE_MINIMO", "0.4"))
    # Arriba de esto la coincidencia no deja dudas y se entrega la solucion ya
    # escrita, sin que ningun modelo la redacte. Es el nivel 0 de la escalera:
    # instantaneo, gratis y sin manera de que se distorsione en el camino.
    ASISTENTE_UMBRAL_DIRECTO: float = float(os.getenv("ASISTENTE_UMBRAL_DIRECTO", "0.75"))
    # Cuanto se tienen que parecer dos pasajes para considerarlos el mismo
    # contenido repetido. La misma falla reportada tres veces son tres tickets y
    # una sola respuesta; sin esto se tomaban por tres fuentes distintas.
    ASISTENTE_DUPLICADO_MINIMO: float = float(
        os.getenv("ASISTENTE_DUPLICADO_MINIMO", "0.7"))
    # Ventaja de una solucion general sobre un ticket suelto. Esta escrita para
    # responder la pregunta; el ticket cuenta lo que paso un dia concreto.
    RECUPERACION_VENTAJA_GENERAL: float = float(
        os.getenv("RECUPERACION_VENTAJA_GENERAL", "0.05"))

    # --- Soluciones generales ---
    # Cuantos tickets del mismo problema hacen falta para que valga la pena
    # escribir un procedimiento. Con uno no hay patron, hay un caso.
    SOLUCION_GENERAL_MIN_TICKETS: int = int(os.getenv("SOLUCION_GENERAL_MIN_TICKETS", "3"))
    # Que tan parecidos tienen que ser dos tickets para considerarlos el mismo
    # problema. Alto a proposito: juntar cosas distintas produce procedimientos
    # que no sirven para ninguna de las dos.
    SOLUCION_GENERAL_UMBRAL: float = float(os.getenv("SOLUCION_GENERAL_UMBRAL", "0.80"))
    # Tope de tickets que se le pasan al modelo. Mas no mejora el resultado y si
    # encarece la consulta.
    SOLUCION_GENERAL_MAX_TICKETS: int = int(os.getenv("SOLUCION_GENERAL_MAX_TICKETS", "10"))
    SOLUCION_GENERAL_MIN_CARACTERES: int = int(
        os.getenv("SOLUCION_GENERAL_MIN_CARACTERES", "80"))
    # Que fraccion del borrador tiene que venir de los tickets. Mas exigente que
    # en el asistente: un borrador se lee una vez y se publica, mientras que una
    # respuesta del asistente lleva sus fuentes al lado para comprobarla.
    SOLUCION_GENERAL_ANCLAJE_MINIMO: float = float(
        os.getenv("SOLUCION_GENERAL_ANCLAJE_MINIMO", "0.5"))
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
    # La activacion asistida se gasta en el mostrador, con la persona enfrente.
    # Dura minutos a proposito: no es un codigo para entregar.
    ACTIVACION_ASISTIDA_MINUTOS: int = int(os.getenv("ACTIVACION_ASISTIDA_MINUTOS", "20"))
    # Cuantos datos personales hay que acertar para activar sin codigo.
    # Con 1, quien vea la lista de RH puede activar cuentas ajenas. Con 2 tiene
    # que conocer dos cosas distintas de esa persona en concreto. Si la cuenta
    # solo tiene uno registrado, se exige ese: no se puede pedir lo que no hay.
    VERIFICACION_FACTORES: int = int(os.getenv("VERIFICACION_FACTORES", "2"))
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

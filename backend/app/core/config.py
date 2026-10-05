import os
from pydantic_settings import BaseSettings, SettingsConfigDict

#: Los entornos en los que el API publica su documentación interactiva.
ENTORNOS_CON_DOCUMENTACION = ("development", "desarrollo", "dev", "local")


def documentacion_api_activa(entorno) -> bool:
    """Si se publican `/docs`, `/redoc` y `/openapi.json`.

    **Solo cuando se pide expresamente.** FastAPI los sirve sin sesión, y son
    el plano completo del sistema: cada ruta, cada cuerpo que acepta y cada
    dato que devuelve. Puertas adentro y en desarrollo ahorran tiempo; en
    producción le ahorran el tiempo a quien quiera atacarlo. Sin la variable,
    o con cualquier valor que no sea de desarrollo, quedan cerrados.
    """
    return (entorno or "").strip().lower() in ENTORNOS_CON_DOCUMENTACION


class Settings(BaseSettings):
    PROJECT_NAME: str = "Portal de Tickets TI — CGR de México"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api"

    # Sin valor por defecto a proposito.
    #
    # Antes caia a una URL con la contrasena escrita aqui mismo, o sea publicada
    # en el repositorio. Peor que eso: si el .env se rompia o faltaba, el portal
    # arrancaba igual contra `localhost` con una credencial conocida en vez de
    # avisar. Ahora, sin DATABASE_URL, no arranca y se ve por que.
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")
    
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
    # Vida máxima de una sesión aunque se siga usando: el token se renueva
    # mientras se trabaja (api/deps.py), pero no más allá de esto desde que se
    # entró. Una semana: TI no vuelve a entrar a media guardia, y un token
    # copiado deja de servir aunque quien lo tiene lo siga usando.
    SESION_MAXIMA_HORAS: int = int(os.getenv("SESION_MAXIMA_HORAS", "168"))

    # Origenes del navegador que pueden llamar a la API. El portal va detras del
    # mismo NGINX que la API, asi que en produccion normalmente basta con la URL
    # publica.
    #
    # **Vacio si no se dice.** El valor por defecto era el Vite de desarrollo
    # (localhost:3000) y acababa abierto en produccion. El Vite tampoco lo
    # necesita para la API —la pasa por su propio proxy—, solo para el
    # WebSocket del grafo: quien desarrolle lo pone en su .env.
    ORIGENES_PERMITIDOS: str = os.getenv("ORIGENES_PERMITIDOS", "")

    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")
    # Swagger (/docs), ReDoc (/redoc) y el esquema (/openapi.json). Se lee la
    # variable cruda, sin el valor por defecto de arriba: que falte no puede
    # abrirlos. Ver `documentacion_api_activa`.
    DOCUMENTACION_API: bool = documentacion_api_activa(os.getenv("ENVIRONMENT"))
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
    #
    # El nombre del modelo caduca. `gemini-2.5-flash` dejo de servirse a cuentas
    # nuevas y la API respondia 404; el portal lo tomaba como "Gemini fallo" y
    # seguia sin el, en silencio. Ahora eso se ve en la pantalla de Estado.
    GEMINI_MODELO: str = os.getenv("GEMINI_MODELO", "gemini-3.6-flash")
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
    # Generoso a proposito: **esto ya no bloquea a nadie.** La normalizacion
    # salio del camino critico de crear un ticket (ver `_normalizar_despues` en
    # api/tickets.py), asi que corre despues de entregar el folio y nadie mira
    # el reloj. Con 10 s se pasaba de largo y fallaba en cada ticket; medido
    # ahora tarda entre 2 y 9 s segun acierte la cache del prompt.
    OLLAMA_TIMEOUT_NORMALIZACION: float = float(os.getenv("OLLAMA_TIMEOUT_NORMALIZACION", "25"))
    # Que fraccion del vocabulario de una descripcion reescrita tiene que venir
    # del reporte original. Bajo a proposito: medido contra reescrituras reales
    # de qwen2.5:3b, una fiel da 0,67, una buena 0,57 y una que cuela una frase
    # inventada da 0,50 — esos siete puntos no dan para poner un corte sin
    # ajustarlo a dos ejemplos. Lo que si separa limpio es irse de tema, que
    # puntua 0,00. Ahi va el corte, y el caso sutil lo cubre otra cosa: la
    # descripcion original nunca se pisa.
    NORMALIZACION_ANCLAJE_MINIMO: float = float(
        os.getenv("NORMALIZACION_ANCLAJE_MINIMO", "0.35"))
    # Tareas de una sola vez donde alguien esta esperando delante de la pantalla
    # (proponer el mapeo de un archivo de RH). Se aguanta mas que en el flujo de
    # un ticket, porque si el modelo estaba dormido la primera respuesta tarda.
    OLLAMA_TIMEOUT_ASISTENCIA: float = float(os.getenv("OLLAMA_TIMEOUT_ASISTENCIA", "30"))
    OLLAMA_TIMEOUT_EMBEDDING: float = float(os.getenv("OLLAMA_TIMEOUT_EMBEDDING", "5"))

    # **Cuántos hilos usa el modelo de texto. Cuatro, y no son pocos: son los
    # que van más rápido.**
    #
    # Ollama reparte por defecto entre los ocho núcleos físicos, y en esta
    # máquina eso es contraproducente para leer el prompt. Medido con texto
    # nuevo en cada muestra y mediana de tres:
    #
    #     hilos     leer tok/s     generar tok/s
    #       3          53.6            25.9
    #       4          62.9            27.7
    #       6          45.6            28.6
    #       8          10.0            28.7      <- el reparto por defecto
    #      16           9.8            25.6
    #
    # Leer se derrumba de 62.9 a 10.0 al pasar de cuatro hilos a ocho: **seis
    # veces más lento**. Generar apenas se mueve de cuatro en adelante. Como
    # leer el prompt es la mitad o más de cada llamada, el efecto de punta a
    # punta es grande:
    #
    #     normalizar   3.38 s -> 1.55 s   (54% menos)
    #     clasificar   2.78 s -> 0.95 s   (66% menos)
    #     redactar     9.27 s -> 7.55 s   (19% menos)
    #
    # **Solo para el modelo de texto.** Los embeddings van al revés —0.043 s con
    # el reparto por defecto contra 0.063 s con cuatro— aunque ahí hablamos de
    # veinte milisegundos y da igual. Se dejan como están.
    #
    # Si se cambia de máquina o de modelo hay que volver a medirlo: el número
    # bueno depende de las dos cosas. La receta está en `scripts/medir-ia.py`.
    OLLAMA_HILOS_TEXTO: int = int(os.getenv("OLLAMA_HILOS_TEXTO", "4"))

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
    # Lo que se le exige a un pasaje que viene **solo**.
    #
    # El margen de arriba filtra midiendo distancias entre candidatos: separa el
    # bueno del ruido porque hay ruido con el que contrastar. Con un unico
    # resultado no filtra nada, y ese es el caso normal mientras la base de
    # conocimiento sea pequeña.
    #
    # Medido: "el escaner del anden 3 no manda nada al sistema" recupero un solo
    # pasaje al 66% —sobre una cuenta bloqueada—, paso el umbral general por
    # cuatro puntos, se gastaron 27 segundos de CPU redactando encima y el
    # anclaje lo rechazo al final. Con este corte se descarta al principio y se
    # contesta la verdad: de eso no hay nada escrito.
    #
    # Va entre RECUPERACION_UMBRAL (0.62) y ASISTENTE_UMBRAL_DIRECTO (0.75): sin
    # corroboracion hay que estar bastante seguro, pero no tanto como para
    # entregar la solucion tal cual sin que nadie la redacte.
    RECUPERACION_UMBRAL_SOLITARIO: float = float(
        os.getenv("RECUPERACION_UMBRAL_SOLITARIO", "0.70"))
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
    # Cuanto pesa en el orden que a la gente le haya servido un pasaje.
    #
    # El portal lleva preguntando "¿te sirvio?" bajo cada sugerencia desde el
    # principio y guardando la respuesta, pero eso solo alimentaba una metrica:
    # **la busqueda no se enteraba**. Un pasaje que ya resolvio el problema a
    # cinco personas se ordenaba igual que uno que nunca le sirvio a nadie.
    #
    # El valor va suavizado (regla de Laplace) para que un voto suelto no mande
    # nada al principio de la lista; ver `ajuste_por_utilidad`. Y es pequeno a
    # proposito: es una preferencia, no un veto. Nunca debe rescatar un pasaje
    # que no habla del tema ni hundir al unico que si. Por eso pesa menos que
    # la ventaja de una solucion general (0,05): que a alguien le sirviera es
    # senal mas debil que estar escrita para responder esa clase de pregunta.
    #
    # En 0 se apaga el lazo por completo y la busqueda vuelve a ordenar solo
    # por parecido.
    RECUPERACION_PESO_UTILIDAD: float = float(
        os.getenv("RECUPERACION_PESO_UTILIDAD", "0.03"))

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
    # Fallos seguidos antes de cerrarle a una cuenta la activacion por datos
    # personales. Cinco es holgado para quien se equivoca tecleando su fecha y
    # ridiculo para quien va probando: contra ~17 000 cumpleaños posibles, cinco
    # tiros no le dan ventaja a nadie. Al sexto hay que pedirle codigo a TI, y el
    # intento queda en la bitacora.
    ACTIVACION_MAX_INTENTOS: int = int(os.getenv("ACTIVACION_MAX_INTENTOS", "5"))
    # Cuanto vive el codigo de activacion que TI le entrega a la persona.
    CODIGO_ACTIVACION_HORAS: int = int(os.getenv("CODIGO_ACTIVACION_HORAS", "168"))
    # La activacion asistida se gasta en el mostrador, con la persona enfrente.
    # Dura minutos a proposito: no es un codigo para entregar.
    ACTIVACION_ASISTIDA_MINUTOS: int = int(os.getenv("ACTIVACION_ASISTIDA_MINUTOS", "20"))

    # --- Certificado TLS ---
    # Se vigila desde la pantalla de Estado porque vence en silencio, y un
    # certificado vencido no degrada nada: el navegador no deja entrar y ya.
    RUTA_CERTIFICADO: str = os.getenv("RUTA_CERTIFICADO", "/certs/portal.crt")
    CERTIFICADO_AVISO_DIAS: int = int(os.getenv("CERTIFICADO_AVISO_DIAS", "20"))
    # Cuantos datos personales hay que acertar para activar sin codigo.
    # Con 1, quien vea la lista de RH puede activar cuentas ajenas. Con 2 tiene
    # que conocer dos cosas distintas de esa persona en concreto. Si la cuenta
    # solo tiene uno registrado, se exige ese: no se puede pedir lo que no hay.
    VERIFICACION_FACTORES: int = int(os.getenv("VERIFICACION_FACTORES", "2"))
    # La longitud es lo que mas aporta a una contrasena y lo que la gente si
    # cumple sin apuntarla en un papel pegado al monitor.
    PASSWORD_MIN_LONGITUD: int = int(os.getenv("PASSWORD_MIN_LONGITUD", "10"))

    # --- Limite de intentos de inicio de sesion ---
    # Frena la prueba de contrasenas contra el portal. Dos frenos a la vez:
    #
    #   * Por cuenta (`LOGIN_MAX_INTENTOS`): el que protege a una persona.
    #   * Por IP (`LOGIN_MAX_INTENTOS_POR_IP`): frena a quien barre muchas
    #     cuentas. **Es mas alto a proposito**: por el acceso directo, Docker
    #     presenta a todos los clientes con la IP de su puerta de enlace, asi
    #     que "una IP" puede ser la planta entera. Con el mismo 8 que por
    #     cuenta, ocho contrasenas mal tecleadas por quien fuera dejaban a
    #     todos sin poder entrar cinco minutos. Solo cuentan los fallos.
    LOGIN_MAX_INTENTOS: int = int(os.getenv("LOGIN_MAX_INTENTOS", "8"))
    LOGIN_MAX_INTENTOS_POR_IP: int = int(os.getenv("LOGIN_MAX_INTENTOS_POR_IP", "40"))
    LOGIN_VENTANA_SEGUNDOS: int = int(os.getenv("LOGIN_VENTANA_SEGUNDOS", "300"))
    # Cuántos bcrypt de entrar, activar o cambiar contraseña corren a la vez,
    # cuántos esperan como mucho y cuánto. Ver `turno_de_hash` en
    # core/security.py: es lo que impide que una inundación de intentos desde
    # muchas IP se lleve toda la CPU. 4 de 16 núcleos son ~23 intentos por
    # segundo: el cambio de turno entero cabe sin esperar.
    HASH_EN_PARALELO: int = int(os.getenv("HASH_EN_PARALELO", "4"))
    HASH_COLA_MAXIMA: int = int(os.getenv("HASH_COLA_MAXIMA", "12"))
    HASH_ESPERA_S: float = float(os.getenv("HASH_ESPERA_S", "1"))
    # Las IP o redes públicas de la planta (separadas por comas; admite CIDR).
    # Lo que llega desde ahí por el camino de internet se trata como la red
    # interna: activa con datos personales, y sus fallos no cuentan contra un
    # freno por IP que compartiría la planta entera. Ver `es_red_de_planta` en
    # core/limitador.py. Vacío, todo lo de internet es público.
    REDES_DE_PLANTA: str = os.getenv("REDES_DE_PLANTA", "")
    # Lo mismo para la activacion de cuenta, que prueba fechas y codigos. Es
    # el freno de corto plazo; el bloqueo definitivo de la via por datos
    # personales es `ACTIVACION_MAX_INTENTOS`, mas arriba.
    ACTIVACION_FRENO_POR_CUENTA: int = int(os.getenv("ACTIVACION_FRENO_POR_CUENTA", "6"))
    ACTIVACION_FRENO_POR_IP: int = int(os.getenv("ACTIVACION_FRENO_POR_IP", "30"))
    ACTIVACION_FRENO_VENTANA_SEGUNDOS: int = int(os.getenv("ACTIVACION_FRENO_VENTANA_SEGUNDOS", "600"))

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
    # Tope de un cuerpo JSON (todo lo que no es subida de archivo). Ver
    # core/limite_cuerpo.py: el texto más largo del portal son 50 000 caracteres.
    CUERPO_JSON_MAX_KB: int = int(os.getenv("CUERPO_JSON_MAX_KB", "1024"))
    # Filas de un CSV de importación de personal. Cada alta nueva cifra su
    # código con bcrypt (~250 ms): sin tope, un archivo de 5 MB son decenas de
    # miles de filas y horas de servidor ocupado en una sola petición.
    IMPORTACION_MAX_FILAS: int = int(os.getenv("IMPORTACION_MAX_FILAS", "1000"))
    # Consultas a la IA por persona y minuto. La compuerta de `cola_ia` cuida
    # que el modelo no se ahogue, pero no reparte: un script de una sola
    # sesión mantenía la sala llena y la compuerta rechazaba a todos los demás.
    # Escribir un ticket dispara tres consultas por pausa; 60 no lo roza nadie
    # que teclee a mano.
    IA_PETICIONES_POR_MINUTO: int = int(os.getenv("IA_PETICIONES_POR_MINUTO", "60"))
    ADJUNTOS_MAX_POR_TICKET: int = int(os.getenv("ADJUNTOS_MAX_POR_TICKET", "5"))

    # --- Imagenes del conocimiento: pasos, base de conocimiento y soluciones ---
    #
    # Un paso que dice "pulse el boton de reinicio de la parte trasera" se
    # sigue a la primera con una foto de donde esta ese boton. Las imagenes
    # viven en una carpeta propia **dentro de ADJUNTOS_RUTA** (ver
    # api/imagenes.py): asi caen en el mismo volumen que ya se respalda, y las
    # pruebas, que aislan ADJUNTOS_RUTA en un temporal, no escriben nunca en el
    # disco de produccion.
    IMAGENES_MAX_MB: int = int(os.getenv("IMAGENES_MAX_MB", "10"))
    IMAGENES_MAX_POR_ELEMENTO: int = int(os.getenv("IMAGENES_MAX_POR_ELEMENTO", "8"))
    # Tope al abrir una imagen para quitarle los metadatos (core/metadatos.py):
    # se mira en la cabecera antes de descomprimir. 100 MP cubre la cámara de
    # cualquier celular y deja fuera las «bombas» de 40 000 × 40 000.
    # **Sumando los cuadros** de una animada: ver core/metadatos.py.
    IMAGENES_MAX_MEGAPIXELES: int = int(os.getenv("IMAGENES_MAX_MEGAPIXELES", "100"))
    # Cuántas imágenes se reescriben a la vez, y cuánto espera turno una subida
    # antes de recibir un 503. Cada una puede ocupar cientos de megas mientras
    # tanto: sin este límite, la memoria la decidía quien subiera más a la vez.
    IMAGENES_EN_PARALELO: int = int(os.getenv("IMAGENES_EN_PARALELO", "2"))
    IMAGENES_ESPERA_S: float = float(os.getenv("IMAGENES_ESPERA_S", "30"))

    # --- Catalogo visual: los problemas que se reconocen mirandolos ---
    #
    # "Mi copia sale borrosa" no se resuelve igual que "no manda a imprimir", y
    # la diferencia no la puede adivinar un modelo: la primera describe **algo
    # que se ve**, y para eso lo util no es un parrafo sino una foto. TI
    # documenta el defecto con su imagen; al usuario se le pregunta "¿se ve
    # asi?" antes de contestarle nada.
    VISUAL_RUTA: str = os.getenv("VISUAL_RUTA", "/app/adjuntos/visual")
    VISUAL_MAX_MB: int = int(os.getenv("VISUAL_MAX_MB", "10"))
    VISUAL_MAX_IMAGENES: int = int(os.getenv("VISUAL_MAX_IMAGENES", "12"))
    # Parecido minimo para ensenarle una ficha a alguien.
    #
    # **Medido contra el modelo de embeddings de esta planta**, con la ficha de
    # la copia borrosa ya escrita:
    #
    #     "mi copia sale borrosa desde ayer" ........... 0,80
    #     "no me deja entrar, cuenta bloqueada" ........ 0,58
    #
    # Veintidos puntos de separacion, asi que el corte va holgado en medio. Y
    # queda **por encima** del umbral general del asistente (0,62), que es al
    # reves de lo que parecia sensato al escribirlo: se puso en 0,55 pensando
    # que "preguntar no es responder" y que una foto de mas solo cuesta un
    # "no". El 0,58 del ruido dice que a esa altura la foto de mas no es rara:
    # es la de una cuenta bloqueada delante de alguien que preguntaba por una
    # impresora.
    #
    # La razon de que se pueda exigir mas aqui es que **una ficha esta escrita
    # para emparejar** —titulo, sintoma y las frases que usa la gente— mientras
    # que un ticket cuenta lo que paso un dia. El acierto sube a 0,80 donde el
    # de un ticket rondaba 0,69, asi que subir el liston no deja fuera nada
    # bueno.
    VISUAL_UMBRAL: float = float(os.getenv("VISUAL_UMBRAL", "0.65"))
    # Cuantas fotos se ensenan a la vez. Tres caben en pantalla de telefono y
    # se comparan de una mirada; con seis nadie compara, elige la primera.
    VISUAL_MAX_CANDIDATAS: int = int(os.getenv("VISUAL_MAX_CANDIDATAS", "3"))
    # Cuanto peor que la mejor puede ser una ficha y aun asi acompanarla.
    # Mas ancho que el margen de la recuperacion normal (0.04) por lo mismo de
    # arriba: aqui las opciones conviven en pantalla en vez de competir por ser
    # la unica respuesta, y dos fotos parecidas son justo lo que hay que
    # distinguir —borrosa y con sombra doble se describen igual y se arreglan
    # distinto—.
    VISUAL_MARGEN: float = float(os.getenv("VISUAL_MARGEN", "0.10"))

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
    # **20 s, y el 10 anterior estaba por debajo del caso normal.**
    #
    # Medido: clasificar tarda ~2,9 s cuando la instruccion sigue en la cache de
    # Ollama, y **11,5 a 12,8 s** cuando la llamada anterior llevaba otra
    # instruccion —una normalizacion de ticket, por ejemplo—, porque entonces
    # hay que releer el prompt entero a ~17 tokens/s.
    #
    # Con el timeout en 10 ese segundo caso **siempre se pasaba**: la
    # clasificacion devolvia None y el chat sacaba los desplegables. Desde fuera
    # se lee como "el bot no entiende"; en realidad no habia llegado a contestar.
    # Y el usuario pagaba los 10 s de espera igual.
    #
    # El numero viejo salio de una medicion que daba en la cache de prompt y por
    # eso parecia que clasificar costaba menos de un segundo. Ver la nota de
    # DESPLIEGUE.md sobre como medir esto sin enganarse.
    OLLAMA_TIMEOUT_CLASIFICACION: float = float(os.getenv("OLLAMA_TIMEOUT_CLASIFICACION", "20"))
    # Cuánto mantiene Ollama el modelo cargado en RAM tras la última petición.
    # Sin esto lo descarga a los 5 minutos y la siguiente consulta paga la
    # recarga completa: varios segundos que el usuario siente como "está trabado".
    # A cambio, qwen2.5:3b ocupa ~2 GB de RAM de forma permanente.
    OLLAMA_KEEP_ALIVE: str = os.getenv("OLLAMA_KEEP_ALIVE", "30m")

    # --- Aforo de la CPU: cuántas tareas de IA corren a la vez ---
    #
    # Aquí no hay GPU. La generación de qwen2.5:3b usa los ocho núcleos y va a
    # ~12 tokens/s; dos a la vez no van a 12 cada una sino a ~5, porque lo que
    # se satura es el ancho de banda a la RAM, no el reloj. El trabajo total
    # baja. Por eso el aforo de generación es **uno**: no es una limitación,
    # es lo que más saca de esta máquina.
    #
    # Ver app/services/cola_ia.py para el detalle.
    IA_AFORO_GENERACION: int = int(os.getenv("IA_AFORO_GENERACION", "1"))
    # Tope duro de cuántos pueden estar esperando a la vez. Es un límite de
    # hilos y memoria, no de paciencia: de la paciencia se encarga el
    # presupuesto de abajo, que es quien de verdad decide.
    #
    # **Ocho, y antes eran tres.** Con tres, la sala rechazaba mucho antes que
    # el presupuesto y lo dejaba sin efecto: desde que el modelo usa cuatro
    # hilos, una generación corriente tarda ~1.5 s, así que el cuarto que
    # llegaba se iba sin IA tras una espera estimada de **seis segundos** —y el
    # presupuesto dice que treinta están bien—. La sala mandaba, que es
    # justo lo contrario de lo que este diseño quiere.
    #
    # Con ocho, en el caso corriente decide la estimación: nueve turnos a 1.5 s
    # son 13 s, dentro del presupuesto. Y si el modelo se pone lento, la
    # estimación vuelve a rechazar sola —a 4 s por trabajo, nueve turnos son
    # 36 s y se pasa—, que es la autorregulación que se buscaba.
    #
    # El número no puede crecer sin freno: cada uno esperando retiene un hilo
    # del *pool*, y el de FastAPI trae cuarenta. Ocho deja margen de sobra.
    IA_SALA_GENERACION: int = int(os.getenv("IA_SALA_GENERACION", "8"))
    # **El presupuesto de espera.** Si lo que se estima que va a esperar quien
    # llega rebasa esto, no entra a la cola: se le contesta que no en el acto,
    # en cero segundos, y el portal sigue sin esa ayuda.
    #
    # La regla que hay detrás: **o se sirve pronto, o se dice que no pronto.
    # Nunca esperar y luego fallar**, que es pagar el costo de la cola sin
    # llevarse nada.
    #
    # Esto se intentó primero con un plazo fijo y falló dos veces por la misma
    # razón: un plazo fijo no sabe cuánto tarda una generación, y una
    # generación no tarda siempre lo mismo. Medido aquí (Ryzen 7 Pro, sin GPU,
    # qwen2.5:3b, num_predict=400), la misma consulta tardó 14 s una vez y
    # 20.7 s la siguiente. Con el plazo en 8 s se rendían todos justo antes de
    # que les tocara; subido a 20 s, la generación de 20.7 s volvió a dejar a
    # alguien esperando en balde. Cualquier constante la gana una lenta.
    #
    # Ahora la compuerta mide lo que tardan las generaciones de verdad y
    # estima; ver `app/services/cola_ia.py`. Este número dejó de ser un
    # cronómetro y pasó a ser una pregunta: **¿cuánto vale la pena esperar por
    # una ayuda opcional que aparece mientras se llena un formulario?** Treinta
    # segundos es generoso; más allá, la persona ya envió el ticket.
    IA_ESPERA_MAXIMA_GENERACION: float = float(
        os.getenv("IA_ESPERA_MAXIMA_GENERACION", "30"))
    # Cuánto se supone que tarda una generación mientras no haya ninguna medida
    # —los primeros segundos tras un reinicio—. En cuanto termina la primera,
    # manda lo medido y esto deja de usarse.
    #
    # Cuatro y no quince: medido en la ruta real, normalizar tarda 1.50 s,
    # clasificar 0.95 s y redactar 7.55 s. Quince era de cuando el modelo
    # repartía entre ocho hilos y nadie lo había medido con texto nuevo; tan
    # alto, en los segundos posteriores a un reinicio rechazaba a gente que
    # habría esperado tres segundos.
    IA_DURACION_INICIAL_GENERACION: float = float(
        os.getenv("IA_DURACION_INICIAL_GENERACION", "4"))

    # Los embeddings son otra cosa: ~80 ms contra ~4 s. Van en su propia
    # compuerta para que una búsqueda por similitud no quede atrapada detrás de
    # una redacción larga — la parte del portal que escala bien no tiene por
    # qué heredar la latencia de la que no.
    IA_AFORO_EMBEDDING: int = int(os.getenv("IA_AFORO_EMBEDDING", "2"))
    # Cuantos vectores se recuerdan para no volver a calcularlos.
    #
    # **Existe porque la misma frase se vectoriza varias veces en la misma
    # pantalla.** Al escribir la descripcion de un ticket, tres bloques
    # distintos consultan por separado —las sugerencias parecidas, la respuesta
    # del asistente y el catalogo visual— y cada uno mandaba el mismo texto al
    # modelo.
    #
    # Lo que cuesta un embedding aqui, medido con cinco frases reales: entre 74
    # y 579 ms, mediana 311. O sea que esa pantalla gastaba cerca de un segundo
    # de CPU **en cada pausa de escritura**, en la maquina donde la CPU es el
    # recurso escaso. Recordado, el segundo y el tercero cuestan 0.
    #
    # Un embedding es una funcion pura del texto y del modelo, asi que
    # recordarlo no cambia ninguna respuesta: solo quita el trabajo repetido.
    # 32 entradas cubren de sobra una pantalla en uso y ocupan menos de un
    # megabyte. En 0 se apaga.
    EMBEDDING_CACHE_MAX: int = int(os.getenv("EMBEDDING_CACHE_MAX", "32"))
    IA_SALA_EMBEDDING: int = int(os.getenv("IA_SALA_EMBEDDING", "8"))
    IA_ESPERA_MAXIMA_EMBEDDING: float = float(
        os.getenv("IA_ESPERA_MAXIMA_EMBEDDING", "3"))

    # --- Grafo de conciencia: la traza en vivo del razonamiento ---
    # Cuántos pasos se le guardan a una pantalla que va atrasada antes de
    # empezar a tirarlos. La traza es decorativa: perder un paso degrada la
    # animación, nunca la respuesta.
    TRAZA_COLA_MAXIMA: int = int(os.getenv("TRAZA_COLA_MAXIMA", "64"))
    # Cada cuánto se manda un ping por el WebSocket si no pasa nada. Sin esto,
    # un intermediario que no ve tráfico da la conexión por muerta y la corta.
    TRAZA_LATIDO_SEGUNDOS: float = float(os.getenv("TRAZA_LATIDO_SEGUNDOS", "20"))
    # Cuánto se espera el token en el primer mensaje del WebSocket. Es corto a
    # propósito: una conexión que se abre y no se identifica no tiene por qué
    # ocupar sitio.
    TRAZA_ESPERA_AUTENTICACION: float = float(
        os.getenv("TRAZA_ESPERA_AUTENTICACION", "10"))

    # Al arrancar, el backend pone el esquema al día. "si" (lo normal), "no"
    # (el worker y el receptor de sensores: migra solo el backend) o "sql"
    # (las pruebas: recorre las migraciones sin conectarse a ninguna base).
    MIGRAR_AL_ARRANCAR: str = os.getenv("MIGRAR_AL_ARRANCAR", "si")

    # --- Redis: limitadores, sesiones, avisos en vivo y cola de tareas ---
    #
    # **Opcional a propósito.** Sin REDIS_URL todo sigue funcionando como antes,
    # en memoria y dentro del proceso del backend: los limitadores cuentan por
    # proceso, cerrar sesión solo borra el token del navegador, y las tareas
    # (indexar un ticket, mandar un correo) se hacen en la misma petición. Con
    # Redis los limitadores valen para todos los procesos, cerrar sesión revoca
    # de verdad, el worker y el receptor de sensores pueden avisar a las
    # pantallas, y lo lento sale de la petición. Si Redis se cae a media
    # operación, el portal vuelve solo al modo en memoria (ver core/redis_cliente).
    REDIS_URL: str = os.getenv("REDIS_URL", "")

    # --- Alertas de SLA ---
    # Cuántos minutos antes del vencimiento se avisa a TI. El vigilante corre
    # cada minuto en el worker.
    SLA_AVISO_MINUTOS: int = int(os.getenv("SLA_AVISO_MINUTOS", "60"))
    # Una calificación de la atención igual o menor que esto abre una alerta.
    SATISFACCION_ALERTA_MAXIMA: int = int(os.getenv("SATISFACCION_ALERTA_MAXIMA", "2"))

    # --- Telemetría IoT (ESP32 por MQTT) ---
    MQTT_HOST: str = os.getenv("MQTT_HOST", "mosquitto")
    MQTT_PUERTO: int = int(os.getenv("MQTT_PUERTO", "1883"))
    # La cuenta con la que el receptor del portal lee del broker. Los equipos
    # usan otra (MQTT_DISPOSITIVO_*), que solo puede escribir telemetría.
    MQTT_USUARIO: str = os.getenv("MQTT_USUARIO", "portal")
    MQTT_PASSWORD: str = os.getenv("MQTT_PASSWORD", "")
    # portal/<clave de planta>/sensores/<clave del equipo>/telemetria
    MQTT_TEMA_TELEMETRIA: str = os.getenv("MQTT_TEMA_TELEMETRIA", "portal/+/sensores/+/telemetria")
    # Lecturas más seguidas que esto, del mismo equipo, se descartan: un ESP32
    # con un bucle sin pausa llenaría la tabla en horas.
    IOT_INTERVALO_MINIMO_S: int = int(os.getenv("IOT_INTERVALO_MINIMO_S", "5"))
    IOT_RETENCION_DIAS: int = int(os.getenv("IOT_RETENCION_DIAS", "90"))
    # Sin reportar en este tiempo, el equipo se da por caído y se avisa.
    IOT_SIN_SENAL_MINUTOS: int = int(os.getenv("IOT_SIN_SENAL_MINUTOS", "10"))
    # Tope de equipos que se registran solos. La contraseña de los sensores es
    # una para todos: sin tope, quien la tenga crea un equipo por cada clave
    # que se invente en el tema. Pasado el tope, uno nuevo se descarta hasta
    # que TI borre los que sobran o suba el número.
    IOT_MAX_DISPOSITIVOS: int = int(os.getenv("IOT_MAX_DISPOSITIVOS", "200"))
    # Umbrales por defecto (cada equipo puede tener los suyos).
    IOT_TEMPERATURA_MAX: float = float(os.getenv("IOT_TEMPERATURA_MAX", "35"))
    IOT_HUMEDAD_MAX: float = float(os.getenv("IOT_HUMEDAD_MAX", "70"))
    IOT_CALIDAD_AIRE_MAX: float = float(os.getenv("IOT_CALIDAD_AIRE_MAX", "1000"))

    model_config = SettingsConfigDict(case_sensitive=True, env_file=".env", extra="ignore")

settings = Settings()

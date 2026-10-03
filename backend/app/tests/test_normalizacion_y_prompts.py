"""La normalizacion: que corra, que no bloquee y que no cuele inventos.

Tres cosas llevaban rotas desde siempre y ninguna daba la cara, porque todo el
modulo de IA degrada en silencio a proposito:

  1. La normalizacion y la clasificacion se pasaban de su timeout de 10 s y
     fallaban en CADA ticket. La causa era el campo `system` de Ollama: con el,
     la cache del prompt no acierta nunca y se vuelve a leer todo (medido:
     90 tokens en 9,8 s con `system`, 0,0 s sin el).
  2. La normalizacion bloqueaba la creacion del ticket, asi que el usuario
     pagaba esos ~10 segundos para acabar guardando su texto original igual.
  3. Al arreglar 1 y 2, la normalizacion empezo a correr de verdad — y un
     modelo de 3B reescribiendo a veces inventa.
"""

import pytest

from app.core.config import settings
from app.models import Ticket
from app.services.asistente_service import AsistenteService
from app.services.kb_service import construir_texto_indexable
from app.services.ollama_client import (
    PROMPT_CLASIFICACION, PROMPT_NORMALIZACION, _instruir,
)


def token(client, email="user@test.com"):
    r = client.post("/api/auth/login", json={"email": email, "password": "Secret123!"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# ----------------------------------------------------------------------
# 1. El prompt va dentro del `prompt`, que es lo que hace que la cache sirva
# ----------------------------------------------------------------------

def test_la_instruccion_va_delante_y_el_texto_detras():
    """El orden **es** el arreglo, no un detalle de formato.

    llama.cpp reutiliza lo ya leido cuando el principio del texto coincide. Con
    la instruccion delante, el prefijo es identico en cada llamada y solo se
    procesa el reporte del usuario. Al reves no hay prefijo comun y se vuelve a
    pagar la lectura entera, que es de donde salian los 10 s de timeout.
    """
    salida = _instruir("INSTRUCCIONES AQUI", "el reporte del usuario")
    assert salida.startswith("INSTRUCCIONES AQUI")
    assert salida.endswith("el reporte del usuario")


def test_los_prompts_de_sistema_son_cortos():
    """Cada token del prompt se paga en las llamadas que no aciertan la cache.

    Medido: leer va a ~9-37 tok/s. El de clasificacion tenia 277 tokens para
    producir 18. No es un tope arbitrario: es que si alguien vuelve a escribir
    un parrafo aqui, vuelven los timeouts.
    """
    for nombre, prompt in (("clasificacion", PROMPT_CLASIFICACION),
                           ("normalizacion", PROMPT_NORMALIZACION)):
        palabras = len(prompt.split())
        assert palabras < 60, (
            f"el prompt de {nombre} crecio a {palabras} palabras; "
            "cada una se paga en cada consulta que falle la cache"
        )


def test_ninguna_llamada_usa_el_campo_system(monkeypatch):
    """La regresion que hay que impedir.

    Volver a poner `system` reintroduce el fallo exacto: la cache deja de
    acertar, las llamadas se pasan del timeout y la funcion falla en silencio
    en cada ticket. Se comprueba sobre el cuerpo que se manda de verdad.
    """
    import httpx
    enviados = []

    class RespuestaFalsa:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {"response": '{"categoria": "red", "confianza": 0.9}'}

    def capturar(self, url, json=None, **k):
        enviados.append(json)
        return RespuestaFalsa()

    monkeypatch.setattr(settings, "IA_HABILITADA", True)
    monkeypatch.setattr(httpx.Client, "post", capturar)

    from app.services.ollama_client import ollama
    ollama.normalizar_descripcion("no jala la cosa esa del anden dos otra vez")
    ollama.clasificar_categoria("no tengo ni idea de que le pasa a esto hoy")

    assert enviados, "no se mando ninguna peticion"
    for cuerpo in enviados:
        assert "system" not in cuerpo, (
            "volvio el campo `system`: la cache del prompt dejara de acertar "
            "y estas llamadas volveran a pasarse del timeout"
        )
        assert cuerpo["prompt"].startswith(("Reescribe", "Clasifica"))


# ----------------------------------------------------------------------
# 2. Crear un ticket no espera al modelo
# ----------------------------------------------------------------------

def test_crear_un_ticket_no_espera_a_la_normalizacion(client, monkeypatch):
    """El ticket se entrega sin que nadie haya llamado al modelo todavia.

    Antes la llamada iba en linea: el usuario esperaba lo que tardara Ollama
    —medido, entre 7 y 10 segundos— antes de ver su folio, y encima lo normal
    era que se pasara del timeout y se guardara la descripcion original de
    todas formas. Se pagaba la espera para no obtener nada.
    """
    llamadas = []
    monkeypatch.setattr(settings, "IA_HABILITADA", True)
    monkeypatch.setattr(
        "app.services.ollama_client.ollama.normalizar_descripcion",
        lambda texto: llamadas.append(texto) or "Texto reescrito por el modelo.")

    respuesta = client.post("/api/tickets", json={
        "sitio_id": 1, "categoria": "impresora",
        "descripcion_original": "no jala la impresora del anden 2 otra vez",
        "prioridad": "baja",
    }, headers=token(client))

    assert respuesta.status_code == 201
    # La respuesta sale sin la reescritura: llega despues, por detras.
    assert respuesta.json()["descripcion_normalizada"] is None


# ----------------------------------------------------------------------
# 3. Una reescritura que se va de tema se descarta
# ----------------------------------------------------------------------

@pytest.mark.parametrize("original,reescrito,pasa", [
    ("no jala la impresora del anden 2 y saca una raya negra en las etiquetas",
     "La impresora en el anden 2 no imprime y marca una raya negra en las etiquetas.",
     True),
    ("la laptop de almacen no enciende, solo prende el led naranja",
     "La laptop del almacen no enciende. Unicamente se ilumina el LED naranja.",
     True),
    # Se fue por completo a otro asunto: eso si se atrapa.
    ("no me deja entrar al correo electronico de la empresa",
     "Se recomienda revisar el cableado de red y reiniciar el switch del rack.",
     False),
])
def test_una_reescritura_que_habla_de_otra_cosa_se_descarta(original, reescrito, pasa):
    """El corte esta donde la medicion separa: irse de tema contra no irse.

    **No** pretende atrapar que el modelo cuele una frase plausible dentro de
    un texto correcto; medido, eso puntua igual que una reescritura buena. Para
    ese caso la defensa es otra: la descripcion original nunca se pisa.
    """
    anclaje = AsistenteService.anclaje_en_texto(reescrito, original)
    assert (anclaje >= settings.NORMALIZACION_ANCLAJE_MINIMO) is pasa, (
        f"anclaje {anclaje:.2f} contra umbral {settings.NORMALIZACION_ANCLAJE_MINIMO}"
    )


def test_lo_que_escribio_el_usuario_siempre_entra_al_indexado():
    """La reescritura se suma, no sustituye.

    Antes el texto indexado usaba `normalizada or original`, o sea que la unica
    copia buscable dependia de que el modelo no hubiera inventado nada. Y
    ademas se recupera mejor con las dos: la gente pregunta con las palabras de
    la planta ("no jala") y no con las del modelo ("no funciona correctamente").
    """
    ticket = Ticket(
        sitio_id=1, usuario_id=1, folio="T-IDX-1", categoria="impresora",
        descripcion_original="no jala la etiquetadora del anden 4",
        descripcion_normalizada="La etiquetadora del anden 4 no opera correctamente.",
        estado="resuelto", prioridad="media",
        solucion="Se limpio el cabezal y volvio a imprimir bien.",
    )
    texto = construir_texto_indexable(ticket)

    assert "no jala" in texto, "se perdio lo que escribio el usuario"
    assert "no opera correctamente" in texto, "se perdio la reescritura"
    assert "Se limpio el cabezal" in texto


# ----------------------------------------------------------------------
# 4. Una respuesta cortada no se entrega
# ----------------------------------------------------------------------

def test_una_respuesta_que_choco_con_el_tope_no_se_devuelve(monkeypatch):
    """Ollama contesta 200 aunque la respuesta se haya quedado a medias.

    Cuando el modelo agota `num_predict` se detiene donde iba, no donde
    terminaba, y el trozo llega con el mismo 200 que una respuesta entera. Se
    reprodujo con el tope real de producción (400) y una pregunta corriente
    sobre mantenimiento: el corte cayó en «1. **Limpie la pantalla y la».

    Media instrucción sobre un equipo físico, con aspecto de estar completa, es
    peor que ninguna: quien la lee no tiene forma de saber que le falta el
    final —que es donde suelen ir las advertencias—. Sin respuesta, la cascada
    sigue y el usuario recibe los extractos tal cual.
    """
    import httpx

    class Cortada:
        status_code = 200
        def raise_for_status(self): pass
        def json(self):
            return {"response": "1. Apague la impresora.\n2. **Limpie la pantalla y la",
                    "done_reason": "length", "eval_count": 400}

    monkeypatch.setattr(settings, "IA_HABILITADA", True)
    monkeypatch.setattr(httpx.Client, "post", lambda self, url, **k: Cortada())

    from app.services.ollama_client import ollama
    assert ollama.responder_texto("redacte el procedimiento") is None, (
        "se devolvió una respuesta cortada a media instrucción como si "
        "estuviera completa"
    )


def test_una_respuesta_completa_si_se_devuelve(monkeypatch):
    """El contrapeso: sin `done_reason: length` la respuesta pasa igual que antes.

    Sin esto, la comprobación de arriba se cumpliría también con un cliente
    que no devolviera nunca nada.
    """
    import httpx

    class Entera:
        status_code = 200
        def raise_for_status(self): pass
        def json(self):
            return {"response": "1. Apague la impresora.\n2. Limpie el cabezal.",
                    "done_reason": "stop", "eval_count": 18}

    monkeypatch.setattr(settings, "IA_HABILITADA", True)
    monkeypatch.setattr(httpx.Client, "post", lambda self, url, **k: Entera())

    from app.services.ollama_client import ollama
    assert ollama.responder_texto("redacte el procedimiento") == (
        "1. Apague la impresora.\n2. Limpie el cabezal.")


# ----------------------------------------------------------------------
# 5. Todas las llamadas de texto limitan los hilos
# ----------------------------------------------------------------------

def test_las_llamadas_al_modelo_de_texto_limitan_los_hilos(monkeypatch):
    """Sin `num_thread`, leer el prompt va seis veces más lento.

    Ollama reparte por defecto entre los ocho núcleos físicos, y en esta máquina
    eso hunde la lectura del prompt: 62,9 tokens/s con cuatro hilos contra 10,0
    con ocho. Como leer es la mitad o más de cada llamada, el efecto es grande
    —clasificar pasa de 2,78 s a 0,95 s—.

    Lo que hay que impedir es que una llamada nueva se escriba sin la opción y
    se quede sola en el reparto lento, que no fallaría: solo iría despacio, y
    eso no se nota mirando.
    """
    import httpx

    enviados = []

    class RespuestaFalsa:
        status_code = 200
        def raise_for_status(self): pass
        def json(self):
            return {"response": '{"categoria": "red", "confianza": 0.9}',
                    "done_reason": "stop"}

    def capturar(self, url, json=None, **k):
        enviados.append((url, json))
        return RespuestaFalsa()

    monkeypatch.setattr(settings, "IA_HABILITADA", True)
    monkeypatch.setattr(httpx.Client, "post", capturar)

    from app.services.ollama_client import ollama
    ollama.normalizar_descripcion("no jala la cosa del anden dos")
    # Una frase que **no** dispare el atajo por vocabulario: si lo dispara,
    # clasifica sin llamar al modelo —que es lo correcto— y la llamada que se
    # quiere inspeccionar no llega a existir.
    ollama.clasificar_categoria("eso de ayer volvio a pasar otra vez aqui")
    ollama.responder_texto("redacte el procedimiento")
    ollama.responder_json("proponga el mapeo")

    generaciones = [c for url, c in enviados if url.endswith("/api/generate")]
    assert len(generaciones) == 4, f"se esperaban 4 llamadas de texto, hubo {len(generaciones)}"
    for cuerpo in generaciones:
        assert cuerpo["options"].get("num_thread") == settings.OLLAMA_HILOS_TEXTO, (
            "una llamada al modelo de texto salió sin `num_thread`: irá seis "
            "veces más lenta al leer el prompt y nada lo delatará"
        )


def test_los_embeddings_no_limitan_los_hilos(monkeypatch):
    """El contrapeso, y no es simetría por gusto: está medido.

    Con el modelo de embeddings el reparto por defecto gana —0,043 s contra
    0,063 s con cuatro hilos—. Son veinte milisegundos, pero no hay razón para
    empeorarlos.
    """
    import httpx

    enviados = []

    class RespuestaFalsa:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {"embedding": [0.1] * 768}

    def capturar(self, url, json=None, **k):
        enviados.append((url, json))
        return RespuestaFalsa()

    monkeypatch.setattr(settings, "IA_HABILITADA", True)
    monkeypatch.setattr(httpx.Client, "post", capturar)

    from app.services.ollama_client import ollama
    ollama.generar_embedding("la impresora saca rayas negras", tarea="consulta")

    assert enviados, "no se mandó ninguna petición de embedding"
    for _, cuerpo in enviados:
        assert "num_thread" not in (cuerpo.get("options") or {}), (
            "el embedding salió con `num_thread`: medido, ahí el reparto por "
            "defecto es más rápido"
        )

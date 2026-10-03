"""Chatbot flotante.

El chat solo sustituye el paso de elegir categoría. Nunca decide reglas de
negocio, nunca atrapa a nadie en un bot, y si Ollama no está simplemente
desaparece.
"""

import pytest

from app.core.config import settings
from app.models import ChatSesion
from app.services.chat_service import (
    ACCION_FLUJO,
    ACCION_NO_DISPONIBLE,
    ACCION_PEDIR,
    ACCION_TICKET,
)
from app.services.ollama_client import OllamaClient, ollama


def get_token(client, email="user@test.com", password="Secret123!"):
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    return response.json()["access_token"]


def headers(client, email="user@test.com"):
    return {"Authorization": f"Bearer {get_token(client, email=email)}"}


@pytest.fixture
def ollama_activo(monkeypatch):
    """Ollama disponible; la clasificación se controla desde cada prueba."""
    monkeypatch.setattr(settings, "IA_HABILITADA", True)
    monkeypatch.setattr(ollama, "disponible", lambda: True)
    return monkeypatch


def clasificar_como(monkeypatch, categoria, confianza):
    monkeypatch.setattr(
        ollama,
        "clasificar_categoria",
        lambda texto: {"categoria": categoria, "confianza": confianza},
    )


def no_clasifica(monkeypatch):
    monkeypatch.setattr(ollama, "clasificar_categoria", lambda texto: None)


# ----------------------------------------------------------------------
# Degradación: si Ollama no está, el widget se oculta
# ----------------------------------------------------------------------
def test_el_widget_se_oculta_sin_ollama(client):
    """La suite corre con IA_HABILITADA=False, que es el caso de Ollama caído."""
    respuesta = client.get("/api/chat/estado", headers=headers(client))

    assert respuesta.status_code == 200
    assert respuesta.json()["disponible"] is False


def test_el_mensaje_degrada_sin_error(client):
    respuesta = client.post(
        "/api/chat/mensaje",
        json={"mensaje": "no me imprime la etiquetadora de embarques"},
        headers=headers(client),
    )

    # 200, nunca un 500 ni un error de IA en pantalla.
    assert respuesta.status_code == 200
    assert respuesta.json()["accion"] == ACCION_NO_DISPONIBLE


def test_lo_escrito_no_se_pierde_al_degradar(client):
    """El texto vuelve como descripción sugerida para prellenar el formulario."""
    texto = "la impresora de embarques no responde desde ayer"
    respuesta = client.post(
        "/api/chat/mensaje", json={"mensaje": texto}, headers=headers(client)
    ).json()

    assert texto in respuesta["descripcion_sugerida"]


# ----------------------------------------------------------------------
# Clasificación
# ----------------------------------------------------------------------
def test_clasificacion_con_confianza_entra_al_flujo(client, ollama_activo):
    clasificar_como(ollama_activo, "impresora", 0.92)

    respuesta = client.post(
        "/api/chat/mensaje",
        json={"mensaje": "la etiquetadora no saca etiquetas"},
        headers=headers(client),
    ).json()

    assert respuesta["accion"] == ACCION_FLUJO
    assert respuesta["categoria"] == "impresora"
    assert respuesta["confianza"] == 0.92


def test_confianza_baja_pide_los_dropdowns(client, ollama_activo):
    """Sin confianza no se adivina: se le pregunta al usuario."""
    clasificar_como(ollama_activo, "otro", 0.30)

    respuesta = client.post(
        "/api/chat/mensaje", json={"mensaje": "no sirve"}, headers=headers(client)
    ).json()

    assert respuesta["accion"] == ACCION_PEDIR
    # No se propone una categoría en la que no se confía.
    assert respuesta["categoria"] is None
    assert set(respuesta["categorias"]) == {
        "impresora", "red", "equipo", "software", "accesos", "otro"
    }


def test_justo_en_el_umbral_se_acepta(client, ollama_activo):
    clasificar_como(ollama_activo, "red", settings.CHAT_UMBRAL_CONFIANZA)

    respuesta = client.post(
        "/api/chat/mensaje", json={"mensaje": "no hay wifi"}, headers=headers(client)
    ).json()

    assert respuesta["accion"] == ACCION_FLUJO


# ----------------------------------------------------------------------
# Máximo 3 intercambios
# ----------------------------------------------------------------------
def test_a_la_tercera_sin_clasificar_se_crea_ticket(client, ollama_activo):
    no_clasifica(ollama_activo)
    cabeceras = headers(client)

    sesion_id = None
    acciones = []
    for i in range(settings.CHAT_MAX_INTERCAMBIOS):
        respuesta = client.post(
            "/api/chat/mensaje",
            json={"mensaje": f"algo no funciona {i}", "sesion_id": sesion_id},
            headers=cabeceras,
        ).json()
        sesion_id = respuesta["sesion_id"]
        acciones.append(respuesta["accion"])

    # Los primeros piden categoría; el último escala.
    assert acciones[:-1] == [ACCION_PEDIR] * (settings.CHAT_MAX_INTERCAMBIOS - 1)
    assert acciones[-1] == ACCION_TICKET


def test_la_sesion_agotada_no_se_reabre(client, ollama_activo, db_session):
    """Tras escalar, un mensaje nuevo empieza una sesión distinta."""
    no_clasifica(ollama_activo)
    cabeceras = headers(client)

    sesion_id = None
    for i in range(settings.CHAT_MAX_INTERCAMBIOS):
        sesion_id = client.post(
            "/api/chat/mensaje",
            json={"mensaje": f"mensaje {i}", "sesion_id": sesion_id},
            headers=cabeceras,
        ).json()["sesion_id"]

    siguiente = client.post(
        "/api/chat/mensaje",
        json={"mensaje": "otra incidencia distinta", "sesion_id": sesion_id},
        headers=cabeceras,
    ).json()

    assert siguiente["sesion_id"] != sesion_id
    assert siguiente["intercambios"] == 1


# ----------------------------------------------------------------------
# Contexto: dentro de la incidencia, no entre incidencias
# ----------------------------------------------------------------------
def test_el_contexto_se_acumula_dentro_de_la_sesion(client, ollama_activo):
    vistos = []
    ollama_activo.setattr(
        ollama, "clasificar_categoria", lambda texto: vistos.append(texto) or None
    )
    cabeceras = headers(client)

    primera = client.post(
        "/api/chat/mensaje", json={"mensaje": "la impresora"}, headers=cabeceras
    ).json()
    client.post(
        "/api/chat/mensaje",
        json={"mensaje": "no saca nada", "sesion_id": primera["sesion_id"]},
        headers=cabeceras,
    )

    # El segundo mensaje se clasifica con todo lo escrito en esa incidencia.
    assert vistos[0] == "la impresora"
    assert "la impresora" in vistos[1] and "no saca nada" in vistos[1]


def test_el_contexto_no_cruza_entre_incidencias(client, ollama_activo):
    vistos = []
    ollama_activo.setattr(
        ollama, "clasificar_categoria", lambda texto: vistos.append(texto) or None
    )
    cabeceras = headers(client)

    client.post("/api/chat/mensaje", json={"mensaje": "la impresora"}, headers=cabeceras)
    # Sin sesion_id: incidencia nueva.
    client.post("/api/chat/mensaje", json={"mensaje": "no tengo red"}, headers=cabeceras)

    assert "impresora" not in vistos[1]


def test_no_se_continua_la_sesion_de_otro(client, ollama_activo):
    no_clasifica(ollama_activo)

    ajena = client.post(
        "/api/chat/mensaje",
        json={"mensaje": "mi problema privado"},
        headers=headers(client, "user@test.com"),
    ).json()["sesion_id"]

    propia = client.post(
        "/api/chat/mensaje",
        json={"mensaje": "otra cosa", "sesion_id": ajena},
        headers=headers(client, "admin@test.com"),
    ).json()

    # Se ignora la sesión ajena y se abre una nueva, sin filtrar su contexto.
    assert propia["sesion_id"] != ajena
    assert "privado" not in propia["descripcion_sugerida"]


# ----------------------------------------------------------------------
# Nunca atrapar a alguien en un bot
# ----------------------------------------------------------------------
def test_hablar_con_un_tecnico_siempre_escala(client, ollama_activo):
    no_clasifica(ollama_activo)
    cabeceras = headers(client)

    sesion_id = client.post(
        "/api/chat/mensaje", json={"mensaje": "algo raro pasa"}, headers=cabeceras
    ).json()["sesion_id"]

    respuesta = client.post(
        "/api/chat/escalar", json={"sesion_id": sesion_id}, headers=cabeceras
    ).json()

    assert respuesta["accion"] == ACCION_TICKET
    assert "algo raro pasa" in respuesta["descripcion_sugerida"]


def test_se_puede_escalar_sin_sesion(client):
    """El botón funciona aunque el usuario no haya escrito nada."""
    respuesta = client.post("/api/chat/escalar", json={}, headers=headers(client))

    assert respuesta.status_code == 200
    assert respuesta.json()["accion"] == ACCION_TICKET


# ----------------------------------------------------------------------
# La IA no decide reglas de negocio
# ----------------------------------------------------------------------
def test_la_categoria_del_chat_no_salta_las_reglas(client, ollama_activo, db_session):
    """El chat elige categoría; el motor de reglas sigue mandando.

    La regla de impresora manda a proveedor, y eso lo decide la tabla de
    reglas al crear el ticket, no el modelo.
    """
    from app.models import ReglaNegocio

    db_session.add(ReglaNegocio(
        sitio_id=1,
        categoria="impresora",
        condicion="*",
        accion="proveedor",
        destinatario="proveedor@ejemplo.com",
        activa=True,
    ))
    db_session.commit()

    clasificar_como(ollama_activo, "impresora", 0.95)
    cabeceras = headers(client)

    chat = client.post(
        "/api/chat/mensaje",
        json={"mensaje": "la etiquetadora no imprime"},
        headers=cabeceras,
    ).json()
    assert chat["categoria"] == "impresora"

    # El ticket se crea con esa categoría y la regla se aplica igual.
    ticket = client.post(
        "/api/tickets",
        json={
            "sitio_id": 1,
            "categoria": chat["categoria"],
            "descripcion_original": chat["descripcion_sugerida"],
            "prioridad": "media",
        },
        headers=cabeceras,
    ).json()

    assert ticket["estado"] == "espera_proveedor"
    assert ticket["canal_resolucion"] == "proveedor"


# ----------------------------------------------------------------------
# El parser aguanta lo que devuelva un modelo pequeño
# ----------------------------------------------------------------------
@pytest.mark.parametrize("crudo", [
    "",
    "no soy JSON",
    '{"categoria": "impresora"}',                    # sin confianza
    '{"confianza": 0.9}',                            # sin categoría
    '{"categoria": "cafetera", "confianza": 0.9}',   # categoría inventada
    '{"categoria": "red", "confianza": 1.7}',        # confianza fuera de rango
    '{"categoria": "red", "confianza": -0.2}',
    '{"categoria": "red", "confianza": "mucha"}',    # confianza no numérica
    '{"categoria": null, "confianza": null}',
])
def test_el_parser_rechaza_basura(crudo):
    assert OllamaClient._parsear_clasificacion(crudo) is None


@pytest.mark.parametrize("crudo,esperado", [
    ('{"categoria": "red", "confianza": 0.8}', ("red", 0.8)),
    ('  {"categoria": "ACCESOS", "confianza": 0.5}  ', ("accesos", 0.5)),
    # A veces el modelo envuelve el JSON en prosa.
    ('Claro: {"categoria": "equipo", "confianza": 0.75} espero que ayude',
     ("equipo", 0.75)),
])
def test_el_parser_acepta_lo_valido(crudo, esperado):
    resultado = OllamaClient._parsear_clasificacion(crudo)
    assert (resultado["categoria"], resultado["confianza"]) == esperado


# ----------------------------------------------------------------------
# Corte previo: un texto sin contenido no se le pregunta al modelo
#
# Medido contra qwen2.5:3b real: a "no sirve" le asigna categoría "equipo" con
# 0.9 de confianza. La confianza que se auto-reporta un modelo pequeño no
# distingue lo que sabe de lo que supone, así que el corte es determinista.
# ----------------------------------------------------------------------
@pytest.mark.parametrize("vago", [
    "no sirve", "ayuda", "ya no jala", "esta mal", "no funciona nada", "tengo un problema",
])
def test_texto_sin_contenido_no_llega_al_modelo(vago, monkeypatch):
    monkeypatch.setattr(settings, "IA_HABILITADA", True)
    llamadas = []
    cliente = OllamaClient(host="http://127.0.0.1:1")
    monkeypatch.setattr(cliente, "_parsear_clasificacion", lambda c: llamadas.append(c))

    assert cliente.clasificar_categoria(vago) is None
    # Ni siquiera se intentó la llamada: se cortó antes.
    assert llamadas == []


@pytest.mark.parametrize("concreto,esperada", [
    ("la etiquetadora de embarques no saca etiquetas", "impresora"),
    ("no hay internet en el area de calidad", "red"),
    ("se me olvido la contrasena del correo", "accesos"),
    ("el monitor de la estacion 4 no da imagen", "equipo"),
])
def test_el_vocabulario_clasifica_sin_ollama(concreto, esperada, monkeypatch):
    """El atajo por vocabulario funciona aunque Ollama esté caído.

    Es la ventaja de no depender del modelo para lo que ya se sabe: instantáneo,
    y sobrevive a una caída de Ollama.
    """
    monkeypatch.setattr(settings, "IA_HABILITADA", True)
    cliente = OllamaClient(host="http://127.0.0.1:1")

    resultado = cliente.clasificar_categoria(concreto)
    assert resultado is not None
    assert resultado["categoria"] == esperada


def test_el_vocabulario_no_decide_ante_un_empate():
    """'La impresora no aparece en la red' toca dos mundos: que decida el modelo."""
    assert OllamaClient.clasificar_por_vocabulario("la impresora no aparece en la red") is None


def test_sin_vocabulario_conocido_se_consulta_al_modelo(monkeypatch):
    """Texto con contenido pero sin palabras conocidas: el corte no aplica y se
    intenta la llamada, que aquí falla por host muerto."""
    monkeypatch.setattr(settings, "IA_HABILITADA", True)
    cliente = OllamaClient(host="http://127.0.0.1:1")

    texto = "el gafete no me abre la puerta del almacen general"
    assert cliente.clasificar_por_vocabulario(texto) is None
    assert cliente.clasificar_categoria(texto) is None


def test_el_chat_pide_dropdowns_ante_un_mensaje_vago(client, ollama_activo):
    """De punta a punta: mensaje vago -> dropdowns, sin adivinar categoría."""
    ollama_activo.setattr(settings, "IA_HABILITADA", True)
    # Se usa el clasificador real (con host muerto da None, igual que el corte).
    ollama_activo.setattr(ollama, "clasificar_categoria",
                          lambda texto: OllamaClient(host="http://127.0.0.1:1").clasificar_categoria(texto))

    respuesta = client.post(
        "/api/chat/mensaje", json={"mensaje": "no sirve"}, headers=headers(client)
    ).json()

    assert respuesta["accion"] == ACCION_PEDIR
    assert respuesta["categoria"] is None


def test_clasificar_no_levanta_con_host_muerto(monkeypatch):
    """Sin vocabulario conocido tiene que llamar al modelo, y con el host muerto
    devuelve None en lugar de reventar."""
    monkeypatch.setattr(settings, "IA_HABILITADA", True)
    cliente = OllamaClient(host="http://127.0.0.1:1")

    assert cliente.clasificar_categoria("el gafete no me abre la puerta del almacen") is None


def test_la_sesion_guarda_el_historial(client, ollama_activo, db_session):
    clasificar_como(ollama_activo, "red", 0.9)

    sesion_id = client.post(
        "/api/chat/mensaje", json={"mensaje": "sin internet en calidad"}, headers=headers(client)
    ).json()["sesion_id"]

    sesion = db_session.query(ChatSesion).filter(ChatSesion.id == sesion_id).first()
    assert sesion.categoria_detectada == "red"
    assert sesion.confianza == 0.9
    assert any(m["rol"] == "usuario" and m["texto"] == "sin internet en calidad"
               for m in sesion.mensajes)


# ----------------------------------------------------------------------
# El mensaje tiene tope, y el tope protege a los demás
# ----------------------------------------------------------------------

def test_un_mensaje_enorme_se_rechaza(client):
    """Sin tope, un pegado bloquea la IA de toda la planta.

    El mensaje va al modelo dos veces —a buscar en el conocimiento y a
    clasificar— y la generación tiene aforo 1: mientras dura, nadie más tiene
    asistente. Medido en esta planta, 20 000 caracteres llenan la ventana de
    contexto de Ollama y cuestan **150 segundos**. Dos minutos y medio de IA
    parada, con un solo pegado.

    Y no compra nada: pasada esa ventana Ollama recorta en silencio, así que el
    texto de más ni siquiera se lee.
    """
    respuesta = client.post(
        "/api/chat/mensaje",
        json={"mensaje": "no jala la impresora " * 2000},   # ~42 000 caracteres
        headers=headers(client),
    )
    assert respuesta.status_code == 422, (
        f"se aceptó un mensaje de 42 000 caracteres ({respuesta.status_code})"
    )


def test_un_mensaje_normal_pasa(client):
    """El contrapeso: el tope no puede estorbar a quien describe una avería.

    Sin esto, la prueba de arriba se cumpliría con un endpoint que rechazara
    todo.
    """
    respuesta = client.post(
        "/api/chat/mensaje",
        json={"mensaje": "no jala la impresora del anden 2 y saca rayas negras"},
        headers=headers(client),
    )
    assert respuesta.status_code == 200, respuesta.text


def test_un_mensaje_vacio_se_rechaza(client):
    """Un mensaje en blanco no tiene nada que clasificar y gastaría un turno
    de la cola igual que uno de verdad."""
    respuesta = client.post(
        "/api/chat/mensaje", json={"mensaje": ""}, headers=headers(client),
    )
    assert respuesta.status_code == 422


def test_el_timeout_de_clasificar_cubre_el_caso_de_cache_fria():
    """El número no puede quedar por debajo de lo que la operación tarda.

    Clasificar tarda ~2,9 s cuando la instrucción sigue en la caché de prompt
    de Ollama, y **11,5 a 12,8 s** medidos cuando la llamada anterior llevaba
    otra instrucción —una normalización de ticket, por ejemplo— y hay que
    releer el prompt entero a ~17 tokens/s.

    Con el timeout en 10 s ese segundo caso se pasaba **siempre**: la
    clasificación devolvía None y el chat sacaba los desplegables. Desde fuera
    se lee como «el bot no entiende», cuando en realidad no había llegado a
    contestar — y el usuario pagaba la espera completa igual.

    Esta prueba no mide nada: fija el suelo para que nadie lo baje sin haber
    vuelto a medir.
    """
    from app.core.config import settings

    assert settings.OLLAMA_TIMEOUT_CLASIFICACION >= 15, (
        "el timeout de clasificación quedó por debajo del caso de caché fría "
        "(11-13 s medidos): el chat degradará a desplegables en cada consulta "
        "que siga a una normalización"
    )

"""La traza del grafo: que cada quien vea la suya y nada mas.

El canal de avisos del portal (`eventos_service`) reparte a todo un sitio, y
por eso no lleva datos: un evento es la palabra `tickets` y punto. Este otro si
lleva detalle —cuantos pasajes se encontraron, que tan parecidos, cuanto tardo
cada salto— y puede permitirselo **solo** porque va a una sola persona: la que
hizo la consulta, que esta recibiendo esa misma informacion en la respuesta.

Si ese aislamiento se rompiera, el canal pasaria de ser una ventana a la
consulta propia a filtrar la actividad ajena. De ahi que sea lo primero que se
prueba, y no un detalle de implementacion.

Lo segundo es que la traza **no puede romper la consulta**. Es decorativa: si
falla, se pierde la animacion, nunca la respuesta.
"""

import asyncio

import pytest

from app.services import traza_service
from app.services.traza_service import DifusorTraza, Traza


@pytest.fixture
def difusor_limpio():
    """Un difusor propio por prueba, atado al bucle que corre en ese momento.

    El del modulo es estado de proceso y se comparte entre pruebas; usarlo
    directamente haria que el resultado dependiera del orden.
    """
    return DifusorTraza()


def _vaciar(cola):
    recogidos = []
    while not cola.empty():
        recogidos.append(cola.get_nowait())
    return recogidos


@pytest.mark.asyncio
async def test_los_pasos_solo_llegan_a_quien_hizo_la_consulta(difusor_limpio, monkeypatch):
    """Ana pregunta; Beto no se entera de nada.

    Es la garantia entera de este canal. Sin ella, cualquiera con el portal
    abierto veria pasar la actividad de sus companeros.
    """
    difusor_limpio.iniciar(asyncio.get_running_loop())
    monkeypatch.setattr(traza_service, "difusor_traza", difusor_limpio)

    ana, beto = 11, 22
    cola_ana = difusor_limpio.suscribir(ana)
    cola_beto = difusor_limpio.suscribir(beto)

    Traza(ana).paso("conocimiento", "listo", pasajes=3, similitud=0.81)
    # `call_soon_threadsafe` encola el reparto en el bucle: hay que cederle el
    # turno para que se ejecute antes de mirar las colas.
    await asyncio.sleep(0)

    de_ana = _vaciar(cola_ana)
    de_beto = _vaciar(cola_beto)

    assert len(de_ana) == 1
    assert de_ana[0]["nodo"] == "conocimiento"
    assert de_ana[0]["detalle"]["pasajes"] == 3
    assert de_beto == [], "a Beto le llego la traza de una consulta ajena"


@pytest.mark.asyncio
async def test_la_linea_se_encadena_sola(difusor_limpio, monkeypatch):
    """Cada paso sabe de que nodo viene sin que haya que repetirselo.

    Es lo que permite que el grafo dibuje el camino completo: quien emite dice
    'enciende el conocimiento' y la linea desde la vectorizacion sale sola.
    """
    difusor_limpio.iniciar(asyncio.get_running_loop())
    monkeypatch.setattr(traza_service, "difusor_traza", difusor_limpio)

    cola = difusor_limpio.suscribir(7)
    traza = Traza(7)
    traza.paso("usuario", "listo")
    traza.paso("embedding", "listo")
    traza.paso("conocimiento", "listo")
    await asyncio.sleep(0)

    pasos = _vaciar(cola)
    assert [p["nodo"] for p in pasos] == ["usuario", "embedding", "conocimiento"]
    assert pasos[1]["desde"] == "usuario"
    assert pasos[2]["desde"] == "embedding"
    # Todos comparten el identificador de la consulta: es lo que evita que dos
    # preguntas seguidas se pinten mezcladas.
    assert len({p["traza"] for p in pasos}) == 1


@pytest.mark.asyncio
async def test_un_nodo_activo_no_mueve_el_cursor(difusor_limpio, monkeypatch):
    """Mientras un nodo trabaja, el siguiente todavia viene del anterior.

    El cursor solo avanza cuando un nodo queda `listo` u `omitido`. Si avanzara
    con `activo`, un nodo que se enciende y falla dejaria la linea saliendo de
    el hacia ninguna parte.
    """
    difusor_limpio.iniciar(asyncio.get_running_loop())
    monkeypatch.setattr(traza_service, "difusor_traza", difusor_limpio)

    cola = difusor_limpio.suscribir(7)
    traza = Traza(7)
    traza.paso("usuario", "listo")
    traza.paso("embedding", "activo")     # no avanza el cursor
    traza.paso("embedding", "error")      # tampoco
    traza.paso("conocimiento", "omitido")
    await asyncio.sleep(0)

    pasos = _vaciar(cola)
    assert pasos[1]["desde"] == "usuario"
    assert pasos[2]["desde"] == "usuario"
    assert pasos[3]["desde"] == "usuario", "el cursor avanzo con un nodo que fallo"


@pytest.mark.asyncio
async def test_una_pantalla_lenta_no_frena_la_consulta(difusor_limpio, monkeypatch):
    """Con la cola llena se tiran pasos, y publicar sigue sin levantar.

    Perder un fotograma de la animacion es aceptable. Que una pantalla atrasada
    bloquee la consulta que la origino, no.
    """
    difusor_limpio.iniciar(asyncio.get_running_loop())
    monkeypatch.setattr(traza_service, "difusor_traza", difusor_limpio)

    cola = difusor_limpio.suscribir(7)
    # Se llena a mano hasta el tope declarado.
    for _ in range(cola.maxsize):
        cola.put_nowait({"relleno": True})

    traza = Traza(7)
    for _ in range(20):
        traza.paso("conocimiento", "listo")   # no debe levantar
    await asyncio.sleep(0)

    assert cola.qsize() == cola.maxsize


@pytest.mark.asyncio
async def test_un_nodo_inventado_se_ignora(difusor_limpio, monkeypatch):
    """Un nombre que el grafo no dibuja no se reparte.

    Es la red contra un `paso("io_local", ...)` mal escrito: sin esto el evento
    viajaria hasta el navegador y ahi no encenderia nada, sin rastro de por que.
    """
    difusor_limpio.iniciar(asyncio.get_running_loop())
    monkeypatch.setattr(traza_service, "difusor_traza", difusor_limpio)

    cola = difusor_limpio.suscribir(7)
    Traza(7).paso("io_local", "listo")
    Traza(7).paso("conocimiento", "flotando")
    await asyncio.sleep(0)

    assert _vaciar(cola) == []


@pytest.mark.asyncio
async def test_sin_nadie_mirando_no_se_guarda_nada(difusor_limpio, monkeypatch):
    """Sin pantallas suscritas, publicar no acumula nada en memoria.

    Es el caso normal: casi nadie tiene el grafo abierto. Si cada consulta
    dejara su traza guardada por si acaso, el proceso creceria sin parar.
    """
    difusor_limpio.iniciar(asyncio.get_running_loop())
    monkeypatch.setattr(traza_service, "difusor_traza", difusor_limpio)

    assert difusor_limpio.hay_alguien(99) is False
    for _ in range(100):
        Traza(99).paso("conocimiento", "listo")
    await asyncio.sleep(0)

    assert difusor_limpio.conectados == 0


@pytest.mark.asyncio
async def test_al_desconectarse_no_queda_rastro(difusor_limpio):
    """Cerrar la pestana libera la entrada, no solo la cola.

    Sin el borrado de la clave vacia, el diccionario acumularia una entrada por
    cada persona que haya abierto el portal desde el ultimo reinicio.
    """
    difusor_limpio.iniciar(asyncio.get_running_loop())

    cola = difusor_limpio.suscribir(42)
    assert difusor_limpio.hay_alguien(42) is True

    difusor_limpio.cancelar(42, cola)
    assert difusor_limpio.hay_alguien(42) is False
    assert difusor_limpio.conectados == 0
    assert 42 not in difusor_limpio._suscriptores

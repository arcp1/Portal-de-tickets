"""El canal de avisos en vivo.

Se prueba el difusor por debajo y la puerta por arriba. Lo que **no** se prueba
aquí es el flujo completo con un cliente conectado: mantener abierta una
respuesta de streaming dentro de `TestClient` es una forma conocida de dejar la
suite colgada, y el valor de esa prueba no compensa el riesgo. Lo que importa
—que el evento llega y que respeta el sitio— se comprueba en las piezas.
"""

import asyncio

import pytest

from app.services.eventos_service import Difusor, COLA_MAXIMA


def test_sin_bucle_publicar_no_revienta():
    """Publicar antes de que arranque la aplicación no puede tumbar nada.

    `publicar()` se llama desde dentro de rutas que crean tickets. Si un fallo
    de arranque dejara el difusor sin bucle, la alternativa a tragarse el aviso
    sería que reventara la creación del ticket — perder el dato por no poder
    avisar de él, que es exactamente al revés de lo que importa.
    """
    difusor = Difusor()
    difusor.publicar(1, "tickets")  # no debe levantar


@pytest.mark.asyncio
async def test_el_aviso_llega_a_todos_los_suscriptores():
    difusor = Difusor()
    difusor.iniciar(asyncio.get_running_loop())

    uno, dos = difusor.suscribir(), difusor.suscribir()
    difusor.publicar(7, "tickets")
    # `call_soon_threadsafe` encola para el siguiente ciclo del bucle.
    await asyncio.sleep(0)

    assert await asyncio.wait_for(uno.get(), 1) == (7, "tickets")
    assert await asyncio.wait_for(dos.get(), 1) == (7, "tickets")


@pytest.mark.asyncio
async def test_cancelar_deja_de_recibir():
    difusor = Difusor()
    difusor.iniciar(asyncio.get_running_loop())

    cola = difusor.suscribir()
    difusor.cancelar(cola)
    difusor.publicar(1, "tickets")
    await asyncio.sleep(0)

    assert cola.empty()
    assert difusor.conectados == 0


@pytest.mark.asyncio
async def test_un_cliente_lento_no_frena_a_los_demas():
    """El que va atrasado pierde avisos; nadie más se entera.

    Sin el límite, una pestaña colgada haría crecer su cola sin fin hasta
    llevarse la memoria del proceso por delante. Y con el límite, lo correcto
    es tirar el aviso y no bloquear al que publica: un aviso perdido se
    recupera solo con el siguiente, porque el cliente vuelve a pedir la lista
    entera.
    """
    difusor = Difusor()
    difusor.iniciar(asyncio.get_running_loop())

    lento, rapido = difusor.suscribir(), difusor.suscribir()
    for _ in range(COLA_MAXIMA + 5):
        difusor.publicar(1, "tickets")
        await asyncio.sleep(0)
        rapido.get_nowait()  # este va vaciando

    assert lento.qsize() == COLA_MAXIMA
    assert rapido.empty()


def test_el_flujo_exige_sesion(client):
    """Sin token no hay canal. Es la misma puerta que el resto de la API."""
    respuesta = client.get("/api/eventos/flujo")
    assert respuesta.status_code in (401, 403)

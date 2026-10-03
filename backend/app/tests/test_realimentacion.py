"""El lazo de realimentacion: que lo que le sirvio a la gente pese en el orden.

El portal pregunta "¿te sirvio?" bajo cada sugerencia desde el primer dia y
guarda la respuesta en `veces_util` / `veces_sugerida`. Hasta ahora eso solo
alimentaba una metrica en una pantalla: **la busqueda no se enteraba**. Un
pasaje que ya resolvio el problema a cinco personas se ordenaba exactamente
igual que uno que nunca le sirvio a nadie.

Lo que se prueba aqui es sobre todo que el lazo **no haga dano**: con pocos
datos tiene que quedarse callado, y nunca debe poder rescatar un pasaje que no
habla del tema ni hundir al unico que si.
"""


from app.core.config import settings
from app.services.recuperacion_service import ajuste_por_utilidad


def test_sin_votos_no_cambia_nada():
    """Lo primero que tiene que hacer un lazo de realimentacion: callarse.

    Una base recien puesta no tiene ni un voto. Si el ajuste empujara en alguna
    direccion con cero datos, estaria inventando una senal que no existe y
    desordenando la busqueda desde el primer dia.
    """
    assert ajuste_por_utilidad(0, 0) == 0.0
    assert ajuste_por_utilidad(None, None) == 0.0


def test_un_voto_suelto_apenas_mueve_la_aguja():
    """Un "si me sirvio" de una sola sugerencia no es evidencia de nada.

    Sin suavizado, 1 de 1 seria utilidad 1,0 y mandaria ese pasaje al principio
    de la lista para siempre por el capricho de una persona. Con la regla de
    Laplace queda en 0,67, o sea un tercio del peso.
    """
    uno = ajuste_por_utilidad(1, 1)
    muchos = ajuste_por_utilidad(10, 10)

    assert 0 < uno < muchos, "un voto suelto deberia pesar menos que diez"
    assert uno < settings.RECUPERACION_PESO_UTILIDAD / 2


def test_lo_que_nunca_sirve_baja_y_lo_que_siempre_sirve_sube():
    """La direccion del ajuste, que es para lo que existe."""
    assert ajuste_por_utilidad(5, 5) > 0
    assert ajuste_por_utilidad(0, 5) < 0
    # Mitad y mitad es no saber: se queda practicamente en cero.
    assert abs(ajuste_por_utilidad(5, 10)) < 1e-9


def test_el_ajuste_nunca_se_sale_del_peso():
    """Es una preferencia, no un veto.

    Acotado, el ajuste no puede rescatar un pasaje que no habla del tema —haria
    falta que la similitud le fallara por mas de `RECUPERACION_PESO_UTILIDAD`,
    que son tres centesimas— ni hundir al unico que si habla de el. Sin el tope
    un pasaje muy votado contestaria preguntas que no le tocan, que es
    exactamente el fallo que ya costo un dia de diagnostico con una entrada mal
    etiquetada.
    """
    peso = settings.RECUPERACION_PESO_UTILIDAD
    casos = [(0, 0), (1, 1), (0, 1), (50, 50), (0, 50), (7, 13), (999, 1000)]
    for utiles, sugeridas in casos:
        assert -peso <= ajuste_por_utilidad(utiles, sugeridas) <= peso


def test_los_contadores_corruptos_no_rompen_la_busqueda():
    """Mas utiles que sugerencias, o negativos, no pueden dar un ajuste absurdo.

    Los dos contadores se escriben desde sitios distintos y en momentos
    distintos; que se descuadren es cuestion de tiempo. Cuando pase, la
    busqueda tiene que seguir ordenando de forma sensata en vez de mandar una
    entrada al principio por un contador roto.
    """
    peso = settings.RECUPERACION_PESO_UTILIDAD
    for utiles, sugeridas in [(10, 1), (-5, 10), (5, -1), (-5, -5)]:
        valor = ajuste_por_utilidad(utiles, sugeridas)
        assert -peso <= valor <= peso, f"{utiles}/{sugeridas} dio {valor}"


def test_se_puede_apagar_el_lazo(monkeypatch):
    """En 0 la busqueda vuelve a ordenar solo por parecido.

    Hace falta para poder descartar el lazo si algun dia se sospecha que esta
    desordenando los resultados, sin tener que revertir codigo.
    """
    monkeypatch.setattr(settings, "RECUPERACION_PESO_UTILIDAD", 0.0)
    assert ajuste_por_utilidad(50, 50) == 0.0
    assert ajuste_por_utilidad(0, 50) == 0.0


def test_entre_dos_pasajes_igual_de_parecidos_gana_el_que_sirvio(db_session, monkeypatch):
    """El caso que motiva todo esto, de punta a punta.

    Dos entradas con la misma similitud: una le sirvio a cinco personas y la
    otra a ninguna. Antes salian en orden arbitrario; ahora manda la que ya
    resolvio el problema.
    """
    from app.models import BaseConocimiento
    from app.services.recuperacion_service import RecuperacionService

    monkeypatch.setattr(settings, "IA_HABILITADA", True)
    monkeypatch.setattr(
        "app.services.ollama_client.ollama.generar_embedding", lambda *a, **k: [0.1] * 768)
    monkeypatch.setattr(RecuperacionService, "_de_soluciones", staticmethod(lambda *a, **k: []))
    monkeypatch.setattr(RecuperacionService, "_de_documentacion", staticmethod(lambda *a, **k: []))

    servible = BaseConocimiento(
        sitio_id=1, titulo="La que si sirve", contenido="Se limpia el cabezal.",
        categoria="impresora", veces_sugerida=5, veces_util=5)
    inutil = BaseConocimiento(
        sitio_id=1, titulo="La que nunca sirvio", contenido="Se revisa el cable.",
        categoria="impresora", veces_sugerida=5, veces_util=0)
    db_session.add_all([servible, inutil])
    db_session.commit()

    # Misma similitud base para las dos: lo unico que las separa es la utilidad.
    from app.services.recuperacion_service import Pasaje

    def tickets_falsos(db, vector, sitio_id, categoria, limite):
        return [
            Pasaje(fuente="ticket", referencia_id=servible.id, titulo=servible.titulo,
                   texto=servible.contenido, categoria="impresora",
                   similitud=0.70 + ajuste_por_utilidad(5, 5)),
            Pasaje(fuente="ticket", referencia_id=inutil.id, titulo=inutil.titulo,
                   texto=inutil.contenido, categoria="impresora",
                   similitud=0.70 + ajuste_por_utilidad(0, 5)),
        ]
    monkeypatch.setattr(RecuperacionService, "_de_tickets", staticmethod(tickets_falsos))

    pasajes = RecuperacionService.buscar(db_session, "raya negra al imprimir", 1)

    assert pasajes, "no se recupero nada"
    assert pasajes[0].titulo == "La que si sirve", (
        "gano la entrada que nunca le sirvio a nadie"
    )

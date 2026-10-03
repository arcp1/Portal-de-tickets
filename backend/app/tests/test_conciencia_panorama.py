"""Conciencia: que sabe la planta, como aprende y que se le escapa.

Lo que se prueba aqui es sobre todo que **la pantalla no mienta cuando no hay
nada**, que es el caso real de una instalacion recien puesta y el que mas
facilmente se pinta mal: una grafica que omite las categorias vacias por no
tener datos esconde justo el dato que importa.
"""

import pytest

from app.models import (
    BaseConocimiento, ConsultaAsistente, SolucionGeneral, Ticket, Usuario,
)
from app.services.conciencia_service import ConcienciaService


def _usuario(db, email="admin@test.com"):
    return db.query(Usuario).filter(Usuario.email == email).first()


def _consulta(db, sitio_id, origen, categoria="impresora", pregunta="algo"):
    db.add(ConsultaAsistente(
        sitio_id=sitio_id, usuario_id=None, pregunta=pregunta,
        categoria=categoria, pasajes=0, origen=origen,
    ))
    db.commit()


def _kb(db, sitio_id, categoria, titulo, contenido):
    entrada = BaseConocimiento(
        sitio_id=sitio_id, titulo=titulo, contenido=contenido, categoria=categoria,
    )
    db.add(entrada)
    db.commit()
    return entrada


# ----------------------------------------------------------------------
# Nivel 1 · Panorama
# ----------------------------------------------------------------------

def test_las_categorias_vacias_se_dibujan_igual(db_session):
    """Sin nada escrito, salen las seis categorias en cero.

    **Es la prueba que define la pantalla.** Lo natural de una grafica es
    omitir lo que no tiene datos, y aqui eso esconderia exactamente el dato:
    una categoria de la que no se sabe nada no es una ausencia, es una tarea.
    """
    sitio = 1
    panorama = ConcienciaService.panorama(db_session, sitio)

    nombres = {c["categoria"] for c in panorama["categorias"]}
    assert {"impresora", "red", "equipo", "software", "accesos", "otro"} <= nombres

    assert panorama["total"]["conocimiento"] == 0
    assert panorama["total"]["categorias_vacias"] >= 6
    assert all(c["estado"] == "vacio" for c in panorama["categorias"])


def test_una_categoria_sin_nada_y_con_preguntas_es_un_hueco(db_session):
    """Preguntar sobre lo que no esta escrito es peor que no preguntar.

    Las dos situaciones tienen cero conocimiento, pero solo una tiene gente
    quedandose sin ayuda. Si se pintaran igual, la pantalla no ayudaria a
    decidir por donde empezar a documentar.
    """
    sitio = 1
    _consulta(db_session, sitio, "sin_fundamento", categoria="red")

    panorama = ConcienciaService.panorama(db_session, sitio)
    por_nombre = {c["categoria"]: c for c in panorama["categorias"]}

    assert por_nombre["red"]["estado"] == "hueco", "una categoria preguntada y vacia es un hueco"
    assert por_nombre["software"]["estado"] == "vacio", "nadie pregunto de software"


def test_con_conocimiento_que_falla_seguido_la_categoria_sale_floja(db_session):
    """Hay material y aun asi no acierta: no es falta, es que no sirve.

    Suele ser conocimiento mal etiquetado, que es el caso que
    `avisos_de_calidad` persigue. Distinguirlo de "no hay nada" es lo que evita
    mandar a alguien a escribir documentacion que ya existe.
    """
    sitio = 1
    _kb(db_session, sitio, "equipo", "Algo de equipo", "Contenido cualquiera")
    for _ in range(3):
        _consulta(db_session, sitio, "sin_fundamento", categoria="equipo")
    _consulta(db_session, sitio, "ollama", categoria="equipo")

    panorama = ConcienciaService.panorama(db_session, sitio)
    por_nombre = {c["categoria"]: c for c in panorama["categorias"]}

    assert por_nombre["equipo"]["conocimiento"] == 1
    assert por_nombre["equipo"]["estado"] == "flojo"


def test_las_mayusculas_no_parten_una_categoria_en_dos(db_session):
    """"Impresora" e "impresora" son la misma, y tienen que sumar juntas.

    El portal guarda la categoria como texto libre en varios sitios; sin
    normalizar, la misma categoria saldria dos veces en el mapa con la mitad
    de sus piezas cada una.
    """
    sitio = 1
    _kb(db_session, sitio, "Impresora", "Con mayuscula", "texto")
    _kb(db_session, sitio, "impresora", "Sin mayuscula", "texto")

    panorama = ConcienciaService.panorama(db_session, sitio)
    filas = [c for c in panorama["categorias"] if c["categoria"] == "impresora"]

    assert len(filas) == 1, "la categoria se partio en dos por las mayusculas"
    assert filas[0]["kb"] == 2


# ----------------------------------------------------------------------
# Nivel 2 · Aprendizaje y avisos de calidad
# ----------------------------------------------------------------------

def test_se_detecta_una_entrada_mal_etiquetada(db_session):
    """El caso real que motivo todo esto.

    Una entrada sobre una cuenta bloqueada marcada como `impresora`. Con el
    filtro por categoria funcionando **correctamente**, esa entrada contestaba
    preguntas sobre impresoras — y el sintoma parecia un fallo del modelo.

    La comprobacion no usa ningun modelo: pasa el texto por la misma tabla de
    vocabulario con la que el chat clasifica sin llamar a Ollama. Deterministica
    y auditable, que es lo que hace falta para senalar datos malos.
    """
    sitio = 1
    _kb(db_session, sitio, "impresora",
        "No deja entrar al portal y dice que contacte a TI",
        "Ese mensaje sale cuando la cuenta quedo bloqueada por intentos "
        "fallidos. Se revisa el panel de usuarios y se desbloquea la cuenta.")

    avisos = ConcienciaService.avisos_de_calidad(db_session, sitio)

    assert len(avisos) == 1
    assert avisos[0]["etiqueta"] == "impresora"
    assert avisos[0]["sugerida"] == "accesos"


def test_una_entrada_bien_etiquetada_no_genera_ruido(db_session):
    """Solo se senala lo que discrepa. Un aviso falso se aprende a ignorar."""
    sitio = 1
    _kb(db_session, sitio, "impresora",
        "Impresora Zebra saca la etiqueta con una raya negra",
        "La raya negra a lo largo de la etiqueta es el cabezal sucio. Se limpia "
        "el cabezal con una torunda con alcohol isopropilico.")

    assert ConcienciaService.avisos_de_calidad(db_session, sitio) == []


def test_la_tuberia_no_marca_atasco_en_un_portal_nuevo(db_session):
    """Cero en todo no es una averia: es que todavia no ha pasado nada.

    Sin esta distincion, una instalacion recien puesta saldria en rojo el
    primer dia y nadie volveria a creerse los avisos.
    """
    datos = ConcienciaService.aprendizaje(db_session, 1)
    assert all(not e.get("atasco") for e in datos["etapas"])


def test_se_marca_el_atasco_cuando_se_resuelve_y_no_se_indexa(db_session):
    """Tickets resueltos y ninguno indexado: la tuberia esta cortada ahi.

    Pasa cuando Ollama estaba caido al cerrar los tickets. El portal no falla —
    simplemente deja de aprender, y no avisa por su cuenta.
    """
    usuario = _usuario(db_session)
    for i in range(3):
        db_session.add(Ticket(
            sitio_id=1, usuario_id=usuario.id,
            folio=f"T-INDEX-{i}", categoria="impresora",
            descripcion_original="algo", estado="resuelto", prioridad="media",
            solucion="Se limpio el cabezal y volvio a imprimir correctamente.",
        ))
    db_session.commit()

    datos = ConcienciaService.aprendizaje(db_session, usuario.sitio_id)
    etapas = {e["clave"]: e for e in datos["etapas"]}

    assert etapas["resueltos"]["valor"] == 3
    assert etapas["indexados"]["valor"] == 0
    assert etapas["indexados"]["atasco"] is True


def test_un_borrador_sin_publicar_no_cuenta_como_conocimiento(db_session):
    """Mientras no lo firme una persona, no contesta a nadie.

    Es la regla que ya tenia `SolucionGeneral` —un borrador no lleva embedding y
    por tanto no aparece en ninguna busqueda—; el panorama tiene que contarlo
    igual, o prometeria conocimiento que no esta disponible.
    """
    sitio = 1
    db_session.add(SolucionGeneral(
        sitio_id=sitio, titulo="Borrador", contenido="x" * 100,
        categoria="red", estado="borrador",
    ))
    db_session.commit()

    panorama = ConcienciaService.panorama(db_session, sitio)
    por_nombre = {c["categoria"]: c for c in panorama["categorias"]}
    assert por_nombre["red"]["soluciones"] == 0
    assert por_nombre["red"]["conocimiento"] == 0

    datos = ConcienciaService.aprendizaje(db_session, sitio)
    assert datos["pendiente_de_revision"] == 1


# ----------------------------------------------------------------------
# Nivel 3 · Consultas
# ----------------------------------------------------------------------

def test_solo_fallidas_deja_la_lista_de_lo_que_hay_que_documentar(db_session):
    """Es el filtro con el que de verdad se usa la pantalla."""
    sitio = 1
    _consulta(db_session, sitio, "ollama", pregunta="una que si se contesto")
    _consulta(db_session, sitio, "directo", pregunta="otra que si")
    _consulta(db_session, sitio, "sin_fundamento", pregunta="de esto no hay nada")
    _consulta(db_session, sitio, "extractos", pregunta="algo se encontro pero no sirvio")

    todas = ConcienciaService.consultas(db_session, sitio)
    fallidas = ConcienciaService.consultas(db_session, sitio, solo_fallidas=True)

    assert len(todas["consultas"]) == 4
    assert len(fallidas["consultas"]) == 2
    assert {c["origen"] for c in fallidas["consultas"]} == {"sin_fundamento", "extractos"}


def test_registrar_no_levanta_nunca(db_session):
    """Apuntar lo que paso no puede impedir que pase.

    Se le pasa a proposito un resultado con la forma equivocada. Si esto
    levantara, un fallo de la bitacora se comeria la respuesta de alguien —que
    es exactamente al reves del orden de prioridades correcto.
    """
    ConcienciaService.registrar(
        db_session, sitio_id=1, usuario_id=None, pregunta="x",
        categoria=None, resultado={"fuentes": "esto no es una lista"},
    )
    # Y con un sitio que no existe, que revienta la clave foranea.
    ConcienciaService.registrar(
        db_session, sitio_id=99999, usuario_id=None, pregunta="x",
        categoria=None, resultado={"origen": "ollama", "fuentes": []},
    )


def test_una_consulta_se_guarda_con_lo_que_encontro(db_session):
    """La fila tiene que decir que se recupero, no solo que hubo una consulta."""
    ConcienciaService.registrar(
        db_session, sitio_id=1, usuario_id=None,
        pregunta="me sale una raya negra al imprimir",
        categoria="impresora",
        resultado={
            "origen": "ollama",
            "fuentes": [{"similitud": 0.81, "fuente": "ticket"},
                        {"similitud": 0.74, "fuente": "documento"}],
        },
        duracion_ms=1234,
    )

    fila = db_session.query(ConsultaAsistente).first()
    assert fila.origen == "ollama"
    assert fila.pasajes == 2
    assert fila.mejor_similitud == pytest.approx(0.81)
    assert fila.mejor_fuente == "ticket"
    assert fila.duracion_ms == 1234


def test_la_pantalla_es_solo_para_administradores(client):
    """El texto de las preguntas ajenas no lo ve un usuario normal."""
    def token(email):
        r = client.post("/api/auth/login", json={"email": email, "password": "Secret123!"})
        return {"Authorization": f"Bearer {r.json()['access_token']}"}

    for ruta in ("panorama", "aprendizaje", "consultas"):
        assert client.get(f"/api/admin/conciencia/{ruta}").status_code == 401
        assert client.get(f"/api/admin/conciencia/{ruta}",
                          headers=token("user@test.com")).status_code == 403
        assert client.get(f"/api/admin/conciencia/{ruta}",
                          headers=token("admin@test.com")).status_code == 200


# ----------------------------------------------------------------------
# La mejora de recuperacion: un pasaje solo tiene que valer mas
# ----------------------------------------------------------------------

def test_un_unico_pasaje_flojo_no_alcanza_para_responder(db_session, monkeypatch):
    """El caso medido, convertido en prueba.

    "El escaner del anden 3 no manda nada al sistema" recuperaba **un** pasaje
    al 66% sobre una cuenta bloqueada. Pasaba el umbral general por cuatro
    puntos, se le daban 27 segundos de CPU al modelo para redactar encima, y el
    anclaje rechazaba el resultado al final.

    El corte relativo (`RECUPERACION_MARGEN`) no podia evitarlo: funciona
    midiendo distancias **entre candidatos**, y con uno solo el mejor es
    tambien el peor y pasa por definicion. Sin corroboracion, el liston sube.
    """
    from app.core.config import settings
    from app.services.recuperacion_service import Pasaje, RecuperacionService

    monkeypatch.setattr(settings, "IA_HABILITADA", True)
    monkeypatch.setattr(
        "app.services.ollama_client.ollama.generar_embedding", lambda *a, **k: [0.1] * 768)

    def un_pasaje(similitud):
        return [Pasaje(fuente="ticket", referencia_id=1, titulo="Cuenta bloqueada",
                       texto="Se desbloquea la cuenta desde el panel.",
                       similitud=similitud, categoria="accesos")]

    # 0.66: por encima del umbral general (0.62) y por debajo del solitario (0.70).
    monkeypatch.setattr(RecuperacionService, "_de_soluciones",
                        staticmethod(lambda *a, **k: un_pasaje(0.66)))
    monkeypatch.setattr(RecuperacionService, "_de_tickets", staticmethod(lambda *a, **k: []))
    monkeypatch.setattr(RecuperacionService, "_de_documentacion", staticmethod(lambda *a, **k: []))

    assert RecuperacionService.buscar(db_session, "el escaner no manda nada", 1) == []


def test_un_unico_pasaje_bueno_si_alcanza(db_session, monkeypatch):
    """No se trata de exigir siempre mas: se trata de exigir mas sin respaldo.

    Con 0.78 la coincidencia no deja dudas aunque venga sola, y cortarla seria
    negarle a alguien una respuesta que si existia.
    """
    from app.core.config import settings
    from app.services.recuperacion_service import Pasaje, RecuperacionService

    monkeypatch.setattr(settings, "IA_HABILITADA", True)
    monkeypatch.setattr(
        "app.services.ollama_client.ollama.generar_embedding", lambda *a, **k: [0.1] * 768)
    monkeypatch.setattr(RecuperacionService, "_de_soluciones", staticmethod(lambda *a, **k: [
        Pasaje(fuente="ticket", referencia_id=1, titulo="Raya negra",
               texto="Se limpia el cabezal.", similitud=0.78, categoria="impresora")]))
    monkeypatch.setattr(RecuperacionService, "_de_tickets", staticmethod(lambda *a, **k: []))
    monkeypatch.setattr(RecuperacionService, "_de_documentacion", staticmethod(lambda *a, **k: []))

    assert len(RecuperacionService.buscar(db_session, "raya negra al imprimir", 1)) == 1


def test_dos_pasajes_flojos_que_se_corroboran_si_pasan(db_session, monkeypatch):
    """Lo que se endurecio es la falta de respaldo, no la busqueda entera.

    Dos pasajes al 66% que dicen lo mismo son otra cosa que uno solo al 66%: se
    refuerzan. Subir `RECUPERACION_UMBRAL` habria matado tambien este caso, que
    es justo donde el sistema acierta.
    """
    from app.core.config import settings
    from app.services.recuperacion_service import Pasaje, RecuperacionService

    monkeypatch.setattr(settings, "IA_HABILITADA", True)
    monkeypatch.setattr(
        "app.services.ollama_client.ollama.generar_embedding", lambda *a, **k: [0.1] * 768)
    monkeypatch.setattr(RecuperacionService, "_de_soluciones", staticmethod(lambda *a, **k: [
        Pasaje(fuente="ticket", referencia_id=1, titulo="Uno",
               texto="Se limpia el cabezal.", similitud=0.66, categoria="impresora"),
        Pasaje(fuente="ticket", referencia_id=2, titulo="Dos",
               texto="El cabezal estaba sucio.", similitud=0.65, categoria="impresora")]))
    monkeypatch.setattr(RecuperacionService, "_de_tickets", staticmethod(lambda *a, **k: []))
    monkeypatch.setattr(RecuperacionService, "_de_documentacion", staticmethod(lambda *a, **k: []))

    assert len(RecuperacionService.buscar(db_session, "raya negra", 1)) == 2


def test_un_ganador_claro_sobre_varios_rivales_si_pasa_aunque_quede_solo(
    db_session, monkeypatch):
    """La distincion que este corte casi se lleva por delante.

    Tres candidatos al 69, 64 y 62 por ciento. El corte relativo deja uno — y
    ese uno **no** esta solo por falta de material: esta solo porque le gano a
    dos rivales por cinco puntos. Eso es exactamente la evidencia que
    `RECUPERACION_MARGEN` existe para producir.

    Escrito sobre los pasajes que sobreviven al corte en vez de sobre los
    candidatos que habia, el umbral solitario descartaba este caso: confundia
    "no habia con que comparar" con "hubo comparacion y gano uno". Lo atrapo
    `test_lo_que_queda_muy_por_debajo_del_mejor_se_descarta`, que ya existia.
    """
    from app.core.config import settings
    from app.services.recuperacion_service import Pasaje, RecuperacionService

    monkeypatch.setattr(settings, "IA_HABILITADA", True)
    monkeypatch.setattr(
        "app.services.ollama_client.ollama.generar_embedding", lambda *a, **k: [0.1] * 768)
    monkeypatch.setattr(RecuperacionService, "_de_soluciones", staticmethod(lambda *a, **k: []))
    monkeypatch.setattr(RecuperacionService, "_de_documentacion", staticmethod(lambda *a, **k: []))
    monkeypatch.setattr(RecuperacionService, "_de_tickets", staticmethod(lambda *a, **k: [
        Pasaje(fuente="ticket", referencia_id=1, titulo="Raya negra",
               texto="Se limpia el cabezal.", similitud=0.69, categoria="impresora"),
        Pasaje(fuente="ticket", referencia_id=2, titulo="Cuenta bloqueada",
               texto="Se desbloquea.", similitud=0.64, categoria="accesos"),
        Pasaje(fuente="ticket", referencia_id=3, titulo="Sin conexion",
               texto="Se revisa el cable.", similitud=0.62, categoria="red"),
    ]))

    pasajes = RecuperacionService.buscar(db_session, "linea oscura al imprimir", 1)

    assert len(pasajes) == 1, "se descarto un ganador claro por quedarse solo"
    assert pasajes[0].referencia_id == 1
    # Y esta por debajo del umbral solitario: lo que lo salva es que hubo
    # comparacion, no su similitud absoluta.
    assert pasajes[0].similitud < settings.RECUPERACION_UMBRAL_SOLITARIO


# ----------------------------------------------------------------------
# Lo que NO debe entrar a la base de conocimiento
# ----------------------------------------------------------------------

def test_un_ticket_resuelto_por_el_usuario_no_se_indexa(db_session):
    """El caso que ensucio la base de verdad, convertido en prueba.

    Un ticket deflectado por checklist no trae descripcion del problema —lleva
    el nombre de la categoria, "Impresora / Etiquetadora"— y su solucion dice
    literalmente que lo resolvio el checklist. Indexarlo mete en la base una
    entrada que no le contesta nada a nadie, y encima compite en la busqueda
    con las que si sirven.

    La regla existia, pero vivia en la ruta que crea tickets. `reindexar_kb.py`
    llama por otro camino, no la conocia, y lo indexo. Ahora vive en
    `KBService.indexar_ticket`, por donde pasan los dos.
    """
    from app.models import BaseConocimiento as BC
    from app.services.kb_service import KBService

    usuario = _usuario(db_session)
    ticket = Ticket(
        sitio_id=1, usuario_id=usuario.id,
        folio="T-CHECKLIST-1", categoria="impresora",
        descripcion_original="Impresora / Etiquetadora",
        estado="resuelto", prioridad="media",
        canal_resolucion="checklist",
        solucion=("Resuelto por el usuario con el checklist: "
                  "¿La impresora esta encendida y conectada a la toma de corriente?"),
    )
    db_session.add(ticket)
    db_session.commit()

    assert KBService.indexar_ticket(db_session, ticket) is False
    assert db_session.query(BC).filter(BC.ticket_origen_id == ticket.id).count() == 0


def test_un_ticket_que_atendio_una_persona_si_se_indexa(db_session, monkeypatch):
    """La contraparte: lo que si es conocimiento nuevo tiene que entrar.

    Sin esta, la correccion de arriba podria haberse pasado de frenada y dejar
    al portal sin aprender de nada.
    """
    from app.core.config import settings
    from app.models import BaseConocimiento as BC
    from app.services.kb_service import KBService

    monkeypatch.setattr(settings, "IA_HABILITADA", True)
    monkeypatch.setattr(
        "app.services.kb_service.ollama.generar_embedding", lambda *a, **k: [0.1] * 768)

    usuario = _usuario(db_session)
    ticket = Ticket(
        sitio_id=1, usuario_id=usuario.id,
        folio="T-TECNICO-1", categoria="impresora",
        descripcion_original="La Zebra del anden 2 saca la etiqueta con una raya negra",
        estado="resuelto", prioridad="media",
        canal_resolucion="tecnico",
        solucion="Se limpio el cabezal con alcohol isopropilico y la raya desaparecio.",
    )
    db_session.add(ticket)
    db_session.commit()

    assert KBService.indexar_ticket(db_session, ticket) is True
    assert db_session.query(BC).filter(BC.ticket_origen_id == ticket.id).count() == 1


def test_la_tuberia_no_pide_indexar_lo_que_nunca_se_indexara(db_session):
    """Un ticket de autoservicio no puede quedarse como pendiente eterno.

    Si contara, la pantalla pediria para siempre correr `reindexar_kb.py` por
    algo que —con razon— el reindexado se va a saltar. Un aviso que no se puede
    apagar se aprende a ignorar, y con el se ignoran los que si importan.
    """
    usuario = _usuario(db_session)
    db_session.add(Ticket(
        sitio_id=1, usuario_id=usuario.id,
        folio="T-CHECKLIST-2", categoria="impresora",
        descripcion_original="Impresora / Etiquetadora",
        estado="resuelto", prioridad="media", canal_resolucion="checklist",
        solucion="Resuelto por el usuario con el checklist: ¿esta encendida?",
        indexado_kb=False,
    ))
    db_session.commit()

    datos = ConcienciaService.aprendizaje(db_session, usuario.sitio_id)
    assert datos["pendientes_indexar"] == 0
    etapas = {e["clave"]: e for e in datos["etapas"]}
    assert etapas["resueltos"]["valor"] == 0, "un autoservicio no es material para aprender"

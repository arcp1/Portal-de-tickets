"""Catálogo visual: cuándo se activa, cuándo no, y qué se entrega.

**La mitad de estas pruebas son sobre el disparador**, y es donde toca que
estén. Que una ficha se guarde y se lea es CRUD; lo que puede salir mal de
verdad es que el portal le enseñe fotos de impresoras a quien preguntó por la
red —molesta, y nadie reporta eso— o que no se las enseñe a quien tenía el
defecto delante —que no se nota nunca—. Las dos se ven aquí o no se ven.

**Sobre la búsqueda por significado.** La suite no sale a la red y SQLite no
tiene pgvector, así que el camino de embeddings no se puede ejercitar aquí:
`generar_embedding` devuelve None y el servicio cae, a propósito, en la
coincidencia literal por frases. Eso es exactamente lo que pasa en producción
cuando Ollama está caído, así que la degradación sí queda probada; el orden por
coseno se calibra contra la base real, con `/api/admin/visual/probar`.
"""

import io

from app.core.config import settings
from app.models import ConsultaAsistente, FichaVisual, Sitio, Ticket, Usuario
from app.services.visual_service import VisualService
from app.tests.imagenes_de_prueba import misma_imagen

PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)

FICHA = {
    "titulo": "La copia sale borrosa",
    "sintoma": "El texto sale desvanecido y con el fondo gris, como si faltara tóner.",
    "solucion": "Abra la bandeja 2, saque el cartucho y agítelo en horizontal cinco veces.",
    "frases": "sale borroso, se ve despintado, queda tenue",
    "categoria": "impresora",
    "descartado": "Se cambió el cartucho completo y siguió igual: no era el tóner.",
}


def token(client, email="admin@test.com"):
    r = client.post("/api/auth/login", json={"email": email, "password": "Secret123!"})
    return r.json()["access_token"]


def cab(client, email="admin@test.com"):
    return {"Authorization": f"Bearer {token(client, email=email)}"}


def crear_ficha(client, cabeceras, **cambios):
    datos = dict(FICHA)
    datos.update(cambios)
    return client.post("/api/admin/visual", json=datos, headers=cabeceras)


def subir(client, ficha_id, cabeceras, rol="sintoma", pie="Así se ve"):
    return client.post(
        f"/api/admin/visual/{ficha_id}/imagenes",
        files={"archivo": ("defecto.png", io.BytesIO(PNG), "image/png")},
        data={"rol": rol, "pie": pie},
        headers=cabeceras,
    )


def ficha_publicada(client, tmp_path, monkeypatch, **cambios):
    """Una ficha con su foto y ya publicada: el estado normal de trabajo."""
    monkeypatch.setattr(settings, "VISUAL_RUTA", str(tmp_path))
    cabeceras = cab(client)
    ficha = crear_ficha(client, cabeceras, **cambios).json()
    subir(client, ficha["id"], cabeceras)
    client.post(f"/api/admin/visual/{ficha['id']}/estado/publicada", headers=cabeceras)
    return ficha


# ----------------------------------------------------------------------
# El disparador: lo que separa "no manda a imprimir" de "sale borroso"
# ----------------------------------------------------------------------
def test_una_falla_de_funcion_no_activa_las_fotos():
    """"No manda a imprimir" no tiene nada que mirar: falta una función.

    Es el caso que da sentido a todo el disparador. Sin él, esta consulta
    emparejaría con la ficha de "la hoja sale en blanco" —misma impresora,
    misma ausencia de resultado— y el portal enseñaría fotos de hojas a alguien
    cuyo problema es que el trabajo no llega a la cola.
    """
    visible, motivo = VisualService.describe_algo_visible("la impresora no manda a imprimir")

    assert visible is False
    assert motivo == "ausencia_de_funcion"


def test_un_defecto_que_se_ve_si_activa():
    visible, motivo = VisualService.describe_algo_visible("mi copia sale borrosa")

    assert visible is True
    assert motivo == "apariencia"


def test_la_falta_de_funcion_no_veta_lo_que_si_se_ve():
    """"No imprime, sale la hoja en blanco" tiene las dos cosas.

    Hay una ausencia de función y hay algo que mirar, y lo segundo es lo que
    resuelve: una hoja en blanco no se parece a una hoja con una raya.
    """
    visible, _ = VisualService.describe_algo_visible("no imprime, sale la hoja en blanco")

    assert visible is True


def test_un_verbo_de_percepcion_solo_no_le_gana_a_la_ausencia():
    """"No aparece la impresora en la lista" dice "aparece" y no se ve nada.

    Los verbos de percepción son señal débil a propósito: dicen que hay un
    resultado, no cómo se ve. Con una ausencia de función al lado, no alcanzan.
    """
    visible, motivo = VisualService.describe_algo_visible("no aparece la impresora en la lista")

    assert visible is False
    assert motivo == "ausencia_de_funcion"


def test_hablar_de_otra_cosa_tampoco_activa():
    visible, motivo = VisualService.describe_algo_visible(
        "necesito permiso para entrar a la carpeta de compras"
    )

    assert visible is False
    assert motivo == "nada_que_ver"


def test_las_lineas_activan_pero_estar_en_linea_no():
    """"Línea" es la palabra más ambigua de todo el léxico, y hace falta.

    Suelta no puede entrar —"el sistema no está en línea" no tiene nada que
    mirar—, pero es una de las dos formas en que la gente describe una hoja con
    un defecto, junto con "raya". Así que entra acompañada.
    """
    hoja, motivo_hoja = VisualService.describe_algo_visible(
        "la hoja sale con lineas verticales")
    # Lo que importa del segundo es que **no** active. El motivo exacto es
    # "nada_que_ver" y no "ausencia_de_funcion" porque "estar en línea" no es
    # una de las ausencias de la tabla: da igual, el desenlace es el mismo y
    # fijarlo aquí ataría la prueba a un detalle que puede cambiar.
    sistema, _ = VisualService.describe_algo_visible("el sistema no esta en linea")

    assert hoja is True and motivo_hoja == "apariencia"
    assert sistema is False


def test_las_frases_de_una_ficha_ensenan_al_disparador():
    """Lo que hace universal a esto, y no está en ninguna tabla del código.

    El léxico lo escribió alguien pensando en impresoras y pantallas. Una
    báscula que marca el peso en cero no está ahí y no va a estarlo: lo que la
    da de alta es que TI escriba la frase en la ficha.
    """
    sin_ficha, motivo = VisualService.describe_algo_visible("la bascula marca el peso en cero")
    con_ficha, motivo_con = VisualService.describe_algo_visible(
        "la bascula marca el peso en cero", ["marca el peso en cero"]
    )

    assert sin_ficha is False and motivo == "nada_que_ver"
    assert con_ficha is True and motivo_con == "frase_del_catalogo"


def test_una_frase_demasiado_corta_no_abre_la_puerta(client, tmp_path, monkeypatch):
    """Un descuido al capturar no puede volverse ruido para toda la planta.

    Con "raro" o "error" en `frases`, una sola ficha mal escrita activaría el
    reconocimiento en media incidencia del portal.
    """
    ficha_publicada(client, tmp_path, monkeypatch, frases="raro, mal")

    r = client.post("/api/visual/reconocer", json={"texto": "todo va raro hoy"},
                    headers=cab(client, "user@test.com"))

    assert r.json()["activado"] is False


# ----------------------------------------------------------------------
# El flujo completo
# ----------------------------------------------------------------------
def test_se_le_ensena_la_foto_y_se_le_pregunta(client, tmp_path, monkeypatch):
    ficha = ficha_publicada(client, tmp_path, monkeypatch)

    r = client.post("/api/visual/reconocer", json={"texto": "la copia sale borroso desde ayer"},
                    headers=cab(client, "user@test.com"))

    datos = r.json()
    assert datos["activado"] is True
    candidata = datos["candidatas"][0]
    assert candidata["ficha_id"] == ficha["id"]
    assert candidata["imagen_id"] is not None
    # La solución **no** viaja aquí: se entrega cuando la persona señala cuál
    # es la suya, no antes.
    assert "solucion" not in candidata


def test_al_confirmar_llega_la_solucion_de_esa_foto(client, tmp_path, monkeypatch):
    ficha = ficha_publicada(client, tmp_path, monkeypatch)
    subir(client, ficha["id"], cab(client), rol="solucion", pie="Destilde 'ahorro de tóner'")

    r = client.post("/api/visual/confirmar", json={"ficha_id": ficha["id"]},
                    headers=cab(client, "user@test.com"))

    datos = r.json()
    assert datos["solucion"] == FICHA["solucion"]
    # Lo que ya se probó y no era se enseña siempre, como en el resto del portal.
    assert datos["descartado"] == FICHA["descartado"]
    # El apartado de "unos clics": la imagen que señala dónde hay que picar.
    assert len(datos["pasos"]) == 1
    assert datos["pasos"][0]["pie"] == "Destilde 'ahorro de tóner'"


def test_la_imagen_se_puede_ver(client, tmp_path, monkeypatch):
    ficha = ficha_publicada(client, tmp_path, monkeypatch)
    imagen = client.get("/api/admin/visual", headers=cab(client)).json()[0]["imagenes"][0]

    r = client.get(f"/api/visual/fichas/{ficha['id']}/imagenes/{imagen['id']}",
                   headers=cab(client, "user@test.com"))

    assert r.status_code == 200
    assert misma_imagen(r.content, PNG)


def test_mostrar_confirmar_y_descartar_quedan_contados(client, tmp_path, monkeypatch, db_session):
    """Las tres cuentan la historia completa de una ficha.

    `mostrada` sola no distingue una ficha útil de una que empareja con lo que
    no debe. Eso sólo se ve restando lo que la gente descartó.
    """
    ficha = ficha_publicada(client, tmp_path, monkeypatch)
    usuario = cab(client, "user@test.com")

    client.post("/api/visual/reconocer", json={"texto": "sale borroso"}, headers=usuario)
    client.post("/api/visual/confirmar", json={"ficha_id": ficha["id"]}, headers=usuario)
    client.post("/api/visual/descartar", json={"ficha_ids": [ficha["id"]]}, headers=usuario)

    fila = db_session.query(FichaVisual).filter(FichaVisual.id == ficha["id"]).first()
    assert (fila.veces_mostrada, fila.veces_confirmada, fila.veces_descartada) == (1, 1, 1)


def test_reconocer_y_que_funcione_son_dos_cosas(client, tmp_path, monkeypatch, db_session):
    """El fallo que se escondía: la foto perfecta con la solución equivocada.

    Esa ficha la reconoce todo el mundo, así que `veces_confirmada` la pinta
    como la mejor del catálogo mientras manda a la planta a hacer algo que no
    arregla nada. Sólo se ve preguntando después.
    """
    ficha = ficha_publicada(client, tmp_path, monkeypatch)
    usuario = cab(client, "user@test.com")

    client.post("/api/visual/confirmar", json={"ficha_id": ficha["id"]}, headers=usuario)
    client.post("/api/visual/resultado",
                json={"ficha_id": ficha["id"], "resuelto": False, "consulta": "sale borroso"},
                headers=usuario)

    fila = db_session.query(FichaVisual).filter(FichaVisual.id == ficha["id"]).first()
    assert fila.veces_confirmada == 1
    assert fila.veces_resuelta == 0


def test_cuando_la_ficha_resuelve_queda_contado(client, tmp_path, monkeypatch, db_session):
    ficha = ficha_publicada(client, tmp_path, monkeypatch)

    r = client.post("/api/visual/resultado",
                    json={"ficha_id": ficha["id"], "resuelto": True, "consulta": "sale borroso"},
                    headers=cab(client, "user@test.com"))

    assert r.status_code == 200
    fila = db_session.query(FichaVisual).filter(FichaVisual.id == ficha["id"]).first()
    assert fila.veces_resuelta == 1


# ----------------------------------------------------------------------
# Lo que se apunta para saber qué falta fotografiar
# ----------------------------------------------------------------------
def test_pedir_una_foto_que_no_tenemos_queda_anotado(client, db_session):
    """**El apunte que más vale de los cuatro.**

    Sin él, alguien describe un defecto que se ve, el portal no tiene la foto
    y de esa consulta no queda ni rastro: el hueco existe y nadie puede verlo.
    """
    r = client.post("/api/visual/reconocer",
                    json={"texto": "la etiqueta sale corrida y no se lee el código"},
                    headers=cab(client, "user@test.com"))

    assert r.json()["activado"] is False
    fila = db_session.query(ConsultaAsistente).filter(
        ConsultaAsistente.origen == "visual_sin_foto").first()
    assert fila is not None
    assert "etiqueta" in fila.pregunta
    # Cero y no uno: no se recuperó nada, y esa columna se pinta en pantalla
    # como "pasajes encontrados". Decir uno sería contar un hallazgo que no
    # hubo, en la única pantalla que existe para no contar eso.
    assert fila.pasajes == 0


def test_una_consulta_que_no_es_visual_no_se_anota(client, db_session):
    """La bitácora es de huecos, no de todo lo que se teclea."""
    client.post("/api/visual/reconocer",
                json={"texto": "necesito permiso para la carpeta de compras"},
                headers=cab(client, "user@test.com"))

    assert db_session.query(ConsultaAsistente).count() == 0


def test_decir_que_ninguna_era_deja_dicho_sobre_que(client, tmp_path, monkeypatch, db_session):
    """Qué ficha sobra y qué defecto falta son dos preguntas distintas."""
    ficha = ficha_publicada(client, tmp_path, monkeypatch)

    client.post("/api/visual/descartar",
                json={"ficha_ids": [ficha["id"]], "consulta": "sale borroso pero solo en la orilla"},
                headers=cab(client, "user@test.com"))

    fila = db_session.query(ConsultaAsistente).filter(
        ConsultaAsistente.origen == "visual_ninguna").first()
    assert fila is not None
    assert "orilla" in fila.pregunta


def test_los_huecos_visuales_salen_en_la_lista_de_fallidas(client, db_session):
    """Van a la misma pantalla que los huecos de texto, que es donde se miran."""
    client.post("/api/visual/reconocer",
                json={"texto": "la pantalla del checador se ve toda verdosa"},
                headers=cab(client, "user@test.com"))

    r = client.get("/api/admin/conciencia/consultas?solo_fallidas=true", headers=cab(client))

    assert r.status_code == 200
    assert any(c["origen"] == "visual_sin_foto" for c in r.json()["consultas"])


def test_resolver_con_una_foto_cuenta_como_deflexion(client, tmp_path, monkeypatch, db_session):
    """El catálogo visual es autoservicio, igual que el checklist y la KB.

    Es lo que contesta si documentar un defecto con foto valió la pena: cada
    ticket con este canal es un ticket que nadie de TI tuvo que atender.
    """
    ficha_publicada(client, tmp_path, monkeypatch)
    usuario = cab(client, "user@test.com")

    r = client.post("/api/tickets", json={
        "sitio_id": 1,
        "categoria": "impresora",
        "descripcion_original": "mi copia sale borrosa desde ayer",
        "prioridad": "baja",
        "canal_auto_resolucion": "visual",
        "solucion": FICHA["solucion"],
    }, headers=usuario)

    assert r.status_code == 201
    ticket = db_session.query(Ticket).filter(Ticket.id == r.json()["id"]).first()
    assert ticket.canal_resolucion == "visual"
    assert ticket.estado == "resuelto"
    # No se indexa: la ficha ya está escrita y ya contesta.
    assert ticket.indexado_kb is False

    metricas = client.get("/api/metricas", headers=cab(client)).json()["tickets"]
    assert metricas["por_canal"]["visual"] == 1
    assert metricas["tickets_deflectados"] == 1


def test_probar_no_ensucia_los_contadores(client, tmp_path, monkeypatch, db_session):
    """Calibrar el disparador veinte veces no puede falsear la métrica."""
    ficha = ficha_publicada(client, tmp_path, monkeypatch)

    r = client.post("/api/admin/visual/probar", json={"texto": "sale borroso"},
                    headers=cab(client))

    assert r.json()["activado"] is True
    fila = db_session.query(FichaVisual).filter(FichaVisual.id == ficha["id"]).first()
    assert fila.veces_mostrada == 0


# ----------------------------------------------------------------------
# Lo que no se le enseña a nadie
# ----------------------------------------------------------------------
def test_un_borrador_no_le_contesta_a_nadie(client, tmp_path, monkeypatch):
    """Misma regla que las soluciones generales: sin revisar, no responde."""
    monkeypatch.setattr(settings, "VISUAL_RUTA", str(tmp_path))
    ficha = crear_ficha(client, cab(client)).json()
    subir(client, ficha["id"], cab(client))       # tiene foto, pero sigue en borrador

    r = client.post("/api/visual/reconocer", json={"texto": "sale borroso"},
                    headers=cab(client, "user@test.com"))

    assert r.json()["activado"] is False
    assert r.json()["motivo"] == "sin_catalogo"


def test_no_se_publica_una_ficha_sin_foto_del_sintoma(client):
    """Sin foto no puede hacer la única pregunta que la justifica."""
    ficha = crear_ficha(client, cab(client)).json()

    r = client.post(f"/api/admin/visual/{ficha['id']}/estado/publicada", headers=cab(client))

    assert r.status_code == 422
    assert "foto" in r.json()["detail"].lower()


def test_quitar_la_ultima_foto_devuelve_la_ficha_a_borrador(client, tmp_path, monkeypatch):
    """Publicada y muda es el peor estado posible: se ve el hueco, no se sufre."""
    ficha = ficha_publicada(client, tmp_path, monkeypatch)
    imagen = client.get("/api/admin/visual", headers=cab(client)).json()[0]["imagenes"][0]

    r = client.delete(f"/api/admin/visual/{ficha['id']}/imagenes/{imagen['id']}",
                      headers=cab(client))

    assert r.json()["estado"] == "borrador"


def test_una_ficha_se_comparte_entre_plantas(client, tmp_path, monkeypatch, db_session):
    """El conocimiento es de toda la empresa (multi-planta, 2026-10-02).

    Lo cura TI, que es global, y una Zebra con la raya negra se arregla igual
    en Querétaro que en Monterrey: el catálogo visual ya no se parte por planta.
    """
    ficha = ficha_publicada(client, tmp_path, monkeypatch)

    otra = Sitio(clave="MTY", nombre="Planta Monterrey", pais="México", activo=True)
    db_session.add(otra)
    db_session.commit()
    forastero = db_session.query(Usuario).filter(Usuario.email == "user@test.com").first()
    forastero.sitio_id = otra.id
    db_session.commit()

    reconocer = client.post("/api/visual/reconocer", json={"texto": "sale borroso"},
                            headers=cab(client, "user@test.com"))
    confirmar = client.post("/api/visual/confirmar", json={"ficha_id": ficha["id"]},
                            headers=cab(client, "user@test.com"))

    assert reconocer.status_code == 200
    assert confirmar.status_code == 200, confirmar.text


def test_solo_se_aceptan_imagenes(client, tmp_path, monkeypatch):
    """Un PDF no se puede mirar de un vistazo, que es lo que hay que hacer."""
    monkeypatch.setattr(settings, "VISUAL_RUTA", str(tmp_path))
    ficha = crear_ficha(client, cab(client)).json()

    r = client.post(
        f"/api/admin/visual/{ficha['id']}/imagenes",
        files={"archivo": ("manual.pdf", io.BytesIO(b"%PDF-1.4"), "application/pdf")},
        data={"rol": "sintoma"},
        headers=cab(client),
    )

    assert r.status_code == 422


def test_una_solucion_que_no_explica_nada_no_se_acepta(client):
    """El mismo mínimo que cualquier solución del portal, y por lo mismo.

    Con un mínimo propio más flojo se podían escribir fichas cuya solución el
    alta de ticket rechazaba después: la deflexión se perdía en un 422 que
    nadie veía.
    """
    r = crear_ficha(client, cab(client), solucion="Ya quedó")

    assert r.status_code == 422


def test_un_usuario_normal_no_documenta_fichas(client):
    r = crear_ficha(client, cab(client, "user@test.com"))

    assert r.status_code == 403


# ----------------------------------------------------------------------
# De un ticket ya resuelto, con sus fotos
# ----------------------------------------------------------------------
def ticket_resuelto_con_foto(client, tmp_path, monkeypatch):
    """Un ticket cerrado con su solución y una foto del defecto adjunta."""
    monkeypatch.setattr(settings, "ADJUNTOS_RUTA", str(tmp_path / "adjuntos"))
    monkeypatch.setattr(settings, "VISUAL_RUTA", str(tmp_path / "visual"))
    cabeceras = cab(client)

    ticket = client.post("/api/tickets", json={
        "sitio_id": 1, "categoria": "impresora",
        "descripcion_original": "La copia de la impresora de embarques sale toda borrosa",
        "prioridad": "media",
    }, headers=cabeceras).json()

    client.post(
        f"/api/tickets/{ticket['id']}/adjuntos",
        files={"archivo": ("hoja.png", io.BytesIO(PNG), "image/png")},
        headers=cabeceras,
    )
    client.patch(f"/api/tickets/{ticket['id']}",
                 json={"estado": "resuelto", "solucion": FICHA["solucion"]},
                 headers=cabeceras)
    return ticket


def test_una_ficha_nace_de_un_ticket_con_su_foto(client, tmp_path, monkeypatch):
    """Las fotos del problema ya existen: la gente las adjunta a sus tickets.

    Pedirle a TI que vuelva a fotografiar el mismo defecto es pedir dos veces
    un trabajo ya hecho.
    """
    ticket = ticket_resuelto_con_foto(client, tmp_path, monkeypatch)

    r = client.post(f"/api/admin/visual/desde-ticket/{ticket['id']}", headers=cab(client))

    assert r.status_code == 201
    ficha = r.json()
    assert ficha["estado"] == "borrador"        # nadie publica sin revisar
    assert ficha["solucion"] == FICHA["solucion"]
    assert ficha["ticket_origen_id"] == ticket["id"]
    assert len([i for i in ficha["imagenes"] if i["rol"] == "sintoma"]) == 1


def test_la_foto_copiada_se_puede_ver_aunque_se_borre_la_del_ticket(client, tmp_path, monkeypatch):
    """Se copia el archivo, no se enlaza: la ficha no puede quedarse muda."""
    ticket = ticket_resuelto_con_foto(client, tmp_path, monkeypatch)
    ficha = client.post(f"/api/admin/visual/desde-ticket/{ticket['id']}",
                        headers=cab(client)).json()
    adjunto = client.get(f"/api/tickets/{ticket['id']}/adjuntos",
                         headers=cab(client)).json()[0]

    client.delete(f"/api/tickets/{ticket['id']}/adjuntos/{adjunto['id']}", headers=cab(client))

    imagen = ficha["imagenes"][0]
    r = client.get(f"/api/visual/fichas/{ficha['id']}/imagenes/{imagen['id']}",
                   headers=cab(client))
    assert r.status_code == 200
    assert misma_imagen(r.content, PNG)


def test_pulsarlo_dos_veces_no_crea_dos_fichas(client, tmp_path, monkeypatch):
    ticket = ticket_resuelto_con_foto(client, tmp_path, monkeypatch)
    cabeceras = cab(client)

    primera = client.post(f"/api/admin/visual/desde-ticket/{ticket['id']}", headers=cabeceras).json()
    segunda = client.post(f"/api/admin/visual/desde-ticket/{ticket['id']}", headers=cabeceras).json()

    assert primera["id"] == segunda["id"]
    assert len(client.get("/api/admin/visual", headers=cabeceras).json()) == 1


def test_un_ticket_sin_solucion_no_da_ficha(client, tmp_path, monkeypatch):
    """Una ficha sin solución no le sirve a nadie."""
    monkeypatch.setattr(settings, "VISUAL_RUTA", str(tmp_path))
    ticket = client.post("/api/tickets", json={
        "sitio_id": 1, "categoria": "impresora",
        "descripcion_original": "La copia sale borrosa",
        "prioridad": "media",
    }, headers=cab(client)).json()

    r = client.post(f"/api/admin/visual/desde-ticket/{ticket['id']}", headers=cab(client))

    assert r.status_code == 422


# ----------------------------------------------------------------------
# El chat: lo visual va delante, y sólo cuando toca
# ----------------------------------------------------------------------
def test_el_chat_ensena_las_fotos_antes_que_nada(client, tmp_path, monkeypatch):
    ficha_publicada(client, tmp_path, monkeypatch)

    r = client.post("/api/chat/mensaje", json={"mensaje": "mi copia sale borroso"},
                    headers=cab(client, "user@test.com"))

    assert r.json()["accion"] == "reconocer_imagen"
    assert len(r.json()["fichas"]) == 1


def test_el_chat_no_cambia_cuando_no_es_visual(client, tmp_path, monkeypatch):
    """La inmensa mayoría de las incidencias no son visuales y no deben notarlo."""
    ficha_publicada(client, tmp_path, monkeypatch)

    r = client.post("/api/chat/mensaje", json={"mensaje": "la impresora no manda a imprimir"},
                    headers=cab(client, "user@test.com"))

    assert r.json()["accion"] != "reconocer_imagen"


def test_decir_que_no_es_ninguna_deja_seguir_la_conversacion(client, tmp_path, monkeypatch):
    """Sin esto el mismo mensaje traería las mismas fotos para siempre."""
    ficha_publicada(client, tmp_path, monkeypatch)

    r = client.post("/api/chat/mensaje",
                    json={"mensaje": "mi copia sale borroso", "omitir_visual": True},
                    headers=cab(client, "user@test.com"))

    assert r.json()["accion"] != "reconocer_imagen"

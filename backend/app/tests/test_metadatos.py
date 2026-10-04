"""Las imágenes se guardan sin metadatos, y sin deformarse.

Ver app/core/metadatos.py. Dos mitades:

  * la limpieza en sí, formato por formato: que no quede rastro —GPS, cámara,
    XMP, comentario— y que la imagen siga siendo la misma (dimensiones,
    píxeles, transparencia, orientación);
  * las cuatro puertas de subida del portal, de punta a punta: lo que se
    descarga ya no lleva nada.
"""

import io

import pytest
from PIL import Image
from PIL.PngImagePlugin import PngInfo

from app.core.config import settings
from app.core.metadatos import ImagenIlegible, sin_metadatos
from app.models import BaseConocimiento, Usuario
from app.tests.imagenes_de_prueba import misma_imagen

#: Lo que no debe sobrevivir en ningún byte del archivo guardado.
RASTROS = (b"CamaraSecreta", b"ModeloSecreto", b"GPSLatitude", b"comentario secreto",
           b"Exif\x00\x00", b"Fulano de Tal")


def _exif(orientacion=1):
    exif = Image.Exif()
    exif[0x010F] = "CamaraSecreta"         # Make
    exif[0x0110] = "ModeloSecreto"         # Model
    exif[0x0112] = orientacion             # Orientation
    exif[0x8825] = {1: "N", 2: (20.0, 35.0, 12.0), 3: "W", 4: (100.0, 23.0, 1.0)}  # GPS
    return exif.tobytes()


def _lienzo(ancho=40, alto=30, modo="RGB"):
    """Gris con un cuadro rojo arriba a la izquierda: así se ve si se giró."""
    im = Image.new(modo, (ancho, alto), (128, 128, 128, 200)[: len(modo)])
    for x in range(10):
        for y in range(10):
            im.putpixel((x, y), (220, 20, 20, 255)[: len(modo)])
    return im


def foto_con_gps(orientacion=1) -> bytes:
    salida = io.BytesIO()
    _lienzo().save(salida, "JPEG", quality=95, exif=_exif(orientacion),
                   comment=b"comentario secreto",
                   xmp=b"<x:xmpmeta><GPSLatitude>20.58</GPSLatitude></x:xmpmeta>")
    return salida.getvalue()


def sin_rastro(datos: bytes) -> bool:
    if any(r in datos for r in RASTROS):
        return False
    with Image.open(io.BytesIO(datos)) as im:
        return (not dict(im.getexif())
                and not {"exif", "xmp", "comment", "XML:com.adobe.xmp"} & set(im.info))


# ----------------------------------------------------------------------
# La limpieza, formato por formato
# ----------------------------------------------------------------------

def test_la_foto_ya_traia_todo_lo_que_hay_que_quitar():
    """Que la prueba pruebe algo: el original sí lleva los rastros."""
    original = foto_con_gps()
    assert all(r in original for r in RASTROS[:4])
    assert not sin_rastro(original)


def test_un_jpeg_pierde_gps_camara_xmp_y_comentario_sin_deformarse():
    original = foto_con_gps()
    limpio = sin_metadatos(original, "image/jpeg")
    assert sin_rastro(limpio)
    # La misma imagen: mismas medidas y los mismos colores (JPEG: casi).
    assert misma_imagen(limpio, original, error_medio=1.5)


def test_una_foto_girada_se_endereza_antes_de_perder_la_orientacion():
    """Quitar la etiqueta sin girar los píxeles dejaría de lado la foto de un
    celular sostenido en vertical."""
    limpio = sin_metadatos(foto_con_gps(orientacion=6), "image/jpeg")
    assert sin_rastro(limpio)
    with Image.open(io.BytesIO(limpio)) as im:
        # 40 × 30 girada 90° a la derecha: 30 × 40, y el cuadro rojo que estaba
        # arriba a la izquierda queda arriba a la derecha.
        assert im.size == (30, 40)
        r, g, b = im.convert("RGB").getpixel((25, 5))
        assert r > 180 and g < 70 and b < 70


def test_un_png_pierde_texto_y_exif_y_conserva_pixeles_y_transparencia():
    info = PngInfo()
    info.add_text("Author", "Fulano de Tal")
    info.add_text("Comment", "GPSLatitude 20.58")
    salida = io.BytesIO()
    _lienzo(modo="RGBA").save(salida, "PNG", pnginfo=info, exif=_exif())
    original = salida.getvalue()

    limpio = sin_metadatos(original, "image/png")
    assert sin_rastro(limpio)
    assert misma_imagen(limpio, original)  # sin pérdida, alfa incluido
    with Image.open(io.BytesIO(limpio)) as im:
        assert im.mode == "RGBA"
        assert not getattr(im, "text", {})


@pytest.mark.parametrize("sin_perdida", [True, False])
def test_un_webp_pierde_exif_y_xmp(sin_perdida):
    salida = io.BytesIO()
    opciones = {"lossless": True} if sin_perdida else {"quality": 90}
    _lienzo(modo="RGBA").save(salida, "WEBP", exif=_exif(),
                              xmp=b"<x:xmpmeta>GPSLatitude</x:xmpmeta>", **opciones)
    original = salida.getvalue()

    limpio = sin_metadatos(original, "image/webp")
    assert sin_rastro(limpio)
    if sin_perdida:
        assert misma_imagen(limpio, original)
        assert b"VP8L" in limpio[:64], "una captura sin pérdida no debe ganar pérdida"
    else:
        assert misma_imagen(limpio, original, error_medio=1.5)


def test_lo_que_no_es_jpeg_png_o_webp_pasa_intacto():
    salida = io.BytesIO()
    _lienzo().convert("P").save(salida, "GIF")
    gif = salida.getvalue()
    assert sin_metadatos(gif, "image/gif") == gif
    assert sin_metadatos(b"%PDF-1.7\n...", "application/pdf") == b"%PDF-1.7\n..."


def test_una_imagen_rota_con_la_firma_buena_se_rechaza():
    with pytest.raises(ImagenIlegible):
        sin_metadatos(b"\x89PNG\r\n\x1a\n" + b"no soy un png" * 20, "image/png")


def test_hay_tope_de_pixeles_antes_de_descomprimir(monkeypatch):
    """Ahora la imagen se abre: un PNG pequeño que declara 40 000 × 40 000
    pediría gigas al decodificarse. Se mira en la cabecera."""
    monkeypatch.setattr(settings, "IMAGENES_MAX_MEGAPIXELES", 0)
    with pytest.raises(ImagenIlegible, match="megapíxeles"):
        sin_metadatos(foto_con_gps(), "image/jpeg")


def _animada(formato, ancho, alto, cuadros) -> bytes:
    """Cuadros de colores alternos: iguales, Pillow los fundiría en uno."""
    marcos = [Image.new("RGB", (ancho, alto), (255 * (i % 2), 0, 0)) for i in range(cuadros)]
    salida = io.BytesIO()
    marcos[0].save(salida, formato, save_all=True, append_images=marcos[1:], duration=100)
    return salida.getvalue()


@pytest.mark.parametrize("formato,tipo", [("PNG", "image/png"), ("WEBP", "image/webp")])
def test_el_tope_de_pixeles_suma_todos_los_cuadros(monkeypatch, formato, tipo):
    """La bomba de la auditoría de 2026-10-03, en pequeño.

    Cada cuadro cabía bajo el tope y la suma no: 40 cuadros de 81 MP en un PNG
    de 9,88 MB tumbaron un contenedor de 4 GB. Aquí, cuatro de 0,36 MP contra
    un tope de 1 MP.
    """
    monkeypatch.setattr(settings, "IMAGENES_MAX_MEGAPIXELES", 1)
    animada = _animada(formato, 600, 600, 4)
    with Image.open(io.BytesIO(animada)) as im:
        assert im.n_frames == 4 and im.width * im.height < 1_000_000
    with pytest.raises(ImagenIlegible, match="sumando todos sus cuadros"):
        sin_metadatos(animada, tipo)
    # Con dos cuadros cabe, y se guarda animada.
    with Image.open(io.BytesIO(sin_metadatos(_animada(formato, 600, 600, 2), tipo))) as im:
        assert im.n_frames == 2


def test_se_limpian_pocas_imagenes_a_la_vez(monkeypatch):
    """Con el turno ocupado, la siguiente espera; si no le toca a tiempo, 503."""
    import asyncio
    import threading
    import time

    from fastapi import HTTPException

    from app.core import metadatos

    monkeypatch.setattr(settings, "IMAGENES_EN_PARALELO", 1)
    monkeypatch.setattr(settings, "IMAGENES_ESPERA_S", 0.2)
    a_la_vez, maximo = 0, 0
    candado = threading.Lock()

    def lenta(contenido, tipo):
        nonlocal a_la_vez, maximo
        with candado:
            a_la_vez += 1
            maximo = max(maximo, a_la_vez)
        time.sleep(0.5)
        with candado:
            a_la_vez -= 1
        return contenido

    monkeypatch.setattr(metadatos, "sin_metadatos", lenta)

    async def tres_a_la_vez():
        return await asyncio.gather(
            *(metadatos.limpiar_subida(b"x", "image/png") for _ in range(3)),
            return_exceptions=True)

    resultados = asyncio.run(tres_a_la_vez())
    assert maximo == 1
    assert resultados.count(b"x") == 1
    rechazos = [r for r in resultados if isinstance(r, HTTPException)]
    assert len(rechazos) == 2 and all(r.status_code == 503 for r in rechazos)
    # Lo que no se reescribe no pide turno: un PDF no espera a nadie.
    assert asyncio.run(metadatos.limpiar_subida(b"%PDF-1.7", "application/pdf")) == b"%PDF-1.7"


# ----------------------------------------------------------------------
# Las cuatro puertas de subida, de punta a punta
# ----------------------------------------------------------------------

def _cab(client, email):
    r = client.post("/api/auth/login", json={"email": email, "password": "Secret123!"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _archivo(nombre="foto.jpg", datos=None):
    return {"archivo": (nombre, io.BytesIO(datos or foto_con_gps()), "image/jpeg")}


def test_el_adjunto_de_un_ticket_se_guarda_sin_metadatos(client):
    persona = _cab(client, "user@test.com")
    ticket = client.post("/api/tickets", headers=persona, json={
        "categoria": "equipo", "descripcion_original": "La pantalla tiene una raya",
        "prioridad": "media"}).json()
    r = client.post(f"/api/tickets/{ticket['id']}/adjuntos", headers=persona,
                    files=_archivo(datos=foto_con_gps(orientacion=6)))
    assert r.status_code == 201, r.text
    datos = client.get(f"/api/tickets/{ticket['id']}/adjuntos/{r.json()['id']}",
                       headers=persona).content
    assert sin_rastro(datos)
    assert len(datos) == r.json()["tamano_bytes"]
    with Image.open(io.BytesIO(datos)) as im:
        assert im.size == (30, 40)


def test_la_imagen_de_la_base_de_conocimiento_se_guarda_sin_metadatos(client, db_session):
    entrada = BaseConocimiento(sitio_id=1, titulo="Raya en la etiqueta",
                               contenido="Limpiar el cabezal con alcohol isopropílico.",
                               categoria="impresora")
    db_session.add(entrada)
    db_session.commit()
    ti = _cab(client, "admin@test.com")
    r = client.post(f"/api/imagenes/kb/{entrada.id}", headers=ti, files=_archivo())
    assert r.status_code == 201, r.text
    datos = client.get(f"/api/imagenes/{r.json()[0]['id']}", headers=ti).content
    assert sin_rastro(datos)


def test_la_foto_del_catalogo_visual_se_guarda_sin_metadatos(client):
    ti = _cab(client, "admin@test.com")
    ficha = client.post("/api/admin/visual", headers=ti, json={
        "titulo": "La copia sale borrosa", "categoria": "impresora",
        "sintoma": "El texto sale desvanecido y con el fondo gris.",
        "solucion": "Saque el cartucho y agítelo en horizontal cinco veces.",
        "frases": "sale borroso"}).json()
    r = client.post(f"/api/admin/visual/{ficha['id']}/imagenes", headers=ti,
                    files=_archivo(), data={"rol": "sintoma"})
    assert r.status_code == 201, r.text
    imagen = r.json()["imagenes"][0]
    datos = client.get(f"/api/visual/fichas/{ficha['id']}/imagenes/{imagen['id']}",
                       headers=ti).content
    assert sin_rastro(datos)


def test_el_documento_del_expediente_se_guarda_sin_metadatos(client, db_session):
    persona = db_session.query(Usuario).filter_by(email="user@test.com").one()
    ti = _cab(client, "admin@test.com")
    r = client.post("/api/documentos", headers=ti, files=_archivo("ine.jpg"),
                    data={"usuario_id": persona.id, "tipo": "identificacion",
                          "titulo": "Identificación escaneada"})
    assert r.status_code == 201, r.text
    datos = client.get(f"/api/documentos/{r.json()['id']}", headers=ti).content
    assert sin_rastro(datos)


def test_una_imagen_ilegible_se_rechaza_con_422_y_no_deja_archivo(client):
    persona = _cab(client, "user@test.com")
    ticket = client.post("/api/tickets", headers=persona, json={
        "categoria": "equipo", "descripcion_original": "No prende el monitor",
        "prioridad": "media"}).json()
    rota = b"\xff\xd8\xff\xe0" + b"no soy una foto" * 30
    r = client.post(f"/api/tickets/{ticket['id']}/adjuntos", headers=persona,
                    files=_archivo(datos=rota))
    assert r.status_code == 422
    assert "dañada" in r.json()["detail"]
    from pathlib import Path
    carpeta = Path(settings.ADJUNTOS_RUTA)
    assert not carpeta.exists() or not any(p.is_file() for p in carpeta.rglob("*"))

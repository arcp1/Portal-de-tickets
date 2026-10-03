"""La etiqueta QR de un equipo: se pega en el equipo y se escanea para reportarlo.

**Qué lleva el QR.** Un enlace a «Nuevo ticket» con el equipo y la categoría
ya elegidos:

    {PORTAL_URL}/new-ticket?equipo=<id>&categoria=<categoria>

Solo el id, nada más: ni el nombre ni la serie viajan en el enlace, así que
fotografiar la etiqueta no enseña nada que no esté ya impreso al lado. Quien
lo escanea tiene que iniciar sesión, y el formulario comprueba que el equipo
sea de una de sus plantas (ver ``NewTicket.jsx``); el API lo vuelve a
comprobar al crear el ticket.

**La imagen.** 1200 × 600 px a 300 ppp: una etiqueta de 4 × 2 pulgadas
(101,6 × 50,8 mm), la más común en las Zebra de la planta, que también sale
bien en una hoja carta recortada. A la izquierda el QR, en el azul de la marca
y con el logotipo al centro —el nivel de corrección H deja tapar hasta un 30 %
y el logotipo ocupa menos del 4 %—; a la derecha, lo que una persona necesita
para saber que escanea el equipo correcto: qué es, de qué planta y su serie.
"""

import io
import re
from functools import lru_cache
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode

import qrcode
from PIL import Image, ImageDraw, ImageFont
from qrcode.constants import ERROR_CORRECT_H

from app.core.config import settings
from app.models import Equipo

ANCHO, ALTO = 1200, 600
PPP = 300

AZUL = (27, 61, 121)        # --cgr-azul
AZUL_CLARO = (20, 142, 194)  # --cgr-azul-claro
ROSA = (179, 22, 113)       # --cgr-rosa
GRIS = (110, 120, 128)
GRIS_CLARO = (226, 230, 234)
TINTA = (24, 30, 40)
BLANCO = (255, 255, 255)

RECURSOS = Path(__file__).resolve().parent.parent / "recursos"
FUENTES = (
    Path("/usr/share/fonts/truetype/dejavu"),
    Path("/usr/share/fonts/dejavu"),
)

#: De lo que se escribe en el inventario (texto libre) a la categoría del
#: ticket. Lo que no se reconoce es "equipo": una etiqueta va pegada a algo
#: físico, y "equipo" es la categoría de hardware.
_CATEGORIA_POR_PALABRA = (
    ("impresora", ("impresora", "zebra", "etiquetadora", "printer", "multifuncional",
                   "escaner", "escáner", "plotter", "toner", "tóner")),
    ("red", ("switch", "router", "access point", "punto de acceso", "antena", "modem",
             "módem", "firewall", "red", "wifi", "ap ")),
)

ETIQUETAS_CATEGORIA = {
    "impresora": "IMPRESORA", "red": "RED", "equipo": "EQUIPO DE CÓMPUTO",
    "software": "SOFTWARE", "accesos": "ACCESOS", "otro": "OTRO",
}


def categoria_de_ticket(equipo: Equipo) -> str:
    texto = f" {equipo.categoria or ''} {equipo.marca or ''} {equipo.modelo or ''} ".lower()
    for categoria, palabras in _CATEGORIA_POR_PALABRA:
        if any(p in texto for p in palabras):
            return categoria
    return "equipo"


def enlace_de(equipo: Equipo) -> str:
    base = (settings.PORTAL_URL or "").rstrip("/")
    return f"{base}/new-ticket?" + urlencode({"equipo": equipo.id,
                                              "categoria": categoria_de_ticket(equipo)})


@lru_cache(maxsize=16)
def _fuente(tamano: int, estilo: str = "") -> ImageFont.FreeTypeFont:
    nombre = {"": "DejaVuSans.ttf", "negrita": "DejaVuSans-Bold.ttf",
              "mono": "DejaVuSansMono.ttf"}[estilo]
    for carpeta in FUENTES:
        ruta = carpeta / nombre
        if ruta.exists():
            return ImageFont.truetype(str(ruta), tamano)
    # Sin DejaVu instalada (fuera del contenedor): la escalable de Pillow.
    return ImageFont.load_default(size=tamano)


@lru_cache(maxsize=1)
def _logotipo() -> Optional[Image.Image]:
    ruta = RECURSOS / "cgr.png"
    if not ruta.exists():
        return None
    return Image.open(ruta).convert("RGBA")


def _ajustar(dibujo: ImageDraw.ImageDraw, texto: str, fuente, ancho: int, lineas: int):
    """Parte el texto en renglones que quepan; el último lleva "…" si sobra."""
    palabras = (texto or "").split()
    renglones, actual = [], ""
    for palabra in palabras:
        prueba = f"{actual} {palabra}".strip()
        if dibujo.textlength(prueba, font=fuente) <= ancho:
            actual = prueba
            continue
        if actual:
            renglones.append(actual)
        actual = palabra
        if len(renglones) == lineas:
            break
    if actual and len(renglones) < lineas:
        renglones.append(actual)
    usadas = " ".join(renglones).split()
    if len(usadas) < len(palabras) and renglones:
        ultimo = renglones[-1]
        while ultimo and dibujo.textlength(ultimo + "…", font=fuente) > ancho:
            ultimo = ultimo[:-1]
        renglones[-1] = ultimo.rstrip() + "…"
    # Una sola palabra más ancha que todo (una serie larguísima): se recorta.
    return [r if dibujo.textlength(r, font=fuente) <= ancho else _recortar(dibujo, r, fuente, ancho)
            for r in renglones]


def _recortar(dibujo, texto, fuente, ancho):
    while texto and dibujo.textlength(texto + "…", font=fuente) > ancho:
        texto = texto[:-1]
    return texto + "…"


def _qr(enlace: str, lado: int) -> Image.Image:
    codigo = qrcode.QRCode(error_correction=ERROR_CORRECT_H, box_size=10, border=2)
    codigo.add_data(enlace)
    codigo.make(fit=True)
    imagen = codigo.make_image(fill_color=AZUL, back_color=BLANCO).convert("RGB")
    # NEAREST: escalar un QR con suavizado le emborrona los bordes de los módulos.
    imagen = imagen.resize((lado, lado), Image.NEAREST)

    logotipo = _logotipo()
    if logotipo is not None:
        ancho_logo = int(lado * 0.26)
        alto_logo = int(logotipo.height * ancho_logo / logotipo.width)
        logo = logotipo.resize((ancho_logo, alto_logo), Image.LANCZOS)
        margen = 12
        caja = (lado // 2 - ancho_logo // 2 - margen, lado // 2 - alto_logo // 2 - margen,
                lado // 2 + ancho_logo // 2 + margen, lado // 2 + alto_logo // 2 + margen)
        ImageDraw.Draw(imagen).rounded_rectangle(caja, radius=14, fill=BLANCO)
        imagen.paste(logo, (lado // 2 - ancho_logo // 2, lado // 2 - alto_logo // 2), logo)
    return imagen


def generar_png(equipo: Equipo) -> bytes:
    lienzo = Image.new("RGB", (ANCHO, ALTO), BLANCO)
    d = ImageDraw.Draw(lienzo)

    # Marco y franja de marca a la izquierda (azul arriba, rosa abajo).
    d.rounded_rectangle((6, 6, ANCHO - 7, ALTO - 7), radius=28, outline=GRIS_CLARO, width=4)
    for y in range(20, ALTO - 20):
        t = (y - 20) / (ALTO - 40)
        color = tuple(int(AZUL_CLARO[i] * (1 - t) + ROSA[i] * t) for i in range(3))
        d.line((20, y, 34, y), fill=color)

    # El QR.
    lado = 500
    lienzo.paste(_qr(enlace_de(equipo), lado), (58, (ALTO - lado) // 2))

    x, ancho = 600, ANCHO - 600 - 48
    y = 48

    # Logotipo y "Soporte TI".
    logotipo = _logotipo()
    if logotipo is not None:
        alto_logo = 54
        ancho_logo = int(logotipo.width * alto_logo / logotipo.height)
        logo = logotipo.resize((ancho_logo, alto_logo), Image.LANCZOS)
        lienzo.paste(logo, (x, y), logo)
        d.text((x + ancho_logo + 18, y + 10), "Soporte TI", font=_fuente(30, "negrita"), fill=GRIS)
    else:
        d.text((x, y + 8), "CGR · Soporte TI", font=_fuente(30, "negrita"), fill=GRIS)
    y += 82

    # La categoría, en una píldora.
    categoria = ETIQUETAS_CATEGORIA.get(categoria_de_ticket(equipo), "EQUIPO")
    fuente_pildora = _fuente(24, "negrita")
    ancho_pildora = int(d.textlength(categoria, font=fuente_pildora)) + 36
    d.rounded_rectangle((x, y, x + ancho_pildora, y + 44), radius=22, fill=AZUL_CLARO)
    d.text((x + 18, y + 9), categoria, font=fuente_pildora, fill=BLANCO)
    y += 64

    # Qué es: marca y modelo, en grande.
    nombre = " ".join(p for p in (equipo.marca, equipo.modelo) if p) or equipo.categoria
    fuente_nombre = _fuente(52, "negrita")
    for renglon in _ajustar(d, nombre, fuente_nombre, ancho, 2):
        d.text((x, y), renglon, font=fuente_nombre, fill=TINTA)
        y += 62
    y += 8

    # De dónde.
    sitio = equipo.sitio
    planta = f"{sitio.nombre} · {sitio.clave}" if sitio else "Sin planta"
    for renglon in _ajustar(d, planta, _fuente(30), ancho, 1):
        d.text((x, y), renglon, font=_fuente(30), fill=AZUL)
        y += 40
    if equipo.ubicacion:
        for renglon in _ajustar(d, equipo.ubicacion, _fuente(26), ancho, 1):
            d.text((x, y), renglon, font=_fuente(26), fill=GRIS)
            y += 36

    # Serie y número de activo, en monoespaciada: se dictan por teléfono.
    serie = f"S/N {equipo.numero_serie}" if equipo.numero_serie else "Sin serie"
    for renglon in _ajustar(d, f"{serie} · #{equipo.id}", _fuente(26, "mono"), ancho, 1):
        d.text((x, y + 4), renglon, font=_fuente(26, "mono"), fill=TINTA)

    # La llamada a la acción, abajo.
    d.line((x, ALTO - 112, x + ancho, ALTO - 112), fill=GRIS_CLARO, width=3)
    llamada = "Escanee para reportar una falla"
    tamano = 32
    while tamano > 20 and d.textlength(llamada, font=_fuente(tamano, "negrita")) > ancho:
        tamano -= 1
    d.text((x, ALTO - 96), llamada, font=_fuente(tamano, "negrita"), fill=ROSA)
    host = re.sub(r"^https?://", "", (settings.PORTAL_URL or "").rstrip("/"))
    for renglon in _ajustar(d, host, _fuente(22), ancho, 1):
        d.text((x, ALTO - 52), renglon, font=_fuente(22), fill=GRIS)

    salida = io.BytesIO()
    lienzo.save(salida, format="PNG", dpi=(PPP, PPP), optimize=True)
    return salida.getvalue()

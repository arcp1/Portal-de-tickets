"""Las imágenes se guardan sin metadatos: ni GPS, ni cámara, ni fecha, ni autor.

**Por qué.** Una foto de celular lleva en su EXIF las coordenadas exactas de
dónde se tomó, el modelo del teléfono y la hora; el XMP puede repetir todo eso y
el comentario JPEG, cualquier cosa. En el portal esas fotos las ve otra gente:
el adjunto de un ticket, TI; la captura de una solución o de la base de
conocimiento, cualquiera de la empresa. Ninguna de esas personas necesita saber
desde qué casa se tomó la foto del equipo que alguien se llevó a trabajar.

**Qué se hace, por formato** (Pillow, que ya estaba en la imagen):

  * **JPEG**: se vuelve a escribir sin EXIF, sin XMP y **sin comentario** —Pillow
    conserva el comentario si no se le dice lo contrario; se comprobó—. Si la
    foto no estaba girada se usa `quality="keep"`: mismas tablas de
    cuantización, sin pérdida visible. Si lo estaba, primero se gira de verdad
    (`exif_transpose`): quitar la etiqueta de orientación sin girar los píxeles
    dejaría de lado la foto de un celular sostenido en vertical.
  * **PNG**: se reescribe sin bloques de texto ni eXIf. Sin pérdida; se
    conserva la transparencia.
  * **WEBP**: se reescribe sin EXIF ni XMP; sin pérdida si el original lo era.
  * El perfil de color (ICC) se conserva: no identifica a nadie, y sin él los
    colores de algunas fotos cambian.
  * Animadas (PNG o WEBP): se conservan todos los cuadros.
  * **GIF** no lleva EXIF; **HEIC** no lo lee Pillow sin una biblioteca más
    (`pillow-heif`), y tampoco lo pinta ningún navegador fuera de Safari. Los
    dos se guardan tal cual. Un iPhone, al subir por el navegador, suele
    convertir sus HEIC a JPEG por su cuenta; si algún día llegan HEIC con GPS,
    la salida es añadir `pillow-heif` (y fijarlo en constraints.txt).

**El tope de píxeles** es nuevo y necesario: antes el portal guardaba los
bytes sin abrirlos, y ahora los descomprime. Un PNG de 10 MB puede declarar
40 000 × 40 000 píxeles y pedir gigas de memoria al decodificarse (una «bomba
de descompresión»). Se mira el tamaño en la cabecera, antes de decodificar.

**Y cuenta todos los cuadros, no solo el primero** (auditoría de seguridad,
2026-10-03). El tope se medía por cuadro, y una animada se guarda decodificando
cada uno —Pillow los tiene todos en memoria a la vez para escribirla—. Medido:
un PNG animado de 9,88 MB, 40 cuadros de 9 000 × 9 000 (81 MP cada uno, bajo el
tope), tumbó por falta de memoria un contenedor con 4 GB. Cualquier cuenta podía
subirlo como adjunto de su propio ticket, y el backend no tiene tope de memoria:
dos a la vez eran unos 20 GB en un servidor de 32 que comparte con Postgres y
Ollama. Ahora el tope es para la suma de los cuadros.

**Y se limpian pocas a la vez** (`IMAGENES_EN_PARALELO`). Aun dentro del tope,
una foto grande ocupa cientos de megas mientras se reescribe, y el *pool* de
hilos admite cuarenta peticiones: cuarenta fotos de 100 MP a la vez seguían
siendo decenas de gigas. Quien no consigue turno en `IMAGENES_ESPERA_S`
recibe un 503 y vuelve a intentar; mientras espera no ocupa un hilo.
"""

import asyncio
import io
import weakref

from PIL import Image, ImageOps, JpegImagePlugin, UnidentifiedImageError

from app.core.config import settings

#: Los formatos que se limpian. El resto pasa sin tocar.
LIMPIABLES = ("image/jpeg", "image/png", "image/webp")


class ImagenIlegible(ValueError):
    """La imagen no se puede abrir, o es demasiado grande para abrirla."""


def _cuadros(im):
    """Para las animadas: todos los cuadros y lo que dura cada uno."""
    duraciones = []
    for i in range(getattr(im, "n_frames", 1)):
        im.seek(i)
        duraciones.append(im.info.get("duration", 100))
    im.seek(0)
    return duraciones


def sin_metadatos(contenido: bytes, tipo: str) -> bytes:
    """La misma imagen, sin metadatos. Lo que no es JPEG, PNG o WEBP, igual.

    Síncrona y de CPU: desde una ruta `async` hay que llamarla en un hilo
    (`limpiar_subida`).
    """
    if tipo not in LIMPIABLES:
        return contenido
    try:
        with Image.open(io.BytesIO(contenido)) as im:
            # Lo dice la cabecera: el tamaño del lienzo y, en las animadas, el
            # número de cuadros. Nada de esto descomprime todavía.
            cuadros = max(1, getattr(im, "n_frames", 1))
            if im.width * im.height * cuadros > settings.IMAGENES_MAX_MEGAPIXELES * 1_000_000:
                raise ImagenIlegible(
                    f"La imagen tiene más de {settings.IMAGENES_MAX_MEGAPIXELES} megapíxeles"
                    + (" sumando todos sus cuadros." if cuadros > 1 else "."))
            icc = im.info.get("icc_profile")
            salida = io.BytesIO()

            if tipo == "image/jpeg":
                girada = im.getexif().get(0x0112, 1) not in (1, None)
                if girada:
                    # Con las tablas de cuantización y el submuestreo del
                    # original: la misma calidad y casi el mismo peso. Con una
                    # calidad fija (95) una foto de 5,8 MB salía de 6,8 —medido
                    # en la prueba de QA del 2026-10-03—.
                    opciones = {"optimize": True, "icc_profile": icc, "comment": b""}
                    tablas = getattr(im, "quantization", None)
                    submuestreo = JpegImagePlugin.get_sampling(im)
                    if tablas and submuestreo != -1:
                        opciones.update(qtables=tablas, subsampling=submuestreo)
                    else:
                        opciones["quality"] = 95
                    derecha = ImageOps.exif_transpose(im)
                    derecha.save(salida, "JPEG", **opciones)
                else:
                    im.save(salida, "JPEG", quality="keep", optimize=True,
                            icc_profile=icc, comment=b"")

            elif tipo == "image/png":
                opciones = {"icc_profile": icc}
                if "transparency" in im.info:
                    opciones["transparency"] = im.info["transparency"]
                if getattr(im, "is_animated", False):
                    opciones.update(save_all=True, duration=_cuadros(im),
                                    loop=im.info.get("loop", 0))
                im.save(salida, "PNG", **opciones)

            else:  # image/webp
                # VP8L es el WebP sin pérdida: se guarda igual, para no meterle
                # pérdida a una captura de pantalla que no la tenía.
                sin_perdida = b"VP8L" in contenido[:64]
                opciones = {"icc_profile": icc, "lossless": sin_perdida}
                if not sin_perdida:
                    opciones["quality"] = 92
                if getattr(im, "is_animated", False):
                    opciones.update(save_all=True, duration=_cuadros(im),
                                    loop=im.info.get("loop", 0))
                im.save(salida, "WEBP", **opciones)

            return salida.getvalue()
    except ImagenIlegible:
        raise
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError,
            SyntaxError) as exc:
        # La firma de los primeros bytes era buena pero el resto no se puede
        # leer: tampoco la podría pintar ningún navegador.
        raise ImagenIlegible("La imagen está dañada o no se puede leer.") from exc


async def limpiar_subida(contenido: bytes, tipo: str) -> bytes:
    """`sin_metadatos` para una ruta de subida: en un hilo y con 422 si falla.

    En un hilo porque reescribir una foto de 10 MB son cientos de milisegundos
    de CPU, y dentro del bucle de eventos congelarían el portal entero mientras
    tanto.
    """
    from fastapi import HTTPException, status
    from starlette.concurrency import run_in_threadpool

    if tipo not in LIMPIABLES:
        return contenido
    turno = _turno()
    try:
        async with asyncio.timeout(settings.IMAGENES_ESPERA_S):
            await turno.acquire()
    except TimeoutError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="El servidor está procesando otras imágenes. Intente de nuevo en un momento.")
    try:
        return await run_in_threadpool(sin_metadatos, contenido, tipo)
    except ImagenIlegible as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))
    finally:
        turno.release()


#: Un semáforo por bucle de eventos. En producción hay uno solo; las pruebas
#: abren uno por `TestClient`, y un `asyncio.Semaphore` queda atado al primer
#: bucle que lo usa.
_turnos: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore]" = (
    weakref.WeakKeyDictionary())


def _turno() -> asyncio.Semaphore:
    bucle = asyncio.get_running_loop()
    turno = _turnos.get(bucle)
    if turno is None:
        turno = _turnos[bucle] = asyncio.Semaphore(max(1, settings.IMAGENES_EN_PARALELO))
    return turno

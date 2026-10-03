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
"""

import io

from PIL import Image, ImageOps, UnidentifiedImageError

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
            if im.width * im.height > settings.IMAGENES_MAX_MEGAPIXELES * 1_000_000:
                raise ImagenIlegible(
                    f"La imagen tiene más de {settings.IMAGENES_MAX_MEGAPIXELES} megapíxeles.")
            icc = im.info.get("icc_profile")
            salida = io.BytesIO()

            if tipo == "image/jpeg":
                girada = im.getexif().get(0x0112, 1) not in (1, None)
                if girada:
                    derecha = ImageOps.exif_transpose(im)
                    derecha.save(salida, "JPEG", quality=95, optimize=True,
                                 icc_profile=icc, comment=b"")
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

    try:
        return await run_in_threadpool(sin_metadatos, contenido, tipo)
    except ImagenIlegible as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))

"""Imágenes de verdad para las pruebas, y cómo compararlas.

Desde que el portal les quita los metadatos al subirlas (core/metadatos.py),
una imagen se abre y se vuelve a escribir: ya no basta con la firma de los
primeros bytes seguida de relleno, y lo que se descarga no es byte a byte lo
que se subió. Lo que sí debe ser igual es **la imagen**: mismas dimensiones y
mismos píxeles (en PNG y WEBP sin pérdida, exactamente; en JPEG, casi).
"""

import io

from PIL import Image


def png(ancho: int = 4, alto: int = 3, color=(20, 142, 194, 255), **guardar) -> bytes:
    salida = io.BytesIO()
    Image.new("RGBA", (ancho, alto), color).save(salida, "PNG", **guardar)
    return salida.getvalue()


def jpeg(ancho: int = 8, alto: int = 6, color=(179, 22, 113), **guardar) -> bytes:
    salida = io.BytesIO()
    Image.new("RGB", (ancho, alto), color).save(salida, "JPEG", quality=95, **guardar)
    return salida.getvalue()


def misma_imagen(a: bytes, b: bytes, error_medio: float = 0.0) -> bool:
    """Mismas dimensiones y los mismos píxeles.

    Sin `error_medio`, idénticos (PNG, WEBP sin pérdida). Con él, para JPEG y
    WEBP con pérdida: volver a comprimir mueve algún píxel de un borde nítido
    varios niveles, pero la diferencia media sobre 255 se queda en décimas
    —medido: 0,6 en una imagen de 40 × 30 con un borde duro, 0,004 en una foto—.
    """
    with Image.open(io.BytesIO(a)) as ia, Image.open(io.BytesIO(b)) as ib:
        if ia.size != ib.size:
            return False
        pa = ia.convert("RGBA").tobytes()
        pb = ib.convert("RGBA").tobytes()
    if not error_medio:
        return pa == pb
    return sum(abs(x - y) for x, y in zip(pa, pb)) / len(pa) <= error_medio

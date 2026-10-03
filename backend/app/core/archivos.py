"""Que un archivo subido sea lo que dice ser.

Las tres puertas de subida del portal —adjuntos de ticket, documentos del
expediente, fotos del catálogo visual— decidían el tipo por lo que **declara
el navegador** y, si no, por la extensión. Las dos cosas las escribe quien
sube: un HTML con `Content-Type: image/png` se guardaba como `.png` y se
servía como imagen.

Hoy eso no llega a ejecutarse —nginx manda `X-Content-Type-Options: nosniff`
y la política de contenido no deja correr scripts de fuera—, pero es una
sola cabecera la que separa el portal de servir HTML ajeno en su propio
origen. Esto mira los primeros bytes: la firma que cada formato lleva al
principio y que el navegador no puede falsificar sin dejar de ser ese formato.
"""


def _es_heic(contenido: bytes) -> bool:
    # Contenedor ISO: tamaño de caja (4 bytes), "ftyp" y la marca.
    return contenido[4:8] == b"ftyp" and contenido[8:12] in {
        b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis", b"mif1", b"msf1",
    }


def _es_texto(contenido: bytes) -> bool:
    # Un binario casi siempre lleva bytes nulos pronto; un texto, nunca.
    return b"\x00" not in contenido[:8192]


FIRMAS = {
    "image/jpeg": lambda c: c.startswith(b"\xff\xd8\xff"),
    "image/png": lambda c: c.startswith(b"\x89PNG\r\n\x1a\n"),
    "image/gif": lambda c: c[:6] in (b"GIF87a", b"GIF89a"),
    "image/webp": lambda c: c[:4] == b"RIFF" and c[8:12] == b"WEBP",
    "image/heic": _es_heic,
    # La especificación admite basura antes de la cabecera, dentro del primer KB.
    "application/pdf": lambda c: b"%PDF-" in c[:1024],
    "text/plain": _es_texto,
}


def contenido_coincide(contenido: bytes, tipo: str) -> bool:
    """Si los bytes corresponden al tipo declarado. Un tipo sin firma conocida
    no pasa: la lista de lo que se acepta la decide cada puerta, y esto solo
    confirma que lo que llegó es de verdad uno de esos."""
    comprobar = FIRMAS.get(tipo)
    return bool(comprobar and contenido and comprobar(contenido))

"""Tope al tamaño de lo que se manda en JSON.

**Por qué.** NGINX deja pasar hasta 20 MB por petición, que es lo que necesitan
las subidas de archivos. Pero un cuerpo JSON de 20 MB se parsea entero en
memoria —el texto, el diccionario y las cadenas de Python, varias veces su
tamaño— antes de que Pydantic pueda decir que un campo admite 5000 caracteres.
Diez de esas a la vez son gigas de RAM en un servidor que comparte memoria con
Ollama. El texto legítimo más largo del portal, la documentación de TI, son
50 000 caracteres: un mega sobra.

Las subidas (`multipart/form-data`) no pasan por aquí: cada endpoint lee el
archivo con su propio tope y nunca entero en memoria.

Se mira el `Content-Length` para cortar sin leer nada, y además se cuentan los
bytes que llegan, porque una petición en trozos (`chunked`) no lo trae.
"""

from fastapi import HTTPException
from starlette.responses import JSONResponse

from app.core.errores import cuerpo_de_error

DETALLE = "La solicitud es demasiado grande."


class LimiteDeCuerpo:
    def __init__(self, app, maximo_bytes: int):
        self.app = app
        self.maximo = maximo_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        cabeceras = dict(scope.get("headers") or [])
        tipo = cabeceras.get(b"content-type", b"").decode("latin-1").lower()
        if tipo.startswith("multipart/form-data"):
            await self.app(scope, receive, send)
            return

        declarado = cabeceras.get(b"content-length", b"").decode("latin-1")
        if declarado.isdigit() and int(declarado) > self.maximo:
            respuesta = JSONResponse(cuerpo_de_error(413, DETALLE), status_code=413)
            await respuesta(scope, receive, send)
            return

        recibidos = 0

        async def recibir_contando():
            nonlocal recibidos
            mensaje = await receive()
            if mensaje["type"] == "http.request":
                recibidos += len(mensaje.get("body", b""))
                if recibidos > self.maximo:
                    # FastAPI deja pasar las HTTPException que surgen al leer
                    # el cuerpo, así que llega al manejador común como un 413.
                    raise HTTPException(status_code=413, detail=DETALLE)
            return mensaje

        await self.app(scope, recibir_contando, send)

"""La cabecera que entrega el token renovado. Ver `_renovar_si_hace_falta`."""


class EntregaTokenRenovado:
    """Pone en la respuesta el token que renovó `get_current_user`.

    La dependencia lo deja en `request.state.token_renovado` (ver
    `_renovar_si_hace_falta` en api/deps.py). Es ASGI puro y no
    `BaseHTTPMiddleware` a propósito: solo toca el arranque de la respuesta,
    así que no se interpone en los flujos de eventos, que no terminan nunca.
    """

    CABECERA = b"x-token-renovado"

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def enviar(mensaje):
            if mensaje["type"] == "http.response.start":
                nuevo = (scope.get("state") or {}).get("token_renovado")
                if nuevo:
                    mensaje = {**mensaje, "headers": [*mensaje.get("headers", []),
                                                      (self.CABECERA, nuevo.encode("latin-1"))]}
            await send(mensaje)

        await self.app(scope, receive, enviar)

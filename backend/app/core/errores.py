"""Una sola forma para todos los errores del API.

Cualquier respuesta de error del portal es este objeto:

    {
      "detail": "Texto para la persona, en español.",
      "codigo": "no_encontrado",
      "errores": [{"campo": "nombre", "mensaje": "debe tener al menos 3 caracteres"}],
      "referencia": "a1b2c3d4"
    }

`detail` y `codigo` van siempre; `errores` solo en las validaciones y
`referencia` solo en los errores internos.

**Por qué hacía falta.** Había tres formas distintas y el frontend tenía que
adivinar cuál le tocaba:

  - Un `HTTPException` daba `{"detail": "texto"}`.
  - Una validación de Pydantic daba `{"detail": [ {loc, msg, type, input}, ... ]}`:
    una lista en inglés, que la pantalla terminaba pintando como objeto —y React
    revienta con eso— y que además **devolvía tal cual lo que se había mandado**,
    contraseñas incluidas, en el campo `input`.
  - Un fallo no previsto daba `Internal Server Error` en texto plano, ni
    siquiera JSON, y sin nada con qué encontrarlo en los registros.

`detail` conserva el nombre de siempre a propósito: es el que ya lee todo el
frontend y el que usan las pruebas.
"""

import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DataError, IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import logger

#: Para que el frontend decida sin leer el texto, que puede cambiar.
CODIGOS = {
    400: "solicitud_invalida",
    401: "sesion_invalida",
    403: "sin_permiso",
    404: "no_encontrado",
    405: "metodo_no_permitido",
    409: "conflicto",
    413: "archivo_demasiado_grande",
    422: "validacion",
    429: "demasiados_intentos",
    500: "error_interno",
    502: "servicio_no_disponible",
    503: "servicio_no_disponible",
    504: "servicio_no_disponible",
}

#: Starlette pone su propio texto, en inglés, cuando la ruta o el método no
#: existen. Esos llegan aquí sin pasar por ningún `raise` del portal.
_TEXTOS_DE_STARLETTE = {
    "Not Found": "No se encontró lo que busca.",
    "Method Not Allowed": "Esa operación no existe.",
    "Unauthorized": "La sesión no es válida. Inicie sesión de nuevo.",
    "Forbidden": "No tiene permiso para esto.",
    "Not authenticated": "Hace falta iniciar sesión.",
}

#: Cómo se le dice a una persona cada campo que puede rechazar una validación.
#: Lo que no esté aquí sale con su nombre técnico, que al menos es exacto.
NOMBRES_DE_CAMPO = {
    "descripcion_original": "la descripción",
    "comentario": "el comentario",
    "categoria": "la categoría",
    "prioridad": "la prioridad",
    "solucion": "la solución",
    "descartado": "lo que se descartó",
    "nombre": "el nombre",
    "numero_empleado": "el número de empleado",
    "email": "el correo",
    "area": "el área",
    "rol": "el rol",
    "idioma_preferido": "el idioma",
    "marca": "la marca",
    "modelo": "el modelo",
    "numero_serie": "el número de serie",
    "ubicacion": "la ubicación",
    "notas": "las notas",
    "pagina": "la página",
    "por_pagina": "los resultados por página",
    "buscar": "la búsqueda",
    "identificador": "el número de empleado",
    "password": "la contraseña",
}


#: Los tipos de error de Pydantic que de verdad se ven en el portal, dichos
#: como los diría una persona. Lo que no esté aquí conserva el texto original.
def _mensaje_de_validacion(error: dict) -> str:
    tipo = error.get("type", "")
    ctx = error.get("ctx") or {}
    if tipo == "missing":
        # Sin género: el resumen antepone el nombre del campo, y "la
        # descripción es obligatorio" salía así.
        return "hace falta"
    if tipo == "string_too_short":
        # "Al menos 1 caracteres" es lo que se leía al dejar en blanco un campo
        # obligatorio: se dice lo que pasó.
        if ctx.get("min_length") == 1:
            return "no puede quedar en blanco"
        return f"debe tener al menos {ctx.get('min_length')} caracteres"
    if tipo == "string_too_long":
        return f"admite como máximo {ctx.get('max_length')} caracteres"
    if tipo in ("int_parsing", "int_type"):
        return "debe ser un número entero"
    if tipo in ("float_parsing", "float_type", "decimal_parsing"):
        return "debe ser un número"
    if tipo in ("bool_parsing", "bool_type"):
        return "debe ser sí o no"
    if tipo in ("string_type",):
        return "debe ser texto"
    if tipo in ("date_parsing", "date_from_datetime_parsing", "datetime_parsing", "datetime_from_date_parsing"):
        return "no es una fecha válida"
    if tipo in ("enum", "literal_error"):
        return "no es una opción válida"
    if tipo in ("greater_than", "greater_than_equal", "less_than", "less_than_equal"):
        return "está fuera del rango permitido"
    if tipo == "json_invalid":
        return "el cuerpo no es JSON válido"
    if tipo == "value_error" and "email" in str(error.get("msg", "")).lower():
        return "no es un correo válido"
    mensaje = str(error.get("msg") or "no es válido")
    return mensaje.removeprefix("Value error, ")


def cuerpo_de_error(estado: int, detalle: str, **extra) -> dict:
    cuerpo = {"detail": detalle, "codigo": CODIGOS.get(estado, "error")}
    cuerpo.update({clave: valor for clave, valor in extra.items() if valor is not None})
    return cuerpo


async def _error_http(_peticion: Request, exc: StarletteHTTPException) -> JSONResponse:
    detalle = exc.detail if isinstance(exc.detail, str) and exc.detail else ""
    detalle = _TEXTOS_DE_STARLETTE.get(detalle, detalle) or "No se pudo completar la solicitud."
    return JSONResponse(cuerpo_de_error(exc.status_code, detalle),
                        status_code=exc.status_code, headers=getattr(exc, "headers", None))


async def _error_de_validacion(_peticion: Request, exc: RequestValidationError) -> JSONResponse:
    errores = []
    for error in exc.errors():
        # "body" / "query" no le dicen nada a nadie: se queda el nombre del campo.
        partes = [str(p) for p in error.get("loc", ())
                  if p not in ("body", "query", "path", "header", "form", "cookie")]
        errores.append({"campo": ".".join(partes) or "solicitud",
                        "mensaje": _mensaje_de_validacion(error)})
    # Un error de la petición entera —dos campos que no casan entre sí— no
    # tiene un campo que nombrar: va solo el mensaje.
    resumen = "; ".join(e["mensaje"] if e["campo"] == "solicitud"
                        else f"{NOMBRES_DE_CAMPO.get(e['campo'], e['campo'])} {e['mensaje']}"
                        for e in errores[:3])
    if len(errores) > 3:
        resumen += f" (y {len(errores) - 3} más)"
    return JSONResponse(cuerpo_de_error(422, f"Revise los datos: {resumen}.", errores=errores),
                        status_code=422)


async def _dato_fuera_de_rango(_peticion: Request, exc: DataError) -> JSONResponse:
    """La base rechazó un valor: un id de 20 dígitos, una página tan lejana que
    el desplazamiento no cabe en un entero, un texto más largo que su columna.

    Es un dato del cliente, no un fallo del servidor, así que es un 422. Las
    validaciones de cada ruta atrapan antes los casos conocidos; esto es la
    red para los que nadie previó, que antes salían como un 500.
    """
    return JSONResponse(cuerpo_de_error(422, "Un dato no es válido o está fuera de rango."),
                        status_code=422)


async def _choque_de_integridad(_peticion: Request, exc: IntegrityError) -> JSONResponse:
    """Una restricción de la base: una referencia a algo que no existe, un valor
    que ya está registrado. Igual que `_dato_fuera_de_rango`: la red detrás de
    las validaciones de cada ruta."""
    return JSONResponse(cuerpo_de_error(409, "La operación choca con datos ya registrados."),
                        status_code=409)


async def _valor_invalido(peticion: Request, exc: ValueError) -> JSONResponse:
    """**El byte nulo.** Postgres no admite el carácter `\\x00` dentro de un
    texto, y el controlador lo rechaza con un `ValueError` antes de mandar la
    consulta: cualquier campo de texto que lo trajera —el inicio de sesión, la
    descripción de un ticket, un comentario— tumbaba la petición con un 500.
    Llega pegando texto de otro programa, no hace falta mala intención.

    Cualquier otro `ValueError` sigue siendo un error interno y se trata como tal.
    """
    if "NUL (0x00)" in str(exc):
        return JSONResponse(
            cuerpo_de_error(422, "El texto contiene un carácter no válido. Vuelva a escribirlo "
                                 "en lugar de pegarlo."),
            status_code=422)
    return await _error_inesperado(peticion, exc)


async def _error_inesperado(peticion: Request, exc: Exception) -> JSONResponse:
    """Lo que nadie previó. A la persona se le da una referencia corta; en el
    registro queda esa misma referencia junto con la traza completa, que es lo
    que TI necesita para encontrarlo entre miles de líneas."""
    referencia = uuid.uuid4().hex[:8]
    logger.error("Error no controlado", exc_info=exc,
                 extra={"referencia": referencia, "ruta": peticion.url.path,
                        "metodo": peticion.method})
    return JSONResponse(
        cuerpo_de_error(500, "Ocurrió un error interno. Si se repite, avise al área de TI "
                             f"con la referencia {referencia}.", referencia=referencia),
        status_code=500,
    )


def registrar_manejadores(app: FastAPI) -> None:
    app.add_exception_handler(StarletteHTTPException, _error_http)
    app.add_exception_handler(RequestValidationError, _error_de_validacion)
    app.add_exception_handler(DataError, _dato_fuera_de_rango)
    app.add_exception_handler(IntegrityError, _choque_de_integridad)
    app.add_exception_handler(ValueError, _valor_invalido)
    app.add_exception_handler(Exception, _error_inesperado)

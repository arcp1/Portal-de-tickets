#!/usr/bin/env python3
"""Cuánto tarda la IA local, desglosado, y de forma repetible.

    docker compose exec -T backend python - < scripts/medir-ia.py

Se manda por la entrada estándar y no como ruta: `scripts/` no está montado en
el contenedor, y copiarlo dentro tampoco vale porque el sistema de archivos del
backend es de solo lectura —a propósito—. Desde el anfitrión sin más tampoco
corre: `httpx` vive en la imagen, no en el sistema.

**Para qué sirve, y por qué desglosado.** Las latencias de la pantalla de Estado
dicen cuánto tardó una operación; esto dice **en qué** se fue ese tiempo, que es
lo único que permite decidir qué tocar:

    leer el prompt (prefill)  — limitado por cómputo. Sube si la CPU va rápido.
    generar la respuesta      — limitado por el ancho de banda a la RAM.

En esta planta, con el gobernador de energía en `powersave`, leer resultó ser
tres veces más lento que escribir —al revés de lo normal— y era el cuello de
botella que hacía fallar la clasificación del chat. Sin este desglose eso se ve
como "el modelo va lento" y se acaba cambiando de modelo, que no era el
problema.

**Se repite y se toma la mediana**, no el promedio ni una sola muestra: en un
procesador de 35 W la primera llamada y las siguientes se diferencian en un
factor de cinco, y un promedio mezcla las dos cosas en un número que no
describe ninguna.
"""

import statistics
import sys
import time

import httpx

from app.core.config import settings
from app.services.ollama_client import (
    PROMPT_CLASIFICACION, PROMPT_NORMALIZACION, _instruir,
)

HOST = settings.OLLAMA_HOST.rstrip("/")
REPETICIONES = 5

#: Descripciones distintas para cada repeticion, y **eso no es un detalle**.
#:
#: Ollama cachea el prompt. Mandar cinco veces el mismo texto mide la cache, no
#: el trabajo: medido en esta planta, 600 tokens tardan 30 s la primera vez y
#: 0,04 s las siguientes —unas mil veces menos—. Con el mismo prompt repetido,
#: este guion reportaba «leer: 2610 tok/s, despreciable» y se concluyo, mal, que
#: leer el prompt no costaba nada.
#:
#: En produccion el texto **siempre es nuevo**: es lo que acaba de escribir una
#: persona. Lo que si se repite es la instruccion, que va delante y por eso si
#: se cachea. Variar solo la descripcion reproduce exactamente eso.
DESCRIPCIONES = (
    "no jala la impresora del anden 2 y saca rayas negras",
    "el wifi del almacen se cae cada rato desde el lunes pasado",
    "no puedo entrar al sistema con mi usuario nuevo y dice que contacte a TI",
    "la pantalla del handheld se queda congelada al escanear codigos",
    "el tablero de produccion no carga desde la actualizacion",
    "la etiquetadora de la linea 3 se reinicia sola cada rato",
)

#: Los tres trabajos que hace el portal, con el tamaño real de cada uno.
#: El segundo elemento es una funcion: recibe la descripcion de esta repeticion
#: y devuelve el prompt completo.
TRABAJOS = (
    ("normalizar", lambda d: _instruir(PROMPT_NORMALIZACION, d), 150, None),
    ("clasificar", lambda d: _instruir(PROMPT_CLASIFICACION, d), 40, "json"),
    # Redactar no lleva instruccion fija delante, asi que aqui no hay prefijo
    # que se cachee: es el caso de cache totalmente fria.
    ("redactar", lambda d: f"En tres pasos, que revisar si: {d}", 200, None),
)


def _una(prompt: str, num_predict: int, formato) -> dict:
    cuerpo = {
        "model": settings.OLLAMA_MODELO_TEXTO,
        "prompt": prompt,
        "stream": False,
        "keep_alive": settings.OLLAMA_KEEP_ALIVE,
        "options": {"num_predict": num_predict, "temperature": 0.2},
    }
    if formato:
        cuerpo["format"] = formato

    inicio = time.monotonic()
    with httpx.Client(timeout=300) as cliente:
        datos = cliente.post(HOST + "/api/generate", json=cuerpo).json()
    return {
        "total": time.monotonic() - inicio,
        "leer_tok": datos.get("prompt_eval_count", 0),
        "leer_s": datos.get("prompt_eval_duration", 0) / 1e9,
        "generar_tok": datos.get("eval_count", 0),
        "generar_s": datos.get("eval_duration", 0) / 1e9,
        "carga_s": datos.get("load_duration", 0) / 1e9,
    }


def main() -> int:
    gobernador = "desconocido"
    try:
        with open("/proc/cpuinfo") as f:
            mhz = [float(l.split(":")[1]) for l in f if "MHz" in l]
        frecuencia = f"{statistics.mean(mhz):.0f} MHz de media"
    except Exception:  # noqa: BLE001 - dentro del contenedor puede no estar
        frecuencia = "no visible desde el contenedor"

    print(f"modelo: {settings.OLLAMA_MODELO_TEXTO}   keep_alive: {settings.OLLAMA_KEEP_ALIVE}")
    print(f"CPU: {frecuencia}")
    print(f"({REPETICIONES} repeticiones por trabajo; se reporta la mediana)\n")

    print(f"{'trabajo':<12} {'total':>7}  {'leer':>16}  {'generar':>16}")
    print("-" * 58)

    for nombre, hacer_prompt, num_predict, formato in TRABAJOS:
        # La primera se descarta: paga la carga del modelo, y mezclarla con las
        # demás la esconde. Se hace con una descripción que no se vuelve a usar.
        _una(hacer_prompt("arranque en frio que no cuenta"), num_predict, formato)

        # **Una descripción distinta por repetición.** Con la misma, de la
        # segunda en adelante se mide la caché de Ollama y no el trabajo.
        muestras = [_una(hacer_prompt(DESCRIPCIONES[i % len(DESCRIPCIONES)]),
                         num_predict, formato)
                    for i in range(REPETICIONES)]

        total = statistics.median(m["total"] for m in muestras)
        leer_s = statistics.median(m["leer_s"] for m in muestras)
        gen_s = statistics.median(m["generar_s"] for m in muestras)
        # Mediana y no la primera: ahora cada repetición lleva una descripción
        # distinta, así que el número de tokens varía entre ellas.
        leer_tok = statistics.median(m["leer_tok"] for m in muestras)
        gen_tok = statistics.median(m["generar_tok"] for m in muestras)

        v_leer = leer_tok / leer_s if leer_s > 0.01 else float("inf")
        v_gen = gen_tok / gen_s if gen_s > 0 else 0

        leer_txt = "caché" if leer_s <= 0.01 else f"{leer_tok:3.0f}tok {v_leer:5.1f}t/s"
        print(f"{nombre:<12} {total:6.2f}s  {leer_s:5.2f}s {leer_txt:>10}"
              f"  {gen_s:5.2f}s {gen_tok:3.0f}tok {v_gen:5.1f}t/s")

    print("\nLeer va limitado por computo y generar por memoria. Si al cambiar")
    print("el gobernador de energia sube 'leer' y 'generar' se queda igual, es")
    print("la senal de que el procesador estaba frenado. Ver DESPLIEGUE.md.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

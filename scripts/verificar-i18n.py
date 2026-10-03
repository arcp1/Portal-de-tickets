#!/usr/bin/env python3
"""
Comprueba que toda clave de traducción que el front pide existe en los tres
idiomas.

**Por qué hace falta.** Cuando i18next no encuentra una clave no falla: enseña
la clave cruda. En pantalla eso es un `dashboard.comentarios` en medio de una
frase, y no se ve hasta que alguien abre esa pantalla en ese idioma —que en
francés puede ser meses después—. La compilación no lo detecta porque para
Vite es una cadena cualquiera.

Dos cosas que hay que tener en cuenta o el resultado es ruido:

  * **Plurales.** i18next resuelve `t('x.y', {count})` contra `x.y_one` y
    `x.y_other`, no contra `x.y`. Buscar la clave a secas da falsos positivos.
  * **Concatenación.** `t('activar.donde_' + campo)` no es una clave, es un
    prefijo. Se excluyen.

Uso:  python3 scripts/verificar-i18n.py
Sale con código 1 si falta alguna, para poder encadenarlo antes de compilar.
"""
import json
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent / 'frontend' / 'src'
IDIOMAS = ['es', 'en', 'fr']
SUFIJOS = ['', '_one', '_other', '_zero', '_two', '_few', '_many']

LITERAL = re.compile(r"\bt\(\s*'([a-zA-Z0-9_.]+)'\s*(?![+,]?\s*\w*\s*\+)")
CONCATENADA = re.compile(r"\bt\(\s*'([a-zA-Z0-9_.]+)'\s*\+")


def existe(dic, clave):
    for sufijo in SUFIJOS:
        actual, bien = dic, True
        for parte in (clave + sufijo).split('.'):
            if not isinstance(actual, dict) or parte not in actual:
                bien = False
                break
            actual = actual[parte]
        if bien and isinstance(actual, str):
            return True
    return False


def main():
    idiomas = {}
    for i in IDIOMAS:
        ruta = RAIZ / 'locales' / f'{i}.json'
        if not ruta.exists():
            print(f'no existe {ruta}', file=sys.stderr)
            return 2
        idiomas[i] = json.loads(ruta.read_text(encoding='utf-8'))

    fuentes = sorted(
        list(RAIZ.glob('**/*.jsx')) + list(RAIZ.glob('**/*.js'))
    )
    prefijos, usadas = set(), {}
    for f in fuentes:
        texto = f.read_text(encoding='utf-8')
        prefijos.update(m.group(1) for m in CONCATENADA.finditer(texto))
        for m in LITERAL.finditer(texto):
            usadas.setdefault(m.group(1), f.relative_to(RAIZ))
    for p in prefijos:
        usadas.pop(p, None)

    fallos = 0
    for i, dic in idiomas.items():
        faltan = sorted((k, v) for k, v in usadas.items() if not existe(dic, k))
        if faltan:
            fallos += len(faltan)
            print(f'\n{i}: faltan {len(faltan)}')
            for clave, archivo in faltan:
                print(f'   {clave:44} ({archivo})')

    # Y al revés no se comprueba: sobrar una clave no rompe nada en pantalla,
    # y varias existen solo para un idioma por razones de idioma.
    total = len(usadas)
    if fallos:
        print(f'\n{fallos} claves sin traducción de {total} comprobadas')
        return 1
    print(f'{total} claves comprobadas en {", ".join(IDIOMAS)}: ninguna falta')
    return 0


if __name__ == '__main__':
    sys.exit(main())

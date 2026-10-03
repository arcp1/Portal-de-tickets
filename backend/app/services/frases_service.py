"""Frases de contraseña: lo que sí recuerda alguien de sesenta años.

**El problema real.** Pedirle a un operador de línea de 60 años que invente
"Xk9$mQ2p" tiene un solo desenlace: acaba escrita en un papel pegado al monitor,
y entonces vale cero. La contraseña más fuerte del mundo, apuntada al lado de la
pantalla, es más débil que una mediana que se recuerda.

**Por qué palabras y no símbolos.** Lo que resiste un ataque es la longitud, no
el zoológico de caracteres. Tres palabras concretas y separadas —"campo.reloj.
perro"— dan unos 24 bits, y con dos dígitos al final llegan a 30. "Marzo2026",
que es lo que la gente escribe cuando se le exige "una mayúscula y un número",
da 11. La frase es diez millones de veces más resistente **y** se recuerda a la
primera.

**Cómo está elegido el vocabulario.** Sustantivos concretos, cortos, de uso
diario y **sin acentos ni eñes**: en una terminal de planta el teclado no
siempre está en español, y una contraseña que no se puede teclear es una
contraseña perdida. Nada de palabras abstractas —"libertad", "proceso"— porque
no dejan imagen mental y se olvidan igual que una cadena aleatoria.
"""

import secrets
from typing import List

from app.core.config import settings

#: Sustantivos concretos y cotidianos. Sin acentos, sin eñes, sin plurales.
#: Se puede alargar sin tocar nada más; cada palabra que se suma refuerza todas
#: las frases que se generen a partir de entonces.
PALABRAS = (
    "campo", "reloj", "perro", "gato", "mesa", "silla", "puerta", "llave",
    "libro", "papel", "lapiz", "vaso", "plato", "taza", "olla", "sarten",
    "cuchara", "tenedor", "jarra", "cubeta", "escoba", "trapo", "jabon",
    "cepillo", "peine", "espejo", "cama", "manta", "sabana", "toalla",
    "zapato", "bota", "guante", "casco", "gorra", "chaleco", "cinturon",
    "bolsa", "caja", "cinta", "clavo", "tuerca", "tornillo", "martillo",
    "pinza", "llanta", "motor", "banda", "cable", "foco", "lampara",
    "ventana", "techo", "pared", "piso", "escalera", "banco", "cajon",
    "arbol", "flor", "hoja", "rama", "raiz", "piedra", "arena", "barro",
    "agua", "fuego", "viento", "lluvia", "nube", "cielo", "sol", "luna",
    "rio", "lago", "monte", "cerro", "valle", "camino", "puente", "muro",
    "pan", "queso", "leche", "cafe", "arroz", "frijol", "maiz", "trigo",
    "sal", "azucar", "limon", "naranja", "manzana", "platano", "sandia",
    "melon", "durazno", "uva", "pera", "mango", "fresa", "nuez", "cacao",
    "caballo", "burro", "vaca", "toro", "cabra", "borrego", "cerdo",
    "gallina", "pato", "ganso", "pavo", "conejo", "raton", "ardilla",
    "aguila", "halcon", "paloma", "gorrion", "colibri", "tucan", "loro",
    "pez", "trucha", "mojarra", "camaron", "cangrejo", "tortuga", "rana",
    "abeja", "hormiga", "mosca", "grillo", "libelula", "mariposa",
    "carro", "camion", "tren", "barco", "lancha", "avion", "bici", "moto",
    "calle", "plaza", "parque", "mercado", "tienda", "taller", "bodega",
    "fabrica", "oficina", "cocina", "patio", "jardin", "huerto", "corral",
    "norte", "sur", "este", "oeste", "centro", "orilla", "fondo", "cima",
    "lunes", "martes", "jueves", "viernes", "sabado", "domingo",
    "enero", "febrero", "marzo", "abril", "junio", "julio", "agosto",
    "verde", "azul", "rojo", "negro", "blanco", "gris", "cafe", "rosa",
    "grande", "chico", "largo", "corto", "alto", "bajo", "ancho", "delgado",
    "nuevo", "viejo", "limpio", "seco", "frio", "tibio", "dulce", "salado",
    "reja", "poste", "barra", "tabla", "viga", "lona", "cuerda", "nudo",
    "regla", "tijera", "aguja", "hilo", "boton", "broche", "parche",
    "radio", "bocina", "pantalla", "teclado", "raton", "cargador", "pila",
)

#: Separador. El punto se teclea igual en cualquier distribucion de teclado y
#: se ve claro al dictarlo por telefono, que es como TI ayuda de verdad.
SEPARADOR = "."


def generar_frase(palabras: int = 3, con_numero: bool = True) -> str:
    """Una frase memorable.

    `secrets` y no `random`: esto acaba siendo la contrasena de alguien, y el
    generador de numeros aleatorios normal es predecible si se conoce su estado.
    """
    elegidas = [secrets.choice(PALABRAS) for _ in range(palabras)]
    frase = SEPARADOR.join(elegidas)
    if con_numero:
        # Dos digitos al final. Suben la resistencia sin estorbar a la memoria:
        # un numero de dos cifras se recuerda solo.
        frase += SEPARADOR + f"{secrets.randbelow(90) + 10}"
    return frase


def sugerencias(cuantas: int = 3) -> List[str]:
    """Varias opciones para que la persona escoja la que le haga gracia.

    Se ofrecen tres y no una a proposito: elegir entre opciones ayuda a
    recordar mucho mas que aceptar lo primero que sale. La que a alguien le
    resulta absurda —"vaca.escoba.limon"— es justo la que no se le olvida.

    Todas cumplen la politica del portal por construccion, asi que la persona
    no se topa con un rechazo despues de haberla memorizado.
    """
    minimo = settings.PASSWORD_MIN_LONGITUD
    salida = []
    intentos = 0
    while len(salida) < cuantas and intentos < 100:
        intentos += 1
        frase = generar_frase()
        if len(frase) >= minimo and frase not in salida:
            salida.append(frase)
    return salida

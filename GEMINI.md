# Encender Gemini

Guía para poner la llave de Gemini en el portal, y para entender qué se paga.

---

## Antes que nada: la llave no se comparte por chat

**No me la mandes a mí, ni por correo, ni por WhatsApp.** Quien tenga esa llave
gasta con la cuenta de la empresa. La pones tú, directamente en el servidor, y
nadie más la ve.

```bash
nano /opt/portal-tickets/.env
```

Buscas la línea `GEMINI_API_KEY=` y pegas la llave después del `=`. Guardas y
reinicias:

```bash
docker compose up -d backend
```

Listo. Para comprobar que quedó bien **no hace falta enseñarle la llave a nadie**:
entra al portal, **Sistema → Estado del sistema**, y la tarjeta de Gemini debe decir *Arriba*. Ahí
solo se muestran los últimos cuatro caracteres, suficiente para saber cuál llave
está puesta e inútil para usarla.

Si alguna vez se filtra, se revoca desde
[aistudio.google.com/apikey](https://aistudio.google.com/apikey) y se genera otra.
Por eso conviene que la llave del portal sea suya y de nadie más.

---

## Ojo con la suscripción

**Google One / Gemini Pro no incluye el uso de la API.** Son dos productos
distintos:

| Lo que tienes | Para qué sirve |
|---|---|
| Suscripción Google AI Pro | La app de Gemini para ti: chatear, subir archivos, más cuota en AI Studio para prototipar. |
| Llave de API con facturación | Que **el portal** consulte a Gemini por su cuenta, sin que nadie esté enfrente. |

Lo segundo se factura aparte, por proyecto de Google Cloud. Es lo que necesita el
portal.

La buena noticia es que también existe un **nivel gratuito** con límite diario, y
con nuestro volumen probablemente alcance. Se puede arrancar ahí y activar la
facturación solo si el uso lo rebasa.

---

## Qué se paga

Se paga por *token*, que es más o menos tres cuartos de palabra. Se cobra lo que
entra (la pregunta más los tickets de contexto) y lo que sale (la respuesta).

Tarifas públicas de Flash al 27 de agosto de 2026: **0.30 USD por millón de
tokens de entrada** y **2.50 USD por millón de salida**.

Con el volumen que esperamos —40 consultas al día, cinco tickets de contexto cada
una— eso da:

```
Entrada:  880 consultas × 3 000 tokens = 2.64 M  →  0.79 USD
Salida:   880 consultas ×   300 tokens = 0.26 M  →  0.66 USD
                                          Total  ≈ 1.45 USD al mes
```

Menos de treinta pesos. Aunque el uso se cuadruplique, sigue siendo comida de
un día.

**Por qué es tan barato:** porque Gemini no hace el trabajo pesado. Ollama corre
en la planta y se queda con todo lo que pasa seguido —clasificar, normalizar,
generar embeddings, cientos de veces al día— y eso es gratis. Gemini entra solo
donde hace falta redactar sobre varios tickets a la vez, que son pocas consultas.

Si algún día se quisiera usar el modelo Pro en lugar de Flash, la entrada cuesta
unas seis veces más y la salida casi cinco. **Para este uso no aporta**: las
respuestas son cortas y sobre extractos que el portal ya recuperó.

---

## Cómo no llevarse un susto en la factura

Cuatro frenos, ya puestos:

- **Tope de contexto.** `GEMINI_MAX_EXTRACTOS=5`. Cada ticket de contexto cuesta
  tokens de entrada; el tope hace el gasto predecible.
- **Tope de respuesta.** `GEMINI_MAX_TOKENS_RESPUESTA=600`. Nadie lee más que eso
  en una pantalla de soporte.
- **Freno de cuota.** Si Google contesta que se agotó el límite, el portal deja de
  insistir un minuto en vez de reintentar en cada petición.
- **Interruptor.** `GEMINI_HABILITADO=false` lo apaga sin borrar la llave ni tocar
  nada más.

Y en la consola de Google Cloud conviene poner una **alerta de presupuesto** de,
digamos, 10 USD al mes. Si algo se dispara, avisa antes de que importe.

---

## Qué pasa si Gemini falla

Nada que el usuario note. Es la misma regla que con Ollama y no se negocia:

> Si no hay llave, si Google no contesta, si se agotó la cuota o si tardó
> demasiado, el portal enseña los tickets parecidos tal cual y sigue. Un ticket
> jamás se queda sin crearse porque un servicio de terceros tuvo un mal día.

Está cubierto con pruebas automáticas: sin llave, sin red, con timeout, con error
del servidor, con cuota agotada y con una respuesta de forma inesperada. En los
seis casos la función devuelve "no pude" y el flujo continúa.

---

## Qué sale de la planta

Cuando Gemini está encendido, lo que viaja a Google es **la pregunta de la persona
y extractos de tickets ya resueltos**. Nada más: ni el padrón de personal, ni los
resguardos, ni contraseñas, ni números de empleado.

Vale la pena tenerlo claro antes de encenderlo, porque es la pregunta que va a
hacer dirección.

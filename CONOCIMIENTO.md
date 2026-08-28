# De dónde saca el asistente lo que sabe

Respuesta a una pregunta concreta: *"¿cómo va a saber Gemini que la raya negra es
el rodillo y no el tóner?"*

**No lo va a saber.** Ni Gemini ni Ollama tienen forma de saber cómo se hacen las
cosas en esta planta. Eso no está en internet. Está en los tickets que TI ya
resolvió y en la documentación que TI ya escribió.

Por eso el portal no le pregunta a un modelo "¿qué hago con una raya negra?".
Hace otra cosa.

---

## Los cuatro pasos

### 1. Buscar en lo nuestro

Cuando alguien escribe *"me sale una línea oscura vertical cuando imprimo"*, el
portal busca en dos lugares, los dos propios:

- **Los tickets resueltos.** Con su solución y con lo que se descartó.
- **La documentación de TI.** Los procedimientos que ustedes escribieron.

La búsqueda es **por significado, no por palabras**. "Línea oscura vertical"
encuentra el ticket que decía "raya negra en todas las hojas" aunque no compartan
ni una palabra. Eso lo hace un modelo pequeño que corre en el servidor de la
planta, gratis y sin mandar nada afuera.

Medido con el caso real: el ticket correcto sale al **69 %** de parecido.

### 2. Si no hay nada, no se le pregunta a nadie

Éste es el paso que más previene las respuestas inventadas, y no cuesta nada.

Si la búsqueda no trae nada suficientemente parecido, **el portal ni siquiera
llama al modelo**. Contesta:

> De esto todavía no hay nada escrito. Nadie ha documentado una falla parecida.
> Levante el ticket: cuando se resuelva, quedará registrado para la próxima.

Un modelo al que no se le da nada, se lo inventa. La única forma segura de que no
invente es no preguntarle.

### 3. El modelo solo redacta lo encontrado

Cuando sí hay de dónde, al modelo se le entregan **esos pasajes y nada más**, con
instrucciones de usar solo eso. El modelo no aporta conocimiento: aporta
redacción. Ordena y resume lo que la planta ya sabía.

### 4. Se comprueba que no se haya salido

Antes de mostrar nada, el portal mide **qué tanto del vocabulario de la respuesta
viene de las fuentes**. Si el modelo empieza a hablar de fusores y kits de
mantenimiento cuando la nota decía rodillo, se descarta la respuesta y se
muestran los extractos tal cual.

Medido, con el corte en 0.40:

| Respuesta | Anclaje | Resultado |
|---|---|---|
| La que dio el modelo local | 0.58 – 0.64 | pasa |
| Breve y correcta | 1.00 | pasa |
| Mencionando lo que se descartó | 0.88 | pasa |
| "Revise el fusor y el kit de mantenimiento" | 0.09 | se descarta |
| Consejo genérico de internet | 0.00 | se descarta |

**Es una heurística, no una demostración.** Atrapa que el modelo se haya ido por
otro lado; no una tergiversación fina. Por eso **las fuentes se muestran siempre
junto a la respuesta**: la comprobación final la hace una persona.

---

## Lo que ya se probó y no era

El campo `solución` cuenta lo que funcionó. Faltaba el otro medio: *"le cambiamos
el tóner y siguió igual, no era eso"*.

Ese saber se perdía, y cuesta caro: media hora de un técnico repitiendo lo que
alguien ya descartó. Ahora tiene su propio campo al cerrar el ticket, se indexa
junto con la solución, y se muestra junto a la fuente:

> ⚠ **Ya se probó y no era:** se cambió el tóner completo y siguió saliendo igual.

### Un detalle que costó descubrir

Al principio ese descarte se le pasaba también al modelo. Con el modelo local, el
resultado fue éste:

> 3. Si la raya vuelve en menos de un mes, **cambiar el tóner completo
>    nuevamente.**

Leyó "se cambió el tóner y no era eso" y lo convirtió en una instrucción. Un
modelo de 3 000 millones de parámetros no distingue de forma confiable entre
*"esto se probó"* y *"esto se hace"*.

Así que ahora **al modelo local no se le da el descarte y a Gemini sí** —el
grande sí sabe qué hacer con esa información—, y a la persona se le muestra
siempre, junto a la fuente, donde no hay modelo que pueda invertirlo.

---

## Quién contesta: la escalera

Ésta es la parte que más se pregunta, así que va completa. Se sube un peldaño
**solo cuando el anterior no alcanzó**, y cada peldaño cuesta más que el de
abajo.

| | Cuándo | Quién redacta | Qué cuesta |
|---|---|---|---|
| **Nivel 0 · Directo** | La coincidencia no deja dudas (≥ 75 %) y no hay otra cosa distinta igual de buena | **Nadie.** Se entrega la solución ya escrita | Nada |
| **Nivel 1 · Ollama** | La coincidencia es parcial, o hay varias fuentes que conviene juntar | El modelo local, dentro de la planta | Nada |
| **Nivel 2 · Gemini** | Lo del nivel 1 no pasó los filtros | El modelo de pago | Céntimos |
| **Nivel 3 · Extractos** | Ningún modelo produjo algo utilizable | Nadie: van los pasajes tal cual | Nada |
| **Nivel 4 · Ticket** | No hay nada parecido en el conocimiento de la planta | Nadie. Se levanta el ticket | Nada |

**El nivel 0 es el que más trabajo hace y el que menos se nota.** Si alguien
escribe "me sale una raya negra" y eso ya está resuelto, no hay nada que
redactar: la respuesta ya está escrita. Meter un modelo en medio solo agregaría
latencia y una oportunidad de que le cambie el sentido.

Un detalle que costó descubrir: la misma falla reportada tres veces son **tres
tickets y una sola respuesta**. Sin comprobar que los pasajes de arriba dicen lo
mismo, tres copias del mismo texto se tomaban por tres fuentes distintas y
mandaban a redactar algo que ya estaba escrito.

### Dónde entra Gemini, en concreto

Dos lugares, y en los dos por el mismo motivo —hay que **sintetizar sobre varios
documentos**, que es justo lo que un modelo chico no hace bien—:

1. **Nivel 2 del asistente.** Cuando el local se queda corto. Son pocas consultas.
2. **Las soluciones generales.** Ahí Gemini va **primero**, y es el único lugar
   del portal donde eso pasa: redactar un procedimiento sobre diez tickets a la
   vez es exactamente su trabajo. Y es una consulta **por problema y por mes**,
   no una por ticket: el gasto no crece con el uso del portal.

Todo lo demás —clasificar, buscar por significado, generar embeddings, cientos de
veces al día— lo hace Ollama, gratis y sin que nada salga de la planta.

---

## Soluciones generales

Diez tickets sobre la misma falla dejan diez soluciones parecidas y ninguna
completa. Cada una cuenta lo que pasó ese día; ninguna cuenta **el problema**.

En **Soluciones** del menú, el portal enseña qué fallas ya se repitieron lo
suficiente y ofrece redactar el procedimiento: síntoma, causa más común, qué
hacer, y qué ya se descartó.

**Nada se publica solo.** El borrador lo escribe la máquina; TI lo lee, lo
corrige y lo firma. Mientras es borrador **no tiene embedding, así que no aparece
en ninguna búsqueda**: un procedimiento sin revisar no le contesta a nadie.

Una vez publicada, entra en las respuestas del asistente con una ventaja
deliberada sobre los tickets sueltos: está escrita para responder justo esa
pregunta.

### El mismo filtro, más estricto

El borrador también se mide contra los tickets de los que salió, y con un corte
más alto que en el asistente. El motivo: **un borrador se lee una vez y se
publica**, mientras que una respuesta del asistente lleva sus fuentes al lado
para comprobarla.

Hizo falta. Medido, el modelo local sacó un procedimiento para la raya negra que
decía "verificar el cable de alimentación" y "revisar la bandeja del papel" —dos
cosas que ningún ticket menciona y que solo *suenan* a impresora—. Se descartó
solo, y esa solución se queda para escribirla a mano o para cuando Gemini esté
encendido.

### Qué tan bien lo hace el modelo local

Medido, seis intentos con el mismo caso: **cinco redactó una respuesta correcta,
uno se quedó corto** y el portal mostró el extracto. El fallo es seguro: la
persona ve el ticket original con su solución completa.

Un detalle que vale la pena saber si algún día se cambia el modelo: **a un modelo
chico, cada regla de más en las instrucciones le quita calidad**. Con cuatro
reglas contestaba "NO_TENGO_INFORMACION" teniendo la respuesta enfrente. Con
tres, contesta bien. Eso está medido y anotado en el código; si se cambia el
modelo, hay que volver a medirlo en vez de asumir.

---

## Qué hace falta para que esto funcione

**Cerrar los tickets contando qué se hizo.** El sistema es tan bueno como lo que
se escriba al cerrar. "Ya quedó" no le sirve a nadie; "se limpió el rodillo de
transferencia con paño seco" le ahorra media hora al siguiente.

Por eso el campo de solución es obligatorio y tiene longitud mínima. No es
burocracia: es literalmente de dónde sale todo lo demás.

**Escribir la documentación de TI.** Cada procedimiento que se escriba —cómo dar
de alta un usuario de telefonía, dónde están las VLAN— entra en las respuestas del
asistente automáticamente. No hay que hacer nada más que escribirlo.

Y una consecuencia agradable: **el asistente mejora solo**. Cada ticket bien
cerrado lo hace un poco mejor, sin tocar código y sin pagar nada.

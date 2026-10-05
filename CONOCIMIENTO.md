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

En **Conocimiento → Procedimientos**, el portal enseña qué fallas ya se repitieron lo
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

## Lo que no cabe en un texto

Todo lo de arriba está escrito en prosa, y funciona mientras el problema se
pueda **nombrar**. Hay una clase de incidencia donde eso no alcanza:

> *"Mi copia sale borrosa."*
> *"Mi copia sale con una sombra doble."*
> *"Mi copia sale con una raya fina."*

Las tres se describen igual —"sale mal"— y se arreglan de tres maneras
distintas. Ninguna búsqueda por significado las separa, porque en el texto no
hay nada que separar. Quien tiene la hoja en la mano las separa de una mirada.

Así que ahí el portal hace lo contrario de lo que hace en todo lo demás: **en
vez de contestar, enseña y pregunta.**

    Usuario:  mi copia sale borrosa
    Portal:   ¿Se ve así su problema?
              [foto: hoja desvanecida]   [foto: raya vertical]
    Usuario:  (señala la primera)
    Portal:   Abra la bandeja 2, saque el cartucho y agítelo cinco veces.
              [captura señalada: destilde «Ahorro de tóner»]
              ¿Se arregló?
    Usuario:  Sí, ya quedó.

Lo que se entrega es la solución atada a **la foto que esa persona reconoció**,
no la que el parecido de texto puso primera.

Esto pasa en los dos sitios donde alguien cuenta su problema: el chat flotante
y la caja de descripción del formulario de ticket. No sólo en el chat, y el
motivo es que mucha gente nunca abre el chat: va derecha al formulario. Si las
fotos vivieran sólo en el chat, a esa persona el portal le enseñaría tres
sugerencias de texto sobre defectos que se describen igual y la mandaría a
levantar un ticket.

### Las fotos no las mira ningún modelo

No hay visión por computadora en ninguna parte de esto, y no es una limitación:
es la misma regla de siempre. **La imagen la etiqueta quien la sube**, que es
quien estuvo delante de la impresora. Lo único que empareja el modelo es texto
contra texto: lo que escribe el usuario contra lo que TI escribió al documentar
el defecto.

Un modelo de visión aquí solo añadiría una manera nueva de equivocarse sobre
algo que ya estaba escrito.

### Cuándo se activa, que es la mitad del problema

Esto **no** puede saltar en cualquier consulta. "No manda a imprimir" y "la
copia sale borrosa" son las dos de impresora y no se parecen en nada:

| | Qué pasa | Qué ayuda |
|---|---|---|
| **no manda a imprimir** | falta una función | el flujo de siempre: checklist, ticket |
| **la copia sale borrosa** | hay algo que ver | la foto, y verla es lo que lo resuelve |

Enseñarle fotos al primero es ruido que le estorba para llegar a su ticket. No
enseñárselas al segundo desperdicia lo único que lo habría resuelto sin levantar
nada.

Hay **dos puertas** y ninguna sobra:

1. **¿Esto describe algo que se ve?** Una tabla de términos de apariencia
   —borroso, manchado, parpadea, luz roja— y otra de ausencias de función —no
   imprime, no enciende, no aparece—. Instantánea, gratis y auditable: si
   clasifica mal, se corrige una línea. Es el mismo criterio con el que ya se
   clasifica por vocabulario de planta.
2. **¿Tenemos una foto de eso?** La búsqueda contra el catálogo. Da igual cuánto
   suene a defecto visual lo que alguien escriba: si TI no ha documentado nada
   parecido, **no hay nada que enseñar** y la consulta sigue su camino de
   siempre sin enterarse de que esto existió.

**Y el listón de parecido es más alto aquí que en el resto del asistente**, que
es al revés de lo que parece sensato. Medido con el modelo de la planta, sobre
la ficha de la copia borrosa ya escrita:

| Lo que escribe la persona | Parecido |
|---|---|
| "mi copia sale borrosa desde ayer" | 0,80 |
| "no me deja entrar, cuenta bloqueada" | 0,58 |

El corte va en 0,65, holgado entre las dos. La primera versión lo puso en 0,55
razonando que preguntar es más barato que responder y que una foto de más sólo
cuesta un "no"; el 0,58 del ruido dice que a esa altura la foto de más no es
rara, es la de una cuenta bloqueada delante de alguien que preguntaba por una
impresora. Se puede exigir más porque **una ficha está escrita para
emparejar** —título, síntoma y las frases que usa la gente— mientras que un
ticket cuenta lo que pasó un día concreto: el acierto sube a 0,80 donde el de un
ticket rondaba 0,69.

La segunda no vuelve prescindible a la primera, aunque lo parezca. Sin la
primera, "no manda a imprimir" emparejaría con la ficha de "la hoja sale en
blanco" —hablan de la misma impresora y de la misma ausencia de resultado— y el
portal enseñaría fotos de hojas a alguien cuyo problema es que el trabajo no
llega a la cola.

Y si las fotos que se enseñan no son, **"ninguna se parece" está siempre a la
vista**: se anota —una ficha que se enseña mucho y no confirma nadie está
emparejando con lo que no debe— y la conversación sigue exactamente como si esto
no existiera.

### Esto se vuelve universal solo

La tabla de términos la escribió alguien pensando en impresoras, pantallas y
luces de equipo. Mañana el problema visual será de una báscula, de una etiqueta
de embarque o de algo que hoy no existe en la planta, y nadie va a abrir el
código para darlo de alta.

Por eso cada ficha tiene un campo de **cómo lo dice la gente** —"queda recorrida
la etiqueta", "marca el peso en cero"— y esas frases **abren la primera puerta
igual que las del código**. El catálogo le va enseñando al portal a reconocer lo
que nadie previó, escribiendo, no programando.

### Los dos clics

La otra mitad de cada ficha son las capturas de la solución, señaladas. Hay
problemas que se arreglan destildando una casilla, y contar dónde está esa
casilla cuesta un párrafo que nadie sigue: *"abra propiedades, pestaña avanzado,
el tercer bloque, la casilla de abajo"*. Sobre la captura, cuesta una mirada.

### La última pregunta es la que más enseña

*"¿Se arregló?"* parece cortesía y no lo es. **Reconocer la foto y resolver el
problema son dos cosas distintas**, y confundirlas esconde el peor de los dos
fallos posibles:

> Una ficha con la foto perfecta y la solución equivocada **la reconoce todo el
> mundo**. En el tablero luce como la mejor del catálogo, con un 90 % de
> aciertos, mientras manda a la planta entera a agitar un cartucho que no era el
> problema.

Por eso cada ficha lleva cuatro cuentas y no tres, y las dos lecturas que
importan salen de dividirlas:

| | Qué significa | Qué hacer |
|---|---|---|
| se enseña y **no la reconocen** | la foto o las frases están mal: empareja con consultas que no son de este defecto | corregir la foto y las frases |
| la reconocen y **no les arregla** | la solución está mal escrita, o bajo una misma foto hay dos averías distintas | reescribirla, o partir la ficha en dos |

La pantalla del catálogo hace esa división y lo dice en una línea, con un mínimo
de casos por debajo del cual no diagnostica nada: con dos casos no hay patrón,
hay dos casos.

**Y si no se arregló, el ticket sale diciendo qué se probó ya.** La persona
levanta su incidencia con una línea añadida —visible y editable, no una
anotación a sus espaldas— que dice qué ficha del catálogo siguió y que no
funcionó. Es la misma idea que el campo de "ya se probó y no era" de los
tickets: media hora de un técnico se va en repetir lo que alguien ya descartó.

### La foto casi siempre ya existe

Documentar un defecto desde cero es trabajo, y el trabajo que se pide dos veces
no se hace ninguna. Pero **las fotos del problema ya están en el portal**: la
gente las adjunta a sus tickets desde que hay adjuntos —la hoja con la raya, la
pantalla con el error, el LED en rojo—.

Así que un ticket ya resuelto se convierte en ficha con un botón. Se lleva la
descripción de quien lo reportó, la solución de quien lo cerró, lo que se
descartó y las fotos adjuntas, y **nace en borrador**: eso es material en bruto,
todavía no está redactado para contestarle a nadie. Alguien tiene que leerlo,
ponerle título, escribir las frases con las que la gente lo dice, y publicar.

Las fotos se **copian**, no se enlazan: si mañana alguien borra ese adjunto —o
el ticket entero— la ficha no puede quedarse muda. Es conocimiento de la planta,
no una vista de un ticket. Lo que sí queda anotado es de cuál salió, para poder
abrirlo y comprobar el caso real dentro de un año.

### Lo que faltaba fotografiar también se apunta

Los contadores de arriba dicen cómo les va a las fichas **que existen**. No
dicen nada de las que faltan, y ése es el dato con el que se escribe la
siguiente.

Así que cuando alguien describe algo que se ve y el portal no tiene la foto, la
consulta se anota en la misma bitácora que ya lleva los huecos del asistente de
texto —**Sistema → Conciencia**, la lista de qué documentar el lunes—, con su
propio rótulo:

| Rótulo | Qué pasó |
|---|---|
| **Faltaba la foto** | describió un defecto que se ve y no teníamos ninguna imagen parecida |
| **Ninguna foto era** | se le enseñaron y ninguna era la suya |
| **La foto no arregló** | reconoció la suya y la solución no le funcionó |
| **Lo resolvió una foto** | reconoció la suya y quedó resuelto, sin ticket |

Sin esto, el catálogo visual sería el único rincón del portal que no rinde
cuentas de lo que no supo.

Y cuando sí resuelve, el ticket queda registrado con canal **visual**, junto al
checklist y la base de conocimiento: es lo que contesta si fotografiar un
defecto valió la pena. Cada uno de esos es un ticket que nadie de TI atendió.

### Cómo se sabe si está bien escrita

El disparador se puede equivocar de dos maneras y **ninguna se reporta sola**:
enseñando fotos a quien preguntó por la red —que molesta, y nadie avisa— y no
enseñándolas a quien sí tenía el defecto delante —que no se nota nunca—.

Contra lo primero está **el probador** de la pantalla de Catálogo visual: se
teclea la frase y se ve la decisión con su motivo, sin que a nadie se le enseñe
nada y sin ensuciar ninguna métrica. Un "no se activa" por *falta una función*
está bien resuelto; uno por *ninguna ficha se parece* teniendo la ficha escrita
significa que el síntoma está redactado con otras palabras que las que usa la
gente, y eso se arregla escribiendo la frase real en el campo de frases.

Contra lo segundo está la lista de huecos de arriba.

Y como el resto del conocimiento del portal, **mientras es borrador no le
contesta a nadie**. Para publicar hace falta al menos una foto del síntoma: sin
ella la ficha no puede hacer la única pregunta que la justifica.

### Lo que cuesta, y por qué acabó costando menos

Añadir esto metía una consulta más al modelo de embeddings en dos sitios donde
ya había otras: el chat y el formulario de ticket. Medido en esta máquina, un
embedding cuesta **entre 74 y 579 ms** según la frase —mediana 311—, así que no
es gratis.

Dos cosas lo dejaron mejor de como estaba:

- **El chat vectoriza una sola vez.** El mensaje se convierte en vector arriba y
  ese mismo vector sirve al catálogo y al asistente de texto. Antes, un mensaje
  que sonara a defecto visual y no tuviera foto se vectorizaba dos veces.
- **Lo ya calculado se recuerda.** Al escribir la descripción de un ticket hay
  tres bloques consultando por separado —sugerencias parecidas, respuesta del
  asistente, catálogo visual— y los tres mandaban el mismo texto al modelo: casi
  un segundo de CPU en cada pausa de escritura. Un embedding es una función pura
  del texto y del modelo, así que recordarlo no cambia ninguna respuesta; el
  segundo y el tercero pasaron a costar **cero**.

Lo delicado de una caché así es la clave, y merece decirse: el mismo texto
vectorizado *como pregunta* y *como documento* da vectores distintos —el modelo
está entrenado con prefijos de tarea— y confundirlos devolvería el vector
equivocado **sin que nada fallara**: la búsqueda encontraría peor, en silencio.
La clave lleva el prefijo ya pegado y el nombre del modelo, y hay una prueba que
lo comprueba.

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

**Fotografiar lo que se repite.** Cuando una falla se reconoce mirándola, una
foto en el catálogo visual resuelve en dos segundos lo que un párrafo no
resuelve nunca. No hace falta fotografiarlo todo: solo lo que vuelve.

Y una consecuencia agradable: **el asistente mejora solo**. Cada ticket bien
cerrado lo hace un poco mejor, sin tocar código y sin pagar nada.

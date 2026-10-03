/**
 * Obliga a que un valor sea una lista, y avisa cuando no lo era.
 *
 * **Por qué existe.** Casi todas las pantallas del portal guardan una respuesta
 * de la API en un estado que arranca como `[]` y luego la recorren con `.map`,
 * `.filter` o `.length`. Si esa respuesta llega con otra forma, el estado deja
 * de ser una lista y el primer recorrido **revienta el render entero**: el
 * límite de error sustituye la pantalla por "Algo se rompió en esta pantalla" y
 * ya no se puede hacer nada ahí.
 *
 * Los `catch` habituales no lo cubren. Solo atrapan fallos de red y códigos de
 * error; una respuesta **200 con el cuerpo equivocado** pasa de largo. Y esa es
 * la que ocurre de verdad: un proxy que devuelve su propia página, un
 * despliegue a medias donde el backend todavía no tiene ese endpoint, un cambio
 * en la forma de una respuesta.
 *
 * Pasó, y no en una pantalla cualquiera: el formulario de tickets se caía
 * entero porque una sugerencia de la base de conocimiento venía sin su lista.
 * La pantalla más importante del portal, tumbada por una ayuda que sobra.
 *
 * **Avisa en vez de callar.** Devolver `[]` en silencio arreglaría el síntoma y
 * escondería la causa: la pantalla saldría vacía y nadie sabría por qué. El
 * `console.warn` deja el rastro para quien abra las herramientas del navegador,
 * que es donde se va a buscar.
 *
 * @param {*} valor      Lo que devolvió la API.
 * @param {string} donde De dónde venía, para que el aviso diga algo útil.
 * @returns {Array}      El valor si era una lista; `[]` si no.
 */
export default function lista(valor, donde = 'la API') {
  if (Array.isArray(valor)) return valor;

  // `null` y `undefined` son el caso corriente de "no vino nada" y no merecen
  // ruido. Lo que sí lo merece es recibir algo **con otra forma**: eso no es
  // una ausencia, es una respuesta equivocada.
  if (valor != null) {
    console.warn(
      `Se esperaba una lista de ${donde} y llegó ${typeof valor}. ` +
      'La pantalla sigue con la lista vacía.',
      valor
    );
  }
  return [];
}

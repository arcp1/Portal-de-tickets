/**
 * Comprueba que una respuesta de la API traiga los campos que la pantalla va a
 * leer, y avisa cuando no.
 *
 * **Por qué existe, y por qué no bastaba [lista.js](./lista.js).** `lista`
 * cubre las pantallas cuyo estado es una lista. Pero varias del portal guardan
 * un **objeto** —`useState(null)`— y luego lo desarman:
 *
 *     const { tickets, chatbot } = datos;
 *     const canales = Object.entries(tickets.por_canal || {});
 *
 * La guarda habitual es `if (error || !datos)`, que solo atrapa el nulo. Con
 * un cuerpo de otra forma —una lista, la página de un proxy, un objeto de otro
 * endpoint— `datos` no es nulo, `tickets` sale `undefined` y la línea
 * siguiente revienta el render entero. El límite de error sustituye la
 * pantalla por «Algo se rompió en esta pantalla» y ahí se acaba.
 *
 * No es hipotético: se encontraron así tres pantallas del portal —métricas,
 * estado del sistema y expediente—, las tres cayéndose con el mismo `Cannot
 * read properties of undefined`.
 *
 * **Qué hace en su lugar.** Devolver `false` manda a la pantalla por su propia
 * rama de error, la que ya dice «no se pudieron cargar los datos». Eso es
 * cierto y es accionable; una pantalla rota no dice nada y encima se lleva por
 * delante lo que sí funcionaba.
 *
 * @param {*} valor       Lo que devolvió la API.
 * @param {string[]} campos Los campos de primer nivel que la pantalla lee.
 * @param {string} donde  De dónde venía, para que el aviso sirva de algo.
 * @returns {boolean}     `true` si se puede pintar con esto.
 */
export default function forma(valor, campos, donde = 'la API') {
  if (valor == null) return false;          // "no vino nada": ya lo dice la pantalla

  if (typeof valor !== 'object' || Array.isArray(valor)) {
    console.warn(
      `Se esperaba un objeto de ${donde} y llegó ${Array.isArray(valor) ? 'una lista' : typeof valor}.`,
      valor
    );
    return false;
  }

  const faltan = campos.filter((campo) => valor[campo] == null);
  if (faltan.length) {
    console.warn(
      `La respuesta de ${donde} no trae ${faltan.join(', ')}. ` +
      'La pantalla enseña su aviso de error en vez de romperse.',
      valor
    );
    return false;
  }
  return true;
}

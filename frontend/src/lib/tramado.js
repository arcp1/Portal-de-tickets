/**
 * Tramado ordenado de Bayer, para marcar lo crítico.
 *
 * Viene de `admit-one-ticket`, que lo resolvía con un shader de WebGL: unas
 * ochocientas líneas y **un contexto WebGL2 por tarjeta**. Un navegador
 * aguanta entre ocho y dieciséis contextos por página y el tablero lista
 * tickets sin límite, así que a partir del noveno el navegador destruye los
 * primeros y las tarjetas se quedan en negro. Además el portal ya paga
 * `backdrop-filter` en cada tarjeta y un filtro SVG a pantalla completa.
 *
 * El tramado es una textura, no una animación: se genera una vez en un
 * `<canvas>` con la misma matriz de Bayer 8×8 del shader, se cachea por paleta
 * y se reutiliza. Un canvas por paleta en lugar de un contexto por tarjeta.
 */

/** El carmesí de avería. El naranja es un punto caliente, no el color de la
 *  pieza: con un radio mayor el conjunto se lee naranja y pierde la lectura
 *  de alarma. */
export const PALETA_CRITICA = {
  textura: {
    colorBack: '#3d060d',
    colorFront: '#e0231c',
    colorHighlight: '#ff9d24',
    size: 3,
    colorSteps: 4,
  },
  degradado: {
    centreX: 0.5,
    centreY: 0.34,
    radius: 0.52,
    midStop: 0.38,
    colorLight: '#ff6a12',
    colorMid: '#a80f1a',
    colorDark: '#3d060d',
  },
};

/** La misma construcción en Warm orange, el naranja de la guía. Es la señal
 *  de alta: se reconoce como la misma familia que la crítica —mismo tramado,
 *  mismo gesto— pero un escalón por debajo. El radio es mayor y el contraste
 *  menor, así que el punto caliente se difumina en lugar de arder. */
export const PALETA_ALTA = {
  textura: {
    colorBack: '#33200c',
    colorFront: '#d67c2f',
    colorHighlight: '#f0aa5b',
    size: 3,
    colorSteps: 3,
  },
  degradado: {
    centreX: 0.5,
    centreY: 0.35,
    radius: 0.72,
    midStop: 0.45,
    colorLight: '#e8994f',
    colorMid: '#b06322',
    colorDark: '#33200c',
  },
};

// La misma matriz que usaba el shader. Ordenada, no aleatoria: el ruido
// blanco tiembla al escalar y esto no.
const BAYER8 = [
  0, 32, 8, 40, 2, 34, 10, 42,
  48, 16, 56, 24, 50, 18, 58, 26,
  12, 44, 4, 36, 14, 46, 6, 38,
  60, 28, 52, 20, 62, 30, 54, 22,
  3, 35, 11, 43, 1, 33, 9, 41,
  51, 19, 59, 27, 49, 17, 57, 25,
  15, 47, 7, 39, 13, 45, 5, 37,
  63, 31, 55, 23, 61, 29, 53, 21,
];

const hexARgb = (hex) => {
  const h = hex.replace('#', '');
  const n = h.length === 3 ? h.split('').map((c) => c + c).join('') : h;
  return [
    parseInt(n.slice(0, 2), 16),
    parseInt(n.slice(2, 4), 16),
    parseInt(n.slice(4, 6), 16),
  ];
};

const mezclar = (a, b, t) => a.map((v, i) => Math.round(v + (b[i] - v) * t));

const cacheTextura = new Map();

/**
 * Dibuja el degradado radial en pequeño, lo trama con Bayer y devuelve la
 * imagen. Se genera a baja resolución a propósito: el tramado tiene que verse
 * como puntos gordos, así que la imagen se estira después con
 * `image-rendering: pixelated` en lugar de dibujarse a tamaño real.
 */
export function texturaTramada(textura, degradado, medidas = {}) {
  const clave = JSON.stringify([textura, degradado, medidas]);
  if (cacheTextura.has(clave)) return cacheTextura.get(clave);
  if (typeof document === 'undefined') return '';

  // **El tamaño en píxeles es el parámetro que importa.** El tramado se ve
  // porque cada punto ocupa un píxel de la imagen; si la imagen se genera
  // grande y luego se muestra pequeña, los puntos se reducen por debajo del
  // píxel y no queda textura, solo un color plano. Así que quien la usa dice
  // cuántos píxeles quiere, no una proporción abstracta.
  const ancho = Math.max(2, Math.round(medidas.ancho ?? 240 / Math.max(1, textura.size)));
  const alto = Math.max(2, Math.round(medidas.alto ?? ancho / (medidas.aspect ?? 1)));
  const lienzo = document.createElement('canvas');
  lienzo.width = ancho;
  lienzo.height = alto;
  const ctx = lienzo.getContext('2d', { willReadFrequently: true });
  if (!ctx) return '';

  ctx.fillStyle = degradado.colorDark;
  ctx.fillRect(0, 0, ancho, alto);
  const radial = ctx.createRadialGradient(
    ancho * degradado.centreX, alto * degradado.centreY, 0,
    ancho * degradado.centreX, alto * degradado.centreY,
    Math.max(1, ancho * degradado.radius)
  );
  radial.addColorStop(0, degradado.colorLight);
  radial.addColorStop(Math.min(0.99, Math.max(0.01, degradado.midStop)), degradado.colorMid);
  radial.addColorStop(1, degradado.colorDark);
  ctx.fillStyle = radial;
  ctx.fillRect(0, 0, ancho, alto);

  const datos = ctx.getImageData(0, 0, ancho, alto);
  const px = datos.data;
  const fondo = hexARgb(textura.colorBack);
  const frente = hexARgb(textura.colorFront);
  const luz = hexARgb(textura.colorHighlight);
  const pasos = Math.max(1, Math.round(textura.colorSteps));

  for (let y = 0; y < alto; y += 1) {
    for (let x = 0; x < ancho; x += 1) {
      const i = (y * ancho + x) * 4;
      // Luminancia perceptual, los mismos coeficientes del shader.
      const lum = (0.2126 * px[i] + 0.7152 * px[i + 1] + 0.0722 * px[i + 2]) / 255;
      const umbral = BAYER8[(y % 8) * 8 + (x % 8)] / 64 - 0.5;
      const nivel = Math.max(0, Math.min(1,
        Math.round((lum + umbral / pasos) * pasos) / pasos));
      // Los dos tercios bajos van de fondo a frente; el último tramo se
      // reserva a la luz, que es lo que da el punto de brillo.
      const color = nivel > 0.75
        ? mezclar(frente, luz, (nivel - 0.75) * 4)
        : mezclar(fondo, frente, nivel / 0.75);
      px[i] = color[0];
      px[i + 1] = color[1];
      px[i + 2] = color[2];
      px[i + 3] = 255;
    }
  }
  ctx.putImageData(datos, 0, 0);

  const url = lienzo.toDataURL('image/png');
  cacheTextura.set(clave, url);
  return url;
}

/**
 * La textura crítica para el fondo entero de una tarjeta de la lista.
 *
 * 180 × 20 no es una proporción caprichosa: es la de una tarjeta del tablero,
 * y la imagen se dibuja al tamaño al que se va a ver en lugar de generarse
 * grande y reducirse. Un intento anterior la generaba a ochenta de ancho para
 * mostrarla a cuatro y salía una línea roja lisa — los puntos del tramado
 * habían quedado a un octavo de píxel.
 */
export function texturaCritica(ancho = 180, alto = 20) {
  return texturaTramada(PALETA_CRITICA.textura, PALETA_CRITICA.degradado, { ancho, alto });
}

/** Igual, en naranja, para prioridad alta. */
export function texturaAlta(ancho = 180, alto = 20) {
  return texturaTramada(PALETA_ALTA.textura, PALETA_ALTA.degradado, { ancho, alto });
}

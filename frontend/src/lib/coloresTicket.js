/**
 * La paleta de estado de los tickets, en un solo sitio.
 *
 * **Cubre dos ejes, no uno.** Lo pedido —Crítico, Alta, Media, Baja, En
 * Proveedor, Resuelto— mezcla prioridades con estados, que en el portal son
 * campos distintos: la prioridad es `baja|media|alta|critica` y el estado es
 * `abierto|en_proceso|espera_proveedor|resuelto|cerrado`. Aquí van los dos con
 * sus claves reales, tomadas de la base, para que se pueda escribir
 * `ticketStatusColors[ticket.prioridad]` sin traducir nada por el camino.
 *
 * **Los colores salen de la marca donde la marca tiene color.** Media es Solid
 * blue, Baja es Soft grey, Alta es Warm orange y Resuelto es Vivid green —los
 * secundarios de la guía—. Los dos que la guía no cubre, Crítica y En
 * Proveedor, se construyeron con la misma saturación y luminosidad que los
 * demás para que la fila no se vea de dos manuales distintos.
 *
 * Cada entrada trae cuatro valores porque son los cuatro que hace falta
 * combinar para pintar algo sobre el vidrio oscuro del portal:
 *
 *   base   el color pleno. Para barras, puntos y bordes de acento.
 *   texto  el mismo tono aclarado hasta que se lee sobre el fondo casi negro;
 *          `base` a secas no llega: `#1b3d79` sobre `#070b15` da 1.6:1.
 *   fondo  el relleno translúcido de una pastilla o un chip.
 *   borde  el filo de esa pastilla.
 */
export const ticketStatusColors = {
  // ---- Prioridad ----
  critica: {
    etiqueta: 'prioridad_critica',
    base: '#c1121f',
    texto: '#ff8a92',
    fondo: 'rgba(193, 18, 31, 0.18)',
    borde: 'rgba(193, 18, 31, 0.42)',
  },
  alta: {
    etiqueta: 'prioridad_alta',
    base: '#d67c2f',
    texto: '#e8994f',
    fondo: 'rgba(214, 124, 47, 0.17)',
    borde: 'rgba(214, 124, 47, 0.40)',
  },
  media: {
    etiqueta: 'prioridad_media',
    base: '#1b3d79',
    texto: '#7ea5dd',
    fondo: 'rgba(27, 61, 121, 0.32)',
    borde: 'rgba(27, 61, 121, 0.55)',
  },
  baja: {
    etiqueta: 'prioridad_baja',
    base: '#869199',
    texto: '#a4afb8',
    fondo: 'rgba(134, 145, 153, 0.16)',
    borde: 'rgba(134, 145, 153, 0.38)',
  },

  // ---- Estado ----
  abierto: {
    etiqueta: 'estado_abierto',
    base: '#148ec2',
    texto: '#5cbde8',
    fondo: 'rgba(20, 142, 194, 0.16)',
    borde: 'rgba(20, 142, 194, 0.40)',
  },
  en_proceso: {
    etiqueta: 'estado_en_proceso',
    base: '#1b3d79',
    texto: '#7ea5dd',
    fondo: 'rgba(27, 61, 121, 0.32)',
    borde: 'rgba(27, 61, 121, 0.55)',
  },
  espera_proveedor: {
    etiqueta: 'estado_espera_proveedor',
    base: '#7a4fbf',
    texto: '#b394e8',
    fondo: 'rgba(122, 79, 191, 0.18)',
    borde: 'rgba(122, 79, 191, 0.42)',
  },
  resuelto: {
    etiqueta: 'estado_resuelto',
    base: '#a4ae2d',
    texto: '#c2cd4a',
    fondo: 'rgba(164, 174, 45, 0.17)',
    borde: 'rgba(164, 174, 45, 0.40)',
  },
  cerrado: {
    etiqueta: 'estado_cerrado',
    base: '#869199',
    texto: '#a4afb8',
    fondo: 'rgba(134, 145, 153, 0.16)',
    borde: 'rgba(134, 145, 153, 0.38)',
  },
};

/** Devuelve la entrada de la paleta, con un neutro si la clave no existe. */
export function colorDeTicket(clave) {
  return ticketStatusColors[clave] ?? ticketStatusColors.cerrado;
}

/**
 * Las mismas entradas como variables CSS, para poder escribir
 * `style={variablesDeTicket('critica')}` y luego usar `var(--estado-base)`
 * dentro de una `GlassCard` sin pasar cuatro props por separado.
 */
export function variablesDeTicket(clave) {
  const c = colorDeTicket(clave);
  return {
    '--estado-base': c.base,
    '--estado-texto': c.texto,
    '--estado-fondo': c.fondo,
    '--estado-borde': c.borde,
  };
}

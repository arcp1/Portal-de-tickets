import React from 'react';

/**
 * El fondo: piezas de CGR flotando en gravedad cero.
 *
 * **AHORA MISMO NO ESTA MONTADO.** El fondo en uso es `FondoBurbujas`, las
 * esferas liquidas en azul y rosa, y va en todo el portal. Este se conserva
 * porque funciona; para volver a el se importa en `App.jsx` y se monta en
 * lugar del otro. Mientras nadie lo importe no entra en el paquete.
 *
 * Tres renders reales —un resorte de compresión oscuro, uno de extensión con
 * ganchos y otro de compresión pulido—, repetidos a distintos tamaños, girados
 * y algunos espejados. Siete piezas de tres archivos: detrás de un `blur(50px)`
 * y a media luz nadie va a reconocer que se repiten, y el portal descarga tres
 * imágenes en vez de siete.
 *
 * **Los renders vienen preparados, no crudos.** Se recortaron al contenido, se
 * les apagó el reflejo del suelo —un objeto que flota no tiene dónde
 * reflejarse— y se les aplastó el casi-negro a negro exacto, que es lo que
 * permite componerlos con `mix-blend-mode: screen` sin que se vea el
 * rectángulo. Pasaron de 4.1 MB entre los tres a 118 KB.
 *
 * **El límite de este enfoque, escrito para quien venga después:** la luz está
 * horneada en el píxel. Por eso las piezas grandes giran poco —±35°— y solo
 * las pequeñas dan la vuelta completa: en una pieza grande y brillante, girarla
 * 180° pone los reflejos abajo y el ojo lo caza. Quitar ese techo pide un
 * modelo 3D con la luz calculada en tiempo real, no más imágenes.
 */

/** Cada entrada es una pieza en pantalla. Las medidas van en variables de CSS
 *  porque el ancho de la caja se calcula desde el alto, y la proporción es la
 *  del archivo. */
const PIEZAS = [
  // --- La grande de la izquierda. Más pequeña que antes: dominaba la pantalla.
  { id: 'a1', archivo: 'resorte.webp', proporcion: 0.5158,
    alto: '42vh', top: '44%', left: '10%', opacidad: 0.9,
    giro: '-7deg', amplitud: '32deg', ruta: 'media',
    deriva: '34s', giroT: '27s', escala: '41s',
    dDeriva: '0s', dGiro: '0s', dEscala: '0s' },

  // --- La que cruza. Recorre el ancho de la pantalla y pasa por detrás del
  //     cristal, que es donde el vidrio se luce: entra nítida y sale difusa.
  //
  //     **Tiene que ser grande.** A 15vh —unos 95 px— se borraba del todo al
  //     pasar por detrás: el desenfoque del panel es de 50 px, y un objeto que
  //     mide el doble que el radio del desenfoque no sobrevive. Para que se
  //     lea a través del cristal, la pieza debe ser bastante mayor que ese
  //     radio; de ahí los 30vh.
  { id: 'b2', archivo: 'pieza-b.webp', proporcion: 1.4851,
    alto: '30vh', top: '30%', left: '2%', opacidad: 0.6,
    giro: '8deg', amplitud: '360deg', ruta: 'cruce',
    deriva: '58s', giroT: '46s', escala: '37s',
    dDeriva: '-9s', dGiro: '-3s', dEscala: '-12s' },

  // --- La otra que cruza, más abajo y en sentido contrario.
  { id: 'c2', archivo: 'pieza-c.webp', proporcion: 1.3333,
    alto: '26vh', top: '72%', left: '98%', opacidad: 0.55,
    giro: '-18deg', amplitud: '-360deg', ruta: 'cruce-inverso',
    deriva: '71s', giroT: '53s', escala: '44s',
    dDeriva: '-26s', dGiro: '-18s', dEscala: '-7s' },

  // --- Las de los bordes.
  { id: 'b1', archivo: 'pieza-b.webp', proporcion: 1.4851,
    alto: '19vh', top: '15%', left: '90%', opacidad: 0.82,
    giro: '14deg', amplitud: '34deg', ruta: 'media',
    deriva: '39s', giroT: '31s', escala: '47s',
    dDeriva: '-14s', dGiro: '-7s', dEscala: '-21s' },

  { id: 'c1', archivo: 'pieza-c.webp', proporcion: 1.3333,
    alto: '22vh', top: '76%', left: '84%', opacidad: 0.8,
    giro: '-12deg', amplitud: '-30deg', ruta: 'media',
    deriva: '45s', giroT: '36s', escala: '29s',
    dDeriva: '-31s', dGiro: '-22s', dEscala: '-9s' },

  // --- Las pequeñas. Estas sí dan la vuelta completa: a este tamaño y con esta
  //     opacidad, que la luz gire con ellas no se aprecia.
  { id: 'a2', archivo: 'resorte.webp', proporcion: 0.5158, espejo: true,
    alto: '11vh', top: '84%', left: '17%', opacidad: 0.55,
    giro: '0deg', amplitud: '360deg', ruta: 'corta',
    deriva: '26s', giroT: '33s', escala: '19s',
    dDeriva: '-6s', dGiro: '-11s', dEscala: '-4s' },

  { id: 'c3', archivo: 'pieza-c.webp', proporcion: 1.3333, espejo: true,
    alto: '9vh', top: '9%', left: '38%', opacidad: 0.5,
    giro: '0deg', amplitud: '-360deg', ruta: 'corta',
    deriva: '31s', giroT: '43s', escala: '23s',
    dDeriva: '-17s', dGiro: '-29s', dEscala: '-13s' },
];

export default function Lienzo({ animado = false }) {
  return (
    <div className={`lienzo${animado ? ' lienzo--animado' : ''}`} aria-hidden="true">
      {/* El swoosh de la marca, lo único que no es una pieza: es la firma.
          Sigue en SVG porque tiene que estirarse con la pantalla. */}
      <svg className="lienzo-svg" viewBox="0 0 1600 900"
        preserveAspectRatio="xMidYMid slice" xmlns="http://www.w3.org/2000/svg">
        <defs>
          <linearGradient id="swooshCromo" x1="0" y1="1" x2="1" y2="0">
            <stop offset="0%" stopColor="#dee7f1" stopOpacity="0" />
            <stop offset="16%" stopColor="#c9d5e3" stopOpacity="0.30" />
            <stop offset="40%" stopColor="#4a5563" stopOpacity="0.38" />
            <stop offset="62%" stopColor="#161d26" stopOpacity="0.45" />
            <stop offset="82%" stopColor="#9fb0c2" stopOpacity="0.30" />
            <stop offset="100%" stopColor="#2a333f" stopOpacity="0" />
          </linearGradient>
        </defs>
        <path d="M -240 640 C 260 920, 1180 900, 1800 460"
          stroke="url(#swooshCromo)" strokeWidth="54" fill="none"
          strokeLinecap="round" />
      </svg>

      {PIEZAS.map((p) => (
        <div
          key={p.id}
          className={`pieza pieza--${p.ruta}${p.espejo ? ' pieza--espejo' : ''}`}
          style={{
            '--proporcion': p.proporcion,
            '--alto': p.alto,
            '--giro': p.giro,
            '--amplitud': p.amplitud,
            '--periodo-deriva': p.deriva,
            '--periodo-giro': p.giroT,
            '--periodo-escala': p.escala,
            '--desfase-deriva': p.dDeriva,
            '--desfase-giro': p.dGiro,
            '--desfase-escala': p.dEscala,
            top: p.top,
            left: p.left,
            opacity: p.opacidad,
          }}
        >
          <img
            src={`/fondo/${p.archivo}`}
            alt=""
            draggable={false}
            /* Decorativo: que no compita con lo que la persona vino a hacer.
               `async` deja que el navegador la descodifique fuera del hilo
               principal y `low` la manda detrás de la fuente y del JavaScript
               en la cola de descarga. */
            decoding="async"
            fetchPriority="low"
          />
        </div>
      ))}
    </div>
  );
}

import React, { useMemo } from 'react';
import { useTranslation } from 'react-i18next';

/**
 * Nivel 1: qué sabe la planta, de un vistazo.
 *
 * El centro es el portal; alrededor, las categorías. De cada una se leen dos
 * cosas a la vez, y **es la combinación la que dice algo**:
 *
 *   - el **tamaño** del nodo es cuánto conocimiento hay escrito ahí,
 *   - el **grosor** de la línea es cuánto se lo preguntan.
 *
 * Una línea gruesa hacia un nodo diminuto es el peor caso que puede tener este
 * portal: mucha gente preguntando sobre algo de lo que no hay nada escrito. Esa
 * figura no aparece en ninguna otra pantalla, y es la que dice qué documentar
 * el lunes.
 *
 * **Por qué las seis categorías siempre se dibujan, aunque estén en cero.** Una
 * gráfica normal omitiría las vacías por no tener datos — y las vacías son
 * justo el dato. Un hueco que no se dibuja es un hueco que nadie ve.
 */

// El `viewBox` va ajustado al contenido, no holgado.
//
// La primera versión era de 760 × 380 para un dibujo que ocupaba los 280 del
// medio: como el SVG escala para caber en su ancho, todo ese aire vacío se
// llevaba la escala y las etiquetas acababan en unos diez píxeles reales,
// ilegibles. Un `viewBox` ceñido hace que el mismo espacio en pantalla lo
// ocupe el dibujo y no el margen, y el texto crece solo.
const ANCHO = 480;
const ALTO = 366;
const CENTRO = { x: 240, y: 176 };
const ORBITA = 120;

// Radios mínimo y máximo de un nodo de categoría. El mínimo no es cero a
// propósito: una categoría vacía tiene que seguir siendo visible y clicable,
// porque es precisamente la que hay que atender.
const RADIO_MIN = 17;
const RADIO_MAX = 36;

//: Radio del círculo central. Las líneas nacen en su borde, no en su centro.
//:
//: El relleno de las tarjetas de este portal es translúcido —`--bg-tertiary`
//: es blanco al 8,5 %—, así que un trazo dibujado por debajo **se ve a través**
//: y acaba cruzando el texto: la palabra «PIEZAS» del centro salía tachada por
//: la línea de la categoría más consultada. Bajar el trazo en el orden de
//: pintado no arregla nada cuando lo de encima deja pasar la luz; lo que hay
//: que hacer es que la línea no llegue hasta ahí.
const RADIO_CENTRO = 44;

const COLOR = {
  cubierto: 'var(--cgr-verde)',
  flojo: 'var(--status-espera-proveedor-text)',
  hueco: 'var(--peligro)',
  vacio: 'var(--text-muted)',
};

const MapaConocimiento = ({ panorama, seleccionada, onSeleccionar }) => {
  const { t } = useTranslation();
  const categorias = panorama?.categorias || [];

  const nodos = useMemo(() => {
    if (!categorias.length) return [];

    // Escala por raíz cuadrada y no lineal: el área de un círculo crece con el
    // cuadrado del radio, así que escalar el radio linealmente exagera las
    // diferencias hasta volver invisible todo lo que no sea el máximo.
    const techo = Math.max(...categorias.map((c) => c.conocimiento), 1);
    const techoConsultas = Math.max(...categorias.map((c) => c.consultas), 1);

    // Se arranca desde arriba (-90°) para que la primera categoría quede en la
    // punta y el reparto se lea como un reloj.
    const paso = (Math.PI * 2) / categorias.length;

    return categorias.map((c, i) => {
      const angulo = -Math.PI / 2 + paso * i;
      const radio = RADIO_MIN
        + (RADIO_MAX - RADIO_MIN) * Math.sqrt(c.conocimiento / techo);
      return {
        ...c,
        x: CENTRO.x + Math.cos(angulo) * ORBITA,
        y: CENTRO.y + Math.sin(angulo) * ORBITA,
        radio,
        // Extremos de la línea, recortados a los bordes de los dos círculos.
        x1: CENTRO.x + Math.cos(angulo) * (RADIO_CENTRO + 3),
        y1: CENTRO.y + Math.sin(angulo) * (RADIO_CENTRO + 3),
        x2: CENTRO.x + Math.cos(angulo) * (ORBITA - radio - 3),
        y2: CENTRO.y + Math.sin(angulo) * (ORBITA - radio - 3),
        // Grosor de la línea: de 1 (nadie pregunta) a 7 (la que más).
        grosor: 1 + 6 * (c.consultas / techoConsultas),
        // Hacia dónde cae la etiqueta, para que no se monte sobre el centro.
        fuera: Math.sin(angulo) >= 0 ? 1 : -1,
      };
    });
  }, [categorias]);

  if (!nodos.length) return null;

  const total = panorama.total || {};

  return (
    <svg
      className="mapa-conocimiento"
      viewBox={`0 0 ${ANCHO} ${ALTO}`}
      role="img"
      aria-label={t('conciencia.mapa_titulo')}
    >
      <title>{t('conciencia.mapa_titulo')}</title>
      <desc>
        {nodos.map((n) => `${t(`conciencia.cat.${n.categoria}`, n.categoria)}: `
          + `${n.conocimiento} ${t('conciencia.piezas')}, `
          + `${n.consultas} ${t('conciencia.consultas_palabra')}`).join('. ')}
      </desc>

      {/* Las líneas van primero para que los nodos las tapen en el borde. */}
      {nodos.map((n) => (
        <line
          key={`l-${n.categoria}`}
          className="mapa-radio"
          x1={n.x1} y1={n.y1} x2={n.x2} y2={n.y2}
          strokeWidth={n.grosor}
          data-estado={n.estado}
        />
      ))}

      {/* El centro: cuánto sabe la planta en total. */}
      <g className="mapa-centro">
        <circle cx={CENTRO.x} cy={CENTRO.y} r={RADIO_CENTRO} />
        {/* La cifra sube y la palabra baja respecto al centro geométrico: las
            dos líneas juntas tienen que quedar ópticamente centradas dentro
            del círculo, y con la cifra en la mitad exacta el conjunto se ve
            caído hacia abajo. */}
        <text x={CENTRO.x} y={CENTRO.y - 3} className="mapa-centro-cifra">
          {total.conocimiento ?? 0}
        </text>
        <text x={CENTRO.x} y={CENTRO.y + 15} className="mapa-centro-texto">
          {t('conciencia.piezas')}
        </text>
      </g>

      {nodos.map((n) => {
        const activa = seleccionada === n.categoria;

        // El texto se apila **alejándose** del nodo, no siempre hacia abajo.
        //
        // Con un desplazamiento fijo hacia abajo, los nodos de la mitad
        // superior quedaban con el nombre encima del círculo y la cifra
        // escrita justo sobre el trazo: ilegibles los dos. Aquí la línea más
        // cercana al nodo es siempre la cifra y el nombre queda por fuera, así
        // que arriba se lee «Accesos / nada escrito / ○» y abajo
        // «○ / Impresora / 3 · 0 cons.».
        const arriba = n.fuera < 0;
        const yCifra = n.y + (arriba ? -(n.radio + 11) : n.radio + 32);
        const yNombre = n.y + (arriba ? -(n.radio + 26) : n.radio + 19);

        return (
          <g
            key={n.categoria}
            className="mapa-nodo"
            data-estado={n.estado}
            data-activa={activa ? 'si' : undefined}
            onClick={() => onSeleccionar?.(activa ? null : n.categoria)}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                onSeleccionar?.(activa ? null : n.categoria);
              }
            }}
            aria-pressed={activa}
          >
            {/* Área de clic cómoda: el círculo visible de una categoría vacía
                mide 15 px y nadie acierta a eso con el dedo. */}
            <circle cx={n.x} cy={n.y} r={Math.max(n.radio, 28)} fill="transparent" />
            <circle
              className="mapa-nodo-circulo"
              cx={n.x} cy={n.y} r={n.radio}
              style={{ '--color': COLOR[n.estado] || COLOR.vacio }}
            />
            <text className="mapa-nodo-etiqueta" x={n.x} y={yNombre}>
              {t(`conciencia.cat.${n.categoria}`, n.categoria)}
            </text>
            <text className="mapa-nodo-cifra" x={n.x} y={yCifra}>
              {n.conocimiento === 0
                ? t('conciencia.sin_nada')
                : `${n.conocimiento} · ${n.consultas} ${t('conciencia.consultas_corto')}`}
            </text>
          </g>
        );
      })}
    </svg>
  );
};

export default MapaConocimiento;

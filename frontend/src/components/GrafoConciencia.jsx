import React, { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { User, Binary, Library, Cpu, Cloud, MessageSquareText, WifiOff } from 'lucide-react';

/**
 * El grafo: por dónde va la consulta, mientras va.
 *
 * Enseña el camino real —usuario, vectorización, base de conocimiento, modelo
 * local— y lo enciende conforme ocurre, con los milisegundos de cada salto.
 *
 * **Por qué no es un adorno.** Cuando alguien dice "el portal está lento", la
 * pregunta cara de contestar es *dónde*. Aquí se ve: si el nodo del
 * conocimiento se apaga enseguida y el del modelo se queda latiendo, es que
 * hay cola en la CPU. Si el del conocimiento se queda en gris con "0 pasajes",
 * es que de eso no hay nada escrito y no había respuesta que dar. Son dos
 * problemas opuestos que desde fuera se ven igual: "tarda".
 *
 * **Por qué SVG a mano y no D3 ni Three.js.** Son seis nodos en posiciones
 * fijas. D3 aporta cuando hay que calcular un diseño —simulaciones de fuerzas,
 * escalas, ejes— y aquí no hay nada que calcular: las coordenadas están escritas
 * más abajo. Three.js es una escena 3D con su contexto WebGL, que en esta
 * máquina compite por la misma CPU que el modelo. El SVG lo compone el
 * navegador solo, hereda los colores del tema sin tocar nada y se lee con un
 * lector de pantalla. Añadir una dependencia habría costado peso y, sobre
 * todo, un `package-lock.json` que aquí no se puede regenerar.
 *
 * El movimiento vive en `index.css` (busque "Grafo de conciencia"); este
 * archivo solo coloca los nodos y dice en qué estado está cada uno.
 */

// --- Dónde cae cada cosa -------------------------------------------------
//
// Coordenadas dentro del `viewBox`, no píxeles: el SVG escala solo y esto
// sigue valiendo en una pantalla de taller y en un teléfono.
const ANCHO = 760;
const ALTO = 250;
const RADIO = 27;
const RADIO_RAMA = 23;

const NODOS = [
  { id: 'usuario',      x: 58,  y: 148, icono: User,              radio: RADIO },
  { id: 'embedding',    x: 202, y: 148, icono: Binary,            radio: RADIO },
  { id: 'conocimiento', x: 366, y: 148, icono: Library,           radio: RADIO },
  { id: 'ia_local',     x: 534, y: 148, icono: Cpu,               radio: RADIO },
  // Gemini cuelga por arriba porque es una rama, no un paso del camino: solo
  // entra cuando el modelo local no alcanzó. Dibujarlo en la línea principal
  // daría a entender que toda consulta pasa por ahí, que es justo lo que este
  // portal se esfuerza en que no ocurra.
  { id: 'gemini',       x: 534, y: 52,  icono: Cloud,             radio: RADIO_RAMA },
  { id: 'respuesta',    x: 692, y: 148, icono: MessageSquareText, radio: RADIO },
];

const POR_ID = Object.fromEntries(NODOS.map((n) => [n.id, n]));

/** Las líneas posibles. Solo se pintan las que la traza haya recorrido. */
const ARISTAS = [
  ['usuario', 'embedding'],
  ['embedding', 'conocimiento'],
  ['conocimiento', 'ia_local'],
  ['ia_local', 'respuesta'],
  ['ia_local', 'gemini'],
  ['gemini', 'respuesta'],
];

/**
 * Los extremos de una línea, recortados para que no entren bajo los círculos.
 *
 * Sin el recorte la línea nace en el centro del nodo y se ve por debajo del
 * relleno cuando éste es translúcido —que lo es, porque el tema usa
 * transparencias—. Además la partícula aparecería ya dentro del círculo.
 */
function extremos(desdeId, hastaId) {
  const a = POR_ID[desdeId];
  const b = POR_ID[hastaId];
  if (!a || !b) return null;

  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const distancia = Math.hypot(dx, dy) || 1;
  const ux = dx / distancia;
  const uy = dy / distancia;

  // Cuatro píxeles de aire antes del destino, para que se note que la línea
  // llega al nodo en vez de morir pegada a él.
  const x1 = a.x + ux * a.radio;
  const y1 = a.y + uy * a.radio;
  const x2 = b.x - ux * (b.radio + 4);
  const y2 = b.y - uy * (b.radio + 4);

  return { x1, y1, x2, y2, largo: Math.hypot(x2 - x1, y2 - y1) };
}

/** El renglón chico bajo cada nodo: lo que ese nodo hizo, en números. */
function detalleDe(id, paso, t) {
  if (!paso) return null;
  const d = paso.detalle || {};

  if (id === 'conocimiento') {
    if (paso.estado === 'omitido' && !d.pasajes) return t('conciencia.nada_escrito');
    const similitud = d.similitud != null ? ` · ${Math.round(d.similitud * 100)}%` : '';
    return `${d.pasajes ?? 0} ${t('conciencia.pasajes')}${similitud}`;
  }

  if (id === 'embedding') {
    if (paso.estado === 'error') return t('conciencia.sin_embeddings');
    return d.dimensiones ? `${d.dimensiones}d · ${paso.ms} ms` : `${paso.ms} ms`;
  }

  if (id === 'ia_local') {
    // Mientras trabaja, lo útil no es "hay 2 en cola" sino cuánto va a tardar:
    // un número de personas no le dice nada a quien espera, un "~27 s" sí, y
    // es la diferencia entre esperar y pensar que se colgó.
    if (paso.estado === 'activo' && d.espera_estimada_s) {
      return `${t('conciencia.en_cola')} · ~${Math.round(d.espera_estimada_s)} s`;
    }
    if (paso.estado === 'activo' && d.en_cola > 0) {
      return `${t('conciencia.en_cola')}: ${d.en_cola}`;
    }
    if (paso.estado === 'omitido') {
      return t(`conciencia.motivo.${d.motivo}`, { defaultValue: t('conciencia.no_hizo_falta') });
    }
    return `${paso.ms} ms`;
  }

  if (id === 'usuario') return d.caracteres ? `${d.caracteres} car.` : null;
  if (paso.estado === 'listo') return `${paso.ms} ms`;
  return null;
}

const GrafoConciencia = ({ nodos = {}, aristas = [], conectado = false, altura = 250 }) => {
  const { t } = useTranslation();

  // Se recalcula solo cuando cambian las líneas recorridas, no en cada render:
  // el estado de los nodos cambia varias veces por consulta y la geometría es
  // siempre la misma.
  const trazadas = useMemo(
    () => aristas.map((a) => ({ ...a, geo: extremos(a.desde, a.hasta) })).filter((a) => a.geo),
    [aristas]
  );
  const recorrida = (desde, hasta) =>
    trazadas.find((a) => a.desde === desde && a.hasta === hasta);

  const paso = nodos.respuesta || null;
  const total = paso?.ms;

  return (
    <div style={{ position: 'relative' }}>
      <svg
        className="grafo-conciencia"
        viewBox={`0 0 ${ANCHO} ${ALTO}`}
        style={{ maxHeight: altura }}
        role="img"
        aria-label={t('conciencia.titulo')}
      >
        {/* Lo que lee un lector de pantalla, que no puede ver encenderse nada.
            Se actualiza con el estado, así que dice lo mismo que el dibujo. */}
        <title>{t('conciencia.titulo')}</title>
        <desc>
          {NODOS.filter((n) => nodos[n.id])
            .map((n) => `${t(`conciencia.nodo.${n.id}`)}: ${t(`conciencia.estado.${nodos[n.id].estado}`)}`)
            .join('. ')}
        </desc>

        {/* Primero todas las líneas apagadas, para que el camino completo se
            intuya desde el principio y el grafo no aparezca de la nada. */}
        {ARISTAS.map(([desde, hasta]) => {
          const geo = extremos(desde, hasta);
          if (!geo) return null;
          return (
            <line
              key={`base-${desde}-${hasta}`}
              className="grafo-arista"
              x1={geo.x1} y1={geo.y1} x2={geo.x2} y2={geo.y2}
              strokeDasharray={hasta === 'gemini' || desde === 'gemini' ? '4 4' : undefined}
            />
          );
        })}

        {/* Encima, las que esta consulta sí recorrió. */}
        {trazadas.map(({ desde, hasta, geo }) => (
          <g key={`viva-${desde}-${hasta}`}>
            <line
              className="grafo-arista grafo-arista-viva"
              x1={geo.x1} y1={geo.y1} x2={geo.x2} y2={geo.y2}
              style={{ '--largo': geo.largo }}
            />
            <circle
              className="grafo-particula"
              cx={geo.x1} cy={geo.y1} r="3.5"
              style={{ '--dx': `${geo.x2 - geo.x1}px`, '--dy': `${geo.y2 - geo.y1}px` }}
            />
          </g>
        ))}

        {NODOS.map(({ id, x, y, icono: Icono, radio }) => {
          const estadoPaso = nodos[id];
          const estado = estadoPaso?.estado || 'apagado';
          const detalle = detalleDe(id, estadoPaso, t);
          const lado = radio * 0.82;

          return (
            <g key={id} className="grafo-nodo" data-estado={estado}>
              {/* Qué hace este nodo, al pasar el ratón por encima.
                  El grafo se entiende de un vistazo cuando ya se sabe qué es
                  cada cosa; la primera vez, no. Un `<title>` dentro del grupo
                  lo cuenta sin ocupar sitio en pantalla, y además es lo que
                  lee un lector de pantalla al llegar al nodo. */}
              <title>
                {`${t(`conciencia.nodo.${id}`)} — ${t(`conciencia.ayuda_nodo.${id}`)}`}
              </title>
              {/* El anillo va debajo del círculo para que al crecer salga de
                  detrás y no tape el icono. */}
              <circle className="grafo-nodo-pulso" cx={x} cy={y} r={radio} />
              <circle className="grafo-nodo-circulo" cx={x} cy={y} r={radio} />

              {/* `foreignObject` para poder usar los iconos de lucide, que son
                  los mismos del resto del portal. Dibujarlos a mano en SVG
                  daría un juego de iconos paralelo que se queda desfasado. */}
              <foreignObject x={x - lado / 2} y={y - lado / 2} width={lado} height={lado}>
                <div
                  xmlns="http://www.w3.org/1999/xhtml"
                  className="grafo-nodo-icono"
                  style={{ width: '100%', height: '100%', display: 'flex',
                           alignItems: 'center', justifyContent: 'center' }}
                >
                  <Icono size={Math.round(lado * 0.8)} aria-hidden="true" />
                </div>
              </foreignObject>

              <text className="grafo-nodo-etiqueta" x={x} y={y + radio + 18}>
                {t(`conciencia.nodo.${id}`)}
              </text>
              {detalle && (
                <text className="grafo-nodo-detalle" x={x} y={y + radio + 32}>
                  {detalle}
                </text>
              )}
            </g>
          );
        })}
      </svg>

      {/* El estado del canal, abajo a la derecha y sin estorbar.
          Importa que se vea: sin WebSocket el grafo se queda en gris, y sin
          este aviso eso es indistinguible de "el portal no está haciendo
          nada". La respuesta llega igual — va por su POST de siempre. */}
      <div style={{
        position: 'absolute', bottom: 0, right: 4,
        display: 'flex', alignItems: 'center', gap: '6px',
        fontSize: '0.72rem', color: 'var(--text-muted)',
        fontFamily: 'var(--font-mono)',
      }}>
        {conectado ? (
          total != null ? `${total} ms` : null
        ) : (
          <>
            <WifiOff size={12} aria-hidden="true" />
            {t('conciencia.sin_conexion')}
          </>
        )}
      </div>
    </div>
  );
};

export default GrafoConciencia;

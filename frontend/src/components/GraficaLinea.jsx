import React, { useMemo, useState, useId } from 'react';

/**
 * Una serie en el tiempo, dibujada a mano en SVG.
 *
 * Sin librería de gráficas a propósito: el portal se compila sin npm en el
 * servidor (ver la memoria del proyecto) y una dependencia nueva rompe
 * `npm ci`. Para lo que hace falta aquí —una línea, su área, el umbral y un
 * cursor que dice el valor— alcanzan cien líneas.
 *
 * Los huecos (tramos sin lectura) cortan la línea en vez de unir los puntos
 * de los lados: un sensor que estuvo caído dos horas no "midió" la recta
 * entre antes y después.
 */
const ANCHO = 600;
const ALTO = 170;
// Los textos van en unidades del viewBox: la gráfica se pinta a ~320 px de
// ancho, así que 17 unidades son ~9 px en pantalla. Con 10 no se leían.
const MARGEN = { izq: 50, der: 12, arr: 14, aba: 28 };

export default function GraficaLinea({
  puntos, campo, umbral, unidad = '', color = 'var(--accent-primary)', etiqueta, idioma = 'es',
  pasoSegundos,
}) {
  const id = useId().replace(/:/g, '');
  const [cursor, setCursor] = useState(null);

  const datos = useMemo(() => (puntos || [])
    .map((p) => ({ t: new Date(p.t).getTime(), v: p[campo] }))
    .filter((p) => p.v != null && Number.isFinite(p.v)), [puntos, campo]);

  if (datos.length === 0) {
    return <div className="grafica-vacia">{etiqueta} · —</div>;
  }

  const t0 = datos[0].t;
  const t1 = datos[datos.length - 1].t;
  const valores = datos.map((p) => p.v);
  let vMin = Math.min(...valores);
  let vMax = Math.max(...valores);
  if (umbral != null) { vMax = Math.max(vMax, umbral); vMin = Math.min(vMin, umbral); }
  const holgura = (vMax - vMin) * 0.12 || Math.abs(vMax) * 0.1 || 1;
  vMin -= holgura;
  vMax += holgura;

  const anchoUtil = ANCHO - MARGEN.izq - MARGEN.der;
  const altoUtil = ALTO - MARGEN.arr - MARGEN.aba;
  const x = (t) => MARGEN.izq + (t1 === t0 ? anchoUtil / 2 : ((t - t0) / (t1 - t0)) * anchoUtil);
  const y = (v) => MARGEN.arr + (1 - (v - vMin) / (vMax - vMin)) * altoUtil;

  // Tramos continuos: se corta donde falta más de dos pasos seguidos.
  const corte = (pasoSegundos || 60) * 1000 * 2.5;
  const tramos = [];
  datos.forEach((p, i) => {
    if (i === 0 || p.t - datos[i - 1].t > corte) tramos.push([]);
    tramos[tramos.length - 1].push(p);
  });
  const linea = tramos.map((tr) => tr.map((p, i) => `${i ? 'L' : 'M'}${x(p.t).toFixed(1)},${y(p.v).toFixed(1)}`).join(' ')).join(' ');
  const area = tramos.map((tr) => `M${x(tr[0].t).toFixed(1)},${(ALTO - MARGEN.aba).toFixed(1)} `
    + tr.map((p) => `L${x(p.t).toFixed(1)},${y(p.v).toFixed(1)}`).join(' ')
    + ` L${x(tr[tr.length - 1].t).toFixed(1)},${(ALTO - MARGEN.aba).toFixed(1)} Z`).join(' ');

  const hora = (t) => new Date(t).toLocaleString(idioma, (t1 - t0) > 36 * 3600 * 1000
    ? { day: '2-digit', month: 'short', hour: '2-digit' }
    : { hour: '2-digit', minute: '2-digit' });
  const fmt = (v) => `${Number(v.toFixed(1))}${unidad}`;

  const mover = (e) => {
    const caja = e.currentTarget.getBoundingClientRect();
    const px = ((e.clientX - caja.left) / caja.width) * ANCHO;
    let mejor = datos[0];
    for (const p of datos) if (Math.abs(x(p.t) - px) < Math.abs(x(mejor.t) - px)) mejor = p;
    setCursor(mejor);
  };

  const sobreUmbral = umbral != null && datos[datos.length - 1].v > umbral;

  return (
    <figure className="grafica">
      <figcaption className="grafica-titulo">
        <span>{etiqueta}</span>
        <strong className={sobreUmbral ? 'grafica-valor grafica-valor--alto' : 'grafica-valor'}>
          {fmt(cursor ? cursor.v : datos[datos.length - 1].v)}
        </strong>
        {cursor && <span className="grafica-hora">{hora(cursor.t)}</span>}
      </figcaption>
      <svg
        viewBox={`0 0 ${ANCHO} ${ALTO}`}
        className="grafica-svg"
        role="img"
        aria-label={`${etiqueta}: ${fmt(Math.min(...valores))} – ${fmt(Math.max(...valores))}`}
        onMouseMove={mover}
        onMouseLeave={() => setCursor(null)}
      >
        <defs>
          <linearGradient id={`relleno-${id}`} x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity="0.32" />
            <stop offset="100%" stopColor={color} stopOpacity="0" />
          </linearGradient>
        </defs>
        {[0, 0.5, 1].map((f) => {
          const v = vMin + (vMax - vMin) * (1 - f);
          const yy = MARGEN.arr + f * altoUtil;
          return (
            <g key={f}>
              <line x1={MARGEN.izq} x2={ANCHO - MARGEN.der} y1={yy} y2={yy} className="grafica-reja" />
              <text x={MARGEN.izq - 8} y={yy + 6} className="grafica-eje" textAnchor="end">{Number(v.toFixed(0))}</text>
            </g>
          );
        })}
        {umbral != null && (
          <g>
            <line x1={MARGEN.izq} x2={ANCHO - MARGEN.der} y1={y(umbral)} y2={y(umbral)} className="grafica-umbral" />
            <text x={ANCHO - MARGEN.der} y={y(umbral) - 4} className="grafica-umbral-texto" textAnchor="end">
              {fmt(umbral)}
            </text>
          </g>
        )}
        <path d={area} fill={`url(#relleno-${id})`} />
        <path d={linea} fill="none" stroke={color} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
        {datos.length === 1 && <circle cx={x(datos[0].t)} cy={y(datos[0].v)} r="3.5" fill={color} />}
        <text x={MARGEN.izq} y={ALTO - 6} className="grafica-eje">{hora(t0)}</text>
        <text x={ANCHO - MARGEN.der} y={ALTO - 6} className="grafica-eje" textAnchor="end">{hora(t1)}</text>
        {cursor && (
          <g>
            <line x1={x(cursor.t)} x2={x(cursor.t)} y1={MARGEN.arr} y2={ALTO - MARGEN.aba} className="grafica-cursor" />
            <circle cx={x(cursor.t)} cy={y(cursor.v)} r="4" fill={color} stroke="var(--bg-primary)" strokeWidth="2" />
          </g>
        )}
      </svg>
    </figure>
  );
}

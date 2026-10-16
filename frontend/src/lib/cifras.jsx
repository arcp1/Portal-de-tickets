import React from 'react';

/**
 * Las cifras de las métricas, escritas como se leen en cada idioma.
 *
 * **Por qué.** El tablero enseñaba `23.4%`, `186 min` y `0.7`: el punto
 * decimal de inglés en una pantalla en castellano, tres horas expresadas en
 * minutos y un umbral que nadie sabe si es mucho o poco. Aquí cada clase de
 * cifra tiene su forma —`23,4 %`, `3 h 6 min`, `1,02 s`, `70 %`— y la unidad
 * va aparte, en pequeño, para que lo que se lea primero sea el número.
 */
const Unidad = ({ children }) => <span className="cifra-unidad">{children}</span>;

export function entero(v, idioma) {
  return new Intl.NumberFormat(idioma, { maximumFractionDigits: 0 }).format(v);
}

/** 23.4 → «23,4 %» (o «23.4%» en inglés: el espacio también es del idioma). */
export function porcentaje(v, idioma) {
  const partes = new Intl.NumberFormat(idioma, { style: 'percent', maximumFractionDigits: 1 })
    .formatToParts(v / 100);
  return (
    <>
      {partes.map((p, i) => (p.type === 'percentSign'
        ? <Unidad key={i}>%</Unidad>
        : p.type === 'literal' ? <Unidad key={i}>{' '}</Unidad> : <React.Fragment key={i}>{p.value}</React.Fragment>))}
    </>
  );
}

/** 0.7 → «70 %»: los umbrales son proporciones y se leen como porcentaje. */
export function proporcion(v, idioma) {
  return porcentaje(v * 100, idioma);
}

/** Minutos → «45 min», «3 h 6 min», «2 d 4 h». */
export function duracion(minutos, idioma) {
  const m = Math.round(minutos);
  if (m < 60) return <>{entero(m, idioma)}<Unidad> min</Unidad></>;
  if (m < 1440) {
    const h = Math.floor(m / 60);
    const resto = m % 60;
    return <>{h}<Unidad> h</Unidad>{resto ? <> {resto}<Unidad> min</Unidad></> : null}</>;
  }
  const d = Math.floor(m / 1440);
  const h = Math.round((m % 1440) / 60);
  return <>{d}<Unidad> d</Unidad>{h ? <> {h}<Unidad> h</Unidad></> : null}</>;
}

/** Milisegundos → «850 ms» o «1,02 s». */
export function milisegundos(ms, idioma) {
  if (ms < 1000) return <>{entero(ms, idioma)}<Unidad> ms</Unidad></>;
  const s = new Intl.NumberFormat(idioma, { maximumFractionDigits: 2, minimumFractionDigits: 2 }).format(ms / 1000);
  return <>{s}<Unidad> s</Unidad></>;
}

/** 4.25 → «4,25 / 5». */
export function sobreCinco(v, idioma) {
  const n = new Intl.NumberFormat(idioma, { maximumFractionDigits: 2 }).format(v);
  return <>{n}<Unidad> / 5</Unidad></>;
}

/** «7 de 9»: lo que está bien de lo que hay. */
export function deTotal(v, total, idioma) {
  return <>{entero(v, idioma)}<Unidad> / {entero(total, idioma)}</Unidad></>;
}

/**
 * **El dinero, en el formato de cada idioma y con su moneda a la vista.**
 *
 * El idioma del portal es `es`, `en` o `fr`, pero el formato de una cantidad
 * es de un país: `es` a secas escribe «105.000,00 MXN» (el de España). La
 * planta está en México, así que el castellano usa `es-MX` —«$105,000.00»—.
 * El símbolo va estrecho (`$`) para pesos y dólares por igual, y por eso el
 * código de la moneda va siempre al lado, en pequeño: «$116.00 USD» no se
 * puede confundir con pesos.
 */
const LOCALES = { es: 'es-MX', en: 'en-US', fr: 'fr-FR' };

export function localeDe(idioma) {
  return LOCALES[(idioma || 'es').slice(0, 2)] || 'es-MX';
}

export function dineroTexto(v, idioma, { moneda = 'MXN', decimales = 2 } = {}) {
  return new Intl.NumberFormat(localeDe(idioma), {
    style: 'currency', currency: moneda, currencyDisplay: 'narrowSymbol',
    minimumFractionDigits: decimales, maximumFractionDigits: decimales,
  }).format(Number(v) || 0);
}

export function dinero(v, idioma, { moneda = 'MXN', decimales = 2, codigo = true } = {}) {
  return (
    <>
      {dineroTexto(v, idioma, { moneda, decimales })}
      {codigo && <Unidad> {moneda}</Unidad>}
    </>
  );
}

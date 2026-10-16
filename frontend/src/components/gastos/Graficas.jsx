import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { dineroTexto, localeDe } from '../../lib/cifras';
import { nombreMes } from './comun';

/**
 * Las dos gráficas del resumen de Gastos, sin biblioteca.
 *
 * **En HTML y no en un SVG escalado.** Un SVG con `viewBox` encoge sus letras
 * con el ancho: a 360 px los meses quedaban en cinco píxeles. Con columnas de
 * CSS cada rótulo conserva su tamaño y lo que se estrecha son las barras. El
 * único SVG es el de las líneas del acumulado, que no lleva texto y dibuja
 * con trazo fijo (`non-scaling-stroke`).
 *
 * Una sola escala en cada una —nunca dos ejes—, la cuadrícula apagada, y al
 * pasar el ratón (o tocar) el detalle de ese mes.
 */

function compacto(v, idioma) {
  return new Intl.NumberFormat(localeDe(idioma), {
    notation: 'compact', maximumFractionDigits: 1, style: 'currency', currency: 'MXN',
    currencyDisplay: 'narrowSymbol',
  }).format(v);
}

/** Un techo redondo para la escala: 1, 2 o 5 por una potencia de diez. */
function techo(v) {
  if (!(v > 0)) return 1;
  const p = 10 ** Math.floor(Math.log10(v));
  return [1, 2, 2.5, 5, 10].map((m) => m * p).find((x) => x >= v);
}

function Rejilla({ maximo, idioma }) {
  return (
    <div className="grafica-rejilla" aria-hidden="true">
      {[1, 0.5, 0].map((f) => (
        <div key={f} className="grafica-rejilla-linea" style={{ bottom: `${f * 100}%` }}>
          <span>{f === 0 ? '0' : compacto(maximo * f, idioma)}</span>
        </div>
      ))}
    </div>
  );
}

/** Gasto de cada mes, apilado por categoría. */
export function GraficaMeses({ meses, colorDe, nombreDe, mesEnCurso, onMes }) {
  const { t, i18n } = useTranslation();
  const idioma = i18n.language;
  const [activo, setActivo] = useState(null);
  const maximo = techo(Math.max(...meses.map((m) => m.total), 0));
  const presentes = [];
  meses.forEach((m) => m.por_categoria.forEach((c) => {
    if (!presentes.includes(c.categoria_id)) presentes.push(c.categoria_id);
  }));
  // La leyenda en el orden de los colores, no en el de aparición.
  presentes.sort((a, b) => a - b);
  const mes = activo ? meses[activo - 1] : null;

  return (
    <div className="grafica" onMouseLeave={() => setActivo(null)}>
      <div className="grafica-lienzo">
        <Rejilla maximo={maximo} idioma={idioma} />
        <div className="grafica-columnas" role="group" aria-label={t('gastos.grafica_meses')}>
          {meses.map((m) => (
            <button
              type="button"
              key={m.mes}
              className={`grafica-columna${activo === m.mes ? ' grafica-columna--activa' : ''}`}
              onMouseEnter={() => setActivo(m.mes)}
              onFocus={() => setActivo(m.mes)}
              onBlur={() => setActivo(null)}
              onClick={() => onMes?.(m.mes)}
              aria-label={`${nombreMes(m.mes, idioma)}: ${dineroTexto(m.total, idioma)}`}
            >
              <span className="grafica-pila" style={{ height: `${(100 * m.total) / maximo}%` }}>
                {/* De abajo arriba en el mismo orden en todas las barras: la
                    misma categoría queda a la misma altura relativa. */}
                {[...m.por_categoria].sort((a, b) => b.categoria_id - a.categoria_id).map((c) => (
                  <span key={c.categoria_id} className="grafica-segmento"
                    style={{ flexGrow: c.total, background: colorDe(c.categoria_id) }} />
                ))}
              </span>
            </button>
          ))}
        </div>
        {mes && (
          <div className="grafica-globo" role="status"
            style={{ left: `${((activo - 0.5) / 12) * 100}%` }}
            data-lado={activo > 6 ? 'izquierda' : 'derecha'}>
            <strong>{nombreMes(mes.mes, idioma)}</strong>
            <span className="grafica-globo-total">{dineroTexto(mes.total, idioma)}</span>
            <span className="grafica-globo-nota">{t('gastos.n_gastos', { count: mes.n })}</span>
            {mes.por_categoria.slice(0, 4).map((c) => (
              <span key={c.categoria_id} className="grafica-globo-fila">
                <i style={{ background: colorDe(c.categoria_id) }} />
                <span>{nombreDe(c.categoria_id)}</span>
                <b>{dineroTexto(c.total, idioma, { decimales: 0 })}</b>
              </span>
            ))}
          </div>
        )}
      </div>
      <div className="grafica-meses" aria-hidden="true">
        {meses.map((m) => (
          <span key={m.mes} className={m.mes === mesEnCurso ? 'grafica-mes--actual' : ''}>
            {nombreMes(m.mes, idioma, 'short')}
          </span>
        ))}
      </div>
      {presentes.length > 0 && (
        <ul className="grafica-leyenda">
          {presentes.map((id) => (
            <li key={id}><i style={{ background: colorDe(id) }} />{nombreDe(id)}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

/**
 * Lo gastado en el año, acumulado mes a mes, contra el ritmo del presupuesto
 * (presupuesto anual repartido en partes iguales). Es la comparación que no
 * engaña: un mes caro no es un problema si el acumulado sigue por debajo.
 */
export function GraficaAcumulado({ meses, presupuesto, ultimoMes }) {
  const { t, i18n } = useTranslation();
  const idioma = i18n.language;
  const [activo, setActivo] = useState(null);
  const acumulado = [];
  meses.reduce((suma, m) => { acumulado.push(suma + m.total); return suma + m.total; }, 0);
  const visibles = acumulado.slice(0, ultimoMes);
  const maximo = techo(Math.max(presupuesto, ...visibles, 0) * 1.04);
  const y = (v) => 100 - (100 * v) / maximo;
  const x = (i) => (100 * i) / 12;
  const real = [`M ${x(0)} ${y(0)}`, ...visibles.map((v, i) => `L ${x(i + 1)} ${y(v)}`)].join(' ');
  const plan = `M ${x(0)} ${y(0)} L ${x(12)} ${y(presupuesto)}`;
  const final = visibles.length ? visibles[visibles.length - 1] : 0;
  const punto = activo && activo <= visibles.length ? activo : null;

  return (
    <div className="grafica grafica--acumulado" onMouseLeave={() => setActivo(null)}>
      <div className="grafica-lienzo">
        <Rejilla maximo={maximo} idioma={idioma} />
        <svg className="grafica-lineas" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
          <path d={plan} className="grafica-linea grafica-linea--plan" vectorEffect="non-scaling-stroke" />
          <path d={real} className="grafica-linea grafica-linea--real" vectorEffect="non-scaling-stroke" />
        </svg>
        {/* Rótulos directos al final de cada línea: la leyenda está, pero con
            dos series se lee antes así. */}
        <span className="grafica-rotulo grafica-rotulo--plan" style={{ top: `${y(presupuesto)}%` }}>
          {t('gastos.presupuesto')}
        </span>
        {visibles.length > 0 && (
          <span className="grafica-rotulo grafica-rotulo--real"
            style={{ top: `${y(final)}%`, left: `${x(visibles.length)}%` }}>
            {t('gastos.gastado')}
          </span>
        )}
        {punto && (
          <span className="grafica-punto" aria-hidden="true"
            style={{ left: `${x(punto)}%`, top: `${y(visibles[punto - 1])}%` }} />
        )}
        <div className="grafica-columnas grafica-columnas--sensores">
          {meses.map((m) => (
            <button type="button" key={m.mes} className="grafica-sensor"
              onMouseEnter={() => setActivo(m.mes)} onFocus={() => setActivo(m.mes)}
              onBlur={() => setActivo(null)} onClick={() => setActivo(m.mes)}
              aria-label={m.mes <= visibles.length
                ? t('gastos.acumulado_a', { mes: nombreMes(m.mes, idioma),
                  gastado: dineroTexto(visibles[m.mes - 1], idioma),
                  plan: dineroTexto((presupuesto * m.mes) / 12, idioma) })
                : nombreMes(m.mes, idioma)} />
          ))}
        </div>
        {activo && (
          <div className="grafica-globo" role="status" style={{ left: `${((activo - 0.5) / 12) * 100}%` }}
            data-lado={activo > 6 ? 'izquierda' : 'derecha'}>
            <strong>{t('gastos.al_cierre_de', { mes: nombreMes(activo, idioma) })}</strong>
            {activo <= visibles.length ? (
              <span className="grafica-globo-fila">
                <i className="grafica-muestra--real" />
                <span>{t('gastos.gastado')}</span>
                <b>{dineroTexto(visibles[activo - 1], idioma, { decimales: 0 })}</b>
              </span>
            ) : (
              <span className="grafica-globo-nota">{t('gastos.sin_datos_aun')}</span>
            )}
            <span className="grafica-globo-fila">
              <i className="grafica-muestra--plan" />
              <span>{t('gastos.ritmo_presupuesto')}</span>
              <b>{dineroTexto((presupuesto * activo) / 12, idioma, { decimales: 0 })}</b>
            </span>
          </div>
        )}
      </div>
      <div className="grafica-meses" aria-hidden="true">
        {meses.map((m) => <span key={m.mes}>{nombreMes(m.mes, idioma, 'short')}</span>)}
      </div>
      <ul className="grafica-leyenda">
        <li><i className="grafica-muestra--real" />{t('gastos.gastado_acumulado')}</li>
        <li><i className="grafica-muestra--plan" />{t('gastos.ritmo_presupuesto')}</li>
      </ul>
    </div>
  );
}

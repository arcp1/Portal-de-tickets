import React, { useCallback, useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import {
  Plus, Wallet, LayoutDashboard, ListOrdered, PiggyBank, TrendingUp, Trophy, Building2, Factory,
  FolderCheck, AlertTriangle, CheckCircle2, ArrowUpRight,
} from 'lucide-react';
import api from '../api/client';
import forma from '../lib/forma';
import lista from '../lib/lista';
import { mensajeDeError } from '../lib/avisos';
import { usePlantas } from '../lib/plantas';
import { dinero, dineroTexto, entero, localeDe } from '../lib/cifras';
import GlassCard from '../components/GlassCard';
import NumeroQueSube from '../components/NumeroQueSube';
import Selector from '../components/Selector';
import Aviso from '../components/Aviso';
import EstadoVacio from '../components/EstadoVacio';
import { EsqueletoLista } from '../components/Cargando';
import { GraficaAcumulado, GraficaMeses } from '../components/gastos/Graficas';
import { coloresDeCategorias, nombreMes } from '../components/gastos/comun';
import Registro from '../components/gastos/Registro';
import Presupuesto from '../components/gastos/Presupuesto';
import FormularioGasto from '../components/gastos/FormularioGasto';
import DetalleGasto from '../components/gastos/DetalleGasto';

/**
 * Gastos y presupuesto de TI (módulo Activos).
 *
 * Lo que antes era «Gastos TI», una aplicación aparte en una PC de escritorio
 * sin usuarios, dentro del portal: con sesión, con la bitácora, y conectada a
 * la planta, el activo, el ticket y el técnico responsable de cada gasto.
 *
 * **Tres vistas, una dirección.** Resumen, Registro y Presupuesto van en la
 * URL (`?vista=registro&anio=2026&planta=3`), igual que el año y la planta:
 * se puede volver atrás y mandar el enlace a un compañero.
 *
 * **El presupuesto se compara contra lo que tocaba a la fecha.** La
 * aplicación original lo dividía entre doce mes a mes, y una licencia anual
 * pagada en enero salía como sobregiro de enero. Aquí lo que se compara es el
 * acumulado contra el presupuesto prorrateado por días transcurridos.
 */

const VISTAS = ['resumen', 'registro', 'presupuesto'];

const Tarjeta = ({ etiqueta, valor, formatear, ambito, ayuda, sinAnimar = false, tono }) => (
  <div className={`casilla-metrica${tono ? ` casilla-metrica--${tono}` : ''}`}>
    <div className="casilla-metrica-cabeza">
      <div className="casilla-metrica-etiqueta">{etiqueta}</div>
      {ambito && <span className="casilla-metrica-ambito">{ambito}</span>}
    </div>
    <div className="casilla-metrica-valor">
      {valor === null || valor === undefined ? '—'
        : sinAnimar ? valor : <NumeroQueSube valor={valor} formatear={formatear} />}
    </div>
    {ayuda && <div className="casilla-metrica-ayuda">{ayuda}</div>}
  </div>
);

const Seccion = ({ icono, titulo, children, accion }) => (
  <GlassCard relleno="24px" style={{ marginBottom: '20px' }}>
    <div className="titulo-bloque-fila">
      <h2 className="titulo-bloque">{icono}{titulo}</h2>
      {accion}
    </div>
    {children}
  </GlassCard>
);

function pct(v, idioma, decimales = 0) {
  return new Intl.NumberFormat(localeDe(idioma), { style: 'percent', maximumFractionDigits: decimales })
    .format(v);
}

export default function Gastos() {
  const { t } = useTranslation();
  const [params, setParams] = useSearchParams();
  const [plantas] = usePlantas();
  const hoy = new Date().getFullYear();
  const vista = VISTAS.includes(params.get('vista')) ? params.get('vista') : 'resumen';
  const anio = Number(params.get('anio')) || hoy;
  // '' todas, '0' las que no tienen planta, o el id.
  const planta = params.get('planta') ?? '';
  const [catalogos, setCatalogos] = useState(null);
  const [aviso, setAviso] = useState('');
  const [editando, setEditando] = useState(null);
  const [abierto, setAbierto] = useState(null);
  // Sube cada vez que algo cambia: las vistas vuelven a pedir sus datos.
  const [version, setVersion] = useState(0);

  const cambiar = useCallback((cambios) => {
    setParams((actual) => {
      const nuevos = new URLSearchParams(actual);
      Object.entries(cambios).forEach(([k, v]) => {
        if (v === null || v === undefined || v === '') nuevos.delete(k);
        else nuevos.set(k, String(v));
      });
      return nuevos;
    }, { replace: true });
  }, [setParams]);

  const cargarCatalogos = useCallback(() => {
    api.get('/gastos/catalogos')
      .then((res) => {
        if (forma(res.data, ['categorias', 'proveedores', 'responsables'], 'los catálogos de gastos')) {
          setCatalogos(res.data);
          setAviso('');
        } else {
          setAviso(t('gastos.error_cargar'));
        }
      })
      .catch((err) => setAviso(mensajeDeError(err, t('gastos.error_cargar'))));
  }, [t]);

  useEffect(() => { cargarCatalogos(); }, [cargarCatalogos]);

  // Un enlace de la bitácora trae `?gasto=12`: se abre su detalle.
  useEffect(() => {
    const id = Number(params.get('gasto'));
    if (id) {
      setAbierto(id);
      cambiar({ gasto: null });
    }
  }, [params, cambiar]);

  const refrescar = () => {
    setVersion((v) => v + 1);
    cargarCatalogos();
  };

  const anios = [];
  for (let a = hoy + 1; a >= hoy - 5; a -= 1) anios.push(a);
  if (!anios.includes(anio)) anios.push(anio);
  const plantaElegida = plantas.find((p) => String(p.id) === planta);

  const pestanas = [
    { id: 'resumen', icono: <LayoutDashboard size={16} />, texto: t('gastos.vista_resumen') },
    { id: 'registro', icono: <ListOrdered size={16} />, texto: t('gastos.vista_registro') },
    { id: 'presupuesto', icono: <PiggyBank size={16} />, texto: t('gastos.vista_presupuesto') },
  ];

  return (
    <div className="page-container animate-fade-in gastos">
      <div className="page-header">
        <div>
          <h1 className="page-title">{t('gastos.titulo')}</h1>
          <p>
            {t('gastos.subtitulo', { anio })}
            {' · '}
            {planta === '0' ? t('gastos.sin_planta') : plantaElegida ? plantaElegida.nombre : t('plantas.todas')}
          </p>
        </div>
        <div className="metricas-controles">
          <Selector className="form-select" value={String(anio)} onChange={(e) => cambiar({ anio: e.target.value })}
            aria-label={t('gastos.anio')} style={{ minWidth: '110px' }}>
            {anios.map((a) => <option key={a} value={String(a)}>{a}</option>)}
          </Selector>
          {vista !== 'presupuesto' && plantas.length > 0 && (
            <Selector className="form-select" value={planta} onChange={(e) => cambiar({ planta: e.target.value })}
              aria-label={t('plantas.planta')} style={{ minWidth: '200px' }}>
              <option value="">{t('plantas.todas')}</option>
              <option value="0">{t('gastos.sin_planta')}</option>
              {plantas.map((p) => <option key={p.id} value={String(p.id)}>{`${p.clave} · ${p.nombre}`}</option>)}
            </Selector>
          )}
          <button type="button" className="btn-acento metricas-boton" onClick={() => setEditando({})}
            disabled={!catalogos}>
            <Plus size={16} /> {t('gastos.nuevo')}
          </button>
        </div>
      </div>

      <nav className="filtros-estado gastos-vistas" aria-label={t('gastos.titulo')}>
        {pestanas.map((p) => (
          <button key={p.id} type="button"
            className={`chip-filtro chip-filtro--pestana${vista === p.id ? ' chip-filtro--activo' : ''}`}
            aria-current={vista === p.id ? 'page' : undefined}
            onClick={() => cambiar({ vista: p.id === 'resumen' ? null : p.id })}>
            {p.icono}{p.texto}
          </button>
        ))}
      </nav>

      <Aviso texto={aviso} />

      {vista === 'resumen' && (
        <Resumen anio={anio} planta={planta} catalogos={catalogos} version={version}
          onMes={(mes) => cambiar({ vista: 'registro', mes })}
          onAbrir={setAbierto} onNuevo={() => setEditando({})} />
      )}
      {vista === 'registro' && (
        <Registro anio={anio} planta={planta} catalogos={catalogos} version={version}
          mes={Number(params.get('mes')) || null} onMes={(mes) => cambiar({ mes })}
          onAbrir={setAbierto} onNuevo={() => setEditando({})} onCambio={refrescar} />
      )}
      {vista === 'presupuesto' && (
        <Presupuesto anio={anio} catalogos={catalogos} onCambio={refrescar} />
      )}

      {editando && catalogos && (
        <FormularioGasto
          gasto={editando.id ? editando : null}
          catalogos={catalogos}
          plantas={plantas}
          onCerrar={() => setEditando(null)}
          onGuardado={(g) => { setEditando(null); refrescar(); setAbierto(g.id); }}
        />
      )}
      {abierto && (
        <DetalleGasto
          id={abierto}
          version={version}
          onCerrar={() => setAbierto(null)}
          onEditar={(g) => { setAbierto(null); setEditando(g); }}
          onCambio={refrescar}
        />
      )}
    </div>
  );
}

function Resumen({ anio, planta, catalogos, version, onMes, onAbrir, onNuevo }) {
  const { t, i18n } = useTranslation();
  const idioma = i18n.language;
  const [datos, setDatos] = useState(null);
  const [error, setError] = useState('');
  const [cargando, setCargando] = useState(true);

  useEffect(() => {
    let vivo = true;
    setCargando(true);
    const p = { anio };
    if (planta !== '') p.sitio_id = planta;
    api.get('/gastos/resumen', { params: p })
      .then((res) => {
        if (!vivo) return;
        if (forma(res.data, ['totales', 'meses', 'por_categoria', 'expediente'], 'el resumen de gastos')) {
          setDatos(res.data);
          setError('');
        } else {
          setError(t('gastos.error_cargar'));
        }
      })
      .catch((err) => vivo && setError(mensajeDeError(err, t('gastos.error_cargar'))))
      .finally(() => vivo && setCargando(false));
    return () => { vivo = false; };
  }, [anio, planta, version, t]);

  if (cargando && !datos) return <EsqueletoLista filas={3} />;
  if (error) return <Aviso texto={error} tono="peligro" />;
  if (!datos) return null;

  const tot = datos.totales;
  const meses = lista(datos.meses, 'los meses del resumen');
  const categorias = lista(datos.por_categoria, 'las categorías del resumen');
  const colorDe = coloresDeCategorias(catalogos?.categorias || categorias.map((c) => ({ id: c.categoria_id })));
  const nombres = new Map([...(catalogos?.categorias || []).map((c) => [c.id, c.nombre]),
    ...categorias.map((c) => [c.categoria_id, c.nombre])]);
  const nombreDe = (id) => nombres.get(id) || t('gastos.categoria_desconocida');
  const fmt = {
    d: (v) => dinero(v, idioma, { decimales: 0 }),
    n: (v) => entero(v, idioma),
  };
  const conPresupuesto = datos.con_presupuesto && tot.presupuesto > 0;
  const ultimoMes = datos.mes_en_curso || (datos.fraccion_transcurrida > 0 ? 12 : 0);

  if (tot.n === 0) {
    return (
      <>
        {conPresupuesto && (
          <div className="rejilla-metricas" style={{ marginBottom: 20 }}>
            <Tarjeta etiqueta={t('gastos.presupuesto_anual')} valor={tot.presupuesto} formatear={fmt.d}
              ambito={String(anio)} />
          </div>
        )}
        <EstadoVacio icono={<Wallet size={26} />} texto={t('gastos.vacio_anio', { anio })}
          detalle={t('gastos.vacio_detalle')}
          accion={<button type="button" className="btn-acento" onClick={onNuevo}><Plus size={16} /> {t('gastos.nuevo')}</button>} />
      </>
    );
  }

  // El estado contra el presupuesto: con palabra e icono, nunca solo color.
  let ritmo = null;
  if (conPresupuesto) {
    if (tot.gastado > tot.presupuesto) ritmo = { tono: 'peligro', texto: t('gastos.ritmo_rebasado'), icono: <AlertTriangle size={14} /> };
    else if (tot.desviacion > 0) ritmo = { tono: 'atencion', texto: t('gastos.ritmo_arriba'), icono: <ArrowUpRight size={14} /> };
    else ritmo = { tono: 'exito', texto: t('gastos.ritmo_dentro'), icono: <CheckCircle2 size={14} /> };
  }
  const caro = datos.mes_mas_caro;

  return (
    <>
      <div className="rejilla-metricas gastos-casillas">
        <Tarjeta etiqueta={t('gastos.gastado')} valor={tot.gastado} formatear={fmt.d} ambito={String(anio)}
          ayuda={t('gastos.n_gastos', { count: tot.n })} />
        <Tarjeta etiqueta={t('gastos.presupuesto_anual')} valor={conPresupuesto ? tot.presupuesto : null}
          formatear={fmt.d} ambito={String(anio)}
          ayuda={!datos.con_presupuesto ? t('gastos.presupuesto_global') : !conPresupuesto ? t('gastos.sin_presupuesto') : null} />
        <Tarjeta etiqueta={t('gastos.disponible')} valor={conPresupuesto ? tot.disponible : null} formatear={fmt.d}
          tono={conPresupuesto && tot.disponible < 0 ? 'peligro' : undefined}
          ayuda={conPresupuesto ? t('gastos.consumido', { pct: pct(tot.consumo, idioma, 1) }) : null} />
        <Tarjeta etiqueta={t('gastos.contra_ritmo')} sinAnimar tono={ritmo?.tono}
          valor={conPresupuesto ? (
            <span className="gasto-desviacion">
              {tot.desviacion > 0 ? '+' : ''}{dinero(tot.desviacion, idioma, { decimales: 0 })}
            </span>) : null}
          ayuda={ritmo ? (
            <span className={`gasto-ritmo gasto-ritmo--${ritmo.tono}`}>{ritmo.icono}{ritmo.texto}</span>
          ) : t('gastos.contra_ritmo_ayuda')} />
        <Tarjeta etiqueta={t('gastos.pendiente_pago')} valor={tot.pendiente} formatear={fmt.d}
          ambito={t('gastos.ambito_ahora')} />
        <Tarjeta etiqueta={t('gastos.ritmo_mensual')} valor={tot.ritmo_mensual} formatear={fmt.d}
          ayuda={t('gastos.ritmo_mensual_ayuda')} />
        <Tarjeta etiqueta={t('gastos.proyeccion')} valor={datos.mes_en_curso ? tot.proyeccion : null} formatear={fmt.d}
          ayuda={datos.mes_en_curso ? t('gastos.proyeccion_ayuda') : t('gastos.proyeccion_solo_actual')} />
        <Tarjeta etiqueta={t('gastos.vs_anio_anterior', { anio: anio - 1 })} sinAnimar
          valor={tot.vs_anio_anterior === null || tot.vs_anio_anterior === undefined ? null
            : `${tot.vs_anio_anterior > 0 ? '+' : ''}${pct(tot.vs_anio_anterior, idioma)}`}
          ayuda={tot.anio_anterior ? t('gastos.vs_anio_anterior_ayuda', {
            monto: dineroTexto(tot.anio_anterior, idioma, { decimales: 0 }) }) : t('gastos.sin_anio_anterior')} />
      </div>
      {tot.usd?.n > 0 && (
        <p className="metricas-nota gastos-nota-usd">
          {t('gastos.nota_usd', { count: tot.usd.n, usd: dineroTexto(tot.usd.total_usd, idioma, { moneda: 'USD' }),
            mxn: dineroTexto(tot.usd.total_mxn, idioma) })}
        </p>
      )}

      <div className="gastos-doble">
        <Seccion icono={<TrendingUp size={20} color="var(--accent-primary)" />} titulo={t('gastos.por_mes')}>
          <p className="metricas-nota gastos-ayuda-grafica">{t('gastos.por_mes_ayuda')}</p>
          <GraficaMeses meses={meses} colorDe={colorDe} nombreDe={nombreDe} mesEnCurso={datos.mes_en_curso}
            onMes={onMes} />
        </Seccion>

        {caro && (
          <Seccion icono={<Trophy size={20} color="var(--accent-primary)" />} titulo={t('gastos.mes_mas_caro')}>
            <div className="gasto-caro">
              <div className="gasto-caro-cabeza">
                <strong>{nombreMes(caro.mes, idioma)}</strong>
                <span>{dinero(caro.total, idioma)}</span>
              </div>
              <ul className="gasto-caro-razones">
                <li>{t('gastos.razon_categoria', { categoria: caro.categoria.nombre || nombreDe(caro.categoria.id),
                  pct: pct(caro.categoria.pct, idioma), monto: dineroTexto(caro.categoria.total, idioma, { decimales: 0 }) })}</li>
                <li>
                  {t(caro.mayor_gasto.proveedor ? 'gastos.razon_mayor_con' : 'gastos.razon_mayor', {
                    concepto: caro.mayor_gasto.concepto, proveedor: caro.mayor_gasto.proveedor,
                    monto: dineroTexto(caro.mayor_gasto.total_mxn, idioma, { decimales: 0 }),
                    pct: pct(caro.mayor_gasto.pct, idioma) })}
                  {' '}
                  <button type="button" className="enlace-boton" onClick={() => onAbrir(caro.mayor_gasto.id)}>
                    {t('gastos.ver')}
                  </button>
                </li>
                {caro.proveedor.nombre && caro.proveedor.n > 1 && (
                  <li>{t('gastos.razon_proveedor', { proveedor: caro.proveedor.nombre, count: caro.proveedor.n,
                    monto: dineroTexto(caro.proveedor.total, idioma, { decimales: 0 }) })}</li>
                )}
                {caro.vs_promedio !== null && caro.vs_promedio !== undefined && (
                  <li>{t('gastos.razon_promedio', { pct: pct(caro.vs_promedio, idioma),
                    promedio: dineroTexto(caro.promedio, idioma, { decimales: 0 }) })}</li>
                )}
                {caro.vs_mes_anterior !== null && caro.vs_mes_anterior !== undefined && (
                  <li>{t(caro.vs_mes_anterior >= 0 ? 'gastos.razon_sube' : 'gastos.razon_baja', {
                    pct: pct(Math.abs(caro.vs_mes_anterior), idioma), mes: nombreMes(caro.mes - 1, idioma) })}</li>
                )}
              </ul>
              <button type="button" className="btn-secondary metricas-boton" onClick={() => onMes(caro.mes)}>
                {t('gastos.ver_mes', { mes: nombreMes(caro.mes, idioma) })}
              </button>
            </div>
          </Seccion>
        )}
      </div>

      {conPresupuesto && ultimoMes > 0 && (
        <Seccion icono={<PiggyBank size={20} color="var(--accent-primary)" />} titulo={t('gastos.acumulado')}>
          <p className="metricas-nota gastos-ayuda-grafica">{t('gastos.acumulado_ayuda')}</p>
          <GraficaAcumulado meses={meses} presupuesto={tot.presupuesto} ultimoMes={ultimoMes} />
        </Seccion>
      )}

      <Seccion icono={<Wallet size={20} color="var(--accent-primary)" />} titulo={t('gastos.por_categoria')}>
        <div className="gasto-categorias">
          {categorias.filter((c) => c.total > 0 || c.presupuesto > 0).map((c) => {
            const base = c.presupuesto > 0 ? c.presupuesto : Math.max(...categorias.map((x) => x.total), 1);
            const lleno = Math.min(1, c.total / base);
            const tono = c.presupuesto > 0
              ? (c.total > c.presupuesto ? 'peligro' : c.total > c.prorrateado ? 'atencion' : 'normal')
              : 'normal';
            return (
              <div key={c.categoria_id} className="gasto-categoria">
                <div className="gasto-categoria-nombre">
                  <i style={{ background: colorDe(c.categoria_id) }} aria-hidden="true" />
                  <span>{c.nombre}</span>
                  {tono === 'peligro' && <span className="gasto-ritmo gasto-ritmo--peligro"><AlertTriangle size={12} />{t('gastos.rebasado')}</span>}
                  {tono === 'atencion' && <span className="gasto-ritmo gasto-ritmo--atencion"><ArrowUpRight size={12} />{t('gastos.arriba_ritmo')}</span>}
                </div>
                <div className="gasto-categoria-pista">
                  <div className={`gasto-categoria-relleno gasto-categoria-relleno--${tono}`}
                    style={{ width: `${lleno * 100}%` }} />
                  {c.presupuesto > 0 && datos.fraccion_transcurrida > 0 && datos.fraccion_transcurrida < 1 && (
                    <span className="gasto-categoria-marca" style={{ left: `${datos.fraccion_transcurrida * 100}%` }}
                      title={t('gastos.marca_ritmo')} />
                  )}
                </div>
                <div className="gasto-categoria-cifra">
                  {dinero(c.total, idioma, { decimales: 0, codigo: false })}
                  {c.presupuesto > 0 && (
                    <span className="gasto-categoria-de">
                      {' / '}{dineroTexto(c.presupuesto, idioma, { decimales: 0 })}
                      {' · '}{pct(c.consumo, idioma)}
                    </span>
                  )}
                </div>
              </div>
            );
          })}
        </div>
        {conPresupuesto && datos.fraccion_transcurrida > 0 && datos.fraccion_transcurrida < 1 && (
          <p className="metricas-nota">{t('gastos.marca_ritmo_nota', { pct: pct(datos.fraccion_transcurrida, idioma) })}</p>
        )}
      </Seccion>

      <div className="gastos-doble gastos-doble--parejo">
        <Seccion icono={<Building2 size={20} color="var(--accent-primary)" />} titulo={t('gastos.por_proveedor')}>
          <Reparto filas={lista(datos.por_proveedor, 'los proveedores del resumen')} total={tot.gastado} idioma={idioma}
            nombre={(f) => f.nombre || t('gastos.sin_proveedor')} />
        </Seccion>
        <Seccion icono={<Factory size={20} color="var(--accent-primary)" />} titulo={t('gastos.por_planta')}>
          <Reparto filas={lista(datos.por_planta, 'las plantas del resumen')} total={tot.gastado} idioma={idioma}
            nombre={(f) => (f.nombre ? `${f.clave} · ${f.nombre}` : t('gastos.sin_planta'))} />
        </Seccion>
      </div>

      <Seccion icono={<FolderCheck size={20} color="var(--accent-primary)" />} titulo={t('gastos.expediente')}>
        <div className="rejilla-metricas gastos-casillas--chicas">
          <Tarjeta etiqueta={t('gastos.exp_completos')} sinAnimar
            valor={<>{entero(datos.expediente.completos, idioma)}<span className="cifra-unidad"> / {entero(datos.expediente.total, idioma)}</span></>} />
          {['sin_factura', 'sin_cotizacion', 'sin_orden_compra', 'sin_pedido', 'sin_albaran'].map((k) => (
            <Tarjeta key={k} etiqueta={t(`gastos.exp_${k}`)} valor={datos.expediente[k]} formatear={fmt.n}
              tono={datos.expediente[k] > 0 ? 'atencion' : undefined} />
          ))}
        </div>
      </Seccion>
    </>
  );
}

function Reparto({ filas, total, idioma, nombre }) {
  const { t } = useTranslation();
  if (!filas.length) return <div className="metricas-vacio">{t('gastos.sin_datos')}</div>;
  return (
    <div className="reparto">
      {filas.map((f, i) => (
        <div key={i} className="fila-canal">
          <div className="fila-canal-nombre" title={nombre(f)}>{nombre(f)}</div>
          <div className="fila-canal-pista">
            <div className="fila-canal-relleno" style={{ width: `${total ? (100 * f.total) / total : 0}%` }} />
          </div>
          <div className="fila-canal-cifra">{dineroTexto(f.total, idioma, { decimales: 0 })}</div>
        </div>
      ))}
    </div>
  );
}

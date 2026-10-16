import React, { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { Search, FileSpreadsheet, FileText, CheckCheck, Store, ShoppingCart, Plus, Receipt, Factory, Laptop, Ticket, SlidersHorizontal } from 'lucide-react';
import api from '../../api/client';
import forma from '../../lib/forma';
import lista from '../../lib/lista';
import { avisar, mensajeDeError } from '../../lib/avisos';
import { dinero, dineroTexto, entero } from '../../lib/cifras';
import Selector from '../Selector';
import Aviso from '../Aviso';
import EstadoVacio from '../EstadoVacio';
import { EsqueletoLista } from '../Cargando';
import { ChipEstado, EtapasExpediente, coloresDeCategorias, fechaCorta, nombreMes, traer } from './comun';

/**
 * El registro de gastos: filtros en una fila, la lista y lo que suma.
 *
 * **Una tarjeta por gasto y no una tabla.** Con ocho columnas, a 360 px una
 * tabla obliga a desplazarse de lado y se pierde de qué fila es cada cifra.
 * La tarjeta se reacomoda: en pantalla ancha es una fila; en el teléfono, el
 * concepto arriba y el importe y el estado debajo.
 *
 * Lo que se exporta es lo que se ve: los mismos filtros van a la exportación.
 */
export default function Registro({ anio, planta, catalogos, version, mes, onMes, onAbrir, onNuevo, onCambio }) {
  const { t, i18n } = useTranslation();
  const idioma = i18n.language;
  const [categoria, setCategoria] = useState('');
  const [estado, setEstado] = useState('');
  const [tipo, setTipo] = useState('');
  const [texto, setTexto] = useState('');
  const [q, setQ] = useState('');
  const [datos, setDatos] = useState(null);
  const [cargando, setCargando] = useState(true);
  const [aviso, setAviso] = useState('');
  const [exportando, setExportando] = useState('');
  // En el teléfono los filtros van plegados: eran cinco renglones antes del
  // primer gasto. En pantalla ancha siempre se ven (index.css).
  const [verFiltros, setVerFiltros] = useState(false);

  // La búsqueda espera a que se deje de teclear.
  useEffect(() => {
    const espera = setTimeout(() => setQ(texto.trim()), 300);
    return () => clearTimeout(espera);
  }, [texto]);

  const parametros = useMemo(() => {
    const p = { anio };
    if (mes) p.mes = mes;
    if (planta !== '') p.sitio_id = planta;
    if (categoria) p.categoria_id = categoria;
    if (estado) p.estado = estado;
    if (tipo) p.tipo_compra = tipo;
    if (q.length >= 2) p.q = q;
    return p;
  }, [anio, mes, planta, categoria, estado, tipo, q]);

  useEffect(() => {
    let vivo = true;
    setCargando(true);
    api.get('/gastos', { params: parametros })
      .then((res) => {
        if (!vivo) return;
        if (forma(res.data, ['gastos', 'total'], 'el registro de gastos')) {
          setDatos(res.data);
          setAviso('');
        } else {
          setAviso(t('gastos.error_cargar'));
        }
      })
      .catch((err) => vivo && setAviso(mensajeDeError(err, t('gastos.error_cargar'))))
      .finally(() => vivo && setCargando(false));
    return () => { vivo = false; };
  }, [parametros, version, t]);

  const colorDe = coloresDeCategorias(catalogos?.categorias);
  const gastos = lista(datos?.gastos, 'los gastos');

  const exportar = async (formato) => {
    setExportando(formato);
    try {
      const nombre = `gastos-ti-${anio}${mes ? `-${String(mes).padStart(2, '0')}` : ''}.${formato}`;
      await traer('/gastos/exportar', nombre, { params: { ...parametros, formato, idioma: idioma.slice(0, 2) } });
    } catch (err) {
      setAviso(mensajeDeError(err, t('gastos.error_exportar')));
    } finally {
      setExportando('');
    }
  };

  const pagar = async (g) => {
    try {
      await api.post(`/gastos/${g.id}/pagar`, {});
      avisar(t('gastos.marcado_pagado', { concepto: g.concepto }), { tono: 'exito' });
      onCambio();
    } catch (err) {
      setAviso(mensajeDeError(err, t('gastos.error_guardar')));
    }
  };

  const hayFiltros = mes || categoria || estado || tipo || q || planta !== '';
  const filtrosPuestos = [mes, categoria, estado, tipo].filter(Boolean).length;

  return (
    <>
      <div className={`gastos-filtros${verFiltros ? ' gastos-filtros--abiertos' : ''}`}>
        <label className="gastos-buscar">
          <Search size={16} aria-hidden="true" />
          <input className="form-input" type="search" value={texto} onChange={(e) => setTexto(e.target.value)}
            placeholder={t('gastos.buscar')} aria-label={t('gastos.buscar')} maxLength={100} />
        </label>
        <button type="button" className="btn-secondary metricas-boton gastos-filtros-boton"
          aria-expanded={verFiltros} onClick={() => setVerFiltros((v) => !v)}>
          <SlidersHorizontal size={15} />
          {filtrosPuestos ? t('gastos.filtros_n', { count: filtrosPuestos }) : t('gastos.filtros')}
        </button>
        <Selector className="form-select gastos-filtro" value={mes ? String(mes) : ''} onChange={(e) => onMes(e.target.value || null)}
          aria-label={t('gastos.mes')}>
          <option value="">{t('gastos.todo_el_anio')}</option>
          {Array.from({ length: 12 }, (_, i) => (
            <option key={i + 1} value={String(i + 1)}>{nombreMes(i + 1, idioma)}</option>
          ))}
        </Selector>
        <Selector className="form-select gastos-filtro" value={categoria} onChange={(e) => setCategoria(e.target.value)}
          aria-label={t('gastos.categoria')}>
          <option value="">{t('gastos.todas_categorias')}</option>
          {lista(catalogos?.categorias).map((c) => (
            <option key={c.id} value={String(c.id)}>{c.activa ? c.nombre : `${c.nombre} (${t('gastos.retirada')})`}</option>
          ))}
        </Selector>
        <Selector className="form-select gastos-filtro" value={estado} onChange={(e) => setEstado(e.target.value)}
          aria-label={t('gastos.estado')}>
          <option value="">{t('gastos.todos_estados')}</option>
          <option value="pendiente">{t('gastos.estado_pendiente')}</option>
          <option value="pagado">{t('gastos.estado_pagado')}</option>
        </Selector>
        <Selector className="form-select gastos-filtro" value={tipo} onChange={(e) => setTipo(e.target.value)}
          aria-label={t('gastos.tipo_compra')}>
          <option value="">{t('gastos.todos_tipos')}</option>
          <option value="proveedor">{t('gastos.compra_proveedor')}</option>
          <option value="linea">{t('gastos.compra_linea')}</option>
        </Selector>
        <div className="gastos-exportar">
          <button type="button" className="btn-secondary metricas-boton" onClick={() => exportar('csv')}
            disabled={!!exportando || !datos?.total}>
            <FileText size={15} /> {exportando === 'csv' ? t('gastos.exportando') : 'CSV'}
          </button>
          <button type="button" className="btn-secondary metricas-boton" onClick={() => exportar('xlsx')}
            disabled={!!exportando || !datos?.total}>
            <FileSpreadsheet size={15} /> {exportando === 'xlsx' ? t('gastos.exportando') : 'Excel'}
          </button>
        </div>
      </div>

      <Aviso texto={aviso} tono="peligro" />

      {cargando && !datos ? <EsqueletoLista filas={4} /> : gastos.length === 0 ? (
        <EstadoVacio icono={<Receipt size={26} />}
          texto={hayFiltros ? t('gastos.vacio_filtros') : t('gastos.vacio_anio', { anio })}
          detalle={hayFiltros ? null : t('gastos.vacio_detalle')}
          accion={hayFiltros ? null : (
            <button type="button" className="btn-acento" onClick={onNuevo}><Plus size={16} /> {t('gastos.nuevo')}</button>
          )} />
      ) : (
        <>
          <div className="gastos-suma" role="status">
            <span>{t('gastos.n_gastos', { count: datos.total })}{mes ? ` · ${nombreMes(mes, idioma)} ${anio}` : ` · ${anio}`}</span>
            <span>{t('gastos.suma')}: <strong>{dinero(datos.suma_mxn, idioma)}</strong></span>
            <span>{t('gastos.pendiente_pago')}: <strong>{dinero(datos.pendiente_mxn, idioma)}</strong></span>
          </div>
          <ul className="gastos-lista">
            {gastos.map((g) => (
              <li key={g.id} className="gasto-fila apple-card">
                <div className="gasto-fila-fecha">
                  <span>{fechaCorta(g.fecha, idioma)}</span>
                  <span className="gasto-fila-tipo" title={t(g.tipo_compra === 'linea' ? 'gastos.compra_linea' : 'gastos.compra_proveedor')}>
                    {g.tipo_compra === 'linea' ? <ShoppingCart size={13} /> : <Store size={13} />}
                    {t(g.tipo_compra === 'linea' ? 'gastos.linea_corto' : 'gastos.proveedor_corto')}
                  </span>
                </div>
                <div className="gasto-fila-principal">
                  <button type="button" className="gasto-fila-concepto" onClick={() => onAbrir(g.id)}>
                    {g.concepto}
                    {g.cantidad > 1 && <span className="gasto-cantidad">× {entero(g.cantidad, idioma)}</span>}
                  </button>
                  <div className="gasto-fila-datos">
                    {g.proveedor && <span className="gasto-dato">{g.proveedor.nombre}</span>}
                    <span className="gasto-dato">
                      <i className="gasto-punto" style={{ background: colorDe(g.categoria.id) }} aria-hidden="true" />
                      {g.categoria.nombre}
                    </span>
                    {g.planta && <span className="chip-dato chip-planta" title={g.planta.nombre}><Factory size={11} />{g.planta.clave}</span>}
                    {g.equipo && <span className="gasto-dato" title={g.equipo.etiqueta}><Laptop size={12} />{g.equipo.etiqueta}</span>}
                    {g.ticket && (
                      <Link to={`/tickets/${g.ticket.id}`} className="gasto-dato gasto-dato--enlace"><Ticket size={12} />{g.ticket.folio}</Link>
                    )}
                  </div>
                </div>
                <div className="gasto-fila-monto">
                  <strong>{dinero(g.total, idioma, { moneda: g.moneda, codigo: g.moneda !== 'MXN' })}</strong>
                  {g.moneda !== 'MXN' && <span className="gasto-fila-mxn">≈ {dineroTexto(g.total_mxn, idioma)}</span>}
                </div>
                <div className="gasto-fila-estado">
                  <ChipEstado estado={g.estado} fechaPago={g.fecha_pago} idioma={idioma} />
                  <EtapasExpediente expediente={g.expediente} tipoCompra={g.tipo_compra} compacta />
                </div>
                <div className="gasto-fila-acciones">
                  {g.estado === 'pendiente' && (
                    <button type="button" className="boton-mini" onClick={() => pagar(g)}
                      title={t('gastos.marcar_pagado')} aria-label={`${t('gastos.marcar_pagado')}: ${g.concepto}`}>
                      <CheckCheck size={15} />
                    </button>
                  )}
                </div>
              </li>
            ))}
          </ul>
          {datos.total > gastos.length && (
            <p className="metricas-nota">{t('gastos.mostrando', { n: gastos.length, total: datos.total })}</p>
          )}
        </>
      )}
    </>
  );
}

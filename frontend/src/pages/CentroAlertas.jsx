import React, { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Bell, Check, CheckCheck, ArrowRight } from 'lucide-react';
import api from '../api/client';
import lista from '../lib/lista';
import Selector from '../components/Selector';
import Aviso from '../components/Aviso';
import EstadoVacio from '../components/EstadoVacio';
import { EsqueletoLista } from '../components/Cargando';
import Confirmacion from '../components/Confirmacion';
import { useEventoPortal } from '../context/Eventos';
import { usePlantas, SelectorPlanta, EtiquetaPlanta } from '../lib/plantas';
import { ICONOS_ALERTA, textoAlerta, hace, pedirResumen } from '../components/CampanaAlertas';

const TIPOS = ['sla_por_vencer', 'sla_vencido', 'satisfaccion_baja', 'iot_umbral', 'iot_sin_senal'];
const PAGINA = 50;

/**
 * El centro de alertas: lo mismo que la campana, con filtros y con historia.
 *
 * La campana contesta «¿qué hay que mirar ahora?» y por eso solo enseña las
 * pendientes, las treinta últimas. Aquí se contesta lo que la campana no
 * puede: qué pasó la semana pasada en Querétaro, cuántas veces se quedó sin
 * señal el mismo sensor, quién dio por atendida una alerta y cuándo.
 *
 * Se pagina por cursor (`antes_de`, el id de la última que ya se tiene) y no
 * por número de página: mientras se lee entran alertas nuevas, y con páginas
 * numeradas la segunda repetiría las últimas de la primera.
 */
export default function CentroAlertas() {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const [plantas] = usePlantas();
  const [estado, setEstado] = useState('pendientes');
  const [tipo, setTipo] = useState('');
  const [plantaId, setPlantaId] = useState(null);
  const [dias, setDias] = useState('30');
  const [alertas, setAlertas] = useState([]);
  const [hayMas, setHayMas] = useState(false);
  const [cargando, setCargando] = useState(true);
  const [aviso, setAviso] = useState('');
  const [preguntaTodas, setPreguntaTodas] = useState(false);

  const params = useCallback((extra = {}) => {
    const p = { limite: PAGINA, ...extra };
    if (estado === 'pendientes') p.pendientes = true;
    else {
      p.pendientes = false;
      if (estado === 'atendidas') p.atendidas = true;
    }
    if (tipo) p.tipo = tipo;
    if (plantaId) p.sitio_id = plantaId;
    if (dias) p.dias = Number(dias);
    return p;
  }, [estado, tipo, plantaId, dias]);

  const cargar = useCallback(async () => {
    setCargando(true);
    try {
      const filas = lista((await api.get('/admin/alertas', { params: params() })).data, 'las alertas');
      setAlertas(filas);
      setHayMas(filas.length === PAGINA);
      setAviso('');
    } catch (err) {
      setAviso(err.response?.data?.detail || t('alertas.error_cargar'));
    } finally {
      setCargando(false);
    }
  }, [params, t]);

  useEffect(() => { cargar(); }, [cargar]);
  // Una alerta nueva o atendida desde otra pantalla: se vuelve a pedir.
  useEventoPortal('alertas', () => { cargar(); });

  const masAntiguas = async () => {
    const ultima = alertas[alertas.length - 1];
    if (!ultima) return;
    try {
      const filas = lista((await api.get('/admin/alertas', {
        params: params({ antes_de: ultima.id }) })).data, 'las alertas');
      setAlertas((a) => [...a, ...filas]);
      setHayMas(filas.length === PAGINA);
    } catch (err) {
      setAviso(err.response?.data?.detail || t('alertas.error_cargar'));
    }
  };

  const atender = async (alerta) => {
    try {
      const res = await api.post(`/admin/alertas/${alerta.id}/atender`);
      // En «pendientes» se va de la lista; en el historial se queda, cerrada.
      setAlertas((a) => (estado === 'pendientes'
        ? a.filter((x) => x.id !== alerta.id)
        : a.map((x) => (x.id === alerta.id ? { ...x, ...res.data } : x))));
      pedirResumen();
    } catch (err) {
      setAviso(err.response?.data?.detail || t('alertas.error_atender'));
    }
  };

  const atenderTodas = async () => {
    setPreguntaTodas(false);
    try {
      const p = {};
      if (tipo) p.tipo = tipo;
      if (plantaId) p.sitio_id = plantaId;
      await api.post('/admin/alertas/atender-todas', null, { params: p });
      pedirResumen();
      cargar();
    } catch (err) {
      setAviso(err.response?.data?.detail || t('alertas.error_atender'));
    }
  };

  const ir = (alerta) => {
    if (alerta.ticket_id) navigate(`/tickets/${alerta.ticket_id}`);
    else if (alerta.dispositivo_id) navigate(`/operacion/monitoreo?dispositivo=${alerta.dispositivo_id}`);
  };

  const fecha = (iso) => new Date(iso).toLocaleString(i18n.language, {
    day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });

  const pendientesEnLista = alertas.filter((a) => !a.atendida_en).length;

  return (
    <div className="page-container animate-fade-in">
      <div className="page-header">
        <div>
          <h1 className="page-title">{t('alertas.centro_titulo')}</h1>
          <p>{t('alertas.centro_sub')}</p>
        </div>
        {estado === 'pendientes' && pendientesEnLista > 1 && (
          <button type="button" className="btn-secondary" onClick={() => setPreguntaTodas(true)}>
            <CheckCheck size={16} /> {t('alertas.atender_todas')}
          </button>
        )}
      </div>

      <div className="barra-herramientas filtros-en-fila">
        <Selector className="form-select" value={estado} onChange={(e) => setEstado(e.target.value)}
          aria-label={t('alertas.filtro_estado')}>
          <option value="pendientes">{t('alertas.estado_pendientes')}</option>
          <option value="atendidas">{t('alertas.estado_atendidas')}</option>
          <option value="todas">{t('alertas.estado_todas')}</option>
        </Selector>
        <Selector className="form-select" value={tipo} onChange={(e) => setTipo(e.target.value)}
          aria-label={t('alertas.filtro_tipo')}>
          <option value="">{t('alertas.tipo_todos')}</option>
          {TIPOS.map((x) => <option key={x} value={x}>{t(`alertas.tipo_${x}`)}</option>)}
        </Selector>
        <SelectorPlanta todas plantas={plantas} value={plantaId} onChange={setPlantaId} />
        <Selector className="form-select" value={dias} onChange={(e) => setDias(e.target.value)}
          aria-label={t('alertas.filtro_periodo')}>
          <option value="7">{t('comun.ultimos_dias', { count: 7 })}</option>
          <option value="30">{t('comun.ultimos_dias', { count: 30 })}</option>
          <option value="90">{t('comun.ultimos_dias', { count: 90 })}</option>
          <option value="365">{t('comun.ultimos_dias', { count: 365 })}</option>
        </Selector>
      </div>

      {aviso && <Aviso texto={aviso} tono="peligro" />}

      {cargando && alertas.length === 0 ? (
        <EsqueletoLista filas={4} />
      ) : alertas.length === 0 ? (
        <EstadoVacio
          icono={<Bell size={28} />}
          texto={estado === 'pendientes' ? t('alertas.ninguna') : t('alertas.sin_historial')}
          detalle={t('alertas.vacio_detalle')}
        />
      ) : (
        <ul className="apple-card centro-alertas-lista">
          {alertas.map((a) => {
            const Icono = ICONOS_ALERTA[a.tipo] || Bell;
            return (
              <li key={a.id} className={`campana-item campana-item--${a.tipo}${a.atendida_en ? ' centro-alerta--atendida' : ''}`}>
                <Icono size={18} className="campana-item-icono" aria-hidden="true" />
                <div className="campana-item-cuerpo">
                  <div className="campana-item-texto">{textoAlerta(a, t)}</div>
                  <div className="campana-item-meta">
                    <span className="centro-alerta-tipo">{t(`alertas.tipo_${a.tipo}`, { defaultValue: a.tipo })}</span>
                    <EtiquetaPlanta planta={a.sitio} compacta />
                    <span title={fecha(a.creado_en)}>{hace(a.creado_en, i18n)}</span>
                  </div>
                  {a.detalle && <div className="campana-item-detalle">{a.detalle}</div>}
                  {a.atendida_en && (
                    <div className="centro-alerta-atendida">
                      <Check size={13} aria-hidden="true" />
                      {a.atendida_por_nombre
                        ? t('alertas.atendida_por', { quien: a.atendida_por_nombre, cuando: fecha(a.atendida_en) })
                        : t('alertas.atendida_sola', { cuando: fecha(a.atendida_en) })}
                    </div>
                  )}
                </div>
                <div className="campana-item-acciones">
                  {(a.ticket_id || a.dispositivo_id) && (
                    <button type="button" className="boton-mini" onClick={() => ir(a)}
                      title={t('alertas.ver')} aria-label={t('alertas.ver')}>
                      <ArrowRight size={14} />
                    </button>
                  )}
                  {!a.atendida_en && (
                    <button type="button" className="boton-mini" onClick={() => atender(a)}
                      title={t('alertas.atender')} aria-label={t('alertas.atender')}>
                      <Check size={14} />
                    </button>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}

      {hayMas && (
        <div style={{ textAlign: 'center', marginTop: '18px' }}>
          <button type="button" className="btn-secondary" onClick={masAntiguas}>{t('alertas.mas_antiguas')}</button>
        </div>
      )}

      {preguntaTodas && (
        <Confirmacion
          titulo={t('alertas.atender_todas')}
          mensaje={t('alertas.confirmar_todas')}
          textoConfirmar={t('alertas.atender_todas')}
          onConfirmar={atenderTodas}
          onCancelar={() => setPreguntaTodas(false)}
        />
      )}
    </div>
  );
}

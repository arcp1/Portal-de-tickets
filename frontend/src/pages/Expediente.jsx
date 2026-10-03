import React, { useState, useEffect } from 'react';
import { useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import api from '../api/client';
import forma from '../lib/forma';
import { useAuth } from '../context/AuthContext';
import { EsqueletoLista } from '../components/Cargando';
import FirmaResguardo from '../components/FirmaResguardo';
import SubirDocumento from '../components/SubirDocumento';
import EstadoVacio from '../components/EstadoVacio';
import {
  Laptop, FileSignature, FileText, Download, AlertTriangle, CheckCircle2,
  Clock, Upload
} from 'lucide-react';

const ESTADOS = {
  pendiente_firma: ['var(--status-espera-proveedor-text)', 'var(--status-espera-proveedor-bg)'],
  firmado: ['var(--status-resuelto-text)', 'var(--status-resuelto-bg)'],
  devuelto: ['var(--text-secondary)', 'var(--bg-tertiary)'],
  cancelado: ['var(--peligro)', 'var(--peligro-bg)'],
  borrador: ['var(--text-secondary)', 'var(--bg-tertiary)']
};

/**
 * Expediente de una persona: lo que tiene a su cargo y lo que tiene firmado.
 *
 * Sin `usuarioId` en la ruta muestra el propio; con él, el de otra persona
 * (solo admin, lo hace valer el backend).
 */
const Expediente = () => {
  const { t, i18n } = useTranslation();
  const { user } = useAuth();
  const { usuarioId } = useParams();

  const [expediente, setExpediente] = useState(null);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState('');
  const [firmando, setFirmando] = useState(null);
  const [subiendo, setSubiendo] = useState(false);

  const esPropio = !usuarioId;

  const cargar = async () => {
    // Una URL editada a mano no es una persona: sin esto el API contestaba
    // con su validación y el nombre técnico del parámetro.
    if (!esPropio && (!/^[1-9]\d{0,9}$/.test(usuarioId) || Number(usuarioId) > 2147483647)) {
      setExpediente(null);
      setError(t('expediente.no_encontrado'));
      setCargando(false);
      return;
    }
    setCargando(true);
    try {
      const ruta = esPropio ? '/expediente/mio' : `/expediente/${usuarioId}`;
      setExpediente((await api.get(ruta)).data);
      setError('');
    } catch (err) {
      // El mismo texto que una URL mal escrita: "no existe" se dice igual
      // venga del API o de la validación de aquí arriba.
      setError(err.response?.status === 404
        ? t('expediente.no_encontrado')
        : err.response?.data?.detail || t('expediente.error_cargar'));
    } finally {
      setCargando(false);
    }
  };

  useEffect(() => { cargar(); }, [usuarioId]);

  const abrirPdf = async (resguardo) => {
    try {
      const res = await api.get(`/resguardos/${resguardo.id}/pdf`, { responseType: 'blob' });
      const url = URL.createObjectURL(res.data);
      window.open(url, '_blank', 'noopener,noreferrer');
      setTimeout(() => URL.revokeObjectURL(url), 60000);
    } catch { setError(t('resguardos.error_pdf')); }
  };

  const abrirDocumento = async (documento) => {
    try {
      const res = await api.get(`/documentos/${documento.id}`, { responseType: 'blob' });
      const url = URL.createObjectURL(res.data);
      window.open(url, '_blank', 'noopener,noreferrer');
      setTimeout(() => URL.revokeObjectURL(url), 60000);
    } catch { setError(t('expediente.error_documento')); }
  };

  const fecha = (iso) => iso ? new Date(iso).toLocaleDateString(i18n.language, {
    day: '2-digit', month: 'short', year: 'numeric'
  }) : '—';

  if (cargando) {
    return <div className="page-container"><EsqueletoLista filas={3} /></div>;
  }

  // `error && !expediente` solo cubría el fallo de red. Un cuerpo con otra
  // forma pasaba de largo y `resguardos.filter` reventaba el render.
  if (error || !forma(expediente, ['usuario', 'equipos_a_cargo', 'resguardos', 'documentos'], 'el expediente')) {
    return (
      <div className="page-container" style={{ textAlign: 'center', padding: '60px' }}>
        <AlertTriangle size={40} color="var(--text-muted)" style={{ margin: '0 auto 16px' }} />
        <div style={{ color: 'var(--text-secondary)' }}>{error || t('expediente.error_cargar')}</div>
      </div>
    );
  }

  const { usuario, equipos_a_cargo: equipos, resguardos, documentos } = expediente;
  const pendientes = resguardos.filter((r) => r.estado === 'pendiente_firma');

  return (
    <div className="page-container animate-fade-in">
      <div className="page-header">
        <div>
          <h1 className="page-title">
            {esPropio ? t('expediente.mi_titulo') : usuario.nombre}
          </h1>
          <p>
            {esPropio
              ? t('expediente.mi_subtitulo')
              // El correo es opcional en planta: sin esto la cabecera decía "null".
            : [usuario.numero_empleado || usuario.email, usuario.area].filter(Boolean).join(' · ')}
          </p>
        </div>
      </div>

      {/* Lo que urge: firmar */}
      {pendientes.length > 0 && (
        <div className="animate-scale-in" style={{
          display: 'flex', alignItems: 'flex-start', gap: '12px',
          padding: '18px 20px', marginBottom: '24px',
          background: 'var(--status-espera-proveedor-bg)',
          color: 'var(--status-espera-proveedor-text)',
          borderRadius: 'var(--radius-md)'
        }}>
          <FileSignature size={20} style={{ flexShrink: 0, marginTop: '1px' }} />
          <div style={{ flex: 1 }}>
            <strong>{t('expediente.tiene_pendientes', { count: pendientes.length })}</strong>
            <div style={{ fontSize: '0.88rem', marginTop: '4px', opacity: 0.9 }}>
              {esPropio ? t('expediente.firme_para_constancia') : t('expediente.pendiente_de_usuario')}
            </div>
          </div>
        </div>
      )}

      {/* Equipos a cargo */}
      <Seccion icono={<Laptop size={19} color="var(--accent-primary)" />}
        /* "A mi cargo" solo es verdad en el propio: TI mirando el de otra
           persona leía que los equipos de ella eran suyos. */
        titulo={esPropio ? t('expediente.equipos') : t('expediente.equipos_ajeno')} conteo={equipos.length}>
        {equipos.length === 0 ? (
          <Vacio texto={t('expediente.sin_equipos')} />
        ) : (
          <div className="lista-escalonada" style={{
            display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(250px, 1fr))', gap: '14px'
          }}>
            {equipos.map((eq) => (
              <div key={eq.id} style={{
                padding: '16px', background: 'var(--bg-secondary)',
                border: '1px solid var(--border-color)', borderRadius: 'var(--radius-md)'
              }}>
                <div style={{ fontWeight: '600', color: 'var(--text-primary)', marginBottom: '4px' }}>
                  {eq.marca} {eq.modelo}
                </div>
                <div style={{ fontSize: '0.84rem', color: 'var(--text-secondary)', lineHeight: 1.6 }}>
                  <span style={{ textTransform: 'capitalize' }}>{eq.categoria}</span><br />
                  {t('inventory.serial')}: {eq.numero_serie || '—'}<br />
                  {eq.ubicacion && <>{t('inventory.location')}: {eq.ubicacion}</>}
                </div>
              </div>
            ))}
          </div>
        )}
      </Seccion>

      {/* Resguardos */}
      <Seccion icono={<FileSignature size={19} color="var(--accent-primary)" />}
        titulo={t('expediente.resguardos')} conteo={resguardos.length}>
        {resguardos.length === 0 ? (
          <Vacio texto={t('expediente.sin_resguardos')} />
        ) : (
          <div className="lista-escalonada" style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
            {resguardos.map((r) => {
              const [color, fondo] = ESTADOS[r.estado] || ESTADOS.borrador;
              return (
                <div key={r.id} style={{
                  padding: '16px 18px', background: 'var(--bg-secondary)',
                  border: '1px solid var(--border-color)', borderRadius: 'var(--radius-md)',
                  display: 'flex', justifyContent: 'space-between', gap: '16px', flexWrap: 'wrap'
                }}>
                  <div style={{ flex: 1, minWidth: '220px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '6px', flexWrap: 'wrap' }}>
                      <span style={{
                        fontFamily: 'var(--font-codigo)', fontWeight: '600', fontSize: '0.86rem',
                        color: 'var(--accent-primary)'
                      }}>{r.folio}</span>
                      <span className="chip-dato" style={{ color, background: fondo }}>
                        {t(`resguardos.estado_${r.estado}`)}
                      </span>
                    </div>
                    <div style={{ fontSize: '0.9rem', color: 'var(--text-primary)', marginBottom: '4px' }}>
                      {r.equipo ? `${r.equipo.marca} ${r.equipo.modelo}` : '—'}
                    </div>
                    <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                      {r.firmado_en
                        ? <><CheckCircle2 size={12} style={{ verticalAlign: '-2px' }} /> {t('resguardos.firmado_el', { fecha: fecha(r.firmado_en) })}</>
                        : <><Clock size={12} style={{ verticalAlign: '-2px' }} /> {t('resguardos.entregado_el', { fecha: fecha(r.entregado_en) })}</>}
                      {r.devuelto_en && ` · ${t('resguardos.devuelto_el', { fecha: fecha(r.devuelto_en) })}`}
                    </div>
                  </div>
                  <div style={{ display: 'flex', gap: '8px', alignItems: 'flex-start' }}>
                    {esPropio && r.estado === 'pendiente_firma' && (
                      <button onClick={() => setFirmando(r)} className="btn-primary"
                        style={{ padding: '9px 16px', fontSize: '0.86rem' }}>
                        <FileSignature size={15} /> {t('resguardos.firmar')}
                      </button>
                    )}
                    <button onClick={() => abrirPdf(r)} className="btn-secondary"
                      style={{ padding: '9px 14px', fontSize: '0.86rem' }} title={t('resguardos.ver_pdf')}>
                      <Download size={15} />
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </Seccion>

      {/* Documentos */}
      <Seccion
        icono={<FileText size={19} color="var(--accent-primary)" />}
        titulo={t('expediente.documentos')}
        conteo={documentos.length}
        accion={!esPropio && (
          <button onClick={() => setSubiendo(true)} className="btn-primary"
            style={{ padding: '8px 14px', fontSize: '0.84rem' }}>
            <Upload size={14} /> {t('expediente.subir')}
          </button>
        )}
      >
        {documentos.length === 0 ? (
          <Vacio texto={t('expediente.sin_documentos')} />
        ) : (
          <div className="lista-escalonada" style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
            {documentos.map((d) => (
              <button key={d.id} onClick={() => abrirDocumento(d)} style={{
                display: 'flex', alignItems: 'center', gap: '14px', textAlign: 'left',
                padding: '14px 16px', background: 'var(--bg-secondary)', cursor: 'pointer',
                border: `1px solid ${d.vencido ? 'var(--peligro-bg)' : 'var(--border-color)'}`,
                borderRadius: 'var(--radius-md)', width: '100%'
              }}>
                <FileText size={20} color={d.vencido ? 'var(--peligro)' : 'var(--text-secondary)'} style={{ flexShrink: 0 }} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontWeight: '600', color: 'var(--text-primary)', fontSize: '0.92rem' }}>
                    {d.titulo}
                  </div>
                  <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginTop: '2px' }}>
                    {t(`expediente.tipo_${d.tipo}`, { defaultValue: d.tipo })} · {fecha(d.creado_en)}
                    {d.vigente_hasta && ` · ${t('expediente.vigente_hasta', { fecha: fecha(d.vigente_hasta) })}`}
                  </div>
                </div>
                {d.vencido && (
                  <span className="chip-dato" style={{ color: 'var(--peligro)', background: 'var(--peligro-bg)' }}>
                    {t('expediente.vencido')}
                  </span>
                )}
              </button>
            ))}
          </div>
        )}
      </Seccion>

      {subiendo && (
        <SubirDocumento
          usuarioId={usuario.id}
          resguardos={resguardos}
          onCerrar={() => setSubiendo(false)}
          onSubido={() => { setSubiendo(false); cargar(); }}
        />
      )}

      {firmando && (
        <FirmaResguardo
          resguardo={firmando}
          nombreSugerido={user?.nombre}
          onCerrar={() => setFirmando(null)}
          onFirmado={() => { setFirmando(null); cargar(); }}
        />
      )}
    </div>
  );
};

const Seccion = ({ icono, titulo, conteo, children, accion }) => (
  <div className="apple-card" style={{ padding: '26px', marginBottom: '22px' }}>
    <div style={{
      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      gap: '12px', marginBottom: '18px', flexWrap: 'wrap'
    }}>
      <h2 style={{
        fontSize: '1.1rem', fontWeight: '700', margin: 0,
        display: 'flex', alignItems: 'center', gap: '10px', color: 'var(--text-primary)'
      }}>
        {icono}
        {titulo}
        {conteo > 0 && (
          <span style={{ fontSize: '0.82rem', color: 'var(--text-muted)', fontWeight: '500' }}>
            ({conteo})
          </span>
        )}
      </h2>
      {accion}
    </div>
    {children}
  </div>
);

const Vacio = ({ texto }) => <EstadoVacio texto={texto} />;

export default Expediente;

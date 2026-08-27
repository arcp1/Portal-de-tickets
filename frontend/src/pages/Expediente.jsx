import React, { useState, useEffect } from 'react';
import { useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import api from '../api/client';
import { useAuth } from '../context/AuthContext';
import Cargando, { EsqueletoLista } from '../components/Cargando';
import FirmaResguardo from '../components/FirmaResguardo';
import SubirDocumento from '../components/SubirDocumento';
import {
  Laptop, FileSignature, FileText, Download, AlertTriangle,
  CheckCircle2, Clock, User, Upload
} from 'lucide-react';

const ESTADOS = {
  pendiente_firma: ['var(--status-espera-proveedor-text)', 'var(--status-espera-proveedor-bg)'],
  firmado: ['var(--status-resuelto-text)', 'var(--status-resuelto-bg)'],
  devuelto: ['var(--text-secondary)', 'var(--bg-tertiary)'],
  cancelado: ['#D8000C', '#FFF0F0'],
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
    setCargando(true);
    try {
      const ruta = esPropio ? '/expediente/mio' : `/expediente/${usuarioId}`;
      setExpediente((await api.get(ruta)).data);
      setError('');
    } catch (err) {
      setError(err.response?.data?.detail || t('expediente.error_cargar'));
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
    return <div className="page-container" style={{ maxWidth: '1000px' }}><EsqueletoLista filas={3} /></div>;
  }

  if (error && !expediente) {
    return (
      <div className="page-container" style={{ maxWidth: '1000px', textAlign: 'center', padding: '60px' }}>
        <AlertTriangle size={40} color="var(--text-muted)" style={{ margin: '0 auto 16px' }} />
        <div style={{ color: 'var(--text-secondary)' }}>{error}</div>
      </div>
    );
  }

  const { usuario, equipos_a_cargo: equipos, resguardos, documentos } = expediente;
  const pendientes = resguardos.filter((r) => r.estado === 'pendiente_firma');

  return (
    <div className="page-container animate-fade-in" style={{ maxWidth: '1000px' }}>
      <h1 style={{ fontSize: '1.85rem', fontWeight: '700', marginBottom: '6px', color: 'var(--text-primary)' }}>
        {esPropio ? t('expediente.mi_titulo') : usuario.nombre}
      </h1>
      <p style={{ color: 'var(--text-secondary)', marginBottom: '28px' }}>
        {esPropio
          ? t('expediente.mi_subtitulo')
          : `${usuario.email}${usuario.area ? ' · ' + usuario.area : ''}`}
      </p>

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
            <strong>{t('expediente.tiene_pendientes', { n: pendientes.length })}</strong>
            <div style={{ fontSize: '0.88rem', marginTop: '4px', opacity: 0.9 }}>
              {esPropio ? t('expediente.firme_para_constancia') : t('expediente.pendiente_de_usuario')}
            </div>
          </div>
        </div>
      )}

      {/* Equipos a cargo */}
      <Seccion icono={<Laptop size={19} color="var(--accent-primary)" />}
        titulo={t('expediente.equipos')} conteo={equipos.length}>
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
                        fontFamily: 'monospace', fontWeight: '600', fontSize: '0.86rem',
                        color: 'var(--accent-primary)'
                      }}>{r.folio}</span>
                      <span style={{
                        fontSize: '0.74rem', fontWeight: '600', padding: '3px 10px',
                        borderRadius: 'var(--radius-full)', color, background: fondo
                      }}>
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
                border: `1px solid ${d.vencido ? '#FFD6D6' : 'var(--border-color)'}`,
                borderRadius: 'var(--radius-md)', width: '100%'
              }}>
                <FileText size={20} color={d.vencido ? '#D8000C' : 'var(--text-secondary)'} style={{ flexShrink: 0 }} />
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
                  <span style={{
                    fontSize: '0.74rem', fontWeight: '600', padding: '3px 10px',
                    borderRadius: 'var(--radius-full)', color: '#D8000C', background: '#FFF0F0'
                  }}>
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

const Vacio = ({ texto }) => (
  <div style={{ padding: '24px', textAlign: 'center', color: 'var(--text-muted)', fontSize: '0.9rem' }}>
    {texto}
  </div>
);

export default Expediente;

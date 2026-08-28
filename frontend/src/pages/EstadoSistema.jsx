import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import api from '../api/client';
import { EsqueletoLista } from '../components/Cargando';
import {
  Activity, CheckCircle2, XCircle, PauseCircle, KeyRound, RefreshCw,
  Database, Cpu, Sparkles, Clock, Ticket, Users
} from 'lucide-react';

/**
 * Estado de los servicios de los que depende el portal.
 *
 * Lo importante de esta pantalla no es que todo salga en verde. Es que cuando
 * algo sale en rojo, se vea **qué deja de funcionar y qué no**: Ollama y Gemini
 * son ayudas, y su caída no impide levantar un ticket. Por eso cada servicio
 * dice, en su propia tarjeta, qué pasa si se cae.
 */

const ICONOS = {
  db: Database,
  ollama: Cpu,
  gemini: Sparkles
};

const ESTADOS = {
  arriba: ['var(--status-resuelto-text)', 'var(--status-resuelto-bg)', CheckCircle2],
  abajo: ['#D8000C', '#FFF0F0', XCircle],
  apagado: ['var(--text-secondary)', 'var(--bg-tertiary)', PauseCircle],
  sin_llave: ['var(--status-espera-proveedor-text)', 'var(--status-espera-proveedor-bg)', KeyRound],
  en_espera: ['var(--status-espera-proveedor-text)', 'var(--status-espera-proveedor-bg)', Clock]
};

const EstadoSistema = () => {
  const { t } = useTranslation();
  const [datos, setDatos] = useState(null);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState('');

  const cargar = async () => {
    try {
      const res = await api.get('/admin/estado/sistema');
      setDatos(res.data);
      setError('');
    } catch {
      setError(t('estado.error_cargar'));
    } finally {
      setCargando(false);
    }
  };

  useEffect(() => {
    cargar();
    // Se refresca solo: es una pantalla que se deja abierta en un monitor.
    const intervalo = setInterval(cargar, 60000);
    return () => clearInterval(intervalo);
  }, []);

  if (cargando) return <div className="page-container"><EsqueletoLista /></div>;

  return (
    <div className="page-container animate-fade-in" style={{ maxWidth: '1000px' }}>
      <div style={{
        display: 'flex', justifyContent: 'space-between',
        alignItems: 'flex-start', gap: '16px', flexWrap: 'wrap', marginBottom: '26px'
      }}>
        <div>
          <h1 style={{ fontSize: '1.85rem', fontWeight: '700', marginBottom: '6px', color: 'var(--text-primary)' }}>
            {t('estado.title')}
          </h1>
          <p style={{ color: 'var(--text-secondary)' }}>{t('estado.subtitle')}</p>
        </div>
        <button onClick={cargar} className="btn-secondary" style={{ padding: '10px 16px', fontSize: '0.86rem' }}>
          <RefreshCw size={15} /> {t('estado.actualizar')}
        </button>
      </div>

      {error && (
        <div style={{
          background: '#FFF0F0', border: '1px solid #FFD6D6', color: '#D8000C',
          padding: '13px 16px', borderRadius: 'var(--radius-md)', marginBottom: '20px'
        }}>
          {error}
        </div>
      )}

      {datos && (
        <>
          {/* Titular: si el portal atiende o no. La IA no entra en esta cuenta. */}
          <div className="apple-card" style={{
            padding: '24px', marginBottom: '20px',
            display: 'flex', alignItems: 'center', gap: '16px',
            borderLeft: `4px solid ${datos.operativo ? 'var(--status-resuelto-text)' : '#D8000C'}`
          }}>
            <Activity size={30} color={datos.operativo ? 'var(--status-resuelto-text)' : '#D8000C'} />
            <div>
              <div style={{ fontSize: '1.15rem', fontWeight: '700', color: 'var(--text-primary)' }}>
                {datos.operativo ? t('estado.operativo') : t('estado.no_operativo')}
              </div>
              <div style={{ fontSize: '0.88rem', color: 'var(--text-secondary)', marginTop: '3px' }}>
                {datos.operativo ? t('estado.operativo_detalle') : t('estado.no_operativo_detalle')}
              </div>
            </div>
          </div>

          <div style={{
            display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))',
            gap: '16px', marginBottom: '24px'
          }}>
            {datos.servicios.map((s) => <TarjetaServicio key={s.clave} servicio={s} t={t} />)}
          </div>

          <div className="apple-card" style={{ padding: '22px' }}>
            <h2 style={{ fontSize: '1rem', fontWeight: '700', marginBottom: '16px', color: 'var(--text-primary)' }}>
              {t('estado.actividad')}
            </h2>
            <div style={{ display: 'flex', gap: '30px', flexWrap: 'wrap' }}>
              <Cifra icono={<Ticket size={16} />}
                valor={datos.actividad_24h.tickets_creados}
                etiqueta={t('estado.tickets_24h')} />
              <Cifra icono={<Users size={16} />}
                valor={datos.actividad_24h.usuarios_activos}
                etiqueta={t('estado.usuarios_24h')} />
              <Cifra icono={<Clock size={16} />}
                valor={datos.horario.dentro_de_horario ? t('estado.si') : t('estado.no')}
                etiqueta={t('estado.en_horario')} />
            </div>
          </div>
        </>
      )}
    </div>
  );
};

const TarjetaServicio = ({ servicio, t }) => {
  const [color, fondo, IconoEstado] = ESTADOS[servicio.estado] || ESTADOS.abajo;
  const Icono = ICONOS[servicio.clave] || Activity;
  const latencias = Object.entries(servicio.latencias_ms || {})
    .filter(([, v]) => v != null);

  return (
    <div className="apple-card" style={{ padding: '20px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '10px' }}>
        <Icono size={18} color="var(--text-secondary)" />
        <strong style={{ color: 'var(--text-primary)', fontSize: '0.95rem', flex: 1 }}>
          {servicio.nombre}
        </strong>
        <span style={{
          display: 'inline-flex', alignItems: 'center', gap: '5px',
          fontSize: '0.74rem', fontWeight: '600', padding: '3px 10px',
          borderRadius: 'var(--radius-full)', color, background: fondo
        }}>
          <IconoEstado size={12} /> {t('estado.' + servicio.estado)}
        </span>
      </div>

      <div style={{ fontSize: '0.82rem', color: 'var(--text-secondary)', marginBottom: '10px' }}>
        {servicio.detalle}
      </div>

      {latencias.length > 0 && (
        <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap', marginBottom: '10px' }}>
          {latencias.map(([nombre, ms]) => (
            <span key={nombre} style={{ fontSize: '0.76rem', color: 'var(--text-muted)' }}>
              {nombre}: <strong style={{ color: 'var(--text-secondary)' }}>{ms} ms</strong>
            </span>
          ))}
        </div>
      )}

      {/* Lo que de verdad importa cuando algo está caído. */}
      {servicio.estado !== 'arriba' && servicio.degradacion && (
        <div style={{
          fontSize: '0.8rem', lineHeight: 1.5, padding: '10px 12px',
          background: 'var(--bg-tertiary)', borderRadius: 'var(--radius-sm)',
          color: 'var(--text-secondary)'
        }}>
          {servicio.degradacion}
        </div>
      )}

      {servicio.critico && (
        <div style={{ fontSize: '0.76rem', color: 'var(--text-muted)', marginTop: '8px' }}>
          {t('estado.critico')}
        </div>
      )}
    </div>
  );
};

const Cifra = ({ icono, valor, etiqueta }) => (
  <div>
    <div style={{
      display: 'flex', alignItems: 'center', gap: '7px',
      fontSize: '1.5rem', fontWeight: '700', color: 'var(--text-primary)'
    }}>
      <span style={{ color: 'var(--text-muted)' }}>{icono}</span> {valor}
    </div>
    <div style={{ fontSize: '0.79rem', color: 'var(--text-secondary)', marginTop: '2px' }}>
      {etiqueta}
    </div>
  </div>
);

export default EstadoSistema;

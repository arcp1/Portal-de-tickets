import React, { useState, useEffect, createContext, useContext } from 'react';
import { useTranslation } from 'react-i18next';
import api from '../api/client';
import { Moon, Clock } from 'lucide-react';

/**
 * Horario del equipo de TI.
 *
 * Fuera de horario no hay a quién escalar. En vez de dejar al usuario esperando
 * una respuesta que no va a llegar hasta mañana, el portal se lo dice de frente
 * y el asistente se esfuerza más antes de rendirse.
 */
const ContextoHorario = createContext({ esHorarioLaboral: true, cargado: false });

export const useHorario = () => useContext(ContextoHorario);

export const ProveedorHorario = ({ children }) => {
  const [horario, setHorario] = useState({ esHorarioLaboral: true, cargado: false });

  useEffect(() => {
    let cancelado = false;
    const consultar = () => {
      api.get('/estado/horario')
        .then((res) => {
          if (cancelado) return;
          setHorario({
            esHorarioLaboral: res.data.es_horario_laboral,
            proximoInicio: res.data.proximo_inicio,
            horarioInicio: res.data.horario_inicio,
            horarioFin: res.data.horario_fin,
            slaHoras: res.data.sla_horas,
            cargado: true
          });
        })
        // Si no se puede consultar, se asume horario laboral: es el caso que
        // no promete nada raro al usuario.
        .catch(() => { if (!cancelado) setHorario({ esHorarioLaboral: true, cargado: true }); });
    };

    consultar();
    // El turno puede terminar con la pestaña abierta.
    const cada = setInterval(consultar, 5 * 60 * 1000);
    return () => { cancelado = true; clearInterval(cada); };
  }, []);

  return (
    <ContextoHorario.Provider value={horario}>
      {children}
    </ContextoHorario.Provider>
  );
};

/** Formatea "mañana a las 8:00" a partir de un ISO en UTC. */
export const formatearProximoTurno = (iso, idioma) => {
  if (!iso) return null;
  const fecha = new Date(iso);
  const hoy = new Date();
  const mismoDia = fecha.toDateString() === hoy.toDateString();
  const manana = new Date(hoy);
  manana.setDate(manana.getDate() + 1);

  const hora = fecha.toLocaleTimeString(idioma, { hour: '2-digit', minute: '2-digit' });
  if (mismoDia) return hora;
  if (fecha.toDateString() === manana.toDateString()) return `${hora}`;
  return fecha.toLocaleString(idioma, { weekday: 'long', hour: '2-digit', minute: '2-digit' });
};

/** Banda de aviso. Solo aparece fuera de horario. */
const AvisoHorario = ({ compacto = false }) => {
  const { t, i18n } = useTranslation();
  const horario = useHorario();

  if (!horario.cargado || horario.esHorarioLaboral) return null;

  const cuando = formatearProximoTurno(horario.proximoInicio, i18n.language);
  const fecha = horario.proximoInicio ? new Date(horario.proximoInicio) : null;
  const esManana = fecha && fecha.toDateString() !== new Date().toDateString();

  return (
    <div
      className="animate-scale-in"
      style={{
        display: 'flex',
        alignItems: 'flex-start',
        gap: '12px',
        padding: compacto ? '12px 16px' : '16px 20px',
        background: 'var(--status-espera-proveedor-bg)',
        color: 'var(--status-espera-proveedor-text)',
        borderRadius: 'var(--radius-md)',
        marginBottom: '20px',
        fontSize: compacto ? '0.86rem' : '0.92rem',
        lineHeight: 1.5
      }}
      role="status"
    >
      <Moon size={compacto ? 17 : 19} style={{ flexShrink: 0, marginTop: '1px' }} />
      <div>
        <strong>{t('horario.fuera_de_horario')}</strong>{' '}
        {cuando && (
          esManana
            ? t('horario.vuelven_manana', { hora: cuando })
            : t('horario.vuelven_hoy', { hora: cuando })
        )}
        {!compacto && (
          <div style={{ marginTop: '6px', opacity: 0.9 }}>
            {t('horario.mientras_tanto')}
          </div>
        )}
      </div>
    </div>
  );
};

/** Indicador de vencimiento de SLA para una tarjeta de ticket. */
export const EtiquetaSLA = ({ venceEn, estado }) => {
  const { t, i18n } = useTranslation();

  // Un ticket cerrado ya no tiene compromiso pendiente.
  if (!venceEn || ['resuelto', 'cerrado'].includes(estado)) return null;

  const vence = new Date(venceEn);
  const ahora = new Date();
  const minutos = Math.round((vence - ahora) / 60000);
  const vencido = minutos < 0;
  const apurado = !vencido && minutos < 120;

  const [color, fondo] = vencido
    ? ['#D8000C', '#FFF0F0']
    : apurado
      ? ['var(--status-espera-proveedor-text)', 'var(--status-espera-proveedor-bg)']
      : ['var(--text-secondary)', 'var(--bg-tertiary)'];

  const absoluto = Math.abs(minutos);
  const texto = vencido
    ? t('horario.vencido')
    : absoluto < 60
      ? t('horario.vence_en_min', { n: absoluto })
      : absoluto < 60 * 24
        ? t('horario.vence_en_horas', { n: Math.round(absoluto / 60) })
        : t('horario.vence_en_dias', { n: Math.round(absoluto / 1440) });

  return (
    <span
      title={vence.toLocaleString(i18n.language)}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: '5px',
        fontSize: '0.75rem',
        fontWeight: '600',
        padding: '4px 10px',
        borderRadius: 'var(--radius-full)',
        color,
        background: fondo,
        whiteSpace: 'nowrap'
      }}
    >
      <Clock size={13} />
      {texto}
    </span>
  );
};

export default AvisoHorario;

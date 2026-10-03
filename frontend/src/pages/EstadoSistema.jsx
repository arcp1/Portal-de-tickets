import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import api from '../api/client';
import forma from '../lib/forma';
import { EsqueletoLista } from '../components/Cargando';
import {
  Activity, CheckCircle2, XCircle, PauseCircle, KeyRound, RefreshCw,
  Database, Cpu, Sparkles, Clock, Ticket, Users, ShieldCheck
} from 'lucide-react';
import GlassCard from '../components/GlassCard';
import Aviso from '../components/Aviso';

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
  certificado: ShieldCheck,
  ollama: Cpu,
  gemini: Sparkles
};

const ESTADOS = {
  arriba: ['var(--status-resuelto-text)', 'var(--status-resuelto-bg)', CheckCircle2],
  abajo: ['var(--peligro)', 'var(--peligro-bg)', XCircle],
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

  // **Esta pantalla no tenía guarda ninguna.**
  //
  // El `catch` de `cargar` preparaba `estado.error_cargar` y nadie lo pintaba:
  // el render seguía derecho a `datos.servicios.map`, así que ante cualquier
  // fallo del backend —el mismo fallo que esta pantalla existe para enseñar—
  // se caía con «Algo se rompió en esta pantalla». La pantalla que dice si el
  // portal está bien era la que peor aguantaba que no lo estuviera.
  //
  // Se comprueba la forma y no solo el nulo por lo mismo de siempre: un 200
  // con el cuerpo equivocado no lo atrapa el `catch`.
  if (error || !forma(datos, ['servicios', 'horario'], 'el estado del sistema')) {
    return (
      <div className="page-container" style={{ textAlign: 'center', padding: '60px' }}>
        <XCircle size={40} color="var(--text-muted)" style={{ margin: '0 auto 16px' }} />
        <div style={{ color: 'var(--text-secondary)', marginBottom: '18px' }}>
          {error || t('estado.error_cargar')}
        </div>
        <button onClick={cargar} className="btn-secondary" style={{ padding: '10px 18px', fontSize: '0.86rem' }}>
          <RefreshCw size={15} /> {t('estado.actualizar')}
        </button>
      </div>
    );
  }

  return (
    <div className="page-container animate-fade-in">
      <div className="page-header">
        <div>
          <h1 className="page-title">
            {t('estado.title')}
          </h1>
          <p>{t('estado.subtitle')}</p>
        </div>
        <button onClick={cargar} className="btn-secondary" style={{ padding: '10px 16px', fontSize: '0.86rem' }}>
          <RefreshCw size={15} /> {t('estado.actualizar')}
        </button>
      </div>

      {error && <Aviso texto={error} tono="peligro" />}

      {datos && (
        <>
          {/* Titular: si el portal atiende o no. La IA no entra en esta cuenta.
              Va en la tarjeta de cristal con borde eléctrico porque es el
              único dato de esta pantalla que se mira de un vistazo desde
              lejos: el borde lo separa del resto sin subirle el tamaño.
              El tono lleva el estado — azul cuando opera, rosa cuando no. */}
          <GlassCard
            tono={datos.operativo ? 'azul' : 'rosa'}
            girando={!datos.operativo}
            style={{ marginBottom: '20px' }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
              <Activity size={30} color={datos.operativo ? 'var(--status-resuelto-text)' : 'var(--peligro)'} />
              <div>
                <div style={{ fontSize: '1.15rem', fontWeight: '700', color: 'var(--text-primary)' }}>
                  {datos.operativo ? t('estado.operativo') : t('estado.no_operativo')}
                </div>
                <div style={{ fontSize: '0.88rem', color: 'var(--text-secondary)', marginTop: '3px' }}>
                  {datos.operativo ? t('estado.operativo_detalle') : t('estado.no_operativo_detalle')}
                </div>
              </div>
            </div>
          </GlassCard>

          <div style={{
            display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))',
            gap: '16px', marginBottom: '24px'
          }}>
            {datos.servicios.map((s) => <TarjetaServicio key={s.clave} servicio={s} t={t} />)}
          </div>

          <div className="apple-card" style={{ padding: '22px' }}>
            <h2 className="titulo-bloque">
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
                valor={datos.horario.es_horario_laboral ? t('estado.si') : t('estado.no')}
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

  // **El borde solo se enciende cuando hay algo que mirar.**
  // La primera versión lo ponía azul cuando el servicio respondía, y con todo
  // en orden salían cuatro anillos de color iguales: el titular de arriba
  // dejaba de destacar y la pantalla se leía como una fila de cosas
  // importantes, ninguna más que otra. Es la misma regla que rige los colores
  // del portal — el color significa estado— aplicada hasta el final: un
  // servicio que funciona no es noticia, y uno apagado a propósito, tampoco.
  // Solo lo caído se lleva el rosa, y además gira.
  const tonoBorde = servicio.estado === 'abajo' ? 'rosa' : 'neutro';

  return (
    <GlassCard relleno="20px" tono={tonoBorde} girando={servicio.estado === 'abajo'}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '10px' }}>
        <Icono size={18} color="var(--text-secondary)" />
        <strong style={{ color: 'var(--text-primary)', fontSize: '0.95rem', flex: 1 }}>
          {servicio.nombre}
        </strong>
        <span className="chip-dato" style={{ color, background: fondo }}>
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

      {/* **La cola del modelo local.**

          El backend la manda desde siempre —`cola_ia.metricas()` viaja dentro
          de cada servicio— y esta pantalla no la pintaba. Un dato que se
          calcula y no se enseña es un dato perdido, y éste en concreto es el
          que separa dos quejas que desde fuera suenan igual: «el asistente
          tarda» porque el modelo piensa despacio (latencias altas, cola en
          cero) o porque hay tres personas delante (latencias normales, cola
          llena). La primera se arregla con un modelo más chico; la segunda,
          subiendo el aforo o aceptando que esta máquina da lo que da.

          Se enseña solo cuando hay algo que mirar, que es la regla de esta
          pantalla: un servicio ocioso no es noticia. */}
      <ColaDelModelo cola={servicio.cola} t={t} />

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
    </GlassCard>
  );
};

/** La ocupación de la cola de generación, si hay algo que contar.
 *
 * `rechazados_sala` va aparte y con aviso: no es una cifra de ocupación, es
 * **gente que se quedó sin ayuda**. Acumula desde el arranque, así que se
 * enseña aunque ahora mismo no haya nadie esperando.
 */
const ColaDelModelo = ({ cola, t }) => {
  const g = cola?.generacion;
  if (!g) return null;

  const rechazados = (g.rechazados_sala || 0) + (g.rechazados_espera || 0);
  const hayTrafico = (g.en_curso || 0) > 0 || (g.esperando || 0) > 0 || (g.admitidos || 0) > 0;
  if (!hayTrafico && !rechazados) return null;

  const datos = [];
  if (hayTrafico) {
    datos.push(t('estado.cola_en_curso', { n: g.en_curso, aforo: g.aforo }));
    if (g.esperando > 0) datos.push(t('estado.cola_esperando', { n: g.esperando }));
    if (g.espera_estimada_s > 0) {
      datos.push(t('estado.cola_espera', { s: Math.round(g.espera_estimada_s) }));
    }
    if (g.admitidos > 0) datos.push(t('estado.cola_atendidas', { n: g.admitidos }));
  }

  return (
    <div style={{ marginBottom: '10px' }}>
      {datos.length > 0 && (
        <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap', marginBottom: rechazados ? '8px' : 0 }}>
          <span style={{ fontSize: '0.76rem', color: 'var(--text-muted)' }}>
            {t('estado.cola_titulo')}:
          </span>
          {datos.map((d, i) => (
            <span key={i} style={{ fontSize: '0.76rem', color: 'var(--text-secondary)' }}>{d}</span>
          ))}
        </div>
      )}

      {/* El color dice lo mismo que la cifra: esto no es información, es un
          problema. */}
      {rechazados > 0 && (
        <div style={{
          display: 'flex', alignItems: 'flex-start', gap: '8px',
          fontSize: '0.78rem', lineHeight: 1.5, padding: '9px 11px',
          borderRadius: 'var(--radius-sm)',
          background: 'var(--status-espera-proveedor-bg)',
          color: 'var(--status-espera-proveedor-text)'
        }}>
          <PauseCircle size={14} style={{ flexShrink: 0, marginTop: '2px' }} />
          <span>{t('estado.cola_rechazados', { n: rechazados })}</span>
        </div>
      )}
    </div>
  );
};

const Cifra = ({ icono, valor, etiqueta }) => (
  <div>
    <div className="cifra-actividad-valor">
      <span>{icono}</span> {valor}
    </div>
    <div className="cifra-actividad-etiqueta">{etiqueta}</div>
  </div>
);

export default EstadoSistema;

import React, { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Factory, Plus, Pencil, X, Check, Users, Laptop, Ticket } from 'lucide-react';
import api from '../api/client';
import lista from '../lib/lista';
import { olvidarPlantas } from '../lib/plantas';
import { mensajeDeError } from '../lib/avisos';
import { EsqueletoLista } from '../components/Cargando';
import CapaModal from '../components/CapaModal';
import Formulario from '../components/Formulario';
import Aviso from '../components/Aviso';

/**
 * Las plantas de la empresa. Solo TI, que es global.
 *
 * **La clave no se edita**: va dentro de cada folio (TICK-QRO-2026-0001), y
 * cambiarla dejaría los folios viejos con una clave que ya no existe. Una
 * planta que cierra se desactiva —deja de ofrecerse al levantar tickets— pero
 * no se borra: sus tickets y sus equipos siguen siendo historia.
 */
export default function Plantas() {
  const { t } = useTranslation();
  const [plantas, setPlantas] = useState([]);
  const [cargando, setCargando] = useState(true);
  const [aviso, setAviso] = useState('');
  const [editando, setEditando] = useState(null);

  const cargar = async () => {
    try {
      const res = await api.get('/sitios/admin');
      setPlantas(lista(res.data, 'las plantas'));
      setAviso('');
    } catch (err) {
      setAviso(mensajeDeError(err, t('plantas.error_cargar')));
    } finally {
      setCargando(false);
    }
  };

  useEffect(() => { cargar(); }, []);

  const guardado = () => {
    setEditando(null);
    olvidarPlantas();
    cargar();
  };

  return (
    <div className="page-container animate-fade-in">
      <div className="page-header">
        <div>
          <h1 className="page-title">{t('plantas.titulo')}</h1>
          <p style={{ color: 'var(--text-secondary)', marginTop: '4px' }}>{t('plantas.subtitulo')}</p>
        </div>
        <button type="button" className="btn-acento" onClick={() => setEditando({})}>
          <Plus size={18} /> {t('plantas.nueva')}
        </button>
      </div>

      <Aviso texto={aviso} />

      {cargando ? <EsqueletoLista filas={2} /> : (
        <div className="iot-rejilla">
          {plantas.map((p) => (
            <div key={p.id} className={`apple-card planta-tarjeta${p.activo ? '' : ' planta-tarjeta--inactiva'}`}>
              <div className="iot-tarjeta-cabeza">
                <Factory size={18} aria-hidden="true" style={{ color: 'var(--accent-primary)' }} />
                <strong className="iot-nombre">{p.nombre}</strong>
                <span className="chip-dato chip-planta">{p.clave}</span>
                {!p.activo && <span className="chip-dato">{t('plantas.inactiva')}</span>}
              </div>
              <div className="iot-tarjeta-sub"><span>{p.pais}</span></div>
              <div className="planta-cifras">
                <span title={t('plantas.personas')}><Users size={14} /> {p.personas}</span>
                <span title={t('plantas.equipos')}><Laptop size={14} /> {p.equipos}</span>
                <span title={t('plantas.abiertos')}><Ticket size={14} /> {p.tickets_abiertos}</span>
              </div>
              <button type="button" className="btn-secondary" onClick={() => setEditando(p)}
                style={{ padding: '8px 12px', alignSelf: 'flex-start' }}>
                <Pencil size={14} /> {t('plantas.editar')}
              </button>
            </div>
          ))}
        </div>
      )}

      {editando && (
        <EditarPlanta planta={editando} onCerrar={() => setEditando(null)} onGuardado={guardado} />
      )}
    </div>
  );
}

function EditarPlanta({ planta, onCerrar, onGuardado }) {
  const { t } = useTranslation();
  const nueva = !planta.id;
  const [clave, setClave] = useState(planta.clave || '');
  const [nombre, setNombre] = useState(planta.nombre || '');
  const [pais, setPais] = useState(planta.pais || 'México');
  const [activo, setActivo] = useState(planta.activo ?? true);
  const [aviso, setAviso] = useState('');
  const [enviando, setEnviando] = useState(false);

  const guardar = async (e) => {
    e.preventDefault();
    setEnviando(true);
    setAviso('');
    try {
      if (nueva) {
        await api.post('/sitios', { clave: clave.trim().toUpperCase(), nombre: nombre.trim(), pais: pais.trim() });
      } else {
        await api.patch(`/sitios/${planta.id}`, { nombre: nombre.trim(), pais: pais.trim(), activo });
      }
      onGuardado();
    } catch (err) {
      setAviso(mensajeDeError(err, t('plantas.error_guardar')));
      setEnviando(false);
    }
  };

  return (
    <CapaModal onCerrar={onCerrar} etiqueta={nueva ? t('plantas.nueva') : t('plantas.editar')}>
      <Formulario onSubmit={guardar} className="apple-card animate-scale-in"
        onClick={(e) => e.stopPropagation()}
        style={{ width: '100%', maxWidth: '460px', padding: '28px' }}>
        <h2 style={{ fontSize: '1.25rem', fontWeight: 700, marginBottom: '18px', color: 'var(--text-primary)' }}>
          {nueva ? t('plantas.nueva') : t('plantas.editar')}
        </h2>
        <div className="form-group">
          <label htmlFor="planta-clave">{t('plantas.clave')}</label>
          <input id="planta-clave" className="form-input" required minLength={2} maxLength={10}
            pattern="[A-Za-z0-9]+" disabled={!nueva} value={clave}
            onChange={(e) => setClave(e.target.value.toUpperCase())} placeholder="MTY" />
          <p className="nota-suave">{t('plantas.clave_ayuda')}</p>
        </div>
        <div className="form-group">
          <label htmlFor="planta-nombre">{t('plantas.nombre')}</label>
          <input id="planta-nombre" className="form-input" required minLength={3} maxLength={100}
            value={nombre} onChange={(e) => setNombre(e.target.value)} placeholder={t('plantas.nombre_ejemplo')} />
        </div>
        <div className="form-group">
          <label htmlFor="planta-pais">{t('plantas.pais')}</label>
          <input id="planta-pais" className="form-input" required minLength={2} maxLength={50}
            value={pais} onChange={(e) => setPais(e.target.value)} />
        </div>
        {!nueva && (
          <>
            <label className="interruptor">
              <input type="checkbox" checked={activo} onChange={(e) => setActivo(e.target.checked)} />
              {t('plantas.activa')}
            </label>
            <p className="nota-suave">{t('plantas.activa_ayuda')}</p>
          </>
        )}
        <Aviso texto={aviso} />
        <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end', marginTop: '18px' }}>
          <button type="button" onClick={onCerrar} className="btn-secondary"><X size={15} /> {t('temas.cancelar')}</button>
          <button type="submit" className="btn-acento" disabled={enviando}>
            <Check size={15} /> {enviando ? t('temas.guardando') : t('temas.guardar')}
          </button>
        </div>
      </Formulario>
    </CapaModal>
  );
}

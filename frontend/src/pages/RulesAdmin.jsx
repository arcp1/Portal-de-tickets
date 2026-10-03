import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import api from '../api/client';
import { useAuth } from '../context/AuthContext';
import { Plus, Trash2, X } from 'lucide-react';
import CapaModal from '../components/CapaModal';
import Confirmacion from '../components/Confirmacion';
import Selector from '../components/Selector';
import Formulario from '../components/Formulario';
import EstadoVacio from '../components/EstadoVacio';
import { EsqueletoLista } from '../components/Cargando';
import Aviso from '../components/Aviso';
import lista from '../lib/lista';
import { usePlantas, SelectorPlanta, EtiquetaPlanta } from '../lib/plantas';

const RulesAdmin = () => {
  const { t } = useTranslation();
  const { user } = useAuth();

  const [reglas, setReglas] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showModal, setShowModal] = useState(false);
  const [guardando, setGuardando] = useState(false);
  const [aviso, setAviso] = useState('');
  // **El diálogo tiene su propio aviso.** Compartía el de la página, que se
  // pinta detrás de la capa del diálogo: un 422 al guardar —o el "falta el
  // destinatario" de aquí mismo— quedaba tapado, el diálogo seguía abierto
  // sin decir nada y "Guardar regla" parecía no hacer nada.
  const [avisoForm, setAvisoForm] = useState('');
  // La regla que espera el "¿seguro?". null = no hay pregunta abierta.
  const [porEliminar, setPorEliminar] = useState(null);

  const FORMULARIO_VACIO = {
    categoria: 'impresora',
    condicion: '',
    accion: 'proveedor',
    destinatario: '',
    // Cada regla es de una planta: decide el trato de los tickets de esa.
    sitio_id: null
  };
  const [plantas] = usePlantas();
  const variasPlantas = plantas.length > 1;
  const nombreDePlanta = (id) => plantas.find((p) => p.id === id);

  const [formData, setFormData] = useState(FORMULARIO_VACIO);

  useEffect(() => {
    fetchReglas();
  }, []);

  const fetchReglas = async () => {
    try {
      const res = await api.get('/reglas');
      setReglas(lista(res.data, 'las reglas'));
      setAviso('');
    } catch (err) {
      setAviso(err.response?.data?.detail || t('reglas.error_cargar'));
    } finally {
      setLoading(false);
    }
  };

  const abrirAlta = () => {
    setFormData(FORMULARIO_VACIO);
    setAvisoForm('');
    setShowModal(true);
  };

  const handleCreate = async (e) => {
    e.preventDefault();
    if (guardando) return;
    // "Enrutar a proveedor" sin correo no avisa a nadie: se pide antes de guardar.
    // Unos espacios pasan el `required` del navegador y llegaban como una
    // condición vacía; el backend la rechaza, pero con el nombre del campo.
    if (!formData.condicion.trim()) {
      setAvisoForm(t('reglas.falta_condicion'));
      return;
    }
    if (formData.accion === 'proveedor' && !formData.destinatario.trim()) {
      setAvisoForm(t('reglas.falta_destinatario'));
      return;
    }
    setGuardando(true);
    setAvisoForm('');
    try {
      await api.post('/reglas', {
        ...formData,
        condicion: formData.condicion.trim(),
        destinatario: formData.destinatario.trim() || null,
        sitio_id: formData.sitio_id || null,
        activa: true
      });
      setShowModal(false);
      setFormData(FORMULARIO_VACIO);
      fetchReglas();
    } catch (err) {
      // Antes solo iba a la consola: el boton "Guardar Regla" parecia muerto.
      setAvisoForm(err.response?.data?.detail || t('reglas.error_guardar'));
    } finally {
      setGuardando(false);
    }
  };

  const handleDelete = async (regla) => {
    setPorEliminar(null);
    try {
      await api.delete(`/reglas/${regla.id}`);
      fetchReglas();
    } catch (err) {
      setAviso(err.response?.data?.detail || t('reglas.error_borrar'));
    }
  };

  return (
    <div className="page-container animate-fade-in">
      <div className="page-header">
        <div>
          <h1 className="page-title">
            {t('reglas.title')}
          </h1>
          <p style={{ color: 'var(--text-secondary)', fontSize: '1rem', marginTop: '4px' }}>
            {t('reglas.subtitle')}
            {' · '}{t('plantas.ti_global')}
          </p>
        </div>

        <button onClick={abrirAlta} className="btn-acento">
          <Plus size={18} />
          {t('reglas.nueva')}
        </button>
      </div>

      <Aviso texto={aviso} />

      {loading ? (
        <EsqueletoLista filas={3} />
      ) : reglas.length === 0 ? (
        <EstadoVacio texto={t('reglas.vacio')} />
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          {reglas.map((r) => (
            <div key={r.id} className="apple-card" style={{ padding: '20px 24px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '8px' }}>
                  {variasPlantas && <EtiquetaPlanta planta={nombreDePlanta(r.sitio_id)} compacta />}
                  <span className="chip-dato" style={{ textTransform: 'uppercase', background: 'var(--status-espera-proveedor-bg)', color: 'var(--status-espera-proveedor-text)' }}>
                    {t(`new_ticket.category_${r.categoria}`, { defaultValue: r.categoria })}
                  </span>
                  <span style={{ fontWeight: '600', color: 'var(--text-primary)', fontSize: '1.05rem' }}>
                    {t('reglas.muestra_condicion', { condicion: r.condicion })}
                  </span>
                </div>
                <div style={{ fontSize: '0.95rem', color: 'var(--text-secondary)' }}>
                  {t('reglas.muestra_accion')}{' '}
                  <strong style={{ color: 'var(--text-primary)'}}>{t(`reglas.accion_${r.accion}`, { defaultValue: r.accion })}</strong>
                  {' → '}{r.destinatario || t('reglas.asignacion_estandar')}
                </div>
              </div>

              <button 
                onClick={() => setPorEliminar(r)} 
                className="btn-secondary btn-secondary--peligro"
                style={{ padding: '10px' }}
              >
                <Trash2 size={18} />
              </button>
            </div>
          ))}
        </div>
      )}

      {showModal && (
        <CapaModal>
          <div className="apple-card" style={{ width: '100%', maxWidth: '500px', padding: '32px', position: 'relative' }}>
            <button 
              onClick={() => setShowModal(false)}
              style={{ position: 'absolute', top: '24px', right: '24px', background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-muted)' }}
            >
              <X size={24} />
            </button>
            
            <h2 style={{ fontSize: '1.4rem', fontWeight: '700', marginBottom: '24px', color: 'var(--text-primary)' }}>
              {t('reglas.crear_titulo')}
            </h2>
            <Formulario onSubmit={handleCreate}>
              {variasPlantas && (
                <div className="form-group">
                  <label htmlFor="planta-regla">{t('plantas.planta')}</label>
                  <SelectorPlanta id="planta-regla" plantas={plantas} value={formData.sitio_id}
                    onChange={(v) => setFormData({ ...formData, sitio_id: v })} required />
                </div>
              )}
              <div className="form-group">
                <label>{t('reglas.categoria')}</label>
                <Selector
                  className="form-select"
                  value={formData.categoria}
                  onChange={(e) => setFormData({ ...formData, categoria: e.target.value })}
                >
                  <option value="impresora">{t('new_ticket.category_impresora')}</option>
                  <option value="red">{t('new_ticket.category_red')}</option>
                  <option value="equipo">{t('new_ticket.category_equipo')}</option>
                  <option value="software">{t('new_ticket.category_software')}</option>
                  <option value="accesos">{t('new_ticket.category_accesos')}</option>
                </Selector>
              </div>

              <div className="form-group">
                <label>{t('reglas.condicion')}</label>
                <input
                  type="text"
                  className="form-input"
                  required
                  placeholder={t('reglas.condicion_ejemplo')}
                  value={formData.condicion}
                  onChange={(e) => setFormData({ ...formData, condicion: e.target.value })}
                />
              </div>

              <div className="form-group">
                <label>{t('reglas.accion')}</label>
                <Selector
                  className="form-select"
                  value={formData.accion}
                  onChange={(e) => setFormData({ ...formData, accion: e.target.value })}
                >
                  <option value="proveedor">{t('reglas.accion_proveedor')}</option>
                  <option value="escalar">{t('reglas.accion_escalar')}</option>
                  <option value="auto">{t('reglas.accion_auto')}</option>
                </Selector>
              </div>

              <div className="form-group">
                <label>{t('reglas.destinatario')}</label>
                <input
                  type="text"
                  className="form-input"
                  placeholder={t('reglas.destinatario_ejemplo')}
                  value={formData.destinatario}
                  onChange={(e) => setFormData({ ...formData, destinatario: e.target.value })}
                />
              </div>

              <Aviso texto={avisoForm} />

              <div style={{ display: 'flex', gap: '12px', marginTop: avisoForm ? '16px' : '32px' }}>
                <button type="button" onClick={() => setShowModal(false)} className="btn-secondary" style={{ flex: 1 }}>
                  {t('comun.cancelar')}
                </button>
                <button type="submit" className="btn-acento" disabled={guardando}
                  style={{ flex: 1, justifyContent: 'center' }}>
                  {guardando ? t('temas.guardando') : t('reglas.guardar')}
                </button>
              </div>
            </Formulario>
          </div>
        </CapaModal>
      )}

      {porEliminar && (
        <Confirmacion
          titulo={t('reglas.muestra_condicion', { condicion: porEliminar.condicion })}
          mensaje={t('reglas.confirmar_borrar')}
          textoConfirmar={t('comun.eliminar')}
          tono="peligro"
          onConfirmar={() => handleDelete(porEliminar)}
          onCancelar={() => setPorEliminar(null)}
        />
      )}
    </div>
  );
};

export default RulesAdmin;

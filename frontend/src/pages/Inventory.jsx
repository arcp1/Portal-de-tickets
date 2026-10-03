import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import api from '../api/client';
import { useAuth } from '../context/AuthContext';
import { Laptop, Plus, Tag, MapPin, User, Pencil, X, QrCode } from 'lucide-react';
import CapaModal from '../components/CapaModal';
import Selector from '../components/Selector';
import Formulario from '../components/Formulario';
import Aviso from '../components/Aviso';
import lista from '../lib/lista';
import EtiquetaQR from '../components/EtiquetaQR';
import { usePlantas, SelectorPlanta, EtiquetaPlanta } from '../lib/plantas';

// Estado del equipo. Debe coincidir con lo que acepta el backend.
const ESTADOS = ['disponible', 'asignado', 'mantenimiento', 'baja'];

const FORMULARIO_VACIO = {
  tipo: 'activo',
  // Vacía, no "Laptop": el campo es obligatorio y el ejemplo ya va en el
  // marcador. Con un valor puesto, cada alta en la que no se tocaba el campo
  // quedaba registrada como laptop.
  categoria: '',
  marca: '',
  modelo: '',
  numero_serie: '',
  ubicacion: '',
  estado: 'disponible',
  asignado_a: '',
  notas: '',
  // La planta del equipo. TI es global: con varias plantas tiene que decir
  // en cuál; con una sola, el backend usa esa.
  sitio_id: null
};

const Inventory = () => {
  const { t } = useTranslation();
  const { user } = useAuth();

  const [equipos, setEquipos] = useState([]);
  const [usuarios, setUsuarios] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showModal, setShowModal] = useState(false);
  // id del equipo que se esta editando; null = alta nueva.
  const [editandoId, setEditandoId] = useState(null);
  const [guardando, setGuardando] = useState(false);
  const [aviso, setAviso] = useState('');
  // **El error de guardar va junto al botón, y solo dentro del diálogo.**
  // Compartía el aviso de la página: salía arriba del diálogo —que tiene
  // scroll, y quien acaba de pulsar Guardar está abajo— y otra vez detrás de
  // la capa. El botón parecía no hacer nada.
  const [avisoForm, setAvisoForm] = useState('');

  const [formData, setFormData] = useState(FORMULARIO_VACIO);
  // El equipo cuya etiqueta QR se está mirando.
  const [qrDe, setQrDe] = useState(null);
  const [plantas] = usePlantas();
  const variasPlantas = plantas.length > 1;
  // Para quien ve más de una planta, qué inventario: todas o una.
  const [plantaFiltro, setPlantaFiltro] = useState(null);

  const esAdmin = user.rol === 'admin';

  useEffect(() => {
    fetchEquipos();
    // Para poder asignar el equipo a alguien. Solo admin puede leer el padron.
    if (esAdmin) {
      api.get('/auth/usuarios').then((r) => setUsuarios(lista(r.data, 'los usuarios'))).catch(() => setUsuarios([]));
    }
  }, []);

  const fetchEquipos = async () => {
    try {
      const res = await api.get('/equipos');
      setEquipos(lista(res.data, 'el inventario'));
      setAviso('');
    } catch (err) {
      setAviso(err.response?.data?.detail || t('inventory.error_cargar'));
    } finally {
      setLoading(false);
    }
  };

  const abrirAlta = () => {
    // Se limpia siempre: reabrir el modal traia los datos del equipo anterior.
    setFormData(FORMULARIO_VACIO);
    setEditandoId(null);
    setAvisoForm('');
    setShowModal(true);
  };

  const abrirEdicion = (eq) => {
    setFormData({
      tipo: eq.tipo,
      categoria: eq.categoria,
      marca: eq.marca,
      modelo: eq.modelo,
      numero_serie: eq.numero_serie || '',
      ubicacion: eq.ubicacion || '',
      estado: eq.estado,
      asignado_a: eq.asignado_a ? String(eq.asignado_a) : '',
      notas: eq.notas || '',
      sitio_id: eq.sitio?.id ?? null
    });
    setEditandoId(eq.id);
    setAvisoForm('');
    setShowModal(true);
  };

  const cerrarModal = () => {
    setShowModal(false);
    setEditandoId(null);
    setFormData(FORMULARIO_VACIO);
  };

  const handleCreate = async (e) => {
    e.preventDefault();
    if (guardando) return;
    setGuardando(true);
    setAvisoForm('');
    try {
      const cuerpo = {
        ...formData,
        numero_serie: formData.numero_serie.trim() || null,
        ubicacion: formData.ubicacion.trim() || null,
        notas: formData.notas.trim() || null,
        asignado_a: formData.asignado_a ? parseInt(formData.asignado_a, 10) : null,
        sitio_id: formData.sitio_id || null
      };
      let guardado;
      if (editandoId) {
        guardado = (await api.patch(`/equipos/${editandoId}`, cuerpo)).data;
      } else {
        guardado = (await api.post('/equipos', cuerpo)).data;
      }
      cerrarModal();
      fetchEquipos();
      // «Guardar y generar QR»: la etiqueta del equipo recién guardado.
      if (e.nativeEvent?.submitter?.dataset?.qr === '1' && guardado?.id) setQrDe(guardado);
    } catch (err) {
      // Antes esto solo iba a la consola: el boton parecia no hacer nada.
      setAvisoForm(err.response?.data?.detail || t('inventory.error_guardar'));
    } finally {
      setGuardando(false);
    }
  };

  return (
    <div className="page-container animate-fade-in">
      <div className="page-header">
        <div>
          <h1 className="page-title">{t('inventory.title')}</h1>
          <p style={{ color: 'var(--text-secondary)', fontSize: '1rem', marginTop: '4px' }}>
            {t('inventory.subtitle')}
          </p>
        </div>

        {esAdmin && (
          <button onClick={abrirAlta} className="btn-primary">
            <Plus size={18} />
            {t('inventory.add_btn')}
          </button>
        )}
      </div>

      <Aviso texto={aviso} />

      {variasPlantas && (
        <div className="barra-herramientas" style={{ marginBottom: '20px' }}>
          <SelectorPlanta
            todas
            plantas={plantas}
            value={plantaFiltro}
            onChange={setPlantaFiltro}
            style={{ minWidth: '240px' }}
          />
        </div>
      )}

      {loading ? (
        <div style={{ textAlign: 'center', padding: '60px', color: 'var(--text-muted)' }}>{t('inventory.cargando')}</div>
      ) : equipos.length === 0 ? (
        <div className="apple-card" style={{ padding: '48px', textAlign: 'center', color: 'var(--text-muted)' }}>
          {t('inventory.vacio')}
        </div>
      ) : (
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))',
          gap: '24px'
        }}>
          {equipos.filter((eq) => !plantaFiltro || eq.sitio?.id === plantaFiltro).map((eq) => (
            <div key={eq.id} className="apple-card" style={{ padding: '24px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '16px' }}>
                <div>
                  <span className="chip-dato" style={{ textTransform: 'uppercase', background: eq.tipo === 'activo' ? 'var(--status-abierto-bg)' : 'var(--status-espera-proveedor-bg)', color: eq.tipo === 'activo' ? 'var(--accent-primary)' : 'var(--status-espera-proveedor-text)', marginBottom: '8px' }}>
                    {eq.tipo}
                  </span>
                  <h3 style={{ fontSize: '1.15rem', fontWeight: '700', color: 'var(--text-primary)' }}>
                    {eq.marca} {eq.modelo}
                  </h3>
                  <div style={{ fontSize: '0.9rem', color: 'var(--text-secondary)' }}>
                    {eq.categoria}
                  </div>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  {esAdmin && (
                    <button onClick={() => setQrDe(eq)} className="btn-secondary"
                      style={{ padding: '9px 12px' }} title={t('qr.generar')}
                      aria-label={t('qr.generar')}>
                      <QrCode size={15} />
                    </button>
                  )}
                  {esAdmin && (
                    <button onClick={() => abrirEdicion(eq)} className="btn-secondary"
                      style={{ padding: '9px 12px' }} title={t('inventory.editar')}>
                      <Pencil size={15} />
                    </button>
                  )}
                  <div style={{ background: 'var(--bg-tertiary)', padding: '10px', borderRadius: '12px' }}>
                    <Laptop size={22} style={{ color: 'var(--accent-primary)' }} />
                  </div>
                </div>
              </div>

              <div style={{ marginBottom: '12px', display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                {(esAdmin || variasPlantas) && <EtiquetaPlanta planta={eq.sitio} />}
                <span className="chip-dato" style={{ color: eq.estado === 'disponible' ? 'var(--status-resuelto-text)' : 'var(--text-secondary)', background: eq.estado === 'disponible' ? 'var(--status-resuelto-bg)' : 'var(--bg-tertiary)' }}>
                  {t(`inventory.estado_${eq.estado}`, { defaultValue: eq.estado })}
                </span>
              </div>

              <div style={{ fontSize: '0.9rem', color: 'var(--text-secondary)', display: 'flex', flexDirection: 'column', gap: '8px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <Tag size={16} style={{ color: 'var(--text-muted)'}}/>
                  <span><strong>{t('inventory.serial')}:</strong> {eq.numero_serie || t('inventory.sin_serie')}</span>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <MapPin size={16} style={{ color: 'var(--text-muted)'}}/>
                  <span><strong>{t('inventory.location')}:</strong> {eq.ubicacion || t('inventory.planta_general')}</span>
                </div>
                {eq.asignado_usuario && (
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: 'var(--accent-primary)', fontWeight: '500', marginTop: '4px' }}>
                    <User size={16} />
                    <span><strong>{t('inventory.assigned')}:</strong> {eq.asignado_usuario.nombre}</span>
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Modal create equipment */}
      {showModal && (
        <CapaModal>
          <div className="apple-card" style={{
            width: '100%', maxWidth: '500px', padding: '32px', position: 'relative',
            // Con los campos de estado, responsable y notas el formulario ya no
            // cabe en una pantalla corta.
            maxHeight: '90vh', overflowY: 'auto'
          }}>
            <button
              onClick={cerrarModal}
              style={{ position: 'absolute', top: '24px', right: '24px', background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-muted)' }}
            >
              <X size={24} />
            </button>
            <h2 style={{ fontSize: '1.4rem', fontWeight: '700', marginBottom: '24px', color: 'var(--text-primary)' }}>
              {editandoId ? t('inventory.editar_titulo') : t('inventory.alta_titulo')}
            </h2>

            <Formulario onSubmit={handleCreate}>
              {esAdmin && variasPlantas && (
                <div className="form-group">
                  <label htmlFor="planta-equipo">{t('plantas.planta')}</label>
                  <SelectorPlanta
                    id="planta-equipo"
                    plantas={plantas}
                    value={formData.sitio_id}
                    onChange={(v) => setFormData({ ...formData, sitio_id: v, asignado_a: '' })}
                    required
                  />
                </div>
              )}

              <div className="form-group">
                <label>{t('inventory.tipo_elemento')}</label>
                <Selector
                  className="form-select"
                  value={formData.tipo}
                  onChange={(e) => setFormData({ ...formData, tipo: e.target.value })}
                >
                  <option value="activo">{t('inventory.tipo_activo_op')}</option>
                  <option value="pasivo">{t('inventory.tipo_pasivo_op')}</option>
                  <option value="consumible">{t('inventory.tipo_consumible_op')}</option>
                </Selector>
              </div>

              <div className="form-group">
                <label>{t('inventory.categoria')}</label>
                <input
                  type="text"
                  className="form-input"
                  required
                  placeholder={t('inventory.categoria_ejemplo')}
                  value={formData.categoria}
                  onChange={(e) => setFormData({ ...formData, categoria: e.target.value })}
                />
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
                <div className="form-group">
                  <label>{t('inventory.marca')}</label>
                  <input
                    type="text"
                    className="form-input"
                    required
                    placeholder={t('inventory.marca_ejemplo')}
                    value={formData.marca}
                    onChange={(e) => setFormData({ ...formData, marca: e.target.value })}
                  />
                </div>
                <div className="form-group">
                  <label>{t('inventory.modelo')}</label>
                  <input
                    type="text"
                    className="form-input"
                    required
                    placeholder={t('inventory.modelo_ejemplo')}
                    value={formData.modelo}
                    onChange={(e) => setFormData({ ...formData, modelo: e.target.value })}
                  />
                </div>
              </div>

              <div className="form-group">
                <label>{t('inventory.numero_serie')}</label>
                <input
                  type="text"
                  className="form-input"
                  placeholder={t('inventory.numero_serie_ejemplo')}
                  value={formData.numero_serie}
                  onChange={(e) => setFormData({ ...formData, numero_serie: e.target.value })}
                />
              </div>

              <div className="form-group">
                <label>{t('inventory.ubicacion_planta')}</label>
                <input
                  type="text"
                  className="form-input"
                  placeholder={t('inventory.ubicacion_ejemplo')}
                  value={formData.ubicacion}
                  onChange={(e) => setFormData({ ...formData, ubicacion: e.target.value })}
                />
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
                <div className="form-group">
                  <label>{t('inventory.estado')}</label>
                  <Selector
                    className="form-select"
                    value={formData.estado}
                    onChange={(e) => setFormData({ ...formData, estado: e.target.value })}
                  >
                    {ESTADOS.map((es) => (
                      <option key={es} value={es}>
                        {t(`inventory.estado_${es}`, { defaultValue: es })}
                      </option>
                    ))}
                  </Selector>
                </div>
                <div className="form-group">
                  <label>{t('inventory.asignado_a')}</label>
                  <Selector
                    className="form-select"
                    value={formData.asignado_a}
                    onChange={(e) => setFormData({ ...formData, asignado_a: e.target.value })}
                  >
                    <option value="">{t('inventory.sin_asignar')}</option>
                    {/* Solo quien trabaja en la planta del equipo —o TI, que
                        es de todas—: el backend rechaza a los demás. */}
                    {usuarios.filter((u) => !formData.sitio_id || u.rol === 'admin'
                      || (u.plantas || []).some((p) => p.id === formData.sitio_id)
                      || u.sitio_id === formData.sitio_id).map((u) => (
                      <option key={u.id} value={u.id}>
                        {u.nombre}{u.numero_empleado ? ` · ${u.numero_empleado}` : ''}
                      </option>
                    ))}
                  </Selector>
                </div>
              </div>

              {/* Estaba en el estado del formulario pero no tenia campo: lo que
                  se escribiera aqui nunca llegaba a guardarse. */}
              <div className="form-group">
                <label>{t('inventory.notas')}</label>
                <textarea
                  className="form-textarea"
                  rows={2}
                  placeholder={t('inventory.notas_ejemplo')}
                  value={formData.notas}
                  onChange={(e) => setFormData({ ...formData, notas: e.target.value })}
                />
              </div>

              <Aviso texto={avisoForm} />

              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '12px', marginTop: avisoForm ? '16px' : '32px' }}>
                <button type="button" onClick={cerrarModal} className="btn-secondary" style={{ flex: 1 }}>
                  {t('temas.cancelar')}
                </button>
                <button type="submit" className="btn-primary" disabled={guardando}
                  style={{ flex: 1, justifyContent: 'center' }}>
                  {guardando ? t('temas.guardando') : t('temas.guardar')}
                </button>
                {/* Guarda y abre la etiqueta: en el alta es el momento en que
                    el equipo está en la mano para pegársela. */}
                <button type="submit" data-qr="1" className="btn-secondary" disabled={guardando}
                  style={{ flexBasis: '100%', justifyContent: 'center' }}>
                  <QrCode size={16} /> {t('qr.guardar_y_generar')}
                </button>
              </div>
            </Formulario>
          </div>
        </CapaModal>
      )}

      {qrDe && <EtiquetaQR equipo={qrDe} onCerrar={() => setQrDe(null)} />}
    </div>
  );
};

export default Inventory;

import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import api from '../api/client';
import { useAuth } from '../context/AuthContext';
import { Laptop, Plus, Tag, MapPin, User, CheckCircle, X } from 'lucide-react';

const Inventory = () => {
  const { t } = useTranslation();
  const { user } = useAuth();

  const [equipos, setEquipos] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showModal, setShowModal] = useState(false);

  const [formData, setFormData] = useState({
    tipo: 'activo',
    categoria: 'Laptop',
    marca: '',
    modelo: '',
    numero_serie: '',
    ubicacion: '',
    notas: ''
  });

  useEffect(() => {
    fetchEquipos();
  }, []);

  const fetchEquipos = async () => {
    try {
      const res = await api.get('/equipos');
      setEquipos(res.data);
    } catch (err) {
      console.error("Error loading equipos", err);
    } finally {
      setLoading(false);
    }
  };

  const handleCreate = async (e) => {
    e.preventDefault();
    try {
      await api.post('/equipos', {
        ...formData,
        sitio_id: user.sitio_id
      });
      setShowModal(false);
      fetchEquipos();
    } catch (err) {
      console.error("Error creating equipo", err);
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

        {user.rol === 'admin' && (
          <button onClick={() => setShowModal(true)} className="btn-primary">
            <Plus size={18} />
            {t('inventory.add_btn')}
          </button>
        )}
      </div>

      {loading ? (
        <div style={{ textAlign: 'center', padding: '60px', color: 'var(--text-muted)' }}>Cargando inventario...</div>
      ) : (
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))',
          gap: '24px'
        }}>
          {equipos.map((eq) => (
            <div key={eq.id} className="apple-card" style={{ padding: '24px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '16px' }}>
                <div>
                  <span style={{
                    fontSize: '0.75rem',
                    fontWeight: '700',
                    textTransform: 'uppercase',
                    padding: '4px 10px',
                    borderRadius: 'var(--radius-full)',
                    background: eq.tipo === 'activo' ? '#E5F0FF' : '#FFF5CC',
                    color: eq.tipo === 'activo' ? 'var(--accent-primary)' : '#B28600',
                    display: 'inline-block',
                    marginBottom: '8px'
                  }}>
                    {eq.tipo}
                  </span>
                  <h3 style={{ fontSize: '1.15rem', fontWeight: '700', color: 'var(--text-primary)' }}>
                    {eq.marca} {eq.modelo}
                  </h3>
                  <div style={{ fontSize: '0.9rem', color: 'var(--text-secondary)' }}>
                    {eq.categoria}
                  </div>
                </div>
                <div style={{ background: 'var(--bg-tertiary)', padding: '10px', borderRadius: '12px' }}>
                  <Laptop size={22} style={{ color: 'var(--accent-primary)' }} />
                </div>
              </div>

              <div style={{ fontSize: '0.9rem', color: 'var(--text-secondary)', display: 'flex', flexDirection: 'column', gap: '8px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <Tag size={16} style={{ color: 'var(--text-muted)'}}/>
                  <span><strong>S/N:</strong> {eq.numero_serie || 'N/A'}</span>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <MapPin size={16} style={{ color: 'var(--text-muted)'}}/>
                  <span><strong>Ubicación:</strong> {eq.ubicacion || 'Planta General'}</span>
                </div>
                {eq.asignado_usuario && (
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: 'var(--accent-primary)', fontWeight: '500', marginTop: '4px' }}>
                    <User size={16} />
                    <span><strong>Asignado a:</strong> {eq.asignado_usuario.nombre}</span>
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Modal create equipment */}
      {showModal && (
        <div style={{
          position: 'fixed',
          top: 0, left: 0, right: 0, bottom: 0,
          background: 'rgba(0,0,0,0.4)',
          backdropFilter: 'blur(4px)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          zIndex: 200,
          padding: '20px'
        }} className="animate-fade-in">
          <div className="apple-card" style={{ width: '100%', maxWidth: '500px', padding: '32px', position: 'relative' }}>
            <button 
              onClick={() => setShowModal(false)}
              style={{ position: 'absolute', top: '24px', right: '24px', background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-muted)' }}
            >
              <X size={24} />
            </button>
            <h2 style={{ fontSize: '1.4rem', fontWeight: '700', marginBottom: '24px', color: 'var(--text-primary)' }}>
              Registrar Nuevo Equipo
            </h2>
            <form onSubmit={handleCreate}>
              <div className="form-group">
                <label>Tipo de Elemento</label>
                <select
                  className="form-select"
                  value={formData.tipo}
                  onChange={(e) => setFormData({ ...formData, tipo: e.target.value })}
                >
                  <option value="activo">Activo (PC, Laptop, Impresora)</option>
                  <option value="pasivo">Pasivo (Switch, Router, Cableado)</option>
                  <option value="consumible">Consumible (Tóner, Cinta, Papel)</option>
                </select>
              </div>

              <div className="form-group">
                <label>Categoría</label>
                <input
                  type="text"
                  className="form-input"
                  required
                  placeholder="Ej. Laptop, Impresora Zebra, Switch"
                  value={formData.categoria}
                  onChange={(e) => setFormData({ ...formData, categoria: e.target.value })}
                />
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
                <div className="form-group">
                  <label>Marca</label>
                  <input
                    type="text"
                    className="form-input"
                    required
                    placeholder="Ej. HP, Zebra, Cisco"
                    value={formData.marca}
                    onChange={(e) => setFormData({ ...formData, marca: e.target.value })}
                  />
                </div>
                <div className="form-group">
                  <label>Modelo</label>
                  <input
                    type="text"
                    className="form-input"
                    required
                    placeholder="Ej. ProBook 440"
                    value={formData.modelo}
                    onChange={(e) => setFormData({ ...formData, modelo: e.target.value })}
                  />
                </div>
              </div>

              <div className="form-group">
                <label>Número de Serie</label>
                <input
                  type="text"
                  className="form-input"
                  placeholder="Ej. SN-8829-X"
                  value={formData.numero_serie}
                  onChange={(e) => setFormData({ ...formData, numero_serie: e.target.value })}
                />
              </div>

              <div className="form-group">
                <label>Ubicación en Planta</label>
                <input
                  type="text"
                  className="form-input"
                  placeholder="Ej. Línea 2, Almacén, IDC"
                  value={formData.ubicacion}
                  onChange={(e) => setFormData({ ...formData, ubicacion: e.target.value })}
                />
              </div>

              <div style={{ display: 'flex', gap: '12px', marginTop: '32px' }}>
                <button type="button" onClick={() => setShowModal(false)} className="btn-secondary" style={{ flex: 1 }}>
                  Cancelar
                </button>
                <button type="submit" className="btn-primary" style={{ flex: 1, justifyContent: 'center' }}>
                  Guardar Equipo
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};

export default Inventory;

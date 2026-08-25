import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import api from '../api/client';
import { useAuth } from '../context/AuthContext';
import { Sliders, Plus, Trash2, ShieldAlert, X } from 'lucide-react';

const RulesAdmin = () => {
  const { t } = useTranslation();
  const { user } = useAuth();

  const [reglas, setReglas] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showModal, setShowModal] = useState(false);

  const [formData, setFormData] = useState({
    categoria: 'impresora',
    condicion: 'hardware',
    accion: 'proveedor',
    destinatario: 'soporte@proveedor.com'
  });

  useEffect(() => {
    fetchReglas();
  }, []);

  const fetchReglas = async () => {
    try {
      const res = await api.get('/reglas');
      setReglas(res.data);
    } catch (err) {
      console.error("Error fetching rules", err);
    } finally {
      setLoading(false);
    }
  };

  const handleCreate = async (e) => {
    e.preventDefault();
    try {
      await api.post('/reglas', {
        ...formData,
        sitio_id: user.sitio_id,
        activa: true
      });
      setShowModal(false);
      fetchReglas();
    } catch (err) {
      console.error("Error creating rule", err);
    }
  };

  const handleDelete = async (id) => {
    if (!window.confirm("¿Seguro que desea eliminar esta regla de negocio?")) return;
    try {
      await api.delete(`/reglas/${id}`);
      fetchReglas();
    } catch (err) {
      console.error("Error deleting rule", err);
    }
  };

  return (
    <div className="page-container animate-fade-in" style={{ maxWidth: '1000px' }}>
      <div className="page-header">
        <div>
          <h1 className="page-title">
            Reglas de Negocio Configurables
          </h1>
          <p style={{ color: 'var(--text-secondary)', fontSize: '1rem', marginTop: '4px' }}>
            Enrutamiento automático de tickets por categoría y condición en Planta Querétaro
          </p>
        </div>

        <button onClick={() => setShowModal(true)} className="btn-primary">
          <Plus size={18} />
          Nueva Regla
        </button>
      </div>

      {loading ? (
        <div style={{ textAlign: 'center', padding: '60px', color: 'var(--text-muted)' }}>Cargando reglas de negocio...</div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          {reglas.map((r) => (
            <div key={r.id} className="apple-card" style={{ padding: '20px 24px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '8px' }}>
                  <span style={{
                    fontSize: '0.75rem',
                    fontWeight: '700',
                    textTransform: 'uppercase',
                    padding: '4px 10px',
                    borderRadius: 'var(--radius-full)',
                    background: 'var(--status-espera-proveedor-bg)',
                    color: 'var(--status-espera-proveedor-text)'
                  }}>
                    {r.categoria}
                  </span>
                  <span style={{ fontWeight: '600', color: 'var(--text-primary)', fontSize: '1.05rem' }}>
                    Condición: "{r.condicion}"
                  </span>
                </div>
                <div style={{ fontSize: '0.95rem', color: 'var(--text-secondary)' }}>
                  Acción: <strong style={{ color: 'var(--text-primary)'}}>{r.accion.toUpperCase()}</strong> → {r.destinatario || 'Asignación estándar'}
                </div>
              </div>

              <button 
                onClick={() => handleDelete(r.id)} 
                className="btn-secondary" 
                style={{ 
                  color: '#FF3B30', // Apple Red
                  padding: '10px',
                  background: '#FFF0F0',
                  border: 'none'
                }}
              >
                <Trash2 size={18} />
              </button>
            </div>
          ))}
        </div>
      )}

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
              Crear Regla de Negocio
            </h2>
            <form onSubmit={handleCreate}>
              <div className="form-group">
                <label>Categoría</label>
                <select
                  className="form-select"
                  value={formData.categoria}
                  onChange={(e) => setFormData({ ...formData, categoria: e.target.value })}
                >
                  <option value="impresora">Impresora</option>
                  <option value="red">Red</option>
                  <option value="equipo">Equipo</option>
                  <option value="software">Software</option>
                  <option value="accesos">Accesos</option>
                </select>
              </div>

              <div className="form-group">
                <label>Palabra Clave / Condición</label>
                <input
                  type="text"
                  className="form-input"
                  required
                  placeholder="Ej. hardware, atasco, proveedor"
                  value={formData.condicion}
                  onChange={(e) => setFormData({ ...formData, condicion: e.target.value })}
                />
              </div>

              <div className="form-group">
                <label>Acción Automática</label>
                <select
                  className="form-select"
                  value={formData.accion}
                  onChange={(e) => setFormData({ ...formData, accion: e.target.value })}
                >
                  <option value="proveedor">Enrutar a Proveedor Externo</option>
                  <option value="escalar">Escalar con Máxima Prioridad</option>
                  <option value="auto">Auto-resolver por Sistema</option>
                </select>
              </div>

              <div className="form-group">
                <label>Destinatario / Correo Proveedor</label>
                <input
                  type="text"
                  className="form-input"
                  placeholder="Ej. soporte@proveedor.com"
                  value={formData.destinatario}
                  onChange={(e) => setFormData({ ...formData, destinatario: e.target.value })}
                />
              </div>

              <div style={{ display: 'flex', gap: '12px', marginTop: '32px' }}>
                <button type="button" onClick={() => setShowModal(false)} className="btn-secondary" style={{ flex: 1 }}>
                  Cancelar
                </button>
                <button type="submit" className="btn-primary" style={{ flex: 1, justifyContent: 'center' }}>
                  Guardar Regla
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};

export default RulesAdmin;

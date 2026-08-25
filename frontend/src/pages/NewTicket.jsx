import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import api from '../api/client';
import { useAuth } from '../context/AuthContext';
import { CheckCircle2, AlertTriangle, ArrowRight, ArrowLeft, Send, HelpCircle } from 'lucide-react';

const NewTicket = () => {
  const { t } = useTranslation();
  const { user } = useAuth();
  const navigate = useNavigate();

  const [step, setStep] = useState(1);
  const [categoria, setCategoria] = useState('impresora');
  const [checklists, setChecklists] = useState([]);
  const [checklistIndex, setChecklistIndex] = useState(0);
  const [resolvedByChecklist, setResolvedByChecklist] = useState(false);

  const [equipos, setEquipos] = useState([]);
  const [equipoId, setEquipoId] = useState('');
  const [descripcion, setDescripcion] = useState('');
  const [prioridad, setPrioridad] = useState('media');
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    fetchChecklists(categoria);
  }, [categoria]);

  useEffect(() => {
    fetchEquipos();
  }, []);

  const fetchChecklists = async (cat) => {
    try {
      const res = await api.get(`/checklists?categoria=${cat}`);
      setChecklists(res.data);
      setChecklistIndex(0);
      setResolvedByChecklist(false);
    } catch (err) {
      console.error("Error loading checklists", err);
    }
  };

  const fetchEquipos = async () => {
    try {
      const res = await api.get('/equipos');
      setEquipos(res.data);
    } catch (err) {
      console.error("Error loading equipos", err);
    }
  };

  const handleNextStep = () => {
    if (step === 1) {
      if (checklists.length > 0) {
        setStep(2);
      } else {
        setStep(3);
      }
    }
  };

  const handleChecklistAnswer = (resolved) => {
    if (resolved) {
      setResolvedByChecklist(true);
    } else {
      if (checklistIndex + 1 < checklists.length) {
        setChecklistIndex(checklistIndex + 1);
      } else {
        setStep(3);
      }
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setSubmitting(true);
    try {
      const payload = {
        sitio_id: user.sitio_id,
        categoria: categoria,
        descripcion_original: descripcion,
        prioridad: prioridad,
        equipo_id: equipoId ? parseInt(equipoId) : null
      };

      const res = await api.post('/tickets', payload);
      navigate(`/tickets/${res.data.id}`);
    } catch (err) {
      console.error("Error creating ticket", err);
      alert("Error al crear ticket.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="page-container animate-fade-in" style={{ maxWidth: '800px' }}>
      <button
        onClick={() => navigate('/')}
        className="btn-secondary"
        style={{ marginBottom: '24px', padding: '8px 16px', fontSize: '0.9rem' }}
      >
        <ArrowLeft size={16} />
        Volver a Tickets
      </button>

      <div className="apple-card" style={{ padding: '40px' }}>
        <h1 style={{ fontSize: '1.85rem', fontWeight: '700', marginBottom: '8px', color: 'var(--text-primary)' }}>
          {t('new_ticket.title')}
        </h1>
        <p style={{ color: 'var(--text-secondary)', marginBottom: '32px', fontSize: '1rem' }}>
          {step === 1 && t('new_ticket.step1_category')}
          {step === 2 && t('new_ticket.step2_checklist')}
          {step === 3 && t('new_ticket.step3_details')}
        </p>

        {/* STEP 1: Select Category */}
        {step === 1 && (
          <div className="animate-fade-in">
            <div className="form-group">
              <label>{t('ticket.categoria')}</label>
              <select
                className="form-select"
                value={categoria}
                onChange={(e) => setCategoria(e.target.value)}
                style={{ width: '100%' }}
              >
                <option value="impresora">{t('new_ticket.category_impresora')}</option>
                <option value="red">{t('new_ticket.category_red')}</option>
                <option value="equipo">{t('new_ticket.category_equipo')}</option>
                <option value="software">{t('new_ticket.category_software')}</option>
                <option value="accesos">{t('new_ticket.category_accesos')}</option>
                <option value="otro">{t('new_ticket.category_otro')}</option>
              </select>
            </div>

            <button
              onClick={handleNextStep}
              className="btn-primary"
              style={{ marginTop: '24px', width: '100%', justifyContent: 'center', height: '48px', fontSize: '1rem' }}
            >
              Continuar
              <ArrowRight size={18} />
            </button>
          </div>
        )}

        {/* STEP 2: Interactive Troubleshooting Checklist */}
        {step === 2 && (
          <div className="animate-fade-in">
            {resolvedByChecklist ? (
              <div style={{
                textAlign: 'center',
                padding: '40px',
                background: 'var(--status-resuelto-bg)',
                borderRadius: 'var(--radius-lg)'
              }}>
                <CheckCircle2 size={56} style={{ color: 'var(--status-resuelto-text)', marginBottom: '16px', margin: '0 auto' }} />
                <h2 style={{ fontSize: '1.35rem', marginBottom: '12px', fontWeight: '600', color: 'var(--text-primary)' }}>
                  {t('new_ticket.ticket_resolved_checklist')}
                </h2>
                <p style={{ color: 'var(--text-secondary)', marginBottom: '24px', fontSize: '0.95rem' }}>
                  Gracias por utilizar la guía de auto-resolución de Planta Querétaro.
                </p>
                <button onClick={() => navigate('/')} className="btn-primary" style={{ padding: '12px 24px' }}>
                  Finalizar y Volver al Panel
                </button>
              </div>
            ) : checklists.length > 0 ? (
              <div style={{
                padding: '28px',
                background: 'var(--bg-tertiary)',
                borderRadius: 'var(--radius-lg)'
              }}>
                <div style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '10px',
                  marginBottom: '20px',
                  color: 'var(--accent-primary)'
                }}>
                  <HelpCircle size={22} />
                  <span style={{ fontWeight: '600', fontSize: '0.95rem' }}>
                    Pregunta {checklistIndex + 1} de {checklists.length}
                  </span>
                </div>

                <div style={{ fontSize: '1.15rem', fontWeight: '600', marginBottom: '16px', color: 'var(--text-primary)', lineHeight: '1.4' }}>
                  {t(checklists[checklistIndex].pregunta_key, { defaultValue: checklists[checklistIndex].pregunta_key })}
                </div>

                {checklists[checklistIndex].accion_si_no && (
                  <div style={{
                    padding: '16px',
                    background: 'var(--bg-secondary)',
                    borderRadius: 'var(--radius-md)',
                    fontSize: '0.9rem',
                    color: 'var(--text-secondary)',
                    marginBottom: '24px',
                    boxShadow: 'var(--shadow-sm)'
                  }}>
                    <strong style={{ color: 'var(--accent-primary)'}}>💡 Sugerencia:</strong> {checklists[checklistIndex].accion_si_no}
                  </div>
                )}

                <div style={{ display: 'flex', gap: '16px', marginTop: '24px' }}>
                  <button
                    onClick={() => handleChecklistAnswer(true)}
                    className="btn-secondary"
                    style={{ flex: 1, justifyContent: 'center', color: 'var(--status-resuelto-text)' }}
                  >
                    {t('new_ticket.yes_resolved')}
                  </button>
                  <button
                    onClick={() => handleChecklistAnswer(false)}
                    className="btn-primary"
                    style={{ flex: 1, justifyContent: 'center' }}
                  >
                    {t('new_ticket.no_continue')}
                  </button>
                </div>
              </div>
            ) : null}
          </div>
        )}

        {/* STEP 3: Create Ticket Form */}
        {step === 3 && (
          <form onSubmit={handleSubmit} className="animate-fade-in">
            <div className="form-group">
              <label>{t('ticket.equipo_asociado')}</label>
              <select
                className="form-select"
                value={equipoId}
                onChange={(e) => setEquipoId(e.target.value)}
              >
                <option value="">-- {t('ticket.sin_equipo')} --</option>
                {equipos.map((eq) => (
                  <option key={eq.id} value={eq.id}>
                    {eq.tipo.toUpperCase()} - {eq.categoria} {eq.marca} {eq.modelo} ({eq.numero_serie || 'S/N'})
                  </option>
                ))}
              </select>
            </div>

            <div className="form-group">
              <label>{t('ticket.prioridad')}</label>
              <select
                className="form-select"
                value={prioridad}
                onChange={(e) => setPrioridad(e.target.value)}
              >
                <option value="baja">Baja</option>
                <option value="media">Media</option>
                <option value="alta">Alta</option>
                <option value="critica">Crítica (Detiene producción)</option>
              </select>
            </div>

            <div className="form-group">
              <label>{t('ticket.descripcion')}</label>
              <textarea
                className="form-textarea"
                rows={5}
                required
                placeholder="Describa el problema detalladamente..."
                value={descripcion}
                onChange={(e) => setDescripcion(e.target.value)}
              />
            </div>

            <button
              type="submit"
              className="btn-primary"
              disabled={submitting}
              style={{ width: '100%', justifyContent: 'center', marginTop: '32px', height: '48px', fontSize: '1rem' }}
            >
              {submitting ? 'Generando Ticket...' : (
                <>
                  <Send size={18} />
                  {t('new_ticket.submit_btn')}
                </>
              )}
            </button>
          </form>
        )}
      </div>
    </div>
  );
};

export default NewTicket;

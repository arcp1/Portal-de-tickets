import React, { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import api from '../api/client';
import { useAuth } from '../context/AuthContext';
import StatusBadge from '../components/StatusBadge';
import { ArrowLeft, MessageSquare, Send, ShieldAlert, User, Laptop, Calendar, Clock, CheckCircle } from 'lucide-react';

const TicketDetail = () => {
  const { id } = useParams();
  const { t } = useTranslation();
  const { user } = useAuth();
  const navigate = useNavigate();

  const [ticket, setTicket] = useState(null);
  const [loading, setLoading] = useState(true);
  const [newComment, setNewComment] = useState('');
  const [isInternal, setIsInternal] = useState(false);
  const [submittingComment, setSubmittingComment] = useState(false);

  useEffect(() => {
    fetchTicket();
  }, [id]);

  const fetchTicket = async () => {
    try {
      const res = await api.get(`/tickets/${id}`);
      setTicket(res.data);
    } catch (err) {
      console.error("Error loading ticket detail", err);
    } finally {
      setLoading(false);
    }
  };

  const handleStatusChange = async (newStatus) => {
    try {
      const res = await api.patch(`/tickets/${id}`, { estado: newStatus });
      setTicket(res.data);
    } catch (err) {
      console.error("Error updating status", err);
    }
  };

  const handleAddComment = async (e) => {
    e.preventDefault();
    if (!newComment.trim()) return;
    setSubmittingComment(true);
    try {
      await api.post(`/tickets/${id}/comments`, {
        comentario: newComment,
        es_interno: user.rol === 'admin' ? isInternal : false
      });
      setNewComment('');
      setIsInternal(false);
      fetchTicket();
    } catch (err) {
      console.error("Error adding comment", err);
    } finally {
      setSubmittingComment(false);
    }
  };

  if (loading) {
    return <div className="page-container" style={{ textAlign: 'center', padding: '60px', color: 'var(--text-muted)' }}>Cargando detalles del ticket...</div>;
  }

  if (!ticket) {
    return <div className="page-container" style={{ textAlign: 'center', padding: '60px', color: 'var(--text-muted)' }}>Ticket no encontrado.</div>;
  }

  return (
    <div className="page-container animate-fade-in" style={{ maxWidth: '1000px' }}>
      <button onClick={() => navigate('/')} className="btn-secondary" style={{ marginBottom: '24px', padding: '8px 16px', fontSize: '0.9rem' }}>
        <ArrowLeft size={16} />
        Volver
      </button>

      {/* Header Info Card */}
      <div className="apple-card" style={{ padding: '32px', marginBottom: '24px' }}>
        <div style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'flex-start',
          gap: '16px',
          flexWrap: 'wrap',
          marginBottom: '20px'
        }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '16px', marginBottom: '8px' }}>
              <h1 style={{ fontSize: '1.75rem', fontWeight: '700', color: 'var(--text-primary)' }}>
                {ticket.folio}
              </h1>
              <StatusBadge estado={ticket.estado} />
            </div>
            <div style={{ color: 'var(--text-secondary)', fontSize: '0.95rem' }}>
              Creado el {new Date(ticket.creado_en).toLocaleString()}
            </div>
          </div>

          {/* Admin Controls */}
          {user.rol === 'admin' && (
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px', background: 'var(--bg-tertiary)', padding: '12px 16px', borderRadius: 'var(--radius-md)' }}>
              <span style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', fontWeight: '500' }}>Cambiar Estado:</span>
              <select
                className="form-select"
                value={ticket.estado}
                onChange={(e) => handleStatusChange(e.target.value)}
                style={{ padding: '8px 14px', fontSize: '0.9rem', minWidth: '150px' }}
              >
                <option value="abierto">Abierto</option>
                <option value="en_proceso">En Proceso</option>
                <option value="espera_proveedor">En Proveedor</option>
                <option value="resuelto">Resuelto</option>
                <option value="cerrado">Cerrado</option>
              </select>
            </div>
          )}
        </div>

        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
          gap: '20px',
          padding: '24px',
          background: 'var(--bg-tertiary)',
          borderRadius: 'var(--radius-md)',
          marginBottom: '28px'
        }}>
          <div>
            <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', textTransform: 'uppercase', marginBottom: '4px', fontWeight: '500' }}>Reportado por</div>
            <div style={{ fontWeight: '600', fontSize: '1.05rem', color: 'var(--text-primary)' }}>{ticket.usuario?.nombre}</div>
          </div>
          <div>
            <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', textTransform: 'uppercase', marginBottom: '4px', fontWeight: '500' }}>Categoría</div>
            <div style={{ fontWeight: '600', fontSize: '1.05rem', textTransform: 'capitalize', color: 'var(--text-primary)' }}>{ticket.categoria}</div>
          </div>
          <div>
            <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', textTransform: 'uppercase', marginBottom: '4px', fontWeight: '500' }}>Prioridad</div>
            <div style={{ fontWeight: '600', fontSize: '1.05rem', textTransform: 'capitalize', color: 'var(--text-primary)' }}>{ticket.prioridad}</div>
          </div>
          <div>
            <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', textTransform: 'uppercase', marginBottom: '4px', fontWeight: '500' }}>Canal de Resolución</div>
            <div style={{ fontWeight: '600', fontSize: '1.05rem', color: 'var(--text-primary)' }}>{ticket.canal_resolucion || 'Técnico'}</div>
          </div>
        </div>

        <div>
          <h3 style={{ fontSize: '1rem', fontWeight: '600', color: 'var(--text-primary)', marginBottom: '12px' }}>
            {t('ticket.descripcion')}
          </h3>
          <div style={{
            fontSize: '1.05rem',
            lineHeight: '1.6',
            color: 'var(--text-primary)',
            background: 'var(--bg-secondary)',
            padding: '20px',
            borderRadius: 'var(--radius-md)',
            border: '1px solid var(--border-color)',
            boxShadow: 'var(--shadow-sm)'
          }}>
            {ticket.descripcion_original}
          </div>
        </div>
      </div>

      {/* Comments Thread */}
      <div className="apple-card" style={{ padding: '32px' }}>
        <h2 style={{ fontSize: '1.35rem', fontWeight: '700', marginBottom: '24px', display: 'flex', alignItems: 'center', gap: '10px', color: 'var(--text-primary)' }}>
          <MessageSquare size={22} color="var(--accent-primary)" />
          {t('ticket.comentarios')}
        </h2>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '20px', marginBottom: '32px' }}>
          {ticket.comentarios && ticket.comentarios.length > 0 ? (
            ticket.comentarios.map((c) => (
              <div
                key={c.id}
                style={{
                  padding: '20px',
                  borderRadius: 'var(--radius-md)',
                  background: c.es_interno ? 'var(--status-espera-proveedor-bg)' : 'var(--bg-tertiary)',
                  border: c.es_interno ? '1px solid var(--status-espera-proveedor-bg)' : '1px solid transparent',
                  boxShadow: 'var(--shadow-sm)'
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
                  <span style={{ fontWeight: '600', fontSize: '0.95rem', color: 'var(--text-primary)' }}>
                    {c.autor?.nombre}
                    {c.es_interno && (
                      <span style={{ marginLeft: '12px', fontSize: '0.75rem', color: 'var(--status-espera-proveedor-text)', background: 'var(--bg-secondary)', padding: '4px 8px', borderRadius: '6px', fontWeight: '600' }}>
                        Nota Interna TI
                      </span>
                    )}
                  </span>
                  <span style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
                    {new Date(c.creado_en).toLocaleString()}
                  </span>
                </div>
                <div style={{ fontSize: '1rem', color: 'var(--text-primary)', lineHeight: '1.5' }}>
                  {c.comentario}
                </div>
              </div>
            ))
          ) : (
            <div style={{ color: 'var(--text-muted)', fontSize: '0.95rem', textAlign: 'center', padding: '20px' }}>
              No hay comentarios en este ticket aún.
            </div>
          )}
        </div>

        {/* Add Comment Form */}
        <form onSubmit={handleAddComment}>
          <div className="form-group" style={{ marginBottom: '20px' }}>
            <textarea
              className="form-textarea"
              rows={3}
              placeholder={t('ticket.add_comment')}
              value={newComment}
              onChange={(e) => setNewComment(e.target.value)}
              required
              style={{ fontSize: '1rem' }}
            />
          </div>

          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            {user.rol === 'admin' ? (
              <label style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '0.95rem', color: 'var(--text-primary)', fontWeight: '500', cursor: 'pointer' }}>
                <input
                  type="checkbox"
                  checked={isInternal}
                  onChange={(e) => setIsInternal(e.target.checked)}
                  style={{ width: '18px', height: '18px', cursor: 'pointer' }}
                />
                {t('ticket.internal_note')}
              </label>
            ) : <div />}

            <button type="submit" className="btn-primary" disabled={submittingComment} style={{ height: '44px', padding: '0 24px' }}>
              <Send size={18} />
              {t('ticket.send_comment')}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};

export default TicketDetail;

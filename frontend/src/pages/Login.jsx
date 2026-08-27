import React, { useState } from 'react';
import { useNavigate, useLocation, Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useAuth } from '../context/AuthContext';
import LanguageSelector from '../components/LanguageSelector';
import { Lock, User, ArrowRight, Shield } from 'lucide-react';

const Login = () => {
  const { t } = useTranslation();
  const { login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  // Número de empleado. Se acepta también el correo para quien lo tenga:
  // el backend resuelve cualquiera de los dos.
  const [identificador, setIdentificador] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setSubmitting(true);
    try {
      await login(identificador.trim(), password);
      // `replace` para que el botón de atrás no regrese al login.
      navigate(location.state?.desde || '/', { replace: true });
    } catch (err) {
      setError(t('auth.error_login'));
      setSubmitting(false);
    }
  };

  return (
    <div style={{
      minHeight: '100vh',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      padding: '20px',
      position: 'relative'
    }}>
      <div style={{ position: 'absolute', top: '24px', right: '24px' }}>
        <LanguageSelector />
      </div>

      <div className="apple-card animate-fade-in" style={{
        width: '100%',
        maxWidth: '420px',
        padding: '36px',
        borderRadius: 'var(--radius-lg)'
      }}>
        {/* Header */}
        <div style={{ textAlign: 'center', marginBottom: '32px' }}>
          <div style={{
            width: '64px',
            height: '64px',
            borderRadius: '16px',
            background: 'var(--accent-primary)',
            display: 'inline-flex',
            alignItems: 'center',
            justifyContent: 'center',
            marginBottom: '20px',
            boxShadow: '0 8px 16px rgba(0, 122, 255, 0.25)'
          }}>
            <Shield size={32} color="white" />
          </div>
          <h1 style={{ fontSize: '1.75rem', fontWeight: '700', marginBottom: '8px' }}>
            {t('auth.title')}
          </h1>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.95rem' }}>
            {t('auth.subtitle')}
          </p>
        </div>

        {error && (
          <div style={{
            background: '#FFF0F0',
            border: '1px solid #FFD6D6',
            color: '#D8000C',
            padding: '12px',
            borderRadius: 'var(--radius-sm)',
            fontSize: '0.9rem',
            marginBottom: '20px',
            textAlign: 'center'
          }}>
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label>{t('auth.identificador')}</label>
            <div style={{ position: 'relative' }}>
              <User size={18} style={{
                position: 'absolute',
                left: '14px',
                top: '50%',
                transform: 'translateY(-50%)',
                color: 'var(--text-muted)'
              }} />
              <input
                type="text"
                className="form-input"
                style={{ width: '100%', paddingLeft: '42px' }}
                placeholder={t('auth.identificador_ejemplo')}
                autoComplete="username"
                autoCapitalize="off"
                spellCheck={false}
                value={identificador}
                onChange={(e) => setIdentificador(e.target.value)}
                required
              />
            </div>
            <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)', marginTop: '6px' }}>
              {t('auth.identificador_ayuda')}
            </div>
          </div>

          <div className="form-group">
            <label>{t('auth.password')}</label>
            <div style={{ position: 'relative' }}>
              <Lock size={18} style={{
                position: 'absolute',
                left: '14px',
                top: '50%',
                transform: 'translateY(-50%)',
                color: 'var(--text-muted)'
              }} />
              <input
                type="password"
                className="form-input"
                style={{ width: '100%', paddingLeft: '42px' }}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            </div>
          </div>

          <button
            type="submit"
            className="btn-primary"
            disabled={submitting}
            style={{ width: '100%', justifyContent: 'center', marginTop: '24px', height: '48px', fontSize: '1rem' }}
          >
            {submitting ? t('auth.logging_in') : (
              <>
                {t('auth.login_btn')}
                <ArrowRight size={18} />
              </>
            )}
          </button>
        </form>
        <Link to="/activar" style={{
          display: 'block', textAlign: 'center', marginTop: '20px',
          fontSize: '0.9rem', color: 'var(--accent-primary)',
          textDecoration: 'none', fontWeight: '600'
        }}>
          {t('activar.primera_vez')}
        </Link>

        {import.meta.env.DEV && (
          <div style={{
            marginTop: '32px',
            paddingTop: '20px',
            borderTop: '1px solid var(--border-color)',
            fontSize: '0.85rem',
            color: 'var(--text-muted)',
            textAlign: 'center'
          }}>
            <div style={{ marginBottom: '8px' }}><strong>Solo en desarrollo:</strong></div>
            <div style={{ marginBottom: '4px' }}>10001 / Admin123!</div>
            <div>10002 / User123!</div>
          </div>
        )}
      </div>
    </div>
  );
};

export default Login;

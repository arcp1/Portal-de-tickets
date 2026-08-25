import React from 'react';
import { Link, useNavigate, useLocation } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useAuth } from '../context/AuthContext';
import LanguageSelector from './LanguageSelector';
import { Ticket, PlusCircle, Laptop, Sliders, LogOut, ShieldCheck, User } from 'lucide-react';

const Navbar = () => {
  const { t } = useTranslation();
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  if (!user) return null;

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  const isActive = (path) => location.pathname === path;

  return (
    <nav style={{
      background: 'rgba(255, 255, 255, 0.85)',
      backdropFilter: 'blur(16px)',
      borderBottom: '1px solid var(--border-color)',
      position: 'sticky',
      top: 0,
      zIndex: 100,
      padding: '12px 24px',
      boxShadow: 'var(--shadow-sm)'
    }}>
      <div style={{
        maxWidth: '1280px',
        margin: '0 auto',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between'
      }}>
        {/* Brand */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
          <Link to="/" style={{ display: 'flex', alignItems: 'center', gap: '10px', textDecoration: 'none' }}>
            <div style={{
              width: '36px',
              height: '36px',
              borderRadius: '10px',
              background: 'var(--accent-primary)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontWeight: 'bold',
              color: 'white',
              boxShadow: '0 4px 12px rgba(0, 122, 255, 0.3)'
            }}>
              CGR
            </div>
            <div>
              <div style={{ fontFamily: 'var(--font-heading)', fontWeight: '700', fontSize: '1.1rem', letterSpacing: '-0.01em', color: 'var(--text-primary)' }}>
                Portal de Tickets TI
              </div>
              <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', fontWeight: '500' }}>
                {t('nav.plant')}
              </div>
            </div>
          </Link>
        </div>

        {/* Navigation Links */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <Link
            to="/"
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              padding: '8px 14px',
              borderRadius: 'var(--radius-full)',
              fontSize: '0.9rem',
              fontWeight: '600',
              textDecoration: 'none',
              color: isActive('/') ? 'var(--accent-primary)' : 'var(--text-secondary)',
              background: isActive('/') ? 'var(--bg-secondary)' : 'transparent',
              transition: 'all 0.2s ease'
            }}
          >
            <Ticket size={18} />
            {t('nav.dashboard')}
          </Link>

          <Link
            to="/new-ticket"
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              padding: '8px 14px',
              borderRadius: 'var(--radius-full)',
              fontSize: '0.9rem',
              fontWeight: '600',
              textDecoration: 'none',
              color: isActive('/new-ticket') ? 'var(--accent-primary)' : 'var(--text-secondary)',
              background: isActive('/new-ticket') ? 'var(--bg-secondary)' : 'transparent',
              transition: 'all 0.2s ease'
            }}
          >
            <PlusCircle size={18} />
            {t('nav.new_ticket')}
          </Link>

          <Link
            to="/inventory"
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              padding: '8px 14px',
              borderRadius: 'var(--radius-full)',
              fontSize: '0.9rem',
              fontWeight: '600',
              textDecoration: 'none',
              color: isActive('/inventory') ? 'var(--accent-primary)' : 'var(--text-secondary)',
              background: isActive('/inventory') ? 'var(--bg-secondary)' : 'transparent',
              transition: 'all 0.2s ease'
            }}
          >
            <Laptop size={18} />
            {t('nav.inventory')}
          </Link>

          {user.rol === 'admin' && (
            <Link
              to="/rules"
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '8px',
                padding: '8px 14px',
                borderRadius: 'var(--radius-full)',
                fontSize: '0.9rem',
                fontWeight: '600',
                textDecoration: 'none',
                color: isActive('/rules') ? 'var(--accent-primary)' : 'var(--text-secondary)',
                background: isActive('/rules') ? 'var(--bg-secondary)' : 'transparent',
                transition: 'all 0.2s ease'
              }}
            >
              <Sliders size={18} />
              {t('nav.rules')}
            </Link>
          )}
        </div>

        {/* User profile & Controls */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '14px' }}>
          <LanguageSelector />

          <div style={{
            display: 'flex',
            alignItems: 'center',
            gap: '10px',
            padding: '6px 14px',
            background: 'var(--bg-tertiary)',
            border: '1px solid var(--border-color)',
            borderRadius: 'var(--radius-full)'
          }}>
            {user.rol === 'admin' ? (
              <ShieldCheck size={18} style={{ color: 'var(--accent-primary)' }} />
            ) : (
              <User size={18} style={{ color: 'var(--text-secondary)' }} />
            )}
            <div style={{ textAlign: 'left' }}>
              <div style={{ fontSize: '0.85rem', fontWeight: '600', color: 'var(--text-primary)' }}>{user.nombre}</div>
              <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>{user.email}</div>
            </div>
          </div>

          <button
            onClick={handleLogout}
            className="btn-secondary"
            style={{ padding: '8px', borderRadius: '50%', width: '38px', height: '38px', display: 'flex', alignItems: 'center', justifyContent: 'center' }}
            title={t('nav.logout')}
          >
            <LogOut size={18} color="var(--text-secondary)" />
          </button>
        </div>
      </div>
    </nav>
  );
};

export default Navbar;

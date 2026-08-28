import React from 'react';
import { Link, useNavigate, useLocation } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useAuth } from '../context/AuthContext';
import LanguageSelector from './LanguageSelector';
import {
  Ticket, PlusCircle, Laptop, Sliders, LogOut, ShieldCheck, User,
  TrendingUp, ListChecks, FolderOpen, FileSignature, Users, BookOpen,
  Upload, Activity, BookOpenCheck
} from 'lucide-react';

const Navbar = () => {
  const { t } = useTranslation();
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  if (!user) return null;

  const cerrarSesion = () => {
    logout();
    navigate('/login', { replace: true });
  };

  const activo = (ruta) => location.pathname === ruta;

  const esAdmin = user.rol === 'admin';

  // El orden es el del uso real: primero lo que hace todo el mundo todos los
  // días, al final lo de administración.
  const enlaces = [
    { ruta: '/', icono: <Ticket size={18} />, texto: t('nav.dashboard') },
    { ruta: '/new-ticket', icono: <PlusCircle size={18} />, texto: t('nav.new_ticket') },
    { ruta: '/inventory', icono: <Laptop size={18} />, texto: t('nav.inventory') },
    { ruta: '/expediente', icono: <FolderOpen size={18} />, texto: t('nav.expediente') },
    ...(esAdmin ? [
      { ruta: '/usuarios', icono: <Users size={18} />, texto: t('nav.usuarios') },
      { ruta: '/importar', icono: <Upload size={18} />, texto: t('nav.importar') },
      { ruta: '/resguardos', icono: <FileSignature size={18} />, texto: t('nav.resguardos') },
      { ruta: '/soluciones', icono: <BookOpenCheck size={18} />, texto: t('nav.soluciones') },
      { ruta: '/documentacion', icono: <BookOpen size={18} />, texto: t('nav.documentacion') },
      { ruta: '/temas', icono: <ListChecks size={18} />, texto: t('nav.temas') },
      { ruta: '/rules', icono: <Sliders size={18} />, texto: t('nav.rules') },
      { ruta: '/metricas', icono: <TrendingUp size={18} />, texto: t('nav.metricas') },
      { ruta: '/estado', icono: <Activity size={18} />, texto: t('nav.estado') }
    ] : [])
  ];

  return (
    <nav className="navbar">
      <div className="navbar-contenido">
        <Link to="/" className="navbar-marca">
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
            fontSize: '0.82rem',
            flexShrink: 0,
            boxShadow: '0 4px 12px rgba(0, 122, 255, 0.3)'
          }}>
            CGR
          </div>
          <div className="navbar-marca-texto">
            <div className="navbar-marca-titulo" style={{
              fontFamily: 'var(--font-heading)',
              fontWeight: '700',
              fontSize: '1.05rem',
              letterSpacing: '-0.01em',
              color: 'var(--text-primary)',
              whiteSpace: 'nowrap'
            }}>
              Portal de Tickets TI
            </div>
            <div className="navbar-marca-sub" style={{
              fontSize: '0.75rem',
              color: 'var(--text-secondary)',
              fontWeight: '500',
              whiteSpace: 'nowrap'
            }}>
              {t('nav.plant')}
            </div>
          </div>
        </Link>

        <div className="navbar-enlaces">
          {enlaces.map((e) => (
            <Link
              key={e.ruta}
              to={e.ruta}
              className={`navbar-enlace${activo(e.ruta) ? ' activo' : ''}`}
              title={e.texto}
              aria-current={activo(e.ruta) ? 'page' : undefined}
            >
              {e.icono}
              <span className="navbar-enlace-texto">{e.texto}</span>
            </Link>
          ))}
        </div>

        <div className="navbar-derecha">
          <LanguageSelector />

          <div className="navbar-perfil">
            {esAdmin
              ? <ShieldCheck size={18} style={{ color: 'var(--accent-primary)', flexShrink: 0 }} />
              : <User size={18} style={{ color: 'var(--text-secondary)', flexShrink: 0 }} />}
            <div className="navbar-perfil-nombre" style={{ lineHeight: 1.25, minWidth: 0 }}>
              <div style={{
                fontSize: '0.85rem',
                fontWeight: '600',
                color: 'var(--text-primary)',
                whiteSpace: 'nowrap',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                maxWidth: '160px'
              }}>
                {user.nombre}
              </div>
              <div className="navbar-perfil-correo" style={{
                fontSize: '0.72rem',
                color: 'var(--text-secondary)',
                whiteSpace: 'nowrap'
              }}>
                {user.email}
              </div>
            </div>
          </div>

          <button
            onClick={cerrarSesion}
            className="btn-secondary"
            style={{ padding: '9px 12px' }}
            title={t('nav.logout')}
            aria-label={t('nav.logout')}
          >
            <LogOut size={17} />
          </button>
        </div>
      </div>
    </nav>
  );
};

export default Navbar;

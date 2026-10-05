import React, { useEffect, useState } from 'react';
import { Link, useNavigate, useLocation } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useAuth } from '../context/AuthContext';
import MenuBarra from './MenuBarra';
import { seccionesDe, seccionActiva } from '../lib/navegacion';
import { LogOut, ShieldCheck, User, FolderOpen, KeyRound, Languages, Check, Search, ScrollText
} from 'lucide-react';
import { useConexionPortal } from '../context/Eventos';
import CambiarPassword from './CambiarPassword';
import { cambiarIdioma as cambiarIdiomaDelPortal } from '../i18n';
import CampanaAlertas from './CampanaAlertas';
import { textoPlantasDe } from '../lib/plantas';

/* Los tres idiomas viven aquí y no en un control aparte de la barra: el
   selector suelto ocupaba noventa y ocho píxeles de una fila que no daba más
   de sí, y es un ajuste que una persona toca una vez en su vida. Dentro del
   menú de la cuenta está donde uno lo busca. */
const IDIOMAS = [['es', 'Español'], ['en', 'English'], ['fr', 'Français']];

/* En el Mac la combinación es ⌘K y en todo lo demás Ctrl+K. Enseñar la que no
   es deja el atajo inservible para quien se fía del cartel. Las máquinas de
   la planta son Windows, así que lo normal aquí es "Ctrl". */
const esMac = typeof navigator !== 'undefined'
  && /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);

const Navbar = () => {
  const { t, i18n } = useTranslation();
  const enVivo = useConexionPortal();
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [cambiandoPassword, setCambiandoPassword] = useState(false);

  /* El diálogo de contraseña vive aquí, pero la paleta de comandos también lo
     ofrece. En vez de subir este estado a la aplicación entera por un atajo,
     la paleta lanza un evento y la barra lo escucha. Va **antes** del
     `return null` de abajo: un hook detrás de una salida temprana dejaría de
     ejecutarse en el render en que no hay sesión, que es justo lo que React
     no admite. */
  useEffect(() => {
    const abrir = () => setCambiandoPassword(true);
    window.addEventListener('portal:cambiar-password', abrir);
    return () => window.removeEventListener('portal:cambiar-password', abrir);
  }, []);

  if (!user) return null;

  const cambiarIdioma = (codigo) => { cambiarIdiomaDelPortal(codigo); };

  const cerrarSesion = () => {
    logout();
    navigate('/login', { replace: true });
  };

  const esAdmin = user.rol === 'admin';

  // La lista vive en `lib/navegacion`, no aquí: la paleta de comandos
  // necesita exactamente la misma, y copiada en dos sitios el día que se
  // añada una sección se añadiría en uno solo.
  const secciones = seccionesDe(t, esAdmin);
  // Por prefijo y no exacta: `/personas/plantas` sigue siendo «Personas».
  const activo = (ruta) => {
    const s = secciones.find((x) => x.ruta === ruta);
    return s ? seccionActiva(s, location.pathname) : location.pathname === ruta;
  };

  return (
    <nav className="navbar">
      <div className="navbar-contenido">
        <Link viewTransition to="/" className="navbar-marca">
          {/* El logotipo oficial, sobre placa blanca por lo mismo que en el
              login: el archivo de marca es la version positiva —letras y lema
              en azul— y `#003b7c` sobre una barra casi negra no se lee. La
              placa es lo que deja que los colores lleguen como los define la
              marca.

              A esta altura el lema no se lee, y esta bien: a 30 px hace de
              textura, no de texto. El nombre del portal va al lado. */}
          <img
            className="navbar-marca-placa"
            src="/marca/cgr.png"
            alt="CGR"
            width={62}
            height={31}
          />
          <div className="navbar-marca-texto">
            <div className="navbar-marca-titulo" style={{
              fontFamily: 'var(--font-heading)',
              fontWeight: '700',
              fontSize: '1.05rem',
              letterSpacing: '-0.01em',
              color: 'var(--text-primary)',
              whiteSpace: 'nowrap'
            }}>
              {t('nav.portal')}
            </div>
            {/* La planta de quien entra, leída de la base. Estaba escrita en
                la traducción, así que desde otra planta se leía "Querétaro".
                Desde multi-planta: TI es de todas, y quien trabaja en varias
                ve sus claves. */}
            {textoPlantasDe(user, t) && (
              <div className="navbar-marca-sub" style={{
                fontSize: '0.75rem',
                color: 'var(--text-secondary)',
                fontWeight: '500',
                whiteSpace: 'nowrap'
              }}>
                {textoPlantasDe(user, t)}
              </div>
            )}
          </div>
        </Link>

        {/* Enlaces y grupos salen de una sola lista y en su orden, no en dos
            pasadas: con dos, cualquier enlace suelto se colaba delante de
            todos los menús y Personas —que es administración— acababa
            pegada a "Nuevo Ticket", entre las tareas del día a día. */}
        <div className="navbar-enlaces">
          {secciones.map((s) => (s.entradas ? (
            <MenuBarra
              key={s.clave}
              texto={s.texto}
              entradas={s.entradas}
              rutaActiva={location.pathname}
            />
          ) : (
            <Link viewTransition
              key={s.ruta}
              to={s.ruta}
              className={`navbar-enlace${activo(s.ruta) ? ' activo' : ''}`}
              title={s.texto}
              aria-current={activo(s.ruta) ? 'page' : undefined}
            >
              {s.icono}
              <span className="navbar-enlace-texto">{s.texto}</span>
            </Link>
          )))}
        </div>

        <div className="navbar-derecha">
          {/* **El atajo hay que enseñarlo o no existe.** Una paleta de
              comandos que solo se abre con una combinación que nadie ha dicho
              es una función que no usa nadie. Este botón la abre con el ratón
              y, sobre todo, enseña la combinación.

              Se esconde por debajo de 1360 px: ahí la barra ya va justa y lo
              primero que cedería sería el nombre de la cuenta, que importa
              más —en una terminal de planta compartida, saber con qué cuenta
              estás abierto no es un adorno—. Quien la conozca sigue teniendo
              el atajo, que funciona a cualquier ancho. */}
          <button
            type="button"
            className="navbar-atajo"
            onClick={() => window.dispatchEvent(new CustomEvent('portal:paleta'))}
            title={t('paleta.pista')}
            aria-label={t('paleta.titulo')}
          >
            <Search size={13} aria-hidden="true" />
            <kbd>{esMac ? '\u2318' : 'Ctrl'} K</kbd>
          </button>

          {/* Que el portal esté escuchando es información: si se cae, lo que
              hay en pantalla deja de ser lo que hay en la base y quien esté
              atendiendo tickets tiene derecho a saberlo. Sin texto, porque el
              caso normal es que esté verde y nadie necesita leer "conectado"
              cien veces al día; el título lo dice para quien pase el ratón y
              para los lectores de pantalla. */}
          {/* Lo que el portal detectó solo —SLA por vencer, sensores fuera
              de rango, una calificación baja—. Solo TI. */}
          {esAdmin && <CampanaAlertas />}
          <span
            className={`pulso-conexion${enVivo ? ' pulso-conexion--vivo' : ''}`}
            title={t(enVivo ? 'navbar.en_vivo' : 'navbar.sin_conexion')}
            role="status"
            aria-label={t(enVivo ? 'navbar.en_vivo' : 'navbar.sin_conexion')}
          />
          {/* **El perfil, la contraseña y la salida, en un solo menú.**
              Sueltos eran tres piezas —un chip con el nombre y dos botones de
              icono— que sumaban más de lo que le cabe a su columna, así que lo
              primero en desaparecer era justo el nombre: en una terminal de
              planta compartida, saber con qué cuenta estás abierto no es un
              adorno. Plegados, el nombre vuelve a verse.

              "Mi Expediente" se mudó aquí desde el grupo de Personas: son los
              equipos, resguardos y documentos de uno mismo, no la
              administración de los demás. */}
          <MenuBarra
            alinear="derecha"
            claseBoton="navbar-perfil navbar-perfil--menu"
            rutaActiva={location.pathname}
            contenido={
              <>
                {esAdmin
                  ? <ShieldCheck size={18} style={{ color: 'var(--accent-primary)', flexShrink: 0 }} />
                  : <User size={18} style={{ color: 'var(--text-secondary)', flexShrink: 0 }} />}
                <span className="navbar-perfil-nombre">{user.nombre}</span>
              </>
            }
            entradas={[
              { ruta: '/expediente', icono: <FolderOpen size={16} />, texto: t('nav.expediente') },
              ...IDIOMAS.map(([codigo, nombre]) => ({
                onSelect: () => cambiarIdioma(codigo),
                icono: i18n.language?.startsWith(codigo)
                  ? <Check size={16} />
                  : <Languages size={16} style={{ opacity: 0.45 }} />,
                texto: nombre
              })),
              { onSelect: () => setCambiandoPassword(true), icono: <KeyRound size={16} />, texto: t('password.abrir') },
              { ruta: '/terminos', icono: <ScrollText size={16} />, texto: t('terminos.enlace') },
              { onSelect: cerrarSesion, icono: <LogOut size={16} />, texto: t('nav.logout'), peligro: true }
            ]}
          />
        </div>
      </div>

      {cambiandoPassword && (
        <CambiarPassword
          onCerrar={() => setCambiandoPassword(false)}
          // Al cambiarla, el backend sube la version del token y esta sesion
          // deja de valer: se acompana a la puerta en vez de esperar a que la
          // siguiente peticion devuelva un 401.
          onCambiada={() => { setCambiandoPassword(false); cerrarSesion(); }}
        />
      )}
    </nav>
  );
};

export default Navbar;

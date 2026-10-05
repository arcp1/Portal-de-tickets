import React, { useState } from 'react';
import { useNavigate, useLocation, Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useAuth } from '../context/AuthContext';
import LanguageSelector from '../components/LanguageSelector';
import { AlertTriangle, Eye, EyeOff } from 'lucide-react';
import Formulario from '../components/Formulario';
import { SESION_CADUCADA, VOLVER_A } from '../api/client';

/**
 * La puerta del portal, con la estructura del componente Mercury.
 *
 * **Qué se tomó de la plantilla:** la cabecera alineada a la izquierda con un
 * rótulo pequeño encima, los campos sin caja —solo una línea abajo que se
 * enciende al enfocar—, el desplazamiento lateral del grupo al recibir el
 * foco, y el botón con la gota que se expande.
 *
 * **Qué no se tomó, y por qué:**
 *
 *   Las tipografías de Google. No es solo que 'Space Mono' hiciera parecer
 *   esto una terminal: la política de contenido del portal es `font-src
 *   'self'`, así que un `@import` a fonts.googleapis.com **lo bloquea el
 *   navegador**. Las fuentes de este proyecto se auto-alojan desde que se
 *   cerró esa política. Se usa la del portal.
 *
 *   El `<style>` incrustado en el JSX. Los estilos van a `index.css` como el
 *   resto: así se ajustan en un sitio y no compiten con las variables del
 *   portal.
 *
 *   El formulario muerto. El de la plantilla hace `preventDefault` y ya; aquí
 *   se conserva entero lo que había: la autenticación, el estado de envío, el
 *   aviso de error, los `autoComplete` y los textos por i18n en tres idiomas.
 */
/**
 * Si la sesión caducó a media tarea, la pantalla en la que se estaba.
 *
 * Solo para la misma cuenta, y solo rutas propias: una dirección que empezara
 * con `//` saldría del portal. Se gasta al leerla.
 */
const destinoTrasEntrar = (quien) => {
  try {
    const guardado = JSON.parse(sessionStorage.getItem(VOLVER_A) || 'null');
    sessionStorage.removeItem(VOLVER_A);
    if (!guardado || guardado.usuarioId !== quien?.id) return null;
    const ruta = String(guardado.ruta || '');
    return ruta.startsWith('/') && !ruta.startsWith('//') && !ruta.startsWith('/login') ? ruta : null;
  } catch {
    return null;
  }
};

const Login = () => {
  const { t } = useTranslation();
  const { login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  // Número de empleado. Se acepta también el correo para quien lo tenga:
  // el backend resuelve cualquiera de los dos.
  const [identificador, setIdentificador] = useState('');
  const [password, setPassword] = useState('');
  // Ver lo que se tecleó antes de enviarlo. En el celular, con el teclado
  // en pantalla, equivocarse en una letra de una frase larga es lo normal, y
  // sin esto la única pista es el «no pudimos iniciar sesión» de después.
  const [verPassword, setVerPassword] = useState(false);
  // Si se llegó aquí porque caducó la sesión, se dice. Antes se aterrizaba en
  // la puerta sin explicación y parecía que el portal había echado a la
  // persona por un fallo. La marca la deja `api/client.js` y se gasta al leerla.
  const [error, setError] = useState(() => {
    try {
      if (!sessionStorage.getItem(SESION_CADUCADA)) return '';
      sessionStorage.removeItem(SESION_CADUCADA);
      return t('auth.sesion_caducada');
    } catch {
      return '';
    }
  });
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setSubmitting(true);
    try {
      const quien = await login(identificador.trim(), password);
      // `replace` para que el botón de atrás no regrese al login.
      navigate(destinoTrasEntrar(quien) || location.state?.desde || '/', { replace: true });
    } catch (err) {
      // **El mensaje del servidor manda.** Pisarlo siempre con "Credenciales
      // invalidas" se llevaba por delante lo unico que la persona necesitaba
      // saber: que tras varios intentos el backend responde 429 ("Demasiados
      // intentos. Espere N segundos") y hay que esperar. Quien lo leia como
      // contrasena mal seguia probando, gastaba intentos y alargaba su propio
      // bloqueo. El texto de reserva solo entra cuando no hay red o cuando el
      // `detail` no es una frase -en un 422 de validacion es una lista de
      // objetos, y pintar eso seria peor que no decir nada.
      const detalle = err.response?.data?.detail;
      setError(typeof detalle === 'string' && detalle ? detalle : t('auth.error_login'));
      setSubmitting(false);
    }
  };

  return (
    <div className="puerta">
      <div className="puerta-idioma">
        <LanguageSelector />
      </div>

      <main className="apple-card ventana-cristal animate-fade-in puerta-panel">
        <header className="puerta-cabecera">
          <span className="puerta-rotulo">{t('auth.title')}</span>
          {/* El logotipo oficial, no el dibujado.

              **Va sobre una placa blanca a propósito.** El archivo de marca
              es la versión positiva: letras en azul y lema en azul, pensados
              para fondo claro. Compuesto directamente sobre el panel del
              login —casi negro— el lema desaparece y las letras quedan al
              límite. Sobre blanco los colores llegan exactamente como los
              define la marca, que es lo que se pide de un logotipo. Si algún
              día aparece la versión en negativo, se sustituye el archivo y se
              quita la placa. */}
          <img
            className="puerta-marca"
            src="/marca/cgr.png"
            alt="CGR · Form your world."
            width={230}
            height={116}
          />
          <p className="puerta-planta">{t('auth.subtitle')}</p>
        </header>

        {error && (
          <div className="puerta-error animate-scale-in">
            <AlertTriangle size={17} />
            {error}
          </div>
        )}

        <Formulario onSubmit={handleSubmit} autoComplete="on">
          <div className="campo-linea">
            <label htmlFor="identificador">{t('auth.identificador')}</label>
            <input
              id="identificador"
              type="text"
              placeholder={t('auth.identificador_ejemplo')}
              autoComplete="username"
              autoCapitalize="off"
              spellCheck={false}
              value={identificador}
              onChange={(e) => setIdentificador(e.target.value)}
              required
            />
            <span className="campo-linea-luz" aria-hidden="true" />
            <span className="campo-linea-ayuda">{t('auth.identificador_ayuda')}</span>
          </div>

          <div className="campo-linea">
            <label htmlFor="password">{t('auth.password')}</label>
            {/* El campo, el ojo y la línea de luz van juntos: la luz se enciende
                con `input:focus ~ .campo-linea-luz`, y para eso tiene que
                seguir siendo hermana del campo. */}
            <div className="campo-linea-entrada">
              <input
                id="password"
                type={verPassword ? 'text' : 'password'}
                autoComplete="current-password"
                // Sin corrector ni mayúscula automática: con la contraseña a la
                // vista, el corrector mejorado del navegador la mandaría a
                // revisar fuera, y el teclado del celular le cambiaría letras.
                spellCheck={false}
                autoCapitalize="off"
                autoCorrect="off"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
              <button
                type="button"
                className="campo-linea-ojo"
                onClick={() => setVerPassword((v) => !v)}
                // Que pulsarlo no le quite el foco al campo: se sigue escribiendo.
                onMouseDown={(e) => e.preventDefault()}
                aria-controls="password"
                aria-pressed={verPassword}
                aria-label={verPassword ? t('auth.ocultar_password') : t('auth.mostrar_password')}
                title={verPassword ? t('auth.ocultar_password') : t('auth.mostrar_password')}
              >
                {verPassword ? <EyeOff size={18} aria-hidden="true" /> : <Eye size={18} aria-hidden="true" />}
              </button>
              <span className="campo-linea-luz" aria-hidden="true" />
            </div>
          </div>

          {/* El botón de la gota. La gota vive detrás del texto y crece al
              pasar el ratón; el `filter` del contenedor la funde con el borde
              del botón, que es lo que hace que parezca líquido y no una caja
              que se estira. */}
          <div className="boton-gota">
            <span className="boton-gota-liquido" aria-hidden="true" />
            <button type="submit" className="boton-gota-base" disabled={submitting}>
              {submitting ? t('auth.logging_in') : t('auth.login_btn')}
            </button>
          </div>
        </Formulario>

        <footer className="puerta-pie">
          <Link to="/activar">{t('activar.primera_vez')}</Link>
          <Link to="/terminos" className="puerta-pie-legal">{t('terminos.enlace')}</Link>
        </footer>
      </main>
    </div>
  );
};

export default Login;

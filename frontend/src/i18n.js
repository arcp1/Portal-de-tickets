import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';

import esTranslation from './locales/es.json';

/**
 * **Solo el español viaja en el paquete.** Los tres idiomas iban dentro
 * siempre —unos 180 KB de texto que cada computadora descargaba y parseaba
 * para usar uno—, y en las de la planta, que no son nuevas, eso se nota en
 * cada carga. El inglés y el francés se piden cuando alguien los elige.
 */
const CARGADORES = {
  en: () => import('./locales/en.json'),
  fr: () => import('./locales/fr.json'),
};

const CLAVE = 'portal_tickets_lang';

/** `localStorage` puede lanzar —modo privado, políticas del navegador—, y
 *  aquí lanzaba antes de montar nada: el portal no arrancaba. */
const leerGuardado = () => {
  try { return localStorage.getItem(CLAVE); } catch { return null; }
};

const cargarIdioma = async (codigo) => {
  if (!CARGADORES[codigo] || i18n.hasResourceBundle(codigo, 'translation')) return;
  const modulo = await CARGADORES[codigo]();
  i18n.addResourceBundle(codigo, 'translation', modulo.default, true, true);
};

/** Cambia el idioma de todo el portal y lo recuerda. Única puerta para eso. */
export const cambiarIdioma = async (codigo) => {
  try {
    await cargarIdioma(codigo);
  } catch {
    // Sin red para traer el idioma: se queda en el actual en vez de mostrar
    // claves sin traducir.
    return;
  }
  i18n.changeLanguage(codigo);
  try { localStorage.setItem(CLAVE, codigo); } catch { /* se olvida al recargar */ }
};

i18n
  .use(initReactI18next)
  .init({
    resources: { es: { translation: esTranslation } },
    // Arranca en español; el guardado se aplica en cuanto llegue (abajo).
    lng: 'es',
    fallbackLng: 'es',
    partialBundledLanguages: true,
    interpolation: {
      escapeValue: false
    }
  });

// El idioma del documento sigue al del portal: con `lang="es"` fijo, un
// lector de pantalla leía el texto inglés o francés con voz española.
i18n.on('languageChanged', (codigo) => {
  document.documentElement.lang = codigo;
});

const guardado = leerGuardado();
if (guardado && guardado !== 'es') cambiarIdioma(guardado);

export default i18n;

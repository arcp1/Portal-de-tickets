import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';

import esTranslation from './locales/es.json';
import enTranslation from './locales/en.json';
import frTranslation from './locales/fr.json';

const resources = {
  es: { translation: esTranslation },
  en: { translation: enTranslation },
  fr: { translation: frTranslation }
};

i18n
  .use(initReactI18next)
  .init({
    resources,
    lng: localStorage.getItem('portal_tickets_lang') || 'es',
    fallbackLng: 'es',
    interpolation: {
      escapeValue: false
    }
  });

export default i18n;

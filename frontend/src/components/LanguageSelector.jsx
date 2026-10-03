import React from 'react';
import { useTranslation } from 'react-i18next';
import { Globe } from 'lucide-react';
import Selector from './Selector';
import { cambiarIdioma } from '../i18n';

const LanguageSelector = () => {
  const { i18n, t } = useTranslation();

  const changeLanguage = (lang) => { cambiarIdioma(lang); };

  return (
    <div style={{ display: 'inline-flex', alignItems: 'center', gap: '6px' }}>
      <Globe size={16} style={{ color: 'var(--text-secondary)' }} />
      <Selector
        value={i18n.language}
        onChange={(e) => changeLanguage(e.target.value)}
        className="form-select"
        textoBoton={(i18n.language || 'es').slice(0, 2).toUpperCase()}
        aria-label={t('navbar.idioma')}
        style={{ padding: '4px 10px', fontSize: '0.8rem', height: '32px', width: 'auto' }}
      >
        {/* Sin banderas: son parejas de indicadores regionales, y Windows no
            trae esa fuente — las dibuja como las dos letras sueltas en una
            cajita ("MX", "US"), que es justo lo que se veía roto. El nombre
            del idioma en su propio idioma se entiende en cualquier sistema. */}
        <option value="es">Español</option>
        <option value="en">English</option>
        <option value="fr">Français</option>
      </Selector>
    </div>
  );
};

export default LanguageSelector;

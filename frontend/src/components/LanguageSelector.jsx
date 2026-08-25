import React from 'react';
import { useTranslation } from 'react-i18next';
import { Globe } from 'lucide-react';

const LanguageSelector = () => {
  const { i18n } = useTranslation();

  const changeLanguage = (lang) => {
    i18n.changeLanguage(lang);
    localStorage.setItem('portal_tickets_lang', lang);
  };

  return (
    <div style={{ display: 'inline-flex', alignItems: 'center', gap: '6px' }}>
      <Globe size={16} style={{ color: 'var(--text-secondary)' }} />
      <select
        value={i18n.language}
        onChange={(e) => changeLanguage(e.target.value)}
        className="form-select"
        style={{
          padding: '4px 10px',
          fontSize: '0.8rem',
          height: '32px',
          background: 'rgba(255, 255, 255, 0.05)',
          border: '1px solid var(--border-color)',
          borderRadius: 'var(--radius-sm)'
        }}
      >
        <option value="es">🇲🇽 Español</option>
        <option value="en">🇺🇸 English</option>
        <option value="fr">🇫🇷 Français</option>
      </select>
    </div>
  );
};

export default LanguageSelector;

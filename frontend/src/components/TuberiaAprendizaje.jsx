import React from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { CheckCircle2, AlertTriangle, ArrowRight, ThumbsUp, ThumbsDown, Sparkles } from 'lucide-react';

/**
 * Nivel 2: por dónde entra el conocimiento, y dónde se está atascando.
 *
 * El portal aprende por una tubería de cuatro tramos:
 *
 *     ticket resuelto → indexado → consolidado en procedimiento → tema nuevo
 *
 * Cada tramo puede pararse por su cuenta, y **parado no avisa**. Un Ollama
 * caído al cerrar un ticket significa que ese ticket se guarda sin vector y no
 * vuelve a aparecer en ninguna búsqueda; el portal no falla, simplemente deja
 * de aprender. Sin esta pantalla eso se descubre meses después, cuando alguien
 * pregunta por qué el asistente no sabe nada nuevo.
 *
 * Por eso se dibujan los cuatro tramos aunque estén en cero: lo que interesa no
 * es la cifra de cada uno, es **dónde se corta la cadena**.
 */

const TuberiaAprendizaje = ({ aprendizaje }) => {
  const { t } = useTranslation();
  if (!aprendizaje) return null;

  const etapas = aprendizaje.etapas || [];

  return (
    <div className="tuberia">
      {etapas.map((etapa, i) => {
        // Una etapa que recibió cosas y no dejó pasar ninguna está rota. Que
        // todo esté en cero desde el principio no lo está: es un portal nuevo.
        const rota = etapa.atasco;
        const seco = etapa.de === 0;

        return (
          <React.Fragment key={etapa.clave}>
            {i > 0 && (
              <div className={`tuberia-flecha${rota ? ' tuberia-flecha-rota' : ''}`}>
                <ArrowRight size={16} aria-hidden="true" />
              </div>
            )}
            <div
              className="tuberia-etapa"
              data-estado={rota ? 'rota' : seco ? 'seca' : 'viva'}
            >
              <div className="tuberia-cifra">{etapa.valor}</div>
              <div className="tuberia-nombre">
                {t(`conciencia.etapa.${etapa.clave}`)}
              </div>
              {etapa.de != null && (
                <div className="tuberia-de">
                  {t('conciencia.de_n', { n: etapa.de })}
                </div>
              )}
              {rota && (
                <div className="tuberia-aviso">
                  <AlertTriangle size={12} aria-hidden="true" />
                  {t(`conciencia.atasco.${etapa.clave}`)}
                </div>
              )}
            </div>
          </React.Fragment>
        );
      })}
    </div>
  );
};

/** Lo que hay que atender, en una lista, o el visto bueno si no hay nada. */
export const AvisosAprendizaje = ({ aprendizaje, hayConocimiento = true }) => {
  const { t } = useTranslation();
  if (!aprendizaje) return null;

  const pendientes = [];

  // El orden **es** la prioridad, de lo que rompe la búsqueda a lo que solo
  // está pendiente de que alguien lo mire.
  //
  // Éste va primero porque es el que más conocimiento tiene retenido: son
  // tickets ya resueltos, con su solución escrita, que no existen para
  // ninguna búsqueda. El cierre nunca se bloquea por culpa de la IA, así que
  // si Ollama estaba caído ese día quedaron aquí — y el portal no lo dice por
  // su cuenta.
  if (aprendizaje.pendientes_indexar > 0) {
    pendientes.push({
      clave: 'pendientes_indexar',
      grave: true,
      texto: t('conciencia.aviso.pendientes_indexar', { n: aprendizaje.pendientes_indexar }),
      comando: 'docker compose exec backend python reindexar_kb.py',
    });
  }

  if (aprendizaje.sin_vector > 0) {
    pendientes.push({
      clave: 'sin_vector',
      grave: true,
      texto: t('conciencia.aviso.sin_vector', { n: aprendizaje.sin_vector }),
      comando: 'docker compose exec backend python reindexar_kb.py',
    });
  }

  (aprendizaje.avisos || []).forEach((a) => {
    pendientes.push({
      clave: `cat-${a.kb_id}`,
      grave: true,
      texto: t('conciencia.aviso.categoria_dudosa', {
        titulo: a.titulo,
        etiqueta: t(`conciencia.cat.${a.etiqueta}`, a.etiqueta),
        sugerida: t(`conciencia.cat.${a.sugerida}`, a.sugerida),
      }),
    });
  });

  // Hay material suficiente y ningun procedimiento escrito. No es una averia:
  // las soluciones generales **se proponen a mano**, por diseno —la maquina
  // redacta el borrador y una persona lo publica—. Lo que faltaba era decir
  // donde se pulsa, porque si no la etapa se queda en rojo para siempre sin
  // que nadie sepa que hacer con ella.
  const atascoProcedimientos = (aprendizaje.etapas || [])
    .find((e) => e.clave === 'procedimientos' && e.atasco);
  if (atascoProcedimientos) {
    pendientes.push({
      clave: 'proponer',
      texto: t('conciencia.aviso.proponer'),
      enlace: '/soluciones',
    });
  }

  if (aprendizaje.pendiente_de_revision > 0) {
    pendientes.push({
      clave: 'borradores',
      texto: t('conciencia.aviso.borradores', { n: aprendizaje.pendiente_de_revision }),
    });
  }
  if (aprendizaje.temas_pendientes > 0) {
    pendientes.push({
      clave: 'temas',
      texto: t('conciencia.aviso.temas', { n: aprendizaje.temas_pendientes }),
    });
  }

  if (!pendientes.length) {
    // **Sin nada escrito no hay visto bueno que dar.**
    //
    // "Nada pendiente: el conocimiento esta al dia y bien etiquetado" es cierto
    // —no hay avisos— y a la vez enganoso el primer dia: no hay conocimiento
    // que pueda estar al dia. En verde y con palomita se lee como "todo bien"
    // justo cuando lo unico que hay que hacer es empezar a escribir.
    //
    // Es el mismo fallo que tenia el panel de votos pintando un 13 % de verde,
    // y lo encontro la misma herramienta: `scripts/vista-previa.py vacio`.
    if (!hayConocimiento) {
      return (
        <div className="conciencia-sin-avisos" data-nivel="vacio">
          <Sparkles size={15} aria-hidden="true" />
          {t('conciencia.nada_que_revisar')}
        </div>
      );
    }
    return (
      <div className="conciencia-sin-avisos">
        <CheckCircle2 size={15} aria-hidden="true" />
        {t('conciencia.sin_avisos')}
      </div>
    );
  }

  return (
    <ul className="conciencia-avisos">
      {pendientes.map((p) => (
        <li key={p.clave} className={p.grave ? 'grave' : undefined}>
          <AlertTriangle size={14} aria-hidden="true" />
          <div>
            <span>{p.texto}</span>
            {/* El comando va escrito, no detrás de un botón: esto corre en el
                servidor, no en el navegador, y un botón que promete hacerlo
                mentiría sobre dónde ocurre. */}
            {p.comando && <code className="conciencia-comando">{p.comando}</code>}
            {/* Enlace y no comando: esto se hace en el portal, no en el
                servidor, y decir donde es la mitad del aviso. */}
            {p.enlace && (
              <Link to={p.enlace} className="conciencia-enlace-aviso">
                {t('conciencia.ir_alli')} <ArrowRight size={12} aria-hidden="true" />
              </Link>
            )}
          </div>
        </li>
      ))}
    </ul>
  );
};

/** Lo que la gente vota bajo cada sugerencia, que ahora **pesa en el orden**.
 *
 * Se calculaba desde el principio y no se ensenaba en ninguna parte. Ahora
 * importa mas: desde que existe `ajuste_por_utilidad`, estos votos no son solo
 * una estadistica, mueven el orden de lo que el asistente recupera. Una tasa
 * que se desploma es la senal de que hay conocimiento que ya no sirve.
 */
export const Realimentacion = ({ aprendizaje }) => {
  const { t } = useTranslation();
  const r = aprendizaje?.realimentacion;

  if (!r || !r.votados) {
    // Sin votos no se inventa un porcentaje: se dice que aun no hay.
    return (
      <div className="conciencia-realimentacion" data-nivel="vacia">
        <ThumbsUp size={14} aria-hidden="true" />
        {t('conciencia.sin_votos')}
      </div>
    );
  }

  const pct = Math.round((r.ratio || 0) * 100);

  // **El color tiene que decir lo mismo que la cifra.**
  //
  // La primera version pintaba de verde cualquier tasa con tal de que hubiera
  // votos, y en la vista previa del estado "roto" salio «4 de 30 sirvieron
  // (13 %)» con el estilo de buena noticia. Un 13 % significa que la base de
  // conocimiento falla dos de cada tres veces, y ademas —desde que los votos
  // pesan en el orden— que el lazo esta hundiendo activamente casi todo lo que
  // hay escrito. Eso no se pinta en verde.
  //
  // El corte de abajo va en la mitad porque ahi esta el cambio de sentido: por
  // debajo, una sugerencia estorba mas veces de las que ayuda.
  const nivel = pct >= 65 ? 'bien' : pct >= 40 ? 'regular' : 'mal';
  const Icono = nivel === 'mal' ? ThumbsDown : ThumbsUp;

  return (
    <div className="conciencia-realimentacion" data-nivel={nivel}>
      <Icono size={14} aria-hidden="true" />
      <span>
        {t('conciencia.votos', { utiles: r.utiles, votados: r.votados, pct })}
        {nivel === 'mal' && ` ${t('conciencia.votos_mal')}`}
      </span>
    </div>
  );
};

export default TuberiaAprendizaje;

'use strict';
(() => {
  const D = window.LAB_DATA;
  const STORE = 'el-espejo:laboratorio:prototype:demo:v1';
  const $ = (selector) => document.querySelector(selector);
  const escape = (value = '') => String(value).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const paths = {
    info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7h.01"/>',
    capture: '<path d="m15 4 5 5M4 20l5-1L20 8a2 2 0 0 0-5-5L4 14Z"/>',
    notes: '<rect x="5" y="3" width="14" height="18" rx="2"/><path d="M9 8h6M9 12h6M9 16h4"/>',
    graph: '<circle cx="12" cy="12" r="3"/><circle cx="4" cy="5" r="2"/><circle cx="20" cy="6" r="2"/><circle cx="18" cy="20" r="2"/><path d="m6 7 4 3m4 0 4-3m-5 8 4 3"/>',
    lab: '<path d="M9 3h6M10 3v6L4 19a1 1 0 0 0 1 2h14a1 1 0 0 0 1-2L14 9V3M7 15h10M10 12h4"/><circle cx="12" cy="17" r=".5"/>',
    arrow: '<path d="M5 12h14m-6-6 6 6-6 6"/>',
    back: '<path d="M19 12H5m6-6-6 6 6 6"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    close: '<path d="m6 6 12 12M6 18 18 6"/>',
    check: '<path d="m5 12 4 4L19 6"/>',
    eye: '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/>',
    search: '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/>',
    edit: '<path d="m16 3 5 5-12 12-6 1 1-6ZM14 5l5 5"/>',
    settings: '<path d="m9 3-1 3-3 1 1 3-2 2 2 2-1 3 3 1 1 3h6l1-3 3-1-1-3 2-2-2-2 1-3-3-1-1-3Z"/><circle cx="12" cy="12" r="3"/>',
    lock: '<rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3M12 14v3"/>',
    leaf: '<path d="M5 20C-1 9 8 3 21 3c0 13-6 21-16 17ZM5 20 16 9"/>',
    spark: '<path d="m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5ZM20 2v4m-2-2h4"/>',
    audio: '<path d="M4 10v4m4-7v10m4-14v18m4-14v10m4-7v4"/>',
    history: '<path d="M3 5v5h5M3 10a9 9 0 1 1 1 8M12 7v5l3 2"/>',
    list: '<path d="M9 6h12M9 12h12M9 18h12M3 6h1M3 12h1M3 18h1"/>',
    chevron: '<path d="m9 5 7 7-7 7"/>',
    minus: '<path d="M5 12h14"/>',
    reset: '<path d="M4 9V4h5M4 4l6 6m10 5v5h-5m5 0-6-6M15 4h5v5M4 15v5h5"/>',
  };
  const icon = (name) => `<svg class="icon" viewBox="0 0 24 24" aria-hidden="true">${paths[name] || paths.spark}</svg>`;
  const note = id => D.notes.find(item => item.id === id);
  const draftDemo = () => ({ ...structuredClone(D.examples.podcast), sample: ['n4', 'n6', 'n7'], kind: 'podcast', step: 2, revision: 1, comments: [] });
  const demoAxis = () => ({ id: 'valores', ...structuredClone(D.examples.values), kind: 'values', version: 1, enabled: true, hasResults: true, resultsVersion: 1 });
  let stored;
  let storageAvailable = true;
  try { stored = JSON.parse(localStorage.getItem(STORE) || 'null'); } catch { storageAvailable = false; }
  const state = {
    draft: stored?.draft?.sample ? stored.draft : stored?.initialized ? null : draftDemo(),
    axes: Array.isArray(stored?.axes) ? stored.axes : [demoAxis()],
    welcomeDismissed: stored?.welcomeDismissed === true,
    page: 'inicio', preview: null, history: [], historyIndex: -1, resultMode: 'graph',
    selected: '', selectedTag: '', graphRevealed: null, zoom: 1, search: '',
    graphVisibility: { note: true, finding: true, label: true }, graphModel: null, graphEntity: null, graphFocusTag: '',
    busy: false, doneCount: 0, compiling: false, scenario: '', returnToResults: false,
    axisId: 'valores', savedAxisId: '', feedback: '',
  };
  let previousFocus;
  let toastTimer;
  let jobGeneration = 0;
  let graphController = null;

  function save() {
    try {
      localStorage.setItem(STORE, JSON.stringify({ initialized: true, draft: state.draft, axes: state.axes, welcomeDismissed: state.welcomeDismissed }));
      storageAvailable = true;
    } catch { storageAvailable = false; }
  }
  function toast(text) {
    const el = $('#toast'); el.textContent = text; el.hidden = false;
    clearTimeout(toastTimer); toastTimer = setTimeout(() => { el.hidden = true; }, 4000);
  }
  const pill = (text, style = '') => `<span class="pill ${style}">${escape(text)}</span>`;
  const tags = items => `<div class="tags">${items.map(t => `<span class="tag">${escape(t)}</span>`).join('')}</div>`;
  const brand = `<img src="../app-refresh/el-espejo-mark.png" alt="">El Espejo`;
  function navigation(mobile = false) {
    return [
      ['capture', 'Capturar', '../app-refresh/#capture'],
      ['notes', mobile ? 'Material' : 'Tu material', '../app-refresh/#material'],
      ['graph', 'Constelaciones', '../app-refresh/#graph'],
      ['lab', 'Laboratorio', '#inicio'],
    ].map(([i, label, href]) => `${!mobile && i === 'lab' ? '<p class="nav-divider">OTRAS MIRADAS</p>' : ''}<a class="button" href="${href}" ${i === 'lab' ? 'aria-current="page"' : ''}>${icon(i)}<span>${label}</span></a>`).join('');
  }
  function shell(content) {
    return `<div class="layout"><aside class="sidebar" aria-label="Tu espacio"><a class="brand" href="../app-refresh/#capture">${brand}</a><p class="tagline">Un espacio para escucharte.</p><nav aria-label="Secciones principales">${navigation()}</nav><footer><a class="button" href="../app-refresh/#settings">${icon('settings')}Ajustes</a><p>Un lugar para probar, a tu ritmo.</p></footer></aside><div class="workspace"><header class="topbar"><a class="brand" href="../app-refresh/#capture">${brand}</a><span class="top-context">TU ESPACIO PERSONAL / LABORATORIO</span><div class="top-actions"><span class="prototype-label">PROTOTIPO</span><button class="icon-button quiet" data-action="scenarios" aria-label="Probar escenarios de la demostración" title="Probar escenarios">${icon('settings')}</button><button class="avatar" data-action="about" aria-label="Información de esta demostración">M</button></div></header><main id="main" tabindex="-1">${content}</main><nav class="bottom-nav" aria-label="Secciones principales, móvil">${navigation(true)}</nav></div></div>`;
  }
  function home() {
    const draft = state.draft;
    const showWelcome = !state.welcomeDismissed && !draft && !state.axes.length;
    return `<header class="home-header"><h1>Laboratorio</h1><button class="text-button home-help" data-action="lab-help">${icon('info')}Cómo funciona</button></header>
      ${draft ? `<section class="draft-resume" aria-labelledby="resume-title"><div><p class="kicker">EN CONSTRUCCIÓN</p><h2 id="resume-title">${escape(draft.title || 'Tu próxima mirada')}</h2><span class="meta">${draft.sample.length ? `${draft.sample.length} de 5 notas elegidas` : 'Tu borrador está listo para continuar'}</span></div><button class="text-button" data-action="resume">Continuar${icon('arrow')}</button></section>` : ''}
      ${showWelcome ? `<section class="welcome-card" aria-labelledby="welcome-title"><span class="welcome-symbol" aria-hidden="true">${icon('spark')}</span><h2 id="welcome-title">Una mirada nueva sobre tus notas</h2><p>Un eje busca lo que te interesa observar. Podés probarlo en cinco notas y ajustarlo antes de activarlo.</p><div class="welcome-actions"><button class="primary" data-action="new">Crear mi primer eje${icon('arrow')}</button><button class="quiet" data-action="dismiss-welcome">Ahora no</button></div></section>` : `<div class="section-heading axes-heading"><div><h2>Tus ejes</h2>${state.axes.length ? `<span class="meta">${state.axes.length} ${state.axes.length === 1 ? 'mirada' : 'miradas'}</span>` : ''}</div><button class="text-button" data-action="new">${icon('plus')}Crear un eje</button></div><div class="axes-grid">${state.axes.length ? state.axes.map(axisCard).join('') : `<div class="empty"><h2>Tu primera mirada empieza acá.</h2><p>Creá un eje cuando quieras. La ayuda sigue disponible en «Cómo funciona».</p><button class="secondary" data-action="new">Crear mi primer eje${icon('arrow')}</button></div>`}</div>`}
      <p class="footnote">${icon('lock')}Este prototipo usa notas ficticias. No modifica tus notas ni se conecta a tu cuenta.</p>`;
  }
  function laboratoryHelp() {
    showModal('Cómo funciona Laboratorio', `<p class="help-intro">Una mirada para encontrar nuevos hilos en lo que escribís, a tu ritmo.</p><div class="help-topics"><details><summary>Qué es un eje</summary><p>Es una mirada sobre tus notas: lo que te importa, ideas para un proyecto o una pregunta que te acompaña. Contá qué querés encontrar con tus palabras.</p></details><details><summary>Probar y ajustar</summary><ol><li><strong>Contá qué querés mirar.</strong> Podés partir de un ejemplo.</li><li><strong>Elegí cinco notas.</strong> Revisá los hallazgos y las citas que los sustentan.</li><li><strong>Ajustá hasta que te sirva.</strong> Después, elegí si querés activar el eje para notas nuevas.</li></ol><p>Las notas de la prueba quedan aparte de los resultados del eje activo.</p></details><details><summary>Explorar los resultados</summary><p>Tocá notas o etiquetas para abrir sus conexiones en el grafo. Las referencias de abajo permiten mostrar u ocultar tipos de nodo.</p><p>Cada hallazgo conserva su cita y el acceso a la nota completa. También podés recorrer todo desde la vista Lista.</p></details></div><div class="modal-actions"><button class="secondary" data-action="close-modal">Entendido</button></div>`, 'help-sheet');
  }
  function axisCard(a) {
    return `<article class="axis-card"><div class="card-top"><span class="axis-symbol sage">${icon(a.kind === 'podcast' ? 'audio' : 'leaf')}</span>${pill(a.enabled ? 'Activo' : 'En pausa', a.enabled ? '' : 'neutral')}</div><h3>${escape(a.title)}</h3><p>${a.kind === 'podcast' ? 'Ideas que merecen un espacio para volver a pensarlas.' : 'Una mirada sobre las maneras de vivir y relacionarte que querés cultivar.'}</p>${a.hasResults ? tags(a.kind === 'podcast' ? ['Relatos cotidianos', 'Conversaciones'] : ['Presencia', 'Autonomía', 'Vínculos']) : '<span class="meta">Esperando tus próximas notas</span>'}<div class="card-footer"><span class="meta">Versión ${a.version}${a.hasResults ? ' · 4 notas conectadas' : ''}</span><button class="text-button" data-action="open-axis" data-id="${escape(a.id)}">${a.hasResults ? 'Explorar' : 'Ver eje'}${icon('arrow')}</button></div></article>`;
  }
  function steps(current) {
    return `<ol class="steps" aria-label="Pasos de creación">${['Tu mirada', 'Tus notas', 'Probar y ajustar'].map((label, i) => `<li class="${i + 1 === current ? 'current' : i + 1 < current ? 'complete' : ''}" ${i + 1 === current ? 'aria-current="step"' : ''}><span class="step-number">${i + 1 < current ? '✓' : i + 1}</span><span>${label}</span></li>`).join('')}</ol>`;
  }
  const backHome = () => `<button class="back-link" data-action="home">${icon('back')}Laboratorio</button>`;
  function draftForm() {
    const d = state.draft;
    if (!d) return home();
    const recheck = state.returnToResults && d.sample.length === 5;
    return `${backHome()}<section class="workflow">${steps(1)}<div class="intro"><p class="kicker">${d.axisId ? 'AJUSTAR TU EJE' : 'UNA MIRADA NUEVA'}</p><h1>¿Qué querés observar?</h1><p>No hace falta definir categorías. Contá qué te interesa encontrar y para qué te serviría.</p></div><div class="form-layout"><div><label class="field" for="axis-title"><span class="field-label">Dale un nombre<span class="meta">Breve y tuyo</span></span><input id="axis-title" maxlength="80" value="${escape(d.title)}" autocomplete="off" placeholder="Por ejemplo, lo que me importa"></label><label class="field" for="axis-purpose"><span class="field-label">Contá qué te gustaría mirar</span><textarea id="axis-purpose" maxlength="4000" placeholder="Quiero reconocer… Me serviría para…">${escape(d.purpose)}</textarea><span class="field-help">Podés contar qué esperás encontrar y también qué preferís dejar afuera.</span></label><p class="example-label">Si te ayuda, empezá con una de estas ideas.</p><div class="example-buttons"><button data-action="example" data-kind="values" class="${d.kind === 'values' ? 'selected' : ''}">${icon('leaf')}Valores personales</button><button data-action="example" data-kind="podcast" class="${d.kind === 'podcast' ? 'selected' : ''}">${icon('audio')}Ideas para un podcast</button></div></div><aside class="side-note"><h2>Una intención,<br>muchas posibilidades.</h2><p>Buscamos entender tu mirada, sin obligarte a anticipar todo lo que puede aparecer.</p><p>Vas a poder probarla, leer las evidencias y afinarla antes de activarla.</p><svg class="hint-visual" viewBox="0 0 185 115" fill="none" aria-hidden="true"><path d="m30 55 63-22 60 46M93 33l-5 65M30 55l58 43" stroke="#697c63"/><circle cx="93" cy="33" r="13" stroke="#c6bc8a"/><circle cx="30" cy="55" r="5" fill="#9dbda4"/><circle cx="153" cy="79" r="8" fill="#6e8d7c"/><circle cx="88" cy="98" r="4" fill="#b1b494"/></svg></aside></div><div class="action-bar"><span class="save-status" id="save-status">${icon('edit')}${storageAvailable ? 'Borrador en este dispositivo' : 'Borrador en esta pestaña'}</span><button class="primary" id="continue-button" data-action="${recheck ? 'preview' : 'sample'}" ${validDraft() ? '' : 'disabled'}>${recheck ? 'Volver a probar' : 'Elegir cinco notas'}${icon('arrow')}</button></div></section>`;
  }
  function validDraft() { return !!state.draft?.title?.trim() && state.draft.purpose.trim().length >= 20; }
  function noteOptions() {
    const term = state.search.toLocaleLowerCase('es');
    const found = D.notes.filter(n => `${n.title} ${n.type}`.toLocaleLowerCase('es').includes(term));
    return found.length ? found.map(n => `<article class="note-choice"><input type="checkbox" id="select-${n.id}" data-note-choice="${n.id}" ${state.draft.sample.includes(n.id) ? 'checked' : ''} ${state.draft.sample.length === 5 && !state.draft.sample.includes(n.id) ? 'disabled' : ''}><label for="select-${n.id}"><strong>${escape(n.title)}</strong><small>${n.type === 'Audio' ? icon('audio') : ''}${n.type}${n.duration ? ` · ${n.duration}` : ''} · ${n.date}</small></label><button class="icon-button" data-action="read" data-id="${n.id}" aria-label="Leer ${escape(n.title)}">${icon('eye')}</button></article>`).join('') : '<div class="empty"><p>No hay notas con esa búsqueda.</p><button class="secondary" data-action="clear-search">Limpiar búsqueda</button></div>';
  }
  function sample() {
    if (!state.draft) return home();
    return `${backHome()}<section class="workflow">${steps(2)}<div class="intro"><p class="kicker">${escape(state.draft.title || 'TU MUESTRA')}</p><h1>Cinco notas para empezar.</h1><p>Elegí notas que conozcas y que te ayuden a reconocer si esta mirada tiene sentido para vos.</p></div><div class="search-wrap">${icon('search')}<input id="note-search" type="search" placeholder="Buscar en tus notas" aria-label="Buscar en tus notas" value="${escape(state.search)}"></div><div class="selection-toolbar"><span class="selection-count" id="selection-count" role="status">${state.draft.sample.length} de 5 notas elegidas</span><button class="text-button" data-action="suggested">Elegir cinco de ejemplo${icon('plus')}</button></div><div class="note-options" id="note-options">${noteOptions()}</div><p class="selection-hint">Vamos a conservar estas mismas notas entre ajustes, para que puedas comparar lo que cambia.</p><div class="action-bar"><button class="quiet" data-action="describe">${icon('back')}Tu mirada</button><button class="primary" id="preview-button" data-action="preview" ${state.draft.sample.length === 5 ? '' : 'disabled'}>Probar esta mirada${icon('spark')}</button></div></section>`;
  }
  function findings(p = state.preview) {
    if (!p) return [];
    return D.findings[p.kind].filter(f => p.sample.includes(f.note) && f.note !== p.failedNote).map(f => {
      const result = structuredClone(f);
      if (p.comments?.length) {
        if (/menos etiquetas|una etiqueta/i.test(p.comments.at(-1))) result.tags = result.tags.slice(0, 1);
        result.content += p.kind === 'values' ? ' Esta lectura conserva la intención expresada, sin asumir que sea una práctica sostenida.' : ' La propuesta se conserva como una idea independiente para que puedas retomarla por separado.';
      }
      return result;
    });
  }
  function loading() {
    const p = state.preview;
    return `${backHome()}<section class="workflow">${steps(3)}<div class="intro"><p class="kicker">${escape(p.title)}</p><h1>Buscando los primeros hilos.</h1><p>Vamos nota por nota. Puede haber varios hallazgos, o ninguno: no hace falta forzar conexiones.</p></div><section class="loading-panel" aria-live="polite"><div class="loading-heading"><span class="spinner" aria-hidden="true"></span><h2>${state.compiling ? (p.comments.length ? 'Afinando tu mirada…' : 'Preparando tu mirada…') : `${state.doneCount} de 5 notas revisadas`}</h2></div><ul class="loading-list">${p.sample.map((id, i) => `<li class="${i > state.doneCount || state.compiling ? 'pending' : ''}">${i < state.doneCount ? icon('check') : i === state.doneCount && !state.compiling ? '<span class="spinner" aria-hidden="true"></span>' : '<span class="dot" aria-hidden="true"></span>'}<span>${escape(note(id).title)}</span></li>`).join('')}</ul></section><p class="footnote">${icon('lock')}Es una prueba con datos de ejemplo. Tus notas reales no se consultan.</p></section>`;
  }
  function activePreview() { return state.historyIndex >= 0 ? state.history[state.historyIndex] : state.preview; }
  function draftChanged(p) {
    const d = state.draft;
    return !d || p.title !== d.title || p.purpose !== d.purpose || [...p.sample].sort().join() !== [...d.sample].sort().join() || JSON.stringify(p.comments) !== JSON.stringify(d.comments);
  }
  function results() {
    if (state.busy) return loading();
    const p = activePreview();
    if (!p) return draftForm();
    const fs = findings(p);
    const older = state.historyIndex !== state.history.length - 1;
    const changed = draftChanged(p);
    return `${backHome()}<section class="workflow">${steps(3)}<div class="result-intro"><div class="result-meta">${pill(`Prueba ${p.number}`, 'warm')}<span class="meta">${p.sample.length} notas · ${fs.length} hallazgos${p.comments.length ? ' · Mirada ajustada' : ''}</span></div><h1>Esto aparece en tus notas.</h1><p>Recorré los hallazgos y sus fragmentos de origen.<br>¿Se parecen a lo que querías mirar?</p></div><div class="intent-summary"><button class="intent-peek" data-action="view-purpose" aria-label="Leer la intención completa de esta prueba"><span class="meta">TU MIRADA · ${escape(p.title)}</span><p>${escape(p.purpose)}</p><span class="read-intent">Leer intención completa</span></button><button class="icon-button" data-action="edit-purpose" aria-label="Editar la intención de tu eje">${icon('edit')}</button></div>
      ${changed && !older ? `<div class="notice"><strong>Cambiaste tu mirada o la muestra.</strong><p>Estos resultados pertenecen a la prueba anterior. Probá los cambios antes de activar el eje.</p><button class="text-button" data-action="${state.draft.sample.length === 5 ? 'preview' : 'change-sample'}">${state.draft.sample.length === 5 ? 'Probar los cambios' : 'Completar las cinco notas'}${icon('arrow')}</button></div>` : ''}
      ${older ? `<div class="notice"><strong>Estás viendo una prueba anterior.</strong><p>Podés compararla con la más reciente antes de decidir.</p><button class="text-button" data-action="latest">Volver a la prueba actual${icon('arrow')}</button></div>` : ''}
      ${p.expired ? `<div class="notice"><strong>Esta prueba ya venció.</strong><p>Tu intención y las notas elegidas siguen en el borrador. Volvé a probar para poder activar el eje.</p><button class="text-button" data-action="preview">Volver a probar${icon('arrow')}</button></div>` : ''}
      ${p.failedNote ? `<div class="notice"><strong>No pudimos revisar una de las notas.</strong><p>Los otros resultados están disponibles. Reintentá la nota pendiente antes de activar el eje.</p><button class="text-button" data-action="retry">Reintentar nota pendiente${icon('arrow')}</button></div>` : ''}
      <div class="result-toolbar"><div class="segmented" role="group" aria-label="Vista de resultados"><button data-action="mode" data-mode="graph" aria-pressed="${state.resultMode === 'graph'}">${icon('graph')}Grafo</button><button data-action="mode" data-mode="list" aria-pressed="${state.resultMode === 'list'}">${icon('list')}Lista</button></div><button class="text-button" data-action="change-sample">Cambiar las cinco notas${icon('edit')}</button></div>${resultsBody(p)}
      ${!older ? `<section class="refinement" aria-labelledby="refinement-title"><h2 id="refinement-title">¿Querés afinar la mirada?</h2><p>Contá qué te gustaría cambiar. Volvemos a probar sobre las mismas cinco notas.</p><label class="sr-only" for="refinement-comment">Qué te gustaría ajustar</label><textarea id="refinement-comment" maxlength="1500" placeholder="${p.kind === 'podcast' ? 'Por ejemplo: separá las propuestas y conservá los ejemplos que me ayuden a retomarlas…' : 'Por ejemplo: prefiero que sugieras posibilidades, sin afirmar cuáles son mis valores…'}">${escape(state.feedback)}</textarea><div class="refine-actions"><span class="meta">${state.history.length > 1 ? `<button class="text-button" data-action="previous">${icon('history')}Ver prueba anterior</button>` : 'Podés ajustar tantas veces como necesites.'}</span><button class="secondary" id="refine-button" data-action="refine" ${state.feedback.trim() ? '' : 'disabled'}>Ajustar y volver a probar${icon('arrow')}</button></div></section>` : ''}
      <div class="accept-bar"><button class="primary" data-action="accept-dialog" ${older || changed || p.failedNote || p.expired ? 'disabled' : ''}>${icon('check')}${state.draft?.axisId ? 'Guardar esta versión' : 'Me sirve, activar eje'}</button><p>Se aplicará a tus próximas notas.<br>Las notas de esta prueba quedan aparte.</p></div></section>`;
  }
  function resultsBody(p, active = false) {
    if (state.resultMode === 'list') return list(p);
    const fs = findings(p);
    if (!fs.length) return `<div class="empty"><h2>No aparecieron hallazgos.</h2><p>Eso también puede tener sentido. Podés revisar las notas o ajustar tu intención sin forzar un resultado.</p><button class="secondary" data-action="mode" data-mode="list">Ver las notas revisadas</button></div>`;
    const graphMarkup = graph(p);
    return `<div class="graph-projection"><p id="graph-description" class="projection-description" aria-live="polite">${graphDescription()}</p><div class="results-layout"><div>${graphMarkup}<p class="footnote">${icon('eye')}Las líneas punteadas resumen conexiones. Tocá cualquier relación para recuperar sus hallazgos y citas.</p></div><aside id="finding-detail" class="finding-detail" aria-label="Detalle de la selección" tabindex="-1">${graphDetail(p, active)}</aside></div></div>`;
  }
  function graphLayerControls() {
    const last = Object.values(state.graphVisibility).filter(Boolean).length === 1;
    return [['note', 'Notas'], ['finding', 'Hallazgos'], ['label', 'Etiquetas']].map(([kind, label]) => {
      const on = state.graphVisibility[kind];
      return `<button class="layer-toggle" data-action="graph-layer" data-kind="${kind}" aria-label="${label}" aria-pressed="${on}" aria-describedby="graph-layer-help" title="${on ? 'Ocultar' : 'Mostrar'} ${label.toLocaleLowerCase('es')}" ${last && on ? 'disabled' : ''}><i class="legend-shape ${kind}" aria-hidden="true"></i><span>${label}</span></button>`;
    }).join('');
  }
  function graphDescription() {
    const {note:n, finding:f, label:l} = state.graphVisibility;
    if (n && f && l) return 'Seguí el recorrido nota → hallazgo → etiqueta. Apagá un tipo para concentrarte en lo que querés mirar.';
    if (n && l) return 'Los hallazgos están ocultos. Las líneas punteadas conectan notas y etiquetas; cada conexión conserva sus hallazgos y citas.';
    if (n && f) return 'Las etiquetas están ocultas. Las citas unen notas y hallazgos; las líneas punteadas muestran qué etiquetas comparten los hallazgos.';
    if (f && l) return 'Las notas están ocultas. Explorá los hallazgos y sus etiquetas; la nota de origen y la cita siguen disponibles en el detalle.';
    if (f) return 'Sólo hallazgos. Las líneas punteadas muestran las etiquetas que comparten; cada hallazgo conserva su cita y su nota de origen.';
    if (n) return 'Sólo notas. Las líneas punteadas reúnen notas cuyos hallazgos comparten etiquetas. Tocá una conexión para ver de dónde surge.';
    return 'Sólo etiquetas. Una línea punteada indica que dos etiquetas coinciden en un mismo hallazgo. Tocala para leerlo con su cita.';
  }
  function graphElements() {
    return [...state.graphModel.nodes, ...state.graphModel.edges].map(x => x.data);
  }
  function graphLegend() {
    return `<div id="graph-layer-controls" class="layer-controls" role="group" aria-label="Tipos de nodo">${graphLayerControls()}</div><span id="graph-layer-help" class="sr-only">Tocá cada referencia para mostrar u ocultar ese tipo de nodo. Debe quedar al menos uno visible.</span><button class="quiet icon-button" data-action="arrange" aria-label="Ordenar" title="Ordenar grafo">${icon('graph')}</button>`;
  }

  function list(p) {
    const fs = findings(p);
    return `<div class="findings-list">${p.sample.map(id => { const own = fs.filter(f => f.note === id); const n = note(id); return `<section class="finding-group"><header><div><h3>${escape(n.title)}</h3><span class="meta">${n.type} · ${n.date}</span></div>${pill(p.failedNote === id ? 'Pendiente' : `${own.length} ${own.length === 1 ? 'hallazgo' : 'hallazgos'}`, own.length ? '' : 'neutral')}</header>${own.length ? own.map(f => `<button class="finding-item" data-action="finding" data-id="${f.id}"><span><strong>${escape(f.title)}</strong>${f.tags.map(t => `<span class="tag">${escape(t)}</span>`).join('')}</span>${icon('chevron')}</button>`).join('') : `<p class="no-findings">${p.failedNote === id ? 'Esta nota todavía no pudo revisarse.' : 'No apareció un hallazgo fundamentado desde esta mirada. No hace falta que todas las notas tengan uno.'}</p>`}<button class="text-button" data-action="read" data-id="${id}">Leer nota${icon('arrow')}</button></section>`; }).join('')}</div>`;
  }
  function graphContext() {
    if (state.page.startsWith('eje-')) {
      const a = state.axes.find(x => x.id === state.axisId);
      return a ? { ...a, comments: [], sample: [...new Set(D.findings[a.kind].map(f => f.note))] } : null;
    }
    return activePreview();
  }
  function graph(p) {
    const fs = findings(p);
    state.graphModel = window.LabGraph.project(fs, { visibility: state.graphVisibility, revealedFindingIds: state.graphRevealed, focusTag: state.graphFocusTag });
    state.graphFocusTag = state.graphModel.rootTag;
    const elements = graphElements();
    state.graphEntity = elements.find(e => e.id === state.graphEntity?.id) || state.graphModel.nodes.find(n => n.data.id === state.graphModel.rootId)?.data;
    return `<section class="graph-panel" aria-label="Conexiones de los hallazgos"><div class="graph-top"><span>${escape(p.title)}</span><span class="graph-caption">${state.graphModel.visibleFindingIds.length} de ${fs.length} hallazgos</span></div><div class="graph-canvas" id="lab-graph" role="img" tabindex="0" aria-label="Grafo de notas, hallazgos y etiquetas. Podés arrastrar nodos y tocar conexiones. Para leer con teclado, usá la vista Lista."></div><div class="graph-tools"><div><button class="icon-button quiet" data-action="zoom-out" aria-label="Alejar grafo">${icon('minus')}</button><button class="icon-button quiet" data-action="zoom-in" aria-label="Acercar grafo">${icon('plus')}</button><button class="icon-button quiet" data-action="fit-graph" aria-label="Ajustar grafo a la pantalla">${icon('reset')}</button></div></div><div class="graph-legend">${graphLegend()}</div><p class="graph-help">Tocá un nodo para seguir el hilo. Arrastrá para moverte.</p></section>`;
  }
  function graphDetail(p, active = false) {
    const fs = findings(p), e = state.graphEntity;
    if (!e) return '<p>Elegí una nota o una conexión para seguir el hilo.</p>';
    let body = '';
    if (e.kind === 'label') {
      state.selectedTag = e.tag;
      body = tagDetail(p);
    } else if (e.kind === 'membership') {
      const matches = fs.filter(f => e.findingIds.includes(f.id));
      body = `<p class="kicker">UNA CONEXIÓN</p><h2>${escape(e.tag)}</h2><p>En <strong>${escape(note(e.noteId).title)}</strong>, ${matches.length === 1 ? 'este hallazgo sostiene' : 'estos hallazgos sostienen'} la conexión con esta etiqueta.</p>${matches.map(f => `<article class="connection-finding"><h3>${escape(f.title)}</h3><p>${escape(f.content)}</p><p class="evidence-label">LA CITA QUE LO SUSTENTA</p><blockquote>“${escape(f.quote)}”</blockquote><button class="text-button" data-action="read" data-id="${f.note}" data-finding="${f.id}">Leer en la nota completa${icon('arrow')}</button></article>`).join('')}`;
    } else if (e.kind === 'shared') {
      const matches = fs.filter(f => e.findingIds.includes(f.id));
      body = `<p class="kicker">ENTRE DOS HALLAZGOS</p><h2>Un hilo compartido.</h2>${tags(e.tags)}<p class="shared-explanation">Comparten estas etiquetas. Cada hallazgo conserva su propia idea y su nota de origen.</p>${matches.map(f => `<button class="finding-item" data-action="graph-finding" data-id="${f.id}"><span><strong>${escape(f.title)}</strong><small>${escape(note(f.note).title)}</small></span>${icon('chevron')}</button>`).join('')}`;
    } else if (e.kind === 'note-shared' || e.kind === 'label-shared') {
      const matches = fs.filter(f => e.findingIds.includes(f.id));
      body = `<p class="kicker">UNA CONEXIÓN RESUMIDA</p><h2>${e.kind === 'note-shared' ? 'Un hilo entre tus notas.' : 'Juntas en un hallazgo.'}</h2>${tags(e.tags)}<p>${e.kind === 'note-shared' ? 'Estas notas tienen hallazgos con etiquetas compartidas. Cada idea conserva su propio contexto.' : 'Estas etiquetas aparecen juntas en los siguientes hallazgos. Cada cita permite recuperar el contexto.'}</p>${matches.map(f => `<article class="connection-finding"><h3>${escape(f.title)}</h3><p>${escape(f.content)}</p><p class="evidence-label">${escape(note(f.note).title)}</p><blockquote>“${escape(f.quote)}”</blockquote><button class="text-button" data-action="read" data-id="${f.note}" data-finding="${f.id}">Leer en la nota completa${icon('arrow')}</button></article>`).join('')}`;
    } else if (e.kind === 'note') {
      const matches = fs.filter(f => f.note === e.noteId);
      body = `<p class="kicker">UNA NOTA · ${matches.length} HALLAZGOS</p><h2>${escape(note(e.noteId).title)}</h2><p>Elegí un hallazgo para recuperar su desarrollo y sus citas.</p>${matches.map(f => `<button class="finding-item" data-action="graph-finding" data-id="${f.id}"><span><strong>${escape(f.title)}</strong>${f.tags.map(t => `<span class="tag">${escape(t)}</span>`).join('')}</span>${icon('chevron')}</button>`).join('')}<button class="text-button" data-action="read" data-id="${e.noteId}">Leer nota completa${icon('arrow')}</button>`;
    } else {
      const f = fs.find(f => f.id === (e.findingId || e.findingIds?.[0]));
      body = f ? `${e.kind === 'evidence' ? '<p class="relation-caption">RELACIÓN CON SU NOTA · CITA DE ORIGEN</p>' : e.kind === 'tagging' ? `<p class="relation-caption">RELACIÓN CON LA ETIQUETA · ${escape(e.tag)}</p>` : ''}${detail(f, active)}` : '<p>Esta selección ya no está disponible en la prueba actual.</p>';
    }
    const hiddenSelection = !graphElements().some(item => item.id === e.id);
    return `${hiddenSelection ? '<p class="selection-hidden">Este elemento está oculto en el mapa. Su detalle sigue disponible.</p>' : ''}<button class="text-button back-to-graph" data-action="back-to-graph">${icon('back')}Volver al grafo</button>${body}`;
  }
  function selectGraphEntity(entity, moveFocus = true, expandNeighbors = true) {
    const p = graphContext(); if (!p || !entity) return;
    state.graphEntity = entity;
    let grew = false;
    if (expandNeighbors && ['note', 'finding', 'label'].includes(entity.kind)) {
      const fs = findings(p), revealed = new Set(state.graphModel.visibleFindingIds);
      const neighbors = fs.filter(f => entity.kind === 'note' ? f.note === entity.noteId : entity.kind === 'finding' ? f.id === entity.findingId : f.tags.some(t => t.toLocaleLowerCase('es').trim() === entity.tag.toLocaleLowerCase('es').trim()));
      neighbors.forEach(f => revealed.add(f.id));
      if (revealed.size > state.graphModel.visibleFindingIds.length) {
        grew = true;
        state.graphRevealed = [...revealed];
        state.graphModel = window.LabGraph.project(fs, { visibility: state.graphVisibility, revealedFindingIds: state.graphRevealed, focusTag: state.graphFocusTag });
        graphController?.update(state.graphModel, entity.id);
        $('.graph-caption').textContent = `${revealed.size} de ${fs.length} hallazgos`;
      }
    }
    if (entity.kind === 'finding') state.selected = entity.findingId;
    graphController?.select(entity.id);
    const target = $('#finding-detail');
    target.innerHTML = graphDetail(p, state.page.startsWith('eje-'));
    if (moveFocus) {
      target.focus({ preventScroll: true });
      if (innerWidth < 1150 && !grew) target.scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth', block: 'start' });
    }
  }
  function mountGraph() {
    const host = $('#lab-graph'); if (!host || !state.graphModel) return;
    graphController = window.LabGraph.mount(host, state.graphModel, data => selectGraphEntity(data));
    if (state.graphEntity) graphController.select(state.graphEntity.id);
  }
  function detail(f, active = false) {
    const n = note(f.note);
    return `<p class="kicker">UN HALLAZGO${active ? ' · VERSIÓN 1' : ''}</p><h2>${escape(f.title)}</h2><p>${escape(f.content)}</p>${tags(f.tags)}<p class="evidence-label">DE DÓNDE SURGE</p><blockquote>“${escape(f.quote)}”</blockquote><div class="finding-origin">${icon('notes')}<span>${escape(n.title)}<br>${n.type} · ${n.date}</span></div><button class="text-button" data-action="read" data-id="${n.id}" data-finding="${f.id}">Leer en la nota completa${icon('arrow')}</button>`;
  }
  function tagDetail(p) {
    const fs = findings(p).filter(f => f.tags.includes(state.selectedTag));
    return `<p class="kicker">UN HILO COMPARTIDO</p><h2>${escape(state.selectedTag)}</h2><p>${fs.length} hallazgos en ${new Set(fs.map(f => f.note)).size} notas se encuentran bajo esta etiqueta.</p>${fs.map(f => `<button class="finding-item" data-action="graph-finding" data-id="${f.id}"><span><strong>${escape(f.title)}</strong><small>${escape(note(f.note).title)}</small></span>${icon('chevron')}</button>`).join('')}`;
  }
  function axisPage() {
    const a = state.axes.find(x => x.id === state.axisId); if (!a) return home();
    const p = { ...a, comments: [], sample: a.hasResults ? [...new Set(D.findings[a.kind].map(f => f.note))] : [] };
    return `${backHome()}<section class="workflow"><div class="axis-header"><p class="kicker">TU EJE · VERSIÓN ${a.version}</p><div class="switch-control"><span>${a.enabled ? 'Activo' : 'En pausa'}</span><button class="switch" role="switch" aria-checked="${a.enabled}" aria-label="Activar ${escape(a.title)}" data-action="toggle-axis"><span class="switch-track"><span class="switch-knob"></span></span></button></div></div><div class="intro axis-intro"><h1>${escape(a.title)}</h1></div><details class="axis-description"><summary>Sobre este eje</summary><p>${escape(a.purpose)}</p><div class="version-info"><span>${a.hasResults ? '4 notas · 5 hallazgos de ejemplo' : 'Todavía sin notas procesadas'}</span><span>${a.enabled ? 'Se aplica a notas nuevas' : 'Las próximas notas no usarán este eje'}</span></div></details><div class="section-heading"><h2>Seguí un hilo</h2><button class="text-button" data-action="edit-axis">Ajustar esta mirada${icon('edit')}</button></div>${a.hasResults ? `<div class="result-toolbar"><div class="segmented" role="group" aria-label="Vista de resultados"><button data-action="mode" data-mode="graph" aria-pressed="${state.resultMode === 'graph'}">${icon('graph')}Grafo</button><button data-action="mode" data-mode="list" aria-pressed="${state.resultMode === 'list'}">${icon('list')}Lista</button></div><span class="meta">Resultados conservados · versión ${a.resultsVersion || 1}</span></div>${resultsBody(p, true)}` : `<div class="empty"><span class="axis-symbol sage">${icon('leaf')}</span><h2>Una mirada lista para crecer.</h2><p>Los hallazgos aparecerán con tus próximas notas.<br>Las cinco notas de prueba no se incorporaron.</p><button class="secondary" data-action="demo-explore">Ver una exploración de ejemplo${icon('arrow')}</button></div>`}<p class="footnote">${icon('lock')}Esta es una demostración. Activar o pausar sólo cambia este prototipo.</p></section>`;
  }
  function success() {
    const a = state.axes.find(x => x.id === state.savedAxisId); if (!a) return home();
    return `<section class="workflow"><div class="success-emblem">${icon('check')}</div><p class="kicker">${a.version > 1 ? 'UNA NUEVA VERSIÓN' : 'UNA MIRADA PROPIA'}</p><h1>${a.version > 1 ? 'Tu mirada ya está ajustada.' : 'Tu eje está listo.'}</h1><p>Elegiste una forma de volver a tus notas.<br>Ahora podés dejar que aparezcan nuevos hilos.</p><div class="success-card">${pill(a.enabled ? 'Activo' : 'En pausa', a.enabled ? '' : 'neutral')}<h2>${escape(a.title)}</h2><p>${escape(a.purpose)}</p><span class="meta">Versión ${a.version} · La misma mirada que acabás de probar</span></div><div class="success-actions"><button class="primary" data-action="open-axis" data-id="${a.id}">Ver mi eje${icon('arrow')}</button><button class="secondary" data-action="home">Volver al Laboratorio</button></div><p class="success-note">${a.enabled ? 'Se aplicará a las próximas notas.' : 'Conservamos la pausa. Podés activarlo cuando quieras.'} Las de la prueba quedan aparte.<br>Guardado únicamente en esta demostración${storageAvailable ? ', en este dispositivo' : ', durante esta sesión'}.</p></section>`;
  }
  function render({ focus = true, scroll = true } = {}) {
    const content = state.page === 'crear' ? draftForm() : state.page === 'muestra' ? sample() : state.page === 'resultados' ? results() : state.page.startsWith('eje-') ? axisPage() : state.page === 'guardado' ? success() : home();
    graphController?.destroy(); graphController = null;
    $('#app').innerHTML = shell(content);
    mountGraph();
    if (scroll) window.scrollTo(0, 0);
    if (focus) { const heading = $('main h1'); if (heading) { heading.tabIndex = -1; heading.focus({ preventScroll: true }); } }
  }
  function go(page) {
    clearTimeout(toastTimer); $('#toast').hidden = true;
    if (location.hash === `#${page}`) { state.page = page; render(); }
    else location.hash = page;
  }
  function freshDraft() {
    jobGeneration++; state.busy = false; state.scenario = ''; state.welcomeDismissed = true;
    state.draft = { title: '', purpose: '', sample: [], kind: '', step: 1, revision: 1, comments: [] };
    state.preview = null; state.history = []; state.historyIndex = -1; state.returnToResults = false;
    state.search = ''; state.feedback = ''; save(); go('crear');
  }
  function showModal(title, body, variant = '') {
    if (!$('.modal')) previousFocus = document.activeElement;
    $('#app').inert = true; document.body.style.overflow = 'hidden';
    $('#modal-root').innerHTML = `<div class="modal-backdrop"><section class="modal ${variant}" role="dialog" aria-modal="true" aria-labelledby="modal-title"><header class="modal-header"><h2 id="modal-title">${title}</h2><button class="icon-button" data-action="close-modal" aria-label="Cerrar diálogo">${icon('close')}</button></header><div class="modal-body">${body}</div></section></div>`;
    $('#modal-title').tabIndex = -1; $('#modal-title').focus();
  }
  function closeModal() {
    $('#modal-root').innerHTML = ''; $('#app').inert = false; document.body.style.overflow = '';
    if (previousFocus?.isConnected) previousFocus.focus({ preventScroll: true });
  }
  function readNote(id, findingId) {
    const n = note(id); if (!n) return;
    const f = [...D.findings.values, ...D.findings.podcast].find(item => item.id === findingId);
    const text = f ? escape(n.content).replace(escape(f.quote), `<mark>${escape(f.quote)}</mark>`) : escape(n.content);
    showModal(escape(n.title), `<span class="meta">${n.type}${n.duration ? ` · ${n.duration}` : ''} · ${n.date}</span><div class="reader-text">${text}</div><div class="modal-actions"><button class="secondary" data-action="close-modal">Volver</button></div>`);
  }
  function beginPreview() {
    if (!validDraft() || state.draft.sample.length !== 5 || state.busy) return;
    closeModal();
    const d = structuredClone(state.draft);
    const kind = d.kind || (/podcast|episodio|propuesta|producto/i.test(d.purpose) ? 'podcast' : 'values');
    state.preview = { ...d, kind, number: state.history.length + 1, expired: false, failedNote: '', comments: [...(d.comments || [])] };
    state.busy = true; state.compiling = true; state.doneCount = 0; state.selectedTag = '';
    state.selected = ''; state.graphRevealed = null; state.zoom = 1; state.feedback = '';
    const job = ++jobGeneration;
    go('resultados');
    setTimeout(() => {
      if (job !== jobGeneration) return;
      state.compiling = false;
      if (state.page === 'resultados') render({ focus: false, scroll: false });
      const advance = () => {
        if (job !== jobGeneration) return;
        state.doneCount++;
        if (state.doneCount === 5) {
          state.busy = false;
          if (state.scenario === 'failure') state.preview.failedNote = state.preview.sample[2];
          if (state.scenario === 'expired') state.preview.expired = true;
          state.scenario = '';
          state.history.push(state.preview); state.historyIndex = state.history.length - 1;
          state.returnToResults = false;
          if (state.page === 'resultados') render();
          else toast('Tu prueba de ejemplo está lista. Podés retomarla desde el borrador.');
        } else {
          if (state.page === 'resultados') render({ focus: false, scroll: false });
          setTimeout(advance, 430);
        }
      };
      setTimeout(advance, 430);
    }, 850);
  }
  function acceptPreview() {
    const p = activePreview();
    if (!p || p.failedNote || p.expired || draftChanged(p) || state.busy || state.historyIndex !== state.history.length - 1) return;
    let a = state.axes.find(x => x.id === p.axisId);
    if (a) { a.version++; a.title = p.title; a.purpose = p.purpose; }
    else { a = { id: `eje-${Date.now()}`, title: p.title, purpose: p.purpose, kind: p.kind, version: 1, enabled: true, hasResults: false }; state.axes.push(a); }
    state.savedAxisId = a.id; state.draft = null; state.returnToResults = false;
    closeModal(); save(); go('guardado');
  }
  function startScenario(name) {
    closeModal(); jobGeneration++; state.busy = false;
    if (name === 'first-visit' || name === 'empty') { state.welcomeDismissed = name !== 'first-visit'; state.axes = []; state.draft = null; state.preview = null; state.history = []; save(); go('inicio'); return; }
    if (name === 'reset') { state.welcomeDismissed = true; state.axes = [demoAxis()]; state.draft = draftDemo(); state.preview = null; state.history = []; state.historyIndex = -1; state.returnToResults = false; save(); go('inicio'); toast('Ejemplo inicial restablecido.'); return; }
    state.draft = { ...structuredClone(D.examples.values), kind: 'values', revision: 1, comments: [], step: 3 };
    state.history = []; state.historyIndex = -1; state.scenario = name; save(); beginPreview();
  }
  document.addEventListener('click', event => {
    const button = event.target.closest('[data-action]');
    if (!button) { if (event.target.classList.contains('modal-backdrop')) closeModal(); return; }
    const action = button.dataset.action;
    if (button.disabled) return;
    if (action === 'close-modal') { closeModal(); return; }
    if (action === 'lab-help') { laboratoryHelp(); return; }
    if (action === 'dismiss-welcome') { state.welcomeDismissed = true; save(); render({ scroll: false }); return; }
    if (action === 'home') { save(); go('inicio'); return; }
    if (action === 'new') {
      if (state.draft) showModal('Tenés una mirada en construcción.', '<p>Podés continuar donde la dejaste o empezar otra. Si empezás de nuevo, reemplazás el borrador de esta demostración.</p><div class="modal-actions"><button class="primary" data-action="resume">Continuar mi borrador</button><button class="secondary" data-action="new-confirm">Empezar otro eje</button></div>');
      else freshDraft();
    } else if (action === 'new-confirm') { closeModal(); freshDraft(); }
    else if (action === 'resume') { closeModal(); if (state.busy || state.preview) go('resultados'); else go(state.draft.step === 2 ? 'muestra' : 'crear'); }
    else if (action === 'example') { const ex = D.examples[button.dataset.kind]; state.draft.title = ex.title; state.draft.purpose = ex.purpose; state.draft.kind = button.dataset.kind; state.draft.revision++; save(); render({ focus: false, scroll: false }); $('#axis-title').focus({ preventScroll: true }); }
    else if (action === 'sample') { state.draft.step = 2; save(); go('muestra'); }
    else if (action === 'describe') { state.draft.step = 1; save(); go('crear'); }
    else if (action === 'suggested') { state.draft.sample = [...D.examples[state.draft.kind || 'values'].sample]; state.draft.revision++; save(); updateSelection(); toast('Elegiste cinco notas de ejemplo. Podés cambiar cualquiera.'); }
    else if (action === 'clear-search') { state.search = ''; $('#note-search').value = ''; updateSelection(); $('#note-search').focus(); }
    else if (action === 'read') readNote(button.dataset.id, button.dataset.finding);
    else if (action === 'preview') beginPreview();
    else if (action === 'mode') { state.resultMode = button.dataset.mode; render({ focus: false, scroll: false }); $(`[data-action="mode"][data-mode="${state.resultMode}"]`).focus({ preventScroll: true }); }
    else if (action === 'finding') { const f = findings(state.page.startsWith('eje-') ? { ...state.axes.find(x => x.id === state.axisId), sample: D.notes.map(n => n.id) } : activePreview()).find(x => x.id === button.dataset.id); if (f) showModal('Un hallazgo', detail(f)); }
    else if (action === 'graph-layer') {
      const kind = button.dataset.kind;
      if (state.graphVisibility[kind] && Object.values(state.graphVisibility).filter(Boolean).length === 1) return;
      state.graphVisibility[kind] = !state.graphVisibility[kind];
      state.graphModel = window.LabGraph.project(findings(graphContext()), { visibility: state.graphVisibility, revealedFindingIds: state.graphRevealed, focusTag: state.graphFocusTag });
      graphController?.update(state.graphModel);
      $('#graph-layer-controls').innerHTML = graphLayerControls();
      $('#graph-description').textContent = graphDescription();
      if (state.graphEntity) selectGraphEntity(state.graphEntity, false, false);
      $(`[data-action="graph-layer"][data-kind="${kind}"]`).focus({ preventScroll: true });
    } else if (action === 'graph-finding' || action === 'graph-tag' || action === 'graph-note') {
      const p = graphContext(), fs = findings(p), id = button.dataset.id;
      let e = state.graphModel.nodes.find(x => x.data.findingId === id)?.data;
      if (action === 'graph-finding' && !e) {
        const f = fs.find(x => x.id === id);
        if (f) e = { id: `finding:${id}`, kind: 'finding', findingId: id };
      }
      selectGraphEntity(e);
    } else if (action === 'back-to-graph') {
      $('#lab-graph')?.focus({ preventScroll: true });
      $('.graph-panel')?.scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth', block: 'start' });
    } else if (action === 'zoom-in' || action === 'zoom-out' || action === 'fit-graph' || action === 'arrange') {
      if (action === 'zoom-in') graphController?.zoom(1.25);
      else if (action === 'zoom-out') graphController?.zoom(.8);
      else if (action === 'arrange') graphController?.arrange();
      else graphController?.fit();
    } else if (action === 'edit-purpose') { state.returnToResults = true; go('crear'); }
    else if (action === 'view-purpose') showModal('La mirada de esta prueba', `<p class="kicker">${escape(activePreview().title)}</p><p>${escape(activePreview().purpose)}</p><div class="modal-actions"><button class="secondary" data-action="close-modal">Volver a los hallazgos</button><button class="primary" data-action="edit-purpose-modal">Editar mi intención${icon('edit')}</button></div>`);
    else if (action === 'edit-purpose-modal') { closeModal(); state.returnToResults = true; go('crear'); }
    else if (action === 'change-sample') { state.returnToResults = true; state.draft.step = 2; save(); go('muestra'); }
    else if (action === 'refine') { if (!state.feedback.trim()) return; state.draft.comments.push(state.feedback.trim()); state.draft.revision++; save(); beginPreview(); }
    else if (action === 'previous') { state.historyIndex = Math.max(0, state.historyIndex - 1); state.selected = ''; state.selectedTag = ''; render(); }
    else if (action === 'latest') { state.historyIndex = state.history.length - 1; state.selected = ''; state.selectedTag = ''; render(); }
    else if (action === 'retry') { const retried = state.preview, generation = jobGeneration; button.disabled = true; button.innerHTML = '<span class="spinner" aria-hidden="true"></span>Revisando la nota pendiente…'; setTimeout(() => { if (state.preview === retried && generation === jobGeneration) { retried.failedNote = ''; render({ scroll: false }); toast('La nota pendiente ya está revisada. Conservamos los otros resultados.'); } }, 1000); }
    else if (action === 'accept-dialog') showModal(state.draft?.axisId ? '¿Guardar esta nueva versión?' : '¿Activar esta mirada?', `<p>Vas a conservar exactamente la mirada de la prueba que acabás de revisar.</p><div class="success-card"><p class="kicker">${escape(activePreview().title)}</p><p>Se aplicará a las próximas notas. Las cinco notas de prueba quedan aparte.</p></div><div class="modal-actions"><button class="secondary" data-action="close-modal">Seguir revisando</button><button class="primary" data-action="accept">${icon('check')}${state.draft?.axisId ? 'Guardar versión' : 'Activar eje'}</button></div>`);
    else if (action === 'accept') acceptPreview();
    else if (action === 'open-axis') { state.axisId = button.dataset.id; state.selected = ''; state.selectedTag = ''; state.zoom = 1; state.graphRevealed = null; go(`eje-${state.axisId}`); }
    else if (action === 'toggle-axis') { const a = state.axes.find(x => x.id === state.axisId); a.enabled = !a.enabled; save(); render({ focus: false, scroll: false }); $('[data-action="toggle-axis"]').focus({ preventScroll: true }); toast(a.enabled ? 'Eje activo en la demostración.' : 'Eje en pausa. Los hallazgos anteriores se conservan.'); }
    else if (action === 'edit-axis' || action === 'edit-axis-confirm') {
      const a = state.axes.find(x => x.id === state.axisId);
      if (action !== 'edit-axis-confirm' && state.draft && state.draft.axisId !== a.id) { showModal('Ya tenés otro borrador.', '<p>Podés continuar esa mirada o reemplazar el borrador por los ajustes de este eje. Los ejes aceptados se conservan.</p><div class="modal-actions"><button class="secondary" data-action="resume">Continuar borrador</button><button class="primary" data-action="edit-axis-confirm">Reemplazar y ajustar</button></div>'); return; }
      closeModal(); jobGeneration++; state.busy = false;
      state.draft = { title: a.title, purpose: a.purpose, kind: a.kind, sample: [...D.examples[a.kind].sample], axisId: a.id, baseVersion: a.version, comments: [], revision: 1, step: 1 };
      state.preview = null; state.history = []; state.historyIndex = -1; state.returnToResults = false; save(); go('crear');
    } else if (action === 'demo-explore') { if (!state.axes.some(a => a.id === 'valores')) state.axes.push(demoAxis()); state.axisId = 'valores'; save(); go('eje-valores'); }
    else if (action === 'about') showModal('Un lugar para experimentar.', '<p>Laboratorio es una propuesta visual de El Espejo. Todo lo que aparece acá —notas, hallazgos y pruebas— es de ejemplo.</p><p>Podés recorrer el flujo completo. El borrador y los ejes de esta demo se conservan en este dispositivo, cuando el navegador lo permite.</p><p>No se llama a la API, no se usa inteligencia artificial y no se modifica tu cuenta.</p><button class="primary" data-action="close-modal">Seguir explorando</button>');
    else if (action === 'scenarios') showModal('Probar otros momentos.', '<p>Estos escenarios permiten revisar estados del recorrido con datos ficticios.</p><div class="scenario-list"><button data-action="scenario" data-name="first-visit"><span>Primera visita<small>Bienvenida breve, sin ejes ni borradores.</small></span></button><button data-action="scenario" data-name="empty"><span>Un Laboratorio vacío<small>Sin ejes ni borradores, con la bienvenida ya vista.</small></span></button><button data-action="scenario" data-name="failure"><span>Una nota pendiente<small>Conservar resultados y reintentar sólo lo que falta.</small></span></button><button data-action="scenario" data-name="expired"><span>Una prueba vencida<small>Retomar la intención y volver a probar.</small></span></button><button data-action="scenario" data-name="reset"><span>Restablecer la demostración<small>Volver al borrador y eje del inicio.</small></span></button></div>');
    else if (action === 'scenario') startScenario(button.dataset.name);
  });
  function updateSelection() {
    const focusId = document.activeElement?.id;
    $('#note-options').innerHTML = noteOptions();
    $('#selection-count').textContent = `${state.draft.sample.length} de 5 notas elegidas`;
    $('#preview-button').disabled = state.draft.sample.length !== 5;
    if (focusId?.startsWith('select-')) document.getElementById(focusId)?.focus({ preventScroll: true });
  }
  document.addEventListener('input', event => {
    if (event.target.id === 'axis-title' || event.target.id === 'axis-purpose') {
      state.draft[event.target.id === 'axis-title' ? 'title' : 'purpose'] = event.target.value;
      state.draft.revision++; save(); $('#continue-button').disabled = !validDraft();
      $('#save-status').innerHTML = `${icon('edit')}${storageAvailable ? 'Borrador guardado en este dispositivo' : 'Borrador en esta pestaña · almacenamiento no disponible'}`;
    } else if (event.target.id === 'note-search') { state.search = event.target.value; $('#note-options').innerHTML = noteOptions(); }
    else if (event.target.id === 'refinement-comment') { state.feedback = event.target.value; $('#refine-button').disabled = !state.feedback.trim(); }
  });
  document.addEventListener('change', event => {
    const id = event.target.dataset.noteChoice; if (!id) return;
    if (event.target.checked && state.draft.sample.length < 5) state.draft.sample.push(id);
    else state.draft.sample = state.draft.sample.filter(x => x !== id);
    state.draft.revision++;
    save(); updateSelection();
  });
  document.addEventListener('keydown', event => {
    if (event.target.matches('.graph-svg [role="button"]') && ['Enter', ' '].includes(event.key)) { event.preventDefault(); event.target.dispatchEvent(new MouseEvent('click', { bubbles: true })); }
    const modal = $('.modal'); if (!modal) return;
    if (event.key === 'Escape') { event.preventDefault(); closeModal(); }
    if (event.key === 'Tab') {
      const focusable = [...modal.querySelectorAll('button:not(:disabled), a[href], input, textarea, select, summary')];
      const first = focusable[0], last = focusable.at(-1);
      if (event.shiftKey && (document.activeElement === first || document.activeElement.id === 'modal-title')) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    }
  });
  function route() {
    let page = location.hash.slice(1) || 'inicio';
    if (page.startsWith('eje-')) { state.axisId = page.slice(4); if (!state.axes.some(a => a.id === state.axisId)) page = 'inicio'; }
    if (['crear', 'muestra'].includes(page) && !state.draft) page = 'inicio';
    if (page === 'resultados' && !state.preview) page = state.draft ? 'crear' : 'inicio';
    if (page === 'guardado' && !state.savedAxisId) page = 'inicio';
    state.page = page; render();
  }
  window.addEventListener('hashchange', route);
  save(); route();
})();

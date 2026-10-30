'use strict';

// Prepared fictional questions; no network, storage, model calls or real notes.
const scenarios = [
  {
    gentle: '¿Qué te hizo bien entre tantos cambios?',
    middle: '¿Cómo estás viviendo los cambios en tu trabajo?',
    deep: '¿Qué necesitás para sentirte más vos en esta etapa de cambios?',
  },
  {
    gentle: '¿Qué momento lindo compartiste con esa persona?',
    middle: '¿Cómo te sentís hoy en ese vínculo importante para vos?',
    deep: '¿Qué te gustaría expresar en ese vínculo y todavía no dijiste?',
  },
  {
    gentle: '¿Qué pequeño momento del día fue para vos?',
    middle: '¿Cómo te estás haciendo espacio en estos días?',
    deep: '¿Qué te cuesta priorizar cuando buscás tiempo para vos?',
  },
];
const microphoneIcon = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="9" y="3" width="6" height="12" rx="3"></rect><path d="M5.5 11.5a6.5 6.5 0 0 0 13 0M12 18v3m-3 0h6"></path></svg>';
const sendIcon = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12h14M13 6l6 6-6 6"></path></svg>';
const state = { scenario: 0, depth: 'middle', screen: 'invitation', mode: 'daily', dailyDraft: '', freeDraft: '', response: null, feedbackTarget: null, feedback: null };
const sheet = document.querySelector('#feedback-sheet');
let feedbackTimer;
const answer = document.querySelector('#answer');
const action = document.querySelector('#capture-action');
const depthButtons = [...document.querySelectorAll('[data-depth]')];
let toastTimer;

function currentQuestion() {
  return scenarios[state.scenario][state.depth];
}
function announce(message) {
  const toast = document.querySelector('#toast');
  clearTimeout(toastTimer);
  toast.textContent = message;
  toast.hidden = false;
  toastTimer = setTimeout(() => { toast.hidden = true; }, 3200);
}
function animate(element) {
  if (!window.matchMedia('(prefers-reduced-motion: reduce)').matches && element.animate) {
    element.animate([{ opacity: 0, transform: 'translateY(6px)' }, { opacity: 1, transform: 'translateY(0)' }], { duration: 220, easing: 'ease-out' });
  }
}
function showScreen(name, focusTarget) {
  clearTimeout(feedbackTimer);
  state.screen = name;
  for (const screen of document.querySelectorAll('.screen')) screen.hidden = screen.id !== `${name}-screen`;
  const screen = document.querySelector(`#${name}-screen`);
  animate(screen);
  (focusTarget || screen).focus({ preventScroll: true });
  window.scrollTo({ top: 0, behavior: 'instant' });
}
function renderQuestion() {
  document.querySelector('#question').textContent = currentQuestion();
  if (state.mode === 'daily') document.querySelector('#compose-question').textContent = currentQuestion();
  for (const button of depthButtons) {
    const selected = button.dataset.depth === state.depth;
    button.setAttribute('aria-checked', String(selected));
    button.tabIndex = selected ? 0 : -1;
  }
}
function selectDepth(depth) {
  if (state.depth === depth) return;
  state.depth = depth;
  renderQuestion();
  animate(document.querySelector('#question'));
}
function renderAction() {
  const hasText = Boolean(answer.value.trim());
  action.innerHTML = hasText ? sendIcon : microphoneIcon;
  action.setAttribute('aria-label', hasText ? 'Guardar respuesta' : 'Grabar respuesta de voz');
}
function showHome() {
  showScreen('home', document.querySelector('#new-note'));
  document.querySelector('#reopen-feedback').hidden = !state.feedbackTarget || Boolean(state.feedback);
}
function openFeedback() {
  if (!state.feedbackTarget || state.feedback || sheet.open || state.screen !== 'home') return;
  showTopicOptions(false);
  sheet.showModal();
  document.querySelector('#sheet-title').focus({ preventScroll: true });
  animate(sheet);
}
function showTopicOptions(open) {
  document.querySelector('#feedback-overview').hidden = open;
  document.querySelector('#topic-options').hidden = !open;
  document.querySelector('#topic-feedback').setAttribute('aria-expanded', String(open));
  sheet.setAttribute('aria-labelledby', open ? 'topic-title' : 'sheet-title');
}
function openComposer(mode) {
  state.mode = mode;
  answer.value = mode === 'daily' ? state.dailyDraft : state.freeDraft;
  document.querySelector('#compose-question').textContent = mode === 'daily' ? currentQuestion() : '¿Qué te gustaría sacar de tu cabeza?';
  document.querySelector('#back').innerHTML = `<span aria-hidden="true">←</span> ${mode === 'daily' ? 'La pregunta' : 'Tu espacio'}`;
  document.querySelector('#compose-status').textContent = '';
  renderAction();
  showScreen('compose', answer);
}
for (const button of depthButtons) button.addEventListener('click', () => selectDepth(button.dataset.depth));
document.querySelector('.depth-control').addEventListener('keydown', event => {
  if (!['ArrowRight', 'ArrowDown', 'ArrowLeft', 'ArrowUp', 'Home', 'End'].includes(event.key)) return;
  event.preventDefault();
  const index = depthButtons.findIndex(button => button.dataset.depth === state.depth);
  const direction = ['ArrowRight', 'ArrowDown'].includes(event.key) ? 1 : -1;
  const nextIndex = event.key === 'Home' ? 0 : event.key === 'End' ? depthButtons.length - 1 : (index + direction + depthButtons.length) % depthButtons.length;
  selectDepth(depthButtons[nextIndex].dataset.depth);
  depthButtons[nextIndex].focus();
});
document.querySelector('#respond').addEventListener('click', () => openComposer('daily'));
document.querySelector('#back').addEventListener('click', () => {
  if (state.mode === 'daily') showScreen('invitation', document.querySelector('#respond'));
  else showHome();
});
document.querySelector('#another').addEventListener('click', () => {
  state.scenario = (state.scenario + 1) % scenarios.length;
  renderQuestion();
  animate(document.querySelector('#question'));
  if (state.dailyDraft.trim()) announce('Tu texto sigue acá si querés retomarlo.');
});
document.querySelector('#skip').addEventListener('click', showHome);
answer.addEventListener('input', () => {
  state[state.mode === 'daily' ? 'dailyDraft' : 'freeDraft'] = answer.value;
  renderAction();
});
action.addEventListener('click', () => {
  if (!answer.value.trim()) {
    document.querySelector('#compose-status').textContent = 'La voz no está habilitada en este prototipo.';
    return;
  }
  const isDaily = state.mode === 'daily';
  state.response = { scenario: state.scenario, depth: state.depth, question: isDaily ? currentQuestion() : null, text: answer.value };
  if (isDaily) {
    state.feedbackTarget = { scenario: state.scenario, depth: state.depth, question: currentQuestion() };
    state.feedback = null;
  }
  state[isDaily ? 'dailyDraft' : 'freeDraft'] = '';
  answer.value = '';
  document.querySelector('#recent-note').hidden = false;
  document.querySelector('#recent-excerpt').textContent = state.response.text;
  document.querySelector('#prototype-note').textContent = 'Envío simulado · Tu respuesta no se guarda ni se envía';
  showHome();
  if (isDaily) feedbackTimer = setTimeout(openFeedback, 400);
});
document.querySelector('#new-note').addEventListener('click', () => openComposer('free'));
document.querySelector('#daily-question').addEventListener('click', () => {
  state.mode = 'daily';
  renderQuestion();
  showScreen('invitation', document.querySelector('#respond'));
});
document.querySelector('#reopen-feedback').addEventListener('click', openFeedback);
document.querySelector('#topic-feedback').addEventListener('click', () => {
  showTopicOptions(true);
  document.querySelector('#topic-title').focus();
});
document.querySelector('#topic-back').addEventListener('click', () => {
  showTopicOptions(false);
  document.querySelector('#topic-feedback').focus();
});
for (const id of ['close-feedback', 'dismiss-feedback']) document.querySelector(`#${id}`).addEventListener('click', () => sheet.close());
sheet.addEventListener('click', event => {
  if (event.target !== sheet) return;
  const rect = sheet.getBoundingClientRect();
  if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) sheet.close();
});
sheet.addEventListener('close', () => {
  if (state.screen !== 'home') return;
  const target = state.feedback ? document.querySelector('#new-note') : document.querySelector('#reopen-feedback');
  target.focus({ preventScroll: true });
});
for (const button of document.querySelectorAll('[data-feedback]')) {
  button.addEventListener('click', () => {
    state.feedback = { value: button.dataset.feedback, ...state.feedbackTarget };
    document.querySelector('#reopen-feedback').hidden = true;
    document.querySelector('#prototype-note').textContent = 'Envío y feedback simulados · No se guarda contenido';
    sheet.close();
    announce('Gracias por contarnos.');
  });
}
renderQuestion();
renderAction();

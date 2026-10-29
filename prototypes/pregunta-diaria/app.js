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
const feedbackMessages = {
  helpful: 'Tu mirada nos ayuda a encontrar preguntas que conecten con vos.',
  unrelated: 'A veces una pregunta no encaja. También está bien.',
  later: 'Hay momentos para explorar y momentos para dejar descansar.',
  closed: 'Este tema puede descansar. Vos marcás el ritmo.',
  stop: 'Tu límite importa. Vos elegís qué querés compartir.',
};
const microphoneIcon = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="9" y="3" width="6" height="12" rx="3"></rect><path d="M5.5 11.5a6.5 6.5 0 0 0 13 0M12 18v3m-3 0h6"></path></svg>';
const sendIcon = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12h14M13 6l6 6-6 6"></path></svg>';
const state = { scenario: 0, depth: 'middle', screen: 'invitation', response: null, feedback: null };
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
  state.screen = name;
  for (const screen of document.querySelectorAll('.screen')) screen.hidden = screen.id !== `${name}-screen`;
  const screen = document.querySelector(`#${name}-screen`);
  animate(screen);
  (focusTarget || screen).focus({ preventScroll: true });
  window.scrollTo({ top: 0, behavior: 'instant' });
}
function renderQuestion() {
  document.querySelector('#question').textContent = currentQuestion();
  document.querySelector('#compose-question').textContent = currentQuestion();
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
function finish(saved) {
  document.querySelector('#end-title').textContent = saved ? 'Gracias por hacerte un lugar.' : 'Por hoy, está bien.';
  document.querySelector('#end-copy').textContent = saved ? 'Podés seguir con tu día.' : 'Este espacio sigue acá para cuando quieras.';
  document.querySelector('#end-kicker').textContent = saved ? 'ESTE MOMENTO ES TUYO' : 'A TU RITMO';
  document.querySelector('#end-symbol').textContent = saved ? '✓' : '◡';
  document.querySelector('#pending').hidden = !saved;
  document.querySelector('#give-feedback').hidden = false;
  document.querySelector('#prototype-note').textContent = saved ? 'Envío simulado · Tu respuesta no se guarda ni se envía' : 'Contenido ficticio · Sin conexión con tus notas';
  showScreen('end');
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
document.querySelector('#respond').addEventListener('click', () => {
  document.querySelector('#compose-status').textContent = '';
  showScreen('compose', answer);
});
document.querySelector('#back').addEventListener('click', () => showScreen('invitation', document.querySelector('#respond')));
document.querySelector('#another').addEventListener('click', () => {
  state.scenario = (state.scenario + 1) % scenarios.length;
  renderQuestion();
  animate(document.querySelector('#question'));
  if (answer.value.trim()) announce('Tu texto sigue acá si querés retomarlo.');
});
document.querySelector('#skip').addEventListener('click', () => finish(false));
answer.addEventListener('input', renderAction);
action.addEventListener('click', () => {
  if (!answer.value.trim()) {
    document.querySelector('#compose-status').textContent = 'La voz no está habilitada en este prototipo.';
    return;
  }
  state.response = { scenario: state.scenario, depth: state.depth, question: currentQuestion(), text: answer.value };
  finish(true);
});
document.querySelector('#give-feedback').addEventListener('click', () => showScreen('feedback'));
document.querySelector('#feedback-back').addEventListener('click', () => showScreen('end', document.querySelector('#give-feedback')));
for (const button of document.querySelectorAll('[data-feedback]')) {
  button.addEventListener('click', () => {
    state.feedback = { value: button.dataset.feedback, question: state.response?.question || currentQuestion() };
    document.querySelector('#end-title').textContent = 'Gracias por contarnos.';
    document.querySelector('#end-copy').textContent = feedbackMessages[button.dataset.feedback];
    document.querySelector('#end-kicker').textContent = 'VOS MARCÁS EL RITMO';
    document.querySelector('#end-symbol').textContent = '✧';
    document.querySelector('#pending').hidden = true;
    document.querySelector('#give-feedback').hidden = true;
    document.querySelector('#prototype-note').textContent = 'Feedback simulado · Tu elección no se guarda';
    showScreen('end');
  });
}
document.querySelector('#restart').addEventListener('click', () => {
  state.response = null;
  state.feedback = null;
  document.querySelector('#prototype-note').textContent = 'Contenido ficticio · Sin conexión con tus notas';
  showScreen('invitation', document.querySelector('#respond'));
});
renderQuestion();
renderAction();

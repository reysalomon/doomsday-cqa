(() => {
const API = window.CQA_API_BASE || '';
const root = document.getElementById('cqa-root');
const state = {filters: {language: '', channel: '', dataset: '', status: ''}, selected: new Set(), timer: null};

function h(tag, props, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else if (k === 'class') el.className = v;
    else if (k === 'value' || k === 'checked' || k === 'disabled' || k === 'selected') el[k] = v;
    else el.setAttribute(k, v);
  }
  el.append(...kids.flat().filter(k => k !== null && k !== undefined && k !== false));
  return el;
}

async function api(path, options) {
  const response = await fetch(API + path, options && {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(options)});
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : 'Ошибка запроса');
  return body;
}

function toast(text, bad) {
  document.querySelector('.toast')?.remove();
  const el = h('div', {class: 'toast' + (bad ? ' bad' : ''), role: 'status'}, text);
  document.body.append(el);
  setTimeout(() => el.remove(), bad ? 7000 : 3000);
}
const guard = fn => async (...args) => { try { return await fn(...args); } catch (e) { toast(e.message, true); } };

const answerText = a => a === 'yes' ? 'Да' : a === 'no' ? 'Нет' : a === 'na' ? 'N/A' : String(a);
const fmt = n => n === null || n === undefined ? '—' : Number(n).toFixed(2);
const when = iso => iso ? new Date(iso).toLocaleString('ru-RU') : '—';
const clock = s => `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(Math.floor(s % 60)).padStart(2, '0')}`;
const STATUS = {pending: ['В очереди', 'warn'], running: ['Оценивается', 'warn'], done: ['Готово', 'ok'], error: ['Ошибка', 'bad']};
const EVIDENCE = {verified: ['Цитата проверена', 'ok'], checked_range: ['Проверен участок', 'ok'], na_explained: ['N/A обосновано', 'ok'],
  quote_mismatch: ['Цитата не найдена в реплике', 'bad'], invalid_turn: ['Реплика не найдена', 'bad'], no_evidence: ['Нет доказательства', 'bad'], no_quote: ['Нет цитаты', 'bad']};
const grade = n => n === null || n === undefined ? '' : n >= 80 ? 'ok' : n >= 60 ? 'warn' : 'bad';
const tag = ([text, kind]) => h('span', {class: 'tag ' + (kind || '')}, text);
const options = c => [...(c.type === 'scale' ? c.scale.map(s => s.value) : ['yes', 'no']), ...(c.na_allowed ? ['na'] : [])];

// Static, trusted SVG icons (Lucide-style strokes).
const ICONS = {
  chat: '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
  shield: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="m9 12 2 2 4-4"/>',
  scale: '<path d="M12 3v18M5 21h14M3 7h18M6 7l-3 7a3 3 0 0 0 6 0zM18 7l-3 7a3 3 0 0 0 6 0z"/>',
  list: '<path d="M10 6h11M10 12h11M10 18h11"/><path d="m3 6 1 1 2-2M3 12l1 1 2-2M3 18l1 1 2-2"/>',
  phone: '<path d="M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2.1 4.2 2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1 1 .4 1.9.7 2.8a2 2 0 0 1-.5 2.1L8 9.9a16 16 0 0 0 6 6l1.3-1.3a2 2 0 0 1 2.1-.4c.9.3 1.8.6 2.8.7a2 2 0 0 1 1.7 2z"/>',
  spark: '<path d="M12 3l1.9 5.8L20 11l-6.1 2.2L12 19l-1.9-5.8L4 11l6.1-2.2z"/>'};
function icon(name) {
  const el = h('span', {class: 'icon', 'aria-hidden': 'true'});
  el.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${ICONS[name]}</svg>`;
  return el;
}

function shell(active, content) {
  const link = (href, id, ic, text) => h('a', {href, class: active === id ? 'on' : ''}, icon(ic), h('span', {}, text));
  const engine = h('div', {class: 'engine'}, 'Модель подключается…');
  api('/api/health').then(i => { engine.replaceChildren(h('span', {class: 'dot'}), h('span', {}, h('b', {}, `Claude ${i.model}`), h('small', {}, i.provider === 'claude_cli' ? 'Claude Code' : i.provider))); }).catch(() => {});
  root.replaceChildren(h('aside', {class: 'top'}, h('a', {class: 'logo', href: '#/'}, h('span', {class: 'mark'}, 'Q'), h('span', {}, h('b', {}, 'CQA'), h('small', {}, 'Quality Analytics'))),
    h('nav', {class: 'nav', 'aria-label': 'Разделы'}, link('#/', 'list', 'chat', 'Диалоги'), link('#/review', 'review', 'shield', 'Проверка'), link('#/appeals', 'appeals', 'scale', 'Апелляции'), link('#/checklist', 'checklist', 'list', 'Чек-лист')),
    h('div', {class: 'side-foot'}, engine, h('div', {class: 'for'}, 'Прототип для Freedom Broker'))),
    h('main', {class: 'page'}, content));
}

/* ---------- Conversations ---------- */
async function viewList() {
  const body = h('div', {}, h('p', {class: 'muted'}, 'Загрузка…'));
  shell('list', body);
  const checklists = await api('/api/checklists');
  const picker = h('select', {'aria-label': 'Чек-лист для оценки'}, checklists.map(c => h('option', {value: c.id}, `${c.name} · v${c.version}`)));
  const group = h('input', {placeholder: 'group_id, например DEV', 'aria-label': 'group_id'});
  const file = h('input', {type: 'file', accept: '.json,application/json', hidden: true, onchange: guard(async e => {
    const data = JSON.parse(await e.target.files[0].text());
    const done = await api('/api/conversations/upload', data);
    toast(`Загружено диалогов: ${done.imported}`); draw();
  })});
  const table = h('div', {});
  const filter = (key, label, values) => h('select', {'aria-label': label, onchange: e => { state.filters[key] = e.target.value; draw(); }},
    h('option', {value: ''}, label), values.map(([v, t]) => h('option', {value: v, selected: state.filters[key] === v}, t)));
  const count = h('span', {class: 'muted small'});
  const kpis = h('div', {class: 'kpis'});
  let visible = [];

  const run = guard(async ids => {
    if (!ids.length) return toast('Выберите диалоги', true);
    await api('/api/evaluations', {conversation_ids: ids, checklist_id: Number(picker.value)});
    toast(`Запущена оценка: ${ids.length}`); state.selected.clear(); draw();
  });

  const draw = guard(async () => {
    clearTimeout(state.timer);
    const all = await api('/api/conversations');
    const f = state.filters;
    visible = all.filter(c => (!f.language || c.language === f.language) && (!f.channel || c.channel === f.channel) &&
      (!f.dataset || c.dataset === f.dataset) && (!f.status || (c.evaluation?.status || 'none') === f.status));
    count.textContent = `Показано ${visible.length} из ${all.length}`;
    const done = all.filter(c => c.evaluation?.status === 'done' && c.evaluation.total !== null);
    const avg = done.length ? done.reduce((n, c) => n + c.evaluation.total, 0) / done.length : null;
    const kpi = (label, value, note, kind) => h('div', {class: 'kpi ' + (kind || '')}, h('div', {class: 'kpi-label'}, label), h('div', {class: 'kpi-value'}, value), h('div', {class: 'kpi-note'}, note));
    kpis.replaceChildren(
      kpi('Средний балл', avg === null ? '—' : avg.toFixed(1), `по ${done.length} оценённым диалогам`, grade(avg)),
      kpi('Диалогов', all.length, `${all.filter(c => c.channel === 'voice call').length} звонков · ${all.filter(c => c.channel !== 'voice call').length} чатов`),
      kpi('Грубые ошибки', all.filter(c => c.evaluation?.gross_error).length, 'диалогов с нарушением', all.some(c => c.evaluation?.gross_error) ? 'bad' : 'ok'),
      kpi('Ждут проверки', all.reduce((n, c) => n + (c.evaluation?.to_review || 0), 0), 'неуверенных ответов модели', 'warn'));
    if (!all.length) table.replaceChildren(h('p', {class: 'muted'}, 'Диалогов пока нет. Введите group_id и нажмите «Загрузить набор».'));
    else table.replaceChildren(h('table', {}, h('thead', {}, h('tr', {}, h('th', {}, ''), ['Диалог', 'Набор', 'Канал', 'Язык', 'Реплик', 'Статус'].map(t => h('th', {}, t)), h('th', {class: 'num'}, 'Итог'), h('th', {}, 'Отметки'))),
      h('tbody', {}, visible.map(c => {
        const e = c.evaluation;
        return h('tr', {}, h('td', {}, h('input', {type: 'checkbox', 'aria-label': 'Выбрать ' + c.id, checked: state.selected.has(c.id),
          onchange: ev => ev.target.checked ? state.selected.add(c.id) : state.selected.delete(c.id)})),
          h('td', {}, h('a', {href: '#/c/' + encodeURIComponent(c.id)}, c.id)), h('td', {}, c.dataset), h('td', {}, h('span', {class: 'chan'}, icon(c.channel === 'voice call' ? 'phone' : 'chat'), c.channel === 'voice call' ? 'Звонок' : 'Чат')), h('td', {}, h('span', {class: 'lang lang-' + c.language}, c.language)), h('td', {}, c.turns),
          h('td', {title: e?.error || ''}, e ? tag(STATUS[e.status]) : h('span', {class: 'muted'}, 'Не оценён')),
          h('td', {class: 'num'}, e?.status === 'done' ? h('span', {class: 'pill ' + grade(e.total)}, fmt(e.total)) : '—'),
          h('td', {}, e?.gross_error && tag(['Грубая ошибка', 'bad']), ' ', e?.open_appeals > 0 && tag(['Апелляция', 'warn']), ' ', e?.to_review > 0 && tag([`Проверить: ${e.to_review}`, 'warn']), ' ', e?.changed && tag(['Изменено', 'ok'])));
      }))));
    if (all.some(c => ['pending', 'running'].includes(c.evaluation?.status))) state.timer = setTimeout(draw, 2500);
  });

  body.replaceChildren(
    h('div', {class: 'hero'}, h('div', {}, h('div', {class: 'eyebrow'}, 'Conversation Quality Analytics'), h('h1', {}, 'Качество работы операторов'),
      h('p', {}, 'Чаты и звонки на русском, казахском и английском. Оценка по чек-листу с доказательствами, проверкой человеком и советами оператору.'))),
    kpis,
    h('div', {class: 'bar'}, h('h2', {}, 'Диалоги'), h('span', {class: 'grow'}), group,
      h('button', {onclick: guard(async () => { const r = await api('/api/import', {group_id: group.value || 'DEV'}); toast(`Загружено: ${r.imported}`); draw(); })}, 'Загрузить набор'),
      h('button', {onclick: () => file.click()}, 'Загрузить файл'), file),
    h('div', {class: 'card'},
      h('div', {class: 'bar'}, filter('language', 'Все языки', [['RU', 'RU'], ['KZ', 'KZ'], ['EN', 'EN']]),
        filter('channel', 'Все каналы', [['agent chat', 'Чаты'], ['voice call', 'Звонки']]),
        filter('status', 'Все статусы', [['none', 'Не оценён'], ['done', 'Готово'], ['error', 'Ошибка']]), count, h('span', {class: 'grow'}), picker,
        h('button', {onclick: () => run([...state.selected])}, 'Оценить выбранные'),
        h('button', {class: 'primary', onclick: () => run(visible.map(c => c.id))}, 'Оценить все показанные')),
      table));
  draw();
}

/* ---------- Conversation card ---------- */
async function viewCard(id) {
  const c = await api('/api/conversations/' + encodeURIComponent(id));
  const checklists = await api('/api/checklists');
  const audio = c.has_audio ? h('audio', {controls: true, preload: 'none', src: `${API}/api/audio/${encodeURIComponent(id)}/stream`}) : null;
  const seek = seconds => {
    if (!audio || seconds === null || seconds === undefined) return;
    const go = () => { audio.currentTime = seconds; audio.play().catch(() => {}); };
    if (audio.readyState >= 1) go(); else { audio.addEventListener('loadedmetadata', go, {once: true}); audio.load(); }
  };
  const turnEls = c.transcript.map((t, i) => h('div', {class: 'turn ' + t.speaker, id: 'turn-' + i},
    h('div', {class: 'meta'}, h('span', {}, `[${i}] ${t.speaker}`), h('span', {}, c.has_audio ? new Date(t.timestamp).toLocaleTimeString('ru-RU') : t.timestamp),
      c.has_audio && c.audio_offsets[i] !== null && h('button', {'aria-label': `Слушать с ${clock(c.audio_offsets[i])}`, onclick: () => seek(c.audio_offsets[i])}, `▶ ${clock(c.audio_offsets[i])}`)),
    h('div', {}, t.text)));
  const focus = (from, to = from) => {
    turnEls.forEach(el => el.classList.remove('hit'));
    for (let i = Math.max(0, from); i <= Math.min(to, turnEls.length - 1); i++) turnEls[i].classList.add('hit');
    turnEls[Math.min(Math.max(0, from), turnEls.length - 1)]?.scrollIntoView({behavior: 'smooth', block: 'center'});
    if (c.has_audio) seek(c.audio_offsets[from]);
  };
  const picker = h('select', {'aria-label': 'Чек-лист'}, checklists.map(x => h('option', {value: x.id, selected: c.evaluation?.checklist_id === x.id}, `${x.name} · v${x.version}`)));
  const start = guard(async () => { await api('/api/evaluations', {conversation_ids: [id], checklist_id: Number(picker.value)}); render(); });
  const left = h('section', {class: 'card sticky'}, h('h2', {}, 'Транскрипт'), audio && h('div', {style: 'margin:10px 0'}, audio,
    h('a', {class: 'small', href: `${API}/api/audio/${encodeURIComponent(id)}`, target: '_blank', rel: 'noopener'}, 'Открыть плеер организаторов')),
    c.has_audio && h('p', {class: 'small muted'}, 'Переход к фрагменту примерный: время считается по меткам транскрипта.'), h('div', {style: 'margin-top:10px'}, turnEls));
  const right = h('section', {});

  const render = guard(async () => {
    clearTimeout(state.timer);
    const e = (await api('/api/conversations/' + encodeURIComponent(id))).evaluation;
    const controls = h('div', {class: 'bar'}, picker, h('button', {class: 'primary', onclick: start}, e ? 'Оценить заново' : 'Запустить оценку'));
    if (!e) return right.replaceChildren(h('div', {class: 'card'}, controls, h('p', {class: 'muted'}, 'Диалог ещё не оценён.')));
    if (e.status !== 'done') {
      if (e.status !== 'error') state.timer = setTimeout(render, 2500);
      return right.replaceChildren(h('div', {class: 'card'}, controls, tag(STATUS[e.status]), e.error && h('p', {class: 'err'}, e.error)));
    }
    const r = e.result, score = e.final_score;
    const head = h('div', {class: 'card'}, controls, h('div', {class: 'score'},
      h('div', {class: 'ring ' + grade(score.total), style: `--p:${score.total ?? 0}`}, h('div', {}, h('div', {class: 'big'}, fmt(score.total)), h('div', {class: 'score-label'}, e.changed ? 'финальный' : 'из 100'))),
      e.changed && h('div', {}, h('div', {class: 'small muted'}, 'Исходная оценка'), h('div', {style: 'font-size:22px'}, fmt(e.original_score.total))),
      score.gross_error ? tag(['Грубая ошибка', 'bad']) : tag(['Грубых ошибок нет', 'ok']),
      e.to_review ? tag([`Человеку проверить: ${e.to_review} из ${e.checklist.criteria.length}`, 'warn']) : tag(['Модель уверена во всех ответах', 'ok'])),
      h('div', {class: 'sections'}, Object.entries(score.sections).filter(([, s]) => s.max > 0).map(([n, s]) => h('div', {class: 'section'}, h('div', {class: 'muted'}, n), `${fmt(s.earned)} из ${fmt(s.max)}`))),
      h('p', {class: 'small muted', style: 'margin-bottom:0'}, `${r.model} · чек-лист v${e.checklist.version} · оценено ${when(e.finished_at)} · прогонов: ${r.votes} · ≈ $${Number(r.cost_usd).toFixed(3)}`));
    const rows = e.checklist.criteria.map(cr => {
      const item = r.criteria[cr.id], final = e.final_answers[cr.id], applied = score.criteria[cr.id];
      const appeals = e.appeals.filter(a => a.criterion_id === cr.id), open = appeals.some(a => a.status === 'open');
      const form = h('div', {class: 'box', hidden: true});
      const comment = h('textarea', {'aria-label': 'Комментарий к апелляции', placeholder: 'Почему вы не согласны с оценкой?'});
      form.append(comment, h('button', {class: 'primary', style: 'margin-top:6px', onclick: guard(async () => {
        await api('/api/appeals', {evaluation_id: e.id, criterion_id: cr.id, comment: comment.value}); toast('Апелляция подана'); render();
      })}, 'Подать апелляцию'));
      const range = item.evidence_status === 'checked_range';
      const review = e.review[cr.id] && reviewBox(e, cr, item, render);
      const coachBox = h('div', {});
      const showAdvice = a => coachBox.replaceChildren(adviceView(a, () => focus(a.turn)));
      if (e.coaching[cr.id]) showAdvice(e.coaching[cr.id]);
      else if (lostPoints(cr, final)) coachBox.append(h('button', {class: 'coach-btn', onclick: guard(async ev => {
        ev.target.disabled = true; ev.target.textContent = 'Готовлю совет…';
        try { showAdvice(await api(`/api/evaluations/${e.id}/coach/${cr.id}`, {})); }
        catch (err) { ev.target.disabled = false; ev.target.textContent = 'Как надо было ответить'; throw err; }
      })}, icon('spark'), ' Как надо было ответить'));
      return h('article', {class: 'crit'}, h('div', {class: 'crit-head'}, h('h3', {}, cr.title), tag([answerText(final), final !== item.answer ? 'warn' : final === 'na' ? '' : lostPoints(cr, final) ? 'bad' : 'ok']),
        final !== item.answer && h('span', {class: 'small muted'}, `было: ${answerText(item.answer)}`),
        cr.type !== 'flag' && h('span', {class: 'pts'}, applied.points === null ? 'Не учитывается' : `${fmt(applied.points)} / ${fmt(applied.applied_weight)}`)),
        h('p', {style: 'margin:6px 0'}, item.explanation),
        item.quote && h('div', {class: 'quote'}, item.quote),
        h('div', {class: 'bar', style: 'margin:6px 0 0'}, item.answer !== 'na' && h('button', {class: 'link', onclick: () => range ? focus(item.checked_from, item.checked_to) : focus(item.evidence_turn)},
          range ? `Перейти к проверенному участку [${item.checked_from}–${item.checked_to}]` : `Перейти к реплике [${item.evidence_turn}]`),
          tag(EVIDENCE[item.evidence_status] || [item.evidence_status, 'warn']), r.votes > 1 && h('span', {class: 'small muted'}, `согласие ${Math.round(item.agreement * 100)}%`),
          h('span', {class: 'grow'}), !open && !review && h('button', {onclick: () => { form.hidden = !form.hidden; }}, 'Оспорить')),
        review, coachBox, form, appeals.map(a => a.source === 'review' ? h('div', {class: 'box small'}, tag(['Проверено человеком', 'ok']), ' ',
          a.decision === 'changed' ? `Исправлено на «${answerText(a.new_answer)}». ` : 'Ответ модели подтверждён. ', a.reason)
          : h('div', {class: 'box small'}, h('div', {}, tag(a.status === 'open' ? ['На рассмотрении', 'warn'] : a.decision === 'changed' ? ['Оценка изменена', 'ok'] : ['Оценка подтверждена', ''])), h('p', {style: 'margin:6px 0'}, 'Комментарий: ', a.comment),
          a.status === 'decided' && h('p', {style: 'margin:0'}, `Решение: ${a.decision === 'changed' ? answerText(a.new_answer) : 'без изменений'}. Причина: ${a.reason}`))));
    });
    right.replaceChildren(head, h('div', {class: 'card', style: 'margin-top:12px'}, h('h2', {}, 'Критерии'), rows));
  });

  shell('list', h('div', {}, h('div', {class: 'bar'}, h('a', {href: '#/'}, '← Диалоги'), h('h1', {}, id), h('span', {class: 'tag'}, c.channel === 'voice call' ? 'Звонок' : 'Чат'), h('span', {class: 'tag'}, c.language)),
    h('div', {class: 'split'}, left, right)));
  render();
}

const REASON_TEXT = {disagreement: 'Прогоны модели разошлись', evidence: 'Доказательство не найдено в транскрипте'};
const lostPoints = (c, a) => c.type === 'flag' ? a === 'yes' : c.type === 'scale' ? a !== 'na' && a < Math.max(...c.scale.map(s => s.value)) : a === 'no';
const votesLine = item => item.votes?.length > 1 && h('span', {class: 'small muted'}, 'Ответы прогонов: ', item.votes.map(answerText).join(' · '));

// Confirm or correct an answer the model was unsure about. `done` redraws the caller.
function reviewControls(e, cr, done) {
  const answer = h('select', {'aria-label': 'Правильный ответ'}, options(cr).map(v => h('option', {value: v, selected: String(v) === String(e.result.criteria[cr.id].answer)}, answerText(v))));
  const reason = h('input', {placeholder: 'Комментарий (необязательно)', 'aria-label': 'Комментарий проверяющего', class: 'grow'});
  const send = decision => guard(async () => {
    await api('/api/reviews', {evaluation_id: e.id, criterion_id: cr.id, decision, new_answer: decision === 'changed' ? answer.value : null, reason: reason.value});
    toast('Проверка сохранена'); done();
  });
  return h('div', {class: 'bar', style: 'margin:8px 0 0'}, h('button', {class: 'primary', onclick: send('confirmed')}, 'Модель права'), answer, h('button', {onclick: send('changed')}, 'Исправить'), reason);
}

function reviewBox(e, cr, item, done) {
  return h('div', {class: 'box review'}, h('div', {class: 'bar', style: 'margin:0'}, tag(['Нужна проверка человеком', 'warn']),
    e.review[cr.id].map(r => h('span', {class: 'small'}, REASON_TEXT[r])), votesLine(item)), reviewControls(e, cr, done));
}

function adviceView(a, jump) {
  return h('div', {class: 'box advice'}, h('div', {class: 'small muted'}, 'Совет оператору'),
    h('p', {style: 'margin:4px 0'}, h('strong', {}, 'Ошибка: '), a.mistake),
    h('div', {class: 'small muted'}, 'Как надо было ответить ', h('button', {class: 'link', onclick: jump}, `(реплика [${a.turn}])`)),
    h('div', {class: 'better'}, a.better_reply),
    a.better_reply_ru && a.better_reply_ru !== a.better_reply && h('div', {class: 'small muted', style: 'margin-top:4px'}, 'Перевод: ', a.better_reply_ru),
    h('p', {style: 'margin:6px 0 0'}, '💡 ', a.tip));
}

/* ---------- Review queue ---------- */
async function viewReview() {
  const q = await api('/api/reviews');
  const auto = q.answers ? Math.round((1 - (q.pending + q.reviewed) / q.answers) * 100) : 0;
  const stat = (big, text) => h('div', {class: 'section stat'}, h('div', {class: 'big'}, big), h('div', {class: 'muted'}, text));
  const card = a => {
    const e = {id: a.evaluation_id, result: {criteria: {[a.criterion.id]: a.original}}};
    return h('article', {class: 'card', style: 'margin-bottom:12px'},
      h('div', {class: 'bar'}, h('h3', {}, a.criterion.title), h('a', {href: '#/c/' + encodeURIComponent(a.conversation_id)}, a.conversation_id), h('span', {class: 'grow'}), a.reasons.map(r => tag([r, 'warn']))),
      h('div', {class: 'row2'}, h('div', {}, h('div', {class: 'small muted'}, 'Ответ модели'), h('p', {style: 'margin:4px 0'}, h('strong', {}, answerText(a.original.answer)), ' — ', a.original.explanation),
        a.original.quote && h('div', {class: 'quote'}, a.original.quote), votesLine(a.original)),
        h('div', {}, h('div', {class: 'small muted'}, 'Фрагмент диалога'), a.fragment.map(t => h('div', {class: 'turn ' + t.speaker + (t.index === a.original.evidence_turn ? ' hit' : ''), style: 'max-width:100%'}, h('div', {class: 'meta'}, `[${t.index}] ${t.speaker}`), t.text)))),
      reviewControls(e, a.criterion, viewReview));
  };
  shell('review', h('div', {}, h('div', {class: 'bar'}, h('h1', {}, 'Проверка человеком')),
    h('p', {class: 'muted', style: 'max-width:760px'}, 'Каждый диалог модель оценивает несколько раз независимо. Если прогоны разошлись или цитата не нашлась в транскрипте, ответ попадает сюда. Остальные ответы принимаются автоматически, и проверять их не нужно.'),
    h('div', {class: 'sections', style: 'margin-bottom:16px'}, stat(`${auto}%`, 'ответов принято автоматически'), stat(q.pending, 'ждут проверки'), stat(q.reviewed, 'проверено человеком'), stat(q.evaluations, 'оценённых диалогов')),
    q.items.length ? q.items.map(card) : h('p', {class: 'muted'}, 'Все неуверенные ответы проверены.')));
}

/* ---------- Appeals ---------- */
async function viewAppeals() {
  const items = await api('/api/appeals');
  const open = items.filter(a => a.status === 'open'), closed = items.filter(a => a.status !== 'open');
  const card = a => {
    const answer = h('select', {'aria-label': 'Новая оценка'}, options(a.criterion).map(v => h('option', {value: v}, answerText(v))));
    const reason = h('textarea', {'aria-label': 'Причина решения', placeholder: 'Причина решения'});
    const decide = decision => guard(async () => {
      await api(`/api/appeals/${a.id}/decision`, {decision, reason: reason.value, new_answer: decision === 'changed' ? answer.value : null});
      toast('Решение сохранено'); viewAppeals();
    });
    return h('article', {class: 'card', style: 'margin-bottom:12px'},
      h('div', {class: 'bar'}, h('h3', {}, a.criterion.title), h('a', {href: '#/c/' + encodeURIComponent(a.conversation_id)}, a.conversation_id), h('span', {class: 'grow'}), tag(['Итог сейчас: ' + fmt(a.current_total), ''])),
      h('div', {class: 'row2'}, h('div', {}, h('div', {class: 'small muted'}, 'Спорная оценка'), h('p', {style: 'margin:4px 0'}, h('strong', {}, answerText(a.original.answer)), ' — ', a.original.explanation),
        h('div', {class: 'small muted'}, 'Комментарий заявителя'), h('p', {style: 'margin:4px 0'}, a.comment)),
        h('div', {}, h('div', {class: 'small muted'}, 'Фрагмент диалога'), a.fragment.map(t => h('div', {class: 'turn ' + t.speaker + (t.index === a.original.evidence_turn ? ' hit' : ''), style: 'max-width:100%'}, h('div', {class: 'meta'}, `[${t.index}] ${t.speaker}`), t.text)))),
      a.status === 'open' ? h('div', {class: 'box'}, reason, h('div', {class: 'bar', style: 'margin:8px 0 0'}, h('button', {onclick: decide('confirmed')}, 'Подтвердить оценку'), h('span', {class: 'grow'}), answer, h('button', {class: 'primary', onclick: decide('changed')}, 'Изменить оценку')))
        : h('p', {class: 'small', style: 'margin-bottom:0'}, a.decision === 'changed' ? tag(['Изменено на ' + answerText(a.new_answer), 'ok']) : tag(['Подтверждено', '']), ' ', a.reason));
  };
  shell('appeals', h('div', {}, h('div', {class: 'bar'}, h('h1', {}, 'Апелляции')), h('h2', {style: 'margin-bottom:10px'}, `Ждут решения: ${open.length}`),
    open.length ? open.map(card) : h('p', {class: 'muted'}, 'Открытых апелляций нет. Оспорить оценку можно в карточке диалога.'),
    closed.length > 0 && h('h2', {style: 'margin:20px 0 10px'}, 'Рассмотренные'), closed.map(card)));
}

/* ---------- Checklist editor ---------- */
async function viewChecklist(versionId) {
  const all = await api('/api/checklists');
  const source = all.find(c => c.id === versionId) || all[0];
  const draft = JSON.parse(JSON.stringify({name: source.name, criteria: source.criteria}));
  const list = h('div', {}), sum = h('span', {class: 'small'});
  const updateSum = () => {
    const total = draft.criteria.reduce((n, c) => n + (c.type === 'flag' ? 0 : Number(c.weight) || 0), 0);
    sum.replaceChildren(tag([`Сумма весов: ${total}`, total === 100 ? 'ok' : 'warn']));
  };
  const field = (label, control) => h('label', {class: 'f'}, label, control);
  const text = (obj, key, attrs) => h('input', {...attrs, value: obj[key] ?? '', oninput: e => { obj[key] = e.target.value; }});
  const area = (obj, key) => h('textarea', {value: obj[key] ?? '', oninput: e => { obj[key] = e.target.value; }});
  const nextId = () => { let n = 1; while (draft.criteria.some(c => c.id === 'c' + String(n).padStart(2, '0'))) n++; return 'c' + String(n).padStart(2, '0'); };

  const criterion = (c, index) => {
    const type = h('select', {onchange: e => {
      c.type = e.target.value;
      if (c.type === 'flag') { c.weight = 0; c.na_allowed = false; }
      if (c.type === 'scale' && !c.scale) c.scale = [{value: 10, label: ''}, {value: 0, label: ''}];
      draw();
    }}, [['binary', 'Да / Нет'], ['scale', 'Шкала'], ['flag', 'Флаг без баллов']].map(([v, t]) => h('option', {value: v, selected: c.type === v}, t)));
    return h('article', {class: 'card', style: 'margin-bottom:12px'},
      h('div', {class: 'row4'}, field('Название', text(c, 'title')), field('Тип ответа', type),
        field('Вес', h('input', {type: 'number', min: 0, step: 1, value: c.weight, disabled: c.type === 'flag', oninput: e => { c.weight = Number(e.target.value); updateSum(); }})),
        field('Секция', text(c, 'section'))),
      field('Правило оценки', area(c, 'rule')),
      c.type !== 'flag' && h('label', {style: 'display:block;margin-bottom:8px'}, h('input', {type: 'checkbox', checked: !!c.na_allowed, onchange: e => { c.na_allowed = e.target.checked; draw(); }}), ' Разрешить N/A'),
      c.na_allowed && field('Когда ставить N/A', area(c, 'na_rule')),
      c.type === 'scale' && h('div', {}, h('div', {class: 'small muted', style: 'margin-bottom:4px'}, 'Ступени шкалы: балл и описание'),
        c.scale.map((s, i) => h('div', {class: 'step'}, h('input', {type: 'number', min: 0, step: 1, 'aria-label': 'Балл', value: s.value, oninput: e => { s.value = Number(e.target.value); }}), text(s, 'label', {'aria-label': 'Описание ступени'}),
          h('button', {class: 'danger', 'aria-label': 'Удалить ступень', onclick: () => { c.scale.splice(i, 1); draw(); }}, '×'))),
        h('button', {onclick: () => { c.scale.push({value: 0, label: ''}); draw(); }}, 'Добавить ступень')),
      h('div', {class: 'bar', style: 'margin:10px 0 0'}, h('span', {class: 'small muted'}, 'id: ' + c.id), h('span', {class: 'grow'}), h('button', {class: 'danger', onclick: () => { draft.criteria.splice(index, 1); draw(); }}, 'Удалить критерий')));
  };
  const draw = () => { list.replaceChildren(...draft.criteria.map(criterion)); updateSum(); };
  const save = guard(async () => {
    const saved = await api('/api/checklists', draft);
    toast(`Сохранена версия ${saved.version}`); viewChecklist(saved.id);
  });
  const addCriterion = () => { draft.criteria.push({id: nextId(), section: '', title: '', type: 'binary', weight: 0, na_allowed: false, rule: ''}); draw(); list.lastElementChild?.scrollIntoView({block: 'center'}); };
  shell('checklist', h('div', {}, h('div', {class: 'bar'}, h('h1', {}, 'Чек-лист'), h('select', {'aria-label': 'Версия', onchange: e => viewChecklist(Number(e.target.value))},
      all.map(c => h('option', {value: c.id, selected: c.id === source.id}, `v${c.version} · ${when(c.created_at)}`))), sum, h('span', {class: 'grow'}),
      h('button', {onclick: addCriterion}, 'Добавить критерий'), h('button', {class: 'primary', onclick: save}, 'Сохранить новую версию')),
    h('p', {class: 'small muted'}, 'Старые оценки остаются на своей версии чек-листа. Новая версия применяется при следующем запуске оценки. Если сумма весов не равна 100, итог всё равно приводится к 100.'),
    h('div', {class: 'card', style: 'margin-bottom:12px'}, field('Название чек-листа', text(draft, 'name'))), list));
  draw();
}

const route = guard(async () => {
  clearTimeout(state.timer);
  const path = location.hash.slice(1) || '/';
  if (path.startsWith('/c/')) return viewCard(decodeURIComponent(path.slice(3)));
  if (path === '/appeals') return viewAppeals();
  if (path === '/review') return viewReview();
  if (path === '/checklist') return viewChecklist();
  return viewList();
});
addEventListener('hashchange', route);
route();
})();

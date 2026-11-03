(() => {
  'use strict';

  const API = (window.ERRAND_CONCIERGE_API || '').replace(/\/$/, '');
  const STORAGE_CHAT = 'errand-concierge.chat.v1';
  const STORAGE_SESSION = 'errand-concierge.session.v1';

  const state = {
    route: 'chat',
    filter: 'pending',
    query: '',
    errands: [],
    config: null,
    messages: sanitizeMessages(loadJSON(STORAGE_CHAT, [])),
    sessionId: loadSession(),
    busy: false,
    editingId: null,
    confirmHandler: null,
    errandRequest: 0,
    trashRequest: 0,
    googleRequest: 0,
  };

  const el = {};
  const STATUS_ICON = { pending: 'i-tick', done: 'i-tick', cancelled: 'i-close' };

  // ------------------------------------------------------------------ utils
  function $(selector, root = document) {
    return root.querySelector(selector);
  }

  function $$(selector, root = document) {
    return Array.from(root.querySelectorAll(selector));
  }

  function loadJSON(key, fallback) {
    try {
      const value = JSON.parse(localStorage.getItem(key) || 'null');
      return value == null ? fallback : value;
    } catch (error) {
      return fallback;
    }
  }

  function saveJSON(key, value) {
    try {
      localStorage.setItem(key, JSON.stringify(value));
    } catch (error) {
      /* storage may be unavailable; the app still works in-memory */
    }
  }

  function newId() {
    if (window.crypto && typeof window.crypto.randomUUID === 'function') {
      return window.crypto.randomUUID();
    }
    return 'sess-' + Math.random().toString(36).slice(2) + Date.now().toString(36);
  }

  function loadSession() {
    let existing = null;
    try { existing = localStorage.getItem(STORAGE_SESSION); } catch (error) { /* ignore */ }
    if (existing && /^[A-Za-z0-9_-]{8,64}$/.test(existing)) return existing;
    const created = newId();
    try { localStorage.setItem(STORAGE_SESSION, created); } catch (error) { /* ignore */ }
    return created;
  }

  function sanitizeMessages(value) {
    if (!Array.isArray(value)) return [];
    return value
      .filter((message) => message && (message.role === 'user' || message.role === 'assistant') && typeof message.content === 'string')
      .slice(-80);
  }

  function svgIcon(id, className) {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    if (className) svg.setAttribute('class', className);
    svg.setAttribute('aria-hidden', 'true');
    const use = document.createElementNS('http://www.w3.org/2000/svg', 'use');
    use.setAttribute('href', '#' + id);
    svg.appendChild(use);
    return svg;
  }

  function parseHash() {
    const raw = (window.location.hash || '#/chat').replace(/^#/, '');
    const [pathPart, queryPart] = raw.split('?');
    const parts = pathPart.split('/').filter(Boolean);
    return { view: parts[0] || 'chat', params: new URLSearchParams(queryPart || '') };
  }

  function navigate(hash) {
    if (window.location.hash === hash) {
      route();
    } else {
      window.location.hash = hash;
    }
  }

  async function api(path, options = {}) {
    const config = { method: options.method || 'GET', headers: {} };
    if (options.body !== undefined) {
      config.headers['Content-Type'] = 'application/json';
      config.body = JSON.stringify(options.body);
    }
    const response = await fetch(API + path, config);
    let payload = null;
    const type = response.headers.get('content-type') || '';
    if (type.includes('application/json')) {
      try { payload = await response.json(); } catch (error) { payload = null; }
    }
    if (!response.ok) {
      let message = 'Something went wrong. Please try again.';
      if (payload && typeof payload.detail === 'string') message = payload.detail;
      else if (payload && Array.isArray(payload.detail) && payload.detail[0]) message = payload.detail[0].msg || message;
      const error = new Error(message);
      error.status = response.status;
      throw error;
    }
    return payload;
  }

  function toast(message, options = {}) {
    const { tone = '', actionLabel = null, onAction = null, duration = 6000 } = options;
    const box = document.createElement('div');
    box.className = 'toast' + (tone ? ' toast--' + tone : '');
    const text = document.createElement('p');
    text.className = 'toast__msg';
    text.textContent = message;
    box.appendChild(text);

    if (actionLabel && onAction) {
      const action = document.createElement('button');
      action.type = 'button';
      action.className = 'toast__action';
      action.textContent = actionLabel;
      action.addEventListener('click', () => {
        box.remove();
        onAction();
      });
      box.appendChild(action);
    }

    const close = document.createElement('button');
    close.type = 'button';
    close.className = 'toast__close';
    close.setAttribute('aria-label', 'Dismiss');
    close.textContent = '×';
    close.addEventListener('click', () => box.remove());
    box.appendChild(close);

    el.toasts.appendChild(box);
    if (duration > 0) {
      window.setTimeout(() => box.remove(), duration);
    }
  }

  // ------------------------------------------------------------------- chat
  function todayLabel() {
    return new Date().toLocaleDateString(undefined, { weekday: 'long', month: 'long', day: 'numeric' });
  }

  function appendInline(parent, text) {
    const pattern = /(\*\*[^*]+\*\*|`[^`]+`|\*[^*\n]+\*)/g;
    let cursor = 0;
    let match;
    while ((match = pattern.exec(text)) !== null) {
      if (match.index > cursor) {
        parent.appendChild(document.createTextNode(text.slice(cursor, match.index)));
      }
      const token = match[0];
      let node;
      if (token.startsWith('**')) {
        node = document.createElement('strong');
        node.textContent = token.slice(2, -2);
      } else if (token.startsWith('`')) {
        node = document.createElement('code');
        node.textContent = token.slice(1, -1);
      } else {
        node = document.createElement('em');
        node.textContent = token.slice(1, -1);
      }
      parent.appendChild(node);
      cursor = match.index + token.length;
    }
    if (cursor < text.length) {
      parent.appendChild(document.createTextNode(text.slice(cursor)));
    }
  }

  function renderRichText(container, text) {
    const lines = String(text || '').replace(/\r/g, '').split('\n');
    let list = null;
    let listType = null;

    const closeList = () => { list = null; listType = null; };

    lines.forEach((raw) => {
      const bullet = raw.match(/^\s*[-*•]\s+(.*)$/);
      const ordered = raw.match(/^\s*\d+[.)]\s+(.*)$/);

      if (bullet || ordered) {
        const type = bullet ? 'ul' : 'ol';
        if (!list || listType !== type) {
          list = document.createElement(type);
          listType = type;
          container.appendChild(list);
        }
        const item = document.createElement('li');
        appendInline(item, (bullet || ordered)[1]);
        list.appendChild(item);
        return;
      }

      closeList();
      if (!raw.trim()) {
        container.appendChild(document.createElement('br'));
        return;
      }
      const heading = raw.match(/^\s*#{1,6}\s+(.*)$/);
      if (heading) {
        const paragraph = document.createElement('p');
        const strong = document.createElement('strong');
        appendInline(strong, heading[1]);
        paragraph.appendChild(strong);
        container.appendChild(paragraph);
        return;
      }
      const paragraph = document.createElement('p');
      appendInline(paragraph, raw);
      container.appendChild(paragraph);
    });
  }

  function messageNode(role, text, timestamp) {
    const wrap = document.createElement('article');
    wrap.className = 'message message--' + role;

    const avatar = document.createElement('div');
    avatar.className = 'message__avatar';
    avatar.setAttribute('aria-hidden', 'true');
    avatar.appendChild(svgIcon('i-chat'));
    wrap.appendChild(avatar);

    const body = document.createElement('div');
    body.className = 'message__body';

    const bubble = document.createElement('div');
    bubble.className = 'message__bubble';
    if (role === 'assistant') renderRichText(bubble, text);
    else {
      text.split('\n').forEach((line) => {
        const p = document.createElement('p');
        p.textContent = line || '\u00a0';
        bubble.appendChild(p);
      });
    }
    body.appendChild(bubble);

    const meta = document.createElement('div');
    meta.className = 'message__meta';
    const time = new Date(timestamp || Date.now()).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
    meta.textContent = (role === 'user' ? 'You' : 'Concierge') + ' · ' + time;
    body.appendChild(meta);

    wrap.appendChild(body);
    return wrap;
  }

  function typingNode() {
    const wrap = document.createElement('article');
    wrap.className = 'message message--assistant message--typing';
    wrap.id = 'typingMessage';

    const avatar = document.createElement('div');
    avatar.className = 'message__avatar';
    avatar.setAttribute('aria-hidden', 'true');
    avatar.appendChild(svgIcon('i-chat'));
    wrap.appendChild(avatar);

    const body = document.createElement('div');
    body.className = 'message__body';
    const bubble = document.createElement('div');
    bubble.className = 'message__bubble';
    const dots = document.createElement('span');
    dots.className = 'typing';
    dots.setAttribute('aria-label', 'Concierge is typing');
    for (let i = 0; i < 3; i += 1) dots.appendChild(document.createElement('span'));
    bubble.appendChild(dots);
    body.appendChild(bubble);
    wrap.appendChild(body);
    return wrap;
  }

  function welcomeNode() {
    const wrap = document.createElement('div');
    wrap.className = 'welcome';

    const title = document.createElement('p');
    title.className = 'welcome__title';
    title.textContent = 'Tell me what you keep forgetting.';
    wrap.appendChild(title);

    const text = document.createElement('p');
    text.className = 'welcome__text';
    text.textContent = 'Bills, appointments, tiny errands — I will sort them, date them, and keep them in view.';
    wrap.appendChild(text);

    const suggestions = document.createElement('div');
    suggestions.className = 'suggestions';
    [
      'Pay rent by Friday',
      'Dentist next Tuesday at 3pm',
      'Renew my passport',
      "What's pending?",
    ].forEach((prompt) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'suggestion';
      button.textContent = prompt;
      button.addEventListener('click', () => sendMessage(prompt));
      suggestions.appendChild(button);
    });
    wrap.appendChild(suggestions);
    return wrap;
  }

  function renderChat() {
    el.thread.textContent = '';
    if (state.messages.length === 0) {
      el.thread.appendChild(welcomeNode());
    } else {
      state.messages.forEach((message) => {
        el.thread.appendChild(messageNode(message.role, message.content, message.ts));
      });
    }
    if (state.busy) el.thread.appendChild(typingNode());
    scrollThread();
  }

  function scrollThread() {
    el.thread.scrollTop = el.thread.scrollHeight;
  }

  function pushMessage(role, content) {
    state.messages.push({ role, content, ts: Date.now() });
    if (state.messages.length > 80) state.messages = state.messages.slice(-80);
    saveJSON(STORAGE_CHAT, state.messages);
  }

  function setBusy(busy) {
    state.busy = busy;
    el.sendBtn.disabled = busy;
    el.messageInput.disabled = busy;
  }

  function autosize() {
    el.messageInput.style.height = 'auto';
    el.messageInput.style.height = Math.min(el.messageInput.scrollHeight, 170) + 'px';
  }

  async function sendMessage(raw) {
    const text = String(raw || '').trim();
    if (!text || state.busy) return;

    el.messageInput.value = '';
    autosize();
    pushMessage('user', text);
    setBusy(true);
    renderChat();

    try {
      const data = await api('/api/chat', {
        method: 'POST',
        body: { message: text, session_id: state.sessionId },
      });
      if (data && data.session_id) {
        state.sessionId = data.session_id;
        try { localStorage.setItem(STORAGE_SESSION, state.sessionId); } catch (error) { /* ignore */ }
      }
      pushMessage('assistant', (data && data.reply) || 'Done.');
    } catch (error) {
      pushMessage('assistant', 'I could not reach the concierge: ' + error.message);
      toast(error.message, { tone: 'error' });
    } finally {
      setBusy(false);
      renderChat();
      refreshStats();
      if (state.route === 'errands') loadErrands();
      el.messageInput.focus();
    }
  }

  // ---------------------------------------------------------------- errands
  function startOfDay(date) {
    return new Date(date.getFullYear(), date.getMonth(), date.getDate());
  }

  function dueInfo(errand) {
    if (!errand.due_at) {
      return {
        label: errand.due_text || 'No date',
        tone: 'none',
        title: errand.due_text ? 'Due: ' + errand.due_text : 'No due date',
      };
    }
    const due = new Date(errand.due_at);
    if (Number.isNaN(due.getTime())) {
      return { label: errand.due_text || 'No date', tone: 'none', title: '' };
    }
    const diff = Math.round((startOfDay(due) - startOfDay(new Date())) / 86400000);
    let label;
    if (diff === 0) label = 'Today';
    else if (diff === 1) label = 'Tomorrow';
    else if (diff === -1) label = 'Yesterday';
    else {
      label = due.toLocaleDateString(undefined, {
        weekday: Math.abs(diff) < 7 ? 'short' : undefined,
        month: 'short',
        day: 'numeric',
      });
    }
    const tone = diff < 0 ? 'overdue' : diff === 0 ? 'today' : 'normal';
    const full = due.toLocaleString(undefined, {
      weekday: 'long', month: 'long', day: 'numeric',
      hour: 'numeric', minute: '2-digit',
    });
    return { label, tone, title: 'Due ' + full };
  }

  function shortDate(iso) {
    if (!iso) return '';
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return '';
    return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
  }

  function emptyState({ icon = 'i-list', title, text, actionLabel = null, onAction = null }) {
    const wrap = document.createElement('div');
    wrap.className = 'empty-state';

    const iconWrap = document.createElement('div');
    iconWrap.className = 'empty-state__icon';
    iconWrap.appendChild(svgIcon(icon));
    wrap.appendChild(iconWrap);

    const heading = document.createElement('h2');
    heading.textContent = title;
    wrap.appendChild(heading);

    const copy = document.createElement('p');
    copy.textContent = text;
    wrap.appendChild(copy);

    if (actionLabel && onAction) {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'btn btn--primary';
      button.textContent = actionLabel;
      button.style.marginTop = '8px';
      button.addEventListener('click', onAction);
      wrap.appendChild(button);
    }
    return wrap;
  }

  function dueChipNode(errand) {
    const info = dueInfo(errand);
    const chip = document.createElement('span');
    chip.className = 'row__due' + (info.tone !== 'normal' ? ' row__due--' + info.tone : '');
    chip.title = info.title;
    chip.appendChild(svgIcon('i-clock'));
    const text = document.createElement('span');
    text.textContent = info.label;
    chip.appendChild(text);
    if (errand.calendar_event_id) {
      const cal = svgIcon('i-calendar');
      cal.classList.add('row__cal');
      chip.appendChild(cal);
      chip.title += ' · On Google Calendar';
    }
    return chip;
  }

  function errandCard(errand) {
    const info = dueInfo(errand);
    const row = document.createElement('article');
    row.className = 'errand-card errand-card--' + errand.status;
    if (errand.status === 'pending' && info.tone === 'overdue') row.classList.add('overdue');
    row.dataset.id = errand.id;

    const lead = document.createElement('div');
    lead.className = 'row__lead';
    const check = document.createElement('button');
    check.type = 'button';
    check.className = 'row__check';
    if (errand.status === 'done') check.classList.add('row__check--done');
    if (errand.status === 'cancelled') check.classList.add('row__check--cancelled');
    check.dataset.action = errand.status === 'pending' ? 'complete' : 'reopen';
    const checkLabel = errand.status === 'pending'
      ? 'Mark “' + errand.title + '” as done'
      : 'Reopen “' + errand.title + '”';
    check.setAttribute('aria-label', checkLabel);
    check.title = checkLabel;
    check.appendChild(svgIcon(STATUS_ICON[errand.status] || 'i-list'));
    lead.appendChild(check);
    row.appendChild(lead);

    const main = document.createElement('div');
    main.className = 'row__main';
    const title = document.createElement('h2');
    title.className = 'row__title';
    title.textContent = errand.title;
    main.appendChild(title);
    if (errand.notes) {
      const notes = document.createElement('p');
      notes.className = 'row__notes';
      notes.textContent = errand.notes;
      notes.title = errand.notes;
      main.appendChild(notes);
    }
    row.appendChild(main);

    row.appendChild(dueChipNode(errand));

    const actions = document.createElement('div');
    actions.className = 'row__actions';
    const addAction = (action, label, extraClass = '') => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'link-btn' + (extraClass ? ' ' + extraClass : '');
      button.dataset.action = action;
      button.textContent = label;
      actions.appendChild(button);
    };

    addAction('edit', 'Edit');
    if (errand.status === 'pending') addAction('cancel', 'Cancel');
    addAction('delete', 'Delete', 'link-btn--danger');

    row.appendChild(actions);

    return row;
  }

  function renderErrands() {
    el.errandGrid.textContent = '';
    if (state.errands.length === 0) {
      if (state.query) {
        el.errandGrid.appendChild(emptyState({
          icon: 'i-search',
          title: 'No matches',
          text: 'Nothing matches “' + state.query + '”. Try a different search.',
        }));
      } else if (state.filter === 'all') {
        el.errandGrid.appendChild(emptyState({
          icon: 'i-list',
          title: 'An empty list is a fine start',
          text: 'Add the first thing you do not want to forget.',
          actionLabel: 'Add an errand',
          onAction: () => openErrandDialog(),
        }));
      } else if (state.filter === 'pending') {
        el.errandGrid.appendChild(emptyState({
          icon: 'i-check',
          title: 'Nothing pending',
          text: 'You are all caught up. Enjoy the quiet.',
        }));
      } else {
        el.errandGrid.appendChild(emptyState({
          icon: 'i-list',
          title: 'Nothing here yet',
          text: 'Errands show up here once they reach this state.',
        }));
      }
      return;
    }
    state.errands.forEach((errand) => el.errandGrid.appendChild(errandCard(errand)));
  }

  async function loadErrands() {
    const requestId = ++state.errandRequest;
    if (!el.errandGrid.children.length) {
      el.errandGrid.textContent = '';
      el.errandGrid.appendChild(emptyState({ icon: 'i-list', title: 'Loading…', text: 'Fetching your errands.' }));
    }
    const params = new URLSearchParams();
    params.set('status', state.filter);
    if (state.query) params.set('q', state.query);
    try {
      const data = await api('/api/errands?' + params.toString());
      if (requestId !== state.errandRequest) return;
      state.errands = data.errands || [];
      renderErrands();
    } catch (error) {
      if (requestId !== state.errandRequest) return;
      el.errandGrid.textContent = '';
      el.errandGrid.appendChild(emptyState({
        icon: 'i-alert',
        title: 'Could not load errands',
        text: error.message,
        actionLabel: 'Try again',
        onAction: loadErrands,
      }));
    }
  }

  function findErrand(id) {
    return state.errands.find((errand) => errand.id === id) || null;
  }

  async function handleErrandAction(action, id) {
    const errand = findErrand(id);
    if (!errand) return;

    if (action === 'edit') {
      openErrandDialog(errand);
      return;
    }

    if (action === 'delete') {
      try {
        await api('/api/errands/' + encodeURIComponent(id), { method: 'DELETE' });
        toast('Moved to trash', {
          tone: 'success',
          actionLabel: 'Undo',
          duration: 8000,
          onAction: async () => {
            try {
              await api('/api/errands/trash/' + encodeURIComponent(id) + '/restore', { method: 'POST' });
              toast('Errand restored', { tone: 'success' });
              loadErrands();
              refreshStats();
            } catch (error) {
              toast(error.message, { tone: 'error' });
            }
          },
        });
        loadErrands();
        refreshStats();
      } catch (error) {
        toast(error.message, { tone: 'error' });
      }
      return;
    }

    const endpoints = { complete: 'complete', cancel: 'cancel', reopen: 'reopen' };
    const messages = {
      complete: 'Marked as done',
      cancel: 'Errand cancelled',
      reopen: 'Errand reopened',
    };
    if (!endpoints[action]) return;
    try {
      await api('/api/errands/' + encodeURIComponent(id) + '/' + endpoints[action], { method: 'POST' });
      toast(messages[action], { tone: 'success' });
      loadErrands();
      refreshStats();
    } catch (error) {
      toast(error.message, { tone: 'error' });
    }
  }

  // ------------------------------------------------------------------ trash
  function trashCard(entry) {
    const row = document.createElement('article');
    row.className = 'errand-card errand-card--cancelled';
    row.dataset.id = entry.id;

    const lead = document.createElement('div');
    lead.className = 'row__lead';
    const mark = document.createElement('span');
    mark.className = 'row__check row__check--cancelled';
    mark.setAttribute('aria-hidden', 'true');
    mark.appendChild(svgIcon('i-trash'));
    lead.appendChild(mark);
    row.appendChild(lead);

    const main = document.createElement('div');
    main.className = 'row__main';
    const title = document.createElement('h2');
    title.className = 'row__title';
    title.textContent = entry.title || 'Untitled errand';
    main.appendChild(title);
    if (entry.notes) {
      const notes = document.createElement('p');
      notes.className = 'row__notes';
      notes.textContent = entry.notes;
      notes.title = entry.notes;
      main.appendChild(notes);
    }
    row.appendChild(main);

    const meta = document.createElement('span');
    meta.className = 'row__due row__due--none';
    const parts = [];
    if (entry.due_text || entry.due_at) parts.push('Was due ' + (entry.due_text || shortDate(entry.due_at)));
    parts.push('Deleted ' + shortDate(entry.deleted_at));
    meta.textContent = parts.join(' · ');
    row.appendChild(meta);

    const actions = document.createElement('div');
    actions.className = 'row__actions';
    actions.innerHTML =
      '<button type="button" class="link-btn" data-action="restore">Restore</button>' +
      '<button type="button" class="link-btn link-btn--danger" data-action="purge">Delete forever</button>';
    row.appendChild(actions);

    return row;
  }

  async function loadTrash() {
    const requestId = ++state.trashRequest;
    el.trashGrid.textContent = '';
    el.trashGrid.appendChild(emptyState({ icon: 'i-trash', title: 'Loading…', text: 'Checking the bin.' }));
    try {
      const data = await api('/api/errands/trash');
      if (requestId !== state.trashRequest) return;
      const entries = data.errands || [];
      el.trashGrid.textContent = '';
      if (entries.length === 0) {
        el.trashGrid.appendChild(emptyState({
          icon: 'i-trash',
          title: 'Trash is empty',
          text: 'Deleted errands will be recorded here.',
        }));
        return;
      }
      entries.forEach((entry) => el.trashGrid.appendChild(trashCard(entry)));
    } catch (error) {
      if (requestId !== state.trashRequest) return;
      el.trashGrid.textContent = '';
      el.trashGrid.appendChild(emptyState({
        icon: 'i-alert',
        title: 'Could not load trash',
        text: error.message,
        actionLabel: 'Try again',
        onAction: loadTrash,
      }));
    }
  }

  async function handleTrashAction(action, id) {
    if (action === 'restore') {
      try {
        await api('/api/errands/trash/' + encodeURIComponent(id) + '/restore', { method: 'POST' });
        toast('Errand restored', { tone: 'success' });
        loadTrash();
        refreshStats();
      } catch (error) {
        toast(error.message, { tone: 'error' });
      }
      return;
    }
    if (action === 'purge') {
      openConfirm({
        title: 'Delete forever?',
        text: 'This removes the errand from the trash permanently. It cannot be undone.',
        actionLabel: 'Delete forever',
        danger: true,
        onConfirm: async () => {
          try {
            await api('/api/errands/trash/' + encodeURIComponent(id), { method: 'DELETE' });
            toast('Deleted permanently');
            loadTrash();
          } catch (error) {
            toast(error.message, { tone: 'error' });
          }
        },
      });
    }
  }

  // ------------------------------------------------------------ integrations
  async function loadGoogleStatus(options = {}) {
    const requestId = ++state.googleRequest;
    try {
      const status = await api('/api/integrations/google/status');
      if (requestId !== state.googleRequest) return;
      el.calDot.dataset.state = status.connected ? 'connected' : 'off';

      if (!status.configured) {
        el.googleStatusText.className = '';
        el.googleStatusText.textContent = 'Not configured on this server';
        el.googleAction.textContent = '';
        return;
      }
      if (status.connected) {
        el.googleStatusText.className = 'is-connected';
        el.googleStatusText.textContent = status.email ? 'Connected as ' + status.email : 'Connected';
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'btn btn--ghost';
        button.textContent = 'Disconnect';
        button.addEventListener('click', disconnectGoogle);
        el.googleAction.textContent = '';
        el.googleAction.appendChild(button);
      } else {
        el.googleStatusText.className = '';
        el.googleStatusText.textContent = 'Not connected';
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'btn btn--primary';
        button.textContent = 'Connect Google Calendar';
        button.addEventListener('click', () => {
          window.location.href = API + '/api/integrations/google/connect';
        });
        el.googleAction.textContent = '';
        el.googleAction.appendChild(button);
      }
      if (options.notify) {
        toast(status.connected ? 'Google Calendar connected' : 'Google Calendar disconnected', { tone: 'success' });
      }
    } catch (error) {
      if (requestId !== state.googleRequest) return;
      el.calDot.dataset.state = 'unknown';
      el.googleStatusText.className = '';
      el.googleStatusText.textContent = 'Could not check connection';
      el.googleAction.textContent = '';
    }
  }

  async function disconnectGoogle() {
    try {
      await api('/api/integrations/google/disconnect', { method: 'POST' });
      toast('Google Calendar disconnected', { tone: 'success' });
      loadGoogleStatus();
    } catch (error) {
      toast(error.message, { tone: 'error' });
    }
  }

  // ------------------------------------------------------------------ stats
  async function refreshStats() {
    try {
      const stats = await api('/api/stats');
      el.navPending.textContent = String(stats.pending);
      el.navPending.hidden = stats.pending === 0;
    } catch (error) {
      /* the sidebar count is cosmetic; failures are not worth interrupting the user */
    }
  }

  // ----------------------------------------------------------------- config
  async function loadConfig() {
    try {
      const config = await api('/api/config');
      state.config = config;
      el.modePill.hidden = false;
      el.modePill.dataset.mode = config.mode;
      el.modePillText.textContent = config.mode === 'bedrock' ? 'Live model' : 'Demo mode';
      el.modePill.title = config.mode === 'bedrock'
        ? 'Connected to the Bedrock model.'
        : 'No BEDROCK_API_KEY is configured, so replies come from the built-in demo assistant.';
    } catch (error) {
      el.modePill.hidden = true;
    }
  }

  // --------------------------------------------------------------- dialogs
  function openErrandDialog(errand = null) {
    state.editingId = errand ? errand.id : null;
    el.errandDialogTitle.textContent = errand ? 'Edit errand' : 'New errand';
    el.errandSubmit.textContent = errand ? 'Save changes' : 'Add errand';
    el.errandTitle.value = errand ? errand.title : '';
    el.errandDue.value = errand ? (errand.due_text || '') : '';
    el.errandNotes.value = errand && errand.notes ? errand.notes : '';
    el.errandFormError.hidden = true;
    el.errandFormError.textContent = '';
    if (typeof el.errandDialog.showModal === 'function') {
      if (!el.errandDialog.open) el.errandDialog.showModal();
    } else {
      el.errandDialog.setAttribute('open', '');
    }
    window.setTimeout(() => el.errandTitle.focus(), 20);
  }

  function closeErrandDialog() {
    if (typeof el.errandDialog.close === 'function') el.errandDialog.close();
    else el.errandDialog.removeAttribute('open');
    state.editingId = null;
  }

  function showFormError(message) {
    el.errandFormError.textContent = message;
    el.errandFormError.hidden = false;
  }

  async function submitErrand(event) {
    event.preventDefault();
    const title = el.errandTitle.value.trim();
    if (!title) {
      showFormError('Give the errand a title.');
      el.errandTitle.focus();
      return;
    }
    const payload = {
      title,
      due: el.errandDue.value.trim() || null,
      notes: el.errandNotes.value.trim() || null,
    };
    el.errandSubmit.disabled = true;
    try {
      if (state.editingId) {
        await api('/api/errands/' + encodeURIComponent(state.editingId), { method: 'PATCH', body: payload });
        toast('Errand updated', { tone: 'success' });
      } else {
        await api('/api/errands', { method: 'POST', body: payload });
        toast('Errand added', { tone: 'success' });
      }
      closeErrandDialog();
      refreshStats();
      if (state.route === 'errands') loadErrands();
    } catch (error) {
      showFormError(error.message);
    } finally {
      el.errandSubmit.disabled = false;
    }
  }

  function openConfirm({ title, text, actionLabel = 'Confirm', danger = false, onConfirm }) {
    el.confirmTitle.textContent = title;
    el.confirmText.textContent = text;
    el.confirmAction.textContent = actionLabel;
    el.confirmAction.className = 'btn ' + (danger ? 'btn--danger' : 'btn--primary');
    state.confirmHandler = onConfirm;
    if (typeof el.confirmDialog.showModal === 'function') {
      if (!el.confirmDialog.open) el.confirmDialog.showModal();
    } else {
      el.confirmDialog.setAttribute('open', '');
    }
    window.setTimeout(() => el.confirmAction.focus(), 20);
  }

  function closeConfirm() {
    if (typeof el.confirmDialog.close === 'function') el.confirmDialog.close();
    else el.confirmDialog.removeAttribute('open');
    state.confirmHandler = null;
  }

  async function runConfirm() {
    const handler = state.confirmHandler;
    closeConfirm();
    if (handler) await handler();
  }

  // ------------------------------------------------------------------ route
  function showView(view) {
    $$('.view').forEach((section) => {
      section.hidden = section.id !== 'view-' + view;
    });
    window.scrollTo({ top: 0, behavior: 'auto' });
  }

  function updateNav(view) {
    $$('.nav__link').forEach((link) => {
      link.classList.remove('is-active');
      link.removeAttribute('aria-current');
    });
    let active = null;
    if (view === 'errands') {
      active = $('.nav__link[data-route="errands"]');
    } else {
      active = $('.nav__link[data-route="' + view + '"]');
    }
    if (active) {
      active.classList.add('is-active');
      active.setAttribute('aria-current', 'page');
    }
  }

  function updateFilterTabs() {
    $$('#filterTabs button').forEach((button) => {
      button.setAttribute('aria-selected', button.dataset.filter === state.filter ? 'true' : 'false');
    });
    const ledes = {
      all: "Everything you're keeping track of, in one place.",
      pending: 'The things still waiting on you.',
      done: "A record of what you've already handled.",
      cancelled: 'Errands you decided not to do.',
    };
    el.errandsLede.textContent = ledes[state.filter] || ledes.all;
  }

  function route() {
    const { view, params } = parseHash();
    const allowed = ['chat', 'errands', 'trash', 'integrations'];
    state.route = allowed.includes(view) ? view : 'chat';

    if (state.route === 'errands') {
      const requested = params.get('status');
      state.filter = ['all', 'pending', 'done', 'cancelled'].includes(requested) ? requested : 'pending';
      updateFilterTabs();
      el.searchInput.value = state.query;
    }

    showView(state.route);
    updateNav(state.route);
    closeSidebar();

    if (state.route === 'chat') {
      renderChat();
    } else if (state.route === 'errands') {
      loadErrands();
    } else if (state.route === 'trash') {
      loadTrash();
    } else if (state.route === 'integrations') {
      loadGoogleStatus();
    }
  }

  // ---------------------------------------------------------------- sidebar
  function openSidebar() {
    el.app.classList.add('sidebar-open');
    el.scrim.hidden = false;
    el.sidebarOpen.setAttribute('aria-expanded', 'true');
    document.body.style.overflow = 'hidden';
    window.setTimeout(() => el.sidebarClose.focus(), 30);
  }

  function closeSidebar() {
    if (!el.app.classList.contains('sidebar-open')) return;
    el.app.classList.remove('sidebar-open');
    el.scrim.hidden = true;
    el.sidebarOpen.setAttribute('aria-expanded', 'false');
    document.body.style.overflow = '';
  }

  // -------------------------------------------------------------------- init
  function cacheElements() {
    el.app = $('#app');
    el.scrim = $('#scrim');
    el.sidebar = $('#sidebar');
    el.sidebarOpen = $('#sidebarOpen');
    el.sidebarClose = $('#sidebarClose');
    el.thread = $('#thread');
    el.composer = $('#composer');
    el.messageInput = $('#messageInput');
    el.sendBtn = $('#sendBtn');
    el.clearChat = $('#clearChat');
    el.todayLabel = $('#todayLabel');
    el.viewChat = $('#view-chat');
    el.viewErrands = $('#view-errands');
    el.viewTrash = $('#view-trash');
    el.viewIntegrations = $('#view-integrations');
    el.errandsLede = $('#errandsLede');
    el.filterTabs = $('#filterTabs');
    el.searchInput = $('#searchInput');
    el.errandGrid = $('#errandGrid');
    el.trashGrid = $('#trashGrid');
    el.emptyTrashBtn = $('#emptyTrashBtn');
    el.calDot = $('#calDot');
    el.googleStatusText = $('#googleStatusText');
    el.googleAction = $('#googleAction');
    el.navPending = $('#navPending');
    el.modePill = $('#modePill');
    el.modePillText = $('#modePillText');
    el.errandDialog = $('#errandDialog');
    el.errandDialogTitle = $('#errandDialogTitle');
    el.errandForm = $('#errandForm');
    el.errandTitle = $('#errandTitle');
    el.errandDue = $('#errandDue');
    el.errandNotes = $('#errandNotes');
    el.errandSubmit = $('#errandSubmit');
    el.errandFormError = $('#errandFormError');
    el.confirmDialog = $('#confirmDialog');
    el.confirmTitle = $('#confirmTitle');
    el.confirmText = $('#confirmText');
    el.confirmAction = $('#confirmAction');
    el.toasts = $('#toasts');
  }

  function bindEvents() {
    window.addEventListener('hashchange', route);
    window.addEventListener('resize', () => {
      if (window.innerWidth > 1024) closeSidebar();
    });

    el.sidebarOpen.addEventListener('click', openSidebar);
    el.sidebarClose.addEventListener('click', closeSidebar);
    el.scrim.addEventListener('click', closeSidebar);

    $$('.nav__link').forEach((link) => link.addEventListener('click', closeSidebar));

    ['newErrandBtn', 'newErrandBtn2', 'topbarNew'].forEach((id) => {
      const button = document.getElementById(id);
      if (button) button.addEventListener('click', () => openErrandDialog());
    });

    el.composer.addEventListener('submit', (event) => {
      event.preventDefault();
      sendMessage(el.messageInput.value);
    });

    el.messageInput.addEventListener('input', autosize);
    el.messageInput.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
        event.preventDefault();
        el.composer.requestSubmit();
      }
    });

    el.clearChat.addEventListener('click', () => {
      openConfirm({
        title: 'Clear this chat?',
        text: 'The conversation history will be removed. Your errands are not affected.',
        actionLabel: 'Clear chat',
        onConfirm: async () => {
          try { await api('/api/chat/' + encodeURIComponent(state.sessionId), { method: 'DELETE' }); } catch (error) { /* best effort */ }
          state.messages = [];
          state.sessionId = newId();
          try { localStorage.setItem(STORAGE_SESSION, state.sessionId); } catch (error) { /* ignore */ }
          saveJSON(STORAGE_CHAT, state.messages);
          renderChat();
          toast('Chat cleared');
        },
      });
    });

    el.filterTabs.addEventListener('click', (event) => {
      const button = event.target.closest('button[data-filter]');
      if (!button) return;
      navigate('#/errands?status=' + button.dataset.filter);
    });

    let searchTimer = null;
    el.searchInput.addEventListener('input', () => {
      window.clearTimeout(searchTimer);
      searchTimer = window.setTimeout(() => {
        state.query = el.searchInput.value.trim();
        loadErrands();
      }, 220);
    });

    el.errandGrid.addEventListener('click', (event) => {
      const button = event.target.closest('button[data-action]');
      const card = event.target.closest('.errand-card');
      if (!button || !card) return;
      handleErrandAction(button.dataset.action, card.dataset.id);
    });

    el.trashGrid.addEventListener('click', (event) => {
      const button = event.target.closest('button[data-action]');
      const card = event.target.closest('.errand-card');
      if (!button || !card) return;
      handleTrashAction(button.dataset.action, card.dataset.id);
    });

    el.emptyTrashBtn.addEventListener('click', () => {
      openConfirm({
        title: 'Empty the trash?',
        text: 'All deleted errands will be removed permanently. This cannot be undone.',
        actionLabel: 'Empty trash',
        danger: true,
        onConfirm: async () => {
          try {
            await api('/api/errands/trash/clear', { method: 'POST' });
            toast('Trash emptied');
            loadTrash();
          } catch (error) {
            toast(error.message, { tone: 'error' });
          }
        },
      });
    });

    el.errandForm.addEventListener('submit', submitErrand);
    $$('[data-close-dialog]').forEach((button) => button.addEventListener('click', closeErrandDialog));
    $$('[data-close-confirm]').forEach((button) => button.addEventListener('click', closeConfirm));
    el.confirmAction.addEventListener('click', runConfirm);

    $('#quickDates').addEventListener('click', (event) => {
      const button = event.target.closest('button[data-due]');
      if (!button) return;
      el.errandDue.value = button.dataset.due;
      el.errandDue.focus();
    });

    [el.errandDialog, el.confirmDialog].forEach((dialog) => {
      dialog.addEventListener('click', (event) => {
        if (event.target !== dialog) return;
        const rect = dialog.getBoundingClientRect();
        const inside = event.clientX >= rect.left && event.clientX <= rect.right &&
          event.clientY >= rect.top && event.clientY <= rect.bottom;
        if (!inside) {
          if (dialog === el.errandDialog) closeErrandDialog();
          else closeConfirm();
        }
      });
    });

    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') closeSidebar();
      if (event.key === '/' && state.route === 'errands' && !/^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName)) {
        event.preventDefault();
        el.searchInput.focus();
      }
    });
  }

  function handleRedirectNotice() {
    const params = new URLSearchParams(window.location.search);
    const outcome = params.get('google');
    if (!outcome) return;
    const messages = {
      connected: ['Google Calendar connected', 'success'],
      error: ['Google sign-in did not complete. Please try again.', 'error'],
      invalid_state: ['That sign-in link expired. Please try again.', 'error'],
      not_configured: ['Google sign-in is not configured on this server.', 'error'],
    };
    const entry = messages[outcome];
    if (entry) toast(entry[0], { tone: entry[1] });
    window.history.replaceState({}, '', window.location.pathname + window.location.hash);
  }

  function init() {
    cacheElements();
    el.todayLabel.textContent = todayLabel();
    bindEvents();
    handleRedirectNotice();
    loadConfig();
    refreshStats();
    loadGoogleStatus();
    if (!window.location.hash) {
      window.history.replaceState({}, '', '#/chat');
    }
    route();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();

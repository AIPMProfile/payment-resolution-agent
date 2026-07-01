/* FinAssist — Transaction Support Frontend */

const chatArea = document.getElementById('chat-area');
const userInput = document.getElementById('user-input');
const sendBtn = document.getElementById('send-btn');
const ticketDisplay = document.getElementById('ticket-id-display');
const statusPill = document.getElementById('status-pill');
const progressTracker = document.getElementById('progress-tracker');
const sidebarNewBtn = document.getElementById('sidebar-new-btn');
const sidebarToggle = document.getElementById('sidebar-toggle');
const sidebar = document.getElementById('sidebar');

let sessionToken = localStorage.getItem('session_token') || null;
const DEMO_USER_ID = 'USR001';
let currentTicketId = null;
let cardCount = 0;

// ── Time-of-day greeting ──

function setGreeting() {
  const el = document.getElementById('welcome-greeting');
  if (!el) return;
  const h = new Date().getHours();
  if (h < 12) el.textContent = 'Good morning!';
  else if (h < 17) el.textContent = 'Good afternoon!';
  else el.textContent = 'Good evening!';
}
setGreeting();

// ── Auth ──

async function ensureSessionToken() {
  if (sessionToken) return;
  try {
    const res = await fetch('/auth/token', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id: DEMO_USER_ID }),
    });
    if (!res.ok) return;
    const data = await res.json();
    sessionToken = data.token;
    localStorage.setItem('session_token', sessionToken);
  } catch (e) {
    console.error('Could not obtain session token', e);
  }
}

function clearToken() {
  sessionToken = null;
  localStorage.removeItem('session_token');
}

async function apiCall(path, body) {
  await ensureSessionToken();
  const headers = { 'Content-Type': 'application/json' };
  if (sessionToken) headers['X-Auth-Token'] = sessionToken;

  let res = await fetch(path, { method: 'POST', headers, body: JSON.stringify(body) });

  if (res.status === 401) {
    clearToken();
    await ensureSessionToken();
    const retryHeaders = { 'Content-Type': 'application/json' };
    if (sessionToken) retryHeaders['X-Auth-Token'] = sessionToken;
    res = await fetch(path, { method: 'POST', headers: retryHeaders, body: JSON.stringify(body) });
  }

  if (!res.ok) {
    const err = await res.text().catch(() => res.statusText);
    throw new Error(`API ${path} returned ${res.status}: ${err}`);
  }

  return res.json();
}

async function apiGet(path) {
  await ensureSessionToken();
  const headers = {};
  if (sessionToken) headers['X-Auth-Token'] = sessionToken;
  const res = await fetch(path, { headers });
  if (!res.ok) throw new Error(`GET ${path} returned ${res.status}`);
  return res.json();
}

// ── Sidebar: User profile ──

async function loadUserProfile() {
  try {
    const user = await apiGet('/user/profile');
    document.getElementById('profile-name').textContent = user.name || user.user_id;
    document.getElementById('profile-id').textContent = user.user_id;
    const initials = (user.name || '?').split(' ').map(w => w[0]).join('').substring(0, 2).toUpperCase();
    document.getElementById('profile-avatar').textContent = initials;
  } catch (e) {
    document.getElementById('profile-name').textContent = DEMO_USER_ID;
    document.getElementById('profile-id').textContent = '';
    document.getElementById('profile-avatar').textContent = 'U';
  }
}

// ── Sidebar: Ticket list ──

const CAT_EMOJI = {
  'UPI_FAILURE': '💸',
  'POT_WITHDRAWAL': '🏦',
  'OUT_OF_SCOPE': '💬',
};

const CAT_LABEL = {
  'UPI_FAILURE': 'UPI payment',
  'POT_WITHDRAWAL': 'Pot withdrawal',
  'OUT_OF_SCOPE': 'General query',
};

const STATUS_LABEL = {
  open: 'Active',
  escalated: 'Escalated',
  resolved: 'Resolved',
  auto_closed: 'Closed',
  pending_confirmation: 'Checking in',
  awaiting_timeline: 'Almost done',
};

function ticketProgressHTML(status) {
  const stages = ['reported', 'reviewing', 'resolved'];
  let activeIdx = 0;
  if (status === 'open') activeIdx = 0;
  else if (status === 'escalated' || status === 'pending_confirmation' || status === 'awaiting_timeline') activeIdx = 1;
  else if (status === 'resolved' || status === 'auto_closed') activeIdx = 2;

  let html = '';
  for (let i = 0; i < 3; i++) {
    const cls = i < activeIdx ? 'done' : i === activeIdx ? 'active' : '';
    html += `<div class="tmp-dot ${cls}"></div>`;
    if (i < 2) {
      const lineCls = i < activeIdx ? 'done' : '';
      html += `<div class="tmp-line ${lineCls}"></div>`;
    }
  }
  return html;
}

function formatDate(dateStr) {
  if (!dateStr) return '';
  const d = new Date(dateStr);
  const now = new Date();
  const diff = now - d;
  const days = Math.floor(diff / 86400000);
  if (days === 0) return 'Today';
  if (days === 1) return 'Yesterday';
  if (days < 7) return `${days}d ago`;
  return d.toLocaleDateString('en-IN', { day: 'numeric', month: 'short' });
}

async function loadTicketList() {
  const list = document.getElementById('ticket-list');
  try {
    const tickets = await apiGet('/user/tickets');
    if (!tickets.length) {
      list.innerHTML = '<div class="sidebar-empty">No tickets yet. Start a new conversation above.</div>';
      return;
    }

    list.innerHTML = tickets.map(t => {
      const emoji = CAT_EMOJI[t.category] || '📋';
      const label = CAT_LABEL[t.category] || t.category || 'Ticket';
      const statusLabel = STATUS_LABEL[t.status] || t.status;
      const statusCls = `tis-${t.status}`;
      const isActive = t.ticket_id === currentTicketId;
      const date = formatDate(t.created_at);
      const progress = ticketProgressHTML(t.status);

      return `
        <div class="ticket-item ${isActive ? 'active' : ''}" data-ticket-id="${t.ticket_id}" data-status="${t.status}">
          <div class="ticket-item-top">
            <span class="ticket-item-category">
              <span class="ticket-item-emoji">${emoji}</span>
              ${escHtml(label)}
            </span>
            <span class="ticket-item-status ${statusCls}">${statusLabel}</span>
          </div>
          <div class="ticket-item-bottom">
            <span class="ticket-item-date">${date}</span>
            <span class="ticket-item-id">#${t.ticket_id.substring(0, 8)}</span>
          </div>
          <div class="ticket-mini-progress">${progress}</div>
        </div>`;
    }).join('');

    list.querySelectorAll('.ticket-item').forEach(item => {
      item.addEventListener('click', () => loadTicketConversation(item.dataset.ticketId, item.dataset.status));
    });
  } catch (e) {
    list.innerHTML = '<div class="sidebar-empty">Could not load tickets.</div>';
    console.error('loadTicketList error', e);
  }
}

function upsertSidebarTicket(ticketId, status, category) {
  const list = document.getElementById('ticket-list');
  const existing = list.querySelector(`[data-ticket-id="${ticketId}"]`);
  if (existing) {
    existing.dataset.status = status;
    const statusEl = existing.querySelector('.ticket-item-status');
    if (statusEl) {
      statusEl.textContent = STATUS_LABEL[status] || status;
      statusEl.className = `ticket-item-status tis-${status}`;
    }
    const progressEl = existing.querySelector('.ticket-mini-progress');
    if (progressEl) progressEl.innerHTML = ticketProgressHTML(status);
    return;
  }
  const emoji = CAT_EMOJI[category] || '\u{1F4CB}';
  const label = CAT_LABEL[category] || category || 'Ticket';
  const statusLabel = STATUS_LABEL[status] || status;
  const html = `
    <div class="ticket-item active" data-ticket-id="${ticketId}" data-status="${status}">
      <div class="ticket-item-top">
        <span class="ticket-item-category">
          <span class="ticket-item-emoji">${emoji}</span>
          ${escHtml(label)}
        </span>
        <span class="ticket-item-status tis-${status}">${statusLabel}</span>
      </div>
      <div class="ticket-item-bottom">
        <span class="ticket-item-date">Today</span>
        <span class="ticket-item-id">#${ticketId.substring(0, 8)}</span>
      </div>
      <div class="ticket-mini-progress">${ticketProgressHTML(status)}</div>
    </div>`;
  const empty = list.querySelector('.sidebar-empty');
  if (empty) empty.remove();
  list.insertAdjacentHTML('afterbegin', html);
  const newItem = list.querySelector(`[data-ticket-id="${ticketId}"]`);
  newItem.addEventListener('click', () => loadTicketConversation(ticketId, status));
  highlightActiveTicket(ticketId);
}

async function loadTicketConversation(ticketId, status) {
  currentTicketId = ticketId;
  cardCount = 0;
  dismissWelcome();
  chatArea.innerHTML = '';

  highlightActiveTicket(ticketId);
  sidebar.classList.remove('open');

  appendTyping();
  try {
    const response = await fetch(
      `/ticket/${ticketId}?user_id=${DEMO_USER_ID}`
    );
    if (!response.ok) throw new Error('Failed to load');
    removeTyping();

    const data = await response.json();
    updateTicketHeader(data.ticket_id, data.status);

    const history = data.conversation_json || [];
    history.forEach(msg => {
      if (msg.role === 'user') {
        appendUserBubble(msg.content);
      } else if (msg.role === 'assistant') {
        appendSystemMsg(msg.content);
      }
    });

    if (!history.length) {
      appendSystemMsg('No conversation history yet. Send a message to continue.');
    }
  } catch (e) {
    removeTyping();
    appendSystemMsg('Could not load this ticket. Please try again.');
    console.error(e);
  }
}

function highlightActiveTicket(ticketId) {
  document.querySelectorAll('.ticket-item').forEach(item => {
    item.classList.toggle('active', item.dataset.ticketId === ticketId);
  });
}

// ── Sidebar toggle (mobile) ──

sidebarToggle.addEventListener('click', () => {
  sidebar.classList.toggle('open');
});

// ── Utilities ──

function scrollBottom() {
  chatArea.scrollTop = chatArea.scrollHeight;
}

function escHtml(str) {
  return (str || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

// ── Progress tracker ──

function updateProgress(stage) {
  progressTracker.style.display = 'flex';
  const steps = progressTracker.querySelectorAll('.progress-step');
  const lines = progressTracker.querySelectorAll('.progress-line');

  steps.forEach(s => { s.classList.remove('active', 'done'); });
  lines.forEach(l => { l.classList.remove('active', 'done'); });

  if (stage === 'reported') {
    steps[0].classList.add('active');
  } else if (stage === 'reviewing') {
    steps[0].classList.add('done');
    lines[0].classList.add('done');
    steps[1].classList.add('active');
  } else if (stage === 'escalated') {
    steps[0].classList.add('done');
    lines[0].classList.add('done');
    steps[1].classList.add('active');
  } else if (stage === 'resolved') {
    steps[0].classList.add('done');
    steps[1].classList.add('done');
    steps[2].classList.add('done');
    lines[0].classList.add('done');
    lines[1].classList.add('done');
  } else if (stage === 'hide') {
    progressTracker.style.display = 'none';
  }
}

// ── Ticket header ──

function updateTicketHeader(ticketId, status) {
  currentTicketId = ticketId;
  ticketDisplay.textContent = ticketId.substring(0, 8) + '...';
  ticketDisplay.title = ticketId;
  ticketDisplay.style.display = 'inline';
  statusPill.style.display = 'inline-block';

  const labels = {
    open: 'Active',
    escalated: 'Escalated',
    resolved: 'Resolved',
    auto_closed: 'Closed',
    pending_confirmation: 'Checking in',
    awaiting_timeline: 'Almost done',
  };
  statusPill.textContent = labels[status] || status.replace(/_/g, ' ');
  statusPill.className = `status-pill status-${status}`;

  const catLabel = CAT_LABEL[chatArea.dataset.category] || '';
  document.getElementById('header-title').textContent = catLabel || `Ticket #${ticketId.substring(0, 8)}`;

  const progressMap = {
    open: 'reported',
    escalated: 'escalated',
    pending_confirmation: 'reviewing',
    awaiting_timeline: 'reviewing',
    resolved: 'resolved',
    auto_closed: 'resolved',
  };
  updateProgress(progressMap[status] || 'reported');
}

function dismissWelcome() {
  const wb = document.getElementById('topic-tiles');
  if (wb) {
    const block = wb.closest('.welcome-block');
    if (block) block.remove();
  }
}

// ── Message renderers ──

function appendUserBubble(text) {
  const el = document.createElement('div');
  el.className = 'msg-user';
  el.textContent = text;
  chatArea.appendChild(el);
  scrollBottom();
}

function appendSystemMsg(text) {
  const el = document.createElement('div');
  el.className = 'msg-system';
  el.textContent = text;
  chatArea.appendChild(el);
  scrollBottom();
  return el;
}

function appendTyping() {
  const el = document.createElement('div');
  el.className = 'typing';
  el.id = 'typing-indicator';
  el.innerHTML = '<span></span><span></span><span></span>';
  chatArea.appendChild(el);
  scrollBottom();
}

function removeTyping() {
  const t = document.getElementById('typing-indicator');
  if (t) t.remove();
}

function appendResponseCard(card, ticketId, showFeedback) {
  cardCount++;
  const wrap = document.createElement('div');
  wrap.className = 'response-card';

  const nextStepHtml = cardCount === 1 && card.next_step ? `
      <div class="card-next-step">
        <span class="next-step-label">What happens next</span><br>
        ${escHtml(card.next_step)}
      </div>` : '';

  wrap.innerHTML = `
    <div class="card-body">
      <div class="card-response">${escHtml(card.response)}</div>
      ${nextStepHtml}
    </div>
    ${showFeedback ? buildFeedbackWidget(ticketId) : ''}
  `;

  chatArea.appendChild(wrap);
  scrollBottom();
  if (showFeedback) bindFeedback(wrap, ticketId);
}

// ── Feedback widget ──

function buildFeedbackWidget(ticketId) {
  return `
    <div class="feedback-widget" data-ticket="${ticketId}">
      <p>Was this helpful?</p>
      <div class="score-buttons">
        <button class="score-btn" data-score="1">Not really</button>
        <button class="score-btn" data-score="2">Somewhat</button>
        <button class="score-btn" data-score="3">Yes, thanks!</button>
      </div>
      <div class="follow-up-question" style="display:none">
        <p style="margin-bottom:8px">What could be better?</p>
        <div class="failure-options">
          <button class="failure-opt" data-reason="Too generic, not specific to my case">Too generic for my case</button>
          <button class="failure-opt" data-reason="Confusing, hard to understand">Hard to understand</button>
          <button class="failure-opt" data-reason="Wrong information">Wrong information</button>
          <button class="failure-opt" data-reason="Did not tell me what to do next">Didn't say what to do next</button>
          <button class="failure-opt" data-reason="Other">Something else</button>
        </div>
        <textarea class="free-text-box" placeholder="Tell us more (optional)..." rows="2" style="display:none"></textarea>
        <button class="submit-feedback-btn">Send feedback</button>
      </div>
    </div>
  `;
}

function bindFeedback(cardEl, ticketId) {
  const widget = cardEl.querySelector('.feedback-widget');
  const scoreBtns = widget.querySelectorAll('.score-btn');
  const followUp = widget.querySelector('.follow-up-question');
  const failureOpts = widget.querySelectorAll('.failure-opt');
  const freeText = widget.querySelector('.free-text-box');
  const submitBtn = widget.querySelector('.submit-feedback-btn');
  let selectedScore = null;
  let selectedReason = null;

  scoreBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      scoreBtns.forEach(b => b.classList.remove('selected'));
      btn.classList.add('selected');
      selectedScore = parseInt(btn.dataset.score);

      if (selectedScore === 3) {
        postFeedback(ticketId, 3, null, null, widget);
      } else {
        followUp.style.display = 'block';
        scrollBottom();
      }
    });
  });

  failureOpts.forEach(opt => {
    opt.addEventListener('click', () => {
      failureOpts.forEach(o => o.classList.remove('selected'));
      opt.classList.add('selected');
      selectedReason = opt.dataset.reason;
      freeText.style.display = selectedReason === 'Other' ? 'block' : 'none';
      setTimeout(() => submitBtn.scrollIntoView({ behavior: 'smooth', block: 'nearest' }), 100);
    });
  });

  submitBtn.addEventListener('click', () => {
    postFeedback(ticketId, selectedScore, selectedReason, freeText.value || null, widget);
  });
}

async function postFeedback(ticketId, score, reason, freeText, widget) {
  try {
    await apiCall('/feedback', {
      ticket_id: ticketId,
      helpful_score: score,
      failure_reason: reason,
      free_text: freeText,
    });
    widget.innerHTML = '<p class="feedback-thanks">Thanks for the feedback — it helps us get better.</p>';
  } catch (e) {
    widget.innerHTML = '<p class="feedback-thanks" style="color:#E65100">Could not submit feedback. Please try again.</p>';
    console.error('Feedback error', e);
  }
}

// ── Stage 2 follow-up ──

function appendStage2Prompt(ticketId) {
  const wrap = document.createElement('div');
  wrap.className = 'stage2-prompt';
  wrap.innerHTML = `
    <div class="stage2-icon">🔔</div>
    <p class="stage2-title">Quick check-in</p>
    <p class="stage2-question">Has the money arrived in your account?</p>
    <div class="stage2-actions">
      <button class="stage2-btn stage2-yes" data-answer="yes">Yes, it's here!</button>
      <button class="stage2-btn" data-answer="no">Not yet</button>
    </div>
  `;
  chatArea.appendChild(wrap);
  scrollBottom();

  wrap.querySelector('.stage2-yes').addEventListener('click', () => handleStage2Resolution(ticketId, 'yes', wrap));
  wrap.querySelector('[data-answer="no"]').addEventListener('click', () => handleStage2Resolution(ticketId, 'no', wrap));
}

async function handleStage2Resolution(ticketId, answer, wrap) {
  wrap.querySelectorAll('.stage2-btn').forEach(b => { b.disabled = true; });
  try {
    const res = await fetch('/stage2/resolution', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ticket_id: ticketId, answer }),
    });
    const data = await res.json();

    if (data.action === 'timeline_question') {
      wrap.innerHTML = `
        <div class="stage2-icon">⏱️</div>
        <p class="stage2-title">One last thing</p>
        <p class="stage2-question">How was the resolution timing?</p>
        <div class="stage2-actions stage2-timeline">
          <button class="stage2-btn" data-answer="yes_as_expected">Right on time</button>
          <button class="stage2-btn" data-answer="roughly">Close enough</button>
          <button class="stage2-btn" data-answer="no_took_longer">Took too long</button>
        </div>
      `;
      wrap.querySelectorAll('.stage2-btn').forEach(btn => {
        btn.addEventListener('click', () => handleStage2Timeline(ticketId, btn.dataset.answer, wrap));
      });
    } else if (data.action === 'escalated') {
      wrap.innerHTML = `
        <div class="stage2-escalation">
          <div class="escalation-icon">🚀</div>
          <p class="stage2-title">We're on it</p>
          <p class="stage2-question">A senior colleague has been notified and will reach out to you directly. Hang tight.</p>
        </div>
      `;
      updateTicketHeader(ticketId, 'escalated');
      upsertSidebarTicket(ticketId, 'escalated', chatArea.dataset.category || null);
    }
  } catch (e) {
    wrap.innerHTML = '<p class="stage2-question">Could not submit — please try again later.</p>';
    console.error('Stage 2 error', e);
  }
}

async function handleStage2Timeline(ticketId, answer, wrap) {
  wrap.querySelectorAll('.stage2-btn').forEach(b => { b.disabled = true; });
  try {
    await fetch('/stage2/timeline', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ticket_id: ticketId, answer }),
    });

    wrap.innerHTML = `
      <div class="stage2-resolved">
        <div class="resolved-check">✓</div>
        <p class="resolved-title">Money's back home!</p>
        <p class="resolved-sub">Glad we could sort this out. Your ticket is now closed.</p>
      </div>
    `;
    updateTicketHeader(ticketId, 'resolved');
    fireConfetti();
    upsertSidebarTicket(ticketId, 'resolved', chatArea.dataset.category || null);
  } catch (e) {
    wrap.innerHTML = '<p class="stage2-question">Could not submit — please try again later.</p>';
    console.error('Timeline error', e);
  }
}

function appendAutoCloseNotice(ticketId) {
  const wrap = document.createElement('div');
  wrap.className = 'autoclose-notice';
  wrap.innerHTML = `
    <div class="autoclose-icon">📋</div>
    <p class="autoclose-title">This ticket has been closed</p>
    <p class="autoclose-sub">No further action was needed. If the issue comes back, just start a new ticket — we've got your history.</p>
  `;
  chatArea.appendChild(wrap);
  scrollBottom();
}

// ── Confetti ──

function fireConfetti() {
  const canvas = document.getElementById('confetti-canvas');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  canvas.width = window.innerWidth;
  canvas.height = window.innerHeight;

  const colors = ['#FF5722', '#4CAF50', '#2196F3', '#FFC107', '#9C27B0', '#FF9800'];
  const particles = [];

  for (let i = 0; i < 80; i++) {
    particles.push({
      x: canvas.width / 2 + (Math.random() - 0.5) * 200,
      y: canvas.height / 2,
      vx: (Math.random() - 0.5) * 12,
      vy: Math.random() * -14 - 4,
      w: Math.random() * 8 + 4,
      h: Math.random() * 6 + 3,
      color: colors[Math.floor(Math.random() * colors.length)],
      rotation: Math.random() * 360,
      rotSpeed: (Math.random() - 0.5) * 10,
      gravity: 0.25,
      life: 1,
    });
  }

  let frame = 0;
  function draw() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    let alive = false;

    for (const p of particles) {
      if (p.life <= 0) continue;
      alive = true;
      p.x += p.vx;
      p.y += p.vy;
      p.vy += p.gravity;
      p.rotation += p.rotSpeed;
      p.life -= 0.012;

      ctx.save();
      ctx.translate(p.x, p.y);
      ctx.rotate((p.rotation * Math.PI) / 180);
      ctx.globalAlpha = Math.max(0, p.life);
      ctx.fillStyle = p.color;
      ctx.fillRect(-p.w / 2, -p.h / 2, p.w, p.h);
      ctx.restore();
    }

    frame++;
    if (alive && frame < 180) requestAnimationFrame(draw);
    else ctx.clearRect(0, 0, canvas.width, canvas.height);
  }
  requestAnimationFrame(draw);
}

// ── Send message ──

async function sendMessage(overrideText) {
  const text = overrideText || userInput.value.trim();
  if (!text) return;

  dismissWelcome();
  userInput.value = '';
  sendBtn.disabled = true;
  appendUserBubble(text);

  appendTyping();

  try {
    const data = await apiCall('/chat', {
      user_id: DEMO_USER_ID,
      message: text,
      ticket_id: currentTicketId,
    });

    removeTyping();
    updateTicketHeader(data.ticket_id, data.ticket_status);

    if (data.ticket_status === 'pending_confirmation') {
      if (data.message) appendSystemMsg(data.message);
      appendStage2Prompt(data.ticket_id);
    } else if (data.ticket_status === 'auto_closed') {
      appendAutoCloseNotice(data.ticket_id);
    } else if (data.escalated || data.card === null) {
      appendSystemMsg(data.message);
    } else if (data.card) {
      appendResponseCard(data.card, data.ticket_id, data.feedback_prompt);
    } else if (data.message) {
      appendSystemMsg(data.message);
    }

    const cat = data.card ? data.card.category : (chatArea.dataset.category || null);
    upsertSidebarTicket(data.ticket_id, data.ticket_status, cat);
  } catch (err) {
    removeTyping();
    appendSystemMsg('Something went wrong. Please try again.');
    console.error(err);
  } finally {
    sendBtn.disabled = false;
    userInput.focus();
  }
}

sendBtn.addEventListener('click', () => sendMessage());
userInput.addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey) sendMessage(); });

// ── New ticket ──

function resetToNewTicket() {
  currentTicketId = null;
  cardCount = 0;
  ticketDisplay.style.display = 'none';
  statusPill.style.display = 'none';
  updateProgress('hide');
  document.getElementById('header-title').textContent = 'New conversation';
  highlightActiveTicket(null);

  // Close sidebar on mobile
  sidebar.classList.remove('open');

  chatArea.innerHTML = `
    <div class="welcome-block">
      <div class="welcome-avatar">👋</div>
      <div class="welcome-heading" id="welcome-greeting">Hey there!</div>
      <div class="welcome-sub">We're here to help with your transaction. Pick what's going on, or tell us in your own words.</div>
      <div class="topic-tiles" id="topic-tiles">
        <button class="topic-tile tile-upi" data-msg="My UPI payment is stuck — the amount was debited but not received by the merchant">
          <span class="tile-emoji">💸</span>
          <div class="tile-text">
            <span class="tile-label">UPI payment stuck</span>
            <span class="tile-desc">Debited but not received</span>
          </div>
        </button>
        <button class="topic-tile tile-pot" data-msg="My Savings Pot withdrawal is pending and the money hasn't arrived in my account">
          <span class="tile-emoji">🏦</span>
          <div class="tile-text">
            <span class="tile-label">Pot withdrawal pending</span>
            <span class="tile-desc">Money not in account yet</span>
          </div>
        </button>
      </div>
    </div>
  `;
  setGreeting();
  bindTiles();
}

sidebarNewBtn.addEventListener('click', resetToNewTicket);

function bindTiles() {
  document.querySelectorAll('.topic-tile').forEach(tile => {
    tile.addEventListener('click', () => sendMessage(tile.dataset.msg));
  });
}

// ── Init ──

async function init() {
  await ensureSessionToken();
  loadUserProfile();
  loadTicketList();
  bindTiles();
}

init();

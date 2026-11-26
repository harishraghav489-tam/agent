const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
let demo = false, kind = 'Both', result = null, controller = null, activeFilter = 'All';
let saved = [];
try {
  const stored = JSON.parse(localStorage.getItem('careerglass-saved') || '[]');
  if (Array.isArray(stored)) saved = stored.filter(j => j && typeof j.id === 'string' && typeof j.title === 'string' && typeof j.url === 'string' && Array.isArray(j.skills));
} catch { /* Storage may be unavailable or contain an older schema. */ }
const escapeHTML = (value) => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const safeURL = (value) => {
  try { const url = new URL(value); return url.protocol === 'https:' && !url.username && !url.password ? url.href : '#'; }
  catch { return '#'; }
};
let toastTimer;
function toast(message) {
  $('#toast').textContent = message;
  $('#toast').hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { $('#toast').hidden = true; }, 3000);
}
function setMode(value) {
  demo = value;
  $('#live-mode').classList.toggle('selected', !demo);
  $('#demo-mode').classList.toggle('selected', demo);
  $('#live-mode').setAttribute('aria-pressed', String(!demo));
  $('#demo-mode').setAttribute('aria-pressed', String(demo));
  $('#demo-notice').hidden = !demo;
  $('#search-button span').textContent = demo ? 'Explore sample matches' : 'Find my opportunities';
}
$('#live-mode').onclick = () => setMode(false);
$('#demo-mode').onclick = () => setMode(true);
$$('[data-kind]').forEach(button => button.onclick = () => {
  kind = button.dataset.kind;
  $$('[data-kind]').forEach(b => { b.classList.toggle('selected', b === button); b.setAttribute('aria-pressed', String(b === button)); });
});
function showView(view) {
  for (const name of ['discover', 'saved', 'profile']) $(`#${name}-view`).hidden = name !== view;
  $$('[data-view]').forEach(b => { b.classList.toggle('active', b.dataset.view === view); b.setAttribute('aria-current', b.dataset.view === view ? 'page' : 'false'); });
  $('#page-label').textContent = { discover:'Discover', saved:'Saved opportunities', profile:'My profile' }[view];
  if (view === 'saved') renderSaved();
  if (view === 'profile') renderProfile();
}
$$('[data-view]').forEach(button => button.onclick = () => showView(button.dataset.view));
$('#about-button').onclick = () => $('#about-dialog').showModal();
$('.dialog-close').onclick = () => $('#about-dialog').close();
$('#about-dialog').onclick = (event) => { if (event.target === $('#about-dialog')) $('#about-dialog').close(); };

const stepNames = ['collect_profile', 'analyze_profile', 'find_jobs', 'rank_jobs', 'summarize'];
const stepMessages = ['Understanding your skills and preferences…', 'Searching your selected job boards…', 'Comparing opportunities with your profile…', 'Writing your friendly career summary…', 'Your shortlist is ready.'];
function handleEvent(event) {
  if (event.event === 'progress') {
    const index = stepNames.indexOf(event.data.step);
    $$('[data-step]').forEach((step, i) => step.classList.toggle('done', i <= index));
    $('#progress-message').textContent = stepMessages[index] || 'Working on your search…';
  }
  if (event.event === 'error') throw new Error(event.data.message);
  if (event.event === 'result') {
    result = event.data;
    activeFilter = 'All';
    $$('[data-filter]').forEach(b => b.classList.toggle('selected', b.dataset.filter === 'All'));
    renderResults();
  }
}
$('#search-form').onsubmit = async (event) => {
  event.preventDefault();
  if (controller) return;
  const sources = $$('.sources input:checked').map(input => input.value);
  if (!sources.length) { toast('Choose at least one job platform.'); return; }
  const payload = {
    linkedin_url: $('#linkedin-url').value.trim(), prompt: $('#prompt').value.trim(),
    profile_text: $('#profile-text').value.trim(), domain: $('#domain').value.trim(),
    location: $('#location').value.trim(), kind, sources, demo,
  };
  if (!demo && ![payload.linkedin_url, payload.prompt, payload.profile_text, payload.domain].some(Boolean)) {
    $('#error-banner').textContent = 'Add a LinkedIn profile, your skills, or tell us what you’re looking for.';
    $('#error-banner').hidden = false;
    $('#prompt').focus();
    return;
  }
  controller = new AbortController();
  $('#error-banner').hidden = true;
  $('#progress-panel').hidden = false;
  $('#progress-message').textContent = demo ? 'Preparing your sample profile…' : 'Reading your profile and public posts…';
  $$('[data-step]').forEach(step => step.classList.remove('done'));
  $('#search-button').disabled = true;
  $('#live-mode').disabled = $('#demo-mode').disabled = true;
  $('#results-panel').hidden = true;
  let completed = false;
  try {
    const response = await fetch('/api/search', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify(payload), signal:controller.signal,
    });
    if (!response.ok) {
      const error = await response.json();
      const message = Array.isArray(error.detail) ? error.detail.map(e => e.msg).join(' ') : error.detail;
      throw new Error(message || 'Something went wrong. Please try again.');
    }
    const reader = response.body.getReader(), decoder = new TextDecoder();
    let buffer = '';
    const consume = line => {
      if (!line.trim()) return;
      const event = JSON.parse(line);
      handleEvent(event);
      if (event.event === 'result') completed = true;
    };
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream:true });
      const lines = buffer.split('\n');
      buffer = lines.pop();
      lines.forEach(consume);
    }
    buffer += decoder.decode();
    consume(buffer);
    if (!completed) throw new Error('The connection ended before your results arrived. Please try again.');
    $('#results-panel').scrollIntoView({ behavior:matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth', block:'start' });
  } catch (error) {
    if (error.name === 'AbortError') toast('Search cancelled.');
    else { $('#error-banner').textContent = error.message; $('#error-banner').hidden = false; }
    if (result) $('#results-panel').hidden = false;
  } finally {
    controller = null;
    $('#progress-panel').hidden = true;
    $('#search-button').disabled = false;
    $('#live-mode').disabled = $('#demo-mode').disabled = false;
  }
};
$('#cancel-button').onclick = () => controller?.abort();

function emptyState(title, text) {
  return `<div class="empty-state"><span>✧</span><h3>${escapeHTML(title)}</h3><p>${escapeHTML(text)}</p></div>`;
}
function jobCard(job) {
  const isSaved = saved.some(j => j.id === job.id);
  const isDemo = job.id.startsWith('demo-');
  return `<article class="job-card glass">
    <div class="job-card-top"><div class="company-avatar">${escapeHTML((job.company || '?').slice(0,2).toUpperCase())}</div><div><div class="company-name">${escapeHTML(job.company)}</div><div class="source-name">via ${escapeHTML(job.source)} ${isDemo ? '<span class="demo-badge">DEMO</span>' : ''}</div></div><button class="save-button ${isSaved?'saved':''}" data-save="${escapeHTML(job.id)}" aria-label="${isSaved?'Unsave':'Save'} ${escapeHTML(job.title)}" aria-pressed="${isSaved}">${isSaved?'♥':'♡'}</button></div>
    <h3>${escapeHTML(job.title)}</h3><div class="job-meta">⌖ ${escapeHTML(job.location)} &nbsp; · &nbsp; ${escapeHTML(job.kind)}</div>
    <div class="skill-tags">${job.skills.slice(0,5).map(s => `<span>${escapeHTML(s)}</span>`).join('')}</div>
    <p class="match-reason">${escapeHTML(job.reason)}</p>
    ${job.salary && job.salary !== 'Not listed' ? `<p class="job-meta">${escapeHTML(job.salary)}</p>` : ''}
    <div class="job-bottom"><span class="match-score"><strong>${escapeHTML(job.match_score)}%</strong> estimated fit</span><a class="job-link" href="${escapeHTML(safeURL(job.url))}" target="_blank" rel="noopener noreferrer">${isDemo?'Explore platform':'View opportunity'} ↗</a></div>
    <p class="availability">${escapeHTML(job.availability)}</p>
  </article>`;
}
function bindSaveButtons() {
  $$('[data-save]').forEach(button => button.onclick = () => {
    const id = button.dataset.save, exists = saved.some(j => j.id === id);
    if (exists) saved = saved.filter(j => j.id !== id);
    else {
      const job = result?.jobs.find(j => j.id === id);
      if (job) saved.push(job);
    }
    try { localStorage.setItem('careerglass-saved', JSON.stringify(saved)); }
    catch { toast('Browser storage is unavailable; saved for this session only.'); }
    $('#saved-count').textContent = saved.length;
    if (result) renderJobs();
    renderSaved();
  });
}
function renderJobs() {
  let jobs = result.jobs.filter(j => activeFilter === 'All' || j.kind === activeFilter);
  jobs = [...jobs].sort($('#sort-order').value === 'title' ? (a,b) => a.title.localeCompare(b.title) : (a,b) => b.match_score - a.match_score);
  $('#job-grid').innerHTML = jobs.length ? jobs.map(jobCard).join('') : emptyState('A little more direction could help.', 'No matching listings here. Try another domain, more platforms, or add your skills and experience.');
  bindSaveButtons();
}
function renderSaved() {
  $('#saved-grid').innerHTML = saved.length ? saved.map(jobCard).join('') : emptyState('Make room for possibility.', 'Tap the heart on an opportunity to keep it here.');
  bindSaveButtons();
}
function renderResults() {
  $('#welcome-panel').hidden = true;
  $('#results-panel').hidden = false;
  $('#result-count').textContent = result.jobs.length;
  $('#summary-card').innerHTML = `<div class="summary-icon">✧</div><div><h3>A note from your career companion ${result.demo?'<span class="demo-badge">DEMO PREVIEW</span>':''}</h3><p>${escapeHTML(result.summary.message)}</p><ul>${result.summary.next_steps.map(s => `<li>${escapeHTML(s)}</li>`).join('')}</ul></div>`;
  $('#source-status').innerHTML = result.source_status.map(s => `<span>${s.status==='error'?'!':'◌'} ${escapeHTML(s.source)} · ${escapeHTML(s.status)}${s.status !== 'demo' ? ` (${s.count} candidates)` : ''}</span>`).join('');
  $('#warnings').innerHTML = result.warnings.map(w => `<p class="warning">${escapeHTML(w)}</p>`).join('');
  renderJobs();
  renderProfile();
}
function renderProfile() {
  if (!result) {
    $('#profile-card').innerHTML = emptyState('Your story starts here.', 'Run a search to see your profile insights, skills, and public-post themes.');
    return;
  }
  const p = result.profile;
  $('#profile-card').innerHTML = `<h2>${escapeHTML(p.name)} ${result.demo?'<span class="demo-badge">SAMPLE PROFILE</span>':''}</h2><p>${escapeHTML(p.headline)}</p><h3>A snapshot of you</h3><p>${escapeHTML(p.summary)}</p><h3>Skills found</h3><div class="skill-tags">${p.skills.length?p.skills.map(s => `<span>${escapeHTML(s)}</span>`).join(''):'<p>No skills could be confirmed from the available evidence.</p>'}</div><h3>Public-post themes</h3><p>${escapeHTML(p.post_themes.join(' · ') || 'No attributable public posts were available.')}</p><h3>Your direction</h3><p>${escapeHTML(p.domain || 'Open to possibilities')} · ${escapeHTML(p.kind)} · ${escapeHTML(p.location || 'Location not specified')}</p><h3>Roles to explore</h3><ul>${p.suggested_roles.map(r => `<li>${escapeHTML(r)}</li>`).join('')}</ul><p class="evidence-note">${escapeHTML(p.evidence_note)}</p>`;
}
$$('[data-filter]').forEach(button => button.onclick = () => {
  activeFilter = button.dataset.filter;
  $$('[data-filter]').forEach(b => { b.classList.toggle('selected', b === button); b.setAttribute('aria-pressed', String(b === button)); });
  if (result) renderJobs();
});
$('#sort-order').onchange = () => { if (result) renderJobs(); };
$('#export-button').onclick = () => {
  if (!result) return;
  const lines = [
    '# CareerGlass — Your opportunity report',
    `Generated: ${new Date().toLocaleString()}`,
    result.demo ? '**DEMO — fictional sample profile and opportunities**' : 'Search-index results; check current availability on each source.',
    '\n## Your profile', result.profile.summary, `Skills: ${result.profile.skills.join(', ')}`,
    `Evidence: ${result.profile.evidence_note}`, '\n## A note from your career companion',
    result.summary.message, ...result.summary.next_steps.map(s => `- ${s}`),
    '\n## Opportunities', ...result.jobs.map(j => `\n### ${j.title} — ${j.company}\n- ${j.location} · ${j.kind} · ${j.source}\n- Estimated relevance: ${j.match_score}%\n- ${j.reason}\n- ${j.availability}\n- ${j.url}`),
    '\n## Search notes', ...result.warnings.map(w => `- ${w}`),
  ];
  const url = URL.createObjectURL(new Blob([lines.join('\n\n')], { type:'text/markdown' }));
  const a = document.createElement('a'); a.href = url; a.download = 'careerglass-report.md'; a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  toast('Your report is ready.');
};
$('#saved-count').textContent = saved.length;
setMode(false);
renderProfile();
fetch('/api/health').then(r => { if (!r.ok) throw new Error(); return r.json(); }).then(data => {
  $('#connection').textContent = data.live_ready ? 'API keys configured' : 'Demo ready · keys needed for live';
}).catch(() => { $('#connection').textContent = 'Server unavailable'; });

'use strict';

(() => {
  const $ = (id) => document.getElementById(id);
  const labels = {draft: 'Borrador', review: 'En revisión', ready: 'Listo', published: 'Publicado'};
  const fields = ['title', 'script', 'status', 'language', 'format', 'youtube_url', 'preview_url', 'youtube_title', 'description', 'tags', 'channel', 'notes', 'social_account_id'];
  const metricFields = ['views', 'likes', 'comments', 'shares', 'average_view_duration_seconds', 'retention_percent'];
  const state = {csrf: '', items: [], current: null, baseline: '', dirty: false, metricDirty: false, busy: false, authenticated: false, loaded: false, selectionRequest: 0, metricRequest: 0};
  const editor = $('editor-form');
  const refs = {items: [], current: null, loaded: false, mode: false, request: 0};
  const socials = {items: [], loaded: false, request: 0};
  let libraryMode = location.pathname === '/social' ? 'social' : location.pathname === '/scripts' ? 'scripts' : 'owned';
  const platforms = {instagram: 'Instagram', tiktok: 'TikTok', youtube: 'YouTube'};
  const referenceTypes = {short: 'Short', video: 'Vídeo', live: 'Directo', post: 'Publicación'};
  const numberFormat = new Intl.NumberFormat('es-ES', {maximumFractionDigits: 2});
  const dateFormat = new Intl.DateTimeFormat('es-ES', {dateStyle: 'medium', timeStyle: 'short'});

  function node(tag, className, text) {
    const el = document.createElement(tag);
    if (className) el.className = className;
    if (text !== undefined) el.textContent = text;
    return el;
  }
  function message(id, text = '', kind = '') {
    const el = $(id);
    el.textContent = text;
    el.className = el.className.replace(/\s(?:error|success)\b/g, '') + (kind ? ` ${kind}` : '');
  }
  function dateText(value) {
    const date = new Date(value);
    return value && !Number.isNaN(date.getTime()) ? dateFormat.format(date) : 'Fecha no disponible';
  }
  function apiError(status, data) {
    const known = {
      400: 'Revisa los campos: el servidor no ha aceptado los datos.',
      401: 'La sesión ha caducado. Vuelve a entrar; conservamos tus cambios en esta pestaña.',
      403: 'No se pudo autorizar la operación. Vuelve a iniciar sesión antes de reintentar.',
      404: 'No se ha encontrado este registro.',
      409: 'El registro ha cambiado. Revisa la información antes de volver a guardar.',
      413: 'El contenido supera el tamaño permitido.',
      422: 'Hay datos que no son válidos. Revisa los campos.',
      429: 'Demasiados intentos. Espera un momento y vuelve a probar.'
    };
    let text = known[status] || 'El servidor no ha podido completar la operación. Inténtalo de nuevo.';
    if (status === 400 || status === 422) {
      const detail = data && (data.message || data.detail || data.error);
      if (typeof detail === 'string') text += ` ${detail.slice(0, 300)}`;
    }
    return text;
  }
  async function api(path, options = {}) {
    const method = options.method || 'GET';
    const headers = {Accept: 'application/json'};
    if (method !== 'GET') {
      headers['Content-Type'] = 'application/json';
      if (state.csrf) headers['X-CSRF-Token'] = state.csrf;
    }
    let response;
    try {
      response = await fetch(path, {method, headers, credentials: 'same-origin', cache: 'no-store', ...(options.body === undefined ? {} : {body: JSON.stringify(options.body)})});
    } catch (_) {
      throw new Error('No hay conexión con el servidor. Tus cambios siguen aquí; vuelve a intentarlo.');
    }
    let data = {};
    if (response.status !== 204) {
      try { data = await response.json(); }
      catch (_) {
        if (response.ok) throw new Error('El servidor devolvió una respuesta inesperada. Comprueba el resultado antes de repetir la operación.');
      }
    }
    if (!response.ok) {
      if (response.status === 401 && path !== '/auth/login' && path !== '/auth/me') showLogin(true);
      const error = new Error(apiError(response.status, data));
      error.status = response.status;
      throw error;
    }
    return data;
  }
  function showLogin(expired = false) {
    state.authenticated = false;
    state.csrf = '';
    $('boot-state').hidden = true;
    $('workspace').hidden = true;
    $('session').hidden = true;
    $('login-view').hidden = false;
    $('login-explanation').textContent = expired ? 'Tu sesión ha caducado. Entra de nuevo: los cambios de esta pestaña se conservarán.' : 'Usa tu cuenta de administración para continuar.';
    if (expired) message('login-message', 'No cierres esta pestaña si tienes cambios sin guardar.', 'error');
  }
  async function startSession(data) {
    if (!data.user || !data.csrf_token) throw new Error('El servidor no ha enviado una sesión válida. Vuelve a intentarlo.');
    state.csrf = data.csrf_token;
    state.authenticated = true;
    $('session-user').textContent = data.user.username;
    $('session').hidden = false;
    $('boot-state').hidden = true;
    $('login-view').hidden = true;
    $('password').value = '';
    if (!state.loaded) await loadList();
    if (!socials.loaded) await loadSocials();
    switchLibrary(libraryMode);
    if (state.authenticated) $('workspace').hidden = false;
  }
  function hasEdits() { return state.dirty || state.metricDirty; }
  function mayLeave() {
    if (state.busy) return false;
    return !hasEdits() || window.confirm('Hay cambios sin guardar. ¿Quieres descartarlos y continuar?');
  }
  function readEditor() {
    const data = {};
    for (const name of fields) data[name] = editor.elements.namedItem(name).value;
    data.title = data.title.trim();
    data.youtube_url = data.youtube_url.trim();
    data.preview_url = data.preview_url.trim();
    data.tags = data.tags.split(',').map((tag) => tag.trim()).filter(Boolean);
    data.social_account_id = data.social_account_id || null;
    return data;
  }
  function updateDirty() {
    state.dirty = JSON.stringify(readEditor()) !== state.baseline;
    $('save-state').textContent = state.dirty ? 'Cambios sin guardar' : (state.current && state.current.id != null ? 'Sin cambios' : 'Borrador nuevo');
    $('save-state').classList.toggle('dirty', state.dirty);
    const script = $('script').value.trim();
    const words = script ? script.split(/\s+/u).length : 0;
    $('word-count').textContent = `${numberFormat.format(words)} ${words === 1 ? 'palabra' : 'palabras'}`;
  }
  function setBusy(busy) {
    state.busy = busy;
    for (const el of editor.elements) el.disabled = busy;
    for (const el of $('metric-form').elements) el.disabled = busy;
    for (const id of ['save-short', 'new-short', 'empty-new', 'logout']) $(id).disabled = busy;
    $('save-metric').disabled = busy;
    $('save-short').textContent = busy ? 'Guardando…' : 'Guardar cambios';
    editor.setAttribute('aria-busy', String(busy));
  }
  function statusBadge(status) {
    const badge = node('span', 'status-badge', labels[status] || 'Sin estado');
    badge.dataset.status = status || '';
    return badge;
  }
  function renderList() {
    const query = $('search').value.trim().toLocaleLowerCase('es');
    const filter = $('status-filter').value;
    const items = state.items.filter((item) => (!filter || item.status === filter) && (!query || [item.title, item.script, item.channel].some((v) => String(v || '').toLocaleLowerCase('es').includes(query))));
    $('total-count').textContent = String(state.items.length);
    $('list-caption').textContent = `${items.length} ${items.length === 1 ? 'pieza' : 'piezas'}${filter || query ? ' en esta vista' : ' en el estudio'}`;
    const list = $('short-list');
    list.replaceChildren();
    if (!items.length) {
      const li = node('li', 'sidebar-message muted', state.items.length ? 'No hay piezas con estos filtros.' : 'Tu biblioteca está vacía. Crea el primer borrador con «Nuevo».');
      list.append(li);
      return;
    }
    for (const item of items) {
      const li = node('li');
      const button = node('button', 'short-item');
      button.type = 'button';
      const selected = state.current && String(state.current.id) === String(item.id);
      button.classList.toggle('selected', Boolean(selected));
      if (selected) button.setAttribute('aria-current', 'true');
      const top = node('span', 'short-item-top');
      top.append(statusBadge(item.status), node('span', 'short-item-format', item.format || '—'));
      button.append(top, node('span', 'short-item-title', item.title || 'Sin título'), node('span', 'short-item-meta', `${item.channel || 'Sin canal'} · ${item.language === 'en' ? 'EN' : 'ES'}`));
      if (libraryMode === 'scripts') button.append(node('span', 'short-item-meta', (item.script || '').trim() ? 'Guion disponible · Leer o editar' : 'Sin guion · Pendiente de escribir'));
      button.addEventListener('click', () => selectShort(item.id));
      li.append(button);
      list.append(li);
    }
  }
  async function loadList() {
    $('refresh-list').disabled = true;
    message('list-message', 'Cargando biblioteca…');
    try {
      const data = await api('/v1/shorts');
      if (!Array.isArray(data.items)) throw new Error('No se ha recibido una lista válida.');
      state.items = data.items;
      state.loaded = true;
      renderList();
      message('list-message');
    } catch (error) { message('list-message', error.message, 'error'); }
    finally { $('refresh-list').disabled = false; }
  }
  function resetMetricForm() {
    $('metric-form').reset();
    const now = new Date();
    const local = new Date(now.getTime() - now.getTimezoneOffset() * 60000);
    $('observed_at').value = local.toISOString().slice(0, 16);
    state.metricDirty = false;
    $('metric-entry').open = false;
  }
  function fillRecord(record) {
    state.current = record;
    // Preserve an association even if its account was removed from the inventory.
    if (record.social_account_id && !Array.from($('social_account_id').options).some(o => o.value === record.social_account_id)) {
      const option = node('option', '', record.social_account_id + ' · No disponible en inventario');
      option.value = record.social_account_id; $('social_account_id').append(option);
    }
    for (const name of fields) {
      let value = record[name];
      if (name === 'tags') value = Array.isArray(value) ? value.join(', ') : value || '';
      editor.elements.namedItem(name).value = value == null ? '' : value;
    }
    if (!$('status').value) $('status').value = 'draft';
    if (!$('language').value) $('language').value = 'es';
    if (!$('format').value) $('format').value = '9:16';
    state.baseline = JSON.stringify(readEditor());
    updateDirty();
    $('detail-title').textContent = record.title || 'Nuevo vídeo';
    $('record-label').textContent = record.id == null ? 'NUEVA PIEZA' : 'PIEZA EDITORIAL';
    $('record-updated').textContent = record.updated_at ? `Actualizado el ${dateText(record.updated_at)}` : 'Todavía no guardado';
    $('detail-status').textContent = labels[record.status] || 'Borrador';
    $('detail-status').dataset.status = record.status || 'draft';
    $('empty-detail').hidden = true;
    $('detail').hidden = false;
    renderPreview();
    renderList();
  }
  async function selectShort(id) {
    if (state.current && String(state.current.id) === String(id)) return;
    if (!mayLeave()) return;
    const request = ++state.selectionRequest;
    const editorAtRequest = JSON.stringify(readEditor());
    const metricsAtRequest = JSON.stringify(Array.from(new FormData($('metric-form')).entries()));
    message('global-message', 'Abriendo vídeo…');
    try {
      const record = await api(`/v1/shorts/${encodeURIComponent(id)}`);
      if (request !== state.selectionRequest) return;
      if (record.id == null) throw new Error('El servidor no ha enviado una pieza válida.');
      // Do not overwrite edits made while the request was in flight.
      const changedDuringLoad = JSON.stringify(readEditor()) !== editorAtRequest || JSON.stringify(Array.from(new FormData($('metric-form')).entries())) !== metricsAtRequest;
      if (changedDuringLoad && !window.confirm('Has editado mientras se cargaba otra pieza. ¿Descartar esos cambios y abrirla?')) { message('global-message'); return; }
      ++state.metricRequest;
      fillRecord(record);
      resetMetricForm();
      message('global-message');
      showSection('editor');
      $('detail-title').setAttribute('tabindex', '-1');
      $('detail-title').focus({preventScroll: true});
    } catch (error) { if (request === state.selectionRequest) message('global-message', error.message, 'error'); }
  }
  function newShort() {
    if (!mayLeave()) return;
    ++state.selectionRequest;
    ++state.metricRequest;
    fillRecord({title: '', script: '', status: 'draft', language: 'es', format: '9:16', tags: []});
    resetMetricForm();
    message('global-message');
    showSection('editor');
    $('short-title').focus();
  }
  function youtubeId(value) {
    if (!value) return null;
    try {
      const url = new URL(value);
      if (!['https:', 'http:'].includes(url.protocol) || url.username || url.password || url.port) return null;
      const host = url.hostname.toLowerCase();
      const parts = url.pathname.split('/').filter(Boolean);
      let id = null;
      if (host === 'youtu.be' && parts.length === 1) id = parts[0];
      if (['youtube.com', 'www.youtube.com', 'm.youtube.com', 'music.youtube.com', 'youtube-nocookie.com', 'www.youtube-nocookie.com'].includes(host)) {
        if (url.pathname === '/watch') id = url.searchParams.get('v');
        else if (parts.length === 2 && ['shorts', 'embed', 'live'].includes(parts[0])) id = parts[1];
      }
      return /^[A-Za-z0-9_-]{11}$/.test(id || '') ? id : null;
    } catch (_) { return null; }
  }
  function safePreview(value) {
    if (!value) return null;
    try {
      const url = new URL(value, location.origin);
      if (url.username || url.password) return null;
      const local = value.startsWith('/media/') && url.origin === location.origin && url.pathname.startsWith('/media/');
      if (local) return {url: url.href, video: true};
      if (url.protocol === 'https:' && /^https:\/\//i.test(value)) return {url: url.href, video: /\.mp4$/i.test(url.pathname)};
      return null;
    } catch (_) { return null; }
  }
  function previewPlaceholder(title, description) {
    const content = $('preview-content');
    const symbol = node('span', 'preview-symbol');
    symbol.setAttribute('aria-hidden', 'true');
    content.append(symbol, node('strong', '', title), node('p', '', description));
  }
  function renderPreview() {
    const content = $('preview-content');
    content.replaceChildren();
    const format = $('format').value;
    $('preview-stage').classList.toggle('landscape', format === '16:9');
    $('preview-format').textContent = format;
    const youtube = $('youtube_url').value.trim();
    const preview = $('preview_url').value.trim();
    const id = youtubeId(youtube);
    const media = safePreview(preview);
    $('youtube-open').hidden = !id;
    $('youtube-open').removeAttribute('href');
    if (id) $('youtube-open').href = `https://www.youtube.com/watch?v=${id}`;
    $('preview-help').textContent = format === '16:9' ? 'Formato horizontal 16:9. Se respeta la proporción del archivo.' : 'Formato vertical 9:16. Se respeta la proporción del archivo.';
    if (media && media.video) {
      previewPlaceholder('Archivo disponible', 'Carga la vista previa para revisar el vídeo.');
      const load = node('button', 'button button-secondary', 'Cargar vista previa');
      load.type = 'button';
      load.addEventListener('click', () => {
        const video = node('video');
        video.controls = true;
        video.playsInline = true;
        video.preload = 'metadata';
        video.setAttribute('aria-label', 'Vista previa del vídeo');
        video.addEventListener('error', () => { $('preview-help').textContent = 'No se pudo reproducir este archivo. Revisa el enlace y el formato del vídeo.'; });
        video.src = media.url;
        content.replaceChildren(video);
      });
      content.append(load);
    } else if (id) {
      previewPlaceholder('Vista previa de YouTube', 'Solo se conecta con YouTube cuando tú lo solicitas.');
      const load = node('button', 'button button-secondary', 'Cargar vista previa');
      load.type = 'button';
      load.addEventListener('click', () => {
        const frame = node('iframe');
        frame.title = 'Vista previa de YouTube';
        frame.referrerPolicy = 'strict-origin-when-cross-origin';
        frame.allow = 'encrypted-media; picture-in-picture; fullscreen';
        frame.allowFullscreen = true;
        frame.src = `https://www.youtube-nocookie.com/embed/${id}`;
        content.replaceChildren(frame);
        $('preview-help').textContent = 'Reproductor de YouTube cargado. Si el vídeo no permite inserción, ábrelo con el enlace inferior.';
      });
      content.append(load);
    } else if (media) {
      previewPlaceholder('Vista previa externa', 'Este enlace se abre aparte; no se incrusta en el estudio.');
    } else {
      previewPlaceholder('Vista previa pendiente', 'Añade el vídeo del creador o un enlace de YouTube en los detalles.');
    }
    if (media && !media.video) {
      const link = node('a', 'external-link', 'Abrir vista previa externa ↗');
      link.href = media.url;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      content.append(link);
    }
    if ((youtube && !id) || (preview && !media)) $('preview-help').textContent = 'Hay un enlace no válido. Revisa los detalles; no se cargará contenido desde ese enlace.';
  }
  function validateLinks() {
    const youtube = $('youtube_url');
    const preview = $('preview_url');
    youtube.setCustomValidity(youtube.value.trim() && !youtubeId(youtube.value.trim()) ? 'Introduce un enlace válido a un vídeo de YouTube.' : '');
    preview.setCustomValidity(preview.value.trim() && !safePreview(preview.value.trim()) ? 'Usa un enlace HTTPS o una ruta local /media/.' : '');
  }
  async function saveShort(event) {
    event.preventDefault();
    if (state.busy || !state.current) return;
    validateLinks();
    if (!editor.reportValidity()) return;
    const body = readEditor();
    if (!body.title) { $('short-title').setCustomValidity('Escribe un título de trabajo.'); $('short-title').reportValidity(); return; }
    const creating = state.current.id == null;
    if (creating) body.status = 'draft';
    ++state.selectionRequest;
    setBusy(true);
    message('global-message');
    try {
      const written = await api(creating ? '/v1/shorts' : `/v1/shorts/${encodeURIComponent(state.current.id)}`, {method: creating ? 'POST' : 'PATCH', body});
      if (written.id == null) throw new Error('Guardado sin identificador. Actualiza la biblioteca antes de repetir.');
      state.current = written;
      const record = await api(`/v1/shorts/${encodeURIComponent(written.id)}`);
      if (record.id == null) throw new Error('La respuesta de guardado está incompleta. Tus cambios siguen aquí; comprueba la biblioteca antes de repetir.');
      const index = state.items.findIndex((item) => String(item.id) === String(record.id));
      if (index === -1) state.items.unshift(record); else state.items[index] = record;
      fillRecord(record);
      message('global-message', creating ? 'Borrador creado y comprobado. No se ha publicado en ninguna plataforma.' : 'Cambios guardados y comprobados. No se ha publicado en ninguna plataforma.', 'success');
      $('save-state').textContent = 'Guardado';
    } catch (error) { message('global-message', error.message, 'error'); }
    finally { setBusy(false); }
  }
  function showSection(section) {
    const metrics = section === 'metrics';
    const reading = section === 'script-read';
    $('editor-panel').hidden = metrics || reading;
    $('metrics-panel').hidden = !metrics;
    $('script-read-panel').hidden = !reading;
    if (reading) $('script-reading').textContent = $('script').value || 'Sin guion. Abre Edición para escribirlo.';
    for (const name of ['editor', 'metrics', 'script-read']) {
      const active = name === section;
      $(`${name}-tab`).classList.toggle('active', active);
      $(`${name}-tab`).setAttribute('aria-pressed', String(active));
    }
    if (metrics) loadMetrics();
  }
  function metricValue(value, suffix = '') {
    return value == null || value === '' || !Number.isFinite(Number(value)) ? '—' : `${numberFormat.format(Number(value))}${suffix}`;
  }
  function renderMetrics(items) {
    const container = $('metrics-history');
    container.replaceChildren();
    if (!items.length) {
      const empty = node('div', 'metrics-empty');
      empty.append(node('strong', '', 'Todavía no hay capturas'), node('span', '', 'Registra una observación para empezar el historial. Los campos vacíos se mostrarán como «—».'));
      container.append(empty);
      return;
    }
    const wrapper = node('div', 'table-scroll');
    wrapper.tabIndex = 0;
    wrapper.setAttribute('role', 'region');
    wrapper.setAttribute('aria-label', 'Historial de rendimiento; desplaza horizontalmente para ver todas las columnas');
    const table = node('table');
    table.append(node('caption', '', `${items.length} ${items.length === 1 ? 'captura registrada' : 'capturas registradas'} · Valores no disponibles: —`));
    const thead = node('thead');
    const head = node('tr');
    for (const text of ['Observación', 'Visualizaciones', 'Me gusta', 'Comentarios', 'Compartidos', 'Duración media', 'Retención', 'Fuente']) {
      const th = node('th', '', text); th.scope = 'col'; head.append(th);
    }
    thead.append(head); table.append(thead);
    const tbody = node('tbody');
    const sorted = [...items].sort((a, b) => new Date(b.observed_at) - new Date(a.observed_at));
    for (const item of sorted) {
      const tr = node('tr');
      const observed = node('td', '', dateText(item.observed_at));
      if (item.notes) observed.append(node('span', 'metric-note', item.notes));
      tr.append(observed);
      for (const field of metricFields) tr.append(node('td', '', metricValue(item[field], field === 'retention_percent' ? ' %' : field === 'average_view_duration_seconds' ? ' s' : '')));
      tr.append(node('td', '', item.source === 'manual' ? 'Manual' : item.source || '—'));
      tbody.append(tr);
    }
    table.append(tbody); wrapper.append(table); container.append(wrapper);
  }
  async function loadMetrics() {
    const id = state.current && state.current.id;
    const request = ++state.metricRequest;
    $('metric-entry').hidden = id == null;
    $('refresh-metrics').disabled = true;
    if (id == null) {
      $('metrics-history').replaceChildren(node('p', 'metrics-empty', 'Guarda primero el borrador para añadir capturas de rendimiento.'));
      message('metrics-message');
      return;
    }
    message('metrics-message', 'Cargando capturas…');
    $('metrics-history').replaceChildren();
    try {
      const data = await api(`/v1/shorts/${encodeURIComponent(id)}/metrics`);
      if (request !== state.metricRequest) return;
      if (!Array.isArray(data.items)) throw new Error('No se ha recibido un historial válido.');
      renderMetrics(data.items);
      message('metrics-message');
    } catch (error) { if (request === state.metricRequest) message('metrics-message', error.message, 'error'); }
    finally { if (request === state.metricRequest) $('refresh-metrics').disabled = false; }
  }
  async function saveMetric(event) {
    event.preventDefault();
    if (state.busy || !state.current || state.current.id == null) return;
    const form = $('metric-form');
    if (!form.reportValidity()) return;
    const observed = new Date($('observed_at').value);
    if (Number.isNaN(observed.getTime())) { message('metrics-message', 'Selecciona una fecha y hora válidas.', 'error'); return; }
    const body = {observed_at: observed.toISOString(), source: 'manual', notes: $('metric-notes').value};
    for (const name of metricFields) {
      const value = $(name).value.trim();
      body[name] = value === '' ? null : Number(value);
      if (body[name] !== null && (!Number.isFinite(body[name]) || body[name] < 0 || (['views', 'likes', 'comments', 'shares'].includes(name) && !Number.isSafeInteger(body[name])))) {
        message('metrics-message', 'Revisa los valores: los recuentos deben ser enteros no negativos.', 'error');
        return;
      }
    }
    setBusy(true);
    $('save-metric').textContent = 'Guardando captura…';
    try {
      await api(`/v1/shorts/${encodeURIComponent(state.current.id)}/metrics`, {method: 'POST', body});
      resetMetricForm();
      await loadMetrics();
      message('global-message', 'Captura guardada. Los valores vacíos se han conservado como no disponibles.', 'success');
    } catch (error) { message('metrics-message', error.message, 'error'); }
    finally { setBusy(false); $('save-metric').textContent = 'Guardar captura'; }
  }

  function profileURL(account) {
    if (typeof account.profile_url !== 'string' || /[\s\\\x00-\x1f]/.test(account.profile_url)) return null;
    try {
      const url = new URL(account.profile_url);
      const hosts = {instagram: ['instagram.com', 'www.instagram.com'], tiktok: ['tiktok.com', 'www.tiktok.com'], youtube: ['youtube.com', 'www.youtube.com']};
      if (url.protocol !== 'https:' || url.username || url.password || url.port || !(hosts[account.platform] || []).includes(url.hostname)) return null;
      return url.href;
    } catch (_) { return null; }
  }
  function renderSocials() {
    const query = $('social-search').value.trim().toLocaleLowerCase('es');
    const platform = $('social-platform').value;
    const items = socials.items.filter(a => (!platform || a.platform === platform) && (!query || [a.name, a.handle, a.id].some(v => String(v || '').toLocaleLowerCase('es').includes(query))));
    $('social-count').textContent = String(socials.items.length);
    $('social-caption').textContent = `${items.length} de ${socials.items.length} cuentas · ${Object.keys(platforms).map(p => `${socials.items.filter(a => a.platform === p).length} ${platforms[p]}`).join(' · ')}`;
    $('social-list').replaceChildren();
    if (!items.length) $('social-list').append(node('li', 'muted', 'No hay cuentas con estos filtros.'));
    for (const account of items) {
      const card = node('li', 'social-card');
      card.append(node('p', 'eyebrow', platforms[account.platform] || account.platform), node('h2', '', account.name), node('p', '', account.handle == null ? 'Handle pendiente de confirmar' : account.handle), node('p', 'small muted', `ID: ${account.id}`), node('p', '', account.ownership === 'user_confirmed' ? 'Propiedad: confirmada por el usuario' : `Propiedad: ${account.ownership || 'pendiente'}`), node('p', '', `Analítica no conectada · ${account.sync_status}`));
      const evidence = account.analytics;
      card.append(node('p', 'social-evidence', evidence && evidence.subscribers != null ? `${numberFormat.format(evidence.subscribers)} suscriptores · Observación de captura, NO en directo. ${evidence.observed_at ? dateText(evidence.observed_at) : 'Fecha de captura desconocida'}.` : 'Sin mediciones aportadas. No equivale a cero.'));
      card.append(node('p', 'small muted', `Fuente del inventario: ${account.source}`));
      const url = profileURL(account);
      if (url) {
        const link = node('a', 'external-link', 'Abrir perfil ↗');
        link.href = url; link.target = '_blank'; link.rel = 'noopener noreferrer'; card.append(link);
      } else card.append(node('p', 'muted', 'URL pendiente de confirmar · Sin enlace disponible'));
      $('social-list').append(card);
    }
  }
  async function loadSocials() {
    const request = ++socials.request;
    $('refresh-social').disabled = true;
    message('social-message', 'Cargando inventario…');
    try {
      const data = await api('/v1/social-accounts');
      if (request !== socials.request || !state.authenticated) return;
      if (!Array.isArray(data.items)) throw new Error('No se ha recibido un inventario válido.');
      socials.items = data.items; socials.loaded = true;
      const select = $('social_account_id');
      const selected = select.value;
      select.replaceChildren(new Option('Sin cuenta asociada', ''));
      for (const account of socials.items) select.append(new Option(`${platforms[account.platform]} · ${account.name} · ${account.handle == null ? 'handle desconocido' : account.handle}`, account.id));
      if (selected && !Array.from(select.options).some(o => o.value === selected)) select.append(new Option(selected + ' · No disponible en inventario', selected));
      select.value = selected;
      renderSocials(); message('social-message');
      $('social-selector-help').textContent = 'Vinculación editorial, no conexión a la plataforma. No cambia el canal ni agrupa marcas. Los nuevos registros se guardan siempre como borrador.';
    } catch (error) {
      message('social-message', error.message, 'error');
      $('social-selector-help').textContent = 'No se pudo cargar el inventario. Puedes editar el guion; vuelve a Mis redes para reintentar.';
    } finally { if (request === socials.request) $('refresh-social').disabled = false; }
  }

  function referenceViews(item) {
    if (item.views == null) return `Visualizaciones no disponibles${item.views_text ? ` · Texto público: ${item.views_text}` : ''}`;
    return `${numberFormat.format(item.views)} visualizaciones (${item.views_approximate ? 'aproximadas' : 'exactas'})${item.views_text ? ` · ${item.views_text}` : ''}`;
  }
  function referenceURL(item) {
    try {
      if (/[\s\\\x00-\x1f]/.test(item.url)) return null;
      const url = new URL(item.url);
      if (url.protocol !== 'https:' || !['youtube.com', 'www.youtube.com', 'm.youtube.com', 'youtu.be'].includes(url.hostname) || url.username || url.password || url.port) return null;
      if (item.content_type === 'post') return url.hostname !== 'youtu.be' && /^\/post\/[A-Za-z0-9_-]{1,200}$/.test(url.pathname) && url.pathname.slice(6) === item.source_id ? url.href : null;
      return youtubeId(item.url) === item.source_id && url.searchParams.getAll('v').length <= 1 ? url.href : null;
    } catch (_) { return null; }
  }
  function renderReferences() {
    const query = $('reference-search').value.trim().toLocaleLowerCase('es');
    const type = $('reference-type').value;
    const sort = $('reference-sort').value;
    const items = refs.items.filter((item) => (!type || type === item.content_type) && (!query || [item.title, item.topic].some((v) => String(v || '').toLocaleLowerCase('es').includes(query))));
    const score = (item) => sort === 'views' ? (item.views == null ? -1 : item.views) : (Date.parse(item.published_at || '') || -1);
    items.sort((a, b) => score(b) - score(a) || a.id - b.id);
    $('reference-count').textContent = String(refs.items.length);
    $('reference-caption').textContent = `${items.length} referencias en esta vista`;
    const list = $('reference-list');
    list.replaceChildren();
    if (!items.length) list.append(node('li', 'sidebar-message muted', refs.items.length ? 'No hay referencias con estos filtros.' : 'Sin referencias importadas. No se han añadido ejemplos ficticios.'));
    for (const item of items) {
      const li = node('li');
      const button = node('button', 'short-item');
      button.type = 'button';
      const selected = refs.current && refs.current.id === item.id;
      button.classList.toggle('selected', Boolean(selected));
      if (selected) button.setAttribute('aria-current', 'true');
      button.append(node('span', 'short-item-meta', `${referenceTypes[item.content_type]} · ${item.channel_name || item.channel_id}`), node('span', 'short-item-title', item.title), node('span', 'short-item-meta', item.topic || 'Tema no clasificado'), node('span', 'short-item-meta', referenceViews(item)));
      button.addEventListener('click', () => selectReference(item));
      li.append(button); list.append(li);
    }
  }
  function selectReference(item) {
    refs.current = item;
    $('reference-detail').hidden = false;
    $('reference-empty').hidden = true;
    for (const [id, value] of Object.entries({title: item.title, channel: `${item.channel_name || item.channel_id} · ${referenceTypes[item.content_type]}`, topic: item.topic || 'Sin clasificar', summary: item.summary || 'Sin resumen. No se ha revisado el contenido.', angle: item.agent_angle || 'Sin hipótesis editorial registrada.', notes: item.notes || 'Sin notas adicionales.', description: item.description || 'Descripción no disponible.'})) $('reference-' + id).textContent = value;
    const basis = item.evidence_basis || 'title/description';
    const reviewed = ['transcript', 'transcript_reviewed', 'viewed', 'video_reviewed'].includes(basis);
    const explanation = reviewed ? 'Revisión declarada por el importador; consulta las notas.' : basis === 'community_text' ? 'Basado en el texto público de la publicación; no es un guion.' : 'Basado en título/descripción públicos; no se ha visto el vídeo ni revisado una transcripción.';
    $('reference-basis').textContent = `Nivel de revisión: ${explanation} Base declarada: ${basis}.`;
    $('reference-metrics').textContent = `${referenceViews(item)} · ${item.likes == null ? 'Me gusta no disponibles' : `${numberFormat.format(item.likes)} Me gusta`}${item.duration_seconds == null ? '' : ` · ${numberFormat.format(item.duration_seconds)} s`}`;
    const publication = /^\d{4}-\d{2}-\d{2}$/.test(item.published_at || '') ? item.published_at : dateText(item.published_at);
    $('reference-dates').textContent = `Observado: ${dateText(item.observed_at)} · Publicación: ${publication}`;
    $('reference-kind').textContent = referenceTypes[item.content_type];
    $('reference-stage').classList.toggle('landscape', item.content_type !== 'short');
    const content = $('reference-preview');
    content.replaceChildren();
    const url = referenceURL(item);
    $('reference-open').hidden = !url;
    $('reference-open').removeAttribute('href');
    if (url) $('reference-open').href = url;
    if (item.content_type === 'post') content.append(node('p', '', 'Publicación de comunidad. Consulta el texto y los adjuntos en la fuente; no tiene reproductor de vídeo.'));
    else if (url) {
      content.append(node('p', '', 'Vista previa externa · YouTube'));
      const load = node('button', 'button button-secondary', 'Cargar referencia de YouTube');
      load.type = 'button';
      load.addEventListener('click', () => {
        const frame = node('iframe');
        frame.title = `Referencia: ${item.title}`;
        frame.referrerPolicy = 'strict-origin-when-cross-origin';
        frame.allow = 'encrypted-media; picture-in-picture; fullscreen';
        frame.allowFullscreen = true;
        frame.src = `https://www.youtube-nocookie.com/embed/${item.source_id}`;
        content.replaceChildren(frame);
      });
      content.append(load);
    } else content.append(node('p', '', 'Enlace de referencia no válido.'));
    renderReferences();
  }
  async function loadReferences() {
    const request = ++refs.request;
    $('refresh-references').disabled = true;
    message('reference-list-message', 'Cargando referencias…');
    try {
      const [data, status] = await Promise.all([api('/v1/references'), api('/v1/references/status')]);
      if (request !== refs.request || !state.authenticated) return;
      if (!Array.isArray(data.items)) throw new Error('No se ha recibido un catálogo válido.');
      refs.items = data.items; refs.loaded = true;
      const run = status.latest_run;
      $('reference-notice').textContent = run ? `${run.channel_name || run.channel_id}: catálogo ${run.status === 'complete' ? 'declarado completo por el importador' : 'parcial'}. ${status.total} registros almacenados realmente (${Object.entries(status.counts).map(([type, count]) => `${count} ${referenceTypes[type]}`).join(' · ')}). Observado: ${dateText(run.observed_at)}. ${run.notes || ''} Los recuentos declarados de extracción no sustituyen estos totales.` : 'Sin importaciones. No se presupone que el catálogo esté completo.';
      if (refs.current) {
        const refreshed = refs.items.find((item) => item.id === refs.current.id);
        if (refreshed) selectReference(refreshed);
      }
      renderReferences(); message('reference-list-message');
    } catch (error) { if (request === refs.request) message('reference-list-message', error.message, 'error'); }
    finally { if (request === refs.request) $('refresh-references').disabled = false; }
  }
  function switchLibrary(mode) {
    if (state.busy) return;
    if (typeof mode === 'boolean') mode = mode ? 'references' : 'owned';
    libraryMode = mode;
    const referenceMode = mode === 'references';
    const socialMode = mode === 'social';
    refs.mode = referenceMode;
    ++state.selectionRequest;
    $('owned-library').hidden = referenceMode || socialMode;
    $('reference-library').hidden = !referenceMode;
    $('reference-workspace').hidden = !referenceMode;
    $('social-workspace').hidden = !socialMode;
    $('detail').hidden = referenceMode || socialMode || !state.current;
    $('empty-detail').hidden = referenceMode || socialMode || Boolean(state.current);
    $('library-heading').textContent = mode === 'scripts' ? 'Guiones' : 'Biblioteca';
    $('library-label').textContent = mode === 'scripts' ? 'TODAS TUS PIEZAS · CON Y SIN GUION' : 'PRODUCCIÓN';
    $('new-short').textContent = mode === 'scripts' ? '+ Nuevo guion' : '+ Nuevo';
    history.replaceState(null, '', socialMode ? '/social' : mode === 'scripts' ? '/scripts' : '/');
    for (const id of ['owned', 'scripts', 'social', 'references']) {
      const active = id === mode;
      $('library-' + id).classList.toggle('active', active); $('library-' + id).setAttribute('aria-pressed', String(active));
    }
    if (referenceMode) {
      $('preview-content').replaceChildren();
      if (!refs.loaded) loadReferences();
    } else {
      $('reference-preview').replaceChildren();
      if (state.current) renderPreview();
    }
    if (referenceMode && refs.current) selectReference(refs.current);
    if (socialMode) { $('preview-content').replaceChildren(); if (!socials.loaded) loadSocials(); }
    renderList();
  }
  $('library-owned').addEventListener('click', () => switchLibrary(false));
  $('library-references').addEventListener('click', () => switchLibrary(true));
  $('library-scripts').addEventListener('click', () => switchLibrary('scripts'));
  $('library-social').addEventListener('click', () => switchLibrary('social'));
  $('social-search').addEventListener('input', renderSocials);
  $('social-platform').addEventListener('change', renderSocials);
  $('refresh-social').addEventListener('click', loadSocials);
  $('reference-search').addEventListener('input', renderReferences);
  $('reference-type').addEventListener('change', renderReferences);
  $('reference-sort').addEventListener('change', renderReferences);
  $('refresh-references').addEventListener('click', loadReferences);

  $('login-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    $('login-submit').disabled = true;
    $('login-submit').textContent = 'Entrando…';
    message('login-message');
    try {
      const data = await api('/auth/login', {method: 'POST', body: {username: $('username').value, password: $('password').value}});
      await startSession(data);
    } catch (error) {
      message('login-message', error.status === 401 ? 'Usuario o contraseña incorrectos.' : error.message, 'error');
    } finally { $('password').value = ''; $('login-submit').disabled = false; $('login-submit').textContent = 'Entrar'; }
  });
  $('logout').addEventListener('click', async () => {
    if (!mayLeave()) return;
    $('logout').disabled = true;
    try {
      await api('/auth/logout', {method: 'POST', body: {}});
      ++state.selectionRequest; ++state.metricRequest;
      state.items = []; state.current = null; state.loaded = false; state.baseline = ''; state.dirty = false; state.metricDirty = false;
      ++refs.request; refs.items = []; refs.current = null; refs.loaded = false;
      ++socials.request; socials.items = []; socials.loaded = false;
      $('social-list').replaceChildren(); $('social-count').textContent = '0';
      $('social_account_id').replaceChildren(new Option('Sin cuenta asociada', ''));
      $('reference-detail').hidden = true; $('reference-empty').hidden = false;
      renderReferences(); switchLibrary(false);
      editor.reset(); resetMetricForm(); renderList();
      $('preview-content').replaceChildren();
      $('metrics-history').replaceChildren();
      $('detail').hidden = true; $('empty-detail').hidden = false;
      message('global-message'); message('login-message');
      showLogin();
    } catch (error) { message('global-message', error.message, 'error'); }
    finally { $('logout').disabled = false; }
  });
  $('new-short').addEventListener('click', newShort);
  $('empty-new').addEventListener('click', newShort);
  $('search').addEventListener('input', renderList);
  $('status-filter').addEventListener('change', renderList);
  $('refresh-list').addEventListener('click', loadList);
  $('refresh-metrics').addEventListener('click', loadMetrics);
  $('editor-tab').addEventListener('click', () => showSection('editor'));
  $('script-read-tab').addEventListener('click', () => showSection('script-read'));
  $('metrics-tab').addEventListener('click', () => showSection('metrics'));
  $('save-short').addEventListener('click', () => showSection('editor'));
  editor.addEventListener('submit', saveShort);
  editor.addEventListener('input', (event) => {
    if (event.target.id === 'short-title') event.target.setCustomValidity('');
    if (event.target.id === 'youtube_url' || event.target.id === 'preview_url') event.target.setCustomValidity('');
    updateDirty();
  });
  for (const id of ['youtube_url', 'preview_url', 'format']) $(id).addEventListener('change', () => { validateLinks(); renderPreview(); });
  $('metric-form').addEventListener('input', () => { state.metricDirty = true; });
  $('metric-form').addEventListener('submit', saveMetric);
  window.addEventListener('beforeunload', (event) => {
    if (hasEdits() || state.busy) { event.preventDefault(); event.returnValue = ''; }
  });
  document.addEventListener('keydown', (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's' && state.authenticated && state.current && ['owned', 'scripts'].includes(libraryMode)) {
      event.preventDefault();
      if (!state.busy) { showSection('editor'); editor.requestSubmit(); }
    }
  });
  document.querySelector('.brand').addEventListener('click', (event) => { if (!mayLeave()) event.preventDefault(); });
  api('/auth/me').then(startSession).catch((error) => {
    showLogin();
    if (error.status !== 401) message('login-message', error.message, 'error');
  });
})();

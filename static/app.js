'use strict';

(() => {
  const $ = (id) => document.getElementById(id);
  const labels = {draft: 'Borrador', review: 'En revisión', ready: 'Listo', published: 'Publicado'};
  const fields = ['title', 'script', 'status', 'language', 'format', 'youtube_url', 'preview_url', 'thumbnail_url', 'youtube_title', 'description', 'tags', 'channel', 'notes', 'social_account_id'];
  const metricFields = ['views', 'likes', 'comments', 'shares', 'average_view_duration_seconds', 'retention_percent'];
  const state = {csrf: '', items: [], current: null, baseline: '', dirty: false, metricDirty: false, busy: false, authenticated: false, loaded: false, selectionRequest: 0, metricRequest: 0};
  const editor = $('editor-form');
  const refs = {items: [], current: null, loaded: false, mode: false, request: 0};
  const socials = {items: [], loaded: false, request: 0};
  let libraryMode = location.pathname === '/references' ? 'references' : location.pathname === '/' ? 'home' : 'owned';
  let selectedChannel = '', activeSection = 'editor', readingScript = false, recovery = false;
  const initialSocial = location.pathname === '/social';
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
    if (state.current && hasEdits()) { $('detail').hidden = false; $('owned-library').hidden = true; }
    else switchLibrary(libraryMode, false);
    if (initialSocial && !hasEdits()) toggleChannels(true);
    if (state.authenticated) $('workspace').hidden = false;
  }
  function hasEdits() { return state.dirty || state.metricDirty || recovery; }
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
    const originalTags = state.current?.tags;
    data.tags = Array.isArray(originalTags) && data.tags === originalTags.join(', ') ? [...originalTags] : data.tags.split(',').map((tag) => tag.trim()).filter(Boolean);
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
    applyLock();
  }
  function statusBadge(status) {
    const badge = node('span', 'status-badge', labels[status] || 'Sin estado');
    badge.dataset.status = status || '';
    return badge;
  }
  function accountFor(item) { return socials.items.find(a => a.id === item.social_account_id); }
  function channelText(item) { const a = accountFor(item); return a ? `${a.name} · ${platforms[a.platform] || a.platform}` : item.channel || 'Sin canal'; }
  function channelMatch(item) { return !selectedChannel || (selectedChannel === '__none' ? !item.social_account_id : item.social_account_id === selectedChannel); }
  function renderList() {
    renderChannelSummary();
    const query = $('search').value.trim().toLocaleLowerCase('es');
    const filter = $('status-filter').value;
    const base = state.items.filter(item => channelMatch(item) && (!query || [item.title, item.script, item.channel, channelText(item), accountFor(item)?.handle].some(v => String(v || '').toLocaleLowerCase('es').includes(query))));
    const items = base.filter(item => !filter || item.status === filter);
    $('total-count').textContent = String(state.items.length);
    $('list-caption').textContent = `${items.length} de ${state.items.length} vídeos propios`;
    $('status-tabs').replaceChildren();
    for (const option of $('status-filter').options) {
      const count = base.filter(i => !option.value || i.status === option.value).length;
      const button = node('button', 'filter-tab', `${option.text} · ${count}`);
      button.type = 'button'; button.dataset.filter = option.value;
      button.setAttribute('aria-pressed', String(option.value === filter));
      button.addEventListener('click', () => { $('status-filter').value = option.value; renderList(); });
      $('status-tabs').append(button);
    }
    $('short-list').replaceChildren();
    $('empty-detail').hidden = state.items.length > 0;
    if (!items.length && state.items.length) $('short-list').append(node('li', 'empty-row', 'No hay vídeos con estos filtros.'));
    for (const item of items) {
      const li = node('li'); const button = node('button', 'short-item'); button.type = 'button';
      const title = node('span', 'row-title');
      title.append(thumbnail(item, 'thumbnail'), node('strong', '', item.title || 'Sin título'));
      button.append(title, node('span', 'row-channel', channelText(item)), statusBadge(item.status), node('span', 'row-arrow', '›'));
      button.addEventListener('click', () => selectShort(item.id));
      button.addEventListener('focus', () => renderInspector(item));
      button.addEventListener('mouseenter', () => renderInspector(item));
      li.append(button); $('short-list').append(li);
    }
    renderInspector(items[0]);
  }
  function renderInspector(item) {
    const box = $('inspector'); box.replaceChildren(node('p', 'muted', 'Vista del guion'));
    if (!item) { box.append(node('h2', '', 'Espacio para tu próxima historia'), node('p', 'muted', 'Selecciona un vídeo o crea un borrador.')); return; }
    box.append(node('h2', '', item.title), node('p', 'inspector-script', item.script ? item.script.slice(0, 360) + (item.script.length > 360 ? '…' : '') : item.status === 'published' ? 'Guion no disponible' : 'Guion pendiente de escribir.'));
    const placeholder = thumbnail(item, 'neutral-preview');
    const open = node('button', 'button button-primary full-width', 'Abrir vídeo'); open.type = 'button'; open.addEventListener('click', () => selectShort(item.id));
    box.append(placeholder, statusBadge(item.status), open);
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
    const locked = record.status === 'published';
    $('status').replaceChildren(...Object.entries(labels).filter(([key]) => locked ? key === 'published' : key !== 'published').map(([key, text]) => new Option(text, key)));
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
    $('record-updated').textContent = record.updated_at ? `Actualizado el ${dateText(record.updated_at)}` : 'Todavía no guardado';
    $('detail-status').textContent = labels[record.status] || 'Borrador';
    $('detail-status').dataset.status = record.status || 'draft';
    $('empty-detail').hidden = true;
    $('detail').hidden = false;
    $('library-home').classList.remove('active');
    $('library-owned').classList.add('active');
    $('library-home').setAttribute('aria-current', 'false');
    $('library-owned').setAttribute('aria-current', 'page');
    $('owned-library').hidden = true;
    $('references-view').hidden = true;
    readingScript = locked;
    applyLock();
    showSection(activeSection);
    renderPreview();
    renderList();
  }
  async function selectShort(id) {
    if (!$('detail').hidden && state.current && String(state.current.id) === String(id)) return;
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
      discardEdits();
      ++state.metricRequest;
      libraryMode = 'owned';
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
    discardEdits();
    ++state.selectionRequest;
    ++state.metricRequest;
    libraryMode = 'owned';
    fillRecord({title: '', script: '', status: 'draft', language: 'es', format: '9:16', tags: [], social_account_id: selectedChannel && selectedChannel !== '__none' ? selectedChannel : null});
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
    if (!value || /[\s\\\x00-\x1f\x7f]/.test(value)) return null;
    try {
      const url = new URL(value, location.origin);
      if (url.username || url.password) return null;
      const local = /^\/media\/[A-Za-z0-9][A-Za-z0-9_.-]{0,199}\.(?:mp4|webm)$/.test(value) && url.origin === location.origin;
      if (local) return {url: url.href, video: true, local: true};
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
  function thumbnailURL(value) {
    return typeof value === 'string' && value.length <= 4096 && !/[\s\\\x00-\x1f\x7f]/.test(value) && !/^https:\/\/[^/]*@/i.test(value) ? sourceURL(value) : null;
  }
  const failedThumbnails = new Set();
  function thumbnail(item, className) {
    const box = node('div', `${className} owned-thumbnail`);
    const fallback = () => box.replaceChildren(node('span', 'thumbnail-fallback', 'Imagen no disponible'));
    const url = thumbnailURL(item.thumbnail_url);
    if (!url || failedThumbnails.has(url)) { fallback(); return box; }
    const image = node('img');
    image.alt = `Miniatura: ${item.title || 'Vídeo sin título'}`;
    image.loading = 'lazy'; image.referrerPolicy = 'no-referrer';
    image.addEventListener('error', () => { failedThumbnails.add(url); fallback(); }, {once: true});
    image.src = url; box.append(image); return box;
  }
  function tiktokId(value) {
    // Match the original string, before URL normalization can erase bogus paths.
    const match = /^https:\/\/(?:www\.)?tiktok\.com\/@[A-Za-z0-9_.]+\/video\/(\d+)(?:\?[^\s\\#]*)?$/.exec(value);
    return match && !/[\x00-\x1f\x7f]/.test(value) ? match[1] : null;
  }
  function renderPreview() {
    const content = $('preview-content');
    content.replaceChildren();
    const format = $('format').value;
    $('preview-stage').classList.toggle('landscape', format === '16:9');
    $('preview-format').textContent = format;
    let facts = $('preview-facts');
    if (!facts) { facts = node('dl', 'preview-facts'); facts.id = 'preview-facts'; $('preview-stage').parentElement.append(facts); }
    facts.replaceChildren();
    const selected = socials.items.find(a => a.id === $('social_account_id').value);
    for (const [key, value] of [['Idioma', $('language').value === 'en' ? 'Inglés' : 'Español'], ['Formato', format], ['Canal', selected ? `${selected.name} · ${platforms[selected.platform] || selected.platform}` : $('channel').value || 'Sin canal']]) facts.append(node('dt', '', key), node('dd', '', value));
    const youtube = $('youtube_url').value.trim();
    const preview = $('preview_url').value.trim();
    const id = youtubeId(youtube);
    const media = safePreview(preview);
    const tiktok = tiktokId(preview);
    let sourceLinks = $('preview-source-links');
    if (!sourceLinks) { sourceLinks = node('div'); sourceLinks.id = 'preview-source-links'; $('preview-help').after(sourceLinks); }
    sourceLinks.replaceChildren();
    if (media) {
      const link = node('a', 'external-link', 'Si el reproductor no está disponible, abrir original ↗');
      link.href = media.url; link.target = '_blank'; link.rel = 'noopener noreferrer'; sourceLinks.append(link);
    }
    $('youtube-open').hidden = !id;
    $('youtube-open').removeAttribute('href');
    if (id) $('youtube-open').href = `https://www.youtube.com/watch?v=${id}`;
    $('preview-help').textContent = format === '16:9' ? 'Formato horizontal 16:9. Se respeta la proporción del archivo.' : 'Formato vertical 9:16. Se respeta la proporción del archivo.';
    content.append(thumbnail({thumbnail_url: $('thumbnail_url').value, title: $('short-title').value}, 'detail-thumbnail'));
    if (media && media.video && (media.local || (!id && !tiktok))) {
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
    } else if (id || tiktok) {
      const platform = id ? 'YouTube' : 'TikTok';
      previewPlaceholder(`Vista previa de ${platform}`, `Solo se conecta con ${platform} cuando tú lo solicitas.`);
      const load = node('button', 'button button-secondary', 'Cargar vista previa');
      load.type = 'button';
      load.addEventListener('click', () => {
        const frame = node('iframe');
        frame.title = `Vista previa de ${platform}: ${$('short-title').value || 'Vídeo'}`;
        frame.referrerPolicy = 'strict-origin-when-cross-origin';
        frame.allow = 'encrypted-media; picture-in-picture; fullscreen';
        frame.allowFullscreen = true;
        frame.src = id ? `https://www.youtube-nocookie.com/embed/${id}?autoplay=0` : `https://www.tiktok.com/player/v1/${tiktok}?autoplay=0&loop=0`;
        content.replaceChildren(frame);
        const restore = node('button', 'button button-secondary', 'Volver a la portada');
        restore.type = 'button';
        restore.addEventListener('click', renderPreview);
        sourceLinks.append(restore);
        $('preview-help').textContent = `Reproductor de ${platform} solicitado. Si no está disponible, abre el original con el enlace inferior.`;
      });
      content.append(load);
    } else if (media) {
      previewPlaceholder('Vista previa externa', 'Este enlace se abre aparte; no se incrusta en el estudio.');
    } else {
      previewPlaceholder('Vista previa pendiente', 'Añade el vídeo del creador o un enlace de YouTube en los detalles.');
    }

    if ((youtube && !id) || (preview && !media)) $('preview-help').textContent = 'Hay un enlace no válido. Revisa los detalles; no se cargará contenido desde ese enlace.';
  }
  function validateLinks() {
    const youtube = $('youtube_url');
    const preview = $('preview_url');
    const cover = $('thumbnail_url');
    cover.setCustomValidity(cover.value && !thumbnailURL(cover.value) ? 'Usa una URL HTTPS de imagen, sin credenciales y de hasta 4096 caracteres.' : '');
    youtube.setCustomValidity(youtube.value.trim() && !youtubeId(youtube.value.trim()) ? 'Introduce un enlace válido a un vídeo de YouTube.' : '');
    preview.setCustomValidity(preview.value.trim() && !safePreview(preview.value.trim()) ? 'Usa un enlace HTTPS o una ruta local /media/.' : '');
  }
  async function saveShort(event, publish = false) {
    event.preventDefault();
    if (state.busy || !state.current) return;
    validateLinks();
    if (!editor.checkValidity()) { showSection($('short-title').validity.valid ? 'summary' : 'editor'); editor.reportValidity(); return; }
    const body = readEditor();
    if (!body.title) { $('short-title').setCustomValidity('Escribe un título de trabajo.'); showSection('editor'); $('short-title').reportValidity(); return; }
    const creating = state.current.id == null;
    if (creating) body.status = 'draft';
    else if (publish) body.status = 'published';
    if (state.current.status === 'published') { delete body.script; delete body.status; }
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
    } catch (error) {
      if (error.status === 409) {
        recovery = true;
        $('recovery-script').value = body.script ?? $('script').value;
        $('recovery-data').value = JSON.stringify(body, null, 2);
        $('recovery-panel').hidden = false;
        try { const fresh = await api(`/v1/shorts/${encodeURIComponent(state.current.id)}`); fillRecord(fresh); const index = state.items.findIndex(i => i.id === fresh.id); if (index >= 0) state.items[index] = fresh; renderList(); } catch (_) { /* Keep the recovery copy even if reloading fails. */ }
        message('global-message', 'Conflicto: el vídeo ha cambiado o ya está publicado. No se guardaron tus cambios. Tu texto está conservado en «Copia recuperable»; revisa el estado actualizado.', 'error');
      } else message('global-message', error.message, 'error');
    }
    finally { setBusy(false); }
  }
  function applyLock() {
    const locked = state.current?.status === 'published';
    $('script').readOnly = locked;
    $('status').disabled = state.busy || locked || state.current?.id == null;
    $('script-lock').hidden = !locked;
    $('edit-script').hidden = locked || !readingScript;
    $('script-read-tab').hidden = locked || readingScript;
    $('script').hidden = locked || readingScript;
    $('script-reading').hidden = !locked && !readingScript;
    $('script-reading').textContent = $('script').value || (locked ? 'Guion no disponible' : 'Guion pendiente de escribir.');
    $('save-short').hidden = locked && activeSection !== 'summary';
    $('save-short').textContent = state.busy ? 'Guardando…' : locked ? 'Guardar metadatos' : 'Guardar cambios';
    $('publish-short').hidden = locked || state.current?.id == null;
    $('publication-state').textContent = locked ? 'Publicación registrada. Guion bloqueado permanentemente.' : state.current?.id == null ? 'Guarda primero el borrador.' : '';
  }
  function showSection(section) {
    if (section === 'script-read') { readingScript = true; section = 'editor'; }
    activeSection = section;
    for (const name of ['summary', 'editor', 'publication', 'metrics']) {
      $(`${name}-panel`).hidden = name !== section;
      $(`${name}-tab`).classList.toggle('active', name === section);
      $(`${name}-tab`).setAttribute('aria-pressed', String(name === section));
    }
    // The title is also editable from metadata without duplicating its value.
    (section === 'summary' ? $('summary-panel') : $('editor-panel')).prepend($('draft-title-field'));
    $('draft-title-field').hidden = state.current?.status === 'published' && section !== 'summary';
    applyLock();
    if (section === 'metrics') loadMetrics();
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
      const written = await api(`/v1/shorts/${encodeURIComponent(state.current.id)}/metrics`, {method: 'POST', body});
      const verified = await api(`/v1/shorts/${encodeURIComponent(state.current.id)}/metrics`);
      if (!Array.isArray(verified.items) || !verified.items.some(item => item.id === written.id && metricFields.every(name => item[name] === body[name]))) throw new Error('La captura se envió, pero no se pudo comprobar. Actualiza el historial antes de volver a enviarla para evitar duplicados.');
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
  const publicStatuses = {ok: 'Consulta pública disponible', partial: 'Consulta pública parcial', blocked: 'Consulta pública bloqueada', missing_url: 'Falta enlace exacto', not_found: 'Perfil no encontrado', identity_mismatch: 'Identidad no coincidente'};
  const publicMetricLabels = {followers: 'Seguidores', subscribers: 'Suscriptores', following: 'Siguiendo', posts: 'Publicaciones', likes: 'Me gusta', views: 'Visualizaciones'};
  function trustedPublic(data) { return ['ok', 'partial'].includes(data?.status); }
  function publicMetricText(metric) {
    if (!metric) return '—';
    const text = typeof metric.display === 'string' && metric.display.trim() ? metric.display : typeof metric.value === 'number' && Number.isFinite(metric.value) ? numberFormat.format(metric.value) : '—';
    return text === '—' ? text : `${metric.approximate ? '≈ ' : ''}${text}`;
  }
  function sourceURL(value) {
    if (typeof value !== 'string' || /[\s\\\x00-\x1f]/.test(value)) return null;
    try { const url = new URL(value); return url.protocol === 'https:' && !url.username && !url.password ? url.href : null; } catch (_) { return null; }
  }
  function publicLink(value, text) {
    const url = sourceURL(value);
    if (!url) return null;
    const link = node('a', '', text); link.href = url; link.target = '_blank'; link.rel = 'noopener noreferrer'; return link;
  }
  function renderChannelSummary() {
    const box = $('channel-summary'); box.replaceChildren();
    box.hidden = !socials.loaded || refs.mode || selectedChannel === '__none';
    if (box.hidden) return;
    if (!selectedChannel) {
      const available = socials.items.filter(a => trustedPublic(a.public_data)).length;
      box.append(node('p', 'small', `Datos públicos: ${available} de ${socials.items.length} canales con información · Sin conexión a plataformas`));
      const pending = socials.items.filter(a => a.public_data?.status !== 'ok');
      if (pending.length) {
        const details = node('details', 'small'); details.append(node('summary', '', `${pending.length} canales con consulta pendiente o incompleta`));
        const list = node('ul');
        for (const a of pending) list.append(node('li', '', `${a.name} · ${platforms[a.platform] || a.platform} · ${publicStatuses[a.public_data?.status] || 'No consultado'}`));
        details.append(list); box.append(details);
      }
      return;
    }
    const account = socials.items.find(a => a.id === selectedChannel);
    if (!account) { box.append(node('p', 'small', 'Canal no disponible en el inventario')); return; }
    const data = account.public_data, trusted = trustedPublic(data);
    const heading = node('div', 'channel-summary-heading');
    heading.append(node('strong', '', account.name || (trusted && data.profile?.display_name) || 'Canal'), node('span', 'small', platforms[account.platform] || account.platform));
    const profile = profileURL(account) || (trusted && profileURL({...account, profile_url: data.canonical_url}));
    const link = publicLink(profile, 'Abrir perfil ↗'); if (link) heading.append(link);
    box.append(heading, node('p', 'small', `${publicStatuses[data?.status] || 'No consultado'} · Sin conexión a plataformas`));
    if (trusted && data.profile?.description) box.append(node('p', 'channel-bio', data.profile.description));
    if (trusted) {
      const metrics = node('dl', 'channel-metrics');
      const keys = new Set([account.platform === 'youtube' ? 'subscribers' : 'followers', 'posts', ...Object.keys(data.metrics || {}).filter(key => publicMetricLabels[key])]);
      for (const key of keys) {
        const metric = data.metrics?.[key];
        const cell = node('div'); cell.dataset.publicMetric = key;
        cell.append(node('dt', '', publicMetricLabels[key]), node('dd', '', publicMetricText(metric)));
        if (metric) {
          const provenance = node('small', '', `Observado: ${dateText(metric.observed_at)}`);
          const source = publicLink(metric.source_url, 'Fuente ↗'); if (source) provenance.append(' · ', source);
          cell.append(provenance);
        }
        metrics.append(cell);
      }
      box.append(metrics);
    }
    if (data) {
      const provenance = node('p', 'small', `Intento de consulta: ${dateText(data.attempted_at)} · Método: ${data.source_method || 'No disponible'}`);
      const source = publicLink(data.source_url, 'Fuente de consulta ↗'); if (source) provenance.append(' · ', source);
      box.append(provenance);
      if (trusted && Number.isInteger(data.publications_collected) && data.publications_collected >= 0) box.append(node('p', 'small', `${data.publications_collected} enlaces recopilados · No es el total de publicaciones del canal · Catálogo: ${data.catalog_status || 'No disponible'}`));
      if (Array.isArray(data.notes) && data.notes.length) {
        const notes = node('details', 'small'); notes.append(node('summary', '', 'Notas de la consulta'));
        const list = node('ul'); for (const note of data.notes) list.append(node('li', '', note)); notes.append(list); box.append(notes);
      }
    }
    if (account.analytics?.subscribers != null) box.append(node('p', 'small channel-screenshot', `${metricValue(account.analytics.subscribers)} suscriptores · Observación de captura, NO en directo · ${account.analytics.observed_at ? dateText(account.analytics.observed_at) : 'Fecha de captura desconocida'}${account.analytics.note ? ' · ' + account.analytics.note : ''}`));
  }
  function toggleChannels(open) {
    $('channel-menu').hidden = !open; $('channel-toggle').setAttribute('aria-expanded', String(open));
    if (open) { renderSocials(); $('social-search').focus(); }
  }
  function renderSocials() {
    const query = $('social-search').value.trim().toLocaleLowerCase('es');
    const filtered = socials.items.filter(a => [a.name, a.handle, a.platform, platforms[a.platform]].some(v => String(v || '').toLocaleLowerCase('es').includes(query)));
    const box = $('channel-options'); box.replaceChildren();
    const options = [{id: '', name: 'Todos los canales'}, {id: '__none', name: 'Sin canal'}, ...filtered];
    for (const a of options) {
      const row = node('div', 'channel-option'); const button = node('button', 'channel-choice'); button.type = 'button';
      button.dataset.channel = a.id; button.setAttribute('aria-pressed', String(selectedChannel === a.id));
      button.append(node('span', 'monogram', a.platform ? a.name.slice(0, 2).toUpperCase() : '▦'));
      const label = node('span', 'channel-label', a.name);
      if (a.platform) label.append(node('small', '', `${platforms[a.platform] || a.platform}${a.handle ? ' · ' + a.handle : ' · Handle pendiente'}`));
      button.append(label, node('span', 'channel-count', String(state.items.filter(i => a.id === '' || (a.id === '__none' ? !i.social_account_id : i.social_account_id === a.id)).length)));
      button.addEventListener('click', () => {
        if (selectedChannel !== a.id && !mayLeave()) return;
        if (selectedChannel !== a.id) { discardEdits(); selectedChannel = a.id; switchLibrary('owned', false); }
        $('channel-toggle').textContent = `${a.name}${a.platform ? ' · ' + platforms[a.platform] : ''} ⌄`;
        toggleChannels(false); $('channel-toggle').focus(); renderList();
      });
      row.append(button);
      const url = a.platform && profileURL(a);
      if (url) { const link = node('a', 'profile-link', '↗'); link.href = url; link.target = '_blank'; link.rel = 'noopener noreferrer'; link.setAttribute('aria-label', `Abrir perfil de ${a.name} en ${platforms[a.platform]}`); row.append(link); }
      const publicMetrics = trustedPublic(a.public_data) ? Object.entries(a.public_data.metrics || {}).filter(([key, metric]) => publicMetricLabels[key] && publicMetricText(metric) !== '—') : [];
      if (publicMetrics.length) row.title = publicMetrics.map(([key, metric]) => `${publicMetricText(metric)} ${publicMetricLabels[key]} · ${a.public_data.source_method || 'Consulta pública'} · ${dateText(metric.observed_at)}${sourceURL(metric.source_url) ? ' · ' + sourceURL(metric.source_url) : ''}`).join('\n');
      else if (a.analytics?.subscribers != null) row.title = `${numberFormat.format(a.analytics.subscribers)} suscriptores · Observación de captura, NO en directo · ${a.analytics.observed_at ? dateText(a.analytics.observed_at) : 'Fecha de captura desconocida'}`;
      box.append(row);
    }
    $('social-caption').textContent = `${filtered.length} de ${socials.items.length} canales · Inventario, sin conexión a plataformas`;
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
      renderSocials(); renderList(); message('social-message');
      $('social-selector-help').textContent = 'Vinculación editorial, no conexión a la plataforma. No cambia el canal ni agrupa marcas. Los nuevos registros se guardan siempre como borrador.';
    } catch (error) {
      message('social-message', error.message, 'error');
      $('social-selector-help').textContent = 'No se pudo cargar el inventario. Puedes editar el guion; usa Actualizar inventario para reintentar.';
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
  function discardEdits() {
    if (state.current && state.baseline && state.dirty) {
      const baseline = JSON.parse(state.baseline);
      for (const name of fields) editor.elements.namedItem(name).value = name === 'tags' ? baseline[name].join(', ') : baseline[name] ?? '';
    }
    state.dirty = false; resetMetricForm(); recovery = false; $('recovery-panel').hidden = true;
  }
  function switchLibrary(mode, guard = true) {
    if (state.busy || (guard && !mayLeave())) return;
    if (guard) discardEdits();
    libraryMode = mode; refs.mode = mode === 'references'; ++state.selectionRequest;
    $('owned-library').hidden = refs.mode; $('references-view').hidden = !refs.mode;
    $('reference-library').hidden = !refs.mode; $('reference-workspace').hidden = !refs.mode;
    $('detail').hidden = true;
    $('library-heading').textContent = mode === 'home' ? 'Tu mesa de trabajo' : 'Tus vídeos';
    for (const name of ['home', 'owned']) { $('library-' + name).classList.toggle('active', name === mode || name === 'owned' && refs.mode); $('library-' + name).setAttribute('aria-current', name === mode ? 'page' : 'false'); }
    history.replaceState(null, '', refs.mode ? '/references' : mode === 'home' ? '/' : '/videos');
    $('preview-content').replaceChildren(); $('reference-preview').replaceChildren();
    if (refs.mode) { if (!refs.loaded) loadReferences(); else if (refs.current) selectReference(refs.current); }
    renderList();
  }
  $('library-home').addEventListener('click', () => switchLibrary('home'));
  $('library-owned').addEventListener('click', () => switchLibrary('owned'));
  $('back-videos').addEventListener('click', () => switchLibrary('owned'));
  $('library-references').addEventListener('click', () => switchLibrary('references'));
  $('channel-toggle').addEventListener('click', () => toggleChannels($('channel-menu').hidden));
  $('social-search').addEventListener('input', renderSocials);
  $('refresh-social').addEventListener('click', loadSocials);
  document.addEventListener('click', event => { if (!event.target.closest('.channel-control')) toggleChannels(false); });
  $('channel-menu').addEventListener('keydown', event => {
    if (event.key === 'Escape') { toggleChannels(false); $('channel-toggle').focus(); }
    if (['ArrowDown', 'ArrowUp'].includes(event.key)) {
      const controls = [$('social-search'), ...$('channel-options').querySelectorAll('button')];
      const index = controls.indexOf(document.activeElement);
      controls[(index + (event.key === 'ArrowDown' ? 1 : controls.length - 1)) % controls.length].focus(); event.preventDefault();
    }
  });
  $('dismiss-recovery').addEventListener('click', () => { if (confirm('¿Descartar la copia recuperable sin guardar?')) { recovery = false; $('recovery-panel').hidden = true; } });
  $('summary-tab').addEventListener('click', () => showSection('summary'));
  $('publication-tab').addEventListener('click', () => showSection('publication'));
  $('edit-script').addEventListener('click', () => { readingScript = false; applyLock(); $('script').focus(); });
  $('publish-short').addEventListener('click', () => {
    if (state.busy || !state.current?.id || state.current.status === 'published') return;
    if (!confirm('Solo se registrará el estado: NO se publica en ninguna plataforma. El guion quedará bloqueado de forma irreversible. Se guardarán también los cambios actuales. ¿Registrar como publicado?')) return;
    saveShort({preventDefault() {}}, true);
  });
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
      $('channel-options').replaceChildren(); selectedChannel = ''; recovery = false;
      $('channel-toggle').textContent = 'Todos los canales ⌄';
      $('social-search').value = '';
      toggleChannels(false);
      $('social_account_id').replaceChildren(new Option('Sin cuenta asociada', ''));
      $('reference-detail').hidden = true; $('reference-empty').hidden = false;
      renderReferences(); switchLibrary('home', false);
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
  editor.addEventListener('submit', saveShort);
  editor.addEventListener('input', (event) => {
    if (event.target.id === 'short-title') { event.target.setCustomValidity(''); $('detail-title').textContent = event.target.value || 'Nuevo vídeo'; }
    if (['youtube_url', 'preview_url', 'thumbnail_url'].includes(event.target.id)) event.target.setCustomValidity('');
    updateDirty();
  });
  for (const id of ['youtube_url', 'preview_url', 'thumbnail_url', 'format', 'social_account_id', 'language', 'channel']) $(id).addEventListener('change', () => { validateLinks(); renderPreview(); });
  $('metric-form').addEventListener('input', () => { state.metricDirty = true; });
  $('metric-form').addEventListener('submit', saveMetric);
  window.addEventListener('beforeunload', (event) => {
    if (hasEdits() || state.busy) { event.preventDefault(); event.returnValue = ''; }
  });
  document.addEventListener('keydown', (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's' && state.authenticated && state.current && !$('detail').hidden) {
      event.preventDefault();
      if (!state.busy && (state.current.status !== 'published' || activeSection === 'summary')) editor.requestSubmit();
    }
  });
  document.querySelector('.brand').addEventListener('click', event => { event.preventDefault(); switchLibrary('home'); });
  api('/auth/me').then(startSession).catch((error) => {
    showLogin();
    if (error.status !== 401) message('login-message', error.message, 'error');
  });
})();

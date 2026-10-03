'use strict';

const PALETTE = ['#fb7299', '#5b9dff', '#3ecf8e', '#f2c14e', '#b28dff', '#66d9e8', '#ff9f68', '#a0e57c'];
const MAX_STREAM_LINES = 400;

const state = {
  sort: 'active',
  keyword: '',
  sessionOnly: false,
  viewers: new Map(),
  selectedUid: null,
  streamPaused: false,
  pendingLines: [],
  detail: null,
  profileTab: 'overview',   // 右侧画像面板当前分类
  behaviorFilter: 'all',    // 「行为」分类下的事件筛选
  behaviorPage: 1,          // 「行为」分类当前页码
  msgPage: 1,               // 「发言」分类当前页码
  msgKeyword: '',           // 「发言」关键词搜索
  msgSessionOnly: false,    // 「发言」只看本场
  msgOrder: 'desc',         // 「发言」时间排序：desc 倒序 | asc 正序
  // 分页 / 时间轴
  viewerPage: 1,
  viewerTotal: 0,
  viewerPageSize: 50,
  streamMode: 'live',       // 'live' 实时 | 'history' 回看
  timeline: [],             // /api/timeline 的按天分组结果
  historyDay: '',
  historyHour: '',
  historyPage: 1,
  historyTotal: 0,
  historyLimit: 200,
  streamView: 'all',         // 'all' 全部弹幕 | 'gift' 只看礼物流水
  roles: {},                // 观众身份标记：uid -> role（AI助手 / 房管 …）
  currentRoom: 0,           // 当前直播间房间号（切换房间列表用）
  // 图表
  densityMetric: 'danmaku',  // 顶部密度曲线当前指标
  densityChart: null,
  densityTimer: null,
  userHourChart: null,       // 概览页：活跃时段分布
  userTrendChart: null,      // 概览页：时间趋势
  // 热门元素库
  topicRe: null,             // 弹幕高亮用：所有别名合成的正则
  topicMap: null,            // 别名（小写）-> 词条
  // 操作记录（唱歌 / PK / 杂谈 …）
  actions: [],               // 轻量记录，时间轴色带用；随 SSE 刷新
  actionKinds: [],           // 可选操作类型（来自 data/actions.json）
  actionSummary: [],         // 按类型汇总，对比表用
  actionBaseline: null,      // 本场全程基线，对比表的参照行
  pendingKind: null,         // 正在记录的操作类型
  analysisKind: 'session',   // AI 分析面板当前标签：'session' 本场 | 'career' 生涯
};

const BEHAVIOR_PAGE_SIZE = 100;
const MESSAGE_PAGE_SIZE = 100;

const $ = (id) => document.getElementById(id);

function colorOf(uid) {
  let hash = 0;
  const key = String(uid);
  for (let i = 0; i < key.length; i++) hash = (hash * 31 + key.charCodeAt(i)) >>> 0;
  return PALETTE[hash % PALETTE.length];
}

function initial(name) {
  return (name || '?').trim().charAt(0).toUpperCase() || '?';
}

function fmtTime(ts) {
  const d = new Date(ts);
  const p = (n) => String(n).padStart(2, '0');
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

function fmtDelta(ts) {
  const sec = Math.max(0, (Date.now() - ts) / 1000);
  if (sec < 60) return '刚刚';
  if (sec < 3600) return `${Math.floor(sec / 60)} 分钟前`;
  if (sec < 86400) return `${(sec / 3600).toFixed(1)} 小时前`;
  return `${Math.floor(sec / 86400)} 天前`;
}

function esc(text) {
  const div = document.createElement('div');
  div.textContent = text == null ? '' : String(text);
  return div.innerHTML;
}

async function api(url, options) {
  const resp = await fetch(url, options);
  if (!resp.ok) throw new Error(`${resp.status} ${await resp.text()}`);
  return resp.json();
}

/* ------------------------------------------------------------------ 顶栏 */
function renderStats(data) {
  const items = [
    [data.session_viewers ?? 0, '本场观众'],
    [data.session_danmaku ?? 0, '本场弹幕'],
    [data.session_guards ?? 0, '本场上舰'],
    ['¥' + (data.session_income ?? 0), '本场流水'],
    [data.popularity ?? 0, '人气值'],
    [data.total_viewers ?? 0, '累计观众'],
  ];
  $('stats').innerHTML = items
    .map(([v, l]) => `<div class="stat"><b>${esc(v)}</b><span>${l}</span></div>`)
    .join('');
  state.currentRoom = data.room_id || 0;
  $('room-line').textContent = `直播间 ${data.room_id || '--'} · 累计观众库 ${data.total_viewers ?? 0} 人`;
  // 顶栏常驻「自动画像」开关：状态由后端下发，保证刷新后仍然一致
  if (typeof data.auto === 'boolean') syncAutoProfile(data.auto);
}

function syncAutoProfile(enabled) {
  const box = $('auto-profile');
  const wrap = $('auto-profile-wrap');
  if (!box) return;
  box.checked = !!enabled;
  wrap.classList.toggle('on', !!enabled);
  wrap.title = enabled
    ? '自动画像已开启：观众达到阈值后才会生成'
    : '自动画像已关闭：不会自动生成任何画像';
}

async function toggleAutoProfile() {
  const box = $('auto-profile');
  const wrap = $('auto-profile-wrap');
  const next = box.checked;
  box.disabled = true;
  wrap.classList.add('busy');
  try {
    await api('/api/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ auto: next }),
    });
    syncAutoProfile(next);
  } catch (err) {
    box.checked = !next; // 保存失败时回滚开关
    wrap.classList.remove('busy');
    box.disabled = false;
    alert('切换失败：' + err.message);
    return;
  }
  wrap.classList.remove('busy');
  box.disabled = false;
}

function setConn(connected, message) {
  const pill = $('conn-pill');
  pill.classList.toggle('on', !!connected);
  $('conn-text').textContent = message || (connected ? '已连接' : '未连接');
}

/* ------------------------------------------------------------------ 观众列表 */
function badgeHtml(viewer) {
  const out = [];
  if (viewer.role) out.push(`<span class="badge role">${esc(viewer.role)}</span>`);
  if (viewer.guard_level) {
    out.push(`<span class="badge guard">${['', '总督', '提督', '舰长'][viewer.guard_level] || '舰队'}</span>`);
  }
  if (viewer.medal_level) out.push(`<span class="badge medal">牌${viewer.medal_level}</span>`);
  if (viewer.gift_value > 0) out.push(`<span class="badge paid">¥${viewer.gift_value}</span>`);
  if (viewer.profile_status === 'pending' || viewer.profile_status === 'running') {
    out.push('<span class="badge pending">分析中</span>');
  } else if (viewer.profile_status === 'error') {
    out.push('<span class="badge error">失败</span>');
  } else if (viewer.profile_status === 'done') {
    out.push('<span class="badge">已画像</span>');
  }
  return out.join('');
}

/* 弹幕流里跟在名字后面的身份标记 */
function roleBadge(uid) {
  const role = state.roles[String(uid)];
  return role ? `<i class="role-tag">${esc(role)}</i>` : '';
}

async function loadRoles() {
  try {
    state.roles = (await api('/api/roles')) || {};
  } catch {
    state.roles = {};
  }
}

function renderViewers(items) {
  state.viewers = new Map(items.map((v) => [v.uid, v]));
  $('viewer-count').textContent = `(${state.viewerTotal || items.length})`;
  const list = $('viewer-list');
  if (!items.length) {
    list.innerHTML = `<div class="empty-state" style="padding:28px"><p>暂无观众数据<br>等待直播间有人互动</p></div>`;
    return;
  }
  list.innerHTML = items
    .map(
      (v) => `
      <div class="viewer ${v.uid === state.selectedUid ? 'active' : ''}" data-uid="${v.uid}">
        <div class="avatar" style="color:${colorOf(v.uid)}">${esc(initial(v.uname))}</div>
        <div class="v-main">
          <div class="v-name">${esc(v.uname || '未知用户')}</div>
          <div class="v-meta">${v.msg_count} 条弹幕 · 进场 ${v.enter_count} · ${fmtDelta(v.last_seen)}</div>
        </div>
        <div class="v-right">
          <div class="v-count">${v.msg_count}</div>
          <div class="v-badges">${badgeHtml(v)}</div>
        </div>
      </div>`
    )
    .join('');
}

async function loadViewers() {
  const params = new URLSearchParams({
    sort: state.sort,
    limit: String(state.viewerPageSize),
    offset: String((state.viewerPage - 1) * state.viewerPageSize),
    session_only: state.sessionOnly ? '1' : '0',
  });
  if (state.keyword) params.set('keyword', state.keyword);
  try {
    const data = await api('/api/viewers?' + params.toString());
    state.viewerTotal = data.total || 0;
    renderViewers(data.items || []);
    renderPager($('viewer-pager'), state.viewerPage, state.viewerTotal, state.viewerPageSize, (p) => {
      state.viewerPage = p;
      loadViewers();
    });
  } catch (err) {
    console.error('加载观众失败', err);
  }
}

function patchViewer(light) {
  if (!light) return;
  const existing = state.viewers.get(light.uid) || {};
  state.viewers.set(light.uid, { ...existing, ...light });

  const node = $('viewer-list').querySelector(`.viewer[data-uid="${light.uid}"]`);
  if (!node) return;
  node.querySelector('.v-main .v-meta').textContent =
    `${light.msg_count} 条弹幕 · 进场 ${light.enter_count} · ${fmtDelta(light.last_seen)}`;
  node.querySelector('.v-count').textContent = light.msg_count;
  node.querySelector('.v-badges').innerHTML = badgeHtml({ ...existing, ...light });
}

/* ------------------------------------------------------------------ 热门元素库 */
/* 纯英文别名加词边界，避免 sc 命中 discord、lol 命中 lollipop。
   中文别名不能加 \b —— JS 的 \b 只认 ASCII，加在中文上反而匹配不到。 */
function aliasPattern(alias) {
  const escaped = alias.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  return /^[A-Za-z0-9_]+$/.test(alias)
    ? `(?<![A-Za-z0-9])${escaped}(?![A-Za-z0-9])`
    : escaped;
}

/* 拉取词库并编译成一条正则：弹幕渲染时一次匹配所有别名（长词优先） */
async function loadTopics() {
  try {
    const data = await api('/api/topics');
    const pairs = [];
    (data.topics || []).forEach((t) => {
      const aliases = t.aliases && t.aliases.length ? t.aliases : [t.name];
      aliases.forEach((a) => { if (a) pairs.push({ alias: a, topic: t }); });
    });
    pairs.sort((a, b) => b.alias.length - a.alias.length);
    // 同一别名被多个词条占用时先出现者胜出（与后端一致），避免重复分支
    const seen = new Set();
    const uniq = pairs.filter((p) => {
      const low = p.alias.toLowerCase();
      if (seen.has(low)) return false;
      seen.add(low);
      return true;
    });
    state.topicMap = new Map(uniq.map((p) => [p.alias.toLowerCase(), p.topic]));
    state.topicRe = uniq.length
      ? new RegExp(uniq.map((p) => aliasPattern(p.alias)).join('|'), 'gi')
      : null;
  } catch (err) {
    console.warn('热门元素库加载失败', err);
  }
}

/* 把弹幕里命中的元素高亮出来，并在词后直接标注所属分类 */
function markTopics(content) {
  const safe = esc(content);
  if (!state.topicRe) return safe;
  return safe.replace(state.topicRe, (match) => {
    const topic = state.topicMap.get(match.toLowerCase());
    if (!topic) return match;
    return `<span class="topic" style="color:${topic.color}">${match}<i class="topic-tag" style="background:${topic.color}">${esc(topic.category_label)}</i></span>`;
  });
}

/* ------------------------------------------------------------------ 弹幕流 */
const SYSTEM_TYPES = new Set(['enter', 'follow', 'special_follow', 'mutual_follow', 'share', 'like']);

function lineHtml(event) {
  const time = fmtTime(event.ts);
  const color = colorOf(event.uid);
  const name = esc(event.uname || event.uid);
  if (event.type === 'danmaku') {
    return `<div class="line"><span class="time">${time}</span>
      <span class="name" style="color:${color}" data-uid="${event.uid}">${name}</span>${roleBadge(event.uid)}
      <span class="msg">${markTopics(event.content)}</span></div>`;
  }
  if (SYSTEM_TYPES.has(event.type)) {
    return `<div class="line system"><span class="time">${time}</span>
      <span class="msg">${name}${roleBadge(event.uid)} ${esc(event.content)}</span></div>`;
  }
  return `<div class="line ${event.type}"><span class="time">${time}</span>
    <span class="name" style="color:${color}" data-uid="${event.uid}">${name}</span>${roleBadge(event.uid)}
    <span class="msg">${esc(event.content)}</span></div>`;
}

function makeLineNode(event) {
  const template = document.createElement('div');
  template.innerHTML = lineHtml(event);
  const node = template.firstElementChild;
  // 记下类型与金额，供「礼物流水」视图过滤与汇总
  node.dataset.type = event.type;
  if (GIFT_TYPES.has(event.type)) {
    node.dataset.value = String((event.extra || {}).value || 0);
  }
  return node;
}

/* 弹幕流视图：全部 / 只看礼物流水。用 CSS 隐藏非礼物行，
   实时流与时间轴回看共用同一套渲染，所以两种模式都能生效。 */
function applyStreamView() {
  $('stream').classList.toggle('view-gift', state.streamView === 'gift');
  $('stream-view-tabs')
    .querySelectorAll('.tab')
    .forEach((node) => node.classList.toggle('active', node.dataset.view === state.streamView));
  refreshStreamHint();
}

function refreshStreamHint() {
  const hint = $('stream-hint');
  if (!hint) return;
  if (state.streamPaused) {
    hint.textContent = `已暂停 · 缓存 ${state.pendingLines.length} 条`;
    return;
  }
  if (state.streamView !== 'gift') {
    hint.textContent = '';
    return;
  }
  const rows = $('stream').querySelectorAll('.line.gift, .line.guard, .line.superchat');
  let total = 0;
  rows.forEach((node) => { total += Number(node.dataset.value || 0); });
  hint.textContent = `礼物流水 · ${rows.length} 笔 · ¥${Math.round(total * 100) / 100}`;
}

function appendStream(event) {
  // 回看历史时不再追加实时消息，避免新旧数据混在一起
  if (state.streamMode !== 'live') return;
  if (state.streamPaused) {
    state.pendingLines.push(event);
    if (state.pendingLines.length > MAX_STREAM_LINES) state.pendingLines.shift();
    refreshStreamHint();
    return;
  }
  pushLine(event);
}

function pushLine(event) {
  const stream = $('stream');
  const nearBottom = stream.scrollTop + stream.clientHeight >= stream.scrollHeight - 60;
  stream.appendChild(makeLineNode(event));
  while (stream.childElementCount > MAX_STREAM_LINES) stream.removeChild(stream.firstElementChild);
  if (nearBottom) stream.scrollTop = stream.scrollHeight;
  if (state.streamView === 'gift' && GIFT_TYPES.has(event.type)) refreshStreamHint();
}

function flushStream() {
  const buffer = state.pendingLines;
  state.pendingLines = [];
  const stream = $('stream');
  buffer.forEach((event) => {
    stream.appendChild(makeLineNode(event));
    while (stream.childElementCount > MAX_STREAM_LINES) stream.removeChild(stream.firstElementChild);
  });
  stream.scrollTop = stream.scrollHeight;
  refreshStreamHint();
}

/* ------------------------------------------------------------------ 通用分页 */
/* 页码分页控件：total 不超过一页时自动隐藏 */
function renderPager(container, page, total, pageSize, onGo) {
  if (!container) return;
  const pages = Math.max(1, Math.ceil(total / pageSize));
  if (total <= pageSize) {
    container.hidden = true;
    container.innerHTML = '';
    return;
  }
  container.hidden = false;
  container.innerHTML = `
    <button data-go="first" ${page <= 1 ? 'disabled' : ''}>«</button>
    <button data-go="prev" ${page <= 1 ? 'disabled' : ''}>上一页</button>
    <span class="pager-info">第 ${page} / ${pages} 页 · 共 ${total} 条</span>
    <button data-go="next" ${page >= pages ? 'disabled' : ''}>下一页</button>
    <button data-go="last" ${page >= pages ? 'disabled' : ''}>»</button>`;
  container.querySelectorAll('button[data-go]').forEach((btn) => {
    btn.onclick = () => {
      const go = btn.dataset.go;
      const target =
        go === 'first' ? 1
        : go === 'prev' ? page - 1
        : go === 'next' ? page + 1
        : pages;
      const clamped = Math.min(Math.max(target, 1), pages);
      if (clamped !== page) onGo(clamped);
    };
  });
}

/* ------------------------------------------------------------------ 弹幕时间轴回看 */
async function loadTimeline() {
  try {
    const data = await api('/api/timeline');
    state.timeline = data.days || [];
  } catch (err) {
    state.timeline = [];
    console.error('加载时间轴失败', err);
  }
  renderTimelineSelects();
}

function renderTimelineSelects() {
  const daySel = $('tl-day');
  const days = state.timeline;
  const liveOpt = '<option value="">实时</option>';
  if (!days.length) {
    daySel.innerHTML = liveOpt;
    daySel.disabled = true;
    $('tl-hour').innerHTML = '';
    $('tl-hour').disabled = true;
    return;
  }
  daySel.disabled = false;
  // 默认停在「实时」：不要预选第一段，否则下拉显示已选中、实际却是实时流，
  // 用户再点同一项时值没变、change 不触发，就切不过去。
  daySel.innerHTML =
    liveOpt +
    days
      .map((d) => `<option value="${d.day}" ${d.day === state.historyDay ? 'selected' : ''}>${d.day}（${d.events} 条）</option>`)
      .join('');
  renderHourSelect();
}

function renderHourSelect() {
  const hourSel = $('tl-hour');
  if (!state.historyDay) {
    hourSel.innerHTML = '<option value="">实时</option>';
    hourSel.disabled = true;
    return;
  }
  const bucket = state.timeline.find((d) => d.day === state.historyDay);
  const hours = bucket ? bucket.hours.slice().sort((a, b) => a.hour.localeCompare(b.hour)) : [];
  if (!hours.length) {
    hourSel.innerHTML = '<option value="">暂无记录</option>';
    hourSel.disabled = true;
    return;
  }
  hourSel.disabled = false;
  if (!hours.some((h) => h.hour === state.historyHour)) state.historyHour = hours[0].hour;
  hourSel.innerHTML = hours
    .map((h) => `<option value="${h.hour}" ${h.hour === state.historyHour ? 'selected' : ''}>${h.hour}:00（${h.events} 条）</option>`)
    .join('');
}

/* 把事件批量渲染进弹幕流（DocumentFragment 一次性插入，避免逐条 reflow） */
function renderStreamLines(items) {
  const stream = $('stream');
  stream.innerHTML = '';
  const fragment = document.createDocumentFragment();
  items.forEach((event) => fragment.appendChild(makeLineNode(event)));
  stream.appendChild(fragment);
  stream.scrollTop = stream.scrollHeight;
}

function setStreamMode(mode) {
  state.streamMode = mode;
  const pill = $('stream-mode');
  pill.textContent = mode === 'live' ? '实时' : '回看中';
  pill.classList.toggle('history', mode !== 'live');
  $('btn-back-live').hidden = mode === 'live';
  if (mode === 'live') {
    $('tl-count').textContent = '';
    $('stream-pager').hidden = true;
  }
  if (state.densityChart) loadDensity();
}

async function enterHistory(day, hour, page = 1) {
  state.historyDay = day;
  state.historyHour = hour;
  state.historyPage = page;
  setStreamMode('history');
  const bucket = state.timeline.find((d) => d.day === day);
  const slot = bucket && bucket.hours.find((h) => h.hour === hour);
  if (!slot) return;
  const params = new URLSearchParams({
    from_ts: String(slot.first_ts),
    to_ts: String(slot.last_ts),
    limit: String(state.historyLimit),
    offset: String((page - 1) * state.historyLimit),
  });
  try {
    const data = await api('/api/events?' + params.toString());
    state.historyTotal = data.total || 0;
    // 后端按时间倒序返回，弹幕流里改成从早到晚更自然
    renderStreamLines((data.items || []).slice().reverse());
    $('tl-count').textContent = `${day} ${hour}:00 · 共 ${state.historyTotal} 条`;
    renderPager($('stream-pager'), page, state.historyTotal, state.historyLimit, (p) => {
      enterHistory(day, hour, p);
    });
  } catch (err) {
    $('stream').innerHTML = `<div class="empty-state">加载历史失败：${esc(err.message)}</div>`;
  }
}

async function backToLive() {
  setStreamMode('live');
  // 下拉同步回到「实时」，避免显示与实际视图不一致
  state.historyDay = '';
  state.historyHour = '';
  renderTimelineSelects();
  state.historyPage = 1;
  state.historyTotal = 0;
  state.pendingLines = [];
  refreshStreamHint();
  try {
    // 回到实时时补一屏最近的记录，避免空白
    const data = await api('/api/events?limit=' + state.historyLimit);
    renderStreamLines((data.items || []).slice().reverse());
  } catch (err) {
    $('stream').innerHTML = '';
  }
}

/* ------------------------------------------------------------------ 图表（ECharts） */
const ECHARTS_CDNS = [
  'https://cdn.bootcdn.net/ajax/libs/echarts/5.5.0/echarts.min.js',
  'https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js',
  'https://unpkg.com/echarts@5/dist/echarts.min.js',
];
let echartsPromise = null;

/* 依次尝试多个 CDN 加载 ECharts；全部失败才 reject */
function ensureECharts() {
  if (window.echarts) return Promise.resolve(window.echarts);
  if (echartsPromise) return echartsPromise;
  echartsPromise = new Promise((resolve, reject) => {
    let index = 0;
    const tryNext = () => {
      if (index >= ECHARTS_CDNS.length) {
        echartsPromise = null;
        reject(new Error('ECharts 加载失败'));
        return;
      }
      const script = document.createElement('script');
      script.src = ECHARTS_CDNS[index++];
      script.onload = () => (window.echarts ? resolve(window.echarts) : tryNext());
      script.onerror = tryNext;
      document.head.appendChild(script);
    };
    tryNext();
  });
  return echartsPromise;
}

const CHART_COLORS = {
  danmaku: '#5b9dff',
  enter: '#3ecf8e',
  gift: '#f2c14e',
  other: '#8b93a7',
};
const GIFT_TYPES_ARR = ['gift', 'guard', 'superchat'];
const INTERACT_TYPES_ARR = ['follow', 'special_follow', 'mutual_follow', 'share', 'like'];

/* 顶部密度条：单指标只画一条线，all 画多条堆叠面积 */
const DENSITY_METRICS = {
  danmaku: [['弹幕', ['danmaku'], CHART_COLORS.danmaku]],
  enter: [['进场', ['enter'], CHART_COLORS.enter]],
  gift: [['礼物', GIFT_TYPES_ARR, CHART_COLORS.gift]],
  all: [
    ['弹幕', ['danmaku'], CHART_COLORS.danmaku],
    ['进场', ['enter'], CHART_COLORS.enter],
    ['礼物', GIFT_TYPES_ARR, CHART_COLORS.gift],
    ['互动', INTERACT_TYPES_ARR, CHART_COLORS.other],
  ],
};

const AXIS_STYLE = {
  axisLine: { lineStyle: { color: '#262c39' } },
  axisLabel: { color: '#8b93a7', fontSize: 9 },
};
const TOOLTIP_STYLE = {
  trigger: 'axis',
  backgroundColor: '#1c212b',
  borderColor: '#262c39',
  textStyle: { color: '#e7eaf0', fontSize: 11 },
};
const GRID_STYLE = { left: 32, right: 10, top: 10, bottom: 18 };

function bindResize(el, chart) {
  if (typeof ResizeObserver === 'undefined') return null;
  const observer = new ResizeObserver(() => chart && chart.resize());
  observer.observe(el);
  return observer;
}

/* 当前密度曲线的时间窗：实时取最近 30 分钟，回看取所选小时 */
function densityWindow() {
  if (state.streamMode === 'history') {
    const day = state.timeline.find((d) => d.day === state.historyDay);
    const slot = day && day.hours.find((h) => h.hour === state.historyHour);
    if (slot) {
      return {
        from_ts: slot.first_ts - 1000,
        to_ts: slot.last_ts + 1000,
        bucket: 60,
        label: `${state.historyDay} ${state.historyHour}:00`,
      };
    }
  }
  const to = Date.now();
  return { from_ts: to - 30 * 60 * 1000, to_ts: to, bucket: 60, label: '近 30 分钟' };
}

function mountDensityChart() {
  const el = $('density-chart');
  if (!el || state.densityChart) return;
  state.densityChart = window.echarts.init(el, null, { renderer: 'canvas' });
  bindResize(el, state.densityChart);
}

async function loadDensity() {
  if (!state.densityChart) return;
  const win = densityWindow();
  const params = new URLSearchParams({
    bucket: String(win.bucket),
    from_ts: String(win.from_ts),
    to_ts: String(win.to_ts),
  });
  const groups = DENSITY_METRICS[state.densityMetric] || DENSITY_METRICS.danmaku;
  if (groups.length === 1) params.set('types', groups[0][1].join(','));
  let data;
  try {
    data = await api('/api/density?' + params.toString());
  } catch (err) {
    $('density-hint').textContent = '曲线加载失败';
    return;
  }
  const series = groups.map(([name, types, color]) => {
    const byTs = new Map();
    types.forEach((t) => (data.groups[t] || []).forEach(([ts, n]) => byTs.set(ts, (byTs.get(ts) || 0) + n)));
    return { name, color, points: [...byTs.entries()].sort((a, b) => a[0] - b[0]) };
  });
  const total = series.reduce((sum, s) => sum + s.points.reduce((a, p) => a + p[1], 0), 0);
  const peak = series.reduce((max, s) => Math.max(max, ...s.points.map((p) => p[1]), 0), 0);
  $('density-hint').textContent = `${win.label} · 共 ${total} 条 · 峰值 ${peak}/分`;
  // 操作记录色带：只画与当前可视窗口有交集的，越界的裁到窗口边缘
  const bands = (state.actions || [])
    .filter((a) => a.end_ts >= win.from_ts && a.start_ts <= win.to_ts)
    .map((a) => [
      {
        xAxis: Math.max(a.start_ts, win.from_ts),
        name: a.label || a.kind,
        itemStyle: { color: a.color || '#8b93a7', opacity: 0.16 },
      },
      { xAxis: Math.min(a.end_ts, win.to_ts) },
    ]);
  state.densityChart.setOption(
    {
      animation: false,
      grid: { ...GRID_STYLE, top: 22 },
      tooltip: TOOLTIP_STYLE,
      legend: {
        right: 2,
        top: 0,
        itemWidth: 9,
        itemHeight: 8,
        itemGap: 12,
        icon: 'roundRect',
        textStyle: { color: '#8b93a7', fontSize: 10 },
        data: series.map((s) => s.name),
      },
      xAxis: { type: 'time', min: win.from_ts, max: win.to_ts, ...AXIS_STYLE, splitLine: { show: false } },
      yAxis: { type: 'value', minInterval: 1, ...AXIS_STYLE, splitLine: { lineStyle: { color: 'rgba(38,44,57,.5)' } } },
      series: series.map((s, i) => {
        const item = {
          name: s.name,
          type: 'line',
          smooth: true,
          showSymbol: false,
          lineStyle: { width: 1.6, color: s.color },
          itemStyle: { color: s.color },
          areaStyle: { opacity: series.length === 1 ? 0.18 : 0.12, color: s.color },
          data: s.points,
        };
        // markArea 只挂第一条：挂多条会叠色加深，而且 silent 才不会吃掉 tooltip
        if (i === 0 && bands.length) {
          item.markArea = {
            silent: true,
            label: { show: true, position: 'insideTop', fontSize: 9, color: '#c9d1de' },
            data: bands,
          };
        }
        return item;
      }),
    },
    true
  );
}

/* -------------------------------------------------- 操作记录（唱歌 / PK / 杂谈 …） */
function fmtClock(ts) {
  const d = new Date(ts);
  const p = (n) => String(n).padStart(2, '0');
  return `${p(d.getHours())}:${p(d.getMinutes())}`;
}

/* 记录锚点：实时就是现在，回看时落在所选小时的末尾，色带才不会跑到窗口外 */
function actionAnchor() {
  return densityWindow().to_ts;
}

function renderActionBar() {
  const wrap = $('action-btns');
  if (!wrap) return;
  wrap.innerHTML = state.actionKinds
    .map(
      (k) =>
        `<button class="action-btn" data-kind="${esc(k.key)}" title="默认 ${k.minutes} 分钟">` +
        `<i style="background:${esc(k.color)}"></i>${esc(k.label)}</button>`
    )
    .join('');
  wrap.querySelectorAll('.action-btn').forEach((btn) => {
    btn.onclick = () => openActionModal(btn.dataset.kind);
  });
}

function updateActionRange() {
  const kind = state.pendingKind;
  if (!kind) return;
  const raw = Number($('action-minutes').value) || kind.minutes;
  const minutes = Math.min(Math.max(raw, 1), 180);
  const end = actionAnchor();
  $('action-modal-range').textContent =
    `记录区间 ${fmtClock(end - minutes * 60000)} – ${fmtClock(end)}（共 ${minutes} 分钟）`;
}

function openActionModal(kindKey) {
  const kind = state.actionKinds.find((k) => k.key === kindKey);
  if (!kind) return;
  state.pendingKind = kind;
  $('action-modal-title').textContent = `记录「${kind.label}」`;
  $('action-minutes').value = String(kind.minutes);
  $('action-note').value = '';
  updateActionRange();
  $('action-modal').classList.add('show');
}

function closeActionModal() {
  $('action-modal').classList.remove('show');
  state.pendingKind = null;
}

async function saveAction() {
  const kind = state.pendingKind;
  if (!kind) return;
  const minutes = Number($('action-minutes').value) || kind.minutes;
  const note = $('action-note').value.trim();
  const btn = $('btn-action-save');
  btn.disabled = true;
  try {
    await api('/api/actions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ kind: kind.key, minutes, note, end_ts: actionAnchor() }),
    });
  } catch (err) {
    btn.disabled = false;
    alert('记录失败：' + err.message);
    return;
  }
  btn.disabled = false;
  closeActionModal();
  await loadActions();
  if (state.densityChart) loadDensity();
}

async function loadActions() {
  try {
    const data = await api('/api/actions?limit=200');
    state.actions = data.items || [];
    state.actionKinds = data.kinds || [];
  } catch (err) {
    console.error('加载操作记录失败', err);
  }
  renderActionBar();
}

async function openActionsModal() {
  $('actions-modal').classList.add('show');
  $('actions-body').innerHTML = '<div class="chart-fallback">正在统计…</div>';
  await loadActionMetrics();
}

async function loadActionMetrics() {
  let data;
  try {
    data = await api('/api/actions?metrics=1&limit=200');
  } catch (err) {
    $('actions-body').innerHTML = `<div class="chart-fallback">读取失败：${esc(err.message)}</div>`;
    return;
  }
  state.actionSummary = data.summary || [];
  state.actionBaseline = data.baseline || null;
  renderActionsModal(data.items || []);
}

const ACTION_COLUMNS = [
  ['danmaku_per_min', '弹幕/分'],
  ['enter_per_min', '进场/分'],
  ['gift_per_min', '礼物/分'],
  ['interact_per_min', '互动/分'],
  ['income_per_min', '流水/分'],
];

function actionCells(row) {
  return ACTION_COLUMNS.map(([, key]) => `<td>${row[key] ?? '—'}</td>`).join('');
}

function renderActionsModal(items) {
  const body = $('actions-body');
  if (!items.length) {
    body.innerHTML = '<div class="chart-fallback">还没有操作记录。点上方「记录」按钮记一条吧。</div>';
    return;
  }
  const head =
    '<tr><th>操作</th><th>次数</th><th>时长(分)</th>' +
    ACTION_COLUMNS.map(([label]) => `<th>${label}</th>`).join('') +
    '<th>人气均值</th></tr>';

  const summaryRows = state.actionSummary
    .map(
      (r) =>
        `<tr><td class="a-name"><i style="background:${esc(r.color || '#8b93a7')}"></i>${esc(r.label)}</td>` +
        `<td>${r.count}</td><td>${r.minutes_avg}</td>${actionCells(r)}<td>${r.popularity_avg ?? '—'}</td></tr>`
    )
    .join('');
  const base = state.actionBaseline;
  const baseRow = base
    ? `<tr class="baseline"><td class="a-name"><i style="background:#8b93a7"></i>本场平均</td>` +
      `<td>—</td><td>${base.minutes ?? '—'}</td>${actionCells(base)}` +
      `<td>${base.popularity_avg ?? '—'}</td></tr>`
    : '';

  const records = items
    .map((it) => {
      const m = it.metrics || {};
      const bits = [
        `弹幕 ${m.danmaku ?? 0}`,
        `进场 ${m.enter ?? 0}`,
        `礼物 ${m.gift ?? 0}`,
        `互动 ${m.interact ?? 0}`,
        `流水 ¥${m.income ?? 0}`,
      ];
      if (m.popularity_avg != null) bits.push(`人气均值 ${m.popularity_avg}`);
      return (
        `<li class="action-row">` +
        `<span class="a-dot" style="background:${esc(it.color || '#8b93a7')}"></span>` +
        `<div class="a-main">` +
        `<div class="a-title">${esc(it.label || it.kind)}` +
        `<span class="a-time">${fmtClock(it.start_ts)}–${fmtClock(it.end_ts)} · ${m.minutes ?? '—'} 分钟</span></div>` +
        `<div class="a-meta">${bits.join(' · ')}${it.note ? ' · 备注：' + esc(it.note) : ''}</div>` +
        `</div>` +
        `<button class="btn ghost small" data-del="${it.id}">删除</button>` +
        `</li>`
      );
    })
    .join('');

  body.innerHTML =
    '<div class="section-title">效果对比（每分钟均值）</div>' +
    `<table class="actions-table"><thead>${head}</thead><tbody>${summaryRows}${baseRow}</tbody></table>` +
    '<div class="section-title">全部记录</div>' +
    `<ul class="actions-list">${records}</ul>`;
  body.querySelectorAll('button[data-del]').forEach((btn) => {
    btn.onclick = () => deleteAction(Number(btn.dataset.del));
  });
}

async function deleteAction(actionId) {
  if (!window.confirm('删除这条操作记录？')) return;
  try {
    await api('/api/actions/' + actionId, { method: 'DELETE' });
  } catch (err) {
    alert('删除失败：' + err.message);
    return;
  }
  await loadActions();
  if (state.densityChart) loadDensity();
  if ($('actions-modal').classList.contains('show')) await loadActionMetrics();
}

/* -------------------------------------------------- 观众个人曲线（概览页） */
let userChartObservers = [];

function disposeUserCharts() {
  userChartObservers.forEach((observer) => observer && observer.disconnect());
  userChartObservers = [];
  if (state.userHourChart) { state.userHourChart.dispose(); state.userHourChart = null; }
  if (state.userTrendChart) { state.userTrendChart.dispose(); state.userTrendChart = null; }
}

/* 把一堆 [ts, n] 按本地小时归并成 0-23 点的分布 */
function hourDistribution(data) {
  const sums = Array.from({ length: 24 }, () => ({ danmaku: 0, enter: 0, gift: 0 }));
  Object.entries(data.groups || {}).forEach(([type, points]) => {
    const key = type === 'danmaku' ? 'danmaku'
      : type === 'enter' ? 'enter'
      : GIFT_TYPES_ARR.includes(type) ? 'gift' : null;
    if (!key) return;
    points.forEach(([ts, n]) => { sums[new Date(ts).getHours()][key] += n; });
  });
  return sums;
}

function buildHourOption(data) {
  const sums = hourDistribution(data);
  const defs = [
    ['弹幕', 'danmaku', CHART_COLORS.danmaku],
    ['进场', 'enter', CHART_COLORS.enter],
    ['礼物', 'gift', CHART_COLORS.gift],
  ];
  return {
    animation: false,
    grid: { left: 30, right: 8, top: 6, bottom: 20 },
    tooltip: TOOLTIP_STYLE,
    legend: { right: 4, top: 0, itemWidth: 8, itemHeight: 8, textStyle: { color: '#8b93a7', fontSize: 10 } },
    xAxis: {
      type: 'category',
      data: Array.from({ length: 24 }, (_, h) => `${h}点`),
      ...AXIS_STYLE,
      axisLabel: { color: '#8b93a7', fontSize: 9, interval: 3 },
    },
    yAxis: { type: 'value', minInterval: 1, ...AXIS_STYLE, splitLine: { lineStyle: { color: 'rgba(38,44,57,.5)' } } },
    series: defs.map(([name, key, color]) => ({
      name,
      type: 'bar',
      stack: 'total',
      barMaxWidth: 10,
      itemStyle: { color },
      data: sums.map((row) => row[key]),
    })),
  };
}

function buildTrendOption(data) {
  const defs = [
    ['弹幕', ['danmaku'], CHART_COLORS.danmaku],
    ['进场', ['enter'], CHART_COLORS.enter],
    ['礼物', GIFT_TYPES_ARR, CHART_COLORS.gift],
  ];
  const series = defs.map(([name, types, color]) => {
    const byTs = new Map();
    types.forEach((t) => (data.groups[t] || []).forEach(([ts, n]) => byTs.set(ts, (byTs.get(ts) || 0) + n)));
    return { name, color, points: [...byTs.entries()].sort((a, b) => a[0] - b[0]) };
  });
  return {
    animation: false,
    grid: { left: 30, right: 8, top: 6, bottom: 18 },
    tooltip: TOOLTIP_STYLE,
    legend: { right: 4, top: 0, itemWidth: 8, itemHeight: 8, textStyle: { color: '#8b93a7', fontSize: 10 } },
    xAxis: { type: 'time', ...AXIS_STYLE, splitLine: { show: false } },
    yAxis: { type: 'value', minInterval: 1, ...AXIS_STYLE, splitLine: { lineStyle: { color: 'rgba(38,44,57,.5)' } } },
    series: series.map((s) => ({
      name: s.name,
      type: 'line',
      smooth: true,
      showSymbol: false,
      lineStyle: { width: 1.5, color: s.color },
      itemStyle: { color: s.color },
      areaStyle: { opacity: 0.1, color: s.color },
      data: s.points,
    })),
  };
}

async function mountUserCharts(viewer) {
  disposeUserCharts();
  const hourEl = $('user-hour-chart');
  const trendEl = $('user-trend-chart');
  if (!hourEl || !trendEl) return;
  let echarts;
  try {
    echarts = await ensureECharts();
  } catch (err) {
    if (hourEl) hourEl.outerHTML = '<div class="chart-fallback">图表库加载失败（ECharts CDN 不可达）</div>';
    return;
  }
  // 加载期间可能切换了观众或分类
  if (state.selectedUid !== viewer.uid || state.profileTab !== 'overview') return;
  const hourBox = $('user-hour-chart');
  const trendBox = $('user-trend-chart');
  if (!hourBox || !trendBox) return;

  state.userHourChart = echarts.init(hourBox, null, { renderer: 'canvas' });
  state.userTrendChart = echarts.init(trendBox, null, { renderer: 'canvas' });
  userChartObservers = [
    bindResize(hourBox, state.userHourChart),
    bindResize(trendBox, state.userTrendChart),
  ].filter(Boolean);

  const from = viewer.first_seen || (viewer.last_seen - 86400000);
  const to = viewer.last_seen || Date.now();
  const span = Math.max(to - from, 60000);
  const trendBucket = Math.min(Math.max(Math.round(span / 200 / 1000), 300), 86400);
  const base = `uid=${viewer.uid}&from_ts=${from}&to_ts=${to}`;
  const hint = $('user-chart-hint');
  try {
    const [hourly, trend] = await Promise.all([
      api(`/api/density?${base}&bucket=3600`),
      api(`/api/density?${base}&bucket=${trendBucket}`),
    ]);
    if (state.selectedUid !== viewer.uid || state.profileTab !== 'overview') return;
    state.userHourChart.setOption(buildHourOption(hourly), true);
    state.userTrendChart.setOption(buildTrendOption(trend), true);
    if (hint) hint.textContent = `统计区间 ${fmtFull(from)} ~ ${fmtFull(to)}`;
  } catch (err) {
    if (hint) hint.textContent = '曲线加载失败：' + err.message;
  }
}

/* ------------------------------------------------------------------ 画像面板 */
const PROFILE_TABS = [
  ['overview', '概览'],
  ['ai', 'AI 画像'],
  ['behavior', '行为'],
  ['spend', '消费'],
  ['messages', '发言'],
  ['note', '备注'],
];

const EVENT_LABELS = {
  danmaku: '弹幕',
  enter: '进场',
  follow: '关注',
  special_follow: '特别关注',
  mutual_follow: '互相关注',
  share: '分享',
  like: '点赞',
  gift: '礼物',
  guard: '上舰',
  superchat: '醒目留言',
};

const INTERACT_TYPES = new Set(['follow', 'special_follow', 'mutual_follow', 'share', 'like']);
const GIFT_TYPES = new Set(['gift', 'guard', 'superchat']);

const BEHAVIOR_FILTERS = [
  ['all', '全部'],
  ['enter', '进场'],
  ['danmaku', '弹幕'],
  ['interact', '互动'],
  ['gift', '礼物'],
];

function fmtFull(ts) {
  if (!ts) return '-';
  const d = new Date(ts);
  const p = (n) => String(n).padStart(2, '0');
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

/* 「行为」筛选走服务端 types 参数，保证筛选与统计是全局口径而不是当前页 */
const BEHAVIOR_TYPE_MAP = {
  all: null,
  enter: ['enter'],
  danmaku: ['danmaku'],
  interact: ['follow', 'special_follow', 'mutual_follow', 'share', 'like'],
  gift: ['gift', 'guard', 'superchat'],
};

function behaviorListHtml(events) {
  if (!events.length) {
    return `<p class="muted-note" style="padding:10px 16px">该分类下暂无记录。</p>`;
  }
  return events
    .map((e) => {
      const label = EVENT_LABELS[e.type] || e.type;
      const body = e.content ? esc(e.content) : '<span class="muted-note">—</span>';
      return `<div class="tl-row ${INTERACT_TYPES.has(e.type) || GIFT_TYPES.has(e.type) ? 'tl-strong' : ''}">
        <span class="tl-time">${fmtFull(e.ts)}</span>
        <span class="tl-type t-${e.type}">${esc(label)}</span>
        <span class="tl-msg">${body}</span>
      </div>`;
    })
    .join('');
}

function tabBehaviorHtml(data) {
  const counts = data.type_counts || {};
  const summary = Object.keys(EVENT_LABELS)
    .filter((k) => counts[k])
    .map((k) => `<span class="mini-stat">${esc(EVENT_LABELS[k])} ${counts[k]}</span>`)
    .join('');
  return `
    <div class="section">
      <h4>记录汇总</h4>
      <div class="mini-stats">${summary || '<span class="muted-note">暂无记录</span>'}</div>
      <p class="muted-note" style="margin-top:8px">B站弹幕协议不推送「出场」事件，因此这里记录的是进场与互动时刻；「最后活跃」可近似当作离开时间。</p>
    </div>
    <div class="section" style="border-bottom:none;padding-bottom:0">
      <h4>行为时间线</h4>
      <div class="tabs behavior-tabs" id="behavior-tabs">
        ${BEHAVIOR_FILTERS.map(([k, label]) => `<button class="tab ${k === state.behaviorFilter ? 'active' : ''}" data-filter="${k}">${label}</button>`).join('')}
      </div>
    </div>
    <div id="behavior-list">${behaviorListHtml(data.events || [])}</div>
    <div class="pager" id="behavior-pager" hidden></div>`;
}

/* 「发言」列表内容，配合筛选项做局部刷新 */
function messageListHtml(events) {
  if (!events.length) {
    return `<p class="muted-note" style="padding:10px 16px">没有符合条件的发言。</p>`;
  }
  return events
    .map(
      (m) => `<div class="mini-msg"><span class="t">${fmtFull(m.ts)}</span><span>${markTopics(m.content)}</span></div>`
    )
    .join('');
}

/* 「发言」分类：只取弹幕，带关键词 / 只看本场 / 正倒序筛选与分页 */
function tabMessagesHtml() {
  const orderLabel = state.msgOrder === 'asc' ? '时间正序 ↑' : '时间倒序 ↓';
  return `
    <div class="section">
      <h4>发言筛选</h4>
      <div class="msg-tools">
        <input type="search" id="msg-search" placeholder="搜索发言关键词…" value="${esc(state.msgKeyword)}">
        <div class="msg-tools-row">
          <label class="switch"><input type="checkbox" id="msg-session" ${state.msgSessionOnly ? 'checked' : ''}>只看本场</label>
          <button class="tab" id="msg-order">${orderLabel}</button>
        </div>
        <span class="hint" id="msg-hint"></span>
      </div>
    </div>
    <div id="msg-list"></div>
    <div class="pager" id="msg-pager" hidden></div>`;
}

function tabNoteHtml(viewer) {
  return `<div class="section" style="border-bottom:none">
    <h4>主播备注</h4>
    <textarea id="note-input" placeholder="记点什么，比如：隔壁老同学 / 昨天说想听某首歌">${esc(viewer.note || '')}</textarea>
    <div class="section-foot"><button class="btn ghost small" id="btn-save-note">保存备注</button></div>
  </div>`;
}

function tabHtml(tab, data) {
  const { viewer, events, metrics } = data;
  if (tab === 'ai') return tabAiHtml(viewer, viewer.profile);
  if (tab === 'behavior') return tabBehaviorHtml(data);
  if (tab === 'spend') return tabSpendHtml(events.filter((e) => GIFT_TYPES.has(e.type)), viewer);
  if (tab === 'messages') return tabMessagesHtml();
  if (tab === 'note') return tabNoteHtml(viewer);
  return tabOverviewHtml(viewer, metrics);
}

/* 「消费」标签：该观众的礼物 / 上舰 / 醒目留言流水（金额、时间、类型） */
function tabSpendHtml(events, viewer) {
  if (!events.length) {
    return `<div class="section" style="border-bottom:none"><p class="muted-note">TA 还没有送过礼物或上舰</p></div>`;
  }
  const rows = events
    .map((e) => {
      const extra = e.extra || {};
      const value = Number(extra.value || 0);
      const paid = extra.paid !== false;   // 旧数据没有 paid 字段，按付费处理
      return `<div class="spend-row">
        <span class="spend-time">${fmtFull(e.ts)}</span>
        <span class="spend-name">${esc(e.content || '-')}</span>
        <span class="spend-type">${esc(EVENT_LABELS[e.type] || e.type)}</span>
        <span class="spend-amount ${paid && value ? '' : 'free'}">${paid && value ? '¥' + value : '免费'}</span>
      </div>`;
    })
    .join('');
  return `
    <div class="section">
      <h4>消费汇总</h4>
      <div class="metric-grid">
        <div class="metric"><b>¥${viewer.gift_value ?? 0}</b><span>累计消费</span></div>
        <div class="metric"><b>${viewer.spend_count || 0}</b><span>付费次数</span></div>
        <div class="metric"><b>${events.length}</b><span>近期记录</span></div>
      </div>
      <p class="muted-note" style="margin-top:8px">只统计金瓜子（付费）礼物的金额，银瓜子等免费礼物不计流水。</p>
    </div>
    <div class="section" style="border-bottom:none">
      <h4>礼物流水</h4>
      <div class="spend-list">${rows}</div>
    </div>`;
}

/* 画像「兴趣元素」：把命中词库的游戏 / 梗 / 番剧等做成小标签，按提及条数排序 */
function topicChipsHtml(metrics) {
  const items = (metrics && metrics['提及元素(规则)']) || [];
  if (!items.length) return '';
  return `
    <div class="section">
      <h4>兴趣元素</h4>
      <div class="topic-chips">
        ${items
          .map(
            (it) => `<span class="topic-chip">
              <i style="background:${it['颜色']}"></i><b>${esc(it['名称'])}</b><em>${esc(it['分类'])} ×${it['次数']}</em>
              ${it['说明'] ? `<span class="topic-desc">${esc(it['说明'])}</span>` : ''}
            </span>`
          )
          .join('')}
      </div>
    </div>`;
}

function tabOverviewHtml(viewer, metrics) {
  const spanDays = Math.max(1, Math.ceil((viewer.last_seen - viewer.first_seen) / 86400000));
  const avgPerDay = (viewer.msg_count / spanDays).toFixed(1);
  const giftSummary = metrics['礼物概览(规则)'] || [];
  const guardSummary = metrics['上舰记录(规则)'] || [];
  const scLines = metrics['醒目留言(规则)'] || [];
  const hasSpend = giftSummary.length || guardSummary.length || scLines.length;
  const metricCards = [
    [viewer.msg_count, '弹幕总数', 'var(--accent)'],
    [viewer.enter_count, '进场次数', 'var(--blue)'],
    [`¥${viewer.gift_value}`, '实际消费(记录)', 'var(--green)'],
    [viewer.spend_count || 0, '付费次数', 'var(--red)'],
  ];
  const info = (label, value, cls = '') =>
    `<div class="info-card"><span>${label}</span><b class="${cls}">${value}</b></div>`;
  return `
    <div class="section">
      <h4>活跃分布</h4>
      <div class="mini-stats">
        <span class="mini-stat">发言 <b>${viewer.msg_count}</b></span>
        <span class="mini-stat">进场 <b>${viewer.enter_count}</b></span>
        <span class="mini-stat">光顾 <b>${metrics['光顾场次数'] || 0}</b> 场</span>
        <span class="mini-stat">付费 <b>${viewer.spend_count || 0}</b> 次</span>
        <span class="mini-stat">礼物 <b>¥${viewer.gift_value}</b></span>
        <span class="mini-stat">活跃 <b>${spanDays}</b> 天</span>
        <span class="mini-stat">日均 <b>${avgPerDay}</b> 条</span>
      </div>
      <div class="chart-box tall" id="user-hour-chart"></div>
      <div class="chart-box tall" id="user-trend-chart"></div>
      <p class="muted-note" id="user-chart-hint" style="margin-top:4px"></p>
    </div>
    ${topicChipsHtml(metrics)}
    <div class="section">
      <h4>行为数据</h4>
      <div class="metric-grid two">
        ${metricCards
          .map(([value, label, color]) => `<div class="metric" style="--c:${color}"><b>${value}</b><span>${label}</span></div>`)
          .join('')}
      </div>
    </div>
    <div class="section">
      <h4>时间</h4>
      <div class="info-grid">
        ${info('首次出现', esc(metrics['首次出现']))}
        ${info('最近出现', esc(metrics['最近出现']))}
        ${info('最近出现距今', esc(metrics['最近出现距今'] || '-'), 'hl')}
        ${info('光顾场次', `${metrics['光顾场次数'] || 0} 场`, 'hl-blue')}
        <div class="info-card wide"><span>关注时长</span><b>${esc(metrics['关注时长'])}</b></div>
      </div>
    </div>
    <div class="section">
      <h4>互动倾向</h4>
      <div class="info-grid">
        ${info('潜水指数', esc(metrics['潜水指数'] || '-'))}
        ${metrics['身份标记'] ? info('身份标记', esc(metrics['身份标记']), 'hl') : ''}
        ${info('关注过主播', esc(metrics['关注过主播'] || '未知'), metrics['关注过主播'] === '是' ? 'hl-blue' : '')}
        ${info('最后活跃', fmtFull(viewer.last_seen))}
      </div>
    </div>
    ${hasSpend ? `
    <div class="section">
      <h4>消费与留言</h4>
      ${giftSummary.length ? `<div class="kv"><span>礼物概览</span><span>${esc(giftSummary.join('、'))}</span></div>` : ''}
      ${guardSummary.length ? `<div class="kv"><span>上舰记录</span><span>${esc(guardSummary.join('、'))}</span></div>` : ''}
      ${scLines.length ? `
        <div class="sub-label">醒目留言</div>
        <div class="quote-list">${scLines.slice(0, 5).map((t) => `<div class="quote">${esc(t)}</div>`).join('')}</div>` : ''}
    </div>` : ''}
    <div class="section" style="border-bottom:none">
      <h4>身份与偏好</h4>
      <div class="info-grid">
        ${info('舰长等级', esc(metrics['舰长等级']), 'hl')}
        ${info('粉丝牌', `${esc(metrics['粉丝牌名称'] || '-')} Lv${metrics['粉丝牌等级'] || 0}`)}
        <div class="info-card wide"><span>粉丝牌折算(估)</span><b>${esc(metrics['粉丝牌折算消费(估)'] || (metrics['粉丝牌等级'] ? '-' : '无牌子'))}</b></div>
        ${info('关注过主播', esc(metrics['关注过主播'] || '未知'), metrics['关注过主播'] === '是' ? 'hl-blue' : '')}
        ${info('情绪倾向(规则)', esc(metrics['情绪倾向(规则)']))}
        <div class="info-card wide"><span>高频词(规则)</span><b>${esc((metrics['高频词(规则)'] || []).join(' ')) || '-'}</b></div>
      </div>
    </div>
  `;
}

/* AI 画像的扩展信息：地点、时段、生活状态、具体偏好（游戏/音乐/动漫等） */
function profileExtrasHtml(profile) {
  const life = profile.life_stage || {};
  const fav = profile.favorites || {};
  const lifeRows = [
    ['感情/婚姻', life.marriage],
    ['孕育', life.pregnancy],
    ['子女', life.children],
    ['父母', life.parents],
  ].filter(([, v]) => v && String(v).trim());
  const favRows = [
    ['游戏', fav.games],
    ['音乐', fav.music],
    ['动漫', fav.anime],
    ['美食', fav.food],
    ['其它爱好', fav.hobbies],
  ].filter(([, list]) => Array.isArray(list) && list.length);
  let html = '';
  if (profile.location || profile.active_hours) {
    html += `<div class="section">
      <h4>基本信息</h4>
      <div class="info-grid">
        ${profile.location ? `<div class="info-card"><span>常驻地点</span><b class="hl">${esc(profile.location)}</b></div>` : ''}
        ${profile.active_hours ? `<div class="info-card wide"><span>活跃时段</span><b>${esc(profile.active_hours)}</b></div>` : ''}
      </div>
    </div>`;
  }
  if (lifeRows.length) {
    html += `<div class="section">
      <h4>生活状态</h4>
      <div class="info-grid">
        ${lifeRows.map(([k, v]) => `<div class="info-card"><span>${k}</span><b>${esc(v)}</b></div>`).join('')}
      </div>
      <p class="muted-note" style="margin-top:8px">仅整理观众本人在直播间公开说过的信息。</p>
    </div>`;
  }
  if (favRows.length) {
    html += `<div class="section">
      <h4>具体偏好</h4>
      ${favRows
        .map(([k, list]) => `<div class="fav-row">
          <span class="fav-label">${k}</span>
          <div class="topic-chips">${list.map((x) => `<span class="tag">${esc(x)}</span>`).join('')}</div>
        </div>`)
        .join('')}
    </div>`;
  }
  if (!html) {
    html = `<div class="section">
      <h4>更多信息</h4>
      <p class="muted-note">该观众暂未在发言中透露地点、生活状态或具体偏好（游戏/歌曲/动漫等）。</p>
    </div>`;
  }
  return html;
}

function tabAiHtml(viewer, profile) {
  if (viewer.profile_status === 'running' || viewer.profile_status === 'pending') {
    return `<div class="section"><h4>AI 画像</h4>
      <p class="muted-note"><span class="spinner"></span>正在分析该观众的行为与发言…</p></div>`;
  }
  if (viewer.profile_status === 'error') {
    return `<div class="section"><h4>AI 画像</h4>
      <p class="muted-note">分析失败：${esc(viewer.profile_error || '未知错误')}</p></div>`;
  }
  if (!profile) {
    return `<div class="section"><h4>AI 画像</h4>
      <p class="muted-note">还没有画像，点上面的「生成画像」按钮开始分析。</p></div>`;
  }
  return `
    <div class="section">
      <h4>AI 画像</h4>
      <div class="persona-hero">
        <div class="persona-name">${esc(profile.nickname_hint || '这位观众')}</div>
        <p class="persona-text">${esc(profile.persona || '暂无概括')}</p>
        <div class="tag-row">${(profile.tags || []).map((t) => `<span class="tag">${esc(t)}</span>`).join('')}</div>
      </div>
      <div class="chip-row">
        <span class="pchip rel">关系 · ${esc(profile.relationship || '未知')}</span>
        <span class="pchip mood">情绪 · ${esc(profile.mood_now || '未知')}</span>
        <span class="pchip act">活跃 ${esc(profile.activity_level || '-')}</span>
        <span class="pchip val">消费 ${esc(profile.value_level || '-')}</span>
      </div>
      <div class="kv" style="margin-top:10px"><span>一句话记住</span><span>${esc(profile.memory_hook || '-')}</span></div>
      <div class="kv"><span>兴趣点</span><span>${esc((profile.interests || []).join(' ')) || '-'}</span></div>
    </div>
    ${profileExtrasHtml(profile)}
    <div class="section">
      <h4>应对方法</h4>
      <ol class="strategy">${(profile.response_strategy || [])
        .map((s, i) => `<li><i>${i + 1}</i><span>${esc(s)}</span></li>`)
        .join('') || '<li><span>暂无</span></li>'}</ol>
    </div>
    <div class="section" style="border-bottom:none">
      <h4>可以直接说</h4>
      ${(profile.sample_replies || []).map((r) => `<div class="reply" data-copy="${esc(r)}">${esc(r)}</div>`).join('') || '<p class="muted-note">暂无</p>'}
      ${profile.risk_note ? `<div class="risk">⚠ ${esc(profile.risk_note)}</div>` : ''}
    </div>`;
}

/* 「行为」分类翻页：只刷新列表与分页条，不重建整个画像面板 */
async function loadBehaviorPage(uid, filter, page) {
  state.behaviorFilter = filter;
  state.behaviorPage = page;
  const types = BEHAVIOR_TYPE_MAP[filter];
  const params = new URLSearchParams({
    limit: String(BEHAVIOR_PAGE_SIZE),
    offset: String((page - 1) * BEHAVIOR_PAGE_SIZE),
  });
  if (types) params.set('types', types.join(','));
  try {
    const data = await api(`/api/viewers/${uid}?${params.toString()}`);
    if (state.selectedUid !== uid) return;
    $('behavior-list').innerHTML = behaviorListHtml(data.events || []);
    renderPager($('behavior-pager'), page, data.total || 0, BEHAVIOR_PAGE_SIZE, (p) =>
      loadBehaviorPage(uid, state.behaviorFilter, p)
    );
  } catch (err) {
    $('behavior-list').innerHTML =
      `<p class="muted-note" style="padding:10px 16px">加载失败：${esc(err.message)}</p>`;
  }
}

/* 「发言」分类翻页 / 筛选：只刷新列表、计数与分页条，不重建整个画像面板 */
async function loadMessagePage(uid, page) {
  state.msgPage = page;
  const params = new URLSearchParams({
    types: 'danmaku',
    limit: String(MESSAGE_PAGE_SIZE),
    offset: String((page - 1) * MESSAGE_PAGE_SIZE),
    order: state.msgOrder,
  });
  if (state.msgKeyword) params.set('keyword', state.msgKeyword);
  if (state.msgSessionOnly) params.set('session_only', '1');
  try {
    const data = await api(`/api/viewers/${uid}?${params.toString()}`);
    if (state.selectedUid !== uid || state.profileTab !== 'messages') return;
    const total = data.total || 0;
    $('msg-list').innerHTML = messageListHtml(data.events || []);
    const hint = $('msg-hint');
    if (hint) hint.textContent = `共 ${total} 条`;
    renderPager($('msg-pager'), page, total, MESSAGE_PAGE_SIZE, (p) => loadMessagePage(uid, p));
  } catch (err) {
    $('msg-list').innerHTML =
      `<p class="muted-note" style="padding:10px 16px">加载失败：${esc(err.message)}</p>`;
  }
}

/* 「消费」标签的数据：只取礼物 / 上舰 / 醒目留言，按时间倒序 */
async function loadSpend(uid) {
  try {
    const data = await api(`/api/viewers/${uid}?types=gift,guard,superchat&limit=100`);
    if (state.selectedUid !== uid || state.profileTab !== 'spend') return;
    $('profile-body').innerHTML = tabSpendHtml(data.events || [], data.viewer || {});
  } catch (err) {
    console.error('加载消费记录失败', err);
  }
}

/* 绑定当前分类里的交互（备注、复制、行为筛选与翻页） */
function bindTabContent(tab, data) {
  const { viewer } = data;
  if (tab === 'note') {
    const button = $('btn-save-note');
    if (button) button.onclick = () => saveNote(viewer.uid);
  }
  $('profile-body')
    .querySelectorAll('.reply')
    .forEach((node) => {
      node.onclick = () => {
        navigator.clipboard?.writeText(node.dataset.copy);
        const original = node.textContent;
        node.textContent = '已复制 ✓';
        setTimeout(() => { node.textContent = original; }, 900);
      };
    });
  const tabs = $('behavior-tabs');
  if (tabs) {
    tabs.querySelectorAll('.tab').forEach((node) => {
      node.onclick = () => {
        state.behaviorFilter = node.dataset.filter;
        tabs.querySelectorAll('.tab').forEach((n) => n.classList.toggle('active', n === node));
        loadBehaviorPage(viewer.uid, state.behaviorFilter, 1);
      };
    });
    // 若当前筛选不是「全部」，初始列表需按筛选重新拉取，保证条数与页数是全局口径
    if (state.behaviorFilter !== 'all') {
      loadBehaviorPage(viewer.uid, state.behaviorFilter, 1);
    } else {
      renderPager($('behavior-pager'), 1, data.total || 0, BEHAVIOR_PAGE_SIZE, (p) =>
        loadBehaviorPage(viewer.uid, state.behaviorFilter, p)
      );
    }
  }
  if (tab === 'messages') {
    const search = $('msg-search');
    if (search) {
      let timer = null;
      search.oninput = () => {
        clearTimeout(timer);
        timer = setTimeout(() => {
          state.msgKeyword = search.value.trim();
          loadMessagePage(viewer.uid, 1);
        }, 300);
      };
    }
    const sessionBox = $('msg-session');
    if (sessionBox) {
      sessionBox.onchange = () => {
        state.msgSessionOnly = sessionBox.checked;
        loadMessagePage(viewer.uid, 1);
      };
    }
    const orderBtn = $('msg-order');
    if (orderBtn) {
      orderBtn.onclick = () => {
        state.msgOrder = state.msgOrder === 'asc' ? 'desc' : 'asc';
        orderBtn.textContent = state.msgOrder === 'asc' ? '时间正序 ↑' : '时间倒序 ↓';
        loadMessagePage(viewer.uid, 1);
      };
    }
  }
}

function switchProfileTab(tab) {
  state.profileTab = tab;
  const panel = $('profile-panel');
  panel.querySelectorAll('.ptab').forEach((n) => n.classList.toggle('active', n.dataset.tab === tab));
  $('profile-body').innerHTML = tabHtml(tab, state.detail);
  bindTabContent(tab, state.detail);
  if (tab === 'messages' && state.detail) loadMessagePage(state.detail.viewer.uid, 1);
  if (tab === 'overview' && state.detail) mountUserCharts(state.detail.viewer);
  else disposeUserCharts();
}

function renderProfile(data) {
  state.detail = data;
  const { viewer } = data;
  const panel = $('profile-panel');
  const tab = PROFILE_TABS.some(([k]) => k === state.profileTab) ? state.profileTab : 'overview';
  state.profileTab = tab;

  panel.innerHTML = `
    <div class="profile-head">
      <div class="profile-title">
        <div class="avatar" style="color:${colorOf(viewer.uid)}">${esc(initial(viewer.uname))}</div>
        <div style="flex:1;min-width:0">
          <div class="profile-name">${esc(viewer.uname || '未知用户')}</div>
          <div class="profile-uid">UID ${viewer.uid} · 最后活跃 ${fmtDelta(viewer.last_seen)}</div>
          <div class="v-badges" style="justify-content:flex-start">${badgeHtml(viewer)}</div>
        </div>
      </div>
      <div class="profile-actions">
        <button class="btn" id="btn-analyze">${viewer.profile ? '重新生成画像' : '生成画像'}</button>
        <button class="btn ghost" id="btn-refresh">刷新</button>
      </div>
    </div>
    <div class="role-bar">
      <span class="role-bar-label">身份</span>
      <input id="role-input" list="role-presets" placeholder="如 AI助手、房管" value="${esc(viewer.role || '')}">
      <datalist id="role-presets">
        <option value="AI助手"></option>
        <option value="房管"></option>
        <option value="主播"></option>
        <option value="机器人"></option>
        <option value="运营"></option>
        <option value="粉丝团"></option>
      </datalist>
      <button class="btn ghost" id="btn-save-role">保存身份</button>
    </div>
    <div class="profile-tabs">
      ${PROFILE_TABS.map(([key, label]) => `<button class="ptab ${key === tab ? 'active' : ''}" data-tab="${key}">${label}</button>`).join('')}
    </div>
    <div class="profile-body" id="profile-body">${tabHtml(tab, data)}</div>`;

  $('btn-analyze').onclick = () => analyze(viewer.uid);
  $('btn-refresh').onclick = () => selectViewer(viewer.uid);
  const roleInput = $('role-input');
  const submitRole = () => saveRole(viewer.uid, roleInput.value.trim());
  $('btn-save-role').onclick = submitRole;
  roleInput.addEventListener('keydown', (e) => { if (e.key === 'Enter') submitRole(); });
  panel.querySelectorAll('.ptab').forEach((node) => {
    node.onclick = () => switchProfileTab(node.dataset.tab);
  });
  bindTabContent(tab, data);
  if (tab === 'messages') loadMessagePage(viewer.uid, 1);
  if (tab === 'spend') loadSpend(viewer.uid);
  if (tab === 'overview') mountUserCharts(viewer);
}

async function selectViewer(uid) {
  state.selectedUid = uid;
  document.querySelectorAll('.viewer').forEach((node) => {
    node.classList.toggle('active', Number(node.dataset.uid) === Number(uid));
  });
  const panel = $('profile-panel');
  if (!state.detail || state.detail.viewer.uid !== uid) {
    panel.innerHTML = `<div class="empty-state"><span class="spinner"></span></div>`;
  }
  try {
    const data = await api(`/api/viewers/${uid}`);
    if (state.selectedUid === uid) renderProfile(data);
  } catch (err) {
    panel.innerHTML = `<div class="empty-state">加载失败：${esc(err.message)}</div>`;
  }
}

async function analyze(uid) {
  await api(`/api/viewers/${uid}/analyze`, { method: 'POST' });
  const panel = $('profile-panel');
  const button = $('btn-analyze');
  if (button) { button.disabled = true; button.innerHTML = '<span class="spinner"></span>分析中…'; }
  else panel.innerHTML = `<div class="empty-state"><span class="spinner"></span><p>正在分析…</p></div>`;
}

async function saveNote(uid) {
  const note = $('note-input').value;
  await api(`/api/viewers/${uid}/note`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ note }),
  });
  const button = $('btn-save-note');
  button.textContent = '已保存 ✓';
  setTimeout(() => { button.textContent = '保存备注'; }, 1000);
}

/* 给观众指定身份：更新本地缓存并就地刷新三处标记，避免整块重渲染 */
async function saveRole(uid, role) {
  await api(`/api/viewers/${uid}/role`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ role }),
  });
  if (role) state.roles[String(uid)] = role;
  else delete state.roles[String(uid)];

  const viewer = state.viewers.get(uid);
  if (viewer) viewer.role = role;
  if (state.detail && state.detail.viewer.uid === uid) state.detail.viewer.role = role;

  const head = document.querySelector('#profile-panel .profile-head .v-badges');
  if (head && state.detail) head.innerHTML = badgeHtml(state.detail.viewer);
  const row = document.querySelector(`#viewer-list .viewer[data-uid="${uid}"] .v-badges`);
  if (row && viewer) row.innerHTML = badgeHtml(viewer);
  document.querySelectorAll(`#stream .name[data-uid="${uid}"]`).forEach((node) => {
    const old = node.nextElementSibling;
    if (old && old.classList.contains('role-tag')) old.remove();
    if (role) node.insertAdjacentHTML('afterend', `<i class="role-tag">${esc(role)}</i>`);
  });

  const button = $('btn-save-role');
  if (button) {
    button.textContent = '已保存 ✓';
    setTimeout(() => { button.textContent = '保存身份'; }, 1000);
  }
}

/* ------------------------------------------------------------------ SSE */
function connectSSE() {
  const source = new EventSource('/api/stream');
  source.onmessage = (message) => {
    let data;
    try { data = JSON.parse(message.data); } catch { return; }
    if (data.type === 'event') {
      appendStream(data.event);
      if (data.event.type !== 'danmaku' || Math.random() < 0.25) {
        setTimeout(loadViewers, 800);
      } else if (state.viewers.size < 400) {
        patchViewer(data.viewer);
      }
    } else if (data.type === 'profile') {
      if (state.selectedUid === data.uid) selectViewer(data.uid);
      if (data.status === 'error') console.warn('画像失败', data.error);
    } else if (data.type === 'profile_status') {
      patchViewer({ ...(state.viewers.get(data.uid) || {}), uid: data.uid, profile_status: data.status });
    } else if (data.type === 'action') {
      // 别的窗口新记/删了一条操作，本窗口的色带与面板跟着更新
      loadActions().then(() => { if (state.densityChart) loadDensity(); });
      if ($('actions-modal').classList.contains('show')) loadActionMetrics();
    } else if (data.type === 'analysis') {
      // AI 分析（本场 / 生涯）异步生成，进度与结果都靠 SSE 回推
      if ($('analysis-modal').classList.contains('show') && data.kind === state.analysisKind) {
        if (data.status === 'running') {
          $('analysis-hint').textContent = 'AI 生成中…';
          $('btn-analysis-run').disabled = true;
          $('btn-analysis-run').textContent = '生成中…';
        } else if (data.status === 'done') {
          renderAnalysis({
            kind: data.kind,
            content: data.content,
            model: data.model,
            created_at: Date.now(),
            llm_enabled: true,
          });
        } else if (data.status === 'error') {
          $('analysis-hint').textContent = `生成失败：${data.error || '未知错误'}`;
          $('btn-analysis-run').disabled = false;
          $('btn-analysis-run').textContent = '重新生成';
        }
      }
    } else if (data.type === 'status') {
      setConn(data.connected, data.message || data.status_message);
    }
  };
  source.onerror = () => {
    setConn(false, '连接已断开');
    source.close();
    setTimeout(connectSSE, 3000);
  };
}

/* ------------------------------------------------------------------ 切换房间 */
async function toggleRooms() {
  const pop = $('rooms-pop');
  if (pop.classList.contains('show')) {
    pop.classList.remove('show');
    return;
  }
  pop.classList.add('show');
  pop.innerHTML = '<div class="room-empty">读取中…</div>';
  try {
    const data = await api('/api/rooms');
    renderRooms(data.items || []);
  } catch (err) {
    pop.innerHTML = `<div class="room-empty">读取失败：${esc(err.message)}</div>`;
  }
}

function renderRooms(items) {
  const pop = $('rooms-pop');
  if (!items.length) {
    pop.innerHTML = '<div class="room-empty">还没有已保存的房间</div>';
    return;
  }
  pop.innerHTML = items.map((r) => {
    const meta = `${r.viewers} 位观众`;
    const when = r.last_active ? ` · ${fmtDelta(r.last_active)}` : '';
    return `<button class="room-item${r.current ? ' current' : ''}" data-room="${r.room_id}">
      <span class="room-id">${r.room_id}${r.current ? ' · 当前' : ''}</span>
      <span class="room-meta">${meta}${when}</span>
    </button>`;
  }).join('');
  pop.querySelectorAll('.room-item').forEach((node) => {
    node.addEventListener('click', () => switchRoom(Number(node.dataset.room)));
  });
}

async function switchRoom(roomId) {
  const pop = $('rooms-pop');
  if (roomId === state.currentRoom) {
    pop.classList.remove('show');
    return;
  }
  pop.querySelectorAll('.room-item').forEach((n) => { n.disabled = true; });
  try {
    await api('/api/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ room_id: roomId }),
    });
    state.currentRoom = roomId;
    pop.classList.remove('show');
    setTimeout(() => { loadStats(); loadViewers(); }, 1200);
  } catch (err) {
    alert('切换失败：' + err.message);
    pop.querySelectorAll('.room-item').forEach((n) => { n.disabled = false; });
  }
}

/* ------------------------------------------------------------------ 扫码登录 */
const QRCODE_CDNS = [
  'https://cdn.jsdelivr.net/npm/qrcodejs@1.0.0/qrcode.min.js',
  'https://unpkg.com/qrcodejs@1.0.0/qrcode.min.js',
  'https://cdnjs.cloudflare.com/ajax/libs/qrcodejs/1.0.0/qrcode.min.js',
];
let qrcodePromise = null;
/* 依次尝试多个 CDN 加载二维码组件 */
function ensureQRCode() {
  if (window.QRCode) return Promise.resolve(window.QRCode);
  if (qrcodePromise) return qrcodePromise;
  qrcodePromise = new Promise((resolve, reject) => {
    let index = 0;
    const tryNext = () => {
      if (index >= QRCODE_CDNS.length) {
        qrcodePromise = null;
        reject(new Error('二维码组件加载失败'));
        return;
      }
      const script = document.createElement('script');
      script.src = QRCODE_CDNS[index++];
      script.onload = () => (window.QRCode ? resolve(window.QRCode) : tryNext());
      script.onerror = tryNext;
      document.head.appendChild(script);
    };
    tryNext();
  });
  return qrcodePromise;
}

const QR_IDLE_TEXT = '用 B 站手机 App 扫码，自动获取并保存完整 Cookie，无需手动复制';
let qrTimer = null;

function stopQrLogin() {
  if (qrTimer) {
    clearInterval(qrTimer);
    qrTimer = null;
  }
}

async function startQrLogin() {
  const box = $('qr-box');
  const status = $('qr-status');
  stopQrLogin();
  box.innerHTML = '';
  status.textContent = '正在获取二维码…';

  let data;
  try {
    data = await api('/api/login/qrcode');
  } catch (err) {
    status.textContent = '获取二维码失败：' + err.message;
    return;
  }
  if (!data.ok || !data.url) {
    status.textContent = '获取二维码失败：' + (data.error || '未知错误');
    return;
  }
  try {
    const QRCode = await ensureQRCode();
    new QRCode(box, { text: data.url, width: 168, height: 168 });
  } catch (err) {
    status.textContent = err.message + '，可改用下方手动粘贴 Cookie';
    return;
  }

  status.textContent = '请用 B 站手机 App 扫码';
  const key = data.qrcode_key;
  qrTimer = setInterval(async () => {
    let res;
    try {
      res = await api('/api/login/poll?key=' + encodeURIComponent(key));
    } catch (err) {
      return; // 网络抖动，下个周期再试
    }
    if (res.status === 'scanned') {
      status.textContent = '已扫码，请在手机上点击确认';
    } else if (res.status === 'expired') {
      status.textContent = '二维码已过期，请重新获取';
      stopQrLogin();
    } else if (res.status === 'confirmed') {
      stopQrLogin();
      box.innerHTML = '';
      status.textContent = `登录成功：${res.uname}，Cookie 已保存`;
      $('cfg-cookie-hint').textContent = `当前已登录：${res.uname}`;
      setTimeout(() => { loadStats(); loadViewers(); }, 1200);
    } else if (res.ok === false && res.error) {
      stopQrLogin();
      status.textContent = res.error;
    }
  }, 2000);
}

/* ------------------------------------------------------------------ 设置 */
// 解析房间号输入：支持纯数字与直播间链接（如 https://live.bilibili.com/1907444111）
function parseRoomInput(text) {
  const raw = (text || '').trim();
  if (!raw) return NaN; // 空表示未填写
  if (/^\d+$/.test(raw)) return Number(raw);
  const link = raw.match(/live\.bilibili\.com\/(?:blanc\/|h5\/|blackboard\/)?(\d+)/i);
  if (link) return Number(link[1]);
  const digits = raw.match(/(\d{3,})/);
  if (digits) return Number(digits[1]);
  return null;
}

function updateRoomHint() {
  const hint = $('cfg-room-hint');
  if (!hint) return;
  const parsed = parseRoomInput($('cfg-room').value);
  if (Number.isNaN(parsed)) {
    hint.textContent = '可填短号 / 真实房间号，也可直接粘贴直播间链接（如 https://live.bilibili.com/1907444111）；每个主播的数据单独存库';
  } else if (parsed === null) {
    hint.textContent = '无法识别，请填写数字或直播间链接';
  } else {
    hint.textContent = `已识别房间号：${parsed}（保存后自动切换，各主播数据单独存库）`;
  }
}

async function openSettings() {
  // 先把弹窗显示出来，再异步读取配置。
  // 否则配置接口一失败（比如程序没启动），点击就会毫无反应。
  $('settings-modal').classList.add('show');
  stopQrLogin();
  $('qr-box').innerHTML = '';
  $('qr-status').textContent = QR_IDLE_TEXT;
  $('cfg-key-hint').textContent = '正在读取配置…';

  let cfg;
  try {
    cfg = await api('/api/config');
  } catch (err) {
    $('cfg-key-hint').textContent =
      `读取配置失败：${err.message}。请确认程序正在运行且本页是从 http://127.0.0.1:8765/ 打开的。`;
    return;
  }

  $('cfg-room').value = cfg.room_id || '';
  updateRoomHint();
  $('cfg-llm-enabled').checked = !!cfg.llm_enabled;
  $('cfg-base-url').value = cfg.base_url || '';
  $('cfg-model').value = cfg.model || '';
  $('cfg-api-key').value = '';
  $('cfg-key-hint').textContent = cfg.api_key_set ? '当前已配置（留空则不修改）' : '当前未配置，画像将降级为本地规则';
  $('cfg-cookie').value = '';
  $('cfg-cookie-hint').textContent = cfg.cookie_set
    ? '当前已配置（留空则不修改）。Cookie 过期后可重新粘贴覆盖。'
    : '当前未配置，弹幕昵称会被 B 站打码成 *';
  $('cfg-auto').checked = !!cfg.auto;
}

async function saveSettings() {
  const button = $('btn-modal-save');
  // 支持直接粘贴直播间链接，这里先本地解析，解析不出来就不提交
  const parsedRoom = parseRoomInput($('cfg-room').value);
  if (parsedRoom === null) {
    alert('无法识别房间号，请填写数字或直播间链接（如 https://live.bilibili.com/1907444111）');
    return;
  }
  const roomValue = Number.isNaN(parsedRoom) ? 0 : parsedRoom;
  button.disabled = true;
  try {
    await api('/api/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        room_id: roomValue,
        llm_enabled: $('cfg-llm-enabled').checked,
        base_url: $('cfg-base-url').value.trim(),
        model: $('cfg-model').value.trim(),
        api_key: $('cfg-api-key').value.trim(),
        cookie: $('cfg-cookie').value.trim(),
        auto: $('cfg-auto').checked,
      }),
    });
    stopQrLogin();
    $('settings-modal').classList.remove('show');
    setTimeout(() => { loadStats(); loadViewers(); }, 1200);
  } catch (err) {
    alert('保存失败：' + err.message);
  } finally {
    button.disabled = false;
  }
}

/* ------------------------------------------------------------------ 主播生涯 */
function fmtDuration(ms) {
  const sec = Math.floor((ms || 0) / 1000);
  if (sec <= 0) return '0 分钟';
  const hour = Math.floor(sec / 3600);
  const minute = Math.floor((sec % 3600) / 60);
  if (hour) return `${hour} 小时 ${minute} 分`;
  if (minute) return `${minute} 分钟`;
  return `${sec} 秒`;
}

function fmtDay(ts) {
  if (!ts) return '--';
  const d = new Date(ts);
  const p = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

function careerHtml(d) {
  const groups = [
    ['场次与时间', [
      [d.sessions, '累计场次'],
      [d.days, '开播天数'],
      [fmtDuration(d.duration_ms), '累计开播时长'],
      [fmtDay(d.first_ts), '首次记录'],
    ]],
    ['观众', [
      [d.total_viewers, '观众库人数'],
      [d.active_viewers, '互动人数'],
    ]],
    ['互动', [
      [d.danmaku, '累计弹幕'],
      [d.guards, '累计上舰'],
    ]],
    ['收益', [
      ['¥' + (d.income ?? 0), '累计流水'],
      [d.payers, '付费人数'],
    ]],
  ];
  return groups
    .map(
      ([title, items]) => `
      <div class="career-group">
        <div class="career-group-title">${esc(title)}</div>
        <div class="career-grid">
          ${items
            .map(([v, l]) => `<div class="career-item"><b>${esc(v)}</b><span>${esc(l)}</span></div>`)
            .join('')}
        </div>
      </div>`
    )
    .join('');
}

async function openCareer() {
  // 与设置弹窗一致：先显示，再异步取数，避免接口慢或失败时点了没反应
  $('career-modal').classList.add('show');
  $('career-body').innerHTML = '<div class="chart-fallback">正在统计…</div>';
  try {
    $('career-body').innerHTML = careerHtml(await api('/api/career'));
  } catch (err) {
    $('career-body').innerHTML = `<div class="chart-fallback">读取失败：${esc(err.message)}</div>`;
  }
}

/* ------------------------------------------------------------------ AI 分析 */
async function openAnalysis() {
  // 与其它弹窗一致：先显示，再异步取缓存，避免点了没反应
  $('analysis-modal').classList.add('show');
  await loadAnalysis(state.analysisKind);
}

async function loadAnalysis(kind) {
  state.analysisKind = kind;
  document.querySelectorAll('#analysis-tabs .tab').forEach((node) => {
    node.classList.toggle('active', node.dataset.kind === kind);
  });
  $('analysis-body').innerHTML = '<div class="chart-fallback">正在读取…</div>';
  $('btn-analysis-run').disabled = false;
  let data;
  try {
    data = await api('/api/analysis?kind=' + encodeURIComponent(kind));
  } catch (err) {
    $('analysis-body').innerHTML =
      `<div class="chart-fallback">读取失败：${esc(err.message)}</div>`;
    $('analysis-hint').textContent = '';
    return;
  }
  renderAnalysis(data);
}

/* 判断一行是否是小节标题（【标题】、**标题**、#标题、短行+冒号、编号短标题） */
function asAnalysisHeader(line) {
  const text = line.replace(/^#{1,6}\s*/, '').replace(/\*\*/g, '').trim();
  const bracket = text.match(/^【(.{1,24})】$/);
  if (bracket) return bracket[1].trim();
  const colon = text.match(/^(.{2,20})[：:]$/);
  if (colon) return colon[1].trim();
  const num = text.match(/^(?:[一二三四五六七八九十]+[、.．)）]|\d+[、.．)）]|[（(]\d+[)）])\s*(.+)$/);
  if (num) {
    const body = num[1].trim();
    if (body.length <= 20 && !/[。！？；]/.test(body)) return body;
    return null;
  }
  if (text.length <= 12 && !/[。！？；，、：:,.]/.test(text) && !/^[·•\-–*]/.test(text)) return text;
  return null;
}

/* 判断一行是否是列表条目，返回去掉项目符号后的正文 */
function asAnalysisItem(line) {
  const match = line.match(/^[·•▪◦\-–—*]\s*(.+)$/)
    || line.match(/^[①-⑳]\s*(.+)$/)
    || line.match(/^(?:[一二三四五六七八九十]+[、.．)）]|\d+[、.．)）]|[（(]\d+[)）])\s*(.+)$/);
  return match ? match[1].trim() : null;
}

/* 把大模型输出的纯文本切成「小节 + 段落/条目」，避免整段糊在一起 */
function splitAnalysis(text) {
  const sections = [];
  let current = null;
  const openSection = (title) => {
    current = { title: title || '', blocks: [] };
    sections.push(current);
  };
  String(text || '').split(/\r?\n/).forEach((raw) => {
    const line = raw.trim();
    if (!line) return;
    // 「小标题：正文」写在同一行时，拆成小节标题 + 正文
    const inline = line.match(/^([^\s：:]{2,10})[：:]\s*(\S.*)$/);
    if (inline && !/[。！？；]/.test(inline[1])) {
      openSection(inline[1]);
      const rest = inline[2].trim();
      const restItem = asAnalysisItem(rest);
      current.blocks.push(restItem ? { kind: 'item', text: restItem } : { kind: 'p', text: rest });
      return;
    }
    const header = asAnalysisHeader(line);
    if (header) { openSection(header); return; }
    const item = asAnalysisItem(line);
    if (item) {
      if (!current) openSection('');
      current.blocks.push({ kind: 'item', text: item });
      return;
    }
    if (!current) openSection('');
    const last = current.blocks[current.blocks.length - 1];
    if (last && last.kind === 'p') last.text += ' ' + line;
    else current.blocks.push({ kind: 'p', text: line });
  });
  return sections.filter((s) => s.title || s.blocks.length);
}

function analysisHtml(text) {
  const sections = splitAnalysis(text);
  if (!sections.length) return `<pre class="analysis-text-plain">${esc(text)}</pre>`;
  return sections
    .map((section) => `
      <div class="an-sec">
        ${section.title ? `<div class="an-sec-title">${esc(section.title)}</div>` : ''}
        <div class="an-sec-body">
          ${section.blocks.map((b) => (b.kind === 'item'
            ? `<div class="an-item">${esc(b.text)}</div>`
            : `<p class="an-p">${esc(b.text)}</p>`)).join('')}
        </div>
      </div>`)
    .join('');
}

function renderAnalysis(data) {
  $('analysis-body').innerHTML = data.content
    ? `<div class="analysis-text">${analysisHtml(data.content)}</div>`
    : '<div class="chart-fallback">暂无分析，点右上角「生成分析」让 AI 总结。</div>';
  const parts = [];
  if (data.created_at) parts.push('生成于 ' + fmtFull(data.created_at));
  if (data.model) parts.push(data.model === 'rule' ? '本地规则' : `模型 ${data.model}`);
  if (!data.content) {
    parts.push(data.llm_enabled ? '尚未生成' : '未配置大模型，将用本地规则');
  }
  $('analysis-hint').textContent = parts.join(' · ');
  $('btn-analysis-run').disabled = false;
  $('btn-analysis-run').textContent = data.content ? '重新生成' : '生成分析';
}

async function runAnalysis() {
  const button = $('btn-analysis-run');
  button.disabled = true;
  button.textContent = '生成中…';
  $('analysis-hint').textContent = 'AI 生成中…';
  try {
    await api('/api/analysis', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ kind: state.analysisKind }),
    });
    // 结果与状态由 SSE 的 analysis 事件回推
  } catch (err) {
    button.disabled = false;
    button.textContent = '生成分析';
    $('analysis-hint').textContent = `发起失败：${err.message}`;
  }
}

/* ------------------------------------------------------------------ 启动 */
async function loadStats() {
  try { renderStats(await api('/api/stats')); } catch (err) { /* 忽略 */ }
}

/* ------------------------------------------------------------------ 拖拽调宽 */
const SPLIT_KEY = 'profileWidth';
const PROFILE_MIN = 300;   // 画像栏最小宽度
const STREAM_MIN = 320;    // 弹幕流最小宽度

function clampProfileWidth(width) {
  const layout = document.querySelector('.layout');
  // 减去 padding(24) + 观众栏(280) + 观众栏间距(12) + 分隔条(12)，剩余给弹幕流与画像栏
  const available = layout.clientWidth - 328;
  const max = Math.max(PROFILE_MIN, available - STREAM_MIN);
  return Math.round(Math.min(Math.max(width, PROFILE_MIN), max));
}

function setProfileWidth(width) {
  document.querySelector('.layout').style.setProperty('--profile-w', `${clampProfileWidth(width)}px`);
}

function initSplitter() {
  const layout = document.querySelector('.layout');
  const splitter = $('splitter');
  const panel = $('profile-panel');

  const saved = Number(localStorage.getItem(SPLIT_KEY));
  if (saved > 0) setProfileWidth(saved);

  let startX = 0;
  let startWidth = 0;

  const onMove = (e) => {
    setProfileWidth(startWidth - (e.clientX - startX));
  };

  const onUp = () => {
    splitter.classList.remove('dragging');
    document.body.classList.remove('resizing');
    window.removeEventListener('pointermove', onMove);
    window.removeEventListener('pointerup', onUp);
    window.removeEventListener('pointercancel', onUp);
    localStorage.setItem(SPLIT_KEY, String(Math.round(panel.getBoundingClientRect().width)));
  };

  // 用 Pointer Events + window 监听：鼠标移出分隔条甚至移出窗口也不会丢失拖动
  splitter.addEventListener('pointerdown', (e) => {
    e.preventDefault();
    startX = e.clientX;
    startWidth = panel.getBoundingClientRect().width;
    splitter.classList.add('dragging');
    document.body.classList.add('resizing');
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp);
    window.addEventListener('pointercancel', onUp);
  });

  // 双击分隔条恢复默认（两栏各占一半）
  splitter.addEventListener('dblclick', () => {
    localStorage.removeItem(SPLIT_KEY);
    layout.style.removeProperty('--profile-w');
  });

  window.addEventListener('resize', () => {
    if (layout.style.getPropertyValue('--profile-w')) {
      setProfileWidth(panel.getBoundingClientRect().width);
    }
  });
}

function bind() {
  $('search').addEventListener('input', (e) => {
    state.keyword = e.target.value.trim();
    state.viewerPage = 1;
    clearTimeout(bind._timer);
    bind._timer = setTimeout(loadViewers, 300);
  });
  $('sort-tabs').addEventListener('click', (e) => {
    const tab = e.target.closest('.tab');
    if (!tab) return;
    document.querySelectorAll('.tab').forEach((n) => n.classList.toggle('active', n === tab));
    state.sort = tab.dataset.sort;
    state.viewerPage = 1;
    loadViewers();
  });
  $('session-only').addEventListener('change', (e) => {
    state.sessionOnly = e.target.checked;
    state.viewerPage = 1;
    loadViewers();
  });
  $('viewer-list').addEventListener('click', (e) => {
    const node = e.target.closest('.viewer');
    if (node) selectViewer(Number(node.dataset.uid));
  });
  $('stream').addEventListener('click', (e) => {
    const name = e.target.closest('.name');
    if (name && name.dataset.uid) selectViewer(Number(name.dataset.uid));
  });
  $('btn-toggle-stream').addEventListener('click', () => {
    state.streamPaused = !state.streamPaused;
    $('btn-toggle-stream').textContent = state.streamPaused ? '继续' : '暂停';
    if (state.streamPaused) refreshStreamHint();
    else flushStream();
  });
  $('btn-clear-stream').addEventListener('click', () => {
    state.pendingLines = [];
    $('stream').innerHTML = '';
    refreshStreamHint();
  });
  // 弹幕流视图切换：全部 / 礼物流水
  $('stream-view-tabs').querySelectorAll('.tab').forEach((node) => {
    node.addEventListener('click', () => {
      state.streamView = node.dataset.view;
      applyStreamView();
    });
  });
  $('btn-rooms').addEventListener('click', (e) => { e.stopPropagation(); toggleRooms(); });
  document.addEventListener('click', (e) => {
    const pop = $('rooms-pop');
    if (pop.classList.contains('show') && !e.target.closest('.rooms-wrap')) {
      pop.classList.remove('show');
    }
  });
  $('btn-settings').addEventListener('click', openSettings);
  $('auto-profile').addEventListener('change', toggleAutoProfile);
  $('cfg-room').addEventListener('input', updateRoomHint);
  $('cfg-room').addEventListener('blur', updateRoomHint);
  $('btn-qr-login').addEventListener('click', startQrLogin);
  $('btn-modal-cancel').addEventListener('click', () => {
    stopQrLogin();
    $('settings-modal').classList.remove('show');
  });
  $('btn-modal-save').addEventListener('click', saveSettings);
  $('btn-career').addEventListener('click', openCareer);
  $('btn-career-close').addEventListener('click', () => $('career-modal').classList.remove('show'));
  // AI 分析：本场 / 生涯两个标签
  $('btn-analysis').addEventListener('click', openAnalysis);
  $('btn-analysis-close').addEventListener('click', () => $('analysis-modal').classList.remove('show'));
  $('btn-analysis-run').addEventListener('click', runAnalysis);
  $('analysis-tabs').addEventListener('click', (e) => {
    const tab = e.target.closest('.tab');
    if (tab) loadAnalysis(tab.dataset.kind);
  });
  // 操作记录：记录条 + 记录确认弹窗 + 记录/对比弹窗
  $('btn-actions').addEventListener('click', openActionsModal);
  $('btn-actions-close').addEventListener('click', () => $('actions-modal').classList.remove('show'));
  $('btn-action-cancel').addEventListener('click', closeActionModal);
  $('btn-action-save').addEventListener('click', saveAction);
  $('action-minutes').addEventListener('input', updateActionRange);
  $('btn-reconnect').addEventListener('click', async () => {
    await api('/api/reconnect', { method: 'POST' });
  });
  // 时间轴回看：按日期 / 小时切换历史弹幕
  $('tl-day').addEventListener('change', (e) => {
    const day = e.target.value;
    if (!day) {
      backToLive();
      return;
    }
    state.historyDay = day;
    state.historyHour = '';
    renderHourSelect();
    if (state.historyHour) enterHistory(state.historyDay, state.historyHour, 1);
  });
  $('tl-hour').addEventListener('change', (e) => {
    if (state.historyDay && e.target.value) enterHistory(state.historyDay, e.target.value, 1);
  });
  $('btn-back-live').addEventListener('click', backToLive);
  // 顶部密度曲线：切换指标
  $('density-tabs').addEventListener('click', (e) => {
    const tab = e.target.closest('.tab');
    if (!tab) return;
    $('density-tabs').querySelectorAll('.tab').forEach((n) => n.classList.toggle('active', n === tab));
    state.densityMetric = tab.dataset.metric;
    loadDensity();
  });
}

async function init() {
  bind();
  initSplitter();
  applyStreamView();
  await loadTopics();   // 先拿词库，保证首屏弹幕就能高亮
  await loadRoles();    // 身份标记：保证首屏弹幕就带标签
  connectSSE();
  await loadStats();
  await loadViewers();
  await loadTimeline();
  await loadActions();  // 操作记录条 + 密度曲线色带所需的轻量数据
  setInterval(() => { if (!state.streamPaused) loadStats(); }, 10000);
  setInterval(loadViewers, 30000);
  // 顶部密度曲线：懒加载 ECharts 后初始化，并每 5 秒滚动刷新
  ensureECharts()
    .then(() => {
      mountDensityChart();
      return loadDensity();
    })
    .catch(() => {
      const el = $('density-chart');
      if (el) el.outerHTML = '<div class="chart-fallback">图表库加载失败（ECharts CDN 不可达）</div>';
    });
  state.densityTimer = setInterval(() => { if (state.densityChart) loadDensity(); }, 5000);
}

init();

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
  // 图表
  densityMetric: 'danmaku',  // 顶部密度曲线当前指标
  densityChart: null,
  densityTimer: null,
  userHourChart: null,       // 概览页：活跃时段分布
  userTrendChart: null,      // 概览页：时间趋势
  // 热门元素库
  topicRe: null,             // 弹幕高亮用：所有别名合成的正则
  topicMap: null,            // 别名（小写）-> 词条
};

const BEHAVIOR_PAGE_SIZE = 100;

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
  $('room-line').textContent = `直播间 ${data.room_id || '--'} · 累计观众库 ${data.total_viewers ?? 0} 人`;
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
      series: series.map((s) => ({
        name: s.name,
        type: 'line',
        smooth: true,
        showSymbol: false,
        lineStyle: { width: 1.6, color: s.color },
        itemStyle: { color: s.color },
        areaStyle: { opacity: series.length === 1 ? 0.18 : 0.12, color: s.color },
        data: s.points,
      })),
    },
    true
  );
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

function tabMessagesHtml(events, total) {
  if (!events.length) return `<div class="section" style="border-bottom:none"><p class="muted-note">TA 还没有发过言</p></div>`;
  const suffix = total && total > events.length ? ` / ${total}` : '';
  return `<div class="section" style="border-bottom:none">
    <h4>最近发言（${events.length}${suffix}）</h4>
    ${events.map((m) => `<div class="mini-msg"><span class="t">${fmtTime(m.ts)}</span><span>${esc(m.content)}</span></div>`).join('')}
  </div>`;
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
  if (tab === 'messages') return tabMessagesHtml(events.filter((e) => e.type === 'danmaku'), 0);
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
  return `
    <div class="section">
      <h4>活跃分布</h4>
      <div class="mini-stats">
        <span class="mini-stat">发言 ${viewer.msg_count}</span>
        <span class="mini-stat">进场 ${viewer.enter_count}</span>
        <span class="mini-stat">付费 ${viewer.spend_count || 0} 次</span>
        <span class="mini-stat">礼物 ¥${viewer.gift_value}</span>
        <span class="mini-stat">活跃 ${spanDays} 天</span>
        <span class="mini-stat">日均 ${avgPerDay} 条</span>
      </div>
      <div class="chart-box tall" id="user-hour-chart"></div>
      <div class="chart-box tall" id="user-trend-chart"></div>
      <p class="muted-note" id="user-chart-hint" style="margin-top:4px"></p>
    </div>
    ${topicChipsHtml(metrics)}
    <div class="section">
      <h4>行为数据</h4>
      <div class="metric-grid">
        <div class="metric"><b>${viewer.msg_count}</b><span>弹幕总数</span></div>
        <div class="metric"><b>${viewer.enter_count}</b><span>进场次数</span></div>
        <div class="metric"><b>¥${viewer.gift_value}</b><span>实际消费(记录)</span></div>
        <div class="metric"><b>${viewer.follow_count || 0}</b><span>关注次数</span></div>
        <div class="metric"><b>${viewer.like_count || 0}</b><span>点赞次数</span></div>
        <div class="metric"><b>${viewer.spend_count || 0}</b><span>付费次数</span></div>
      </div>
    </div>
    <div class="section">
      <h4>时间</h4>
      <div class="kv"><span>首次出现</span><span>${esc(metrics['首次出现'])}</span></div>
      <div class="kv"><span>最近出现</span><span>${esc(metrics['最近出现'])}</span></div>
      <div class="kv"><span>最后活跃</span><span>${fmtFull(viewer.last_seen)}</span></div>
      <div class="kv"><span>关注时长</span><span>${esc(metrics['关注时长'])}</span></div>
    </div>
    <div class="section" style="border-bottom:none">
      <h4>身份与偏好</h4>
      <div class="kv"><span>舰长等级</span><span>${esc(metrics['舰长等级'])}</span></div>
      <div class="kv"><span>粉丝牌</span><span>${esc(metrics['粉丝牌名称'] || '-')} Lv${metrics['粉丝牌等级'] || 0}</span></div>
      <div class="kv"><span>粉丝牌折算(估)</span><span>${esc(metrics['粉丝牌折算消费(估)'] || (metrics['粉丝牌等级'] ? '-' : '无牌子'))}</span></div>
      <div class="kv"><span>关注过主播</span><span>${metrics['关注过主播'] ? '是' : '否'}</span></div>
      <div class="kv"><span>情绪倾向(规则)</span><span>${esc(metrics['情绪倾向(规则)'])}</span></div>
      <div class="kv"><span>高频词(规则)</span><span>${esc((metrics['高频词(规则)'] || []).join(' ')) || '-'}</span></div>
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
      ${profile.location ? `<div class="kv"><span>常驻地点</span><span>${esc(profile.location)}</span></div>` : ''}
      ${profile.active_hours ? `<div class="kv"><span>活跃时段</span><span>${esc(profile.active_hours)}</span></div>` : ''}
    </div>`;
  }
  if (lifeRows.length) {
    html += `<div class="section">
      <h4>生活状态</h4>
      ${lifeRows.map(([k, v]) => `<div class="kv"><span>${k}</span><span>${esc(v)}</span></div>`).join('')}
      <p class="muted-note" style="margin-top:6px">仅整理观众本人在直播间公开说过的信息。</p>
    </div>`;
  }
  if (favRows.length) {
    html += `<div class="section">
      <h4>具体偏好</h4>
      ${favRows.map(([k, list]) => `<div class="kv"><span>${k}</span><span>${list.map(esc).join(' / ')}</span></div>`).join('')}
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
      <div class="kv"><span>记忆点</span><span>${esc(profile.nickname_hint || '-')}</span></div>
      <div class="kv"><span>人设</span><span>${esc(profile.persona || '-')}</span></div>
      <div class="kv"><span>关系</span><span>${esc(profile.relationship || '-')}</span></div>
      <div class="kv"><span>当前情绪</span><span>${esc(profile.mood_now || '-')}</span></div>
      <div class="kv"><span>活跃/消费</span><span>${esc(profile.activity_level || '-')} / ${esc(profile.value_level || '-')}</span></div>
      <div class="kv"><span>一句话记住</span><span>${esc(profile.memory_hook || '-')}</span></div>
      <div class="tag-row">${(profile.tags || []).map((t) => `<span class="tag">${esc(t)}</span>`).join('')}</div>
      <div class="kv" style="margin-top:8px"><span>兴趣点</span><span>${esc((profile.interests || []).join(' ')) || '-'}</span></div>
    </div>
    ${profileExtrasHtml(profile)}
    <div class="section">
      <h4>应对方法</h4>
      <ul class="strategy">${(profile.response_strategy || []).map((s) => `<li>${esc(s)}</li>`).join('') || '<li>暂无</li>'}</ul>
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

/* 「发言」分类单独拉取（只取弹幕），避免混入进场等事件 */
async function loadMessages(uid) {
  try {
    const data = await api(`/api/viewers/${uid}?types=danmaku&limit=60`);
    if (state.selectedUid !== uid || state.profileTab !== 'messages') return;
    $('profile-body').innerHTML = tabMessagesHtml(data.events || [], data.total || 0);
  } catch (err) {
    console.error('加载发言失败', err);
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
}

function switchProfileTab(tab) {
  state.profileTab = tab;
  const panel = $('profile-panel');
  panel.querySelectorAll('.ptab').forEach((n) => n.classList.toggle('active', n.dataset.tab === tab));
  $('profile-body').innerHTML = tabHtml(tab, state.detail);
  bindTabContent(tab, state.detail);
  if (tab === 'messages' && state.detail) loadMessages(state.detail.viewer.uid);
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
  if (tab === 'messages') loadMessages(viewer.uid);
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

/* ------------------------------------------------------------------ 设置 */
async function openSettings() {
  // 先把弹窗显示出来，再异步读取配置。
  // 否则配置接口一失败（比如程序没启动），点击就会毫无反应。
  $('settings-modal').classList.add('show');
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
  button.disabled = true;
  try {
    await api('/api/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        room_id: $('cfg-room').value.trim() || 0,
        llm_enabled: $('cfg-llm-enabled').checked,
        base_url: $('cfg-base-url').value.trim(),
        model: $('cfg-model').value.trim(),
        api_key: $('cfg-api-key').value.trim(),
        cookie: $('cfg-cookie').value.trim(),
        auto: $('cfg-auto').checked,
      }),
    });
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
  $('btn-settings').addEventListener('click', openSettings);
  $('btn-modal-cancel').addEventListener('click', () => $('settings-modal').classList.remove('show'));
  $('btn-modal-save').addEventListener('click', saveSettings);
  $('btn-career').addEventListener('click', openCareer);
  $('btn-career-close').addEventListener('click', () => $('career-modal').classList.remove('show'));
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

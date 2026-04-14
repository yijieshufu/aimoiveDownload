<script setup>
import { computed, onBeforeUnmount, onMounted, ref, nextTick, watch } from 'vue';
import { Sparkles, Copy, User, Bot } from 'lucide-vue-next';
import { useMagnetic } from './composables/useMagnetic';
import {
  apiAbsolute,
  apiDeleteNotesEdit,
  apiDownload,
  apiDownloadFileUrl,
  apiExtract,
  apiMe,
  apiLogout,
  apiBillingCreateWeChatpay,
  apiBillingCreateAlipay,
  apiBillingMockMarkPaid,
  apiGetMindmap,
  apiGetNotesEdit,
  apiGetTabs,
  apiSaveMindmap,
  apiSaveNotesEdit,
  apiSummarize,
  apiSummarizeStreamCreate,
  apiSummarizeStreamUrl,
  apiSummarizeChat,
  apiSummarizeStatus,
  apiTranslateSummary,
  apiGetSubtitles,
  apiSubtitleDownloadUrl,
  apiOptimizeTranscript,
} from './api/index.js';
import { marked } from 'marked';
import DOMPurify from 'dompurify';
import MindmapFlow from './components/MindmapFlow.vue';
import AppHeader from './components/AppHeader.vue';
import HeroSection from './components/HeroSection.vue';
import VideoUrlBar from './components/VideoUrlBar.vue';
import VideoResultPanel from './components/VideoResultPanel.vue';
import UpgradeModal from './components/UpgradeModal.vue';

marked.setOptions({ gfm: true, breaks: true });

function shouldOpenUpgradeModal(err) {
  const s = err && typeof err.status === 'number' ? err.status : 0;
  if (s === 402 || s === 401) return true;
  if (s === 403) {
    const msg = String(err?.message || '');
    return /pro|专享|premium/i.test(msg);
  }
  return false;
}

function extractFirstUrl(input) {
  const s = String(input || '').trim();
  if (!s) return '';
  const stripTail = (u) => String(u || '').trim().replace(/[)\],.;:!?}"'>，。！？；：、】）》）】>]+$/g, '');
  if (/^https?:\/\//i.test(s)) return stripTail(s);
  const m = s.match(/https?:\/\/[^\s"'<>]+/i);
  if (m && m[0]) return stripTail(m[0]);
  const m2 = s.match(/\b(v\.douyin\.com\/[A-Za-z0-9]+)\b/i);
  if (m2 && m2[1]) return `https://${m2[1]}`;
  return '';
}

function formatDuration(seconds) {
  const totalSeconds = Math.max(0, Math.floor(Number(seconds) || 0));
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const remainingSeconds = totalSeconds % 60;
  if (hours > 0) return `${hours}:${String(minutes).padStart(2, '0')}:${String(remainingSeconds).padStart(2, '0')}`;
  return `${minutes}:${String(remainingSeconds).padStart(2, '0')}`;
}

function formatTs(seconds) {
  return formatDuration(seconds);
}

function formatViews(views) {
  const v = Number(views || 0);
  if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`;
  if (v >= 1_000) return `${(v / 1_000).toFixed(1)}K`;
  return String(v || 0);
}

function formatFileSize(bytes) {
  const b = Number(bytes || 0);
  if (b >= 1024 ** 3) return `${(b / 1024 ** 3).toFixed(2)} GB`;
  if (b >= 1024 ** 2) return `${(b / 1024 ** 2).toFixed(2)} MB`;
  if (b >= 1024) return `${(b / 1024).toFixed(2)} KB`;
  return `${b} B`;
}

/** 将模型偶发的 JSON（如 {"回答":[...]}）转为可读纯文本 */
function stripAssistantCodeFence(s) {
  let t = String(s || '').trim();
  const m = t.match(/^```(?:json)?\s*([\s\S]*?)```$/i);
  if (m) return m[1].trim();
  return t;
}

function normalizeChatAssistantText(raw) {
  const text = stripAssistantCodeFence(String(raw || '').trim());
  if (!text) return '';
  try {
    const obj = JSON.parse(text);
    if (Array.isArray(obj)) {
      return obj
        .map((x, i) => `${i + 1}. ${String(x).trim()}`)
        .filter((line) => !/^\d+\.\s*$/.test(line))
        .join('\n');
    }
    if (obj && typeof obj === 'object') {
      const keys = ['回答', 'answer', 'reply', 'content', 'response', 'text'];
      for (const k of keys) {
        if (!(k in obj)) continue;
        const v = obj[k];
        if (Array.isArray(v)) {
          return v
            .map((x, i) => `${i + 1}. ${String(x).trim()}`)
            .filter((line) => !/^\d+\.\s*$/.test(line))
            .join('\n');
        }
        if (typeof v === 'string' && v.trim()) return v.trim();
      }
    }
  } catch {
    /* 非 JSON，沿用原文 */
  }
  return text;
}

function scrollQaChatToBottom() {
  const el = qaChatScrollRef.value;
  if (!el) return;
  el.scrollTop = el.scrollHeight;
}

function humanizeQaError(e) {
  const msg = String(e?.message || e || '').trim();
  const status = Number(e?.status || 0) || 0;

  if (msg.toLowerCase().includes('failed to fetch')) {
    return '问答失败：后端不可达（可能已重启或未启动）。请确认后端在 8003 端口运行；若你刚重启过后端，请重新做一次视频总结后再问答。';
  }
  if (status === 400 && (msg.includes('任务不存在') || (msg.toLowerCase().includes('task') && msg.toLowerCase().includes('not')))) {
    return '问答失败：当前总结任务已失效（后端重启会清空内存任务）。请重新做一次视频总结，然后再进行问答。';
  }
  if (status) return `问答失败（HTTP ${status}）：${msg || '请求失败'}`;
  return `问答失败：${msg || '请求失败'}`;
}

const inputText = ref('');
const resolvedUrl = ref('');
const lastResolvedInput = ref('');
const isExtracting = ref(false);
const isVideoDownloading = ref(false);
const extractError = ref('');
const videoInfo = ref(null);
const activeTab = ref('summary');
const tabs = ref([]);

const isSummarizing = ref(false);
const notesTaskId = ref('');
const notesStage = ref('');
const notesProgress = ref(0);
const notesProgressText = ref('未开始');
const notesError = ref('');
const notesResult = ref(null);
const streamBuffer = ref('');
const streamState = ref('idle'); // idle | connecting | streaming | finalizing | polling_fallback | completed | failed
const streamErrorDetail = ref('');

function escapeHtml(s) {
  return String(s || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/** 流式 Markdown → 安全 HTML（AI笔记 Tab 实时排版） */
const streamNotesHtml = computed(() => {
  const raw = streamBuffer.value || '';
  if (!String(raw).trim()) return '';
  try {
    const html = marked.parse(raw, { async: false });
    if (html && typeof html.then === 'function') return '';
    return DOMPurify.sanitize(html);
  } catch {
    return DOMPurify.sanitize(
      `<pre class="whitespace-pre-wrap text-[13px] leading-relaxed">${escapeHtml(raw)}</pre>`
    );
  }
});

const subtitleSegments = ref([]);
const subtitleSource = ref('');
const transcriptExpanded = ref(false);
const transcriptOptimizing = ref(false);
const transcriptShowOptimized = ref(false);

const qaQuestion = ref('');
const qaErrorBanner = ref('');
const qaLoading = ref(false);
const qaMessages = ref([]);
const qaChatScrollRef = ref(null);
const streamNotesScrollRef = ref(null);
const translatingNotes = ref(false);
const mindmapSavingText = ref('');
let saveMindmapTimer = null;
let liveStatusProbeToken = 0;
const mindmapData = ref({ title: '视频主题', children: [] });

const noteEditSections = ref({ overview: [], outline: [], key_points: [], one_liner: '' });
const noteEditLoaded = ref(false);
const noteEditMode = ref(false);
const noteEditSavingText = ref('');
let saveNoteTimer = null;

const upgradeModalOpen = ref(false);
const me = ref(null);
const isPro = computed(() => {
  const plan = String(me.value?.plan || me.value?.subscription?.plan || '').toLowerCase();
  return plan === 'pro' || plan === 'premium';
});

const usageHint = computed(() => {
  const h = me.value?.usage?.hint;
  return typeof h === 'string' && h.trim() ? h.trim() : '';
});
const billingState = ref({ loading: false, error: '', lastOrder: null });

async function refreshMe() {
  try {
    me.value = await apiMe();
  } catch {
    me.value = null;
  }
}

function oauthLogin(provider) {
  const p = String(provider || '').trim().toLowerCase();
  if (!p) return;
  const next = '/frontend/';
  window.location.href = `/api/auth/login/${encodeURIComponent(p)}?next=${encodeURIComponent(next)}`;
}

async function doLogout() {
  try {
    await apiLogout();
  } finally {
    await refreshMe();
  }
}

async function createOrder(channel) {
  billingState.value = { loading: true, error: '', lastOrder: null };
  try {
    const title = '升级 Pro（月度）';
    const amount = 1999;
    const resp = channel === 'alipay' ? await apiBillingCreateAlipay(amount, title) : await apiBillingCreateWeChatpay(amount, title);
    billingState.value = { loading: false, error: '', lastOrder: resp };
  } catch (e) {
    billingState.value = { loading: false, error: String(e?.message || e), lastOrder: null };
  }
}

async function mockMarkPaid() {
  const oid = billingState.value?.lastOrder?.order_id;
  if (!oid) return;
  billingState.value = { ...billingState.value, loading: true, error: '' };
  try {
    await apiBillingMockMarkPaid(oid);
    billingState.value = { ...billingState.value, loading: false };
    await refreshMe();
  } catch (e) {
    billingState.value = { ...billingState.value, loading: false, error: String(e?.message || e) };
  }
}

const notesDownloadUrl = computed(() => {
  const u = notesResult.value?.markdown_download_url;
  return apiAbsolute(u);
});

const notesSectionsVisible = ref(false);

/** 长笔记折叠：超过条数后默认收起，点击展开 */
const SUMMARY_COLLAPSE = { overviewAfter: 3, overviewShow: 2, outlineAfter: 4, outlineShow: 3, keyPointsAfter: 4, keyPointsShow: 4 };
const notesBlockExpand = ref({ overview: false, outline: false, keyPoints: false });

useMagnetic('[data-magnetic]', { strength: 10, maxTranslate: 10 });

const notesBlocks = computed(() => {
  const s = notesResult.value?.note_sections || notesResult.value?.summary_sections || {};
  const arr = notesResult.value?.summary || [];
  const overview = Array.isArray(s.overview) && s.overview.length ? s.overview : arr.slice(0, 2);
  const outline = Array.isArray(s.outline) && s.outline.length ? s.outline : (notesResult.value?.chapters || []).slice(0, 5).map((c) => c.title).filter(Boolean);
  const keyPoints = Array.isArray(s.key_takeaways) && s.key_takeaways.length
    ? s.key_takeaways
    : (Array.isArray(s.key_points) && s.key_points.length ? s.key_points : (arr.slice(2, 8).length ? arr.slice(2, 8) : arr.slice(0, 6)));
  const oneLiner = s.one_liner || arr[0] || '';
  return { overview, outline, keyPoints, oneLiner };
});

const effectiveNotesParts = computed(() => {
  if (!notesResult.value) {
    return { overview: [], outline: [], keyPoints: [], oneLiner: '' };
  }
  if (!noteEditLoaded.value) {
    const b = notesBlocks.value;
    return {
      overview: b.overview,
      outline: b.outline,
      keyPoints: b.keyPoints,
      oneLiner: b.oneLiner,
    };
  }
  const s = noteEditSections.value;
  return {
    overview: Array.isArray(s.overview) ? [...s.overview] : [],
    outline: Array.isArray(s.outline) ? [...s.outline] : [],
    keyPoints: Array.isArray(s.key_points) ? [...s.key_points] : [],
    oneLiner: s.one_liner || '',
  };
});

const notesIsEmpty = computed(() => {
  const p = effectiveNotesParts.value;
  return (
    (!p.overview || p.overview.length === 0) &&
    (!p.outline || p.outline.length === 0) &&
    (!p.keyPoints || p.keyPoints.length === 0) &&
    !String(p.oneLiner || '').trim()
  );
});

watch(
  () => notesTaskId.value,
  () => {
    notesBlockExpand.value = { overview: false, outline: false, keyPoints: false };
  }
);

const outlineRowsWithTime = computed(() => {
  if (!notesResult.value) return [];
  const titles = effectiveNotesParts.value.outline || [];
  const chapters = notesResult.value.chapters || [];
  return titles.map((title, i) => {
    const t = String(title || '').trim();
    let startSec = null;
    const ch = chapters[i];
    if (ch && String(ch.title || '').trim() === t) {
      const n = Number(ch.start);
      startSec = Number.isFinite(n) ? n : null;
    } else {
      const found = chapters.find((c) => String(c.title || '').trim() === t);
      if (found) {
        const n = Number(found.start);
        startSec = Number.isFinite(n) ? n : null;
      }
    }
    return { title, startSec };
  });
});

const overviewDisplay = computed(() => {
  const full = effectiveNotesParts.value.overview || [];
  const { overviewAfter, overviewShow } = SUMMARY_COLLAPSE;
  if (noteEditMode.value || full.length <= overviewAfter) {
    return { items: full, showToggle: false, expanded: true };
  }
  const ex = notesBlockExpand.value.overview;
  if (ex) return { items: full, showToggle: true, expanded: true };
  return { items: full.slice(0, overviewShow), showToggle: true, expanded: false, restCount: full.length - overviewShow };
});

const outlineDisplay = computed(() => {
  const rows = outlineRowsWithTime.value;
  const { outlineAfter, outlineShow } = SUMMARY_COLLAPSE;
  if (noteEditMode.value || rows.length <= outlineAfter) {
    return { rows, showToggle: false, expanded: true };
  }
  const ex = notesBlockExpand.value.outline;
  if (ex) return { rows, showToggle: true, expanded: true };
  return { rows: rows.slice(0, outlineShow), showToggle: true, expanded: false, restCount: rows.length - outlineShow };
});

const keyPointsDisplay = computed(() => {
  const full = effectiveNotesParts.value.keyPoints || [];
  const { keyPointsAfter, keyPointsShow } = SUMMARY_COLLAPSE;
  if (noteEditMode.value || full.length <= keyPointsAfter) {
    return { items: full, showToggle: false, expanded: true };
  }
  const ex = notesBlockExpand.value.keyPoints;
  if (ex) return { items: full, showToggle: true, expanded: true };
  return { items: full.slice(0, keyPointsShow), showToggle: true, expanded: false, restCount: full.length - keyPointsShow };
});

const notesMarkdownText = computed(() => buildFullNotesText());
const notesMarkdownHtml = computed(() => {
  const raw = String(notesMarkdownText.value || '').trim();
  if (!raw) return '';
  try {
    const html = marked.parse(raw, { async: false });
    if (html && typeof html.then === 'function') return '';
    return DOMPurify.sanitize(html);
  } catch {
    return DOMPurify.sanitize(`<pre class="whitespace-pre-wrap text-[13px] leading-relaxed">${escapeHtml(raw)}</pre>`);
  }
});

function normalizeInlineText(value) {
  return String(value || '').replace(/\s+/g, ' ').trim();
}

function sanitizeNoteCardTitle(value) {
  let text = normalizeInlineText(value)
    .replace(/https?:\/\/\S+/gi, ' ')
    .replace(/复制此链接.*$/i, ' ')
    .replace(/#([^\s#]+)/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
  if (!text) return '';
  return text.slice(0, 34).trim();
}

function dedupeNoteLines(items, limit = 6) {
  const out = [];
  const seen = new Set();
  for (const item of items || []) {
    const text = normalizeInlineText(item);
    const key = text.replace(/\s+/g, '').toLowerCase();
    if (!text || seen.has(key)) continue;
    seen.add(key);
    out.push(text);
    if (out.length >= limit) break;
  }
  return out;
}

function collectChapterFallbackPoints(chapter, nextChapterStart) {
  const highlights = notesResult.value?.highlights || [];
  const start = Number(chapter?.start);
  const end =
    Number.isFinite(Number(chapter?.end)) && Number(chapter?.end) > start
      ? Number(chapter.end)
      : Number.isFinite(Number(nextChapterStart))
        ? Number(nextChapterStart)
        : Infinity;

  return dedupeNoteLines(
    highlights
      .filter((h) => {
        const ts = Number(h?.ts);
        return Number.isFinite(ts) && ts >= start && ts < end;
      })
      .map((h) => h.text),
    5
  );
}

const noteCardTitle = computed(() => {
  const title = sanitizeNoteCardTitle(notesResult.value?.title || '');
  if (title) return title;
  const oneLiner = sanitizeNoteCardTitle(effectiveNotesParts.value.oneLiner || '');
  if (oneLiner) return oneLiner;
  return 'AI 笔记';
});

const noteCardSummary = computed(() => {
  const parts = effectiveNotesParts.value;
  const lines = dedupeNoteLines([parts.oneLiner, ...(parts.overview || [])], 2);
  return lines.join(' ');
});

const noteCardSections = computed(() => {
  const chapters = notesResult.value?.chapters || [];
  if (chapters.length) {
    return chapters
      .map((chapter, index) => {
        const currentPoints = dedupeNoteLines(chapter?.points || [], 5);
        const nextStart = chapters[index + 1]?.start;
        const fallbackPoints = currentPoints.length ? [] : collectChapterFallbackPoints(chapter, nextStart);
        const points = currentPoints.length ? currentPoints : fallbackPoints;
        const lead = points.length >= 3 ? points[0] : '';
        const items = lead ? points.slice(1) : points;
        return {
          title: normalizeInlineText(chapter?.title || ''),
          start: Number.isFinite(Number(chapter?.start)) ? Number(chapter.start) : 0,
          lead,
          items,
        };
      })
      .filter((section) => section.title || section.lead || section.items.length);
  }

  const parts = effectiveNotesParts.value;
  const fallback = [];
  const overview = dedupeNoteLines(parts.overview || [], 4);
  if (overview.length) {
    fallback.push({
      title: '核心结论',
      start: 0,
      lead: overview[0] || '',
      items: overview.slice(1),
    });
  }
  const keyPoints = dedupeNoteLines(parts.keyPoints || [], 5);
  if (keyPoints.length) {
    fallback.push({
      title: '关键要点',
      start: 0,
      lead: '',
      items: keyPoints,
    });
  }
  return fallback;
});

function defaultNoteSectionsFromResult() {
  const res = notesResult.value;
  if (!res) {
    return { overview: [], outline: [], key_points: [], one_liner: '' };
  }
  const s = res.note_sections || res.summary_sections || {};
  const arr = res.summary || [];
  const overview = Array.isArray(s.overview) && s.overview.length ? [...s.overview] : [...arr.slice(0, 2)];
  const outline =
    Array.isArray(s.outline) && s.outline.length
      ? [...s.outline]
      : (res.chapters || []).slice(0, 5).map((c) => c.title).filter(Boolean);
  const key_points =
    Array.isArray(s.key_points) && s.key_points.length
      ? [...s.key_points]
      : (arr.slice(2, 8).length ? [...arr.slice(2, 8)] : [...arr.slice(0, 6)]);
  const one_liner = s.one_liner || arr[0] || '';
  return { overview, outline, key_points, one_liner };
}

function normalizeNoteSections(sec) {
  if (!sec || typeof sec !== 'object') {
    return { overview: [], outline: [], key_points: [], one_liner: '' };
  }
  return {
    overview: Array.isArray(sec.overview) ? sec.overview.map((x) => String(x)) : [],
    outline: Array.isArray(sec.outline) ? sec.outline.map((x) => String(x)) : [],
    key_points: Array.isArray(sec.key_points) ? sec.key_points.map((x) => String(x)) : [],
    one_liner: String(sec.one_liner || ''),
  };
}

async function loadNotesEdit() {
  const tid = notesTaskId.value;
  if (!tid || !notesResult.value) {
    noteEditLoaded.value = false;
    return;
  }
  try {
    const data = await apiGetNotesEdit(tid);
    if (data.note_sections || data.sections) {
      const source = data.note_sections
        ? {
            overview: data.note_sections.overview || [],
            outline: data.note_sections.outline || [],
            key_points: data.note_sections.key_takeaways || [],
            one_liner: data.note_sections.one_liner || '',
          }
        : data.sections;
      noteEditSections.value = normalizeNoteSections(source);
    } else {
      noteEditSections.value = defaultNoteSectionsFromResult();
    }
  } catch {
    noteEditSections.value = defaultNoteSectionsFromResult();
  }
  noteEditLoaded.value = true;
}

function scheduleNoteSave() {
  if (!notesTaskId.value) return;
  if (saveNoteTimer) clearTimeout(saveNoteTimer);
  noteEditSavingText.value = '保存中…';
  saveNoteTimer = setTimeout(async () => {
    try {
      await apiSaveNotesEdit(notesTaskId.value, {
        overview: noteEditSections.value.overview || [],
        outline: noteEditSections.value.outline || [],
        key_takeaways: noteEditSections.value.key_points || [],
        one_liner: noteEditSections.value.one_liner || '',
      });
      noteEditSavingText.value = '已保存';
      setTimeout(() => {
        if (noteEditSavingText.value === '已保存') noteEditSavingText.value = '';
      }, 1200);
    } catch {
      noteEditSavingText.value = '保存失败';
    }
  }, 600);
}

function onNoteOverviewInput(e) {
  noteEditSections.value.overview = e.target.value.split('\n').map((l) => l.trim()).filter(Boolean);
  scheduleNoteSave();
}
function onNoteOutlineInput(e) {
  noteEditSections.value.outline = e.target.value.split('\n').map((l) => l.trim()).filter(Boolean);
  scheduleNoteSave();
}
function onNoteKeyPointsInput(e) {
  noteEditSections.value.key_points = e.target.value.split('\n').map((l) => l.trim()).filter(Boolean);
  scheduleNoteSave();
}
function onNoteOneLinerInput(e) {
  noteEditSections.value.one_liner = String(e.target.value || '').slice(0, 2000);
  scheduleNoteSave();
}

function markdownToNoteSections(md) {
  const lines = String(md || '').replace(/\r\n/g, '\n').split('\n');
  const out = { overview: [], outline: [], key_points: [], one_liner: '' };
  let section = '';
  const pushLine = (target, text) => {
    const t = String(text || '').trim();
    if (!t) return;
    target.push(t);
  };
  for (let i = 0; i < lines.length; i++) {
    const raw = lines[i];
    const line = String(raw || '').trim();
    if (!line) continue;
    if (/^#\s*一句话总结\b/.test(line)) {
      section = 'one_liner';
      continue;
    }
    if (/^##\s*概述\b/.test(line)) {
      section = 'overview';
      continue;
    }
    if (/^##\s*内容大纲\b/.test(line)) {
      section = 'outline';
      continue;
    }
    if (/^##\s*核心(知识)?(要点|内容)\b/.test(line)) {
      section = 'key_points';
      continue;
    }
    if (section === 'one_liner') {
      if (!out.one_liner) out.one_liner = line.replace(/^[-*]\s+/, '').replace(/^\d+\.\s+/, '');
      continue;
    }
    if (section === 'overview') {
      pushLine(out.overview, line.replace(/^[-*]\s+/, '').replace(/^\d+\.\s+/, ''));
      continue;
    }
    if (section === 'outline') {
      pushLine(out.outline, line.replace(/^\d+\.\s+/, '').replace(/^[-*]\s+/, ''));
      continue;
    }
    if (section === 'key_points') {
      pushLine(out.key_points, line.replace(/^[-*]\s+/, '').replace(/^\d+\.\s+/, ''));
      continue;
    }
  }
  return out;
}

function onNoteMarkdownInput(e) {
  const next = String(e?.target?.value || '');
  noteEditSections.value = markdownToNoteSections(next);
  scheduleNoteSave();
}

function toggleNoteEditMode() {
  noteEditMode.value = !noteEditMode.value;
}

async function restoreAINotes() {
  if (!notesTaskId.value) return;
  try {
    await apiDeleteNotesEdit(notesTaskId.value);
    noteEditSections.value = defaultNoteSectionsFromResult();
    noteEditMode.value = false;
    noteEditSavingText.value = '';
  } catch (e) {
    notesError.value = `恢复失败：${String(e?.message || e)}`;
  }
}

function setProgress(p, text) {
  const n = Math.max(0, Math.min(100, Number(p) || 0));
  notesProgress.value = n;
  if (text) notesProgressText.value = text;
}

const SYSTEM_TAB_LABELS = {
  summary: 'AI笔记',
  highlights: '时间笔记',
  transcript: '字幕稿',
  mindmap: '思维导图',
  qa: '问答',
};

const STREAM_STATE_LABELS = {
  idle: '空闲',
  connecting: '连接中',
  streaming: '生成中',
  finalizing: '收尾中',
  polling_fallback: '轮询中',
  completed: '已完成',
  failed: '失败',
};

function tabDisplayName(tab) {
  if (tab?.type === 'system' && SYSTEM_TAB_LABELS[tab.id]) return SYSTEM_TAB_LABELS[tab.id];
  return tab?.name || tab?.id || '';
}

function streamStateLabel(state) {
  return STREAM_STATE_LABELS[state] || state || '';
}

function visibleTabs() {
  return (tabs.value || [])
    .filter((t) => t.visible !== false)
    .sort((a, b) => (a.order_index || 0) - (b.order_index || 0));
}

async function loadTabs() {
  const data = await apiGetTabs();
  tabs.value = data.tabs || [];
  if (activeTab.value === 'chapters') activeTab.value = 'summary';
  if (!tabs.value.find((t) => t.id === activeTab.value && t.visible !== false)) {
    activeTab.value = visibleTabs()[0]?.id || 'summary';
  }
}

function mapStageTextLegacy(stage) {
  const mapping = {
    pending: '排队中',
    normalizing_url: '解析链接',
    extracting_transcript: '提取字幕/转写',
    calling_llm: '生成结构化总结',
    rendering_markdown: '导出 Markdown',
    completed: '已完成',
    failed: '失败',
  };
  return mapping[stage] || '处理中';
}

function updateProgressByStageLegacy(stage) {
  const stageProgress = {
    pending: 8,
    normalizing_url: 15,
    extracting_transcript: 55,
    calling_llm: 85,
    rendering_markdown: 95,
    completed: 100,
    failed: 100,
  };
  setProgress(stageProgress[stage] ?? 20, mapStageText(stage));
}

function mapStageText(stage) {
  const mapping = {
    pending: '排队中',
    normalizing_url: '解析链接',
    extracting_transcript: '提取字幕/转写',
    fetching_subtitles: '抓取平台字幕',
    downloading_audio: '下载语音',
    transcribing_audio: '语音转写',
    calling_llm: '生成结构化总结',
    rendering_markdown: '导出 Markdown',
    completed: '已完成',
    failed: '失败',
  };
  return mapping[stage] || '处理中';
}

function updateProgressByStage(stage) {
  const stageProgress = {
    pending: 8,
    normalizing_url: 15,
    extracting_transcript: 55,
    fetching_subtitles: 28,
    downloading_audio: 42,
    transcribing_audio: 58,
    calling_llm: 85,
    rendering_markdown: 95,
    completed: 100,
    failed: 100,
  };
  setProgress(stageProgress[stage] ?? 20, mapStageText(stage));
}

function stopLiveStatusProbe() {
  liveStatusProbeToken += 1;
}

async function startLiveStatusProbe(taskId) {
  const token = ++liveStatusProbeToken;
  while (token === liveStatusProbeToken && taskId) {
    try {
      const s = await apiSummarizeStatus(taskId);
      if (token !== liveStatusProbeToken) return;
      if (s?.stage) {
        notesStage.value = s.stage || '';
        if (s.stage === 'calling_llm') streamState.value = 'streaming';
        if (s.stage === 'rendering_markdown') streamState.value = 'finalizing';
        updateProgressByStage(s.stage);
      }
      if (s?.status === 'completed' || s?.status === 'failed') return;
    } catch {}
    await new Promise((r) => setTimeout(r, 1200));
  }
}

async function onExtract() {
  extractError.value = '';
  notesError.value = '';
  const url = extractFirstUrl(inputText.value);
  if (!url) {
    resolvedUrl.value = '';
    videoInfo.value = null;
    extractError.value = '请输入视频URL';
    return;
  }
  resolvedUrl.value = url;
  lastResolvedInput.value = String(inputText.value || '').trim();
  isExtracting.value = true;
  try {
    const data = await apiExtract(url);
    videoInfo.value = data;
    activeTab.value = 'summary';
    await refreshMe();
  } catch (e) {
    const msg = String(e?.message || e);
    extractError.value = msg;
    // 解析额度用尽(402)等：只显示文案即可，避免与「平台需 cookies」类提示一样打断全屏弹窗
  } finally {
    isExtracting.value = false;
  }
}

async function onTrySample(url) {
  const u = String(url || '').trim();
  if (!u) return;
  inputText.value = u;
  await onExtract();
}

async function onDownload(formatId) {
  if (!resolvedUrl.value) return;
  isVideoDownloading.value = true;
  try {
    const data = await apiDownload(resolvedUrl.value, formatId);
    await refreshMe();
    window.location.href = apiDownloadFileUrl(data.file_path);
  } catch (e) {
    const msg = String(e?.message || e);
    extractError.value = msg;
    if (shouldOpenUpgradeModal(e)) upgradeModalOpen.value = true;
    await refreshMe();
  } finally {
    isVideoDownloading.value = false;
  }
}

async function onDownloadFormatFromPanel(f) {
  if (!f?.format_id) return;
  await onDownload(f.format_id);
}

async function onSummarize() {
  stopLiveStatusProbe();
  notesError.value = '';
  streamErrorDetail.value = '';
  qaErrorBanner.value = '';
  qaMessages.value = [];
  const rawInput = String(inputText.value || '').trim();
  const inputUrl = extractFirstUrl(rawInput);
  if (inputUrl) {
    if (inputUrl !== resolvedUrl.value) {
      videoInfo.value = null;
    }
    resolvedUrl.value = inputUrl;
    lastResolvedInput.value = rawInput;
  } else if (!resolvedUrl.value) {
    notesError.value = '请输入视频URL';
    return;
  } else if (rawInput && rawInput !== lastResolvedInput.value) {
    resolvedUrl.value = '';
    videoInfo.value = null;
    notesError.value = '当前输入内容里没有可用视频链接，请重新粘贴完整 URL 后再试。';
    return;
  }
  if (!resolvedUrl.value) {
    const url = extractFirstUrl(inputText.value);
    if (!url) {
      notesError.value = '请输入视频URL';
      return;
    }
    resolvedUrl.value = url;
  }
  isSummarizing.value = true;
  activeTab.value = 'summary';
  notesTaskId.value = '';
  notesResult.value = null;
  noteEditLoaded.value = false;
  noteEditMode.value = false;
  streamBuffer.value = '';
  streamState.value = 'connecting';
  setProgress(5, '创建任务');
  try {
    const { task_id } = await apiSummarizeStreamCreate(resolvedUrl.value);
    notesTaskId.value = task_id;
    void startLiveStatusProbe(task_id);
    setProgress(10, '连接流式输出');
    await runSseStream(task_id);
    streamState.value = 'completed';
    activeTab.value = 'summary';
    await refreshMe();
  } catch (e) {
    const msg = String(e?.message || e);
    streamErrorDetail.value = msg;
    if (shouldOpenUpgradeModal(e)) {
      notesError.value = msg;
      streamState.value = 'failed';
      upgradeModalOpen.value = true;
    } else {
      stopLiveStatusProbe();
      streamState.value = 'polling_fallback';
      try {
        if (notesTaskId.value) {
          notesError.value = classifyStreamError(msg);
          await fallbackPollResult(notesTaskId.value);
          streamState.value = 'completed';
          activeTab.value = 'summary';
        } else {
          // 创建任务阶段就失败（常见 Failed to fetch：后端未启动或网络不可达），勿再抛 no task 掩盖原因
          const isNet =
            /failed to fetch|networkerror|load failed|连接.*失败|无法连接/i.test(msg) ||
            (e && e.name === 'TypeError');
          notesError.value = classifyStreamError(
            isNet
              ? '未能创建总结任务：无法连接服务器。请确认后端已启动（默认 uvicorn 端口 8003），开发环境需与 Vite 同域或通过 /api 代理访问。'
              : msg
          );
          streamState.value = 'failed';
        }
      } catch (e2) {
        const m2 = String(e2?.message || e2);
        notesError.value = classifyStreamError(m2);
        streamState.value = 'failed';
      }
    }
    await refreshMe();
  } finally {
    stopLiveStatusProbe();
    isSummarizing.value = false;
  }
}

watch(inputText, (next) => {
  const current = String(next || '').trim();
  if (current === lastResolvedInput.value) return;
  const currentUrl = extractFirstUrl(current);
  if (!current || !currentUrl || currentUrl !== resolvedUrl.value) {
    resolvedUrl.value = '';
    videoInfo.value = null;
  }
});

function classifyStreamError(msg) {
  const m = String(msg || '').toLowerCase();
  if (!m) return '连接中断，已尝试降级轮询。';
  if (m.includes('failed to fetch') || m.includes('networkerror') || m.includes('load failed'))
    return '无法连接服务器：请确认后端 API 已启动（默认 http://127.0.0.1:8003 ），页面与接口需同域或通过 Vite 将 /api 代理到后端。';
  if (m.includes('network') || m.includes('eventsource') || m.includes('stream')) return '流式连接中断，已自动切换到轮询模式。';
  if (
    m.includes('timeout') ||
    m.includes('timed out') ||
    m.includes('read operation timed out') ||
    m.includes('超时')
  )
    return '请求超时，已自动切换到轮询模式。';
  if (
    m.includes('llm') ||
    m.includes('chat/completions') ||
    m.includes('api key') ||
    m.includes('deepseek') ||
    m.includes('openai')
  ) {
    return `模型服务异常：${msg}`;
  }
  if (m.includes('invalid argument') || m.includes('unable to download video')) return `视频下载失败：${msg}`;
  return `总结失败：${msg}`;
}

async function fallbackPollResult(taskId) {
  if (!taskId) throw new Error('missing task_id');
  for (let i = 0; i < 160; i++) {
    const s = await apiSummarizeStatus(taskId);
    notesStage.value = s.stage || '';
    updateProgressByStage(s.stage);
    if (s.status === 'completed') {
      setProgress(100, '完成');
      notesResult.value = s.result || {};
      await loadSubtitles(taskId);
      await loadMindmapForTask(taskId, notesResult.value?.mindmap || {});
      await loadNotesEdit();
      return;
    }
    if (s.status === 'failed') throw new Error(s.error || '总结失败');
    await new Promise((r) => setTimeout(r, 1500));
  }
  throw new Error('轮询超时');
}

function runSseStream(taskId) {
  return new Promise((resolve, reject) => {
    const es = new EventSource(apiSummarizeStreamUrl(taskId));
    let done = false;
    const cleanup = () => {
      try {
        es.close();
      } catch {}
    };
    es.addEventListener('stage', (ev) => {
      try {
        const j = JSON.parse(ev.data || '{}');
        notesStage.value = j.stage || '';
        if (j.stage === 'calling_llm') streamState.value = 'streaming';
        if (j.stage === 'rendering_markdown') streamState.value = 'finalizing';
        updateProgressByStage(j.stage);
      } catch {}
    });
    es.addEventListener('progress', (ev) => {
      try {
        const j = JSON.parse(ev.data || '{}');
        if (typeof j.progress === 'number') setProgress(j.progress, j.text || notesProgressText.value);
      } catch {}
    });
    es.addEventListener('delta', (ev) => {
      try {
        const j = JSON.parse(ev.data || '{}');
        const t = String(j.text || '');
        if (t) streamBuffer.value += t;
      } catch {}
    });
    es.addEventListener('done', async (ev) => {
      try {
        stopLiveStatusProbe();
        const j = JSON.parse(ev.data || '{}');
        notesResult.value = j.result || {};
        setProgress(100, '完成');
        done = true;
        await loadSubtitles(taskId);
        await loadMindmapForTask(taskId, notesResult.value?.mindmap || {});
        await loadNotesEdit();
        cleanup();
        resolve();
      } catch (e) {
        cleanup();
        reject(e);
      }
    });
    es.addEventListener('error', (ev) => {
      stopLiveStatusProbe();
      if (done || notesResult.value) {
        cleanup();
        resolve();
        return;
      }
      try {
        const j = JSON.parse(ev.data || '{}');
        cleanup();
        reject(new Error(j.error || 'stream error'));
      } catch {
        cleanup();
        reject(new Error('stream error'));
      }
    });
  });
}

onBeforeUnmount(() => {
  stopLiveStatusProbe();
});

async function loadSubtitles(taskId) {
  try {
    const data = await apiGetSubtitles(taskId);
    subtitleSegments.value = data.segments || [];
    subtitleSource.value = data.source || '';
  } catch {
    subtitleSegments.value = [];
    subtitleSource.value = '';
  }
}

async function onOptimizeTranscript() {
  if (!notesTaskId.value || !notesResult.value || transcriptOptimizing.value) return;
  transcriptOptimizing.value = true;
  try {
    const data = await apiOptimizeTranscript(notesTaskId.value);
    if (notesResult.value) {
      notesResult.value = {
        ...notesResult.value,
        transcript_text: data.transcript_text || notesResult.value.transcript_text || '',
        transcript_optimized: true,
      };
    }
    transcriptShowOptimized.value = true;
    notesError.value = '字幕优化完成';
    setTimeout(() => {
      if (notesError.value === '字幕优化完成') notesError.value = '';
    }, 1400);
  } catch (e) {
    notesError.value = `字幕优化失败：${String(e?.message || e)}`;
  } finally {
    transcriptOptimizing.value = false;
  }
}

function scheduleMindmapSaveData(mindmap) {
  if (!notesTaskId.value) return;
  if (saveMindmapTimer) clearTimeout(saveMindmapTimer);
  mindmapSavingText.value = '自动保存中…';
  saveMindmapTimer = setTimeout(async () => {
    try {
      await apiSaveMindmap(notesTaskId.value, mindmap || { title: '视频主题', children: [] });
      mindmapSavingText.value = '已保存';
      setTimeout(() => {
        if (mindmapSavingText.value === '已保存') mindmapSavingText.value = '';
      }, 1200);
    } catch {
      mindmapSavingText.value = '保存失败';
    }
  }, 600);
}

async function retrySseNow() {
  if (!notesTaskId.value) return;
  notesError.value = '';
  streamErrorDetail.value = '';
  streamState.value = 'connecting';
  try {
    await runSseStream(notesTaskId.value);
    streamState.value = 'completed';
    activeTab.value = 'summary';
  } catch (e) {
    const msg = String(e?.message || e);
    streamErrorDetail.value = msg;
    notesError.value = classifyStreamError(msg);
    streamState.value = 'failed';
  }
}

async function retryPollingNow() {
  if (!notesTaskId.value) return;
  notesError.value = '';
  streamErrorDetail.value = '';
  streamState.value = 'polling_fallback';
  try {
    await fallbackPollResult(notesTaskId.value);
    streamState.value = 'completed';
    activeTab.value = 'summary';
  } catch (e) {
    notesError.value = classifyStreamError(String(e?.message || e));
    streamState.value = 'failed';
  }
}

async function loadMindmapForTask(taskId, fallbackMindmap) {
  try {
    const saved = await apiGetMindmap(taskId);
    const mm = saved?.mindmap || fallbackMindmap || { title: '视频主题', children: [] };
    mindmapData.value = mm;
  } catch {
    mindmapData.value = fallbackMindmap || { title: '视频主题', children: [] };
  }
}

function onMindmapChange(nextMindmap) {
  mindmapData.value = nextMindmap || { title: '视频主题', children: [] };
  scheduleMindmapSaveData(mindmapData.value);
}

async function onAsk() {
  if (!notesTaskId.value) {
    qaErrorBanner.value = '请先完成一次 AI 笔记生成。';
    return;
  }
  const q = qaQuestion.value.trim();
  if (!q) {
    qaErrorBanner.value = '请输入问题。';
    return;
  }
  qaErrorBanner.value = '';
  qaLoading.value = true;
  await nextTick();
  scrollQaChatToBottom();
  try {
    qaMessages.value.push({ role: 'user', content: q, ts: Date.now() });
    qaQuestion.value = '';
    await nextTick();
    scrollQaChatToBottom();
    const data = await apiSummarizeChat(notesTaskId.value, q);
    const raw = data.answer || '';
    const answer = normalizeChatAssistantText(raw) || raw || '（空回复）';
    qaMessages.value.push({ role: 'assistant', content: answer, ts: Date.now() });
  } catch (e) {
    qaErrorBanner.value = humanizeQaError(e);
  } finally {
    qaLoading.value = false;
    await nextTick();
    scrollQaChatToBottom();
  }
}

async function onTranslateToChinese() {
  if (!notesTaskId.value || !notesResult.value) return;
  translatingNotes.value = true;
  try {
    const data = await apiTranslateSummary(notesTaskId.value, 'zh');
    notesResult.value = {
      ...notesResult.value,
      summary: data.summary || notesResult.value.summary || [],
      chapters: data.chapters || notesResult.value.chapters || [],
      highlights: data.highlights || notesResult.value.highlights || [],
      output_language: 'zh',
    };
    await loadNotesEdit();
  } catch (e) {
    notesError.value = `翻译失败：${String(e?.message || e)}`;
  } finally {
    translatingNotes.value = false;
  }
}

function buildFullNotesText() {
  const p = effectiveNotesParts.value;
  const lines = [];
  if (p.oneLiner) {
    lines.push(`# 一句话总结`, '', p.oneLiner, '');
  }
  if (p.overview?.length) {
    lines.push('## 概述', ...p.overview.map((x) => `- ${x}`), '');
  }
  if (p.outline?.length) {
    lines.push('## 内容大纲', ...p.outline.map((x, i) => `${i + 1}. ${x}`), '');
  }
  if (p.keyPoints?.length) {
    lines.push('## 核心知识点', ...p.keyPoints.map((x) => `- ${x}`), '');
  }
  if (noteCardSections.value.length) {
    lines.push('## 章节速览', '');
    noteCardSections.value.forEach((section) => {
      const ts = formatDuration(section.start || 0);
      lines.push(`### ${section.title} ${ts}`);
      if (section.lead) lines.push(section.lead);
      if (section.items?.length) lines.push(...section.items.map((x) => `- ${x}`));
      lines.push('');
    });
  }
  return lines.join('\n').trim();
}

async function onCopyFullNotes() {
  try {
    const txt = buildFullNotesText();
    if (!txt) return;
    await navigator.clipboard.writeText(txt);
    notesError.value = '已复制全文到剪贴板';
    setTimeout(() => {
      if (notesError.value === '已复制全文到剪贴板') notesError.value = '';
    }, 1600);
  } catch (e) {
    notesError.value = `复制失败，请手动复制：${String(e?.message || e)}`;
  }
}

function expandNotesBlock(which) {
  notesBlockExpand.value = { ...notesBlockExpand.value, [which]: true };
}

function collapseNotesBlock(which) {
  notesBlockExpand.value = { ...notesBlockExpand.value, [which]: false };
}

async function onCopyNotesSection(kind) {
  const p = effectiveNotesParts.value;
  let txt = '';
  if (kind === 'overview' && p.overview?.length) {
    txt = ['## 概述', ...p.overview.map((x) => `- ${x}`)].join('\n');
  } else if (kind === 'outline' && p.outline?.length) {
    txt = ['## 内容大纲', ...p.outline.map((x, i) => `${i + 1}. ${x}`)].join('\n');
  } else if (kind === 'keypoints' && p.keyPoints?.length) {
    txt = ['## 核心知识要点', ...p.keyPoints.map((x) => `- ${x}`)].join('\n');
  }
  if (!txt) return;
  try {
    await navigator.clipboard.writeText(txt);
    notesError.value = '已复制该区块 Markdown';
    setTimeout(() => {
      if (notesError.value === '已复制该区块 Markdown') notesError.value = '';
    }, 1600);
  } catch (e) {
    notesError.value = `复制失败：${String(e?.message || e)}`;
  }
}

function jumpToTimelineFromOutline(startSec) {
  if (startSec == null || !Number.isFinite(startSec)) return;
  const highlights = notesResult.value?.highlights || [];
  let bestIdx = -1;
  let bestDelta = Infinity;
  highlights.forEach((h, i) => {
    const ts = Number(h.ts) || 0;
    const d = Math.abs(ts - startSec);
    if (d < bestDelta) {
      bestDelta = d;
      bestIdx = i;
    }
  });
  activeTab.value = 'highlights';
  if (bestIdx < 0) return;
  nextTick(() => {
    document.getElementById(`summary-hl-${bestIdx}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' });
  });
}

function triggerNotesSectionsAnimation() {
  notesSectionsVisible.value = false;
  nextTick(() => {
    requestAnimationFrame(() => {
      notesSectionsVisible.value = true;
    });
  });
}

onMounted(async () => {
  await refreshMe();
  await loadTabs();
});

watch(
  () => notesResult.value,
  (v, oldV) => {
    if (v && v !== oldV) {
      triggerNotesSectionsAnimation();
    }
  }
);

watch(
  [qaMessages, qaLoading],
  () => {
    nextTick(() => scrollQaChatToBottom());
  },
  { deep: true }
);

watch(
  () => [streamBuffer.value, streamNotesHtml.value, streamState.value, activeTab.value],
  async () => {
    if (activeTab.value !== 'summary') return;
    if (!['streaming', 'connecting', 'finalizing'].includes(streamState.value)) return;
    await nextTick();
    const el = streamNotesScrollRef.value;
    if (el) el.scrollTop = el.scrollHeight;
  }
);
</script>

<template>
  <div class="app-shell">
    <div class="app-shell-inner">
      <div class="app-shell-card">
        <!-- Header (Linear/Framer/Apple glass) -->
        <AppHeader class="print-hidden" :me="me" :is-pro="isPro" @open-upgrade="upgradeModalOpen = true" />

        <main class="px-4 sm:px-6 pb-6 pt-3 sm:pt-4 print-main">
          <HeroSection class="print-hidden" :usage-hint="usageHint" />
          <VideoUrlBar
            class="print-hidden"
            v-model="inputText"
            :is-extracting="isExtracting"
            :is-summarizing="isSummarizing"
            :extract-error="extractError"
            @extract="onExtract"
            @try-sample="onTrySample"
            @summarize="onSummarize"
          />

          <div class="main-workspace-grid grid grid-cols-1 lg:grid-cols-12 gap-5 items-start">
            <VideoResultPanel
              :video-info="videoInfo"
              :is-extracting="isExtracting"
              :is-pro="isPro"
              :is-downloading="isVideoDownloading"
              @download-format="onDownloadFormatFromPanel"
              @need-pro="upgradeModalOpen = true"
            />

            <!-- Right: summary & tools -->
            <section class="lg:col-span-8 print-summary-column">
              <div class="glass-card p-5 summary-print-card">
                <!-- Summary head with actions -->
                <div class="flex items-start justify-between gap-3 mb-4">
                  <div>
                    <div class="flex items-center gap-2">
                      <div class="h-8 w-8 rounded-2xl bg-slate-50 border border-slate-200 shadow-md shadow-blue-500/15 flex items-center justify-center print-hidden">
                        <Sparkles class="w-4 h-4 text-[#2563eb]" />
                      </div>
                      <div>
                        <div class="text-base font-semibold tracking-tight text-slate-900">AI笔记</div>
                        <div class="text-xs text-slate-500">AI 为你提炼可复用的知识笔记</div>
                      </div>
                    </div>
                  </div>
                  <div class="flex flex-col items-end gap-2 print-hidden">
                    <div class="flex flex-wrap justify-end gap-1.5">
                      <button
                        v-if="notesResult && (notesResult.output_language || '').toLowerCase() === 'en'"
                        class="pill-soft px-2.5 py-1 text-[10px] text-slate-800 disabled:opacity-60"
                        :disabled="translatingNotes"
                        @click="onTranslateToChinese"
                      >
                        {{ translatingNotes ? '翻译中…' : '一键翻译中文' }}
                      </button>
                      <a
                        v-if="notesDownloadUrl"
                        class="pill-soft px-2.5 py-1 text-[10px] text-emerald-700 hover:text-emerald-900"
                        :href="notesDownloadUrl"
                      >
                        下载 Markdown
                      </a>
                    </div>
                    <div class="flex flex-wrap items-center justify-end gap-1 text-xs text-slate-500">
                      <span class="text-slate-700 font-medium">{{ notesProgressText }}</span>
                      <span>· {{ notesProgress }}%</span>
                      <span v-if="streamState && streamState !== 'idle'">· 流：{{ streamStateLabel(streamState) }}</span>
                      <span v-if="notesResult?.output_language">· 语言：{{ notesResult.output_language.toUpperCase() }}</span>
                    </div>
                  </div>
                </div>

                <div class="w-full h-1.5 rounded-full bg-slate-200 overflow-hidden mb-4 print-hidden">
                  <div class="h-full rounded-full bg-gradient-to-r from-emerald-400 via-sky-400 to-indigo-400 transition-all" :style="{ width: `${notesProgress}%` }"></div>
                </div>

                <div v-if="notesError" class="mb-3 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2">
                  <div class="text-xs text-rose-800">{{ notesError }}</div>
                  <div v-if="streamErrorDetail" class="text-[10px] text-rose-700 mt-1 break-all">{{ streamErrorDetail }}</div>
                  <div class="flex items-center gap-2 mt-2 print-hidden">
                    <button class="px-2 py-1 text-[10px] rounded border border-rose-300 bg-transparent text-rose-800 hover:bg-rose-500/10" @click="retrySseNow">
                      重试流式
                    </button>
                    <button class="px-2 py-1 text-[10px] rounded border border-rose-300 bg-transparent text-rose-800 hover:bg-rose-500/10" @click="retryPollingNow">
                      改用轮询
                    </button>
                  </div>
                </div>

                <div class="flex flex-wrap gap-1.5 mb-4 print-hidden">
                  <button
                    v-for="t in visibleTabs()"
                    :key="t.id"
                    class="px-3.5 py-2 text-sm rounded-full border"
                    :class="activeTab===t.id ? 'bg-sky-100 border-sky-300 text-sky-900' : 'bg-slate-100 border-slate-200 text-slate-600'"
                    @click="activeTab=t.id"
                  >
                    {{ tabDisplayName(t) }}
                  </button>
                </div>

                <div v-if="!notesResult">
                  <div v-if="isSummarizing" class="space-y-3">
                    <div v-show="activeTab === 'summary'" class="print-hidden">
                      <div
                        class="rounded-2xl border border-slate-200 bg-white shadow-sm overflow-hidden flex flex-col"
                      >
                        <div
                          ref="streamNotesScrollRef"
                          class="stream-summary-prose max-h-[min(72vh,36rem)] min-h-[14rem] overflow-y-auto px-5 py-4 text-slate-800"
                        >
                          <div
                            v-if="streamNotesHtml"
                            class="summary-markdown-prose prose prose-base prose-slate max-w-none"
                            v-html="streamNotesHtml"
                          />
                          <p
                            v-else-if="notesStage === 'calling_llm' || streamState === 'streaming'"
                            class="text-sm text-slate-500 m-0 leading-relaxed"
                          >
                            等待 AI 笔记输出…
                          </p>
                        </div>
                        <div
                          v-if="['streaming', 'connecting', 'finalizing'].includes(streamState)"
                          class="flex items-center gap-2.5 border-t border-slate-100 px-5 py-2.5 bg-slate-50/95 text-sm text-sky-900"
                        >
                          <span class="relative flex h-2 w-2 shrink-0">
                            <span
                              class="animate-ping absolute inline-flex h-full w-full rounded-full bg-sky-400 opacity-70"
                            ></span>
                            <span class="relative inline-flex rounded-full h-2 w-2 bg-sky-500"></span>
                          </span>
                          <span v-if="streamState === 'finalizing'">正在整理结构与导图…</span>
                          <span v-else>AI 正在生成中…</span>
                        </div>
                      </div>
                    </div>
                    <div
                      v-show="activeTab !== 'summary' && isSummarizing"
                      class="text-center text-xs text-slate-500 py-10 print-hidden"
                    >
                      AI 笔记正在生成。请切换到「AI笔记」查看实时排版正文。
                    </div>
                    <div
                      v-if="
                        isSummarizing &&
                        activeTab === 'summary' &&
                        !String(streamBuffer || '').trim() &&
                        notesStage !== 'calling_llm' &&
                        notesStage !== 'rendering_markdown'
                      "
                      class="space-y-3 print-hidden"
                    >
                      <div class="shimmer rounded-2xl h-24"></div>
                      <div class="shimmer rounded-2xl h-24"></div>
                      <div class="shimmer rounded-2xl h-20"></div>
                    </div>
                  </div>
                  <div v-else class="text-xs text-slate-400">
                    右侧为 AI 笔记与工具区。先解析视频，或直接点击「AI 笔记」开始生成结构化内容。
                  </div>
                </div>

                <div v-else>
                  <div v-show="activeTab==='summary'">
                    <div class="flex flex-wrap items-center gap-2 mb-3 print-hidden">
                      <button
                        type="button"
                      class="text-xs px-3 py-1.5 rounded border border-slate-200 bg-slate-50 text-slate-800 disabled:opacity-50"
                        :disabled="!noteEditLoaded"
                        @click="toggleNoteEditMode"
                      >
                        {{ noteEditMode ? '完成编辑' : '编辑笔记' }}
                      </button>
                      <button
                        type="button"
                      class="text-xs px-3 py-1.5 rounded border border-slate-200 bg-slate-50 text-slate-800 disabled:opacity-50"
                        :disabled="!notesResult"
                        @click="onCopyFullNotes"
                      >
                        <span class="inline-flex items-center gap-1.5">
                          <Copy class="w-3.5 h-3.5" />
                          复制全文
                        </span>
                      </button>
                      <button
                        type="button"
                      class="text-xs px-3 py-1.5 rounded border border-amber-400/70 bg-amber-50 text-amber-900 hover:bg-amber-100"
                        @click="restoreAINotes"
                      >
                        恢复 AI 原文
                      </button>
                      <span v-if="noteEditSavingText" class="text-xs text-slate-500">{{ noteEditSavingText }}</span>
                    </div>

                    <div
                      v-if="notesIsEmpty && noteEditLoaded"
                      class="text-[11px] text-amber-900 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2 mb-4"
                    >
                      暂无 AI 生成笔记内容。可点击「编辑笔记」在此手动填写；有内容后会自动保存到当前任务。
                    </div>

                    <div class="space-y-4">
                      <div
                        class="summary-section"
                        :class="notesSectionsVisible ? 'summary-section--visible' : ''"
                        style="--summary-delay: 0ms"
                      >
                        <div class="summary-notebook glass-soft rounded-2xl px-3.5 py-4">
                          <div class="flex items-center justify-between gap-2 mb-2">
                            <div>
                              <div class="text-sm font-semibold tracking-tight text-slate-900">
                                {{ noteEditMode ? '笔记 Markdown' : 'AI 笔记卡片' }}
                              </div>
                              <div class="text-xs text-slate-500">
                                {{ noteEditMode ? '概述 / 内容大纲 / 核心知识点统一在一个文本框编辑' : '按章节时间点生成适合阅读和复盘的卡片式笔记' }}
                              </div>
                            </div>
                          </div>

                          <div v-if="noteEditMode">
                            <textarea
                              class="w-full min-h-[320px] text-xs border border-slate-200 rounded-md bg-white text-slate-800 p-2 font-mono"
                              :value="notesMarkdownText"
                              placeholder="# 一句话总结&#10;&#10;## 概述&#10;- ...&#10;&#10;## 内容大纲&#10;1. ...&#10;&#10;## 核心知识点&#10;- ..."
                              @input="onNoteMarkdownInput"
                            />
                          </div>
                          <div v-else-if="noteCardSections.length" class="ai-note-card">
                            <div class="ai-note-card-head">
                              <div class="ai-note-card-label">
                                <Sparkles class="w-3.5 h-3.5" />
                                <span>AI 笔记</span>
                              </div>
                              <h2 class="ai-note-card-title">{{ noteCardTitle }}</h2>
                              <p v-if="noteCardSummary" class="ai-note-card-summary">{{ noteCardSummary }}</p>
                              <div class="ai-note-card-meta">
                                <span class="ai-note-card-chip">卡片笔记</span>
                                <span
                                  v-if="notesResult?.transcript_quality === 'low'"
                                  class="ai-note-card-chip ai-note-card-chip--warn"
                                >
                                  低信号兜底
                                </span>
                                <span v-if="subtitleSource || notesResult?.subtitle_source" class="ai-note-card-chip">
                                  {{ subtitleSource || notesResult?.subtitle_source }}
                                </span>
                              </div>
                            </div>

                            <div class="ai-note-card-body">
                              <section
                                v-for="(section, idx) in noteCardSections"
                                :key="`${section.title}-${section.start}-${idx}`"
                                class="ai-note-card-section"
                              >
                                <div class="ai-note-card-section-head">
                                  <span class="ai-note-card-index">{{ String(idx + 1).padStart(2, '0') }}</span>
                                  <h3 class="ai-note-card-section-title">{{ section.title }}</h3>
                                  <button
                                    type="button"
                                    class="ai-note-card-time"
                                    @click="jumpToTimelineFromOutline(section.start)"
                                  >
                                    {{ formatDuration(section.start || 0) }}
                                  </button>
                                </div>
                                <p v-if="section.lead" class="ai-note-card-lead">{{ section.lead }}</p>
                                <ul v-if="section.items.length" class="ai-note-card-list">
                                  <li v-for="(item, itemIdx) in section.items" :key="`${idx}-${itemIdx}`">
                                    {{ item }}
                                  </li>
                                </ul>
                              </section>
                            </div>
                          </div>
                          <div v-else class="summary-markdown-prose prose prose-base prose-slate max-w-none">
                            <div v-if="notesMarkdownHtml" v-html="notesMarkdownHtml"></div>
                            <p v-else class="text-xs text-slate-500">（空）</p>
                          </div>
                        </div>
                      </div>

                    </div>
                  </div>

                  <div v-show="activeTab==='highlights'">
                    <ul class="list-none pl-0 space-y-2 text-sm text-slate-800">
                      <li
                        v-for="(h, idx) in (notesResult.highlights || [])"
                        :id="'summary-hl-' + idx"
                        :key="idx"
                        class="flex gap-2.5 scroll-mt-24 rounded-md px-1.5 -mx-1.5 py-1"
                      >
                        <span class="font-mono text-xs text-slate-500">[{{ formatDuration(h.ts || 0) }}]</span>
                        <span class="flex-1">{{ h.text }}</span>
                      </li>
                    </ul>
                  </div>

                  <div v-show="activeTab==='transcript'">
                    <div class="flex items-center justify-between gap-3 mb-2">
                      <div class="text-xs text-slate-500">
                        来源：{{ subtitleSource || notesResult.transcript_source || '-' }}
                        <span v-if="subtitleSegments.length" class="text-slate-500"> · </span>
                        <span v-if="subtitleSegments.length">片段数：{{ subtitleSegments.length }}</span>
                      </div>
                      <div class="flex items-center gap-1.5">
                        <button class="px-2.5 py-1.5 text-xs rounded border border-slate-200 bg-slate-100 text-slate-800" @click="transcriptExpanded=!transcriptExpanded">
                          {{ transcriptExpanded ? '收起' : '展开' }}
                        </button>
                        <button
                          v-if="notesTaskId"
                          class="px-2.5 py-1.5 text-xs rounded border border-slate-200 bg-slate-100 text-slate-800 disabled:opacity-60"
                          :disabled="transcriptOptimizing"
                          @click="onOptimizeTranscript"
                        >
                          {{ transcriptOptimizing ? '优化中…' : 'AI优化字幕' }}
                        </button>
                        <button
                          v-if="notesResult?.transcript_text && (notesResult?.transcript_optimized || transcriptShowOptimized)"
                          class="px-2.5 py-1.5 text-xs rounded border border-slate-200 bg-slate-100 text-slate-800"
                          @click="transcriptShowOptimized=!transcriptShowOptimized"
                        >
                          {{ transcriptShowOptimized ? '隐藏优化全文' : '查看优化全文' }}
                        </button>
                        <a
                          v-if="notesTaskId"
                          class="px-2.5 py-1.5 text-xs rounded border border-slate-200 bg-slate-100 text-slate-800"
                          :href="apiSubtitleDownloadUrl(notesTaskId,'srt')"
                        >下载 SRT</a>
                        <a
                          v-if="notesTaskId"
                          class="px-2.5 py-1.5 text-xs rounded border border-slate-200 bg-slate-100 text-slate-800"
                          :href="apiSubtitleDownloadUrl(notesTaskId,'vtt')"
                        >下载 VTT</a>
                        <a
                          v-if="notesTaskId"
                          class="px-2.5 py-1.5 text-xs rounded border border-slate-200 bg-slate-100 text-slate-800"
                          :href="apiSubtitleDownloadUrl(notesTaskId,'txt')"
                        >下载 TXT</a>
                      </div>
                    </div>

                    <div
                      v-if="transcriptShowOptimized && notesResult?.transcript_text"
                      class="mb-3 rounded-xl border border-slate-200 bg-white px-4 py-3"
                    >
                      <div class="flex items-center justify-between gap-2 mb-2">
                        <div class="text-[11px] font-semibold tracking-[0.12em] uppercase text-slate-400">优化后全文</div>
                        <div class="text-[10px] text-slate-400">更通顺的断句与标点（尽量保留原意）</div>
                      </div>
                      <div class="whitespace-pre-wrap text-sm leading-7 text-slate-800">
                        {{ notesResult.transcript_text }}
                      </div>
                    </div>

                    <div v-if="subtitleSegments.length" class="border border-slate-200 rounded bg-white">
                      <div
                        class="max-h-80 overflow-auto divide-y divide-slate-100"
                        :class="transcriptExpanded ? '' : 'max-h-56'"
                      >
                        <div v-for="(seg, idx) in subtitleSegments" :key="idx" class="p-2.5 text-sm leading-6 text-slate-800">
                          <span class="font-mono text-slate-500">[{{ formatTs(seg.start || 0) }}]</span>
                          <span class="ml-2">{{ seg.text }}</span>
                        </div>
                      </div>
                    </div>
                    <pre v-else class="max-h-64 overflow-auto whitespace-pre-wrap bg-white border border-slate-200 rounded p-3 text-sm leading-6 text-slate-800">{{ notesResult.transcript_text || '' }}</pre>
                  </div>

                  <div v-show="activeTab==='mindmap'" class="text-xs text-slate-700">
                    <div class="mb-1 text-[11px] text-slate-400">{{ mindmapSavingText }}</div>
                    <MindmapFlow
                      :key="notesTaskId || 'mindmap-idle'"
                      :mindmap="mindmapData"
                      @change="onMindmapChange"
                      @seek="jumpToTimelineFromOutline"
                    />
                  </div>

                  <div v-show="activeTab==='qa'">
                    <div class="text-[11px] text-slate-400 mb-2">基于当前任务上下文（多轮对话）</div>
                    <div
                      ref="qaChatScrollRef"
                      class="min-h-[200px] max-h-72 overflow-y-auto flex flex-col gap-3 p-3 mb-2 rounded-2xl border border-slate-200/80 bg-slate-50/80"
                    >
                      <div v-if="!qaMessages.length && !qaLoading" class="text-[11px] text-slate-500 text-center py-8">
                        暂无对话，输入问题开始。
                      </div>
                      <div
                        v-for="(m, idx) in qaMessages"
                        :key="`${idx}-${m.ts}`"
                        class="flex w-full"
                        :class="m.role === 'user' ? 'justify-end' : 'justify-start'"
                      >
                        <div
                          class="flex gap-2 items-end max-w-[min(92%,28rem)]"
                          :class="m.role === 'user' ? 'flex-row-reverse' : 'flex-row'"
                        >
                          <div
                            class="shrink-0 w-8 h-8 rounded-full border flex items-center justify-center"
                            :class="
                              m.role === 'user'
                                ? 'bg-sky-500/20 border-sky-300/60 text-sky-800'
                                : 'bg-slate-200/80 border-slate-300/70 text-slate-700'
                            "
                          >
                            <User v-if="m.role === 'user'" class="w-4 h-4" aria-hidden="true" />
                            <Bot v-else class="w-4 h-4" aria-hidden="true" />
                          </div>
                          <div
                            class="rounded-2xl px-3 py-2 text-xs leading-relaxed border shadow-sm whitespace-pre-wrap break-words"
                            :class="
                              m.role === 'user'
                                ? 'bg-sky-500/15 border-sky-200/80 text-slate-900'
                                : 'bg-white border-slate-200 text-slate-800'
                            "
                          >
                            {{ m.content }}
                          </div>
                        </div>
                      </div>
                      <div v-if="qaLoading" class="flex w-full justify-start">
                        <div class="flex gap-2 items-end max-w-[min(92%,28rem)]">
                          <div
                            class="shrink-0 w-8 h-8 rounded-full border bg-slate-200/80 border-slate-300/70 text-slate-700 flex items-center justify-center"
                          >
                            <Bot class="w-4 h-4" aria-hidden="true" />
                          </div>
                          <div
                            class="rounded-2xl px-3 py-2 text-xs border border-slate-200 bg-white text-slate-500 shadow-sm"
                          >
                            <span class="inline-flex items-center gap-1">
                              <span class="inline-flex gap-0.5">
                                <span class="qa-typing-dot" />
                                <span class="qa-typing-dot" style="animation-delay: 0.15s" />
                                <span class="qa-typing-dot" style="animation-delay: 0.3s" />
                              </span>
                              正在输入…
                            </span>
                          </div>
                        </div>
                      </div>
                    </div>
                    <div
                      v-if="qaErrorBanner"
                      class="text-[10px] text-rose-700 bg-rose-50 border border-rose-200/80 rounded-lg px-2.5 py-1.5 mb-2"
                    >
                      {{ qaErrorBanner }}
                    </div>
                    <div class="flex gap-2">
                      <input
                        v-model="qaQuestion"
                        class="flex-1 px-3 py-2 border border-slate-200 rounded-md bg-white text-xs text-slate-800 placeholder:text-slate-500 focus:outline-none focus:ring-1 focus:ring-sky-400/70"
                        placeholder="基于当前视频内容提问..."
                        :disabled="qaLoading"
                        @keydown.enter.prevent="onAsk"
                      />
                      <button
                        class="px-4 py-2 rounded-md text-xs font-semibold bg-slate-100 text-slate-900 hover:bg-white disabled:opacity-60"
                        :disabled="qaLoading"
                        @click="onAsk"
                      >
                        提问
                      </button>
                    </div>
                  </div>

                  <div
                    v-if="notesResult && !['summary','highlights','transcript','mindmap','qa'].includes(activeTab)"
                    class="text-xs text-slate-400"
                  >
                    自定义标签「{{ tabs.find(t => t.id === activeTab)?.name || activeTab }}」已就绪。
                  </div>
                </div>

              </div>
            </section>
          </div>
        </main>
      </div>
    </div>
  </div>

  <UpgradeModal
    v-model="upgradeModalOpen"
    :me="me"
    :is-pro="isPro"
    :billing-state="billingState"
    @oauth="oauthLogin"
    @logout="doLogout"
    @create-order="createOrder"
    @mock-paid="mockMarkPaid"
  />
</template>


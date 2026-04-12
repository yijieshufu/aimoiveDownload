<script setup>
import { computed, onMounted, ref, nextTick, watch } from 'vue';
import { Sparkles, Copy, Image as ImageIcon } from 'lucide-vue-next';
import { useMagnetic } from './composables/useMagnetic';
import {
  apiAbsolute,
  apiDeleteSummaryEdit,
  apiDownload,
  apiDownloadFileUrl,
  apiExtract,
  apiMe,
  apiLogout,
  apiBillingCreateWeChatpay,
  apiBillingCreateAlipay,
  apiBillingMockMarkPaid,
  apiGetMindmap,
  apiGetSummaryEdit,
  apiGetTabs,
  apiSaveMindmap,
  apiSaveSummaryEdit,
  apiSaveTabs,
  apiSummarize,
  apiSummarizeStreamCreate,
  apiSummarizeStreamUrl,
  apiSummarizeChat,
  apiSummarizeStatus,
  apiTranslateSummary,
  apiGetSubtitles,
  apiSubtitleDownloadUrl,
} from './api/index.js';
import MindmapFlow from './components/MindmapFlow.vue';
import AppHeader from './components/AppHeader.vue';
import HeroSection from './components/HeroSection.vue';
import VideoUrlBar from './components/VideoUrlBar.vue';
import VideoResultPanel from './components/VideoResultPanel.vue';
import UpgradeModal from './components/UpgradeModal.vue';

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

const inputText = ref('');
const resolvedUrl = ref('');
const isExtracting = ref(false);
const isVideoDownloading = ref(false);
const extractError = ref('');
const videoInfo = ref(null);
const activeTab = ref('summary');
const tabs = ref([]);
const tabEditing = ref(false);

const isSummarizing = ref(false);
const summaryTaskId = ref('');
const summaryStage = ref('');
const summaryProgress = ref(0);
const summaryProgressText = ref('未开始');
const summaryError = ref('');
const summaryResult = ref(null);
const streamBuffer = ref('');
const streamState = ref('idle'); // idle | connecting | streaming | finalizing | polling_fallback | completed | failed
const streamErrorDetail = ref('');
const subtitleSegments = ref([]);
const subtitleSource = ref('');
const transcriptExpanded = ref(false);

const qaQuestion = ref('');
const qaAnswer = ref('');
const qaLoading = ref(false);
const qaMessages = ref([]);
const translatingSummary = ref(false);
const mindmapSavingText = ref('');
let saveMindmapTimer = null;
const mindmapData = ref({ title: '视频主题', children: [] });

const summaryEditSections = ref({ overview: [], outline: [], key_points: [], one_liner: '' });
const summaryEditLoaded = ref(false);
const summaryEditMode = ref(false);
const summaryEditSavingText = ref('');
let saveSummaryTimer = null;

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

const summaryDownloadUrl = computed(() => {
  const u = summaryResult.value?.markdown_download_url;
  return apiAbsolute(u);
});

const summaryCardRef = ref(null);
const summarySectionsVisible = ref(false);

useMagnetic('[data-magnetic]', { strength: 10, maxTranslate: 10 });

const summaryBlocks = computed(() => {
  const s = summaryResult.value?.summary_sections || {};
  const arr = summaryResult.value?.summary || [];
  const overview = Array.isArray(s.overview) && s.overview.length ? s.overview : arr.slice(0, 2);
  const outline = Array.isArray(s.outline) && s.outline.length ? s.outline : (summaryResult.value?.chapters || []).slice(0, 5).map((c) => c.title).filter(Boolean);
  const keyPoints = Array.isArray(s.key_points) && s.key_points.length ? s.key_points : (arr.slice(2, 8).length ? arr.slice(2, 8) : arr.slice(0, 6));
  const oneLiner = s.one_liner || arr[0] || '';
  return { overview, outline, keyPoints, oneLiner };
});

const effectiveSummaryParts = computed(() => {
  if (!summaryResult.value) {
    return { overview: [], outline: [], keyPoints: [], oneLiner: '' };
  }
  if (!summaryEditLoaded.value) {
    const b = summaryBlocks.value;
    return {
      overview: b.overview,
      outline: b.outline,
      keyPoints: b.keyPoints,
      oneLiner: b.oneLiner,
    };
  }
  const s = summaryEditSections.value;
  return {
    overview: Array.isArray(s.overview) ? [...s.overview] : [],
    outline: Array.isArray(s.outline) ? [...s.outline] : [],
    keyPoints: Array.isArray(s.key_points) ? [...s.key_points] : [],
    oneLiner: s.one_liner || '',
  };
});

const summaryIsEmpty = computed(() => {
  const p = effectiveSummaryParts.value;
  return (
    (!p.overview || p.overview.length === 0) &&
    (!p.outline || p.outline.length === 0) &&
    (!p.keyPoints || p.keyPoints.length === 0) &&
    !String(p.oneLiner || '').trim()
  );
});

function defaultSummarySectionsFromResult() {
  const res = summaryResult.value;
  if (!res) {
    return { overview: [], outline: [], key_points: [], one_liner: '' };
  }
  const s = res.summary_sections || {};
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

function normalizeSummarySections(sec) {
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

async function loadSummaryEdit() {
  const tid = summaryTaskId.value;
  if (!tid || !summaryResult.value) {
    summaryEditLoaded.value = false;
    return;
  }
  try {
    const data = await apiGetSummaryEdit(tid);
    if (data.sections) {
      summaryEditSections.value = normalizeSummarySections(data.sections);
    } else {
      summaryEditSections.value = defaultSummarySectionsFromResult();
    }
  } catch {
    summaryEditSections.value = defaultSummarySectionsFromResult();
  }
  summaryEditLoaded.value = true;
}

function scheduleSummarySave() {
  if (!summaryTaskId.value) return;
  if (saveSummaryTimer) clearTimeout(saveSummaryTimer);
  summaryEditSavingText.value = '保存中…';
  saveSummaryTimer = setTimeout(async () => {
    try {
      await apiSaveSummaryEdit(summaryTaskId.value, summaryEditSections.value);
      summaryEditSavingText.value = '已保存';
      setTimeout(() => {
        if (summaryEditSavingText.value === '已保存') summaryEditSavingText.value = '';
      }, 1200);
    } catch {
      summaryEditSavingText.value = '保存失败';
    }
  }, 600);
}

function onSummaryOverviewInput(e) {
  summaryEditSections.value.overview = e.target.value.split('\n').map((l) => l.trim()).filter(Boolean);
  scheduleSummarySave();
}
function onSummaryOutlineInput(e) {
  summaryEditSections.value.outline = e.target.value.split('\n').map((l) => l.trim()).filter(Boolean);
  scheduleSummarySave();
}
function onSummaryKeyPointsInput(e) {
  summaryEditSections.value.key_points = e.target.value.split('\n').map((l) => l.trim()).filter(Boolean);
  scheduleSummarySave();
}
function onSummaryOneLinerInput(e) {
  summaryEditSections.value.one_liner = String(e.target.value || '').slice(0, 2000);
  scheduleSummarySave();
}

function toggleSummaryEditMode() {
  summaryEditMode.value = !summaryEditMode.value;
}

async function restoreAISummary() {
  if (!summaryTaskId.value) return;
  try {
    await apiDeleteSummaryEdit(summaryTaskId.value);
    summaryEditSections.value = defaultSummarySectionsFromResult();
    summaryEditMode.value = false;
    summaryEditSavingText.value = '';
  } catch (e) {
    summaryError.value = `恢复失败：${String(e?.message || e)}`;
  }
}

function setProgress(p, text) {
  const n = Math.max(0, Math.min(100, Number(p) || 0));
  summaryProgress.value = n;
  if (text) summaryProgressText.value = text;
}

const SYSTEM_TAB_LABELS = {
  summary: '摘要',
  highlights: '时间轴',
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

async function persistTabs() {
  tabs.value = tabs.value.map((t, i) => ({ ...t, order_index: i }));
  const data = await apiSaveTabs(tabs.value);
  tabs.value = data.tabs || tabs.value;
}

async function addTab() {
  const name = prompt('标签名称', '自定义');
  if (!name) return;
  const id = `custom_${Date.now()}`;
  tabs.value.push({ id, name: name.trim(), type: 'custom', order_index: tabs.value.length, visible: true });
  await persistTabs();
}

async function renameTab(tab) {
  const name = prompt('重命名标签', tab.name || '');
  if (!name) return;
  tab.name = name.trim();
  await persistTabs();
}

async function deleteTab(tab) {
  if (!canDeleteTab(tab)) return;
  tabs.value = tabs.value.filter((x) => x.id !== tab.id);
  if (activeTab.value === tab.id) activeTab.value = 'summary';
  await persistTabs();
}

async function moveTab(tab, delta) {
  const list = [...tabs.value].sort((a, b) => (a.order_index || 0) - (b.order_index || 0));
  const idx = list.findIndex((x) => x.id === tab.id);
  if (idx < 0) return;
  const ni = idx + delta;
  if (ni < 0 || ni >= list.length) return;
  const temp = list[idx];
  list[idx] = list[ni];
  list[ni] = temp;
  tabs.value = list.map((x, i) => ({ ...x, order_index: i }));
  await persistTabs();
}

function mapStageText(stage) {
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

function canDeleteTab(tab) {
  return tab.type !== 'system' && !['summary', 'mindmap'].includes(tab.id);
}

function updateProgressByStage(stage) {
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

async function onExtract() {
  extractError.value = '';
  summaryError.value = '';
  const url = extractFirstUrl(inputText.value);
  if (!url) {
    extractError.value = '请输入视频URL';
    return;
  }
  resolvedUrl.value = url;
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

async function onExtractBatch() {
  extractError.value = '';
  summaryError.value = '';
  const lines = String(inputText.value || '')
    .split(/\r?\n/)
    .map((line) => extractFirstUrl(line))
    .filter(Boolean);
  if (!lines.length) {
    extractError.value = '每行粘贴一条含 https 的链接，再点「串行批量」';
    return;
  }
  isExtracting.value = true;
  videoInfo.value = null;
  let lastOk = null;
  let lastUrl = '';
  const errs = [];
  for (let i = 0; i < lines.length; i++) {
    const u = lines[i];
    try {
      const data = await apiExtract(u);
      lastOk = data;
      lastUrl = u;
    } catch (e) {
      errs.push(`第${i + 1}条：${String(e?.message || e)}`);
    }
  }
  if (lastOk) {
    videoInfo.value = lastOk;
    resolvedUrl.value = lastUrl;
    activeTab.value = 'summary';
  }
  if (errs.length) {
    extractError.value =
      errs.length === lines.length
        ? `全部 ${errs.length} 条失败：${errs[0]}`
        : `完成 ${lines.length - errs.length}/${lines.length} 条；失败：${errs.slice(0, 2).join('；')}${errs.length > 2 ? '…' : ''}`;
  }
  isExtracting.value = false;
  await refreshMe();
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
  summaryError.value = '';
  streamErrorDetail.value = '';
  qaAnswer.value = '';
  qaMessages.value = [];
  if (!resolvedUrl.value) {
    const url = extractFirstUrl(inputText.value);
    if (!url) {
      summaryError.value = '请输入视频URL';
      return;
    }
    resolvedUrl.value = url;
  }
  isSummarizing.value = true;
  summaryTaskId.value = '';
  summaryResult.value = null;
  summaryEditLoaded.value = false;
  summaryEditMode.value = false;
  streamBuffer.value = '';
  streamState.value = 'connecting';
  setProgress(5, '创建任务');
  try {
    const { task_id } = await apiSummarizeStreamCreate(resolvedUrl.value);
    summaryTaskId.value = task_id;
    setProgress(10, '连接流式输出');
    await runSseStream(task_id);
    streamState.value = 'completed';
    await refreshMe();
  } catch (e) {
    const msg = String(e?.message || e);
    streamErrorDetail.value = msg;
    if (shouldOpenUpgradeModal(e)) {
      summaryError.value = msg;
      streamState.value = 'failed';
      upgradeModalOpen.value = true;
    } else {
      streamState.value = 'polling_fallback';
      summaryError.value = classifyStreamError(msg);
      try {
        if (summaryTaskId.value) {
          await fallbackPollResult(summaryTaskId.value);
          streamState.value = 'completed';
        } else {
          throw new Error('no task');
        }
      } catch (e2) {
        const m2 = String(e2?.message || e2);
        summaryError.value = classifyStreamError(m2);
        streamState.value = 'failed';
      }
    }
    await refreshMe();
  } finally {
    isSummarizing.value = false;
  }
}

function classifyStreamError(msg) {
  const m = String(msg || '').toLowerCase();
  if (!m) return '连接中断，已尝试降级轮询。';
  if (m.includes('network') || m.includes('eventsource') || m.includes('stream')) return '流式连接中断，已自动切换到轮询模式。';
  if (m.includes('timeout')) return '请求超时，已自动切换到轮询模式。';
  if (m.includes('llm') || m.includes('model')) return `模型服务异常：${msg}`;
  if (m.includes('invalid argument') || m.includes('unable to download video')) return `视频下载失败：${msg}`;
  return `总结失败：${msg}`;
}

async function fallbackPollResult(taskId) {
  if (!taskId) throw new Error('missing task_id');
  for (let i = 0; i < 160; i++) {
    const s = await apiSummarizeStatus(taskId);
    summaryStage.value = s.stage || '';
    updateProgressByStage(s.stage);
    if (s.status === 'completed') {
      setProgress(100, '完成');
      summaryResult.value = s.result || {};
      await loadSubtitles(taskId);
      await loadMindmapForTask(taskId, summaryResult.value?.mindmap || {});
      await loadSummaryEdit();
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
        summaryStage.value = j.stage || '';
        if (j.stage === 'calling_llm') streamState.value = 'streaming';
        if (j.stage === 'rendering_markdown') streamState.value = 'finalizing';
        updateProgressByStage(j.stage);
      } catch {}
    });
    es.addEventListener('progress', (ev) => {
      try {
        const j = JSON.parse(ev.data || '{}');
        if (typeof j.progress === 'number') setProgress(j.progress, j.text || summaryProgressText.value);
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
        const j = JSON.parse(ev.data || '{}');
        summaryResult.value = j.result || {};
        setProgress(100, '完成');
        done = true;
        await loadSubtitles(taskId);
        await loadMindmapForTask(taskId, summaryResult.value?.mindmap || {});
        await loadSummaryEdit();
        cleanup();
        resolve();
      } catch (e) {
        cleanup();
        reject(e);
      }
    });
    es.addEventListener('error', (ev) => {
      if (done || summaryResult.value) {
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

function scheduleMindmapSaveData(mindmap) {
  if (!summaryTaskId.value) return;
  if (saveMindmapTimer) clearTimeout(saveMindmapTimer);
  mindmapSavingText.value = '自动保存中…';
  saveMindmapTimer = setTimeout(async () => {
    try {
      await apiSaveMindmap(summaryTaskId.value, mindmap || { title: '视频主题', children: [] });
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
  if (!summaryTaskId.value) return;
  summaryError.value = '';
  streamErrorDetail.value = '';
  streamState.value = 'connecting';
  try {
    await runSseStream(summaryTaskId.value);
    streamState.value = 'completed';
  } catch (e) {
    const msg = String(e?.message || e);
    streamErrorDetail.value = msg;
    summaryError.value = classifyStreamError(msg);
    streamState.value = 'failed';
  }
}

async function retryPollingNow() {
  if (!summaryTaskId.value) return;
  summaryError.value = '';
  streamErrorDetail.value = '';
  streamState.value = 'polling_fallback';
  try {
    await fallbackPollResult(summaryTaskId.value);
    streamState.value = 'completed';
  } catch (e) {
    summaryError.value = classifyStreamError(String(e?.message || e));
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
  if (!summaryTaskId.value) {
    qaAnswer.value = '请先完成一次视频总结。';
    return;
  }
  const q = qaQuestion.value.trim();
  if (!q) {
    qaAnswer.value = '请输入问题。';
    return;
  }
  qaLoading.value = true;
  qaAnswer.value = 'AI 思考中...';
  try {
    qaMessages.value.push({ role: 'user', content: q, ts: Date.now() });
    qaQuestion.value = '';
    const data = await apiSummarizeChat(summaryTaskId.value, q);
    const answer = data.answer || '';
    qaAnswer.value = answer;
    qaMessages.value.push({ role: 'assistant', content: answer, ts: Date.now() });
  } catch (e) {
    qaAnswer.value = `问答失败：${String(e?.message || e)}`;
  } finally {
    qaLoading.value = false;
  }
}

async function onTranslateToChinese() {
  if (!summaryTaskId.value || !summaryResult.value) return;
  translatingSummary.value = true;
  try {
    const data = await apiTranslateSummary(summaryTaskId.value, 'zh');
    summaryResult.value = {
      ...summaryResult.value,
      summary: data.summary || summaryResult.value.summary || [],
      chapters: data.chapters || summaryResult.value.chapters || [],
      highlights: data.highlights || summaryResult.value.highlights || [],
      output_language: 'zh',
    };
    await loadSummaryEdit();
  } catch (e) {
    summaryError.value = `翻译失败：${String(e?.message || e)}`;
  } finally {
    translatingSummary.value = false;
  }
}

function buildFullSummaryText() {
  const p = effectiveSummaryParts.value;
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
  return lines.join('\n').trim();
}

async function onCopyFullSummary() {
  try {
    const txt = buildFullSummaryText();
    if (!txt) return;
    await navigator.clipboard.writeText(txt);
    summaryError.value = '已复制全文到剪贴板';
    setTimeout(() => {
      if (summaryError.value === '已复制全文到剪贴板') summaryError.value = '';
    }, 1600);
  } catch (e) {
    summaryError.value = `复制失败，请手动复制：${String(e?.message || e)}`;
  }
}

async function onGenerateShareImage() {
  if (!summaryCardRef.value) return;
  try {
    const { toPng } = await import('html-to-image');
    const dataUrl = await toPng(summaryCardRef.value, {
      cacheBust: true,
      pixelRatio: 2,
      backgroundColor: '#ffffff',
    });
    const a = document.createElement('a');
    a.href = dataUrl;
    a.download = '视频总结分享图.png';
    a.click();
  } catch (e) {
    summaryError.value = `生成分享图失败：${String(e?.message || e)}`;
  }
}

function triggerSummarySectionsAnimation() {
  summarySectionsVisible.value = false;
  nextTick(() => {
    requestAnimationFrame(() => {
      summarySectionsVisible.value = true;
    });
  });
}

onMounted(async () => {
  await refreshMe();
  await loadTabs();
});

watch(
  () => summaryResult.value,
  (v, oldV) => {
    if (v && v !== oldV) {
      triggerSummarySectionsAnimation();
    }
  }
);
</script>

<template>
  <div class="app-shell">
    <div class="app-shell-inner">
      <div class="app-shell-card">
        <!-- Header (Linear/Framer/Apple glass) -->
        <AppHeader :me="me" :is-pro="isPro" @open-upgrade="upgradeModalOpen = true" />

        <main class="px-4 sm:px-6 pb-6 pt-3 sm:pt-4">
          <HeroSection :usage-hint="usageHint" />
          <VideoUrlBar
            v-model="inputText"
            :is-extracting="isExtracting"
            :is-summarizing="isSummarizing"
            :extract-error="extractError"
            @extract="onExtract"
            @extract-batch="onExtractBatch"
            @try-sample="onTrySample"
            @summarize="onSummarize"
          />

          <div class="grid grid-cols-1 lg:grid-cols-12 gap-5 items-start">
            <VideoResultPanel
              :video-info="videoInfo"
              :is-extracting="isExtracting"
              :is-pro="isPro"
              :is-downloading="isVideoDownloading"
              @download-format="onDownloadFormatFromPanel"
              @need-pro="upgradeModalOpen = true"
            />

            <!-- Right: summary & tools -->
            <section class="lg:col-span-8">
              <div ref="summaryCardRef" class="glass-card p-5">
                <!-- Summary head with actions -->
                <div class="flex items-start justify-between gap-3 mb-4">
                  <div>
                    <div class="flex items-center gap-2">
                      <div class="h-8 w-8 rounded-2xl bg-slate-50 border border-slate-200 shadow-md shadow-blue-500/15 flex items-center justify-center">
                        <Sparkles class="w-4 h-4 text-[#2563eb]" />
                      </div>
                      <div>
                        <div class="text-sm font-semibold tracking-tight text-slate-900">视频总结</div>
                        <div class="text-[11px] text-slate-400">AI 为你提炼可复用的知识骨架</div>
                      </div>
                    </div>
                  </div>
                  <div class="flex flex-col items-end gap-2">
                    <div class="flex flex-wrap justify-end gap-1.5">
                      <button
                        v-if="summaryResult && (summaryResult.output_language || '').toLowerCase() === 'en'"
                        class="pill-soft px-2.5 py-1 text-[10px] text-slate-800 disabled:opacity-60"
                        :disabled="translatingSummary"
                        @click="onTranslateToChinese"
                      >
                        {{ translatingSummary ? '翻译中…' : '一键翻译中文' }}
                      </button>
                      <button
                        class="pill-soft px-2.5 py-1 text-[10px] text-slate-800 disabled:opacity-50"
                        :disabled="!summaryResult"
                        @click="onCopyFullSummary"
                      >
                        <span class="inline-flex items-center gap-1.5">
                          <Copy class="w-3.5 h-3.5" />
                          复制全文
                        </span>
                      </button>
                      <button
                        class="pill-soft px-2.5 py-1 text-[10px] text-slate-800 disabled:opacity-50"
                        :disabled="!summaryResult"
                        @click="onGenerateShareImage"
                      >
                        <span class="inline-flex items-center gap-1.5">
                          <ImageIcon class="w-3.5 h-3.5" />
                          生成分享图
                        </span>
                      </button>
                      <a
                        v-if="summaryDownloadUrl"
                        class="pill-soft px-2.5 py-1 text-[10px] text-emerald-700 hover:text-emerald-900"
                        :href="summaryDownloadUrl"
                      >
                        下载 Markdown
                      </a>
                    </div>
                    <div class="flex flex-wrap items-center justify-end gap-1 text-[10px] text-slate-500">
                      <span class="text-slate-700 font-medium">{{ summaryProgressText }}</span>
                      <span>· {{ summaryProgress }}%</span>
                      <span v-if="streamState && streamState !== 'idle'">· 流：{{ streamStateLabel(streamState) }}</span>
                      <span v-if="summaryResult?.output_language">· 语言：{{ summaryResult.output_language.toUpperCase() }}</span>
                    </div>
                  </div>
                </div>

                <div class="w-full h-1.5 rounded-full bg-slate-200 overflow-hidden mb-4">
                  <div class="h-full rounded-full bg-gradient-to-r from-emerald-400 via-sky-400 to-indigo-400 transition-all" :style="{ width: `${summaryProgress}%` }"></div>
                </div>

                <div v-if="summaryError" class="mb-3 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2">
                  <div class="text-xs text-rose-800">{{ summaryError }}</div>
                  <div v-if="streamErrorDetail" class="text-[10px] text-rose-700 mt-1 break-all">{{ streamErrorDetail }}</div>
                  <div class="flex items-center gap-2 mt-2">
                    <button class="px-2 py-1 text-[10px] rounded border border-rose-300 bg-transparent text-rose-800 hover:bg-rose-500/10" @click="retrySseNow">
                      重试流式
                    </button>
                    <button class="px-2 py-1 text-[10px] rounded border border-rose-300 bg-transparent text-rose-800 hover:bg-rose-500/10" @click="retryPollingNow">
                      改用轮询
                    </button>
                  </div>
                </div>

                <div class="flex items-center gap-2 mb-3">
                  <button class="px-2.5 py-1.5 text-[10px] rounded border border-slate-200 bg-slate-50 text-slate-800" @click="tabEditing=!tabEditing">
                    {{ tabEditing ? '完成' : '编辑标签' }}
                  </button>
                  <button class="px-2.5 py-1.5 text-[10px] rounded border border-slate-200 bg-slate-50 text-slate-800" @click="addTab">
                    + 添加标签
                  </button>
                </div>
                <div class="flex flex-wrap gap-1.5 mb-4">
                  <div v-for="t in visibleTabs()" :key="t.id" class="inline-flex items-center gap-1">
                    <button
                      class="px-2.5 py-1.5 text-[10px] rounded-full border"
                      :class="activeTab===t.id ? 'bg-sky-100 border-sky-300 text-sky-900' : 'bg-slate-100 border-slate-200 text-slate-600'"
                      @click="activeTab=t.id"
                    >
                      {{ tabDisplayName(t) }}
                    </button>
                    <template v-if="tabEditing">
                      <button class="text-[9px] px-1 border border-slate-200 rounded text-slate-600" @click="moveTab(t,-1)">↑</button>
                      <button class="text-[9px] px-1 border border-slate-200 rounded text-slate-600" @click="moveTab(t,1)">↓</button>
                      <button class="text-[9px] px-1 border border-slate-200 rounded text-slate-600" @click="renameTab(t)">✎</button>
                      <button v-if="canDeleteTab(t)" class="text-[9px] px-1 border border-rose-300 rounded text-rose-600" @click="deleteTab(t)">✕</button>
                    </template>
                  </div>
                </div>

                <div v-if="!summaryResult">
                  <div v-if="isSummarizing" class="space-y-3">
                    <div class="shimmer rounded-2xl h-24"></div>
                    <div class="shimmer rounded-2xl h-28"></div>
                    <div class="shimmer rounded-2xl h-24"></div>
                  </div>
                  <div v-else class="text-xs text-slate-400">
                    右侧为 AI 摘要与工具区。先解析视频，或直接点击「视频总结」开始生成结构化内容。
                  </div>
                </div>

                <div v-else>
                  <div v-show="activeTab==='summary'">
                    <div class="flex flex-wrap items-center gap-2 mb-3">
                      <button
                        type="button"
                        class="text-[10px] px-2.5 py-1.5 rounded border border-slate-200 bg-slate-50 text-slate-800 disabled:opacity-50"
                        :disabled="!summaryEditLoaded"
                        @click="toggleSummaryEditMode"
                      >
                        {{ summaryEditMode ? '完成编辑' : '编辑摘要' }}
                      </button>
                      <button
                        type="button"
                        class="text-[10px] px-2.5 py-1.5 rounded border border-amber-400/70 bg-amber-50 text-amber-900 hover:bg-amber-100"
                        @click="restoreAISummary"
                      >
                        恢复 AI 原文
                      </button>
                      <span v-if="summaryEditSavingText" class="text-[10px] text-slate-400">{{ summaryEditSavingText }}</span>
                    </div>

                    <div
                      v-if="summaryIsEmpty && summaryEditLoaded"
                      class="text-[11px] text-amber-900 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2 mb-4"
                    >
                      暂无 AI 生成摘要内容。可点击「编辑摘要」在此手动填写；有内容后会自动保存到当前任务。
                    </div>

                    <div class="space-y-4">
                      <!-- 概述卡片 + AI 灵感图标 -->
                      <div
                        class="summary-section"
                        :class="summarySectionsVisible ? 'summary-section--visible' : ''"
                        style="--summary-delay: 0ms"
                      >
                        <div class="glass-soft px-3.5 py-3 rounded-2xl flex gap-3">
                          <div class="mt-0.5">
                            <div class="h-9 w-9 rounded-2xl bg-sky-500/25 border border-sky-400/60 shadow-[0_0_26px_rgba(56,189,248,0.8)] flex items-center justify-center text-[15px]">
                              💡
                            </div>
                          </div>
                          <div class="flex-1">
                            <div class="flex items-center justify-between gap-2 mb-1">
                              <div>
                                <div class="text-xs font-semibold tracking-tight text-slate-900">概述</div>
                                <div class="text-[11px] text-slate-400">快速理解本视频的核心脉络与调性</div>
                              </div>
                            </div>
                            <div v-if="summaryEditMode">
                              <textarea
                                class="w-full min-h-[120px] text-xs border border-slate-200 rounded-md bg-white text-slate-800 p-2 font-sans"
                                :value="(summaryEditSections.overview || []).join('\n')"
                                placeholder="每行一条概述，支持多行"
                                @input="onSummaryOverviewInput"
                              />
                            </div>
                            <div v-else class="mt-1">
                              <div v-if="effectiveSummaryParts.overview.length" class="space-y-1.5 text-xs text-slate-800">
                                <div v-for="(s, idx) in effectiveSummaryParts.overview" :key="idx" class="flex gap-1.5">
                                  <span class="mt-[3px] h-1 w-1 rounded-full bg-sky-400/80"></span>
                                  <span class="leading-relaxed">{{ s }}</span>
                                </div>
                              </div>
                              <p v-else class="text-xs text-slate-500">（空）</p>
                            </div>
                          </div>
                        </div>
                      </div>

                      <!-- 内容大纲：垂直步骤条 -->
                      <div
                        class="summary-section"
                        :class="summarySectionsVisible ? 'summary-section--visible' : ''"
                        style="--summary-delay: 80ms"
                      >
                        <div class="glass-soft px-3.5 py-3 rounded-2xl">
                          <div class="flex items-center justify-between mb-2">
                            <div>
                              <div class="text-xs font-semibold tracking-tight text-slate-900">内容大纲</div>
                              <div class="text-[11px] text-slate-400">按章节梳理视频推进节奏</div>
                            </div>
                          </div>
                          <div v-if="summaryEditMode">
                            <textarea
                              class="w-full min-h-[110px] text-xs border border-slate-200 rounded-md bg-white text-slate-800 p-2 font-sans"
                              :value="(summaryEditSections.outline || []).join('\n')"
                              placeholder="每行一条小节标题"
                              @input="onSummaryOutlineInput"
                            />
                          </div>
                          <div v-else>
                            <div v-if="effectiveSummaryParts.outline.length" class="relative pl-4 space-y-3 text-xs text-slate-800">
                              <div
                                v-for="(x, idx) in effectiveSummaryParts.outline"
                                :key="idx"
                                class="relative flex gap-3"
                              >
                                <div class="flex flex-col items-center">
                                  <div class="h-8 w-8 rounded-full bg-white border border-slate-200 flex items-center justify-center">
                                    <div class="h-6 w-6 rounded-full bg-gradient-to-br from-sky-400 via-indigo-400 to-fuchsia-400 text-[11px] font-semibold text-slate-900 flex items-center justify-center">
                                      {{ idx + 1 }}
                                    </div>
                                  </div>
                                  <div
                                    v-if="idx < effectiveSummaryParts.outline.length - 1"
                                    class="flex-1 w-px bg-slate-200 mt-1"
                                  />
                                </div>
                                <div class="pt-1 flex-1">
                                  <div class="font-medium leading-relaxed">{{ x }}</div>
                                </div>
                              </div>
                            </div>
                            <p v-else class="text-xs text-slate-500">（空）</p>
                          </div>
                        </div>
                      </div>

                      <!-- 核心知识点：Glassmorphism 卡片网格 -->
                      <div
                        class="summary-section"
                        :class="summarySectionsVisible ? 'summary-section--visible' : ''"
                        style="--summary-delay: 160ms"
                      >
                        <div class="glass-soft px-3.5 py-3 rounded-2xl">
                          <div class="flex items-center justify-between mb-2">
                            <div>
                              <div class="text-xs font-semibold tracking-tight text-slate-900">核心知识要点</div>
                              <div class="text-[11px] text-slate-400">提炼可迁移、可复用的关键知识点</div>
                            </div>
                          </div>
                          <div v-if="summaryEditMode">
                            <textarea
                              class="w-full min-h-[120px] text-xs border border-slate-200 rounded-md bg-white text-slate-800 p-2 font-sans"
                              :value="(summaryEditSections.key_points || []).join('\n')"
                              placeholder="每行一条知识要点"
                              @input="onSummaryKeyPointsInput"
                            />
                          </div>
                          <div v-else>
                            <div
                              v-if="effectiveSummaryParts.keyPoints.length"
                              class="grid grid-cols-1 sm:grid-cols-2 gap-2.5"
                            >
                              <div
                                v-for="(s, idx) in effectiveSummaryParts.keyPoints"
                                :key="idx"
                                class="rounded-2xl border border-slate-200 bg-slate-50 shadow-md shadow-slate-200/80 p-3 flex gap-2.5 items-start"
                              >
                                <div class="shrink-0 h-8 w-8 rounded-xl flex items-center justify-center bg-white border border-slate-200 text-lg">
                                  <span>
                                    {{
                                      s.includes('注意') || s.includes('风险') || s.includes('坑')
                                        ? '⚠️'
                                        : s.includes('工具') || s.includes('操作') || s.includes('步骤')
                                          ? '🛠️'
                                          : idx === 0
                                            ? '💡'
                                            : '📌'
                                    }}
                                  </span>
                                </div>
                                <div class="text-xs text-slate-800 leading-relaxed">
                                  {{ s }}
                                </div>
                              </div>
                            </div>
                            <p v-else class="text-xs text-slate-500">（空）</p>
                          </div>
                        </div>
                      </div>

                      <!-- 一句话总结：Border Beam 精华卡片 -->
                      <div
                        class="summary-section"
                        :class="summarySectionsVisible ? 'summary-section--visible' : ''"
                        style="--summary-delay: 240ms"
                      >
                        <div class="border-beam rounded-2xl p-[1px]">
                          <div class="rounded-[1rem] bg-gradient-to-br from-emerald-50 via-emerald-50 to-slate-50 px-3.5 py-3 flex items-start gap-2.5">
                            <div class="pill-soft px-2 py-0.5 text-[10px] text-emerald-800 mt-0.5 bg-emerald-500/20 border-emerald-300">
                              精华
                            </div>
                            <div class="flex-1">
                              <div class="text-[11px] font-semibold text-emerald-900 mb-1">一句话总结</div>
                              <div v-if="summaryEditMode">
                                <input
                                  class="w-full text-xs border border-emerald-300 rounded-md px-2 py-1.5 bg-emerald-950/60 text-emerald-50"
                                  :value="summaryEditSections.one_liner"
                                  maxlength="2000"
                                  @input="onSummaryOneLinerInput"
                                />
                              </div>
                              <div v-else class="text-[13px] italic text-emerald-900 font-medium leading-relaxed">
                                {{ effectiveSummaryParts.oneLiner || '（空）' }}
                              </div>
                            </div>
                          </div>
                        </div>
                      </div>

                      <!-- AI Analysis：合并的思维导图画布（暗色玻璃） -->
                      <div
                        class="summary-section"
                        :class="summarySectionsVisible ? 'summary-section--visible' : ''"
                        style="--summary-delay: 320ms"
                      >
                        <div class="glass-soft px-3.5 py-3 rounded-2xl">
                          <div class="flex items-center justify-between mb-2">
                            <div>
                              <div class="text-xs font-semibold tracking-tight text-slate-900">思维导图</div>
                              <div class="text-[11px] text-slate-400">把摘要结构化成可编辑的知识树</div>
                            </div>
                            <div class="text-[11px] text-slate-500">{{ mindmapSavingText }}</div>
                          </div>
                          <MindmapFlow :key="summaryTaskId || 'mindmap-idle'" :mindmap="mindmapData" @change="onMindmapChange" />
                        </div>
                      </div>
                    </div>
                  </div>

                  <div v-show="activeTab==='highlights'">
                    <ul class="list-none pl-0 space-y-1.5 text-xs text-slate-800">
                      <li v-for="(h, idx) in (summaryResult.highlights || [])" :key="idx" class="flex gap-2">
                        <span class="font-mono text-[10px] text-slate-400">[{{ formatDuration(h.ts || 0) }}]</span>
                        <span class="flex-1">{{ h.text }}</span>
                      </li>
                    </ul>
                  </div>

                  <div v-show="activeTab==='transcript'">
                    <div class="flex items-center justify-between gap-3 mb-2">
                      <div class="text-[11px] text-slate-400">
                        来源：{{ subtitleSource || summaryResult.transcript_source || '-' }}
                        <span v-if="subtitleSegments.length" class="text-slate-500"> · </span>
                        <span v-if="subtitleSegments.length">片段数：{{ subtitleSegments.length }}</span>
                      </div>
                      <div class="flex items-center gap-1.5">
                        <button class="px-2 py-1 text-[10px] rounded border border-slate-200 bg-slate-100 text-slate-800" @click="transcriptExpanded=!transcriptExpanded">
                          {{ transcriptExpanded ? '收起' : '展开' }}
                        </button>
                        <a
                          v-if="summaryTaskId"
                          class="px-2 py-1 text-[10px] rounded border border-slate-200 bg-slate-100 text-slate-800"
                          :href="apiSubtitleDownloadUrl(summaryTaskId,'srt')"
                        >下载 SRT</a>
                        <a
                          v-if="summaryTaskId"
                          class="px-2 py-1 text-[10px] rounded border border-slate-200 bg-slate-100 text-slate-800"
                          :href="apiSubtitleDownloadUrl(summaryTaskId,'vtt')"
                        >下载 VTT</a>
                        <a
                          v-if="summaryTaskId"
                          class="px-2 py-1 text-[10px] rounded border border-slate-200 bg-slate-100 text-slate-800"
                          :href="apiSubtitleDownloadUrl(summaryTaskId,'txt')"
                        >下载 TXT</a>
                      </div>
                    </div>

                    <div v-if="subtitleSegments.length" class="border border-slate-200 rounded bg-white">
                      <div
                        class="max-h-80 overflow-auto divide-y divide-slate-100"
                        :class="transcriptExpanded ? '' : 'max-h-56'"
                      >
                        <div v-for="(seg, idx) in subtitleSegments" :key="idx" class="p-2 text-[11px] text-slate-800">
                          <span class="font-mono text-slate-500">[{{ formatTs(seg.start || 0) }}]</span>
                          <span class="ml-2">{{ seg.text }}</span>
                        </div>
                      </div>
                    </div>
                    <pre v-else class="max-h-64 overflow-auto whitespace-pre-wrap bg-white border border-slate-200 rounded p-3 text-[11px] text-slate-800">{{ summaryResult.transcript_text || '' }}</pre>
                  </div>

                  <div v-show="activeTab==='mindmap'" class="text-xs text-slate-700">
                    <div class="mb-1 text-[11px] text-slate-400">{{ mindmapSavingText }}</div>
                    <MindmapFlow :key="summaryTaskId || 'mindmap-idle'" :mindmap="mindmapData" @change="onMindmapChange" />
                  </div>

                  <div v-show="activeTab==='qa'">
                    <div class="text-[11px] text-slate-400 mb-2">基于当前任务上下文（多轮对话）</div>
                    <div class="max-h-56 overflow-auto border border-slate-200 rounded-md p-2 bg-white mb-3">
                      <div v-if="!qaMessages.length" class="text-[11px] text-slate-500">暂无对话，输入问题开始。</div>
                      <div v-for="(m, idx) in qaMessages" :key="idx" class="mb-2">
                        <div class="text-[10px] text-slate-500">{{ m.role === 'user' ? '你' : 'AI' }}</div>
                        <div class="text-xs text-slate-800 whitespace-pre-wrap">{{ m.content }}</div>
                      </div>
                    </div>
                    <div class="flex gap-2">
                      <input
                        v-model="qaQuestion"
                        class="flex-1 px-3 py-2 border border-slate-200 rounded-md bg-white text-xs text-slate-800 placeholder:text-slate-500 focus:outline-none focus:ring-1 focus:ring-sky-400/70"
                        placeholder="基于当前视频内容提问..."
                      />
                      <button
                        class="px-4 py-2 rounded-md text-xs font-semibold bg-slate-100 text-slate-900 hover:bg-white disabled:opacity-60"
                        :disabled="qaLoading"
                        @click="onAsk"
                      >
                        提问
                      </button>
                    </div>
                    <div class="mt-3 text-xs text-slate-800 whitespace-pre-wrap">{{ qaAnswer }}</div>
                  </div>

                  <div
                    v-if="summaryResult && !['summary','highlights','transcript','mindmap','qa'].includes(activeTab)"
                    class="text-xs text-slate-400"
                  >
                    自定义标签「{{ tabs.find(t => t.id === activeTab)?.name || activeTab }}」已就绪。
                  </div>
                </div>

                <div v-if="streamBuffer && !summaryResult" class="mt-3">
                  <div class="text-[11px] text-slate-500 mb-1.5">流式输出（实时生成中）</div>
                  <pre class="max-h-56 overflow-auto whitespace-pre-wrap bg-slate-100 border border-slate-200 rounded p-3 text-[11px] text-slate-800">{{ streamBuffer }}</pre>
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

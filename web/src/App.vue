<script setup>
import { computed, onMounted, ref } from 'vue';
import {
  apiAbsolute,
  apiDeleteSummaryEdit,
  apiDownload,
  apiDownloadFileUrl,
  apiExtract,
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
} from './api';
import MindmapFlow from './components/MindmapFlow.vue';

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

const summaryDownloadUrl = computed(() => {
  const u = summaryResult.value?.markdown_download_url;
  return apiAbsolute(u);
});

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
  } catch (e) {
    extractError.value = String(e?.message || e);
  } finally {
    isExtracting.value = false;
  }
}

async function onDownload(formatId) {
  if (!resolvedUrl.value) return;
  try {
    const data = await apiDownload(resolvedUrl.value, formatId);
    window.location.href = apiDownloadFileUrl(data.file_path);
  } catch (e) {
    extractError.value = String(e?.message || e);
  }
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
  } catch (e) {
    const msg = String(e?.message || e);
    streamErrorDetail.value = msg;
    streamState.value = 'polling_fallback';
    summaryError.value = classifyStreamError(msg);
    try {
      await fallbackPollResult(summaryTaskId.value);
      streamState.value = 'completed';
    } catch (e2) {
      const m2 = String(e2?.message || e2);
      summaryError.value = classifyStreamError(m2);
      streamState.value = 'failed';
    }
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

onMounted(async () => {
  await loadTabs();
});
</script>

<template>
  <div class="min-h-screen bg-gray-50">
    <div class="bg-gradient-to-r from-slate-900 to-slate-800 text-white">
      <div class="max-w-6xl mx-auto px-4 py-5 flex items-center justify-between">
        <div class="font-bold text-lg">万能视频下载器</div>
        <div class="text-xs text-slate-300">解析/下载 + AI 总结 + 可编辑导图</div>
      </div>
    </div>

    <main class="max-w-6xl mx-auto px-4 py-8">
      <div class="bg-white rounded-xl shadow p-5">
        <div class="flex flex-col md:flex-row gap-3">
          <input
            v-model="inputText"
            class="flex-1 px-4 py-3 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-slate-600"
            placeholder="粘贴视频链接或分享文案（包含 https://...）"
            @keyup.enter="onExtract"
          />
          <button
            class="px-5 py-3 rounded-md font-bold bg-slate-800 text-white hover:bg-slate-900 disabled:opacity-60"
            :disabled="isExtracting"
            @click="onExtract"
          >
            {{ isExtracting ? '解析中...' : '开始解析' }}
          </button>
          <button
            class="px-5 py-3 rounded-md font-bold bg-emerald-600 text-white hover:bg-emerald-700 disabled:opacity-60"
            :disabled="isSummarizing"
            @click="onSummarize"
          >
            {{ isSummarizing ? '总结中...' : '视频总结' }}
          </button>
        </div>
        <div v-if="extractError" class="mt-3 text-sm text-red-600">{{ extractError }}</div>
      </div>

      <div class="mt-6 grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
        <!-- Left: Parse + download -->
        <section class="lg:col-span-5 space-y-4">
          <div class="bg-white rounded-xl shadow p-4">
            <div class="font-semibold text-slate-800 mb-2">视频播放区域</div>
            <div class="aspect-video bg-gray-100 border border-gray-200 rounded-lg flex items-center justify-center overflow-hidden">
              <img v-if="videoInfo?.thumbnail" class="w-full h-full object-contain" :src="apiAbsolute(videoInfo.thumbnail)" />
              <div v-else class="text-sm text-gray-500">解析后显示预览</div>
            </div>
            <div class="mt-2 text-sm text-gray-600 truncate">{{ videoInfo?.title || '' }}</div>
          </div>

          <div class="bg-white rounded-xl shadow p-4" v-if="videoInfo">
            <div class="font-semibold text-slate-800 mb-3">解析信息</div>
            <div class="text-sm text-gray-700">
              <div class="font-medium truncate">{{ videoInfo.title }}</div>
              <div class="mt-1 text-xs text-gray-500">
                {{ videoInfo.uploader }} · {{ formatDuration(videoInfo.duration) }} · {{ formatViews(videoInfo.view_count) }} 次播放
              </div>
            </div>
          </div>

          <div class="bg-white rounded-xl shadow p-4" v-if="videoInfo">
            <div class="font-semibold text-slate-800 mb-3">选择分辨率下载</div>
            <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <button
                v-for="f in (videoInfo.formats || [])"
                :key="f.format_id"
                class="border border-gray-200 rounded-lg p-3 hover:bg-gray-50 text-left"
                @click="onDownload(f.format_id)"
              >
                <div class="font-bold text-slate-900">
                  {{ f.width && f.height ? `${f.width}×${f.height}` : '音频/未知' }}
                </div>
                <div class="text-xs text-gray-500 mt-1">
                  {{ f.ext }} · {{ f.filesize ? formatFileSize(f.filesize) : '大小未知' }}
                </div>
              </button>
            </div>
          </div>
        </section>

        <!-- Right: Summary module -->
        <section class="lg:col-span-7">
          <div class="bg-white rounded-xl shadow p-6">
            <div class="flex items-center justify-between mb-3">
              <div class="font-bold text-slate-800">视频总结</div>
              <div class="flex items-center gap-3">
                <button
                  v-if="summaryResult && (summaryResult.output_language || '').toLowerCase() === 'en'"
                  class="text-sm px-3 py-1 rounded border border-gray-300 bg-white hover:bg-gray-50 disabled:opacity-60"
                  :disabled="translatingSummary"
                  @click="onTranslateToChinese"
                >
                  {{ translatingSummary ? '翻译中...' : '一键翻译中文' }}
                </button>
                <a v-if="summaryDownloadUrl" class="text-sm font-semibold text-emerald-700 hover:underline" :href="summaryDownloadUrl">
                  下载 Markdown
                </a>
              </div>
            </div>

            <div class="mb-3 text-sm text-gray-600">
              <span class="font-medium">{{ summaryProgressText }}</span>
              <span class="text-gray-400"> · </span>
              <span>{{ summaryProgress }}%</span>
              <span v-if="streamState && streamState !== 'idle'" class="text-gray-400"> · </span>
              <span v-if="streamState && streamState !== 'idle'">流状态：{{ streamStateLabel(streamState) }}</span>
              <span v-if="summaryResult?.output_language" class="text-gray-400"> · </span>
              <span v-if="summaryResult?.output_language">语言: {{ summaryResult.output_language.toUpperCase() }}</span>
            </div>
            <div class="w-full bg-gray-200 rounded-full h-2.5 mb-4">
              <div class="h-2.5 rounded-full bg-emerald-600 transition-all" :style="{ width: `${summaryProgress}%` }"></div>
            </div>

            <div v-if="summaryError" class="mb-3 p-3 border border-red-200 bg-red-50 rounded-md">
              <div class="text-sm text-red-700">{{ summaryError }}</div>
              <div v-if="streamErrorDetail" class="text-xs text-red-500 mt-1 break-all">{{ streamErrorDetail }}</div>
              <div class="flex items-center gap-2 mt-2">
                <button class="px-2 py-1 text-xs border border-red-300 rounded bg-white hover:bg-red-50" @click="retrySseNow">
                  重试流式
                </button>
                <button class="px-2 py-1 text-xs border border-red-300 rounded bg-white hover:bg-red-50" @click="retryPollingNow">
                  改用轮询
                </button>
              </div>
            </div>

            <div class="flex items-center gap-2 mb-2">
              <button class="px-3 py-1.5 text-xs rounded border border-gray-300 bg-white hover:bg-gray-50" @click="tabEditing=!tabEditing">
                {{ tabEditing ? '完成' : '编辑标签' }}
              </button>
              <button class="px-3 py-1.5 text-xs rounded border border-gray-300 bg-white hover:bg-gray-50" @click="addTab">+ 添加标签</button>
            </div>
            <div class="flex flex-wrap gap-2 mb-4">
              <div v-for="t in visibleTabs()" :key="t.id" class="inline-flex items-center gap-1">
                <button
                  class="px-3 py-1.5 text-xs rounded border"
                  :class="activeTab===t.id ? 'bg-emerald-50 border-emerald-200' : 'bg-white border-gray-300'"
                  @click="activeTab=t.id"
                >
                  {{ tabDisplayName(t) }}
                </button>
                <template v-if="tabEditing">
                  <button class="text-[10px] px-1 border rounded" @click="moveTab(t,-1)">↑</button>
                  <button class="text-[10px] px-1 border rounded" @click="moveTab(t,1)">↓</button>
                  <button class="text-[10px] px-1 border rounded" @click="renameTab(t)">✎</button>
                  <button v-if="canDeleteTab(t)" class="text-[10px] px-1 border rounded text-red-600" @click="deleteTab(t)">✕</button>
                </template>
              </div>
            </div>

            <div v-if="!summaryResult" class="text-sm text-gray-500">
              右侧是总结模块。先在左侧解析并选择分辨率下载，或直接点击“视频总结”生成内容。
            </div>

            <div v-else>
              <div v-show="activeTab==='summary'">
                <div class="flex flex-wrap items-center gap-2 mb-3">
                  <button
                    type="button"
                    class="text-xs px-3 py-1.5 rounded border border-gray-300 bg-white hover:bg-gray-50 disabled:opacity-50"
                    :disabled="!summaryEditLoaded"
                    @click="toggleSummaryEditMode"
                  >
                    {{ summaryEditMode ? '完成编辑' : '编辑摘要' }}
                  </button>
                  <button
                    type="button"
                    class="text-xs px-3 py-1.5 rounded border border-amber-300 bg-amber-50 text-amber-900 hover:bg-amber-100"
                    @click="restoreAISummary"
                  >
                    恢复 AI 原文
                  </button>
                  <span v-if="summaryEditSavingText" class="text-xs text-gray-500">{{ summaryEditSavingText }}</span>
                </div>
                <div v-if="summaryIsEmpty && summaryEditLoaded" class="text-sm text-amber-800 bg-amber-50 border border-amber-200 rounded-lg p-3 mb-4">
                  暂无 AI 生成摘要内容。可点击「编辑摘要」在此手动填写；有内容后会自动保存到当前任务。
                </div>
                <div class="space-y-4">
                  <div class="border border-gray-200 rounded-lg p-3">
                    <div class="text-xs font-semibold text-gray-500 mb-2">概述</div>
                    <template v-if="summaryEditMode">
                      <textarea
                        class="w-full min-h-[120px] text-sm border border-gray-300 rounded-md p-2 font-sans"
                        :value="(summaryEditSections.overview || []).join('\n')"
                        placeholder="每行一条"
                        @input="onSummaryOverviewInput"
                      />
                    </template>
                    <template v-else>
                      <div class="prose prose-slate max-w-none">
                        <ul v-if="effectiveSummaryParts.overview.length">
                          <li v-for="(s, idx) in effectiveSummaryParts.overview" :key="idx">{{ s }}</li>
                        </ul>
                        <p v-else class="text-sm text-gray-400">（空）</p>
                      </div>
                    </template>
                  </div>
                  <div class="border border-gray-200 rounded-lg p-3">
                    <div class="text-xs font-semibold text-gray-500 mb-2">内容大纲</div>
                    <template v-if="summaryEditMode">
                      <textarea
                        class="w-full min-h-[100px] text-sm border border-gray-300 rounded-md p-2 font-sans"
                        :value="(summaryEditSections.outline || []).join('\n')"
                        placeholder="每行一条"
                        @input="onSummaryOutlineInput"
                      />
                    </template>
                    <template v-else>
                      <ol v-if="effectiveSummaryParts.outline.length" class="list-decimal pl-5 text-sm text-gray-800 space-y-1">
                        <li v-for="(x, idx) in effectiveSummaryParts.outline" :key="idx">{{ x }}</li>
                      </ol>
                      <p v-else class="text-sm text-gray-400">（空）</p>
                    </template>
                  </div>
                  <div class="border border-gray-200 rounded-lg p-3">
                    <div class="text-xs font-semibold text-gray-500 mb-2">核心知识要点</div>
                    <template v-if="summaryEditMode">
                      <textarea
                        class="w-full min-h-[120px] text-sm border border-gray-300 rounded-md p-2 font-sans"
                        :value="(summaryEditSections.key_points || []).join('\n')"
                        placeholder="每行一条"
                        @input="onSummaryKeyPointsInput"
                      />
                    </template>
                    <template v-else>
                      <ul v-if="effectiveSummaryParts.keyPoints.length" class="list-disc pl-5 text-sm text-gray-800 space-y-1">
                        <li v-for="(s, idx) in effectiveSummaryParts.keyPoints" :key="idx">{{ s }}</li>
                      </ul>
                      <p v-else class="text-sm text-gray-400">（空）</p>
                    </template>
                  </div>
                  <div class="border border-emerald-200 bg-emerald-50 rounded-lg p-3">
                    <div class="text-xs font-semibold text-emerald-700 mb-1">一句话总结</div>
                    <template v-if="summaryEditMode">
                      <input
                        class="w-full text-sm border border-emerald-300 rounded-md p-2 bg-white"
                        :value="summaryEditSections.one_liner"
                        maxlength="2000"
                        @input="onSummaryOneLinerInput"
                      />
                    </template>
                    <template v-else>
                      <div class="text-sm text-emerald-900">{{ effectiveSummaryParts.oneLiner || '（空）' }}</div>
                    </template>
                  </div>
                </div>
              </div>

              <div v-show="activeTab==='highlights'">
                <ul class="list-disc pl-5 space-y-1 text-sm text-gray-800">
                  <li v-for="(h, idx) in (summaryResult.highlights || [])" :key="idx">
                    [{{ formatDuration(h.ts || 0) }}] {{ h.text }}
                  </li>
                </ul>
              </div>

              <div v-show="activeTab==='transcript'">
                <div class="flex items-center justify-between gap-3 mb-2">
                  <div class="text-xs text-gray-500">
                    来源：{{ subtitleSource || summaryResult.transcript_source || '-' }}
                    <span v-if="subtitleSegments.length" class="text-gray-400"> · </span>
                    <span v-if="subtitleSegments.length">片段数：{{ subtitleSegments.length }}</span>
                  </div>
                  <div class="flex items-center gap-2">
                    <button class="px-2 py-1 text-xs border border-gray-300 rounded bg-white hover:bg-gray-50" @click="transcriptExpanded=!transcriptExpanded">
                      {{ transcriptExpanded ? '收起' : '展开' }}
                    </button>
                    <a
                      v-if="summaryTaskId"
                      class="px-2 py-1 text-xs border border-gray-300 rounded bg-white hover:bg-gray-50"
                      :href="apiSubtitleDownloadUrl(summaryTaskId,'srt')"
                    >下载 SRT</a>
                    <a
                      v-if="summaryTaskId"
                      class="px-2 py-1 text-xs border border-gray-300 rounded bg-white hover:bg-gray-50"
                      :href="apiSubtitleDownloadUrl(summaryTaskId,'vtt')"
                    >下载 VTT</a>
                    <a
                      v-if="summaryTaskId"
                      class="px-2 py-1 text-xs border border-gray-300 rounded bg-white hover:bg-gray-50"
                      :href="apiSubtitleDownloadUrl(summaryTaskId,'txt')"
                    >下载 TXT</a>
                  </div>
                </div>

                <div v-if="subtitleSegments.length" class="border border-gray-200 rounded bg-white">
                  <div
                    class="max-h-80 overflow-auto divide-y"
                    :class="transcriptExpanded ? '' : 'max-h-56'"
                  >
                    <div v-for="(seg, idx) in subtitleSegments" :key="idx" class="p-2 text-xs text-gray-800">
                      <span class="font-mono text-gray-500">[{{ formatTs(seg.start || 0) }}]</span>
                      <span class="ml-2">{{ seg.text }}</span>
                    </div>
                  </div>
                </div>
                <pre v-else class="max-h-64 overflow-auto whitespace-pre-wrap bg-gray-50 border border-gray-200 rounded p-3 text-xs text-gray-800">{{ summaryResult.transcript_text || '' }}</pre>
              </div>

              <div v-show="activeTab==='mindmap'" class="text-sm text-gray-700">
                <div class="mb-2 text-xs text-gray-500">{{ mindmapSavingText }}</div>
                <MindmapFlow :key="summaryTaskId || 'mindmap-idle'" :mindmap="mindmapData" @change="onMindmapChange" />
              </div>

              <div v-show="activeTab==='qa'">
                <div class="text-xs text-gray-500 mb-2">基于当前任务上下文（多轮对话）</div>
                <div class="max-h-56 overflow-auto border border-gray-200 rounded-md p-2 bg-gray-50 mb-3">
                  <div v-if="!qaMessages.length" class="text-xs text-gray-400">暂无对话，输入问题开始。</div>
                  <div v-for="(m, idx) in qaMessages" :key="idx" class="mb-2">
                    <div class="text-[11px] text-gray-500">{{ m.role === 'user' ? '你' : 'AI' }}</div>
                    <div class="text-sm text-gray-800 whitespace-pre-wrap">{{ m.content }}</div>
                  </div>
                </div>
                <div class="flex gap-2">
                  <input v-model="qaQuestion" class="flex-1 px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-slate-600" placeholder="基于当前视频内容提问..." />
                  <button class="px-4 py-2 rounded-md font-bold bg-slate-800 text-white hover:bg-slate-900 disabled:opacity-60" :disabled="qaLoading" @click="onAsk">
                    提问
                  </button>
                </div>
                <div class="mt-3 text-sm text-gray-800 whitespace-pre-wrap">{{ qaAnswer }}</div>
              </div>

              <div
                v-if="summaryResult && !['summary','highlights','transcript','mindmap','qa'].includes(activeTab)"
                class="text-sm text-gray-500"
              >
                自定义标签「{{ tabs.find(t => t.id === activeTab)?.name || activeTab }}」已就绪。
              </div>
            </div>

            <div v-if="streamBuffer && !summaryResult" class="mt-3">
              <div class="text-xs text-gray-500 mb-2">流式输出（实时生成中）</div>
              <pre class="max-h-56 overflow-auto whitespace-pre-wrap bg-gray-50 border border-gray-200 rounded p-3 text-xs text-gray-700">{{ streamBuffer }}</pre>
            </div>
          </div>
        </section>
      </div>
    </main>
  </div>
</template>

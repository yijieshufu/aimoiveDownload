<script setup>
import { computed, nextTick, onMounted, ref } from 'vue';
import {
  apiAbsolute,
  apiDownload,
  apiDownloadFileUrl,
  apiExtract,
  apiGetMindmap,
  apiGetTabs,
  apiSaveMindmap,
  apiSaveTabs,
  apiSummarize,
  apiSummarizeQa,
  apiSummarizeStatus,
  apiTranslateSummary,
} from './api';
import 'jsmind/style/jsmind.css';
import jsMind from 'jsmind';

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

const qaQuestion = ref('');
const qaAnswer = ref('');
const qaLoading = ref(false);
const translatingSummary = ref(false);
const mindmapSavingText = ref('');
const mindmapContainer = ref(null);
let jm = null;
let saveMindmapTimer = null;
let nodeSeq = 10000;

const summaryDownloadUrl = computed(() => {
  const u = summaryResult.value?.markdown_download_url;
  return apiAbsolute(u);
});

function setProgress(p, text) {
  const n = Math.max(0, Math.min(100, Number(p) || 0));
  summaryProgress.value = n;
  if (text) summaryProgressText.value = text;
}

function visibleTabs() {
  return (tabs.value || [])
    .filter((t) => t.visible !== false)
    .sort((a, b) => (a.order_index || 0) - (b.order_index || 0));
}

async function loadTabs() {
  const data = await apiGetTabs();
  tabs.value = data.tabs || [];
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
  const name = prompt('Tab name', 'Custom');
  if (!name) return;
  const id = `custom_${Date.now()}`;
  tabs.value.push({ id, name: name.trim(), type: 'custom', order_index: tabs.value.length, visible: true });
  await persistTabs();
}

async function renameTab(tab) {
  const name = prompt('Rename tab', tab.name || '');
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
  qaAnswer.value = '';
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
  setProgress(5, '创建任务');
  try {
    const { task_id } = await apiSummarize(resolvedUrl.value);
    summaryTaskId.value = task_id;
    setProgress(10, '任务已创建');
    for (let i = 0; i < 160; i++) {
      const s = await apiSummarizeStatus(task_id);
      summaryStage.value = s.stage || '';
      updateProgressByStage(s.stage);
      if (s.status === 'completed') {
        setProgress(100, '完成');
        summaryResult.value = s.result || {};
        await loadMindmapForTask(task_id, summaryResult.value?.mindmap || {});
        break;
      }
      if (s.status === 'failed') {
        setProgress(100, '失败');
        throw new Error(s.error || '总结失败');
      }
      await new Promise((r) => setTimeout(r, 1500));
    }
  } catch (e) {
    summaryError.value = String(e?.message || e);
  } finally {
    isSummarizing.value = false;
  }
}

function toJsMindData(mindmap) {
  const rootTitle = String(mindmap?.title || 'Video Topic');
  const isBadName = (name) => {
    const s = String(name || '').trim();
    if (!s) return true;
    return ['(', ')', '[]', '[', ']', '{}', '{', '}', '（）'].includes(s.replace(/\s+/g, ''));
  };
  const convert = (node) => {
    if (!node || typeof node !== 'object') return null;
    const id = String(node.id || `n${++nodeSeq}`);
    let topic = String(node.name || 'Node').trim();
    if (isBadName(topic)) topic = '';
    const children = (Array.isArray(node.children) ? node.children : []).map(convert).filter(Boolean);
    if (!topic && children.length === 0) return null;
    if (!topic) topic = 'Node';
    return { id, topic, children };
  };
  const children = (Array.isArray(mindmap?.children) ? mindmap.children : []).map(convert).filter(Boolean).slice(0, 8);
  return {
    meta: { name: 'video-mindmap', author: 'aimovie', version: '1.0' },
    format: 'node_tree',
    data: { id: 'root', topic: rootTitle, children },
  };
}

function renderMindmapEditor(mindmap) {
  if (!mindmapContainer.value) return;
  mindmapContainer.value.innerHTML = '';
  jm = new jsMind({
    container: mindmapContainer.value,
    editable: true,
    theme: 'primary',
    mode: 'full',
  });
  jm.show(toJsMindData(mindmap));
  if (typeof jm.add_event_listener === 'function') {
    jm.add_event_listener(() => {
      if (summaryTaskId.value) scheduleMindmapSave();
    });
  }
}

function exportMindmapFromEditor() {
  if (!jm) return null;
  const d = jm.get_data('node_tree');
  const walk = (node) => {
    const children = (node.children || []).map(walk);
    if (node.id === 'root') return { title: node.topic || 'Video Topic', children };
    return { id: node.id, name: node.topic || 'Node', children, start: 0, end: 0, importance: 3 };
  };
  return walk(d.data);
}

function scheduleMindmapSave() {
  if (!summaryTaskId.value) return;
  if (saveMindmapTimer) clearTimeout(saveMindmapTimer);
  mindmapSavingText.value = 'Auto-saving...';
  saveMindmapTimer = setTimeout(async () => {
    try {
      const mindmap = exportMindmapFromEditor();
      if (mindmap) await apiSaveMindmap(summaryTaskId.value, mindmap);
      mindmapSavingText.value = 'Saved';
      setTimeout(() => {
        if (mindmapSavingText.value === 'Saved') mindmapSavingText.value = '';
      }, 1200);
    } catch {
      mindmapSavingText.value = 'Save failed';
    }
  }, 600);
}

async function loadMindmapForTask(taskId, fallbackMindmap) {
  await nextTick();
  try {
    const saved = await apiGetMindmap(taskId);
    const mm = saved?.mindmap || fallbackMindmap || { title: 'Video Topic', children: [] };
    renderMindmapEditor(mm);
  } catch {
    renderMindmapEditor(fallbackMindmap || { title: 'Video Topic', children: [] });
  }
}

function selectedNode() {
  if (!jm) return null;
  return jm.get_selected_node();
}

function addChildNode() {
  const s = selectedNode();
  if (!s) return;
  const topic = prompt('Child node name', 'New node');
  if (!topic) return;
  jm.add_node(s, `n${++nodeSeq}`, topic);
  scheduleMindmapSave();
}

function addSiblingNode() {
  const s = selectedNode();
  if (!s || !s.parent) return;
  const topic = prompt('Sibling node name', 'New sibling');
  if (!topic) return;
  jm.add_node(s.parent, `n${++nodeSeq}`, topic);
  scheduleMindmapSave();
}

function renameNode() {
  const s = selectedNode();
  if (!s) return;
  const topic = prompt('Rename node', s.topic || '');
  if (!topic) return;
  jm.update_node(s.id, topic);
  scheduleMindmapSave();
}

function deleteNode() {
  const s = selectedNode();
  if (!s || s.id === 'root') return;
  if (!confirm(`Delete node "${s.topic}"?`)) return;
  jm.remove_node(s);
  scheduleMindmapSave();
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
    const data = await apiSummarizeQa(summaryTaskId.value, q);
    qaAnswer.value = data.answer || '';
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
                {{ videoInfo.uploader }} · {{ formatDuration(videoInfo.duration) }} · {{ formatViews(videoInfo.view_count) }} views
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
              <span v-if="summaryResult?.output_language" class="text-gray-400"> · </span>
              <span v-if="summaryResult?.output_language">语言: {{ summaryResult.output_language.toUpperCase() }}</span>
            </div>
            <div class="w-full bg-gray-200 rounded-full h-2.5 mb-4">
              <div class="h-2.5 rounded-full bg-emerald-600 transition-all" :style="{ width: `${summaryProgress}%` }"></div>
            </div>

            <div v-if="summaryError" class="text-sm text-red-600 mb-3">{{ summaryError }}</div>

            <div class="flex items-center gap-2 mb-2">
              <button class="px-3 py-1.5 text-xs rounded border border-gray-300 bg-white hover:bg-gray-50" @click="tabEditing=!tabEditing">
                {{ tabEditing ? 'Done' : 'Edit Tabs' }}
              </button>
              <button class="px-3 py-1.5 text-xs rounded border border-gray-300 bg-white hover:bg-gray-50" @click="addTab">+ Add Tab</button>
            </div>
            <div class="flex flex-wrap gap-2 mb-4">
              <div v-for="t in visibleTabs()" :key="t.id" class="inline-flex items-center gap-1">
                <button
                  class="px-3 py-1.5 text-xs rounded border"
                  :class="activeTab===t.id ? 'bg-emerald-50 border-emerald-200' : 'bg-white border-gray-300'"
                  @click="activeTab=t.id"
                >
                  {{ t.name }}
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
                <ul class="list-disc pl-5 space-y-1 text-sm text-gray-800">
                  <li v-for="(s, idx) in (summaryResult.summary || [])" :key="idx">{{ s }}</li>
                </ul>
              </div>

              <div v-show="activeTab==='chapters'" class="space-y-3">
                <div v-for="(ch, idx) in (summaryResult.chapters || [])" :key="idx" class="border border-gray-200 rounded-lg p-3">
                  <div class="font-semibold text-sm text-slate-900">
                    {{ formatDuration(ch.start || 0) }} - {{ formatDuration(ch.end || 0) }} | {{ ch.title }}
                  </div>
                  <ul class="list-disc pl-5 mt-2 text-sm text-gray-800">
                    <li v-for="(p, pIdx) in (ch.points || [])" :key="pIdx">{{ p }}</li>
                  </ul>
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
                <div class="text-xs text-gray-500 mb-2">来源：{{ summaryResult.transcript_source || '-' }}</div>
                <pre class="max-h-64 overflow-auto whitespace-pre-wrap bg-gray-50 border border-gray-200 rounded p-3 text-xs text-gray-800">{{ summaryResult.transcript_text || '' }}</pre>
              </div>

              <div v-show="activeTab==='mindmap'" class="text-sm text-gray-700">
                <div class="flex flex-wrap gap-2 mb-2">
                  <button class="px-2 py-1 text-xs border border-gray-300 rounded" @click="addChildNode">Add Child</button>
                  <button class="px-2 py-1 text-xs border border-gray-300 rounded" @click="addSiblingNode">Add Sibling</button>
                  <button class="px-2 py-1 text-xs border border-gray-300 rounded" @click="renameNode">Rename</button>
                  <button class="px-2 py-1 text-xs border border-gray-300 rounded" @click="deleteNode">Delete</button>
                  <span class="text-xs text-gray-500">{{ mindmapSavingText }}</span>
                </div>
                <div ref="mindmapContainer" class="border border-gray-200 rounded-md bg-white" style="height: 520px; overflow: auto;"></div>
              </div>

              <div v-show="activeTab==='qa'">
                <div class="flex gap-2">
                  <input v-model="qaQuestion" class="flex-1 px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-slate-600" placeholder="基于当前视频内容提问..." />
                  <button class="px-4 py-2 rounded-md font-bold bg-slate-800 text-white hover:bg-slate-900 disabled:opacity-60" :disabled="qaLoading" @click="onAsk">
                    提问
                  </button>
                </div>
                <div class="mt-3 text-sm text-gray-800 whitespace-pre-wrap">{{ qaAnswer }}</div>
              </div>

              <div
                v-if="summaryResult && !['summary','chapters','highlights','transcript','mindmap','qa'].includes(activeTab)"
                class="text-sm text-gray-500"
              >
                Custom tab "{{ tabs.find(t => t.id === activeTab)?.name || activeTab }}" is ready.
              </div>
            </div>
          </div>
        </section>
      </div>
    </main>
  </div>
</template>

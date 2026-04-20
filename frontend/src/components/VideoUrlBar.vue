<script setup>
import { BookOpen, Link2, Search } from 'lucide-vue-next';

const inputText = defineModel({ type: String, default: '' });

defineProps({
  isExtracting: { type: Boolean, default: false },
  isSummarizing: { type: Boolean, default: false },
  extractError: { type: String, default: '' },
});

defineEmits(['extract', 'summarize', 'try-sample']);

const trySamples = [
  { label: 'YouTube', url: 'https://www.youtube.com/watch?v=jNQXAC9IVRw' },
  { label: 'Bilibili', url: 'https://www.bilibili.com/video/BV1GJ411x7h7' },
  { label: '抖音', url: 'https://www.iesdouyin.com/share/video/6961737553342991651/' },
];
</script>

<template>
  <div id="video-url-anchor" class="scroll-mt-24">
    <div class="relative mb-4 sm:mb-5 mt-1">
      <div class="flex justify-center">
        <div
          class="url-bar-shell w-full max-w-2xl rounded-full border border-slate-200/90 bg-white pl-3 sm:pl-4 pr-2 py-2 shadow-[0_8px_30px_rgba(15,23,42,0.08)] flex flex-col sm:flex-row sm:items-center gap-2"
        >
          <div class="flex items-center gap-2 min-w-0 flex-1">
            <div class="h-9 w-9 shrink-0 rounded-full bg-slate-100 flex items-center justify-center text-slate-400">
              <Link2 class="w-4 h-4" />
            </div>
            <input
              v-model="inputText"
              class="flex-1 min-w-0 bg-transparent py-2.5 sm:py-2 text-sm text-slate-800 placeholder:text-slate-400 focus:outline-none min-h-[44px] sm:min-h-0"
              placeholder="https://www.youtube.com/watch?v=… 粘贴视频链接"
              autocomplete="off"
              autocapitalize="off"
              @keyup.enter="$emit('extract')"
            />
          </div>
          <div class="flex items-center justify-end shrink-0 pl-1 sm:pl-0">
            <button
              type="button"
              class="h-11 min-w-0 px-4 sm:px-5 rounded-full bg-[#2563eb] text-white text-sm font-semibold inline-flex items-center justify-center gap-2 shadow-md shadow-blue-500/30 hover:bg-[#1d4ed8] disabled:opacity-50 transition active:scale-[0.98]"
              :disabled="isExtracting"
              title="解析视频信息"
              aria-label="解析视频"
              @click="$emit('extract')"
            >
              <Search class="w-4 h-4 shrink-0 opacity-95" />
              <span class="whitespace-nowrap">{{ isExtracting ? '解析中…' : '解析视频' }}</span>
            </button>
          </div>
        </div>
      </div>
    </div>

    <div class="flex flex-wrap items-center justify-center gap-2 mb-4 text-sm">
      <span class="text-slate-500">试试：</span>
      <button
        v-for="s in trySamples"
        :key="s.label"
        type="button"
        class="rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 hover:border-blue-200 hover:bg-blue-50/80 hover:text-[#2563eb] transition"
        @click="$emit('try-sample', s.url)"
      >
        {{ s.label }}
      </button>
    </div>

    <div class="flex flex-wrap items-center justify-center gap-2 sm:gap-2.5 mb-2">
      <button
        type="button"
        class="min-h-10 px-4 py-2 rounded-full text-xs font-semibold text-slate-800 border border-slate-200/90 bg-white shadow-sm hover:bg-slate-50 hover:border-slate-300 disabled:opacity-55 transition active:scale-[0.99]"
        :disabled="isExtracting"
        title="仅解析视频信息与格式"
        @click="$emit('extract')"
      >
        {{ isExtracting ? '解析中…' : '解析' }}
      </button>
      <button
        type="button"
        class="min-h-10 px-4 py-2 rounded-full text-xs font-semibold text-violet-900 border border-violet-200/90 bg-gradient-to-b from-white to-violet-50/90 shadow-sm shadow-violet-500/10 hover:border-violet-300 hover:to-violet-50 disabled:opacity-55 inline-flex items-center gap-1.5 transition active:scale-[0.99]"
        :disabled="isSummarizing"
        title="生成结构化 AI 笔记"
        data-magnetic
        @click="$emit('summarize')"
      >
        <BookOpen class="w-3.5 h-3.5 shrink-0 text-violet-700" />
        {{ isSummarizing ? '生成中…' : 'AI 笔记' }}
      </button>
    </div>

    <div v-if="extractError" class="mb-4 text-xs text-rose-600 text-center max-w-2xl mx-auto break-words">
      {{ extractError }}
    </div>
  </div>
</template>

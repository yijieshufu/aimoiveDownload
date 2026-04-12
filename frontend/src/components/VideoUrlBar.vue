<script setup>
import { Link2, Search, Sparkles } from 'lucide-vue-next';

const inputText = defineModel({ type: String, default: '' });

defineProps({
  isExtracting: { type: Boolean, default: false },
  isSummarizing: { type: Boolean, default: false },
  extractError: { type: String, default: '' },
});

defineEmits(['extract', 'extract-batch', 'summarize', 'try-sample']);

const trySamples = [
  { label: 'YouTube', url: 'https://www.youtube.com/watch?v=jNQXAC9IVRw' },
  { label: 'Bilibili', url: 'https://www.bilibili.com/video/BV1GJ411x7h7' },
  { label: 'Twitter/X', url: 'https://twitter.com/wikipedia/status/1899283078310842368' },
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
          <div class="flex items-center justify-end gap-2 shrink-0 pl-1 sm:pl-0">
            <button
              type="button"
              class="h-11 w-11 sm:h-10 sm:w-10 rounded-full bg-[#2563eb] text-white flex items-center justify-center shadow-md shadow-blue-500/30 hover:bg-[#1d4ed8] disabled:opacity-50 transition active:scale-[0.98]"
              :disabled="isExtracting"
              title="解析链接"
              aria-label="解析链接"
              @click="$emit('extract')"
            >
              <Search class="w-5 h-5" />
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

    <div class="flex flex-wrap items-center justify-center gap-2 mb-2">
      <button
        type="button"
        class="min-h-10 px-3 py-2 rounded-full text-xs font-medium text-slate-600 border border-slate-200 bg-white hover:bg-slate-50 disabled:opacity-60"
        :disabled="isExtracting"
        title="每行一条链接，按顺序解析"
        @click="$emit('extract-batch')"
      >
        串行批量
      </button>
      <button
        type="button"
        class="min-h-10 px-4 py-2 rounded-full text-xs font-medium text-slate-700 border border-slate-200 bg-slate-50 hover:bg-slate-100 disabled:opacity-60"
        :disabled="isExtracting"
        @click="$emit('extract')"
      >
        {{ isExtracting ? '解析中…' : '解析' }}
      </button>
      <button
        type="button"
        class="min-h-10 px-4 py-2 rounded-full text-xs font-semibold text-white bg-gradient-to-r from-[#2563eb] to-sky-500 shadow-md shadow-blue-500/20 disabled:opacity-60 inline-flex items-center gap-1.5"
        :disabled="isSummarizing"
        data-magnetic
        @click="$emit('summarize')"
      >
        <Sparkles class="w-3.5 h-3.5" />
        {{ isSummarizing ? '生成中…' : 'AI 分析' }}
      </button>
    </div>

    <div v-if="extractError" class="mb-4 text-xs text-rose-600 text-center max-w-2xl mx-auto break-words">
      {{ extractError }}
    </div>
  </div>
</template>

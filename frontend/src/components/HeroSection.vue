<script setup>
import { computed } from 'vue';

const props = defineProps({
  usageHint: { type: String, default: '' },
});

const hintVisible = computed(() => Boolean(props.usageHint?.trim()));
</script>

<template>
  <section class="hero-section mb-6 sm:mb-8 text-center px-1">
    <div class="flex flex-wrap items-center justify-center gap-2 mb-5">
      <span
        class="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 shadow-sm"
      >
        <span class="h-2 w-2 rounded-full bg-emerald-500 shrink-0" aria-hidden="true"></span>
        支持多平台链接解析，核心功能免费使用
      </span>
      <span
        v-if="hintVisible"
        class="inline-flex rounded-full border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs text-slate-600"
      >
        {{ usageHint }}
      </span>
    </div>

    <h1
      class="text-2xl sm:text-3xl md:text-[2.15rem] font-bold tracking-tight text-slate-900 leading-tight max-w-2xl mx-auto"
    >
      万能视频下载器，<span class="text-[#2563eb]">一键保存</span>
    </h1>
    <p class="mt-3 text-sm sm:text-[15px] text-slate-500 max-w-xl mx-auto leading-relaxed">
      粘贴视频链接，智能解析，支持多种清晰度下载。YouTube、Bilibili、抖音、TikTok…随时随地，想下就下。请仅下载你有权使用的内容。
    </p>
  </section>
</template>

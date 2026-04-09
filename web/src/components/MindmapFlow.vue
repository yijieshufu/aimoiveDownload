<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue';
import { VueFlow, useVueFlow } from '@vue-flow/core';
import { Controls } from '@vue-flow/controls';
import { Background } from '@vue-flow/background';
import '@vue-flow/core/dist/style.css';
import '@vue-flow/core/dist/theme-default.css';
import '@vue-flow/controls/dist/style.css';
import { toPng, toSvg } from 'html-to-image';

const props = defineProps({
  mindmap: { type: Object, default: () => ({ title: '视频主题', children: [] }) },
});
const emit = defineEmits(['change']);

const flowWrap = ref(null);
const renameInputRef = ref(null);
const selectedNodeId = ref('');
const isFullscreen = ref(false);
const isExporting = ref(false);

const RENAME_DIALOG_CLOSED = { visible: false, nodeId: '', value: '', title: '重命名节点', isNew: false };
const renameDialog = ref({ ...RENAME_DIALOG_CLOSED });
const contextMenu = ref({ visible: false, x: 0, y: 0, nodeId: '' });

const nodes = ref([]);
const edges = ref([]);
const nodeMap = ref(new Map());
const { fitView, zoomIn, zoomOut, setCenter } = useVueFlow();

function cleanName(name) {
  const s = String(name || '').trim();
  if (!s) return '';
  if (/^[\-\_=~`!@#$%^&*(){}\[\]|\\:;"'<>,.?/，。！？；：、（）【】《》]+$/.test(s)) return '';
  return s.slice(0, 40);
}

function sanitizeTree(root) {
  const title = cleanName(root?.title) || '视频主题';
  const dedup = new Set();
  function walk(node, depth = 1) {
    if (!node || depth > 4) return null;
    const name = cleanName(node.name || node.title);
    const children = (Array.isArray(node.children) ? node.children : []).map((c) => walk(c, depth + 1)).filter(Boolean);
    if (!name && children.length === 0) return null;
    return {
      id: String(node.id || `n_${Math.random().toString(16).slice(2, 8)}`),
      name: name || '节点',
      start: Number(node.start || 0),
      end: Number(node.end || 0),
      importance: Math.max(1, Math.min(5, Number(node.importance || 3))),
      children: children.slice(0, 8),
    };
  }
  const children = [];
  for (const c of root?.children || []) {
    const x = walk(c, 1);
    if (!x) continue;
    const k = x.name.toLowerCase().replace(/\s+/g, '');
    if (dedup.has(k)) continue;
    dedup.add(k);
    children.push(x);
  }
  return { title, children: children.slice(0, 8) };
}

function mindmapStructureSignature(tree) {
  function nodeSig(node) {
    return [node.id, node.name, (node.children || []).map(nodeSig)];
  }
  return JSON.stringify([tree.title, (tree.children || []).map(nodeSig)]);
}

function buildGraph(tree, opts = {}) {
  const preservePositions = opts.preservePositions !== false;
  const prevPos = preservePositions ? new Map(nodes.value.map((x) => [x.id, { ...x.position }])) : new Map();

  const palette = ['#f97316', '#ef4444', '#22c55e', '#3b82f6', '#a855f7', '#14b8a6', '#f59e0b', '#06b6d4'];
  const n = [];
  const e = [];
  const map = new Map();

  const colW = 230;
  const rowH = 78;
  const gapY = 12;
  const gapBranch = 24;
  const branchDeltaX = 36;

  function subtreeHeight(node) {
    const ch = node.children || [];
    if (ch.length === 0) return rowH;
    let h = 0;
    ch.forEach((c, i) => {
      h += subtreeHeight(c);
      if (i < ch.length - 1) h += gapY;
    });
    return Math.max(rowH, h);
  }

  function edgeDefaults(stroke, strokeWidth) {
    return {
      type: 'smoothstep',
      animated: false,
      style: {
        '--mm-edge': stroke,
        stroke: 'var(--mm-edge)',
        strokeWidth,
      },
    };
  }

  function placeDescendants(parentNode, parentId, bandTop, bandBottom, sign, color, branchIdx, depth) {
    const children = parentNode.children || [];
    if (children.length === 0) return;
    const totalInner = children.reduce((acc, c, i) => acc + subtreeHeight(c) + (i < children.length - 1 ? gapY : 0), 0);
    let y = bandTop + (bandBottom - bandTop - totalInner) / 2;
    const x = sign * (colW * depth + branchIdx * branchDeltaX);

    children.forEach((child) => {
      const h = subtreeHeight(child);
      const cy = y + h / 2;
      n.push({
        id: child.id,
        type: 'default',
        position: { x, y: cy },
        data: { label: child.name, mmBranchColor: color },
        style: {
          '--mm-bg': '#f8fafc',
          '--mm-border': `${color}66`,
          background: 'var(--mm-bg)',
          color: '#0f172a',
          borderRadius: '10px',
          padding: '6px 10px',
          border: '1px solid var(--mm-border)',
        },
        draggable: true,
      });
      e.push({
        id: `e_${parentId}_${child.id}`,
        source: parentId,
        target: child.id,
        ...edgeDefaults(color, 1.6),
      });
      map.set(child.id, child);
      placeDescendants(child, child.id, y, y + h, sign, color, branchIdx, depth + 1);
      y += h + gapY;
    });
  }

  function placeSide(sideList, sign) {
    if (!sideList.length) return;
    const totalH = sideList.reduce((s, it) => s + subtreeHeight(it.node) + gapBranch, 0) - gapBranch;
    let yTop = -totalH / 2;

    sideList.forEach((item, branchIdx) => {
      const th = subtreeHeight(item.node);
      const yCenter = yTop + th / 2;
      n.push({
        id: item.node.id,
        type: 'default',
        position: { x: sign * colW, y: yCenter },
        data: { label: item.node.name, mmBranchColor: item.color },
        style: {
          '--mm-bg': item.color,
          '--mm-border': item.color,
          background: 'var(--mm-bg)',
          color: '#fff',
          borderRadius: '12px',
          padding: '6px 10px',
          border: '1px solid var(--mm-border)',
        },
        draggable: true,
      });
      e.push({
        id: `e_root_${item.node.id}`,
        source: 'root',
        target: item.node.id,
        ...edgeDefaults(item.color, 2.5),
      });
      map.set(item.node.id, item.node);
      placeDescendants(item.node, item.node.id, yTop, yTop + th, sign, item.color, branchIdx, 2);
      yTop += th + gapBranch;
    });
  }

  n.push({
    id: 'root',
    type: 'default',
    position: { x: 0, y: 0 },
    data: { label: tree.title, mmRoot: true },
    style: {
      '--mm-bg': '#0f172a',
      '--mm-border': '#0f172a',
      background: 'var(--mm-bg)',
      color: '#fff',
      borderRadius: '14px',
      padding: '8px 14px',
      border: '1px solid var(--mm-border)',
    },
    draggable: true,
  });
  map.set('root', { title: tree.title, children: [] });

  const right = [];
  const left = [];
  (tree.children || []).forEach((c, idx) =>
    (idx % 2 === 0 ? right : left).push({ node: c, parent: 'root', color: palette[idx % palette.length] })
  );

  placeSide(right, 1);
  placeSide(left, -1);

  if (preservePositions) {
    for (const node of n) {
      const p = prevPos.get(node.id);
      if (p) node.position = { ...p };
    }
  }

  nodes.value = n;
  edges.value = e;
  nodeMap.value = map;
}

function exportTreeFromGraph() {
  const idToNode = new Map();
  const root = { title: '', children: [] };
  const rootNode = nodes.value.find((x) => x.id === 'root');
  root.title = String(rootNode?.data?.label || '视频主题');
  for (const n of nodes.value) {
    if (n.id === 'root') continue;
    const raw = nodeMap.value.get(n.id) || {};
    idToNode.set(n.id, { id: n.id, name: String(n.data?.label || '节点'), start: Number(raw.start || 0), end: Number(raw.end || 0), importance: Number(raw.importance || 3), children: [] });
  }
  const edgeBySource = new Map();
  for (const x of edges.value) {
    const arr = edgeBySource.get(x.source) || [];
    arr.push(x.target);
    edgeBySource.set(x.source, arr);
  }
  function buildChildren(parentId) {
    const ids = edgeBySource.get(parentId) || [];
    return ids.map((id) => {
      const node = idToNode.get(id);
      if (!node) return null;
      node.children = buildChildren(id);
      return node;
    }).filter(Boolean);
  }
  root.children = buildChildren('root');
  return sanitizeTree(root);
}

function emitChange() {
  emit('change', exportTreeFromGraph());
}

function onNodeDragStop() {
  emitChange();
}

function closeContextMenu() {
  contextMenu.value = { ...contextMenu.value, visible: false };
}

function openRenameDialog(nodeId, opts = {}) {
  const node = nodes.value.find((x) => x.id === nodeId);
  if (!node) return;
  closeContextMenu();
  renameDialog.value = {
    visible: true,
    nodeId,
    value: String(node.data?.label || ''),
    title: opts.title || '重命名节点',
    isNew: Boolean(opts.isNew),
  };
}

function openAddNodeDialog(pid) {
  const parent = nodes.value.find((x) => x.id === pid);
  if (!parent) return;
  closeContextMenu();
  const id = `n_${Date.now().toString(16)}_${Math.random().toString(16).slice(2, 6)}`;
  const p = parent;
  nodes.value.push({
    id,
    position: { x: p.position.x + 220, y: p.position.y + 40 },
    data: { label: '新节点' },
    style: {
      '--mm-bg': '#f8fafc',
      '--mm-border': '#cbd5e1',
      background: 'var(--mm-bg)',
      border: '1px solid var(--mm-border)',
      borderRadius: '10px',
      padding: '6px 10px',
    },
    draggable: true,
  });
  edges.value.push({
    id: `e_${pid}_${id}`,
    source: pid,
    target: id,
    type: 'smoothstep',
    animated: false,
    style: {
      '--mm-edge': '#94a3b8',
      stroke: 'var(--mm-edge)',
      strokeWidth: 1.8,
    },
  });
  selectedNodeId.value = id;
  renameDialog.value = {
    visible: true,
    nodeId: id,
    value: '',
    title: '新建节点',
    isNew: true,
  };
}

function confirmRenameDialog() {
  const { nodeId, value } = renameDialog.value;
  const node = nodes.value.find((x) => x.id === nodeId);
  if (node) {
    const t = String(value || '').trim() || (nodeId === 'root' ? '视频主题' : '节点');
    node.data = { ...node.data, label: t.slice(0, 40) };
    emitChange();
  }
  renameDialog.value = { ...RENAME_DIALOG_CLOSED };
}

function cancelRenameDialog() {
  const { nodeId, isNew } = renameDialog.value;
  if (isNew && nodeId) {
    nodes.value = nodes.value.filter((n) => n.id !== nodeId);
    edges.value = edges.value.filter((e) => e.target !== nodeId && e.source !== nodeId);
    if (selectedNodeId.value === nodeId) selectedNodeId.value = '';
    emitChange();
  }
  renameDialog.value = { ...RENAME_DIALOG_CLOSED };
}

function onNodeContextMenu(evt) {
  const e = evt?.event || evt;
  if (e?.preventDefault) e.preventDefault();
  const node = evt?.node;
  if (!node) return;
  contextMenu.value = { visible: true, x: e.clientX, y: e.clientY, nodeId: node.id };
}

function onNodeDoubleClick(evt) {
  const node = evt?.node;
  if (node) openRenameDialog(node.id);
}

function onPaneClick() {
  closeContextMenu();
}

function contextAddChild() {
  const pid = contextMenu.value.nodeId || 'root';
  closeContextMenu();
  openAddNodeDialog(pid);
}

function contextAddSibling() {
  const sid = contextMenu.value.nodeId;
  closeContextMenu();
  if (!sid || sid === 'root') return;
  const parentEdge = edges.value.find((x) => x.target === sid);
  if (!parentEdge) return;
  openAddNodeDialog(parentEdge.source);
}

function contextRename() {
  const id = contextMenu.value.nodeId;
  closeContextMenu();
  if (id) openRenameDialog(id);
}

function contextDelete() {
  const sid = contextMenu.value.nodeId;
  closeContextMenu();
  if (!sid || sid === 'root') return;
  selectedNodeId.value = sid;
  deleteNode();
}

function addChild() {
  const pid = selectedNodeId.value || 'root';
  openAddNodeDialog(pid);
}

function addSibling() {
  const sid = selectedNodeId.value;
  if (!sid || sid === 'root') return;
  const parentEdge = edges.value.find((x) => x.target === sid);
  if (!parentEdge) return;
  selectedNodeId.value = parentEdge.source;
  addChild();
}

function renameNode() {
  const sid = selectedNodeId.value;
  if (!sid) return;
  openRenameDialog(sid);
}

function deleteNode() {
  const sid = selectedNodeId.value;
  if (!sid || sid === 'root') return;
  const removeSet = new Set([sid]);
  let changed = true;
  while (changed) {
    changed = false;
    for (const e of edges.value) {
      if (removeSet.has(e.source) && !removeSet.has(e.target)) {
        removeSet.add(e.target);
        changed = true;
      }
    }
  }
  nodes.value = nodes.value.filter((n) => !removeSet.has(n.id));
  edges.value = edges.value.filter((e) => !removeSet.has(e.source) && !removeSet.has(e.target));
  selectedNodeId.value = '';
  emitChange();
}

function autoArrange() {
  const tree = exportTreeFromGraph();
  buildGraph(tree, { preservePositions: false });
  setTimeout(() => fitView({ padding: 0.2, includeHiddenNodes: true }), 30);
  emitChange();
}

function centerRoot() {
  const r = nodes.value.find((x) => x.id === 'root');
  if (!r) return;
  setCenter(r.position.x, r.position.y, { duration: 250, zoom: 1 });
}

function toggleFullscreen() {
  isFullscreen.value = !isFullscreen.value;
  setTimeout(() => fitView({ padding: 0.2, includeHiddenNodes: true }), 60);
}

async function exportSvg() {
  if (!flowWrap.value) return;
  isExporting.value = true;
  try {
    const svg = await toSvg(flowWrap.value, { cacheBust: true });
    const blob = new Blob([svg], { type: 'image/svg+xml;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = '思维导图.svg';
    a.click();
    URL.revokeObjectURL(url);
  } finally {
    isExporting.value = false;
  }
}

async function exportPng4k() {
  if (!flowWrap.value) return;
  isExporting.value = true;
  try {
    const rect = flowWrap.value.getBoundingClientRect();
    const scale = Math.max(2, Math.ceil(3840 / Math.max(1, rect.width)));
    const dataUrl = await toPng(flowWrap.value, { cacheBust: true, pixelRatio: scale, backgroundColor: '#ffffff' });
    const a = document.createElement('a');
    a.href = dataUrl;
    a.download = '思维导图_4k.png';
    a.click();
  } finally {
    isExporting.value = false;
  }
}

const lastMindmapSig = ref('');
const didInitialFit = ref(false);

watch(
  () => props.mindmap,
  async (v) => {
    const cleaned = sanitizeTree(v || { title: '视频主题', children: [] });
    const sig = mindmapStructureSignature(cleaned);
    if (sig === lastMindmapSig.value && lastMindmapSig.value !== '') return;
    lastMindmapSig.value = sig;
    buildGraph(cleaned, { preservePositions: true });
    if (!didInitialFit.value) {
      didInitialFit.value = true;
      await nextTick();
      setTimeout(() => fitView({ padding: 0.2, includeHiddenNodes: true }), 20);
    }
  },
  { immediate: true }
);

const rootCls = computed(() => (isFullscreen.value ? 'mindmap-root mindmap-root-fullscreen' : 'mindmap-root'));

const contextMenuSiblingDisabled = computed(() => {
  const id = contextMenu.value.nodeId;
  return !id || id === 'root';
});

const contextMenuDeleteDisabled = computed(() => {
  const id = contextMenu.value.nodeId;
  return !id || id === 'root';
});

function onKeydown(e) {
  if (renameDialog.value.visible) {
    if (e.key === 'Escape') {
      e.preventDefault();
      cancelRenameDialog();
    }
    return;
  }
  if (e.key === 'Escape') {
    closeContextMenu();
    if (isFullscreen.value) {
      e.preventDefault();
      isFullscreen.value = false;
    }
    return;
  }
  const tag = (e.target && e.target.tagName) || '';
  if (tag === 'INPUT' || tag === 'TEXTAREA' || e.target?.isContentEditable) return;
  if (e.key === 'F2') {
    e.preventDefault();
    const sid = selectedNodeId.value;
    if (sid) openRenameDialog(sid);
    return;
  }
  if (e.key === 'Delete' || e.key === 'Backspace') {
    const sid = selectedNodeId.value;
    if (sid && sid !== 'root') {
      e.preventDefault();
      deleteNode();
    }
  }
}

watch(
  () => renameDialog.value.visible,
  async (v) => {
    if (!v) return;
    await nextTick();
    renameInputRef.value?.focus?.();
    renameInputRef.value?.select?.();
  }
);

onMounted(() => {
  window.addEventListener('keydown', onKeydown);
  window.addEventListener('click', onWindowClickCloseMenu);
});

onUnmounted(() => {
  window.removeEventListener('keydown', onKeydown);
  window.removeEventListener('click', onWindowClickCloseMenu);
});

function onWindowClickCloseMenu(e) {
  if (!contextMenu.value.visible) return;
  const t = e.target;
  if (t && t.closest && t.closest('.mindmap-context-menu')) return;
  closeContextMenu();
}
</script>

<template>
  <div :class="rootCls">
    <div class="toolbar">
      <button @click="addChild">添加子节点</button>
      <button @click="addSibling">添加兄弟节点</button>
      <button @click="renameNode">重命名</button>
      <button @click="deleteNode">删除</button>
      <span class="sep"></span>
      <button @click="autoArrange">自动排版</button>
      <button @click="() => fitView({ padding: 0.2, includeHiddenNodes: true })">适应画布</button>
      <button @click="centerRoot">居中根节点</button>
      <button @click="zoomOut">缩小</button>
      <button @click="zoomIn">放大</button>
      <button type="button" @click="toggleFullscreen">{{ isFullscreen ? '退出全屏' : '全屏' }}</button>
      <span class="sep"></span>
      <button :disabled="isExporting" @click="exportSvg">导出 SVG</button>
      <button :disabled="isExporting" @click="exportPng4k">导出 PNG（4K+）</button>
      <span class="toolbar-hint">画布：双击编辑 · 右键菜单 · F2 重命名 · Del 删除</span>
    </div>
    <div ref="flowWrap" class="flow-wrap">
      <VueFlow
        v-model:nodes="nodes"
        v-model:edges="edges"
        :min-zoom="0.2"
        :max-zoom="2.5"
        :nodes-draggable="true"
        :nodes-selectable="false"
        :pan-on-drag="true"
        @node-drag-stop="onNodeDragStop"
        @node-click="({ node }) => (selectedNodeId = node.id)"
        @node-double-click="onNodeDoubleClick"
        @node-context-menu="onNodeContextMenu"
        @pane-click="onPaneClick"
      >
        <Background />
        <Controls />
      </VueFlow>
    </div>

    <Teleport to="body">
      <div
        v-if="contextMenu.visible"
        class="mindmap-context-menu"
        :style="{ position: 'fixed', left: `${contextMenu.x}px`, top: `${contextMenu.y}px`, zIndex: 80 }"
        @click.stop
      >
        <button type="button" @click="contextAddChild">添加子节点</button>
        <button type="button" :disabled="contextMenuSiblingDisabled" @click="contextAddSibling">添加兄弟节点</button>
        <button type="button" @click="contextRename">重命名</button>
        <button type="button" :disabled="contextMenuDeleteDisabled" class="danger" @click="contextDelete">删除</button>
      </div>
    </Teleport>

    <Teleport to="body">
      <div v-if="renameDialog.visible" class="mindmap-rename-overlay" @click.self="cancelRenameDialog">
        <div class="mindmap-rename-box" @click.stop>
          <div class="mindmap-rename-title">{{ renameDialog.title }}</div>
          <input
            ref="renameInputRef"
            v-model="renameDialog.value"
            class="mindmap-rename-input"
            maxlength="40"
            :placeholder="renameDialog.isNew ? '输入节点名称' : ''"
            @keyup.enter="confirmRenameDialog"
          />
          <div class="mindmap-rename-actions">
            <button type="button" @click="cancelRenameDialog">取消</button>
            <button type="button" class="primary" @click="confirmRenameDialog">确定</button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.mindmap-root { display: flex; flex-direction: column; gap: 8px; }
.mindmap-root-fullscreen {
  position: fixed;
  inset: 16px;
  z-index: 60;
  padding: 10px;
  box-sizing: border-box;
  background: #fff;
  border-radius: 16px;
  box-shadow: 0 24px 60px rgba(15, 23, 42, 0.22);
}
.mindmap-root-fullscreen .flow-wrap {
  flex: 1;
  min-height: 0;
  height: auto;
}
.toolbar { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.toolbar button { border: 1px solid #d1d5db; background: #fff; border-radius: 6px; padding: 4px 10px; font-size: 12px; }
.toolbar .sep { width: 1px; background: #e5e7eb; margin: 0 2px; align-self: stretch; min-height: 20px; }
.toolbar-hint { font-size: 11px; color: #94a3b8; margin-left: 4px; }
.flow-wrap {
  height: 520px;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  overflow: hidden;
  background: linear-gradient(180deg, #fff 0%, #f8fbff 100%);
}
/* 拖拽/点击时不要改用 Vue Flow 默认选中高亮（避免「变色」） */
.flow-wrap :deep(.vue-flow__node) {
  transition: none !important;
}
.flow-wrap :deep(.vue-flow__node-default),
.flow-wrap :deep(.vue-flow__node-default:hover),
.flow-wrap :deep(.vue-flow__node.selected .vue-flow__node-default),
.flow-wrap :deep(.vue-flow__node.dragging .vue-flow__node-default),
.flow-wrap :deep(.vue-flow__node:focus .vue-flow__node-default),
.flow-wrap :deep(.vue-flow__node:focus-visible .vue-flow__node-default) {
  background: var(--mm-bg) !important;
  border-color: var(--mm-border) !important;
  box-shadow: none !important;
  outline: none !important;
  filter: none !important;
  opacity: 1 !important;
}
.flow-wrap :deep(.vue-flow__node.selected),
.flow-wrap :deep(.vue-flow__node:focus),
.flow-wrap :deep(.vue-flow__node:focus-visible),
.flow-wrap :deep(.vue-flow__node.dragging) {
  box-shadow: none !important;
  outline: none !important;
  opacity: 1 !important;
  filter: none !important;
}
/* 锁定边线颜色，避免 hover/selected/focus 发生视觉变色 */
.flow-wrap :deep(.vue-flow__edge),
.flow-wrap :deep(.vue-flow__edge:hover),
.flow-wrap :deep(.vue-flow__edge.selected),
.flow-wrap :deep(.vue-flow__edge:focus),
.flow-wrap :deep(.vue-flow__edge:focus-visible),
.flow-wrap :deep(.vue-flow__edge-path),
.flow-wrap :deep(.vue-flow__edge:hover .vue-flow__edge-path),
.flow-wrap :deep(.vue-flow__edge.selected .vue-flow__edge-path),
.flow-wrap :deep(.vue-flow__edge:focus .vue-flow__edge-path),
.flow-wrap :deep(.vue-flow__edge:focus-visible .vue-flow__edge-path) {
  transition: none !important;
  filter: none !important;
  opacity: 1 !important;
}
.flow-wrap :deep(.vue-flow__edge-path),
.flow-wrap :deep(.vue-flow__edge.selected .vue-flow__edge-path),
.flow-wrap :deep(.vue-flow__edge:hover .vue-flow__edge-path),
.flow-wrap :deep(.vue-flow__edge:focus .vue-flow__edge-path),
.flow-wrap :deep(.vue-flow__edge:focus-visible .vue-flow__edge-path) {
  stroke: var(--mm-edge) !important;
}
.mindmap-context-menu {
  display: flex;
  flex-direction: column;
  min-width: 140px;
  padding: 4px 0;
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  box-shadow: 0 10px 40px rgba(15, 23, 42, 0.15);
}
.mindmap-context-menu button {
  border: none;
  background: transparent;
  text-align: left;
  padding: 8px 14px;
  font-size: 13px;
  cursor: pointer;
}
.mindmap-context-menu button:hover:not(:disabled) { background: #f1f5f9; }
.mindmap-context-menu button:disabled { opacity: 0.45; cursor: not-allowed; }
.mindmap-context-menu button.danger { color: #b91c1c; }
.mindmap-rename-overlay {
  position: fixed;
  inset: 0;
  z-index: 85;
  background: rgba(15, 23, 42, 0.35);
  display: flex;
  align-items: center;
  justify-content: center;
}
.mindmap-rename-box {
  background: #fff;
  border-radius: 12px;
  padding: 16px 18px;
  min-width: 280px;
  box-shadow: 0 20px 50px rgba(15, 23, 42, 0.2);
}
.mindmap-rename-title { font-size: 14px; font-weight: 600; margin-bottom: 10px; color: #0f172a; }
.mindmap-rename-input {
  width: 100%;
  box-sizing: border-box;
  padding: 8px 10px;
  border: 1px solid #d1d5db;
  border-radius: 8px;
  font-size: 14px;
}
.mindmap-rename-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 14px; }
.mindmap-rename-actions button {
  padding: 6px 14px;
  border-radius: 6px;
  border: 1px solid #d1d5db;
  background: #fff;
  font-size: 13px;
  cursor: pointer;
}
.mindmap-rename-actions button.primary { background: #0f172a; color: #fff; border-color: #0f172a; }
</style>


<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import type { MessageRecord, MessageState } from "./types";
import {
  ConflictError,
  fetchMessages,
  triggerIngest,
  updateMessageState,
} from "./api";
import MessageCard from "./components/MessageCard.vue";

const records = ref<MessageRecord[]>([]);
const loading = ref(false);
const ingesting = ref(false);
const error = ref<string | null>(null);
const notice = ref<string | null>(null);
const busyIds = ref<Set<string>>(new Set());

const unhandledCount = computed(
  () => records.value.filter((r) => r.state === "unhandled").length,
);

async function load(): Promise<void> {
  loading.value = true;
  error.value = null;
  try {
    records.value = await fetchMessages();
  } catch (e) {
    error.value = e instanceof Error ? e.message : "読み込みに失敗しました.";
  } finally {
    loading.value = false;
  }
}

async function onIngest(): Promise<void> {
  ingesting.value = true;
  error.value = null;
  notice.value = null;
  try {
    await triggerIngest();
    await load();
    notice.value = "取り込みが完了しました.";
  } catch (e) {
    error.value = e instanceof Error ? e.message : "取り込みに失敗しました.";
  } finally {
    ingesting.value = false;
  }
}

function setBusy(id: string, on: boolean): void {
  const next = new Set(busyIds.value);
  if (on) next.add(id);
  else next.delete(id);
  busyIds.value = next;
}

async function onChangeState(
  record: MessageRecord,
  state: MessageState,
): Promise<void> {
  setBusy(record.message_id, true);
  error.value = null;
  notice.value = null;
  try {
    const updated = await updateMessageState(
      record.message_id,
      state,
      record.version,
    );
    const idx = records.value.findIndex(
      (r) => r.message_id === record.message_id,
    );
    if (idx !== -1) records.value[idx] = updated;
  } catch (e) {
    if (e instanceof ConflictError) {
      notice.value = e.message;
      await load();
    } else {
      error.value = e instanceof Error ? e.message : "更新に失敗しました.";
    }
  } finally {
    setBusy(record.message_id, false);
  }
}

onMounted(load);
</script>

<template>
  <div class="app">
    <header class="bar">
      <div class="brand">
        <span class="logo">ReplyGuard</span>
        <span class="tag-line">受信トレイ管制塔</span>
      </div>
      <div class="bar-right">
        <span class="counter" :class="{ alert: unhandledCount > 0 }">
          未対応 {{ unhandledCount }}
        </span>
        <button
          type="button"
          class="refresh"
          :disabled="loading"
          @click="load"
        >
          再読込
        </button>
        <button
          type="button"
          class="ingest"
          :disabled="ingesting"
          @click="onIngest"
        >
          {{ ingesting ? "取り込み中…" : "手動更新" }}
        </button>
      </div>
    </header>

    <main class="main">
      <p v-if="error" class="banner err" role="alert">{{ error }}</p>
      <p v-if="notice" class="banner info" role="status">{{ notice }}</p>

      <p v-if="loading && records.length === 0" class="state-msg">読み込み中…</p>
      <p
        v-else-if="!loading && records.length === 0 && !error"
        class="state-msg"
      >
        メッセージはありません. 「手動更新」で取り込んでください.
      </p>

      <div v-else class="list">
        <MessageCard
          v-for="r in records"
          :key="r.message_id"
          :record="r"
          :busy="busyIds.has(r.message_id)"
          @change-state="(s) => onChangeState(r, s)"
        />
      </div>
    </main>
  </div>
</template>

<style scoped>
.app {
  max-width: 920px;
  margin: 0 auto;
  padding: 0 16px 48px;
}
.bar {
  position: sticky;
  top: 0;
  z-index: 10;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 0;
  background: var(--bg);
  border-bottom: 1px solid var(--border);
}
.brand {
  display: flex;
  align-items: baseline;
  gap: 10px;
}
.logo {
  font-size: 18px;
  font-weight: 800;
  color: var(--accent);
}
.tag-line {
  font-size: 12px;
  color: var(--text-muted);
}
.bar-right {
  display: flex;
  align-items: center;
  gap: 8px;
}
.counter {
  font-size: 13px;
  color: var(--text-muted);
  padding: 4px 10px;
  border-radius: 999px;
  border: 1px solid var(--border);
}
.counter.alert {
  color: var(--danger);
  background: var(--danger-weak);
  border-color: var(--danger);
  font-weight: 700;
}
.refresh,
.ingest {
  font-size: 13px;
  padding: 6px 14px;
  border-radius: var(--radius);
  border: 1px solid var(--border);
  background: var(--surface);
  color: var(--text);
}
.ingest {
  border-color: var(--accent);
  background: var(--accent);
  color: #fff;
}
.refresh:disabled,
.ingest:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
.main {
  margin-top: 16px;
}
.banner {
  margin: 0 0 12px;
  padding: 10px 12px;
  border-radius: var(--radius);
  font-size: 13px;
}
.banner.err {
  color: var(--danger);
  background: var(--danger-weak);
  border: 1px solid var(--danger);
}
.banner.info {
  color: var(--accent);
  background: var(--accent-weak);
  border: 1px solid var(--accent);
}
.state-msg {
  color: var(--text-muted);
  text-align: center;
  padding: 48px 0;
}
.list {
  display: flex;
  flex-direction: column;
  gap: var(--gap);
}
</style>

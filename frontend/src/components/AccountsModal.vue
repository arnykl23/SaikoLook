<script setup lang="ts">
import { ref, onMounted } from "vue";
import type { AccountConfig, AccountConfigCreate } from "../types";
import { getAccounts, createAccount, deleteAccount, startGmailOAuth, startGithubOAuth } from "../api";

const emit = defineEmits<{
  "accounts-changed": [];
  close: [];
}>();

const accounts = ref<AccountConfig[]>([]);
const listLoading = ref(false);
const listError = ref<string | null>(null);

async function loadAccounts(): Promise<void> {
  listLoading.value = true;
  listError.value = null;
  try {
    accounts.value = await getAccounts();
  } catch (e) {
    listError.value = e instanceof Error ? e.message : "取得に失敗しました.";
  } finally {
    listLoading.value = false;
  }
}

const deletingId = ref<string | null>(null);
const deleteError = ref<string | null>(null);

async function onDelete(id: string): Promise<void> {
  deletingId.value = id;
  deleteError.value = null;
  try {
    await deleteAccount(id);
    await loadAccounts();
    emit("accounts-changed");
  } catch (e) {
    deleteError.value = e instanceof Error ? e.message : "削除に失敗しました.";
  } finally {
    deletingId.value = null;
  }
}

// Which provider's connect form is expanded
const expandedProvider = ref<string | null>(null);

function toggleExpand(provider: string): void {
  expandedProvider.value = expandedProvider.value === provider ? null : provider;
  // Reset form when switching
  form.value = { provider, label: "", address: "", credential: "" };
  formError.value = null;
  oauthError.value = null;
  labelEdited.value = false;
}

// --- Connect form ---
const form = ref<AccountConfigCreate>({ provider: "gmail", label: "", address: "", credential: "" });
const formError = ref<string | null>(null);
const submitting = ref(false);
const labelEdited = ref(false);

function onAddressInput(): void {
  if (!labelEdited.value) form.value.label = form.value.address;
}
function onLabelInput(): void {
  labelEdited.value = form.value.label !== form.value.address;
}

const oauthLoading = ref(false);
const oauthError = ref<string | null>(null);

async function onGoogleConnect(): Promise<void> {
  oauthError.value = null;
  if (!form.value.label.trim()) { oauthError.value = "表示名を入力してください."; return; }
  oauthLoading.value = true;
  try {
    const { auth_url } = await startGmailOAuth(form.value.label, "");
    window.location.href = auth_url;
  } catch (e) {
    oauthError.value = e instanceof Error ? e.message : "OAuth 開始に失敗しました.";
  } finally {
    oauthLoading.value = false;
  }
}

async function onGithubConnect(): Promise<void> {
  oauthError.value = null;
  if (!form.value.label.trim()) {
    oauthError.value = "表示名を入力してください.";
    return;
  }
  oauthLoading.value = true;
  try {
    const { auth_url } = await startGithubOAuth(form.value.label);
    window.location.href = auth_url;
  } catch (e) {
    oauthError.value = e instanceof Error ? e.message : "OAuth 開始に失敗しました.";
  } finally {
    oauthLoading.value = false;
  }
}

async function onSubmit(provider: string): Promise<void> {
  formError.value = null;
  if (!form.value.label.trim()) { formError.value = "表示名を入力してください."; return; }
  if (!form.value.address.trim()) { formError.value = "アドレスを入力してください."; return; }
  if (!form.value.credential.trim()) { formError.value = "認証情報を入力してください."; return; }
  submitting.value = true;
  try {
    await createAccount({ ...form.value, provider });
    form.value = { provider, label: "", address: "", credential: "" };
    labelEdited.value = false;
    expandedProvider.value = null;
    await loadAccounts();
    emit("accounts-changed");
  } catch (e) {
    formError.value = e instanceof Error ? e.message : "追加に失敗しました.";
  } finally {
    submitting.value = false;
  }
}

function onOverlayClick(e: MouseEvent): void {
  if ((e.target as HTMLElement).classList.contains("modal-overlay")) emit("close");
}

// Provider catalogue — fixed list, enriched with connected account if any
const PROVIDERS = [
  { id: "gmail",   label: "Gmail",   color: "#EA4335", soon: false },
  { id: "github",  label: "GitHub",  color: "#24292e", soon: false },
  { id: "slack",   label: "Slack",   color: "#4A154B", soon: false },
  { id: "outlook", label: "Outlook", color: "#0078D4", soon: true  },
] as const;

function connectedAccount(provider: string): AccountConfig | undefined {
  return accounts.value.find((a) => a.provider.toLowerCase() === provider);
}

onMounted(() => { void loadAccounts(); });
</script>

<template>
  <div class="modal-overlay" role="dialog" aria-modal="true" aria-label="アカウント設定" @click="onOverlayClick">
    <div class="modal-card">
      <div class="modal-header">
        <span class="modal-title">アカウント設定</span>
        <button type="button" class="close-btn" aria-label="閉じる" @click="emit('close')">✕</button>
      </div>

      <div class="provider-list">
        <p v-if="listError" class="banner err" role="alert">{{ listError }}</p>
        <p v-if="deleteError" class="banner err" role="alert">{{ deleteError }}</p>
        <p v-if="listLoading" class="muted-msg">読み込み中…</p>

        <div
          v-for="p in PROVIDERS"
          :key="p.id"
          class="provider-row"
          :class="{ expanded: expandedProvider === p.id }"
        >
          <!-- Main row -->
          <div class="provider-main">
            <!-- Icon -->
            <div class="provider-icon" :style="{ background: p.color }">
              <!-- Gmail -->
              <svg v-if="p.id === 'gmail'" width="18" height="18" viewBox="0 0 24 24" fill="white" aria-hidden="true">
                <path d="M20 4H4a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2zm0 4-8 5-8-5V6l8 5 8-5v2z"/>
              </svg>
              <!-- GitHub -->
              <svg v-else-if="p.id === 'github'" width="18" height="18" viewBox="0 0 24 24" fill="white" aria-hidden="true">
                <path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0 0 24 12c0-6.63-5.37-12-12-12z"/>
              </svg>
              <!-- Slack -->
              <svg v-else-if="p.id === 'slack'" width="18" height="18" viewBox="0 0 24 24" fill="white" aria-hidden="true">
                <path d="M5.042 15.165a2.528 2.528 0 0 1-2.52 2.523A2.528 2.528 0 0 1 0 15.165a2.527 2.527 0 0 1 2.522-2.52h2.52v2.52zM6.313 15.165a2.527 2.527 0 0 1 2.521-2.52 2.527 2.527 0 0 1 2.521 2.52v6.313A2.528 2.528 0 0 1 8.834 24a2.528 2.528 0 0 1-2.521-2.522v-6.313zM8.834 5.042a2.528 2.528 0 0 1-2.521-2.52A2.528 2.528 0 0 1 8.834 0a2.528 2.528 0 0 1 2.521 2.522v2.52H8.834zM8.834 6.313a2.528 2.528 0 0 1 2.521 2.521 2.528 2.528 0 0 1-2.521 2.521H2.522A2.528 2.528 0 0 1 0 8.834a2.528 2.528 0 0 1 2.522-2.521h6.312zM18.956 8.834a2.528 2.528 0 0 1 2.522-2.521A2.528 2.528 0 0 1 24 8.834a2.528 2.528 0 0 1-2.522 2.521h-2.522V8.834zM17.688 8.834a2.528 2.528 0 0 1-2.523 2.521 2.527 2.527 0 0 1-2.52-2.521V2.522A2.527 2.527 0 0 1 15.165 0a2.528 2.528 0 0 1 2.523 2.522v6.312zM15.165 18.956a2.528 2.528 0 0 1 2.523 2.522A2.528 2.528 0 0 1 15.165 24a2.527 2.527 0 0 1-2.52-2.522v-2.522h2.52zM15.165 17.688a2.527 2.527 0 0 1-2.52-2.523 2.526 2.526 0 0 1 2.52-2.52h6.313A2.527 2.527 0 0 1 24 15.165a2.528 2.528 0 0 1-2.522 2.523h-6.313z"/>
              </svg>
              <!-- Outlook -->
              <svg v-else width="18" height="18" viewBox="0 0 24 24" fill="white" aria-hidden="true">
                <path d="M24 7.387v10.478L19.2 15l-5.2 3V9l5.2-3 4.8 1.387zM13 8.5V18l-2 1.5V5L2 7v10l9 2v1.5L0 18V6l13-3v5.5z"/>
              </svg>
            </div>

            <!-- Name + status -->
            <div class="provider-info">
              <span class="provider-name">{{ p.label }}</span>
              <span v-if="connectedAccount(p.id)" class="provider-status connected">接続済み</span>
              <span v-else-if="p.soon" class="provider-status soon">近日公開</span>
              <span v-else class="provider-status disconnected">未接続</span>
            </div>

            <!-- Account label if connected -->
            <span v-if="connectedAccount(p.id)" class="provider-account-label">
              {{ connectedAccount(p.id)!.label }}
            </span>

            <!-- Action button -->
            <button
              v-if="connectedAccount(p.id)"
              type="button"
              class="action-btn disconnect-btn"
              :disabled="deletingId === connectedAccount(p.id)!.id"
              @click="onDelete(connectedAccount(p.id)!.id)"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" aria-hidden="true">
                <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
              </svg>
            </button>
            <button
              v-else-if="!p.soon"
              type="button"
              class="action-btn connect-btn"
              :class="{ active: expandedProvider === p.id }"
              @click="toggleExpand(p.id)"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" aria-hidden="true">
                <line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>
              </svg>
            </button>
          </div>

          <!-- Inline connect form -->
          <div v-if="expandedProvider === p.id" class="connect-form">
            <p v-if="formError" class="banner err" role="alert">{{ formError }}</p>

            <!-- Gmail: label + OAuth -->
            <template v-if="p.id === 'gmail'">
              <div class="field">
                <label class="label" for="f-label">表示名</label>
                <input id="f-label" v-model="form.label" type="text" class="input" placeholder="例: 仕事用 Gmail" autocomplete="off" @input="onLabelInput" />
              </div>
              <button type="button" class="oauth-btn" :disabled="oauthLoading" @click="onGoogleConnect">
                {{ oauthLoading ? "接続中..." : "Google アカウントで接続" }}
              </button>
              <p v-if="oauthError" class="error-text">{{ oauthError }}</p>
            </template>

            <!-- GitHub: label + OAuth -->
            <template v-else-if="p.id === 'github'">
              <div class="field">
                <label class="label" for="f-label-github">表示名</label>
                <input id="f-label-github" v-model="form.label" type="text" class="input" placeholder="例: 仕事用 GitHub" autocomplete="off" @input="onLabelInput" />
              </div>
              <button type="button" class="oauth-btn oauth-btn--github" :disabled="oauthLoading" @click="onGithubConnect">
                {{ oauthLoading ? "接続中..." : "GitHub で接続" }}
              </button>
              <p v-if="oauthError" class="error-text">{{ oauthError }}</p>
            </template>

            <!-- Slack: label + workspace + token -->
            <template v-else-if="p.id === 'slack'">
              <div class="field">
                <label class="label" for="f-label-slack">表示名</label>
                <input id="f-label-slack" v-model="form.label" type="text" class="input" placeholder="例: 会社の Slack" autocomplete="off" @input="onLabelInput" />
              </div>
              <div class="field">
                <label class="label" for="f-address">ワークスペース名</label>
                <input id="f-address" v-model="form.address" type="text" class="input" placeholder="例: my-team" autocomplete="off" @input="onAddressInput" />
              </div>
              <div class="field">
                <label class="label" for="f-cred">Bot User OAuth Token</label>
                <input id="f-cred" v-model="form.credential" type="password" class="input" placeholder="xoxb-..." autocomplete="new-password" />
              </div>
              <div class="form-footer">
                <button type="button" class="btn-primary" :disabled="submitting" @click="onSubmit('slack')">
                  {{ submitting ? "追加中…" : "接続する" }}
                </button>
              </div>
            </template>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(16, 12, 8, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
}

.modal-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: calc(var(--radius) * 1.5);
  width: 440px;
  max-width: calc(100vw - 32px);
  max-height: calc(100vh - 48px);
  overflow-y: auto;
  box-shadow: var(--shadow-lg);
}

.modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  border-bottom: 1px solid var(--border);
  background: var(--brand-gradient);
  position: sticky;
  top: 0;
  z-index: 1;
  border-radius: calc(var(--radius) * 1.5) calc(var(--radius) * 1.5) 0 0;
}
.modal-title {
  font-size: 15px;
  font-weight: 700;
  color: #fff;
}
.close-btn {
  background: none;
  border: none;
  font-size: 16px;
  color: rgba(255, 255, 255, 0.75);
  padding: 4px;
  line-height: 1;
  cursor: pointer;
  transition: color 0.15s;
}
.close-btn:hover { color: #fff; }

/* ── Provider list ── */
.provider-list {
  padding: 12px 16px 20px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.provider-row {
  border: 1px solid var(--border);
  border-radius: var(--radius);
  overflow: hidden;
  transition: border-color 0.15s;
}
.provider-row.expanded {
  border-color: var(--brand-blue);
}

.provider-main {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 14px;
  background: var(--snow-surface);
}

.provider-icon {
  width: 36px;
  height: 36px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.provider-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.provider-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--text);
}
.provider-status {
  font-size: 11px;
  font-weight: 600;
}
.provider-status.connected { color: var(--success); }
.provider-status.disconnected { color: var(--text-muted); }
.provider-status.soon { color: var(--text-muted); }

.provider-account-label {
  flex: 1;
  font-size: 12px;
  color: var(--text-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  text-align: right;
}

.action-btn {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  flex-shrink: 0;
  transition: background 0.15s, border-color 0.15s, color 0.15s;
}
.connect-btn {
  border: 1px solid var(--brand-blue);
  background: var(--surface);
  color: var(--brand-blue);
}
.connect-btn:hover,
.connect-btn.active {
  background: var(--brand-blue);
  color: #fff;
}
.disconnect-btn {
  border: none;
  background: none;
  color: var(--text-muted);
}
.disconnect-btn:hover:not(:disabled) {
  color: var(--danger);
}
.disconnect-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

/* ── Inline connect form ── */
.connect-form {
  padding: 14px 14px 16px;
  border-top: 1px solid var(--border);
  background: var(--surface);
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.label {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}
.input {
  font: inherit;
  font-size: 13px;
  padding: 8px 10px;
  border-radius: var(--radius);
  border: 1px solid var(--border);
  background: var(--snow-surface);
  color: var(--text);
  outline: none;
  transition: border-color 0.15s;
}
.input:focus { border-color: var(--brand-blue); }

.form-footer {
  display: flex;
  justify-content: flex-end;
}
.btn-primary {
  font-size: 13px;
  font-weight: 600;
  padding: 7px 18px;
  border-radius: var(--radius-pill);
  border: none;
  background: var(--brand-gradient);
  color: #fff;
  cursor: pointer;
  box-shadow: var(--shadow-sm);
  transition: opacity 0.15s;
}
.btn-primary:hover:not(:disabled) { opacity: 0.88; }
.btn-primary:disabled { opacity: 0.55; cursor: not-allowed; }

.oauth-btn {
  width: 100%;
  padding: 9px;
  background: var(--brand-gradient);
  color: #fff;
  border: none;
  border-radius: var(--radius);
  cursor: pointer;
  font-size: 13px;
  font-weight: 600;
  box-shadow: var(--shadow-sm);
  transition: opacity 0.15s;
}
.oauth-btn:hover:not(:disabled) { opacity: 0.88; }
.oauth-btn:disabled { opacity: 0.55; cursor: not-allowed; }

.banner {
  margin: 0;
  padding: 8px 12px;
  border-radius: var(--radius);
  font-size: 13px;
}
.banner.err {
  color: var(--danger);
  background: var(--danger-weak);
  border: 1px solid var(--danger);
}
.error-text {
  font-size: 12px;
  color: var(--danger);
  margin: 0;
}
.muted-msg {
  font-size: 13px;
  color: var(--text-muted);
  padding: 8px 0;
  margin: 0;
}

.oauth-btn--github {
  background: #24292e;
}
</style>

<script setup lang="ts">
import { ref, onMounted, computed } from "vue";
import type { AccountConfig, AccountConfigCreate } from "../types";
import { getAccounts, createAccount, deleteAccount } from "../api";

const emit = defineEmits<{
  "accounts-changed": [];
  close: [];
}>();

// --- 登録済みアカウント ---
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

// --- 追加フォーム ---
const selectedProvider = ref("gmail");
const form = ref<AccountConfigCreate>({
  provider: "gmail",
  label: "",
  address: "",
  credential: "",
});
const formError = ref<string | null>(null);
const submitting = ref(false);

function onAddressInput(): void {
  // address 入力時に label が未編集なら自動セット
  if (!labelEdited.value) {
    form.value.label = form.value.address;
  }
}

const labelEdited = ref(false);
function onLabelInput(): void {
  labelEdited.value = form.value.label !== form.value.address;
}

function selectProvider(p: string): void {
  selectedProvider.value = p;
  form.value.provider = p;
}

// --- プロバイダ別のフォーム表示 ---
const addressLabel = computed(() =>
  selectedProvider.value === "slack" ? "ワークスペース名" : "メールアドレス"
);
const addressPlaceholder = computed(() =>
  selectedProvider.value === "slack" ? "例: my-team" : "you@gmail.com"
);
const addressInputType = computed(() => (selectedProvider.value === "slack" ? "text" : "email"));
const credentialLabel = computed(() =>
  selectedProvider.value === "slack" ? "Bot User OAuth Token" : "アプリパスワード"
);
const credentialPlaceholder = computed(() =>
  selectedProvider.value === "slack" ? "xoxb-..." : "Google アプリパスワード（16桁）"
);

async function onSubmit(): Promise<void> {
  formError.value = null;
  if (!form.value.label.trim()) {
    formError.value = "表示名を入力してください.";
    return;
  }
  if (!form.value.address.trim()) {
    formError.value = `${addressLabel.value}を入力してください.`;
    return;
  }
  if (!form.value.credential.trim()) {
    formError.value = `${credentialLabel.value}を入力してください.`;
    return;
  }
  submitting.value = true;
  try {
    await createAccount({ ...form.value });
    // フォームリセット
    form.value = { provider: selectedProvider.value, label: "", address: "", credential: "" };
    labelEdited.value = false;
    await loadAccounts();
    emit("accounts-changed");
  } catch (e) {
    formError.value = e instanceof Error ? e.message : "追加に失敗しました.";
  } finally {
    submitting.value = false;
  }
}

function onOverlayClick(e: MouseEvent): void {
  if ((e.target as HTMLElement).classList.contains("modal-overlay")) {
    emit("close");
  }
}

onMounted(() => {
  void loadAccounts();
});
</script>

<template>
  <div class="modal-overlay" role="dialog" aria-modal="true" aria-label="アカウント設定" @click="onOverlayClick">
    <div class="modal-card">
      <!-- ヘッダー -->
      <div class="modal-header">
        <span class="modal-title">アカウント設定</span>
        <button type="button" class="close-btn" aria-label="閉じる" @click="emit('close')">✕</button>
      </div>

      <!-- 登録済みアカウント -->
      <section class="section">
        <h2 class="section-title">登録済みアカウント</h2>
        <p v-if="listError" class="banner err" role="alert">{{ listError }}</p>
        <p v-if="deleteError" class="banner err" role="alert">{{ deleteError }}</p>
        <p v-if="listLoading" class="muted-msg">読み込み中…</p>
        <p v-else-if="accounts.length === 0" class="muted-msg">まだ登録されていません.</p>
        <ul v-else class="account-list">
          <li v-for="ac in accounts" :key="ac.id" class="account-item">
            <span class="account-provider">{{ ac.provider }}</span>
            <span class="account-label">{{ ac.label }}</span>
            <button
              type="button"
              class="btn-danger-sm"
              :disabled="deletingId === ac.id"
              @click="onDelete(ac.id)"
            >
              {{ deletingId === ac.id ? "削除中…" : "削除" }}
            </button>
          </li>
        </ul>
      </section>

      <hr class="divider" />

      <!-- 追加フォーム -->
      <section class="section">
        <h2 class="section-title">アカウントを追加</h2>

        <!-- プロバイダ選択 -->
        <div class="provider-row">
          <button
            type="button"
            class="provider-btn"
            :class="{ active: selectedProvider === 'gmail' }"
            @click="selectProvider('gmail')"
          >
            Gmail
          </button>
          <button
            type="button"
            class="provider-btn"
            :class="{ active: selectedProvider === 'slack' }"
            @click="selectProvider('slack')"
          >
            Slack
          </button>
          <button type="button" class="provider-btn" disabled>
            Outlook
            <span class="soon-badge">近日公開</span>
          </button>
        </div>

        <!-- フォーム -->
        <p v-if="formError" class="banner err" role="alert">{{ formError }}</p>
        <form class="form" @submit.prevent="onSubmit">
          <div class="field">
            <label class="label" for="account-label">表示名</label>
            <input
              id="account-label"
              v-model="form.label"
              type="text"
              class="input"
              placeholder="例: 仕事用 Gmail"
              autocomplete="off"
              @input="onLabelInput"
            />
          </div>
          <div class="field">
            <label class="label" for="account-address">{{ addressLabel }}</label>
            <input
              id="account-address"
              v-model="form.address"
              :type="addressInputType"
              class="input"
              :placeholder="addressPlaceholder"
              autocomplete="off"
              @input="onAddressInput"
            />
          </div>
          <div class="field">
            <label class="label" for="account-credential">{{ credentialLabel }}</label>
            <input
              id="account-credential"
              v-model="form.credential"
              type="password"
              class="input"
              :placeholder="credentialPlaceholder"
              autocomplete="new-password"
            />
          </div>
          <div class="form-footer">
            <button type="submit" class="btn-primary" :disabled="submitting">
              {{ submitting ? "追加中…" : "追加する" }}
            </button>
          </div>
        </form>
      </section>
    </div>
  </div>
</template>

<style scoped>
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
}

.modal-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: calc(var(--radius) * 2);
  width: 480px;
  max-width: calc(100vw - 32px);
  max-height: calc(100vh - 48px);
  overflow-y: auto;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.18);
}

.modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  border-bottom: 1px solid var(--border);
  position: sticky;
  top: 0;
  background: var(--surface);
  z-index: 1;
}

.modal-title {
  font-size: 15px;
  font-weight: 700;
  color: var(--text);
}

.close-btn {
  background: none;
  border: none;
  font-size: 16px;
  color: var(--text-muted);
  padding: 4px 6px;
  border-radius: var(--radius);
  line-height: 1;
  cursor: pointer;
}
.close-btn:hover {
  background: var(--bg);
  color: var(--text);
}

.section {
  padding: 16px 20px;
}

.section-title {
  font-size: 12px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--text-muted);
  margin: 0 0 12px;
}

.divider {
  border: none;
  border-top: 1px solid var(--border);
  margin: 0;
}

/* アカウント一覧 */
.account-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.account-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius);
}

.account-provider {
  font-size: 12px;
  font-weight: 600;
  color: var(--accent);
  background: var(--accent-weak);
  border-radius: 4px;
  padding: 2px 8px;
  white-space: nowrap;
}

.account-label {
  flex: 1;
  font-size: 13px;
  color: var(--text);
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.btn-danger-sm {
  font-size: 12px;
  padding: 4px 10px;
  border-radius: var(--radius);
  border: 1px solid var(--danger);
  background: transparent;
  color: var(--danger);
  white-space: nowrap;
  cursor: pointer;
}
.btn-danger-sm:hover:not(:disabled) {
  background: var(--danger-weak);
}
.btn-danger-sm:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* プロバイダ選択 */
.provider-row {
  display: flex;
  gap: 8px;
  margin-bottom: 16px;
}

.provider-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  padding: 6px 14px;
  border-radius: var(--radius);
  border: 1px solid var(--border);
  background: var(--surface);
  color: var(--text);
  cursor: pointer;
  transition: border-color 0.15s, background 0.15s;
}
.provider-btn.active {
  border-color: var(--accent);
  background: var(--accent-weak);
  color: var(--accent);
  font-weight: 600;
}
.provider-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.soon-badge {
  font-size: 10px;
  padding: 1px 5px;
  border-radius: 4px;
  background: var(--border);
  color: var(--text-muted);
  white-space: nowrap;
}

/* フォーム */
.form {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.label {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-muted);
}

.input {
  font: inherit;
  font-size: 13px;
  padding: 7px 10px;
  border-radius: var(--radius);
  border: 1px solid var(--border);
  background: var(--bg);
  color: var(--text);
  outline: none;
  transition: border-color 0.15s;
}
.input:focus {
  border-color: var(--accent);
  background: var(--surface);
}

.form-footer {
  display: flex;
  justify-content: flex-end;
  margin-top: 4px;
}

.btn-primary {
  font-size: 13px;
  padding: 6px 14px;
  border-radius: var(--radius);
  border: 1px solid var(--accent);
  background: var(--accent);
  color: #fff;
  cursor: pointer;
}
.btn-primary:hover:not(:disabled) {
  opacity: 0.88;
}
.btn-primary:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

/* バナー・メッセージ */
.banner {
  margin: 0 0 10px;
  padding: 8px 12px;
  border-radius: var(--radius);
  font-size: 13px;
}
.banner.err {
  color: var(--danger);
  background: var(--danger-weak);
  border: 1px solid var(--danger);
}

.muted-msg {
  font-size: 13px;
  color: var(--text-muted);
  margin: 0;
  padding: 8px 0;
}
</style>

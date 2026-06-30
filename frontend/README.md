# SaikoLook Frontend

SaikoLook のダッシュボード（Vite + Vue 3 + TypeScript）。トリアージ順にメッセージを一覧表示し、対応状態を変更する。

## 起動

```bash
cd frontend
cp .env.example .env   # 必要なら API ベース URL を編集
npm install
npm run dev            # http://localhost:5173
```

API（FastAPI）は別途 `http://localhost:8000` で起動しておく（`VITE_API_BASE` で変更可）。

## ビルド

```bash
npm run build     # 型チェック(vue-tsc) + 本番ビルド -> dist/
npm run preview   # ビルド成果物のプレビュー
```

API 未起動でもビルドは通る（実行時に fetch するため）。

## 環境変数

| 変数 | 既定 | 用途 |
|---|---|---|
| `VITE_API_BASE` | `http://localhost:8000` | バックエンド API のベース URL |

`.env` の実値はコミットしない（`.env.example` のみ管理）。

## API 契約（backend-api 提供）

| メソッド | パス | 用途 |
|---|---|---|
| GET | `/messages?order_by=triage_score&descending=true` | `MessageRecord[]` を取得 |
| POST | `/messages/{message_id}/state` | 状態変更。body `{ state, version }`（楽観ロック。409 で競合→リロード） |
| POST | `/ingest` | 手動取り込み。完了後にリフェッチ |

型は `src/types.ts`（`app/models.py` をミラー）。

## 構成

```
src/
├── main.ts                    # エントリ
├── App.vue                    # 一覧・取得・状態変更・エラー/ローディング
├── api.ts                     # fetch ラッパ（VITE_API_BASE・409 を ConflictError 化）
├── types.ts                   # API 契約の型（models.py ミラー）
├── styles.css                 # light テーマのデザイントークン（CSS 変数）
└── components/
    ├── MessageCard.vue        # 1 メッセージのカード＋状態変更ボタン
    ├── ImportanceBadge.vue    # 重要度 1-5 バッジ
    └── StateBadge.vue         # 対応状態バッジ
```

## セキュリティ

- `summary` ・件名・本文は **テキストバインド**で描画する（`v-html` を使わない＝XSS リスクなし）。将来 HTML 描画が必要になったら DOMPurify を導入する。
- API キー等の秘密情報をフロントに埋め込まない。取得したメール内容を外部へ送らない。

# LLM by norin - Local GPU Chat Assistant

搭載されている **NVIDIA GeForce RTX 4070 Ti (12GB VRAM)** をフル活用した、高速・完全ローカル動作のLLMチャットシステムです。

外部API（クラウド）へのデータ送信を行わず、すべてローカルマシンのGPU上で推論を実行します。

---

## 🌟 主な特徴

- ⚡ **RTX 4070 Ti (CUDA) 最適化推論**:
  - `Qwen/Qwen2.5-3B-Instruct`（高精度・日本語対応・指示追従性に優れた最新モデル）を bfloat16 / float16 でGPU VRAMにロード。
  - 約6GBのVRAMフットプリントで、12GB VRAM環境下で極めて高速（数十〜100+ tokens/sec）に動作。
- 🌊 **リアルタイム・トークンストリーミング**:
  - Server-Sent Events (SSE) を用いたChatGPTライクな流れるような逐次回答表示。
- 📊 **リアルタイム GPU & VRAM モニタリング**:
  - VRAM使用量/総容量（例: `5.2 GB / 12.0 GB`）、GPUステータスを画面上にリアルタイム表示。
- 🎛️ **柔軟なパラメータ調整**:
  - System Prompt（AIの役割・キャラクター設定）、Temperature、Max Tokens をUIから自由に変更可能。
- 🎨 **モダンで洗練されたUI**:
  - React + TypeScript + Vite + Markdownレンダリング（コードブロック・表組み等に対応）。

---

## 🛠️ システム構成

- **Backend**:
  - FastAPI / Uvicorn
  - PyTorch (CUDA 12.4)
  - Hugging Face Transformers / Accelerate
  - モデル: `Qwen/Qwen2.5-3B-Instruct` (初回起動時に自動ダウンロード)
- **Frontend**:
  - React 18 / TypeScript
  - Vite
  - Lucide Icons / React Markdown

---

## 🚀 クイックスタート

### 1. 必要要件
- OS: Windows 10 / 11 (64-bit)
- GPU: NVIDIA GPU (RTX 4070 Ti 推奨, VRAM 8GB以上)
- Python: 3.10 以上 (3.13対応確認済み)
- Node.js: 18.0 以上

### 2. ワンクリック起動
リポジトリ直下の `start.bat` をダブルクリックするだけで、バックエンドとフロントエンドが同時に起動し、ブラウザでUIが開きます。

```cmd
start.bat
```

ブラウザで `http://localhost:5173` にアクセスしてください。

---

## 💻 手動でのセットアップ & 起動

### バックエンドのセットアップ
```cmd
cd backend
# 仮想環境の作成
python -m venv .venv
# 有効化
call .\.venv\Scripts\activate
# 依存パッケージのインストール
pip install -r requirements.txt
# サーバー起動
python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

### フロントエンドのセットアップ
```cmd
cd frontend
# 依存パッケージのインストール
npm install
# 開発サーバー起動
npm run dev
```

---

## 📡 API エンドポイント

| メソッド | パス | 説明 |
|---|---|---|
| `GET` | `/` | サーバーヘルスチェック |
| `GET` | `/api/gpu` | GPU名、VRAM使用量、モデルロード状態の取得 |
| `POST` | `/api/chat/stream` | Server-Sent Events (SSE) による逐次トークン生成 |
| `POST` | `/api/chat` | 通常のJSON一括チャット生成 |
| `POST` | `/api/model/load` | 指定モデルIDの動的ロード |

---

## 📄 ライセンス
MIT License

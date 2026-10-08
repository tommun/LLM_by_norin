# LLM by norin - Local GPU Chat & Image Generation Studio

搭載されている **NVIDIA GeForce RTX 4070 Ti (12GB VRAM)** をフル活用した、高速・完全ローカル動作の**LLMチャット＆画像生成スタジオ**です。

外部API（クラウド）へのデータ送信を行わず、すべてローカルマシンのGPU上で推論・生成を実行します。

---

## 🌟 主な特徴

- ⚡ **RTX 4070 Ti (CUDA) 最適化推論**:
  - `Qwen/Qwen2.5-3B-Instruct`（高精度・日本語対応・指示追従性に優れた最新モデル）を bfloat16 / float16 でGPU VRAMにロード。
  - 約6GBのVRAMフットプリントで、12GB VRAM環境下で極めて高速（数十〜100+ tokens/sec）に動作。
- 🎨 **1秒未満の爆速ローカル画像生成 (SD-Turbo)**:
  - Hugging Face `diffusers` と `stabilityai/sd-turbo` による最新の拡散蒸留（ADD）モデルを搭載。
  - わずか **1〜2ステップ（約 0.8〜1.2 秒）** で 512x512 の高精細な画像を即座に生成。
  - VRAM約 2.8GB で動作するため、**LLM（約5.9GB）と同時にGPUメモリに常駐可能**（合計約 8.7GB / 12GB）。
- 🌊 **リアルタイム・トークンストリーミング**:
  - Server-Sent Events (SSE) を用いたChatGPTライクな流れるような逐次回答表示。
- 📊 **リアルタイム GPU & VRAM モニタリング**:
  - VRAM使用量/総容量（例: `8.7 GB / 12.0 GB`）、GPUステータス、アクティブモデル一覧をリアルタイム表示。
- 🎛️ **ワンクリック モード切り替え & パラメータ調整**:
  - 「💬 テキスト対話」と「🎨 画像生成」をタブでシームレスに切り替え。
  - テキストチャット中でも「`/image <プロンプト>`」を入力すると即座に画像生成が可能。
  - 生成画像はワンクリックで拡大プレビューやPNG保存が可能。
  - System Prompt、Temperature、Max Tokens、画像生成ステップ数などを自由に調整可能。

---

## 🛠️ システム構成

- **Backend**:
  - FastAPI / Uvicorn
  - PyTorch (CUDA 12.4)
  - Hugging Face Transformers / Accelerate / Diffusers
  - LLMモデル: `Qwen/Qwen2.5-3B-Instruct`
  - 画像生成モデル: `stabilityai/sd-turbo`
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
# 仮想環境の作成 (初回のみ)
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
# 依存パッケージのインストール (初回のみ)
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
| `POST` | `/api/generate-image` | テキストプロンプトからの高速画像生成 (Base64返却) |
| `POST` | `/api/model/load` | 指定モデルIDの動的ロード |

---

## 📄 ライセンス
MIT License

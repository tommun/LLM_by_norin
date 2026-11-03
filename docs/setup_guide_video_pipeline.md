# 動画生成パイプライン セットアップ手順書
**対象システム**: Local GPU Vision LLM & Diffusion Studio / Creative Buddy Luka  
**モデル**: Wan 2.2 TI2V-5B (Image-to-Video)  
**環境**: Windows 11 / NVIDIA GeForce RTX 4070 Ti (12GB VRAM)  

---

## 1. 概要
本手順書は、既存の画像生成・対話AIシステムに「Wan 2.2 TI2V-5B」動画生成パイプラインをローカル環境で安全に起動・運用するための手順書です。  
外部クラウドや有料APIへの通信は一切発生せず、完全ローカル（オフライン）で動作します。

---

## 2. 必要なモデルの入手先と配置

| モデル名 | 用途 | 配布元 (Hugging Face) | ローカルキャッシュ先 |
| :--- | :--- | :--- | :--- |
| **Wan2.2-TI2V-5B-Diffusers** | 動画生成 (I2V / 5秒) | `Wan-AI/Wan2.2-TI2V-5B-Diffusers` | `~/.cache/huggingface/hub/` (自動キャッシュ) |
| **RealVisXL_V4.0** | キーフレーム静止画生成 | `SG161222/RealVisXL_V4.0` | `backend/models/` |
| **Qwen2.5-VL-7B-Instruct** | シーン解析・プロンプト分離 | `Qwen/Qwen2.5-VL-7B-Instruct` | `~/.cache/huggingface/hub/` |
| **OpenPoseXL2 ControlNet** | ポーズ骨格固定 | `thibaud/controlnet-openpose-sdxl-1.0` | `backend/models/controlnet/` |

> [!NOTE]
> 初回実行時に Diffusers および Hugging Face Hub により自動的に最適化キャッシュ（約10〜11GB）がダウンロードされます。手動で事前ダウンロードする場合は以下を実行してください：
> ```powershell
> huggingface-cli download Wan-AI/Wan2.2-TI2V-5B-Diffusers --local-dir ~/.cache/huggingface/hub/models--Wan-AI--Wan2.2-TI2V-5B-Diffusers
> ```

---

## 3. 追加依存パッケージの確認

仮想環境（`backend/.venv`）に必要な追加ライブラリが導入されていることを確認します：

```powershell
cd C:\Users\owner\.gemini\antigravity\scratch\LLM_by_norin\backend
.\.venv\Scripts\pip install diffusers transformers accelerate bitsandbytes imageio-ffmpeg opencv-python ftfy
```

* `imageio-ffmpeg`: Windows環境でもシステムへのFFmpegインストール不要でスタンドアロンFFmpegバイナリを提供し、クリップの高速ロスレス結合（concat）を可能にします。

---

## 4. 起動手順（PowerShell）

システムは以下の 3 つのプロセスを起動します。

### ステップ 1: バックエンド API サーバーの起動
```powershell
cd C:\Users\owner\.gemini\antigravity\scratch\LLM_by_norin\backend
.\.venv\Scripts\python -m uvicorn main:app --host 0.0.0.0 --port 8000
```
* `Uvicorn running on http://0.0.0.0:8000` と表示されれば待機完了。

### ステップ 2: フロントエンド WebUI の起動
```powershell
cd C:\Users\owner\.gemini\antigravity\scratch\LLM_by_norin\frontend
npm run dev
```
* ブラウザで `http://localhost:5173/` にアクセスしてギャラリーを表示。

### ステップ 3: Discord Bot (ルカ) の起動
```powershell
cd C:\Users\owner\.gemini\antigravity\scratch\LLM_by_norin\backend
.\.venv\Scripts\python -u discord_bot.py
```
* `Registered Persistent Button Views for zero-timeout clicks!` と表示されれば完了。

---

## 5. 操作方法

### (1) Discord からの操作
1. **テキストでシーン指示**:
   * `@ルカ このキャラが草原を歩く動画にして`
   * `@ルカ 闘技場に立つエレナのアニメーションを作って`
2. **既存画像からの動画化**:
   * 生成された静止画の下にある **`[🎬 5秒動画化 (Wan 2.2)]`** ボタンをタップ。
3. **動画完了後の操作**:
   * **`[🎬 モーション編集して再生成]`**: カメラワークや動きをテキストモーダルで微調整。
   * **`[🔄 別シードで再生成]`**: 構図や動きのバリエーションをランダムシードで試行。
   * **`[🎞️ クリップを結合して1話にする]`**: チャンネル内の直近クリップ群を 1 本のフルエピソード MP4（`SlaveArena_Ep01_Full.mp4`）に瞬時結合。

### (2) WebUI からの操作
* ギャラリータブで `.mp4` 動画クリップが「🎬 VIDEO」バッジ付きでインライン自動再生されます。
* モーダルを開くことで、大画面プレビュー、モーションプロンプト確認、動画ダウンロードが可能です。

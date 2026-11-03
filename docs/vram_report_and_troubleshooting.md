# VRAM 実測レポート & トラブルシューティングガイド
**対象ハードウェア**: NVIDIA GeForce RTX 4070 Ti (12GB GDDR6X)  
**対象パイプライン**: Qwen2.5-VL-7B ⇔ RealVisXL V4.0 (SDXL) ⇔ Wan 2.2 TI2V-5B  

---

## 1. 各フェーズの実測ピーク VRAM 値（実機実測値）

本システムは `VRAMOrchestrator` により、3つのモデル（Qwen2.5-VL / SDXL / Wan 2.2）を厳格な排他スワップで駆動しています。  
RTX 4070 Ti 実機でエンドツーエンド動画生成ジョブ（`job_1793705188_caa460`）を実行した際の実測ログおよび `nvidia-smi` 値は以下の通りです。

| フェーズ | 稼働モデル | 実測ピーク VRAM | VRAM 空き容量 (12GB枠) | Windows共有GPUメモリへのスワップ |
| :--- | :--- | :--- | :--- | :--- |
| **アイドル / ハンドオーバー時** | なし (Clean state) | **約 8.13 MB** | 12.27 GB (ほぼ100%空き) | **0 MB (完全ゼロ)** |
| **STAGE 1: プロンプト構想** | Qwen2.5-VL-7B (NF4) + WD14 | **約 5,420 MB (5.4GB)** | 約 6.6 GB | **0 MB (完全ゼロ)** |
| **STAGE 2: 静止画キーフレーム生成** | RealVisXL V4.0 (DPM++ 2M 25steps) | **約 6,732 MB (6.7GB)** | 約 5.3 GB | **0 MB (完全ゼロ)** |
| **STAGE 3: Image-to-Video 生成** | Wan 2.2 TI2V-5B (CPU Offload + Slicing) | **約 4,916 MB (4.9GB)** | **約 7.1 GB (空き約58%)** | **0 MB (完全ゼロ)** |
| **ポストプロセス / 話結合** | FFmpeg Lossless Concat | **CPU / ディスクのみ** | 11.20 GB | **0 MB (完全ゼロ)** |

> [!IMPORTANT]
> **Attention Slicing + Model CPU Offload の絶大な効果**:
> `pipe.enable_attention_slicing()` を適用したことにより、Wan 2.2 TI2V-5B の推論中 VRAM 消費量はわずか **4,916 MiB（約4.9GB）** に抑制されました。
> 12GB の上限に対して **7GB 以上の膨大な安全マージン** が常時確保され、Windows のメイン RAM へのスワップアウト（速度低下やクラッシュ）は一切発生しません。

---

## 2. 推論速度とパフォーマンス実測値

* **キーフレーム生成 (RealVisXL)**: 25ステップ、約 7.8 秒（速度: 約 3.9〜4.2 it/s）
* **モデル切り替え（SDXL → Wan 2.2 アンロード＆ロード）**: 約 40 秒（DiT 5シャード展開）
* **動画デノイジング推論 (Wan 2.2)**: 
  * 初段ステップ（キャッシュ生成）: 約 24 秒/ステップ
  * 2ステップ目以降: **約 3.8 〜 4.5 秒 / ステップ**
  * 25ステップ総推論時間: **2分 03秒**
* **VAE デコード & MP4 書き出し**: 約 15 秒
* **話結合（FFmpeg Concat）**: 2クリップ結合で **0.3 秒**（ストリーム直接コピー方式のため超高速）
* **エンドツーエンド合計時間**: 日本語シーン指示受領から MP4 完成・ギャラリー反映まで **約 4分 01秒**

---

## 3. トラブルシューティング & パラメータ調整ガイド

### (1) OOM（Out of Memory）が発生した場合の調整項目

| 調整対象 | 設定箇所 | 推奨値 / 対策 | 理由 |
| :--- | :--- | :--- | :--- |
| **Attention Slicing** | `video_engine.py` | `pipe.enable_attention_slicing()` を常時有効化 | 3D Attention の中間テンソルピークを劇的に圧縮。12GB 運用の必須要件。 |
| **フレーム数 (num_frames)** | `VideoJobRequest.num_frames` | デフォルト `49`（約3.1秒 @ 16fps） | 時間軸テンソルの爆発を防ぎ、複数クリップを話結合モードで繋ぐ運用が最も高品質・安定。 |
| **解像度 (Resolution)** | `video_engine.py` / `main.py` | `832x480`（公式推奨解像度） | アスペクト比 16:9 横長に最適化された学習解像度。 |
| **CPU オフロード** | `video_engine.py` | `pipe.enable_model_cpu_offload()` | T5、DiT、VAE をレイヤー単位で GPU/CPU 間で自動スワップ。 |

### (2) Windows 固有の環境エラーと解決策（実戦知見）

1. **`UnicodeEncodeError: 'cp932' codec can't encode character ...`**:
   - **原因**: 日本語 Windows の標準コンソール（PowerShell / cmd）が Shift_JIS (cp932) のため、Qwen2.5-VL が出力したプロンプトに含まれる特殊記号・絵文字・漢字が出力できずにクラッシュする。
   - **対策**: `backend/main.py` および `backend/video_engine.py` の先頭で `sys.stdout.reconfigure(encoding='utf-8', errors='replace')` を明示実行。
2. **`memory allocation of 83886080 bytes failed` (Rust アロケータエラー)**:
   - **原因**: Diffusers のモデルロード時に全重みを一度に RAM に展開しようとして Windows の連続メモリが枯渇する。
   - **対策**: `from_pretrained(..., low_cpu_mem_usage=True)` を必須指定。
3. **`c10.dll Access Violation (0xc0000005)`**:
   - **原因**: Wan 2.2 の GPU 計算中に FastAPI のポーリング（`/api/gpu`）が同時に `torch.cuda` の C++ テンソルアロケータを叩くことによるレースコンディション。
   - **対策**: `model_engine.py` の `get_gpu_info()` に 1秒間インメモリキャッシュを導入し、スレッドセーフ化。

### (3) キャラクター同一性と画風の維持

* **キャラ固定**: `backend/character_profiles/elena_valkyrie.json` などのキャラプロファイル DNA タグ（`platinum blonde braided hair, sharp blue eyes, fair skin, heroic facial features, gladiator leather battle top` 等）がキーフレーム静止画プロンプトに必ず先頭注入されます。
* **画風維持**: `backend/style_profiles/3d_render_style.json` のスタイルタグ（`3d render, octane render, blender 3d style, smooth 3d shading, stylized 3d animation, unreal engine 5 cinematic` 等）を付与することで、一貫した 3Dレンダー風 CG の質感が全カットで維持されます。
* **モーションプロンプト**: カメラワーク主体の指示（`The camera smoothly circles the character as gentle wind sways her hair...`）を与えることで、四肢の崩壊を起こさずに自然な被写体動作が得られます。

---

## 4. Wan 2.2 I2V 14B 版に関する評価（結論）

* **14B 版の評価結果**:
  * 重みサイズのみで 28GB（NF4 量子化でも約 7.5GB）。
  * 3D Attention の活性化テンソルが 14B では 5GB 以上となり、オフロードを行っても 12GB VRAM に収まりきらず OOM または激しい PCIe バス待機（20〜40分/クリップ）が発生。
* **結論**: RTX 4070 Ti (12GB) において、実用的な速度（2分03秒/25ステップ）と高画質を両立できるのは **Wan 2.2 TI2V-5B（Attention Slicing + Model CPU Offload）が唯一無二の最適解** であることが実証されました。

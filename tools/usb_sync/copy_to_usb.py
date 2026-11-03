import os
import shutil
import time

src_dir = r"C:\Users\owner\.gemini\antigravity\scratch\LLM_by_norin"
dst_dir = r"H:\LLM_by_norin"

print(f"Starting copy from {src_dir} to {dst_dir}...")
start_time = time.time()

def ignore_patterns(path, names):
    ignored = set()
    for name in names:
        if name in (".venv", "node_modules", "__pycache__", ".git"):
            ignored.add(name)
        elif name.endswith(".pyc"):
            ignored.add(name)
    return ignored

if os.path.exists(dst_dir):
    shutil.rmtree(dst_dir)

shutil.copytree(src_dir, dst_dir, ignore=ignore_patterns)

elapsed = round(time.time() - start_time, 2)
print(f"Successfully copied application files in {elapsed} seconds!")

# Also copy linuxmint guide and installer directly to USB root for quick access
usb_guide = r"H:\README_FIRST.txt"
with open(usb_guide, "w", encoding="utf-8") as f:
    f.write("""==========================================================
  🐧 LLM & Image Studio - Linux Mint 導入ガイド
==========================================================

このUSBメモリには、Linux Mint用の高機能ローカルAIスタジオ
（Vision LLM、SDXL画像生成、ControlNet、構図固定リメイク、LoRA学習）
が含まれています。

【Linux Mint でのインストール・使い方】

1. このUSBをLinux Mintのパソコンに挿入します。

2. 「LLM_by_norin」フォルダを、お好みの場所（例: ホームディレクトリ ~/）
   にコピーします。（USBから直接起動することも可能です）

3. 端末（Terminal: Ctrl + Alt + T）を開き、linuxmintフォルダに移動して
   インストーラを実行します:

   cd ~/LLM_by_norin/linuxmint
   chmod +x install_linuxmint.sh
   ./install_linuxmint.sh

4. インストールが完了すると、デスクトップおよびスタートメニュー
   （グラフィックス -> LLM & Image Studio）にアプリアイコンが作成されます！
   アイコンをダブルクリックするだけで、ネイティブGUIアプリが起動します。

詳しい操作マニュアルは、
LLM_by_norin/linuxmint/LINUXMINT_GUIDE.md
をご覧ください。
==========================================================
""")

usb_installer = r"H:\install_linuxmint.sh"
with open(usb_installer, "w", encoding="utf-8") as f:
    f.write("""#!/usr/bin/env bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_DIR="$SCRIPT_DIR/LLM_by_norin/linuxmint"

if [ -f "$TARGET_DIR/install_linuxmint.sh" ]; then
    chmod +x "$TARGET_DIR/install_linuxmint.sh"
    cd "$TARGET_DIR"
    ./install_linuxmint.sh
else
    echo "Error: Could not find LLM_by_norin/linuxmint/install_linuxmint.sh"
    exit 1
fi
""")

print("Created USB root helper files (README_FIRST.txt, install_linuxmint.sh)")

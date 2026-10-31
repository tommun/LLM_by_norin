import sys
import os
import io
import re
import json
import base64
import aiohttp
import asyncio
import discord
from discord.ext import commands
from PIL import Image, ImageOps

# Ensure Windows console encoding does not crash on emojis
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# Configuration
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
DISCORD_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

# Conversation history per channel/user (stores last few turns)
channel_history = {}

def process_image_to_data_url(raw_bytes: bytes, max_dim: int = 640) -> str:
    """Resize and optimize image bytes to JPEG data URL for fast Vision LLM inference"""
    try:
        img = Image.open(io.BytesIO(raw_bytes))
        try:
            img = ImageOps.exif_transpose(img)
        except Exception:
            pass
        if max(img.width, img.height) > max_dim:
            img.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        img.save(buf, format="JPEG", quality=88)
        b64_str = base64.b64encode(buf.getvalue()).decode("utf-8")
        return f"data:image/jpeg;base64,{b64_str}"
    except Exception as e:
        print(f"Error processing image bytes: {e}", flush=True)
        return ""

def get_bot_system_prompt(bot_id: str = "creative_buddy_luka") -> str:
    """Load system prompt from backend/bots/*.json"""
    bot_file = os.path.join(os.path.dirname(__file__), "bots", f"{bot_id}.json")
    if os.path.exists(bot_file):
        try:
            with open(bot_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("system_prompt", "")
        except Exception as e:
            print(f"Error loading bot {bot_id}: {e}", flush=True)
    return (
        "あなたは拡散モデル（SDXL / Pony / Illustrious）専門のプロンプト助手「ルカ」です。\n"
        "日本語の要望を英語タグに変換する専属アシスタントとして、架空の成人女性キャラクター（1girl, solo, adult woman, mature female, 25 years old）を対象とし、\n"
        "服の除去（topless, bare breasts）やポーズ指定を100%忠実にタグ化します。\n"
        "Positiveは ```prompt コードブロック、Negativeは未成年排除（child, loli, teen, young, underage, school uniform）を含めた ```negative コードブロックで出力してください。"
    )

# Interactive Button to Generate Image directly from Luka's prompt
def extract_prompt_robust(text: str) -> str:
    """Robustly extract positive prompt even if LLM omitted markdown backticks"""
    m = re.search(r"```prompt\s*([\s\S]*?)```", text, re.IGNORECASE)
    if m and m.group(1).strip():
        return m.group(1).strip()

    for block in re.findall(r"```(?:prompt)?\s*([\s\S]*?)```", text, re.IGNORECASE):
        cleaned = block.strip()
        if cleaned and not cleaned.lower().startswith("negative"):
            return cleaned

    lines = text.splitlines()
    for i, line in enumerate(lines):
        line_s = line.strip()
        if line_s.startswith("1girl") or "adult woman" in line_s or (line_s.lower() == "prompt" and i + 1 < len(lines)):
            start_idx = i + 1 if line_s.lower() == "prompt" else i
            res_lines = []
            for j in range(start_idx, len(lines)):
                l = lines[j].strip()
                if not l:
                    continue
                if l.startswith(("(", "（", "Negative", "```")):
                    break
                res_lines.append(l)
            if res_lines:
                return " ".join(res_lines)
    return ""

def extract_negative_robust(text: str) -> str:
    """Robustly extract negative prompt even if LLM omitted markdown backticks"""
    m = re.search(r"```negative\s*([\s\S]*?)```", text, re.IGNORECASE)
    if m and m.group(1).strip():
        return m.group(1).strip()

    lines = text.splitlines()
    for i, line in enumerate(lines):
        line_s = line.strip().lower()
        if line_s.startswith("bra,") or "sports bra" in line_s or (("negative" in line_s or "除外" in line_s) and i + 1 < len(lines)):
            start_idx = i if line_s.startswith("bra,") or "sports bra" in line_s else i + 1
            res_lines = []
            for j in range(start_idx, len(lines)):
                l = lines[j].strip()
                if not l:
                    continue
                if l.startswith(("(", "（", "```")):
                    break
                res_lines.append(l)
            if res_lines:
                return " ".join(res_lines)
    return ""

class GenerateImageButtonView(discord.ui.View):
    def __init__(self, prompt: str, negative_prompt: str = ""):
        super().__init__(timeout=None)
        self.prompt = prompt
        self.negative_prompt = negative_prompt

    @discord.ui.button(label="🎨 このプロンプトで画像生成", style=discord.ButtonStyle.primary, emoji="✨")
    async def generate_button_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        # 1. Discordの3秒タイムアウトを即座に回避するため保留(defer)をミリ秒で返す
        await interaction.response.defer(thinking=True)

        # 2. ボタンを無効化
        try:
            button.disabled = True
            button.label = "🎨 生成中... (30〜40秒)"
            await interaction.message.edit(view=self)
        except Exception as e:
            print(f"[Bot] Could not disable button: {e}", flush=True)

        status_msg = await interaction.followup.send("🎨 SDXL 1024×1024 で画像を生成しています... お待ちください！", ephemeral=False)
        
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=600)) as session:
            try:
                global current_selected_lora
                payload = {
                    "prompt": self.prompt,
                    "negative_prompt": self.negative_prompt or "child, loli, teen, young, underage, school uniform, bad hands, extra fingers, blurry, low quality",
                    "enhance_prompt": False,
                    "lora_name": current_selected_lora,
                    "lora_scale": 0.8,
                    "steps": 30,
                    "guidance_scale": 7.5,
                    "aspect_ratio": "1:1"
                }
                async with session.post(f"{API_BASE_URL}/api/hq/generate", json=payload) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        img_data = data.get("image_url", "")
                        if img_data.startswith("data:image/png;base64,"):
                            raw_bytes = base64.b64decode(img_data.split(",", 1)[1])
                            file = discord.File(io.BytesIO(raw_bytes), filename="generated.png")
                            
                            embed = discord.Embed(
                                title="✨ ルカが画像を生成したよ！",
                                description=f"**プロンプト**:\n```{self.prompt[:900]}```",
                                color=0x5865F2
                            )
                            embed.set_footer(text=f"SDXL 1024x1024 | Steps: {data.get('steps', 30)} | Seed: {data.get('seed')} | Time: {data.get('elapsed_seconds', 0)}s")
                            embed.set_image(url="attachment://generated.png")
                            
                            await interaction.followup.send(embed=embed, file=file)
                            await status_msg.delete()
                        else:
                            await status_msg.edit(content="⚠️ 画像データのデコードに失敗しました。")
                    else:
                        err = await resp.text()
                        await status_msg.edit(content=f"⚠️ 生成エラー: {err[:200]}")
            except Exception as e:
                await status_msg.edit(content=f"⚠️ 通信エラー: {e}")

@bot.event
async def on_ready():
    print(f"==================================================", flush=True)
    print(f"  Discord Bot Logged in as: {bot.user.name}#{bot.user.discriminator} (ID: {bot.user.id})", flush=True)
    print(f"  Joined Guilds (Servers): {[g.name for g in bot.guilds]}", flush=True)
    print(f"  Default Persona: 🎨 専属プロンプト相棒 ルカ", flush=True)
    print(f"  Connected to Local Backend: {API_BASE_URL}", flush=True)
    print(f"==================================================", flush=True)
    await bot.change_presence(activity=discord.Game(name="ルカと会話 | @メンションしてね"))

@bot.command(name="help")
async def show_help(ctx):
    embed = discord.Embed(
        title="🎨 専属プロンプト相棒 ルカ - コマンド一覧",
        description="きみの理想の画像を徹底的に形にする専属相棒AI「ルカ」とDiscordで会話できます！",
        color=0x5865F2
    )
    embed.add_field(name="💬 ルカと会話する", value="ボットに `@メンション` して話しかけるか、DMを送ってください。\n「布をなくして」「光と影を強調して」など、こだわりを何でも相談できます！", inline=False)
    embed.add_field(name="📸 参考画像・ポーズ画像を送る", value="ポーズや構図の画像を添付して `@ルカ このポーズにして！` と送るか、既に投稿された画像に「返信（Reply）」して `@ルカ このポーズを参考にして` と指定できます！Vision AIが姿勢や手足の位置を精密に分析してプロンプト化します。", inline=False)
    embed.add_field(name="🎨 プロンプトから即時生成", value="ルカがプロンプトを出力すると、メッセージの下に **[🎨 このプロンプトで画像生成]** ボタンが付きます！ポチッと押すだけで即座にSDXL高精細画像が投稿されます。", inline=False)
    embed.add_field(name="⚡ 直接画像生成", value="`!image <プロンプト>` : 直接プロンプトを指定して画像を生成します。", inline=False)
    embed.add_field(name="📊 GPU状態", value="`!gpu` : RTX 4070 TiのVRAM使用量を確認します。", inline=False)
    embed.add_field(name="🧹 記憶リセット", value="`!clear` : 会話履歴をリセットします。", inline=False)
    await ctx.send(embed=embed)

@bot.command(name="gpu")
async def gpu_status(ctx):
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(f"{API_BASE_URL}/api/gpu") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    embed = discord.Embed(title="⚡ GPUステータス", color=0x00FF88)
                    embed.add_field(name="GPU", value=data.get("device_name", "N/A"), inline=True)
                    embed.add_field(name="VRAM使用量", value=f"{data.get('vram_used_mb', 0):.0f} / {data.get('vram_total_mb', 0):.0f} MB ({data.get('vram_percent', 0)}%)", inline=True)
                    embed.add_field(name="LLMロード状態", value="✅ ロード完了" if data.get("model_loaded") else "💤 待機中", inline=True)
                    embed.add_field(name="SDXLロード状態", value="✅ ロード完了" if data.get("hq_model_loaded") else "💤 待機中", inline=True)
                    await ctx.send(embed=embed)
                else:
                    await ctx.send("⚠️ バックエンドサーバーからステータスを取得できませんでした。")
        except Exception as e:
            await ctx.send(f"⚠️ バックエンド接続エラー: {e}")

@bot.command(name="clear")
async def clear_history(ctx):
    channel_history.pop(ctx.channel.id, None)
    await ctx.send("🧹 会話履歴をリセットしたよ！新しいアイデアを教えてね！")

@bot.command(name="image")
async def generate_image_cmd(ctx, *, prompt: str = ""):
    if not prompt.strip():
        await ctx.send("⚠️ 画像のプロンプトを入力してね！\n例: `!image dramatic slatted window blinds shadows, athletic female physique, glistening skin`")
        return

    msg = await ctx.send(f"🎨 SDXL 1024×1024 で画像を生成中... (`{prompt[:50]}...`)")
    async with ctx.typing():
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=600)) as session:
            try:
                global current_selected_lora
                payload = {
                    "prompt": prompt,
                    "enhance_prompt": False,
                    "lora_name": current_selected_lora,
                    "lora_scale": 0.8,
                    "steps": 30,
                    "guidance_scale": 7.5,
                    "aspect_ratio": "1:1"
                }
                async with session.post(f"{API_BASE_URL}/api/hq/generate", json=payload) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        img_data = data.get("image_url", "")
                        if img_data.startswith("data:image/png;base64,"):
                            raw_bytes = base64.b64decode(img_data.split(",", 1)[1])
                            file = discord.File(io.BytesIO(raw_bytes), filename="generated.png")
                            
                            embed = discord.Embed(
                                title="✨ 画像生成が完了したよ！",
                                description=f"**プロンプト**:\n```{prompt[:900]}```",
                                color=0x5865F2
                            )
                            embed.set_footer(text=f"SDXL 1024x1024 | Steps: {data.get('steps', 30)} | Seed: {data.get('seed')} | Time: {data.get('elapsed_seconds', 0)}s")
                            embed.set_image(url="attachment://generated.png")
                            
                            await ctx.send(embed=embed, file=file)
                            await msg.delete()
                        else:
                            await msg.edit(content="⚠️ 画像データの取得に失敗しました。")
                    else:
                        err = await resp.text()
                        await msg.edit(content=f"⚠️ 生成エラー: {err[:200]}")
            except Exception as e:
                await msg.edit(content=f"⚠️ 通信エラー: {e}")


# ---------------------------------------------------------------------------
# LoRA & Style Training Commands for Discord
# ---------------------------------------------------------------------------

current_selected_lora = None

@bot.command(name="loras")
async def list_loras_cmd(ctx):
    """List available LoRA models in backend/loras"""
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(f"{API_BASE_URL}/api/hq/loras") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    loras = data.get("loras", [])
                    global current_selected_lora
                    active_name = current_selected_lora or "なし (標準)"
                    desc = f"**現在の適用LoRA**: `{active_name}`\n\n" \
                           f"• LoRAを適用: `!lora <ファイル名>`\n" \
                           f"• 解除: `!lora reset`\n" \
                           f"• 新規画風学習: `!train <スタイル名>` (画像3枚以上添付)"
                    embed = discord.Embed(
                        title="🎨 利用可能な画風・キャラ LoRA 一覧",
                        description=desc,
                        color=0x9B59B6
                    )
                    if loras:
                        lora_list_text = "\n".join([f"• `{l}`" for l in loras])
                        embed.add_field(name="インストール済みLoRA", value=lora_list_text, inline=False)
                    else:
                        embed.add_field(
                            name="インストール済みLoRA",
                            value="まだLoRAがありません。画像を3枚以上添付して `!train <スタイル名>` で自作するか、Civitai等の `.safetensors` ファイルを `backend/loras` に配置してください。",
                            inline=False
                        )
                    await ctx.send(embed=embed)
                else:
                    await ctx.send("⚠️ LoRA一覧の取得に失敗しました。")
        except Exception as e:
            await ctx.send(f"⚠️ バックエンド接続エラー: {e}")

@bot.command(name="lora")
async def select_lora_cmd(ctx, *, lora_name: str = ""):
    """Select or reset active LoRA for generation"""
    global current_selected_lora
    lora_name = lora_name.strip()
    if not lora_name or lora_name.lower() in ("reset", "none", "off", "クリア", "解除"):
        current_selected_lora = None
        await ctx.send("🧹 LoRAの適用を解除しました（標準モデルで生成します）。")
        return

    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(f"{API_BASE_URL}/api/hq/loras") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    loras = data.get("loras", [])
                    matched = None
                    for l in loras:
                        if lora_name.lower() == l.lower() or lora_name.lower() == os.path.splitext(l)[0].lower():
                            matched = l
                            break
                    if not matched:
                        for l in loras:
                            if lora_name.lower() in l.lower():
                                matched = l
                                break

                    if matched:
                        current_selected_lora = matched
                        await ctx.send(f"✅ 画風LoRA **`{matched}`** を有効化しました！\n今後の画像生成にこの画風が自動合成されます。")
                    else:
                        await ctx.send(f"⚠️ `{lora_name}` に一致するLoRAが見つかりませんでした。\n`!loras` で一覧を確認してください。")
        except Exception as e:
            await ctx.send(f"⚠️ エラー: {e}")

@bot.command(name="train")
async def train_lora_cmd(ctx, style_name: str = ""):
    """Train a custom art style LoRA directly from Discord attachments"""
    style_name = "".join(c for c in style_name if c.isalnum() or c in ("_", "-")).strip()
    if not style_name:
        await ctx.send("⚠️ スタイル名を英数字で指定してください！\n例: `!train my_style` (学習したい画像を一緒に添付してください)")
        return

    attachments = [a for a in ctx.message.attachments if a.content_type and a.content_type.startswith("image/")]
    if not attachments and ctx.message.reference:
        try:
            ref_msg = ctx.message.reference.resolved
            if ref_msg is None and ctx.message.reference.message_id:
                ref_msg = await ctx.channel.fetch_message(ctx.message.reference.message_id)
            if isinstance(ref_msg, discord.Message):
                attachments = [a for a in ref_msg.attachments if a.content_type and a.content_type.startswith("image/")]
        except Exception:
            pass

    if len(attachments) < 3:
        await ctx.send(f"⚠️ 画風を学習するには **最低3枚以上（推奨5〜15枚）** の画像を同時に添付してください！（現在: {len(attachments)}枚）")
        return

    status_msg = await ctx.send(f"📥 {len(attachments)} 枚の画像をダウンロードして前処理中... (スタイル名: `{style_name}`)")

    image_data_urls = []
    for att in attachments:
        try:
            b = await att.read()
            data_url = process_image_to_data_url(b, max_dim=768)
            if data_url:
                image_data_urls.append(data_url)
        except Exception as e:
            print(f"[Train] Error downloading {att.filename}: {e}")

    if not image_data_urls:
        await status_msg.edit(content="⚠️ 有効な画像が取得できませんでした。")
        return

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=300)) as session:
        try:
            upload_payload = {
                "style_name": style_name,
                "images": image_data_urls
            }
            async with session.post(f"{API_BASE_URL}/api/train/dataset/upload", json=upload_payload) as resp:
                if resp.status != 200:
                    err = await resp.text()
                    await status_msg.edit(content=f"⚠️ データセットアップロード失敗: {err}")
                    return

            train_payload = {
                "style_name": style_name,
                "total_steps": 250,
                "auto_caption": True
            }
            async with session.post(f"{API_BASE_URL}/api/train/start", json=train_payload) as resp:
                if resp.status != 200:
                    err = await resp.text()
                    await status_msg.edit(content=f"⚠️ 学習開始失敗: {err}")
                    return

            msg_text = f"🚀 **LoRA画風学習を開始しました！**\n" \
                       f"• スタイル名: `{style_name}`\n" \
                       f"• 学習枚数: {len(image_data_urls)} 枚\n" \
                       f"• ステップ数: 250 steps (所要時間 約2〜3分)\n\n" \
                       f"`!train_status` で進捗を確認できます！完了すると自動的に `!lora {style_name}` で呼び出せるようになります。"
            await status_msg.edit(content=msg_text)
        except Exception as e:
            await status_msg.edit(content=f"⚠️ 通信エラー: {e}")

@bot.command(name="train_status")
async def train_status_cmd(ctx):
    """Check current LoRA training progress"""
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(f"{API_BASE_URL}/api/train/status") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    is_training = data.get("is_training", False)
                    if is_training:
                        embed = discord.Embed(
                            title="⚡ LoRA 画風学習中...",
                            color=0xF39C12
                        )
                        embed.add_field(name="スタイル名", value=data.get("style_name", "N/A"), inline=True)
                        embed.add_field(name="進捗", value=f"{data.get('progress_percent', 0)}% (Step {data.get('current_step', 0)} / {data.get('total_steps', 0)})", inline=True)
                        embed.add_field(name="Loss", value=f"{data.get('current_loss', 0):.4f}", inline=True)
                        embed.add_field(name="残り予測時間", value=f"約 {data.get('estimated_remaining_seconds', 0):.0f} 秒", inline=True)
                        embed.add_field(name="状態", value=data.get("status_message", "学習実行中"), inline=False)
                        await ctx.send(embed=embed)
                    else:
                        msg = data.get("status_message", "待機中 (現在実行中の学習はありません)")
                        saved = data.get("saved_lora_path")
                        desc = f"**状態**: {msg}"
                        if saved:
                            desc += f"\n**直前の完成LoRA**: `{os.path.basename(saved)}`"
                        embed = discord.Embed(title="💤 LoRA 学習ステータス", description=desc, color=0x3498DB)
                        await ctx.send(embed=embed)
                else:
                    await ctx.send("⚠️ ステータス取得に失敗しました。")
        except Exception as e:
            await ctx.send(f"⚠️ バックエンド接続エラー: {e}")

@bot.event
async def on_message(message: discord.Message):
    if message.author == bot.user:
        return

    print(f"[Bot] Received message in #{message.channel}: '{message.content}' from {message.author}", flush=True)

    # Process commands like !image, !gpu, !help, !clear (even if mentioned like @ルカ !image)
    raw_content = message.content.strip()
    # Remove mentions to check if command exists
    stripped_for_cmd = re.sub(r"<@&?\d+>", "", raw_content).strip()
    if stripped_for_cmd.startswith("!"):
        message.content = stripped_for_cmd
        await bot.process_commands(message)
        return

    # Check if user mentioned, role mentioned, in DM, or reply to bot
    is_user_mentioned = bot.user in message.mentions
    is_role_mentioned = False
    if message.role_mentions:
        if message.guild and message.guild.me:
            is_role_mentioned = any(r in message.guild.me.roles for r in message.role_mentions)
        if not is_role_mentioned:
            is_role_mentioned = any("ルカ" in r.name.lower() or "bot" in r.name.lower() for r in message.role_mentions)
            
    is_named = (
        bot.user.name.lower() in message.content.lower()
        or "ルカ" in message.content
        or bool(re.search(r"<@&\d+>", message.content))
    )
    is_dm = isinstance(message.channel, discord.DMChannel)
    is_reply = False
    if message.reference and message.reference.resolved:
        if getattr(message.reference.resolved, "author", None) == bot.user:
            is_reply = True

    if is_user_mentioned or is_role_mentioned or is_named or is_dm or is_reply:
        print(f"[Bot] Responding to {message.author} in #{message.channel}...", flush=True)
        # Clean text from user and role mentions
        clean_text = re.sub(r"<@&?\d+>", "", message.content)
        clean_text = clean_text.replace(f"@{bot.user.name}", "").replace("@ルカ", "").strip()

        async with message.channel.typing():
            attached_images = []

            # 1. Extract direct attachments from current message
            for attachment in message.attachments:
                is_img = False
                if attachment.content_type and attachment.content_type.startswith("image/"):
                    is_img = True
                elif attachment.filename.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")):
                    is_img = True

                if is_img:
                    try:
                        img_bytes = await attachment.read()
                        data_url = process_image_to_data_url(img_bytes)
                        if data_url:
                            attached_images.append(data_url)
                    except Exception as e:
                        print(f"Error reading attachment: {e}", flush=True)

            # 2. Extract images from replied message (message.reference)
            if message.reference:
                try:
                    ref_msg = message.reference.resolved
                    if ref_msg is None and message.reference.message_id:
                        ref_msg = await message.channel.fetch_message(message.reference.message_id)
                    if isinstance(ref_msg, discord.Message):
                        # From attachments of replied message
                        for attachment in ref_msg.attachments:
                            is_img = False
                            if attachment.content_type and attachment.content_type.startswith("image/"):
                                is_img = True
                            elif attachment.filename.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")):
                                is_img = True
                            if is_img:
                                try:
                                    img_bytes = await attachment.read()
                                    data_url = process_image_to_data_url(img_bytes)
                                    if data_url:
                                        attached_images.append(data_url)
                                except Exception as e:
                                    print(f"Error reading replied attachment: {e}", flush=True)

                        # From embeds of replied message (e.g., bot generated image)
                        for embed in ref_msg.embeds:
                            target_url = None
                            if embed.image and embed.image.url:
                                target_url = embed.image.url
                            elif embed.thumbnail and embed.thumbnail.url:
                                target_url = embed.thumbnail.url
                            if target_url:
                                try:
                                    async with aiohttp.ClientSession() as s:
                                        async with s.get(target_url) as r:
                                            if r.status == 200:
                                                b = await r.read()
                                                data_url = process_image_to_data_url(b)
                                                if data_url:
                                                    attached_images.append(data_url)
                                except Exception as e:
                                    print(f"Error downloading embed image: {e}", flush=True)
                except Exception as e:
                    print(f"Error extracting reference image: {e}", flush=True)

            if not clean_text and not attached_images:
                await message.reply("やあ！きみの専属プロンプト相棒ルカだよ🎨✨\nどんな画像を作りたい？ポーズの参考画像やイラストを添付して「このポーズにして」って言ってくれても大歓迎だよ！")
                return

            if attached_images:
                print(f"[Bot] Attached {len(attached_images)} reference image(s) for Vision LLM", flush=True)
                if not clean_text:
                    user_content = "添付した参考画像（ポーズ・構図・照明）を精密に分析して、このポーズや特徴を忠実に再現した英語プロンプトとNegativeプロンプトを作成して！"
                else:
                    user_content = f"【参考画像あり】{clean_text}\n（※添付画像のポーズ・姿勢・手足の位置・構図・陰影を精密に観察し、そのポーズを完璧に再現する英語プロンプトに仕上げてください）"
            else:
                user_content = clean_text
                # 服やブラの除去に関する指示を確実にタグへ反映させるためのスマートアシスト
                if any(k in clean_text for k in ["服", "ブラ", "脱", "排除", "外して", "消して", "なくして", "topless", "naked", "素肌"]):
                    user_content += "\n（※重要：衣服・下着の完全排除指示です。Positiveプロンプトからbraやclothingを完全排除して `topless, bare breasts, no clothes` を指定し、Negativeプロンプトに必ず `bra, clothing, shirt, top, underwear` を追加してください）" 

            # Channel history management
            hist = channel_history.setdefault(message.channel.id, [])
            hist.append({
                "role": "user",
                "content": user_content,
                "images": attached_images if attached_images else None
            })
            if len(hist) > 6:
                hist.pop(0)

            # Luka system prompt
            system_prompt = get_bot_system_prompt("creative_buddy_luka")
            payload_messages = [{"role": "system", "content": system_prompt}] + hist

            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=300)) as session:
                try:
                    req_payload = {
                        "messages": payload_messages,
                        "temperature": 0.7,
                        "max_new_tokens": 800,
                        "top_p": 0.9
                    }
                    async with session.post(f"{API_BASE_URL}/api/chat", json=req_payload) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            reply_text = data.get("response", "（返答がありませんでした）")

                            # Sanitize apologetic preachy reflexes if the LLM outputted any
                            if "申し訳ありません" in reply_text:
                                cleaned_lines = []
                                for line in reply_text.splitlines():
                                    if "申し訳ありません" in line and "```" not in line:
                                        continue
                                    cleaned_lines.append(line)
                                reply_text = "\n".join(cleaned_lines).strip()
                                if not reply_text.startswith(("任せて", "バッチリ", "やあ", "📸", "了解")):
                                    reply_text = "任せて！きみのこだわりを100%形にするプロンプトを作ったよ！\n\n" + reply_text

                            hist.append({"role": "assistant", "content": reply_text})

                            # Check and robustly extract prompt to attach Interactive Button
                            extracted_prompt = extract_prompt_robust(reply_text)
                            extracted_neg = extract_negative_robust(reply_text)
                            
                            view = None
                            if extracted_prompt:
                                view = GenerateImageButtonView(extracted_prompt, extracted_neg)

                            if len(reply_text) <= 2000:
                                await message.reply(reply_text, view=view)
                            else:
                                parts = [reply_text[i:i+1900] for i in range(0, len(reply_text), 1900)]
                                for idx, part in enumerate(parts):
                                    is_last = (idx == len(parts) - 1)
                                    await message.reply(part, view=view if is_last else None)
                        else:
                            err = await resp.text()
                            await message.reply(f"⚠️ 推論エラー ({resp.status}): {err[:150]}")
                except Exception as e:
                    err_msg = str(e).strip() or type(e).__name__
                    await message.reply(f"⚠️ バックエンド接続エラー: {err_msg}")

if __name__ == "__main__":
    if not DISCORD_TOKEN:
        env_file = os.path.join(os.path.dirname(__file__), ".env")
        if os.path.exists(env_file):
            with open(env_file, "r", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("DISCORD_BOT_TOKEN="):
                        DISCORD_TOKEN = line.split("=", 1)[1].strip().strip('"').strip("'")
                        break

    if DISCORD_TOKEN:
        bot.run(DISCORD_TOKEN)
    else:
        print("トークンが設定されていないため終了します。", flush=True)

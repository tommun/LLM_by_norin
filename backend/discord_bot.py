import os
import io
import re
import json
import base64
import aiohttp
import asyncio
import discord
from discord.ext import commands

# Configuration
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
DISCORD_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

# Conversation history per channel/user (stores last few turns)
channel_history = {}
channel_current_bot = {}

def get_bot_system_prompt(bot_id: str = "creative_buddy_luka") -> str:
    """Load system prompt from backend/bots/*.json"""
    bot_file = os.path.join(os.path.dirname(__file__), "bots", f"{bot_id}.json")
    if os.path.exists(bot_file):
        try:
            with open(bot_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("system_prompt", "")
        except Exception as e:
            print(f"Error loading bot {bot_id}: {e}")
    # Fallback to Luka
    return (
        "あなたは画像生成（Midjourney v6 / SDXL）専門の専属クリエイティブ相棒「ルカ」です。\n"
        "【口調】一人称は「ボク」、二人称は「きみ」。フランクで明るく頼もしい相棒口調（「〜だよ！」「任せて！」「〜してみようか！」）で話してください。\n"
        "【ルール】ユーザーの意図（布やブラの除去、露出、光と影の陰影強調など）を100%最優先にし、勝手な衣服の追加や無難化を固く禁止します。\n"
        "必ず最新の英語プロンプトを ```prompt コードブロック、除外設定を ```negative コードブロックで出力してください。"
    )

# Interactive Button to Generate Image directly from Luka's prompt
class GenerateImageButtonView(discord.ui.View):
    def __init__(self, prompt: str, negative_prompt: str = ""):
        super().__init__(timeout=300)
        self.prompt = prompt
        self.negative_prompt = negative_prompt

    @discord.ui.button(label="🎨 このプロンプトで画像生成", style=discord.ButtonStyle.primary, emoji="✨")
    async def generate_button_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        button.disabled = True
        button.label = "🎨 生成中... (30〜40秒)"
        await interaction.response.edit_message(view=self)
        
        status_msg = await interaction.followup.send(f"🎨 SDXL 1024×1024 で画像を生成しています... お待ちください！", ephemeral=False)
        
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=180)) as session:
            try:
                payload = {
                    "prompt": self.prompt,
                    "negative_prompt": self.negative_prompt or "no underwear, avoid overfitting the body",
                    "enhance_prompt": False,
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
                            
                            await interaction.channel.send(embed=embed, file=file)
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
    print(f"==================================================")
    print(f"  Discord Bot Logged in as: {bot.user.name} ({bot.user.id})")
    print(f"  Default Persona: 🎨 専属プロンプト相棒 ルカ")
    print(f"  Connected to Local Backend: {API_BASE_URL}")
    print(f"==================================================")
    await bot.change_presence(activity=discord.Game(name="ルカと会話 | @メンションしてね"))

@bot.command(name="help")
async def show_help(ctx):
    embed = discord.Embed(
        title="🎨 専属プロンプト相棒 ルカ - コマンド一覧",
        description="きみの理想の画像を徹底的に形にする専属相棒AI「ルカ」とDiscordで会話できます！",
        color=0x5865F2
    )
    embed.add_field(name="💬 ルカと会話する", value="ボットに `@メンション` して話しかけるか、DMを送ってください。\n「布をなくして」「光と影を強調して」など、こだわりを何でも相談できます！\n画像を添付して「この画像をもっとこうしたい」と送ることも可能です。", inline=False)
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
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=180)) as session:
            try:
                payload = {
                    "prompt": prompt,
                    "enhance_prompt": False,
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

@bot.event
async def on_message(message: discord.Message):
    if message.author == bot.user:
        return

    # Process commands like !image, !gpu, !help, !clear
    if message.content.startswith("!"):
        await bot.process_commands(message)
        return

    # Check if mentioned or in DM
    is_dm = isinstance(message.channel, discord.DMChannel)
    is_mentioned = bot.user in message.mentions

    if is_mentioned or is_dm:
        clean_text = message.clean_content.replace(f"@{bot.user.name}", "").strip()
        if not clean_text and not message.attachments:
            await message.reply("やあ！きみの専属プロンプト相棒ルカだよ🎨✨\nどんな画像を作りたい？布をなくしたり、光と影の陰影を強くしたり、どんなこだわりでも教えてね！")
            return

        async with message.channel.typing():
            attached_images = []
            for attachment in message.attachments:
                if attachment.content_type and attachment.content_type.startswith("image/"):
                    try:
                        img_bytes = await attachment.read()
                        b64_str = base64.b64encode(img_bytes).decode("utf-8")
                        data_url = f"data:{attachment.content_type};base64,{b64_str}"
                        attached_images.append(data_url)
                    except Exception as e:
                        print(f"Error reading image: {e}")

            # Channel history management
            hist = channel_history.setdefault(message.channel.id, [])
            hist.append({
                "role": "user",
                "content": clean_text or "この画像について説明して、プロンプトをブラッシュアップして！",
                "images": attached_images if attached_images else None
            })
            if len(hist) > 6:
                hist.pop(0)

            # Luka system prompt
            system_prompt = get_bot_system_prompt("creative_buddy_luka")
            payload_messages = [{"role": "system", "content": system_prompt}] + hist

            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=120)) as session:
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
                            hist.append({"role": "assistant", "content": reply_text})

                            # Check if ```prompt exists to attach Interactive Button
                            prompt_match = re.search(r"```prompt\s*([\s\S]*?)```", reply_text, re.IGNORECASE)
                            neg_match = re.search(r"```negative\s*([\s\S]*?)```", reply_text, re.IGNORECASE)
                            
                            view = None
                            if prompt_match:
                                extracted_prompt = prompt_match.group(1).strip()
                                extracted_neg = neg_match.group(1).strip() if neg_match else ""
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
                    await message.reply(f"⚠️ バックエンド接続エラー: {e}")

if __name__ == "__main__":
    # Check token from environment or .env file
    if not DISCORD_TOKEN:
        env_file = os.path.join(os.path.dirname(__file__), ".env")
        if os.path.exists(env_file):
            with open(env_file, "r", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("DISCORD_BOT_TOKEN="):
                        DISCORD_TOKEN = line.split("=", 1)[1].strip().strip('"').strip("'")
                        break

    if not DISCORD_TOKEN:
        print("\n========================================================")
        print(" [!] DISCORD_BOT_TOKEN が設定されていません。")
        print("  backend/.env ファイルに DISCORD_BOT_TOKEN=あなたのトークン")
        print("  と記述するか、下記に入力してください。")
        print("========================================================\n")
        try:
            token_input = input("Discord Bot Tokenを入力してください: ").strip()
            if token_input:
                DISCORD_TOKEN = token_input
        except Exception:
            pass

    if DISCORD_TOKEN:
        bot.run(DISCORD_TOKEN)
    else:
        print("トークンが設定されていないため終了します。")

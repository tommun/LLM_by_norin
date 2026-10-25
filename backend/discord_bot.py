import os
import io
import json
import base64
import aiohttp
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

# Default System Prompt (Customizable)
DEFAULT_SYSTEM_PROMPT = (
    "あなたは親切で優秀なAIアシスタントです。自然な日本語で回答してください。"
    "画像が添付されている場合は画像の内容を正確に読み取って解説してください。"
)

@bot.event
async def on_ready():
    print(f"==================================================")
    print(f"  Discord Bot logged in as: {bot.user.name} ({bot.user.id})")
    print(f"  Connected to Local Backend: {API_BASE_URL}")
    print(f"==================================================")
    await bot.change_presence(activity=discord.Game(name="!help | @メンションで会話"))

@bot.command(name="help")
async def show_help(ctx):
    embed = discord.Embed(
        title="🤖 ローカルGPU AI ボット コマンド一覧",
        description="自作ローカルLLM（Qwen2.5-VL）＆ SDXL画像生成とDiscordで会話できます！",
        color=0x5865F2
    )
    embed.add_field(name="💬 会話する", value="ボットに `@メンション` して話しかけるか、DMを送ってください。\n画像を添付すると画像認識も可能です！", inline=False)
    embed.add_field(name="🎨 画像を生成する", value="`!image <プロンプト>`\n例: `!image beautiful sunset beach, anime style`\nSDXL 1024×1024で高精細画像を生成して投稿します。", inline=False)
    embed.add_field(name="📊 GPU状態を確認", value="`!gpu` : RTX 4070 TiのVRAM使用率やモデル状態を表示します。", inline=False)
    embed.add_field(name="🧹 記憶をリセット", value="`!clear` : このチャンネルの会話履歴をクリアします。", inline=False)
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
    await ctx.send("🧹 このチャンネルの会話履歴をリセットしました！")

@bot.command(name="image")
async def generate_image_cmd(ctx, *, prompt: str = ""):
    if not prompt.strip():
        await ctx.send("⚠️ 画像のプロンプトを入力してください。\n例: `!image a cute cat, anime style`")
        return

    msg = await ctx.send(f"🎨 SDXL 1024×1024 で画像を生成中... (`{prompt[:50]}...`)")
    async with ctx.typing():
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=180)) as session:
            try:
                payload = {
                    "prompt": prompt,
                    "enhance_prompt": True,
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
                                title="✨ 画像生成が完了しました！",
                                description=f"**プロンプト**: {prompt}",
                                color=0x9B59B6
                            )
                            if data.get("enhanced_prompt"):
                                embed.add_field(name="🪄 拡張プロンプト", value=data["enhanced_prompt"][:1000], inline=False)
                            embed.set_footer(text=f"所要時間: {data.get('elapsed_seconds', 0)}s | Seed: {data.get('seed')}")
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
    # Ignore self messages
    if message.author == bot.user:
        return

    # Process commands like !image, !gpu, !help
    if message.content.startswith("!"):
        await bot.process_commands(message)
        return

    # Check if bot is mentioned or if it is a Direct Message
    is_dm = isinstance(message.channel, discord.DMChannel)
    is_mentioned = bot.user in message.mentions

    if is_mentioned or is_dm:
        # Remove mention string from user message
        clean_text = message.clean_content.replace(f"@{bot.user.name}", "").strip()
        if not clean_text and not message.attachments:
            await message.reply("こんにちは！何かご質問や話したいことはありますか？😊")
            return

        async with message.channel.typing():
            # Process attachments (images)
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

            # Manage conversation history (last 6 messages)
            hist = channel_history.setdefault(message.channel.id, [])
            hist.append({
                "role": "user",
                "content": clean_text or "この画像について説明してください。",
                "images": attached_images if attached_images else None
            })
            if len(hist) > 6:
                hist.pop(0)

            # Build full message payload
            payload_messages = [{"role": "system", "content": DEFAULT_SYSTEM_PROMPT}] + hist

            # Call Local LLM Backend
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=120)) as session:
                try:
                    req_payload = {
                        "messages": payload_messages,
                        "temperature": 0.7,
                        "max_new_tokens": 1024,
                        "top_p": 0.9
                    }
                    async with session.post(f"{API_BASE_URL}/api/chat", json=req_payload) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            reply_text = data.get("response", "（返答がありませんでした）")

                            # Store assistant turn in history
                            hist.append({"role": "assistant", "content": reply_text})

                            # Discord has a 2000 character limit per message
                            if len(reply_text) <= 2000:
                                await message.reply(reply_text)
                            else:
                                for i in range(0, len(reply_text), 1900):
                                    await message.reply(reply_text[i:i+1900])
                        else:
                            err = await resp.text()
                            await message.reply(f"⚠️ 推論エラー ({resp.status}): {err[:150]}")
                except Exception as e:
                    await message.reply(f"⚠️ バックエンド接続エラー: {e}")

if __name__ == "__main__":
    if not DISCORD_TOKEN:
        print("\n========================================================")
        print(" [!] DISCORD_BOT_TOKEN が設定されていません。")
        print("  環境変数 DISCORD_BOT_TOKEN を設定するか、")
        print("  backend/.env ファイルに DISCORD_BOT_TOKEN=あなたのトークン")
        print("  と記述して実行してください。")
        print("========================================================\n")
        token_input = input("Discord Bot Tokenを入力してください: ").strip()
        if token_input:
            DISCORD_TOKEN = token_input

    if DISCORD_TOKEN:
        bot.run(DISCORD_TOKEN)
    else:
        print("トークンが入力されなかったため終了します。")

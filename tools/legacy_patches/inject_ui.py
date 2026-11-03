import os

bot_path = r"C:\Users\owner\.gemini\antigravity\scratch\LLM_by_norin\backend\discord_bot.py"
with open(bot_path, "r", encoding="utf-8") as f:
    code = f.read()

# 1. Add PromptEditModal definition before RemakeInteractiveView
modal_code = '''
class PromptEditModal(discord.ui.Modal, title="🎨 プロンプト・Denoiseの微調整"):
    positive_input = discord.ui.TextInput(
        label="Positive プロンプト (タグ・指示文)",
        style=discord.TextStyle.paragraph,
        placeholder="1girl, solo, photorealistic, RAW photo, 8k, masterpiece...",
        max_length=1500,
        required=True
    )
    negative_input = discord.ui.TextInput(
        label="Negative 除外タグ (不要な要素)",
        style=discord.TextStyle.paragraph,
        placeholder="child, loli, teen, bad hands, blurry, low quality...",
        max_length=1000,
        required=False
    )
    denoise_input = discord.ui.TextInput(
        label="Denoise強度 (リメイク時のみ: 0.50〜0.70)",
        style=discord.TextStyle.short,
        placeholder="0.60",
        max_length=10,
        required=False
    )

    def __init__(self, current_prompt: str, current_neg: str = "", init_image_url: Optional[str] = None, current_denoise: float = 0.60, pose_image: Optional[str] = None, aspect_ratio: str = "9:16"):
        super().__init__()
        self.positive_input.default = (current_prompt or "")[:1500]
        self.negative_input.default = (current_neg or "child, loli, teen, young, underage, school uniform, bad hands, extra fingers, blurry, low quality")[:1000]
        if init_image_url:
            self.denoise_input.default = f"{current_denoise:.2f}"
        self.init_image_url = init_image_url
        self.pose_image = pose_image
        self.aspect_ratio = aspect_ratio

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)
        pos = self.positive_input.value.strip()
        neg = self.negative_input.value.strip()
        denoise_str = self.denoise_input.value.strip()
        denoise_val = 0.60
        if denoise_str:
            try:
                v = float(denoise_str)
                if 0.1 <= v <= 1.0:
                    denoise_val = v
            except ValueError:
                pass

        ratio_lbl = HQ_ASPECT_RATIO_DESCS.get(self.aspect_ratio, self.aspect_ratio)
        status_msg = await interaction.followup.send(
            f"✏️ **編集されたプロンプト**で再生成中... ({ratio_lbl})" if not self.init_image_url
            else f"✏️ **編集プロンプト＆Denoise {denoise_val:.2f}** でリメイク再生成中..."
        )

        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=600)) as session:
            try:
                global current_selected_lora
                payload = {
                    "prompt": pos,
                    "negative_prompt": neg or "child, loli, teen, young, underage, school uniform, bad hands, extra fingers, blurry, low quality",
                    "enhance_prompt": False,
                    "lora_name": current_selected_lora,
                    "lora_scale": 0.8,
                    "steps": 30,
                    "guidance_scale": 7.5,
                    "aspect_ratio": self.aspect_ratio,
                    "init_image": self.init_image_url,
                    "denoise_strength": denoise_val,
                    "pose_image": self.pose_image,
                    "controlnet_scale": 0.85
                }
                async with session.post(f"{API_BASE_URL}/api/hq/generate", json=payload) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        img_data = data.get("image_url", "")
                        if img_data.startswith("data:image/png;base64,"):
                            raw_b = base64.b64decode(img_data.split(",", 1)[1])
                            filename = "remake.png" if self.init_image_url else "generated.png"
                            file_to_send = discord.File(io.BytesIO(raw_b), filename=filename)
                            w = data.get("width", 832)
                            h = data.get("height", 1216)
                            
                            is_remake = bool(self.init_image_url)
                            embed = discord.Embed(
                                title=f"🔄 構図固定リメイク完了！ ({w}×{h})" if is_remake else f"✨ 画像生成完了！ ({w}×{h})",
                                description=f"""**プロンプト**:\n```{pos[:800]}```""",
                                color=0xFF0055 if is_remake else 0x5865F2
                            )
                            footer_extra = f" | Denoise: {denoise_val:.2f}" if is_remake else ""
                            embed.set_footer(text=f"RealVisXL {w}x{h} ({self.aspect_ratio}){footer_extra} | Seed: {data.get('seed')} | Time: {data.get('elapsed_seconds', 0)}s")
                            embed.set_image(url=f"attachment://{filename}")

                            if is_remake:
                                next_view = RemakeInteractiveView(
                                    prompt=pos,
                                    negative_prompt=neg,
                                    init_image_url=self.init_image_url,
                                    current_denoise=denoise_val,
                                    aspect_ratio=self.aspect_ratio
                                )
                            else:
                                next_view = PersistentGenerateButtonView(
                                    prompt=pos,
                                    negative_prompt=neg,
                                    pose_image=self.pose_image,
                                    default_ratio=self.aspect_ratio
                                )

                            await interaction.followup.send(embed=embed, file=file_to_send, view=next_view)
                            await status_msg.delete()
                        else:
                            await status_msg.edit(content="⚠️ 画像データのデコードに失敗しました。")
                    else:
                        err = await resp.text()
                        await status_msg.edit(content=f"⚠️ 生成エラー: {err[:200]}")
            except Exception as e:
                await status_msg.edit(content=f"⚠️ 通信エラー: {e}")
'''

# Check if PromptEditModal exists
if "class PromptEditModal" not in code:
    code = code.replace("class RemakeInteractiveView", modal_code + "\nclass RemakeInteractiveView")

# 2. Add Edit Prompt button to RemakeInteractiveView
remake_edit_btn = '''    @discord.ui.button(label="✏️ プロンプト編集", style=discord.ButtonStyle.secondary, emoji="✏️", custom_id="luka_remake_edit_prompt", row=0)
    async def btn_edit_prompt(self, interaction: discord.Interaction, button: discord.ui.Button):
        p = self.prompt
        neg = self.negative_prompt
        if not p and interaction.message:
            p = extract_prompt_robust(interaction.message.content or "")
            neg = extract_negative_robust(interaction.message.content or "")
        modal = PromptEditModal(
            current_prompt=p,
            current_neg=neg,
            init_image_url=self.init_image_url,
            current_denoise=self.current_denoise,
            aspect_ratio=self.aspect_ratio
        )
        await interaction.response.send_modal(modal)
'''

if "luka_remake_edit_prompt" not in code:
    code = code.replace(
        '    @discord.ui.button(label="🎲 シード変更で再生成", style=discord.ButtonStyle.primary, emoji="🎲", custom_id="luka_remake_reseed", row=0)',
        '    @discord.ui.button(label="🎲 シード変更で再生成", style=discord.ButtonStyle.primary, emoji="🎲", custom_id="luka_remake_reseed", row=0)\n' + remake_edit_btn
    )

# 3. Add Edit Prompt button to PersistentGenerateButtonView
gen_edit_btn = '''    @discord.ui.button(label="✏️ プロンプト微調整", style=discord.ButtonStyle.secondary, emoji="✏️", custom_id="luka_gen_edit_prompt")
    async def btn_edit_prompt(self, interaction: discord.Interaction, button: discord.ui.Button):
        p = self.prompt
        neg = self.negative_prompt
        if not p and interaction.message:
            p = extract_prompt_robust(interaction.message.content or "")
            neg = extract_negative_robust(interaction.message.content or "")
        modal = PromptEditModal(
            current_prompt=p,
            current_neg=neg,
            pose_image=self.pose_image,
            aspect_ratio=self.default_ratio or "1:1"
        )
        await interaction.response.send_modal(modal)
'''

if "luka_gen_edit_prompt" not in code:
    code = code.replace(
        '    @discord.ui.button(label="🎬 横長 (16:9)", style=discord.ButtonStyle.secondary, emoji="🎬", custom_id="luka_btn_16_9")',
        '    @discord.ui.button(label="🎬 横長 (16:9)", style=discord.ButtonStyle.secondary, emoji="🎬", custom_id="luka_btn_16_9")\n\n' + gen_edit_btn
    )

# 4. Add QuickControlPanelView & !menu / !panel command
panel_code = '''
class QuickControlPanelView(discord.ui.View):
    """Interactive Hub for Luka's settings, aspect ratios, and quick controls"""
    def __init__(self, channel_id: int = 0):
        super().__init__(timeout=None)
        self.channel_id = channel_id

    @discord.ui.button(label="📱 縦長 (9:16)", style=discord.ButtonStyle.primary, emoji="📱", row=0, custom_id="luka_hub_ratio_916")
    async def hub_ratio_916(self, interaction: discord.Interaction, button: discord.ui.Button):
        channel_default_ratio[interaction.channel.id] = "9:16"
        await interaction.response.send_message("✅ このチャンネルの画像サイズを **📱 スマホ縦長・全身 (9:16: 832×1216)** に設定したよ！", ephemeral=True)

    @discord.ui.button(label="🖼️ 縦長 (3:4)", style=discord.ButtonStyle.secondary, emoji="🖼️", row=0, custom_id="luka_hub_ratio_34")
    async def hub_ratio_34(self, interaction: discord.Interaction, button: discord.ui.Button):
        channel_default_ratio[interaction.channel.id] = "3:4"
        await interaction.response.send_message("✅ このチャンネルの画像サイズを **🖼️ ポスター縦長 (3:4: 896×1152)** に設定したよ！", ephemeral=True)

    @discord.ui.button(label="⏹️ 正方形 (1:1)", style=discord.ButtonStyle.secondary, emoji="⏹️", row=0, custom_id="luka_hub_ratio_11")
    async def hub_ratio_11(self, interaction: discord.Interaction, button: discord.ui.Button):
        channel_default_ratio[interaction.channel.id] = "1:1"
        await interaction.response.send_message("✅ このチャンネルの画像サイズを **⏹️ 正方形 (1:1: 1024×1024)** に設定したよ！", ephemeral=True)

    @discord.ui.button(label="🎬 横長 (16:9)", style=discord.ButtonStyle.secondary, emoji="🎬", row=0, custom_id="luka_hub_ratio_169")
    async def hub_ratio_169(self, interaction: discord.Interaction, button: discord.ui.Button):
        channel_default_ratio[interaction.channel.id] = "16:9"
        await interaction.response.send_message("✅ このチャンネルの画像サイズを **🎬 シネマ横長 (16:9: 1216×832)** に設定したよ！", ephemeral=True)

    @discord.ui.button(label="⚡ GPU稼働状況", style=discord.ButtonStyle.success, emoji="📊", row=1, custom_id="luka_hub_gpu")
    async def hub_gpu(self, interaction: discord.Interaction, button: discord.ui.Button):
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(f"{API_BASE_URL}/api/gpu") as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        embed = discord.Embed(title="⚡ RTX 4070 Ti リアルタイムステータス", color=0x00FF88)
                        embed.add_field(name="VRAM使用量", value=f"{data.get('vram_used_mb', 0):.0f} / {data.get('vram_total_mb', 0):.0f} MB ({data.get('vram_percent', 0)}%)", inline=True)
                        embed.add_field(name="LLMロード状態", value="✅ ロード完了" if data.get("model_loaded") else "💤 待機中", inline=True)
                        embed.add_field(name="SDXLロード状態", value="✅ ロード完了" if data.get("hq_model_loaded") else "💤 待機中", inline=True)
                        await interaction.response.send_message(embed=embed, ephemeral=True)
                    else:
                        await interaction.response.send_message("⚠️ GPUステータスを取得できませんでした。", ephemeral=True)
            except Exception as e:
                await interaction.response.send_message(f"⚠️ バックエンド接続エラー: {e}", ephemeral=True)

    @discord.ui.button(label="🧹 会話履歴クリア", style=discord.ButtonStyle.danger, emoji="🧹", row=1, custom_id="luka_hub_clear")
    async def hub_clear(self, interaction: discord.Interaction, button: discord.ui.Button):
        channel_history.pop(interaction.channel.id, None)
        await interaction.response.send_message("🧹 会話履歴をリセットしたよ！新しいアイデアを教えてね！", ephemeral=True)
'''

if "class QuickControlPanelView" not in code:
    code = code.replace("class RemakeInteractiveView", panel_code + "\nclass RemakeInteractiveView")

# 5. Add !panel / !menu command
menu_cmd_code = '''
@bot.command(name="menu", aliases=["panel", "config"])
async def menu_cmd(ctx):
    """Show interactive graphical control panel for all Luka features"""
    current_ratio = channel_default_ratio.get(ctx.channel.id, "1:1")
    ratio_desc = HQ_ASPECT_RATIO_DESCS.get(current_ratio, current_ratio)
    
    embed = discord.Embed(
        title="🎛️ ルカのクリエイティブ・コントロールパネル",
        description="下のボタンから画像サイズ変更やGPU確認、会話履歴のリセットがワンタップで行えます！",
        color=0x5865F2
    )
    embed.add_field(name="📐 現在のアスペクト比設定", value=f"**{ratio_desc}**", inline=True)
    embed.add_field(name="🎨 適用中のスタイルLoRA", value=f"**{current_selected_lora or 'なし (RealVisXL Native)'}**", inline=True)
    embed.add_field(name="🔄 構図固定リメイク (img2img)", value="画像添付＋`!remake [denoise(0.55-0.65)]`\n（手・噴出・デスクなどの配置を100%固定）", inline=False)
    embed.add_field(name="💡 ワンクリック機能一覧", value=(
        "・**画像サイズ切替**: 下の `📱 縦長` や `⏹️ 正方形` ボタンをタップ\n"
        "・**プロンプト微調整**: 生成後の `✏️ プロンプト微調整` ボタンで手動編集\n"
        "・**シード変更**: 生成後の `🎲 シード変更` ボタンで無限バリエーション"
    ), inline=False)
    embed.set_footer(text="いつでも !menu または !panel でこの設定画面を呼び出せます")

    view = QuickControlPanelView(channel_id=ctx.channel.id)
    await ctx.send(embed=embed, view=view)
'''

if "def menu_cmd" not in code:
    code = code.replace('@bot.command(name="help")', menu_cmd_code + '\n@bot.command(name="help")')

# 6. Add QuickControlPanelView to persistent views on on_ready
if "bot.add_view(QuickControlPanelView())" not in code:
    code = code.replace("bot.add_view(RemakeInteractiveView())", "bot.add_view(RemakeInteractiveView())\n    bot.add_view(QuickControlPanelView())")

with open(bot_path, "w", encoding="utf-8") as f:
    f.write(code)

print("Successfully injected all UI enhancements into discord_bot.py!")

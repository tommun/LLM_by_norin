import os
import re

bot_path = r"C:\Users\owner\.gemini\antigravity\scratch\LLM_by_norin\backend\discord_bot.py"
with open(bot_path, "r", encoding="utf-8") as f:
    code = f.read()

# 1. Add detect_requested_image_mode support for remake
remake_detect = '''    if any(k in t for k in ["リメイク", "img2img", "remake", "構図固定", "配置固定", "手固定", "母乳"]):
        return "remake"
'''
if "remake" not in code:
    code = code.replace('    if "ポーズ" in t:\n        return "pose_only"', remake_detect + '    if "ポーズ" in t:\n        return "pose_only"')

# 2. Add RemakeInteractiveView and _process_remake_mode into ImageModeSelectView
remake_view_code = '''
class RemakeInteractiveView(discord.ui.View):
    """Interactive view after img2img remake: re-roll seeds, tweak denoise (0.55/0.60/0.65)"""
    def __init__(self, prompt: str = "", negative_prompt: str = "", init_image_url: str = "", current_denoise: float = 0.60, aspect_ratio: str = "9:16"):
        super().__init__(timeout=None)
        self.prompt = prompt
        self.negative_prompt = negative_prompt
        self.init_image_url = init_image_url
        self.current_denoise = current_denoise
        self.aspect_ratio = aspect_ratio

    async def _execute_remake(self, interaction: discord.Interaction, denoise: float):
        await interaction.response.defer(thinking=True)
        p = self.prompt
        neg = self.negative_prompt
        init_img = self.init_image_url
        if not p and interaction.message:
            p = extract_prompt_robust(interaction.message.content or "")
            neg = extract_negative_robust(interaction.message.content or "")

        if not p:
            p = "1girl, hetero, 1boy, grabbing from behind, breast grab, grabbing, nipple, photorealistic, RAW photo, 8k, masterpiece, best quality"

        ratio_lbl = HQ_ASPECT_RATIO_DESCS.get(self.aspect_ratio, self.aspect_ratio)
        status_msg = await interaction.followup.send(f"🔄 **構図完全固定リメイク (Denoise {denoise:.2f})** で再生成中... (配置・手を100%固定)")
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=600)) as session:
            try:
                global current_selected_lora
                payload = {
                    "prompt": p,
                    "negative_prompt": neg or "child, loli, teen, young, underage, school uniform, bad hands, extra fingers, blurry, low quality",
                    "enhance_prompt": False,
                    "lora_name": current_selected_lora,
                    "lora_scale": 0.8,
                    "steps": 30,
                    "guidance_scale": 7.5,
                    "aspect_ratio": self.aspect_ratio,
                    "init_image": init_img,
                    "denoise_strength": denoise
                }
                async with session.post(f"{API_BASE_URL}/api/hq/generate", json=payload) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        img_data = data.get("image_url", "")
                        if img_data.startswith("data:image/png;base64,"):
                            raw_b = base64.b64decode(img_data.split(",", 1)[1])
                            file_to_send = discord.File(io.BytesIO(raw_b), filename="remake.png")
                            w = data.get("width", 832)
                            h = data.get("height", 1216)
                            embed = discord.Embed(
                                title=f"🔄 構図完全固定リメイク完了！ ({w}×{h})",
                                description=f"元画像の配置（後ろから掴む手・噴出・デスク）をそのまま完全固定し、RealVisXLで実写化しました！\n\n**プロンプト**:\n```{p[:800]}```",
                                color=0xFF0055
                            )
                            embed.set_footer(text=f"RealVisXL img2img {w}x{h} | Denoise: {denoise:.2f} | Seed: {data.get('seed')} | Time: {data.get('elapsed_seconds', 0)}s")
                            embed.set_image(url="attachment://remake.png")

                            new_view = RemakeInteractiveView(
                                prompt=p,
                                negative_prompt=neg,
                                init_image_url=init_img,
                                current_denoise=denoise,
                                aspect_ratio=self.aspect_ratio
                            )
                            await interaction.followup.send(embed=embed, file=file_to_send, view=new_view)
                            await status_msg.delete()
                        else:
                            await status_msg.edit(content="⚠️ 画像データのデコードに失敗しました。")
                    else:
                        err = await resp.text()
                        await status_msg.edit(content=f"⚠️ 生成エラー: {err[:200]}")
            except Exception as e:
                await status_msg.edit(content=f"⚠️ 通信エラー: {e}")

    @discord.ui.button(label="🎲 シード変更で再生成", style=discord.ButtonStyle.primary, emoji="🎲", custom_id="luka_remake_reseed", row=0)
    async def btn_reseed(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._execute_remake(interaction, self.current_denoise)

    @discord.ui.button(label="⚙️ Denoise 0.55 (元画像固定強)", style=discord.ButtonStyle.secondary, emoji="🔒", custom_id="luka_remake_d55", row=1)
    async def btn_d55(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._execute_remake(interaction, 0.55)

    @discord.ui.button(label="⚙️ Denoise 0.60 (黄金バランス)", style=discord.ButtonStyle.success, emoji="🎯", custom_id="luka_remake_d60", row=1)
    async def btn_d60(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._execute_remake(interaction, 0.60)

    @discord.ui.button(label="⚙️ Denoise 0.65 (実写質感強め)", style=discord.ButtonStyle.secondary, emoji="✨", custom_id="luka_remake_d65", row=1)
    async def btn_d65(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._execute_remake(interaction, 0.65)
'''

# Check if RemakeInteractiveView already in code
if "class RemakeInteractiveView" not in code:
    # Insert right before class PersistentGenerateButtonView
    code = code.replace("class PersistentGenerateButtonView", remake_view_code + "\nclass PersistentGenerateButtonView")

# 3. Add mode 5 button to ImageModeSelectView
mode_button_code = '''    @discord.ui.button(label="🔄 5. 構図固定リメイク (img2img / denoise 0.6)", style=discord.ButtonStyle.danger, emoji="🔄", row=2, custom_id="luka_mode_remake")
    async def mode_remake(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._process_remake_mode(interaction)
'''

remake_processor = '''    async def _process_remake_mode(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)
        img_url = self.image_data_url
        if not img_url and interaction.message:
            for att in interaction.message.attachments:
                if att.content_type and att.content_type.startswith("image/"):
                    b = await att.read()
                    img_url = process_image_to_data_url(b)
                    break

        if not img_url:
            await interaction.followup.send("⚠️ 画像データが見つかりませんでした。もう一度画像を添付してね！", ephemeral=True)
            return

        status_msg = await interaction.followup.send("🔄 **構図・手・噴出・デスクを完全固定し、Denoise 0.60 でRealVisXL実写化中...**")
        
        # Determine prompt: user instruction or default template
        p = self.user_prompt.strip() if self.user_prompt else ""
        if not p:
            # ComfyUI exact formula prompt template
            p = "1girl, hetero, 1boy, grabbing from behind, breast grab, grabbing, nipple, lactating, milk squirt, photorealistic, ultra-detailed skin, RAW photo, 8k, masterpiece, best quality"
        elif "grabbing" not in p and "breast" not in p:
            p = f"{p}, 1girl, hetero, 1boy, grabbing from behind, breast grab, grabbing, nipple, photorealistic, RAW photo, masterpiece"

        neg = "child, loli, teen, young, underage, school uniform, bad hands, extra fingers, blurry, low quality"

        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=600)) as session:
            try:
                global current_selected_lora
                payload = {
                    "prompt": p,
                    "negative_prompt": neg,
                    "enhance_prompt": False,
                    "lora_name": current_selected_lora,
                    "lora_scale": 0.8,
                    "steps": 30,
                    "guidance_scale": 7.5,
                    "aspect_ratio": "9:16",
                    "init_image": img_url,
                    "denoise_strength": 0.60
                }
                async with session.post(f"{API_BASE_URL}/api/hq/generate", json=payload) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        img_data = data.get("image_url", "")
                        if img_data.startswith("data:image/png;base64,"):
                            raw_b = base64.b64decode(img_data.split(",", 1)[1])
                            file_to_send = discord.File(io.BytesIO(raw_b), filename="remake.png")
                            w = data.get("width", 832)
                            h = data.get("height", 1216)
                            embed = discord.Embed(
                                title=f"🔄 構図完全固定リメイク完了！ ({w}×{h})",
                                description=f"元画像の配置（後ろから掴む手・噴出・デスク）をそのまま完全固定し、RealVisXLで実写化しました！\n\n**プロンプト**:\n```{p[:800]}```",
                                color=0xFF0055
                            )
                            embed.set_footer(text=f"RealVisXL img2img {w}x{h} | Denoise: 0.60 | Seed: {data.get('seed')} | Time: {data.get('elapsed_seconds', 0)}s")
                            embed.set_image(url="attachment://remake.png")

                            view = RemakeInteractiveView(
                                prompt=p,
                                negative_prompt=neg,
                                init_image_url=img_url,
                                current_denoise=0.60,
                                aspect_ratio="9:16"
                            )
                            await interaction.followup.send(embed=embed, file=file_to_send, view=view)
                            await status_msg.delete()
                        else:
                            await status_msg.edit(content="⚠️ 画像データのデコードに失敗しました。")
                    else:
                        err = await resp.text()
                        await status_msg.edit(content=f"⚠️ 生成エラー: {err[:200]}")
            except Exception as e:
                await status_msg.edit(content=f"⚠️ 通信エラー: {e}")
'''

if "custom_id=\"luka_mode_remake\"" not in code:
    code = code.replace(
        '        await self._process_mode(interaction, "scene_and_pose")',
        '        await self._process_mode(interaction, "scene_and_pose")\n\n' + mode_button_code
    )
    # Also add _process_remake_mode method
    code = code.replace(
        '            await status_msg.delete()\n        except Exception as e:\n            await status_msg.edit(content=f"⚠️ 解析エラー: {e}")',
        '            await status_msg.delete()\n        except Exception as e:\n            await status_msg.edit(content=f"⚠️ 解析エラー: {e}")\n\n' + remake_processor
    )

# 4. Add !remake command
remake_cmd_code = '''
@bot.command(name="remake", aliases=["img2img"])
async def remake_cmd(ctx, *args):
    """
    ComfyUI equivalent: LoadImage -> VAE Encode -> denoise 0.55~0.65.
    Locks 'grabbing hands from behind, lactation/spurting, desk and keyboard' in place,
    using tags only to refine photorealistic skin, textures and likeness.
    Usage: !remake [0.55-0.65] [prompt]
    """
    # 1. Parse denoise strength & prompt
    denoise_strength = 0.60
    prompt_parts = []
    for arg in args:
        try:
            val = float(arg)
            if 0.1 <= val <= 1.0:
                denoise_strength = val
                continue
        except ValueError:
            pass
        prompt_parts.append(arg)

    custom_prompt = " ".join(prompt_parts).strip()
    if not custom_prompt:
        custom_prompt = "1girl, hetero, 1boy, grabbing from behind, breast grab, grabbing, nipple, lactating, milk squirt, photorealistic, ultra-detailed skin, RAW photo, 8k, masterpiece, best quality"

    pos_prompt, neg_prompt = parse_direct_prompt_and_negative(custom_prompt)
    if not neg_prompt:
        neg_prompt = "child, loli, teen, young, underage, school uniform, bad hands, extra fingers, blurry, low quality"

    # 2. Get reference image from attachments or replied message
    init_data_url = None
    attachments = [a for a in ctx.message.attachments if a.content_type and a.content_type.startswith("image/")]
    if not attachments and ctx.message.reference:
        try:
            ref_msg = ctx.message.reference.resolved
            if ref_msg is None and ctx.message.reference.message_id:
                ref_msg = await ctx.channel.fetch_message(ctx.message.reference.message_id)
            if isinstance(ref_msg, discord.Message):
                attachments = [a for a in ref_msg.attachments if a.content_type and a.content_type.startswith("image/")]
                # Also check embeds
                if not attachments:
                    for embed in ref_msg.embeds:
                        target_url = embed.image.url if embed.image else (embed.thumbnail.url if embed.thumbnail else None)
                        if target_url:
                            async with aiohttp.ClientSession() as s:
                                async with s.get(target_url) as r:
                                    if r.status == 200:
                                        b = await r.read()
                                        init_data_url = process_image_to_data_url(b)
                                        break
        except Exception as e:
            print(f"Error fetching reference message: {e}", flush=True)

    if not init_data_url and attachments:
        try:
            raw_b = await attachments[0].read()
            init_data_url = process_image_to_data_url(raw_b)
        except Exception as e:
            await ctx.send(f"⚠️ 画像の読み込みに失敗しました: {e}")
            return

    if not init_data_url:
        await ctx.send("⚠️ 元画像を添付するか、画像に返信して `!remake [denoise値 (0.55-0.65)] [プロンプト]` を実行してね！\n（配置・手・母乳・机などを元画像からそのまま完全固定して再描画します）")
        return

    target_ratio = extract_ratio_from_text(custom_prompt) or "9:16"
    ratio_lbl = HQ_ASPECT_RATIO_DESCS.get(target_ratio, target_ratio)
    msg = await ctx.send(f"🔄 元画像の配置を固定し、**Denoise {denoise_strength:.2f}**（縦長 {ratio_lbl}）で実写リメイク中... (`{pos_prompt[:50]}...`)")

    async with ctx.typing():
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=600)) as session:
            try:
                global current_selected_lora
                payload = {
                    "prompt": pos_prompt,
                    "negative_prompt": neg_prompt,
                    "enhance_prompt": False,
                    "lora_name": current_selected_lora,
                    "lora_scale": 0.8,
                    "steps": 30,
                    "guidance_scale": 7.5,
                    "aspect_ratio": target_ratio,
                    "init_image": init_data_url,
                    "denoise_strength": denoise_strength
                }
                async with session.post(f"{API_BASE_URL}/api/hq/generate", json=payload) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        img_data = data.get("image_url", "")
                        if img_data.startswith("data:image/png;base64,"):
                            raw_b = base64.b64decode(img_data.split(",", 1)[1])
                            file_to_send = discord.File(io.BytesIO(raw_b), filename="remake.png")
                            w = data.get("width", 832)
                            h = data.get("height", 1216)
                            embed = discord.Embed(
                                title=f"🔄 構図完全固定リメイク完了！ ({w}×{h})",
                                description=f"元画像の配置（後ろから掴む手・噴出・デスク）をそのまま完全固定し、RealVisXLで実写化しました！\n\n**プロンプト**:\n```{pos_prompt[:800]}```",
                                color=0xFF0055
                            )
                            embed.set_footer(text=f"RealVisXL img2img {w}x{h} | Denoise: {denoise_strength:.2f} | Seed: {data.get('seed')} | Time: {data.get('elapsed_seconds', 0)}s")
                            embed.set_image(url="attachment://remake.png")

                            view = RemakeInteractiveView(
                                prompt=pos_prompt,
                                negative_prompt=neg_prompt,
                                init_image_url=init_data_url,
                                current_denoise=denoise_strength,
                                aspect_ratio=target_ratio
                            )
                            await ctx.send(embed=embed, file=file_to_send, view=view)
                            await msg.delete()
                        else:
                            await msg.edit(content="⚠️ 画像データのデコードに失敗しました。")
                    else:
                        err = await resp.text()
                        await msg.edit(content=f"⚠️ 生成エラー: {err[:200]}")
            except Exception as e:
                await msg.edit(content=f"⚠️ 通信エラー: {e}")
'''

if "def remake_cmd" not in code:
    code = code.replace('@bot.command(name="help")', remake_cmd_code + '\n@bot.command(name="help")')

# 5. Add RemakeInteractiveView to on_ready persistent views
if "bot.add_view(RemakeInteractiveView())" not in code:
    code = code.replace("bot.add_view(ImageModeSelectView())", "bot.add_view(ImageModeSelectView())\n    bot.add_view(RemakeInteractiveView())")

# 6. Update help message with remake
if "!remake" not in code:
    code = code.replace(
        'embed.add_field(name="🕺 ポーズ完全固定 ControlNet"',
        'embed.add_field(name="🔄 構図・手・体液完全固定リメイク (img2img)", value="`!remake [denoise(0.55-0.65)] [プロンプト]` : 画像を添付（または返信）して実行すると、元画像の配置（後ろから掴む手・噴出・デスク等）を100%固定したまま、RealVisXLで超高精細実写化します！", inline=False)\n    embed.add_field(name="🕺 ポーズ完全固定 ControlNet"'
    )

# 7. Update image mode selector embed description
code = code.replace(
    '🦴 **3. ポーズのみ固定**: 骨格ワイヤーフレーム（ControlNet）で姿勢を100%固定\\n"\n                            "📸 **4. シチュ＋ポーズ**: 骨格と背景・照明・空間を丸ごと完全再現"',
    '🦴 **3. ポーズのみ固定**: 骨格ワイヤーフレーム（ControlNet）で姿勢を100%固定\\n"\n                            "📸 **4. シチュ＋ポーズ**: 骨格と背景・照明・空間を丸ごと完全再現\\n"\n                            "🔄 **5. 構図固定リメイク**: 後ろから掴む手・噴出・デスクなどの配置を完全固定して実写化 (img2img)"'
)

with open(bot_path, "w", encoding="utf-8") as f:
    f.write(code)

print("Successfully updated discord_bot.py!")

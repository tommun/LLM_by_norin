import os

bot_path = r"C:\Users\owner\.gemini\antigravity\scratch\LLM_by_norin\backend\discord_bot.py"
with open(bot_path, "r", encoding="utf-8") as f:
    code = f.read()

anchor_start = '# Find the most recent prompt in this channel to enable smooth incremental editing'
anchor_end = '            # Channel history management'

idx_start = code.find(anchor_start)
idx_end = code.find(anchor_end, idx_start)

if idx_start == -1 or idx_end == -1:
    print(f"Error: anchors not found! start={idx_start}, end={idx_end}")
    exit(1)

new_region = '''# 1. First, check if the user is replying to a previous image generation result or prompt
            replied_positive_prompt = ""
            replied_negative_prompt = ""
            is_reply_to_generation = False

            if message.reference:
                try:
                    ref_msg = message.reference.resolved
                    if ref_msg is None and message.reference.message_id:
                        ref_msg = await message.channel.fetch_message(message.reference.message_id)
                    if isinstance(ref_msg, discord.Message):
                        # Inspect embeds (Generated images store positive prompt inside embed description)
                        for em in ref_msg.embeds:
                            texts_to_check = []
                            if em.description:
                                texts_to_check.append(em.description)
                            for field in em.fields:
                                texts_to_check.append(field.value)
                            for t in texts_to_check:
                                p = extract_prompt_robust(t)
                                n = extract_negative_robust(t)
                                if p:
                                    replied_positive_prompt = p
                                    replied_negative_prompt = n
                                    is_reply_to_generation = True
                                    break
                            if replied_positive_prompt:
                                break

                        # Inspect message content
                        if not replied_positive_prompt and ref_msg.content:
                            p = extract_prompt_robust(ref_msg.content)
                            n = extract_negative_robust(ref_msg.content)
                            if p:
                                replied_positive_prompt = p
                                replied_negative_prompt = n
                                is_reply_to_generation = True
                except Exception as e:
                    print(f"Error inspecting replied message prompt: {e}", flush=True)

            # 2. Find recent channel prompt if not directly replying
            last_positive_prompt = replied_positive_prompt
            last_negative_prompt = replied_negative_prompt
            
            if not last_positive_prompt:
                hist = channel_history.get(message.channel.id, [])
                for h in reversed(hist):
                    if h.get("role") == "assistant":
                        p = extract_prompt_robust(h.get("content", ""))
                        if p:
                            last_positive_prompt = p
                            last_negative_prompt = extract_negative_robust(h.get("content", ""))
                            break

            if not last_positive_prompt:
                try:
                    async for past_msg in message.channel.history(limit=8):
                        if past_msg.author == bot.user and past_msg.id != message.id:
                            for em in past_msg.embeds:
                                if em.description:
                                    p = extract_prompt_robust(em.description)
                                    if p:
                                        last_positive_prompt = p
                                        last_negative_prompt = extract_negative_robust(em.description)
                                        break
                            if last_positive_prompt:
                                break
                            p = extract_prompt_robust(past_msg.content or "")
                            if p:
                                last_positive_prompt = p
                                last_negative_prompt = extract_negative_robust(past_msg.content or "")
                                break
                except Exception as e:
                    print(f"Error fetching past channel prompt: {e}", flush=True)

            # 3. Branching logic:
            # Case A: User is replying to a generated image/prompt OR giving prompt modification requests
            has_modification_intent = bool(last_positive_prompt) and bool(clean_text) and (
                is_reply_to_generation
                or any(k in clean_text for k in [
                    "にして", "に変えて", "に変更", "消して", "削除", "なくして", "追加", "足して",
                    "髪", "服", "水着", "ポーズ", "顔", "歳", "才", "体型", "胸", "背景", "夜", "昼",
                    "全身", "アップ", "表情", "笑", "泣", "タトゥー", "ピアス", "眼鏡", "脱", "ブラ"
                ])
                or not message.attachments
            )

            if has_modification_intent:
                print(f"[Bot] Detected prompt revision/transformation request: '{clean_text}' (Base prompt: '{last_positive_prompt[:40]}...')", flush=True)
                user_content = (
                    f"【返信元のベースプロンプト】\\n"
                    f"Positive: {last_positive_prompt}\\n"
                    f"Negative: {last_negative_prompt}\\n\\n"
                    f"【ユーザーからの最新の変更・変身要望】\\n{clean_text}\\n\\n"
                    f"（※最重要指示：上記の【返信元のベースプロンプト】を100%土台として使用し、ユーザーの最新の変更要望（例：髪型、衣装・服装、年齢、表情、ポーズ、シチュエーション、体型など）に該当する部分だけを正確に差し替え・加筆・削除してください。変更指示のない他の魅力的な要素（画質タグ、顔立ち、質感、雰囲気など）は絶対に消去せず完全に維持してください）"
                )
                if any(k in clean_text for k in ["服", "ブラ", "脱", "排除", "外して", "消して", "なくして", "topless", "naked", "素肌"]):
                    user_content += "\\n（※衣服・下着の完全排除指示です。Positiveプロンプトからbraやclothingを完全排除して `topless, bare breasts, no clothes` を指定し、Negativeプロンプトに必ず `bra, clothing, shirt, top, underwear` を追加してください）"

            elif attached_images:
                # Case B: Newly uploaded reference image to analyze
                print(f"[Bot] Attached {len(attached_images)} reference image(s) for Vision LLM", flush=True)
                target_mode = detect_requested_image_mode(clean_text)

                # If user didn't specify mode and text is minimal, show 5-Mode Interactive Selector!
                if not target_mode and (not clean_text or len(clean_text) < 15):
                    embed = discord.Embed(
                        title="📸 画像を受け取ったよ！どう活用する？",
                        description=(
                            "目的に合わせて下のボタンをタップしてね！\\n\\n"
                            "🎨 **1. 画風学習**: 絵柄・タッチ・色彩・質感のみを抽出\\n"
                            "👤 **2. 人物学習**: 顔立ち・髪型・体型DNAを抽出して同一人物を再現\\n"
                            "🦴 **3. ポーズのみ固定**: 骨格ワイヤーフレーム（ControlNet）で姿勢を100%固定\\n"
                            "📸 **4. シチュ＋ポーズ**: 骨格と背景・照明・空間を丸ごと完全再現\\n"
                            "🔄 **5. 構図固定リメイク**: 後ろから掴む手・噴出・デスクなどの配置を完全固定して実写化 (img2img)"
                        ),
                        color=0x9B59B6
                    )
                    mode_view = ImageModeSelectView(image_data_url=attached_images[0], user_prompt=clean_text)
                    await message.reply(embed=embed, view=mode_view)
                    return

                # If mode detected or detailed text given, construct mode-specific prompt
                if target_mode == "art_style":
                    user_content = f"【モード1：画風学習】画像の絵柄・タッチ・色彩・質感を抽出してください。追加要望: {clean_text}"
                elif target_mode == "character_identity":
                    user_content = f"【モード2：人物学習】画像の女性の顔立ち・髪型・体型DNA特徴を抽出してください。追加要望: {clean_text}"
                elif target_mode == "pose_only":
                    user_content = f"【モード3：ポーズのみ固定】画像のポーズ・姿勢・手足の配置のみを抽出してください。追加要望: {clean_text}"
                elif target_mode == "remake":
                    user_content = f"【モード5：構図固定リメイク】元画像の配置（手・小道具・背景）をそのまま固定したまま、RealVisXLで美しく実写化するためのプロンプトを構築してください。追加要望: {clean_text}"
                else:
                    user_content = f"【モード4：シチュエーション＋ポーズ】画像のポーズおよび背景・照明・部屋のシチュエーションを丸ごと忠実に再現してください。追加要望: {clean_text}"
            else:
                user_content = clean_text
'''

updated_code = code[:idx_start] + new_region + "\n" + code[idx_end:]

with open(bot_path, "w", encoding="utf-8") as f:
    f.write(updated_code)

print("Successfully applied reply-based prompt transformation logic!")

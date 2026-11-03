import os
import re

bot_path = r"C:\Users\owner\.gemini\antigravity\scratch\LLM_by_norin\backend\discord_bot.py"
with open(bot_path, "r", encoding="utf-8") as f:
    code = f.read()

# Inspect and update the reply handling inside on_message
pattern = re.compile(
    r'(# 2\. Extract images from replied message \(message\.reference\)\s+if message\.reference:\s+try:.*?'
    r'if not clean_text and not attached_images:\s+await message\.reply\(".*?"\)\s+return\s+)'
    r'(# Find the most recent prompt in this channel.*?)(if attached_images:)',
    re.DOTALL
)

replacement_logic = '''
            # Check if user is replying to a previous image generation result or prompt
            replied_positive_prompt = ""
            replied_negative_prompt = ""
            is_reply_to_generation = False

            if message.reference:
                try:
                    ref_msg = message.reference.resolved
                    if ref_msg is None and message.reference.message_id:
                        ref_msg = await message.channel.fetch_message(message.reference.message_id)
                    if isinstance(ref_msg, discord.Message):
                        # 1. Inspect embeds (Generated image embeds store prompt in description or fields)
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

                        # 2. Inspect message text content
                        if not replied_positive_prompt and ref_msg.content:
                            p = extract_prompt_robust(ref_msg.content)
                            n = extract_negative_robust(ref_msg.content)
                            if p:
                                replied_positive_prompt = p
                                replied_negative_prompt = n
                                is_reply_to_generation = True
                except Exception as e:
                    print(f"Error checking replied message prompt: {e}", flush=True)

            # Find the most recent prompt in this channel if not directly replying
            last_positive_prompt = replied_positive_prompt
            last_negative_prompt = replied_negative_prompt
            
            if not last_positive_prompt:
                # Check history first
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
                            # Check embeds
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

            # Branch: If user is replying to an image/prompt with specific revision requests!
            if (is_reply_to_generation or last_positive_prompt) and clean_text and not (message.attachments and len(message.attachments) > 0 and len(clean_text) < 5):
                print(f"[Bot] Applying incremental prompt revision based on user request: '{clean_text}'", flush=True)
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
'''

# Let's inspect the exact lines in discord_bot.py around line 1665
print("Searching target region...")
target_anchor = '# Find the most recent prompt in this channel to enable smooth incremental editing'
idx = code.find(target_anchor)
print("Anchor index:", idx)
if idx != -1:
    # Find start of `if attached_images:`
    idx_att = code.find('            if attached_images:', idx)
    print("Attached images index:", idx_att)
    # Also find where `else:` ends
    idx_else_end = code.find('            # Channel history management', idx_att)
    print("Channel history index:", idx_else_end)


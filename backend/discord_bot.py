import sys
import os
import io
import re
import json
import base64
import aiohttp
import asyncio
from typing import Optional, List, Dict, Any
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

# Active style LoRA selection
current_selected_lora: Optional[str] = None

# Channel default aspect ratios
channel_default_ratio: Dict[int, str] = {}

# Channel last uploaded or generated image data URL cache (robust fallback)
channel_last_image: Dict[int, str] = {}

async def safe_defer(interaction: discord.Interaction):
    try:
        if not interaction.response.is_done():
            await interaction.response.defer(thinking=True)
            return True
    except Exception:
        pass
    return False

async def safe_send(interaction: discord.Interaction, content: str = "", embed: Optional[discord.Embed] = None, file: Optional[discord.File] = None, view: Optional[discord.ui.View] = None):
    try:
        if interaction.response.is_done():
            return await interaction.followup.send(content=content, embed=embed, file=file, view=view)
        else:
            return await interaction.response.send_message(content=content, embed=embed, file=file, view=view)
    except Exception:
        if interaction.channel:
            return await interaction.channel.send(content=content, embed=embed, file=file, view=view)
    return None

async def resolve_interaction_image(interaction: discord.Interaction, fallback_url: str = "") -> str:
    """Robustly resolve the reference image from button view, message reply reference, cache, or channel history"""
    if fallback_url and fallback_url.startswith("data:image"):
        if interaction.channel:
            channel_last_image[interaction.channel.id] = fallback_url
        return fallback_url

    # A. Check message attachments on interaction.message itself
    if interaction.message:
        for att in interaction.message.attachments:
            if att.content_type and att.content_type.startswith("image/"):
                try:
                    b = await att.read()
                    u = process_image_to_data_url(b)
                    if u:
                        if interaction.channel:
                            channel_last_image[interaction.channel.id] = u
                        return u
                except Exception:
                    pass

        # B. Check parent message if this was a reply
        if interaction.message.reference and interaction.message.reference.message_id:
            try:
                parent_msg = interaction.message.reference.resolved
                if not parent_msg and interaction.channel:
                    parent_msg = await interaction.channel.fetch_message(interaction.message.reference.message_id)
                if parent_msg:
                    for att in parent_msg.attachments:
                        if att.content_type and att.content_type.startswith("image/"):
                            b = await att.read()
                            u = process_image_to_data_url(b)
                            if u:
                                if interaction.channel:
                                    channel_last_image[interaction.channel.id] = u
                                return u
            except Exception:
                pass

        # C. Check message embeds (e.g. from previously generated image)
        for emb in interaction.message.embeds:
            img_url = emb.image.url if emb.image else (emb.thumbnail.url if emb.thumbnail else None)
            if img_url and not img_url.startswith("attachment://"):
                try:
                    async with aiohttp.ClientSession() as sess:
                        async with sess.get(img_url) as r:
                            if r.status == 200:
                                b = await r.read()
                                u = process_image_to_data_url(b)
                                if u:
                                    if interaction.channel:
                                        channel_last_image[interaction.channel.id] = u
                                    return u
                except Exception:
                    pass

    # D. Check channel cache
    if interaction.channel and interaction.channel.id in channel_last_image:
        cached = channel_last_image[interaction.channel.id]
        if cached:
            return cached

    # E. Search recent channel history for the latest image
    if interaction.channel and hasattr(interaction.channel, "history"):
        try:
            async for old_msg in interaction.channel.history(limit=12):
                for att in old_msg.attachments:
                    if att.content_type and att.content_type.startswith("image/"):
                        b = await att.read()
                        u = process_image_to_data_url(b)
                        if u:
                            channel_last_image[interaction.channel.id] = u
                            return u
        except Exception:
            pass

    return fallback_url


HQ_ASPECT_RATIO_DESCS = {
    "1:1": "正方形 (1024×1024)",
    "9:16": "スマホ縦長・全身 (832×1216)",
    "3:4": "ポスター縦長 (896×1152)",
    "16:9": "シネマ横長 (1216×832)",
    "4:3": "写真横長 (1152×896)"
}

def extract_ratio_from_text(text: str) -> Optional[str]:
    """Detect requested aspect ratio from user text or prompt"""
    if not text:
        return None
    t = text.lower()
    if "9:16" in t or "9/16" in t or "--ar 9:16" in t:
        return "9:16"
    if "16:9" in t or "16/9" in t or "--ar 16:9" in t:
        return "16:9"
    if "3:4" in t or "3/4" in t or "--ar 3:4" in t:
        return "3:4"
    if "4:3" in t or "4/3" in t or "--ar 4:3" in t:
        return "4:3"
    if "1:1" in t or "1/1" in t or "--ar 1:1" in t:
        return "1:1"
    
    if any(k in t for k in ["スマホ", "壁紙", "縦長", "全身", "vertical", "portrait", "立ち絵", "足先まで"]):
        return "9:16"
    if any(k in t for k in ["ポスター", "半身"]):
        return "3:4"
    if any(k in t for k in ["横長", "シネマ", "ワイド", "landscape", "horizontal", "cinema", "wide"]):
        return "16:9"
    if any(k in t for k in ["正方形", "スクエア", "square"]):
        return "1:1"
    return None

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
# Interactive Button to Generate Image directly from Luka's prompt
def extract_prompt_robust(text: str) -> str:
    """Robustly extract positive prompt even if LLM omitted markdown backticks or malformed blocks"""
    # 1. Standard ```prompt ... ``` or ```positive ... ``` block
    m = re.search(r"```(?:prompt|positive)?\s*([\s\S]*?)```", text, re.IGNORECASE)
    if m:
        candidate = m.group(1).strip()
        candidate = re.sub(r"^(?:positive|prompt)\s*:\s*", "", candidate, flags=re.IGNORECASE).strip()
        if candidate and not candidate.lower().startswith("negative") and len(candidate) > 20 and "," in candidate:
            return candidate

    # 2. Look for explicit Positive tag markers like "Positiveタグ: ..." or "(2) Positiveタグ...:"
    pos_match = re.search(r"(?:positive\S*|positive)\s*[:：]\s*([\s\S]*?)(?=(?:\(3\)|negative|除外|ブラッシュアップ|$))", text, re.IGNORECASE)
    if pos_match:
        candidate = pos_match.group(1).strip()
        candidate = re.sub(r"```(?:prompt|positive)?", "", candidate, flags=re.IGNORECASE).replace("```", "").replace("`", "").strip()
        candidate = re.sub(r"^(?:positive|prompt)\s*:\s*", "", candidate, flags=re.IGNORECASE).strip()
        candidate = re.sub(r"^.*?コードブロック.*?[：:]\s*", "", candidate).strip()
        if len(candidate) > 20 and "," in candidate:
            return candidate

    # 3. Scan line-by-line for characteristic Danbooru tags like 1girl, adult woman, solo
    lines = text.splitlines()
    for i, line in enumerate(lines):
        line_s = line.strip()
        clean_l = re.sub(r"^(?:prompt|positive)\s*:\s*", "", line_s, flags=re.IGNORECASE).strip()
        clean_l = clean_l.replace("`", "").strip()
        if clean_l.startswith(("1girl", "solo", "adult woman")) or "1girl," in clean_l or "adult woman," in clean_l:
            res_lines = []
            for j in range(i, len(lines)):
                l = lines[j].strip().replace("`", "")
                if not l:
                    continue
                if l.startswith(("(", "（", "Negative", "negative", "除外", "【", "3.", "(3)")):
                    break
                l = re.sub(r"^(?:positive|prompt)\s*:\s*", "", l, flags=re.IGNORECASE).strip()
                res_lines.append(l)
            if res_lines:
                cand = " ".join(res_lines).strip()
                if len(cand) > 20 and "," in cand:
                    return cand

    return ""

def extract_negative_robust(text: str) -> str:
    """Robustly extract negative prompt even if LLM omitted markdown backticks"""
    m = re.search(r"```negative\s*([\s\S]*?)```", text, re.IGNORECASE)
    if m:
        candidate = m.group(1).strip()
        candidate = re.sub(r"^negative\s*:\s*", "", candidate, flags=re.IGNORECASE).strip()
        if candidate and len(candidate) > 15:
            return candidate

    neg_match = re.search(r"(?:negative\S*|除外\S*)\s*[:：]\s*([\s\S]*?)(?=(?:\(4\)|ブラッシュアップ|$))", text, re.IGNORECASE)
    if neg_match:
        candidate = neg_match.group(1).strip()
        candidate = re.sub(r"```(?:negative)?", "", candidate, flags=re.IGNORECASE).replace("```", "").replace("`", "").strip()
        candidate = re.sub(r"^negative\s*:\s*", "", candidate, flags=re.IGNORECASE).strip()
        candidate = re.sub(r"^.*?コードブロック.*?[：:]\s*", "", candidate).strip()
        if len(candidate) > 15:
            return candidate

    lines = text.splitlines()
    for i, line in enumerate(lines):
        line_s = line.strip().lower()
        if any(k in line_s for k in ["bra,", "sports bra", "child, loli", "clothes, clothing", "bad hands"]):
            res_lines = []
            for j in range(i, len(lines)):
                l = lines[j].strip().replace("`", "")
                if not l or l.startswith(("(", "（", "【", "4.", "(4)", "ブラッシュアップ")):
                    break
                l = re.sub(r"^negative\s*:\s*", "", l, flags=re.IGNORECASE).strip()
                res_lines.append(l)
            if res_lines:
                return " ".join(res_lines).strip()

    return ""

def format_luka_natural_response(reply_text: str, has_reference_image: bool = False) -> str:
    """Format Luka's response into a lively, natural creator dialogue, stripping away robotic prompt template headers."""
    extracted_pos = extract_prompt_robust(reply_text)
    extracted_neg = extract_negative_robust(reply_text)
    
    # Check if text contains robotic meta templates
    has_meta = bool(re.search(r"\(\d\)|コードブロック|威勢のいいコメント|Positiveタグ|Negativeタグ", reply_text))

    if not has_meta or not extracted_pos:
        return reply_text

    # Extract conversational intro comment from the beginning
    lines = reply_text.splitlines()
    intro_lines = []
    for line in lines:
        l = line.strip()
        if not l:
            continue
        # Stop at prompt markers or code blocks
        if any(k in l for k in ["Positive", "positive", "```", "1girl", "prompt", "Negative", "negative", "(2)", "(3)"]):
            break
        # Filter out meta instruction lines like "(1) 相棒としての威勢のいいコメント..."
        if re.search(r"^\(\d\)|威勢のいいコメント|指示|出力フォーマット|必ず", l):
            continue
        intro_lines.append(l)

    intro_comment = " ".join(intro_lines).strip()
    # Strip any leftover canned text if LLM regurgitated it
    if "手を頭の後ろで組んだ" in intro_comment and not has_reference_image:
        intro_comment = "任せて！きみの指示通りにタグを微調整して、理想の1枚に仕上げたよ✨"

    if not intro_comment or len(intro_comment) < 6:
        intro_comment = "任せて！きみのこだわりをしっかり反映してタグを調整したよ✨"

    # Reconstruct into clean, natural and gorgeous response
    formatted = f"{intro_comment}\n\n**🎨 プロンプト (Positive)**\n```prompt\n{extracted_pos}\n```"
    if extracted_neg:
        formatted += f"\n\n**🛡️ 除外タグ (Negative)**\n```negative\n{extracted_neg}\n```"

    return formatted


def detect_requested_image_mode(text: str) -> Optional[str]:
    """Detect if user explicitly asked for one of the 4 modes"""
    t = text.lower()
    if any(k in t for k in ["画風", "絵柄", "タッチ", "スタイル", "art style", "style of", "塗り方"]):
        return "art_style"
    if any(k in t for k in ["人物", "この人", "この子", "顔", "似た人物", "キャラ", "同一人物", "容姿", "女性の顔", "顔立ち", "character", "face"]):
        return "character_identity"
    if any(k in t for k in ["ポーズのみ", "ポーズだけ", "姿勢だけ", "骨格だけ", "pose only", "ポーズ固定"]):
        return "pose_only"
    if any(k in t for k in ["シチュエーション", "背景とポーズ", "場所とポーズ", "雰囲気も", "部屋ごと", "構図も背景も", "scene"]):
        return "scene_and_pose"
    # Default to pose if user says "このポーズ"
    if any(k in t for k in ["リメイク", "img2img", "remake", "構図固定", "配置固定", "手固定", "母乳"]):
        return "remake"
    if "ポーズ" in t:
        return "pose_only"
    return None

async def analyze_image_for_mode(image_data_url: str, mode: str, user_instruction: str = "", base_prompt: str = "") -> dict:
    """Analyze image using Vision LLM based on one of the 4 dedicated modes"""
    mode_instructions = {
        "outfit": (
            "【モード：衣装・ドレス・服装の抽出と着用】\n"
            "添付された画像に写っているドレスや衣装（デザイン、色、生地の質感、装飾、胸元の開き具合、シルエット、アクセサリーなど）を最高解像度で精緻に解析・抽出し、それを完璧に反映したRealVisXL用最高峰の英語プロンプトを構築してください。\n"
            "※特定のポーズや背景は固定せず、魅力的な人物がこのドレス・衣装を美しく着用した姿を生成できるプロンプトにしてください。\n"
            "Positiveは ```prompt コードブロック、Negativeは ```negative コードブロックで出力してください。"
        ),
        "art_style": (
            "【モード1：画風・アートスタイル抽出】\n"
            "添付された画像のアートスタイル・画風・色彩設計・光の質感・レンダリング手法（写実的写真/油彩画/35mm写真、色調、コントラスト、照明技法）を精密に分析してください。\n"
            "※特定のポーズや女性の顔立ちは含めず、他の人物やシーンにも適用できる純粋な【スタイル・質感・ライティング英語Danbooru/SDXLタグ】を構築してください。\n"
            "Positiveは ```prompt コードブロック、Negativeは ```negative コードブロックで出力してください。"
        ),
        "character_identity": (
            "【モード2：人物学習・同一人物再現】\n"
            "添付された画像の【女性キャラクターの容姿・身体的特徴】（年齢、推定人種、目鼻立ち、輪郭、髪型、髪色、肌のトーン、体型、胸のサイズ、タトゥー、ピアス、ホクロ等の固有特徴）を精密に分析してください。\n"
            "※特定のポーズや背景は固定せず、別のポーズやシチュエーションでも【この人物本人として一貫して生成できる人物DNA英語タグ】を構築してください。\n"
            "Positiveは ```prompt コードブロック、Negativeは ```negative コードブロックで出力してください。"
        ),
        "pose_only": (
            "【モード3：ポーズのみ固定（骨格抽出）】\n"
            "添付された画像の【ポーズ・姿勢・手足の位置・関節の角度・カメラアングル】だけを精密に分析してください。\n"
            "※顔立ちや背景は固定せず、どのような人物やシチュエーションにもこのポーズをとらせられるように、ポーズ関連の英語タグ（squatting, arms behind head, spread legs等）を中心としたプロンプトを構築してください。\n"
            "Positiveは ```prompt コードブロック、Negativeは ```negative コードブロックで出力してください。"
        ),
        "scene_and_pose": (
            "【モード4：シチュエーション＋ポーズ完全再現】\n"
            "添付された画像の【ポーズ・姿勢】に加えて、【背景・場所（ベッド、窓、部屋）、照明（影、逆光、夜）、小道具、濡れ感、空気感・雰囲気】をすべて丸ごと精密に分析してください。\n"
            "この画像のシチュエーションと姿勢を余すところなく忠実に完全再現する英語プロンプトを構築してください。\n"
            "Positiveは ```prompt コードブロック、Negativeは ```negative コードブロックで出力してください。"
        )
    }

    instruction = mode_instructions.get(mode, mode_instructions["scene_and_pose"])
    if user_instruction:
        instruction += f"\n\n【ユーザーからの追加指示】: {user_instruction}"
    if base_prompt:
        instruction += f"\n\n【ベースとなる既存プロンプト】: {base_prompt}\n（このベースプロンプトを活かしつつ、上記のモード分析を反映してください）"

    messages = [
        {"role": "system", "content": get_bot_system_prompt("creative_buddy_luka")},
        {"role": "user", "content": instruction, "images": [image_data_url]}
    ]

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=300)) as session:
        async with session.post(f"{API_BASE_URL}/api/chat", json={
            "messages": messages,
            "temperature": 0.7,
            "max_new_tokens": 800,
            "top_p": 0.9
        }) as resp:
            if resp.status == 200:
                data = await resp.json()
                reply = data.get("response", "")
                pos = extract_prompt_robust(reply)
                neg = extract_negative_robust(reply)
                return {"reply": reply, "positive": pos, "negative": neg}
            else:
                err = await resp.text()
                raise RuntimeError(f"Vision LLM error ({resp.status}): {err[:150]}")

class ImageModeSelectView(discord.ui.View):
    """Interactive Mode Selector when an image is uploaded"""
    def __init__(self, image_data_url: str = "", user_prompt: str = ""):
        super().__init__(timeout=None)
        self.image_data_url = image_data_url
        self.user_prompt = user_prompt

    @discord.ui.button(label="👗 衣装・ドレス参考", style=discord.ButtonStyle.primary, emoji="👗", row=0, custom_id="luka_mode_outfit")
    async def mode_outfit(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._process_mode(interaction, "outfit")

    @discord.ui.button(label="🎨 1. 画風学習", style=discord.ButtonStyle.secondary, emoji="🎨", row=0, custom_id="luka_mode_art")
    async def mode_art(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._process_mode(interaction, "art_style")

    @discord.ui.button(label="👤 2. 人物学習・再現", style=discord.ButtonStyle.success, emoji="👤", row=1, custom_id="luka_mode_char")
    async def mode_char(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._process_mode(interaction, "character_identity")

    @discord.ui.button(label="🦴 3. ポーズのみ固定", style=discord.ButtonStyle.secondary, emoji="🦴", row=1, custom_id="luka_mode_pose")
    async def mode_pose(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._process_mode(interaction, "pose_only")

    @discord.ui.button(label="📸 4. シチュ＋ポーズ", style=discord.ButtonStyle.secondary, emoji="📸", row=2, custom_id="luka_mode_scene")
    async def mode_scene(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._process_mode(interaction, "scene_and_pose")

    @discord.ui.button(label="🔄 5. 構図固定リメイク (img2img / denoise 0.6)", style=discord.ButtonStyle.danger, emoji="🔄", row=2, custom_id="luka_mode_remake")
    async def mode_remake(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._process_remake_mode(interaction)


    async def _process_mode(self, interaction: discord.Interaction, mode: str):
        await safe_defer(interaction)
        img_url = await resolve_interaction_image(interaction, self.image_data_url)

        if not img_url:
            await safe_send(interaction, "⚠️ 画像データが見つかりませんでした。もう一度画像を添付してね！")
            return

        mode_titles = {
            "outfit": "👗 衣装・ドレスデザインを抽出中...",
            "art_style": "🎨 画風・アートスタイルを抽出中...",
            "character_identity": "👤 人物の顔立ち・体型DNAを抽出中...",
            "pose_only": "🦴 骨格ワイヤーフレーム（ポーズ）を抽出中...",
            "scene_and_pose": "📸 シチュエーション＋ポーズを丸ごと抽出中..."
        }
        status_msg = await interaction.followup.send(f"🔍 **{mode_titles.get(mode, '解析中...')}** 少々お待ちください！")

        try:
            res = await analyze_image_for_mode(img_url, mode=mode, user_instruction=self.user_prompt)
            pos = res["positive"]
            neg = res["negative"]

            if not pos:
                await status_msg.edit(content="⚠️ プロンプトの抽出に失敗しました。もう一度試してみてね！")
                return

            use_pose_cnet = img_url if mode in ("pose_only", "scene_and_pose") else None

            mode_intros = {
                "outfit": "👗 **画像のドレス・衣装デザインを抽出したよ！**\nこのドレスの美しい装飾やシルエットを完璧に再現できるようにプロンプトを組んだよ✨",
                "art_style": "🎨 **画像の画風・タッチ・色彩を抽出したよ！**\nこの絵柄やライティングの質感を適用できるようにタグを組んだよ✨",
                "character_identity": "👤 **この女性の顔立ち・髪型・体型DNAを忠実に抽出したよ！**\nこの人物の同一性をキープしたまま、別のシーンやポーズでも生成できるように組んだよ✨",
                "pose_only": "🦴 **ポーズの骨格（ControlNet）を抽出したよ！**\n顔や背景は自由にして、このポーズだけを100%忠実に固定して生成するよ！",
                "scene_and_pose": "📸 **ポーズの骨格と、背景・照明・部屋のシチュエーションを丸ごと再現したよ！**\nこの空間と姿勢を完璧にそのまま出力できるように組んだよ✨"
            }

            clean_reply = f"{mode_intros.get(mode, '')}\n\n**🎨 プロンプト (Positive)**\n```prompt\n{pos}\n```\n\n**🛡️ 除外タグ (Negative)**\n```negative\n{neg}\n```"
            view = PersistentGenerateButtonView(pos, neg, pose_image=use_pose_cnet)
            
            await interaction.followup.send(clean_reply, view=view)
            await status_msg.delete()
        except Exception as e:
            await status_msg.edit(content=f"⚠️ 解析エラー: {e}")

    async def _process_remake_mode(self, interaction: discord.Interaction):
        await safe_defer(interaction)
        img_url = await resolve_interaction_image(interaction, self.image_data_url)

        if not img_url:
            await safe_send(interaction, "⚠️ 画像データが見つかりませんでした。もう一度画像を添付してね！")
            return

        status_msg = await safe_send(interaction, "🔄 **構図・手・噴出・デスクを完全固定し、Denoise 0.60 でRealVisXL実写化中...**")
        
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
                                description=f"""元画像の配置（後ろから掴む手・噴出・デスク）をそのまま完全固定し、RealVisXLで実写化しました！

**プロンプト**:
```{p[:800]}```""",
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
                                description=f"""**プロンプト**:
```{pos[:800]}```""",
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
                                description=f"""元画像の配置（後ろから掴む手・噴出・デスク）をそのまま完全固定し、RealVisXLで実写化しました！

**プロンプト**:
```{p[:800]}```""",
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
    @discord.ui.button(label="✏️ プロンプト編集", style=discord.ButtonStyle.secondary, emoji="✏️", custom_id="luka_remake_edit_prompt", row=0)
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

class PersistentGenerateButtonView(discord.ui.View):
    def __init__(self, prompt: str = "", negative_prompt: str = "", pose_image: Optional[str] = None, default_ratio: str = "1:1"):
        super().__init__(timeout=None)
        self.prompt = prompt
        self.negative_prompt = negative_prompt
        self.pose_image = pose_image
        self.default_ratio = default_ratio

        # Highlight primary button based on requested default ratio safely
        try:
            if hasattr(self, "btn_9_16") and hasattr(self.btn_9_16, "style"):
                if self.default_ratio == "9:16":
                    self.btn_9_16.style = discord.ButtonStyle.success if self.pose_image else discord.ButtonStyle.primary
                elif self.default_ratio == "3:4":
                    self.btn_3_4.style = discord.ButtonStyle.success if self.pose_image else discord.ButtonStyle.primary
                elif self.default_ratio == "16:9":
                    self.btn_16_9.style = discord.ButtonStyle.success if self.pose_image else discord.ButtonStyle.primary
                else:
                    self.btn_1_1.style = discord.ButtonStyle.success if self.pose_image else discord.ButtonStyle.primary

            if self.pose_image:
                if hasattr(self, "btn_9_16") and hasattr(self.btn_9_16, "label"):
                    self.btn_9_16.label = "🦴 縦長 (9:16)"
                    self.btn_3_4.label = "🦴 縦長 (3:4)"
                    self.btn_1_1.label = "🦴 正方形 (1:1)"
                    self.btn_16_9.label = "🦴 横長 (16:9)"
        except Exception as e:
            print(f"Warning updating PersistentGenerateButtonView button styles: {e}", flush=True)

    async def _execute_generate(self, interaction: discord.Interaction, ratio: str):
        # 1. Defer immediately to satisfy Discord's 3-second limit
        await interaction.response.defer(thinking=True)

        # 2. Dynamically restore prompt from message if missing (after bot reboot)
        effective_prompt = self.prompt
        effective_neg = self.negative_prompt
        effective_pose = self.pose_image

        if not effective_prompt and interaction.message:
            msg_content = interaction.message.content or ""
            effective_prompt = extract_prompt_robust(msg_content)
            effective_neg = extract_negative_robust(msg_content)

        if not effective_prompt:
            await interaction.followup.send("⚠️ プロンプトが見つかりませんでした。新しく `@ルカ` に話しかけてみてね！", ephemeral=True)
            return

        ratio_label = HQ_ASPECT_RATIO_DESCS.get(ratio, ratio)
        status_msg = await interaction.followup.send(
            f"🦴 参考画像から骨格を抽出し、**{ratio_label}** でポーズ固定生成中..." if effective_pose
            else f"🎨 RealVisXL **{ratio_label}** で画像を生成しています... お待ちください！",
            ephemeral=False
        )
        
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=600)) as session:
            try:
                global current_selected_lora
                payload = {
                    "prompt": effective_prompt,
                    "negative_prompt": effective_neg or "child, loli, teen, young, underage, school uniform, bad hands, extra fingers, blurry, low quality",
                    "enhance_prompt": False,
                    "lora_name": current_selected_lora,
                    "lora_scale": 0.8,
                    "steps": 30,
                    "guidance_scale": 7.5,
                    "aspect_ratio": ratio,
                    "pose_image": effective_pose,
                    "controlnet_scale": 0.85
                }
                async with session.post(f"{API_BASE_URL}/api/hq/generate", json=payload) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        img_data = data.get("image_url", "")
                        skel_data = data.get("pose_skeleton_url")
                        
                        if img_data.startswith("data:image/png;base64,"):
                            raw_bytes = base64.b64decode(img_data.split(",", 1)[1])
                            files_to_send = [discord.File(io.BytesIO(raw_bytes), filename="generated.png")]
                            
                            is_cnet = data.get("controlnet_active", False)
                            w = data.get("width", 1024)
                            h = data.get("height", 1024)
                            embed = discord.Embed(
                                title=f"🕺 ポーズ完全固定 ControlNet 生成完了！ ({w}×{h})" if is_cnet else f"✨ 画像生成が完了したよ！ ({w}×{h})",
                                description=f"**プロンプト**:\n```{effective_prompt[:900]}```",
                                color=0x00FF88 if is_cnet else 0x5865F2
                            )
                            mode_lbl = "OpenPose XL ControlNet" if is_cnet else "RealVisXL Standard"
                            embed.set_footer(text=f"{mode_lbl} {w}x{h} ({ratio}) | Steps: {data.get('steps', 30)} | Seed: {data.get('seed')} | Time: {data.get('elapsed_seconds', 0)}s")
                            embed.set_image(url="attachment://generated.png")

                            if skel_data and skel_data.startswith("data:image/png;base64,"):
                                skel_bytes = base64.b64decode(skel_data.split(",", 1)[1])
                                files_to_send.append(discord.File(io.BytesIO(skel_bytes), filename="skeleton.png"))
                                embed.set_thumbnail(url="attachment://skeleton.png")
                                embed.add_field(name="🦴 抽出された骨格ワイヤーフレーム", value="右上のサムネイルに骨格抽出結果を表示しています！", inline=False)
                            
                            await interaction.followup.send(embed=embed, files=files_to_send)
                            await status_msg.delete()
                        else:
                            await status_msg.edit(content="⚠️ 画像データのデコードに失敗しました。")
                    else:
                        err = await resp.text()
                        await status_msg.edit(content=f"⚠️ 生成エラー: {err[:200]}")
            except Exception as e:
                await status_msg.edit(content=f"⚠️ 通信エラー: {e}")

    # Backward compatibility for old single button
    @discord.ui.button(label="🎨 このプロンプトで画像生成", style=discord.ButtonStyle.primary, emoji="✨", custom_id="luka_gen_btn_v1")
    async def legacy_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._execute_generate(interaction, self.default_ratio or "1:1")

    # Ratio Buttons
    @discord.ui.button(label="📱 縦長 (9:16)", style=discord.ButtonStyle.secondary, emoji="📱", custom_id="luka_btn_9_16")
    async def btn_9_16(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._execute_generate(interaction, "9:16")

    @discord.ui.button(label="🖼️ 縦長 (3:4)", style=discord.ButtonStyle.secondary, emoji="🖼️", custom_id="luka_btn_3_4")
    async def btn_3_4(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._execute_generate(interaction, "3:4")

    @discord.ui.button(label="⏹️ 正方形 (1:1)", style=discord.ButtonStyle.secondary, emoji="⏹️", custom_id="luka_btn_1_1")
    async def btn_1_1(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._execute_generate(interaction, "1:1")

    @discord.ui.button(label="🎬 横長 (16:9)", style=discord.ButtonStyle.secondary, emoji="🎬", custom_id="luka_btn_16_9")
    async def btn_16_9(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._execute_generate(interaction, "16:9")

    @discord.ui.button(label="🎬 5秒動画化 (Wan 2.2)", style=discord.ButtonStyle.success, emoji="🎬", custom_id="luka_btn_generate_video")
    async def btn_generate_video(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(thinking=True)
        # Resolve keyframe image from message
        keyframe_data = await resolve_interaction_image(interaction, self.pose_image or "")
        p = self.prompt
        if not p and interaction.message:
            p = extract_prompt_robust(interaction.message.content or "")
        
        status_msg = await interaction.followup.send("🎬 **Wan 2.2 TI2V 動画生成ジョブを開始中...**\nキーフレーム画像からカメラワークと動きを構想しています！")
        await execute_and_track_video_job(
            interaction,
            user_instruction=f"このキャラクターが魅力的に動くシネマティックアニメーションシーン: {p[:100]}",
            reference_image=keyframe_data,
            status_message=status_msg
        )

    @discord.ui.button(label="✏️ プロンプト微調整", style=discord.ButtonStyle.secondary, emoji="✏️", custom_id="luka_gen_edit_prompt")
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

class VideoMotionModal(discord.ui.Modal, title="🎬 モーションプロンプト編集"):
    def __init__(self, keyframe_url: str = "", current_motion: str = ""):
        super().__init__()
        self.keyframe_url = keyframe_url
        self.motion_input = discord.ui.TextInput(
            label="カメラワーク＆動作 (英語自然文)",
            style=discord.TextStyle.paragraph,
            placeholder="e.g. The camera smoothly orbits around the character as wind blows gently.",
            default=current_motion or "The camera smoothly circles around the character with dynamic rim lighting.",
            required=True,
            max_length=500
        )
        self.add_item(self.motion_input)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)
        new_motion = self.motion_input.value.strip()
        status_msg = await interaction.followup.send(f"🎬 **新しいモーション指示で再生成中...**\n`{new_motion[:100]}`")

        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=600)) as session:
            try:
                payload = {
                    "keyframe_image": self.keyframe_url,
                    "motion_prompt": new_motion,
                    "num_frames": 81,
                    "fps": 16,
                    "steps": 30,
                    "width": 832,
                    "height": 480
                }
                async with session.post(f"{API_BASE_URL}/api/video/generate-direct", json=payload) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        fn = data.get("filename")
                        fp = os.path.join(OUTPUTS_DIR, fn)
                        if os.path.exists(fp):
                            view = VideoControlView(video_filename=fn, keyframe_url=self.keyframe_url, motion_prompt=new_motion)
                            await interaction.followup.send(
                                content=f"✨ **Wan 2.2 動画再生成完了！** ({data.get('duration_seconds')}秒 / {data.get('elapsed_seconds')}s)\n**Motion**: `{new_motion}`",
                                file=discord.File(fp, filename=fn),
                                view=view
                            )
                            await status_msg.delete()
                            return
                    err = await resp.text()
                    await status_msg.edit(content=f"⚠️ 動画再生成エラー: {err[:150]}")
            except Exception as e:
                await status_msg.edit(content=f"⚠️ 通信エラー: {e}")

class VideoControlView(discord.ui.View):
    """Persistent controls for generated video clips"""
    def __init__(self, video_filename: str = "", keyframe_url: str = "", motion_prompt: str = ""):
        super().__init__(timeout=None)
        self.video_filename = video_filename
        self.keyframe_url = keyframe_url
        self.motion_prompt = motion_prompt

    @discord.ui.button(label="🎬 モーション編集して再生成", style=discord.ButtonStyle.primary, emoji="🎬", custom_id="luka_video_btn_edit_motion")
    async def btn_edit_motion(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = VideoMotionModal(keyframe_url=self.keyframe_url, current_motion=self.motion_prompt)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="🔄 別シードで再生成", style=discord.ButtonStyle.secondary, emoji="🔄", custom_id="luka_video_btn_reseed")
    async def btn_reseed(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(thinking=True)
        status_msg = await interaction.followup.send("🔄 **新しいランダムシードで Wan 2.2 動画を再生成中...** (約1〜2分)")
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=600)) as session:
            try:
                payload = {
                    "keyframe_image": self.keyframe_url,
                    "motion_prompt": self.motion_prompt or "The camera smoothly orbits around the character as wind blows gently.",
                    "num_frames": 81,
                    "fps": 16,
                    "steps": 30,
                    "width": 832,
                    "height": 480
                }
                async with session.post(f"{API_BASE_URL}/api/video/generate-direct", json=payload) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        fn = data.get("filename")
                        fp = os.path.join(OUTPUTS_DIR, fn)
                        if os.path.exists(fp):
                            view = VideoControlView(video_filename=fn, keyframe_url=self.keyframe_url, motion_prompt=self.motion_prompt)
                            await interaction.followup.send(
                                content=f"✨ **シード再生成完了！** (Seed: {data.get('seed')})",
                                file=discord.File(fp, filename=fn),
                                view=view
                            )
                            await status_msg.delete()
                            return
                    err = await resp.text()
                    await status_msg.edit(content=f"⚠️ シード再生成エラー: {err[:150]}")
            except Exception as e:
                await status_msg.edit(content=f"⚠️ 通信エラー: {e}")

    @discord.ui.button(label="🎞️ クリップを結合して1話にする", style=discord.ButtonStyle.success, emoji="🎞️", custom_id="luka_video_btn_concat")
    async def btn_concat_episode(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(thinking=True)
        if not os.path.exists(OUTPUTS_DIR):
            await interaction.followup.send("⚠️ 出力ディレクトリが見つかりません。")
            return
        v_files = [f for f in os.listdir(OUTPUTS_DIR) if f.lower().endswith(".mp4") and not f.endswith("_Full.mp4")]
        v_files.sort(key=lambda f: os.path.getmtime(os.path.join(OUTPUTS_DIR, f)))
        if len(v_files) < 2:
            await interaction.followup.send("⚠️ 結合するには少なくとも2本以上の動画クリップが必要です。次のシーンも作ってみてね！")
            return

        status_msg = await interaction.followup.send(f"🎞️ **直近 {min(len(v_files), 5)} 本のクリップをロスレス結合中...** (SlaveArena_Ep01_Full.mp4)")
        async with aiohttp.ClientSession() as session:
            try:
                payload = {
                    "clip_filenames": v_files[-5:],
                    "output_filename": f"SlaveArena_Ep01_Full_{int(time.time())}.mp4"
                }
                async with session.post(f"{API_BASE_URL}/api/video/concat", json=payload) as resp:
                    if resp.status == 200:
                        cdata = await resp.json()
                        out_fn = cdata["filename"]
                        out_fp = os.path.join(OUTPUTS_DIR, out_fn)
                        if os.path.exists(out_fp):
                            await interaction.followup.send(
                                content=f"🎉 **1話分のアニメーション結合完了！**\n結合クリップ数: {cdata['clips_count']} 本 | ファイル: `{out_fn}`",
                                file=discord.File(out_fp, filename=out_fn)
                            )
                            await status_msg.delete()
                            return
                    err = await resp.text()
                    await status_msg.edit(content=f"⚠️ 結合エラー: {err[:150]}")
            except Exception as e:
                await status_msg.edit(content=f"⚠️ 通信エラー: {e}")

async def execute_and_track_video_job(
    interaction_or_msg,
    user_instruction: str,
    reference_image: Optional[str] = None,
    character_id: Optional[str] = None,
    status_message: Optional[Any] = None
):
    """
    Submits video job to /api/video/jobs and periodically updates Discord progress.
    """
    async with aiohttp.ClientSession() as session:
        try:
            req_data = {
                "user_instruction": user_instruction,
                "reference_image": reference_image,
                "character_id": character_id,
                "style_id": "3d_render_fantasy"
            }
            async with session.post(f"{API_BASE_URL}/api/video/jobs", json=req_data) as resp:
                if resp.status != 200:
                    err = await resp.text()
                    if status_message:
                        await status_message.edit(content=f"⚠️ ジョブ開始エラー: {err[:150]}")
                    return
                res_json = await resp.json()
                job_id = res_json["job_id"]

            # Polling loop
            last_text = ""
            for _ in range(180):  # max 6 minutes timeout
                await asyncio.sleep(2.5)
                async with session.get(f"{API_BASE_URL}/api/video/jobs/{job_id}") as poll_resp:
                    if poll_resp.status != 200:
                        continue
                    jdata = await poll_resp.json()
                    st = jdata.get("status")
                    prog = jdata.get("progress", 0)
                    st_text = jdata.get("status_text", "")

                    if st_text != last_text and status_message:
                        last_text = st_text
                        try:
                            await status_message.edit(content=f"🎬 **3Dレンダー風アニメーション生成中** ({prog}%)\n{st_text}")
                        except Exception:
                            pass

                    if st == "completed":
                        rdata = jdata.get("result_data", {})
                        fn = rdata.get("filename")
                        fp = os.path.join(OUTPUTS_DIR, fn) if fn else None
                        kf_url = rdata.get("keyframe_url", "")
                        mp = rdata.get("motion_prompt", "")

                        if fp and os.path.exists(fp):
                            view = VideoControlView(video_filename=fn, keyframe_url=kf_url, motion_prompt=mp)
                            send_target = status_message.channel if hasattr(status_message, "channel") else interaction_or_msg.channel
                            await send_target.send(
                                content=(
                                    f"✨ **5秒アニメーションクリップ完成！** (Wan 2.2 TI2V-5B)\n"
                                    f"⏱️ 尺: {rdata.get('duration_seconds')}秒 (81フレーム @ 16fps) | 所要時間: {rdata.get('elapsed_seconds')}秒\n"
                                    f"🎥 **Camera Motion**: `{mp}`"
                                ),
                                file=discord.File(fp, filename=fn),
                                view=view
                            )
                            try:
                                await status_message.delete()
                            except Exception:
                                pass
                        return
                    elif st == "failed":
                        err_msg = jdata.get("error_message", "不明なエラー")
                        if status_message:
                            await status_message.edit(content=f"⚠️ 動画生成失敗: {err_msg[:200]}")
                        return

            if status_message:
                await status_message.edit(content="⚠️ ジョブがタイムアウトしました。")
        except Exception as e:
            if status_message:
                await status_message.edit(content=f"⚠️ ジョブ実行エラー: {e}")

@bot.event
async def on_ready():
    # Register persistent button view so buttons survive bot restarts!
    bot.add_view(PersistentGenerateButtonView())
    bot.add_view(ImageModeSelectView())
    bot.add_view(RemakeInteractiveView())
    bot.add_view(QuickControlPanelView())
    bot.add_view(VideoControlView())
    print(f"==================================================", flush=True)
    print(f"  Discord Bot Logged in as: {bot.user.name}#{bot.user.discriminator} (ID: {bot.user.id})", flush=True)
    print(f"  Joined Guilds (Servers): {[g.name for g in bot.guilds]}", flush=True)
    print(f"  Registered Persistent Button Views for zero-timeout clicks!", flush=True)
    print(f"  Connected to Local Backend: {API_BASE_URL}", flush=True)
    print(f"==================================================", flush=True)
    await bot.change_presence(activity=discord.Game(name="ルカと会話 | @メンションしてね"))

    # Send a notification to the first available text channel
    for guild in bot.guilds:
        for channel in guild.text_channels:
            if "画" in channel.name or "llm" in channel.name or channel.permissions_for(guild.me).send_messages:
                try:
                    await channel.send("✨ **ルカが最新システムで復帰したよ！**\nボタンの永続化（再起動後も押せる機能）とControlNetポーズ固定を完全同期しました！いつでも話しかけてね🎨")
                    print(f"[Bot] Sent ready announcement to #{channel.name}", flush=True)
                    return
                except Exception as e:
                    print(f"[Bot] Could not send to #{channel.name}: {e}", flush=True)


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
                                description=f"""元画像の配置（後ろから掴む手・噴出・デスク）をそのまま完全固定し、RealVisXLで実写化しました！

**プロンプト**:
```{pos_prompt[:800]}```""",
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
    embed.add_field(name="💡 ワンクリック機能一覧", value="・画像サイズ切替: 下のボタンをタップ\n・プロンプト微調整: 生成後の [✏️ プロンプト微調整] で直接編集\n・シード変更: 生成後の [🎲 シード変更] で無限バリエーション", inline=False)
    embed.set_footer(text="いつでも !menu または !panel でこの設定画面を呼び出せます")

    view = QuickControlPanelView(channel_id=ctx.channel.id)
    await ctx.send(embed=embed, view=view)

@bot.command(name="help")
async def show_help(ctx):
    embed = discord.Embed(
        title="🎨 専属プロンプト相棒 ルカ - コマンド一覧",
        description="きみの理想の画像を徹底的に形にする専属相棒AI「ルカ」とDiscordで会話できます！",
        color=0x5865F2
    )
    embed.add_field(name="💬 ルカと会話する", value="ボットに `@メンション` して話しかけるか、DMを送ってください。\n「布をなくして」「光と影を強調して」など、こだわりを何でも相談できます！", inline=False)
    embed.add_field(name="📸 参考画像・ポーズ画像を送る", value="ポーズや構図の画像を添付して `@ルカ このポーズにして！` と送るか、既に投稿された画像に「返信（Reply）」して `@ルカ このポーズを参考にして` と指定できます！Vision AIが姿勢や手足の位置を精密に分析してプロンプト化します。", inline=False)
    embed.add_field(name="🕺 ポーズ完全固定 ControlNet", value="参考画像を添付して `@ルカ このポーズにして` と頼むと、骨格抽出対応の **[🦴 このポーズで画像生成 (ControlNet)]** ボタンが付きます！ポチッと押すだけで手足の配置や難関ポーズ（しゃがみ等）を100%忠実に固定生成します。", inline=False)
    embed.add_field(name="⚡ 直接画像生成", value="`!image <プロンプト>` : 直接プロンプトを指定して画像を生成します（画像を添付すると自動でControlNetポーズ固定になります）。", inline=False)
    embed.add_field(name="🦴 直接ポーズ固定生成", value="`!pose <プロンプト>` : 画像を添付（または返信）して実行すると、骨格抽出＋ポーズ完全固定で即座に生成します。", inline=False)
    embed.add_field(name="📐 画像サイズ変更", value="`!size [比率]` : 縦長(9:16)・横長(16:9)・正方形(1:1)などのサイズ設定を確認・変更します。", inline=False)
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


def parse_direct_prompt_and_negative(input_text: str):
    """Parse positive and negative from !image / !pose inputs"""
    cleaned = input_text.strip()
    pos = cleaned
    neg = ""

    # Check for markdown code blocks or positive:/negative: sections
    if "negative:" in cleaned.lower() or "```negative" in cleaned.lower():
        # Try extracting positive
        m_pos = re.search(r"(?:positive\s*:\s*|```positive\s*)([\s\S]*?)(?=```negative|negative\s*:|$)", cleaned, re.IGNORECASE)
        if m_pos:
            pos = m_pos.group(1).strip()
        else:
            # Split by negative:
            parts = re.split(r"negative\s*:\s*", cleaned, flags=re.IGNORECASE)
            pos = parts[0].strip()
            if len(parts) > 1:
                neg = parts[1].strip()

        # Try extracting negative
        m_neg = re.search(r"(?:negative\s*:\s*|```negative\s*)([\s\S]*?)(?=```|$)", cleaned, re.IGNORECASE)
        if m_neg:
            neg = m_neg.group(1).strip()

    # Clean code blocks and backticks
    pos = re.sub(r"```(?:positive|prompt)?", "", pos, flags=re.IGNORECASE).replace("```", "").replace("`", "").strip()
    pos = re.sub(r"^(?:positive|prompt)\s*:\s*", "", pos, flags=re.IGNORECASE).strip()
    neg = re.sub(r"```(?:negative)?", "", neg, flags=re.IGNORECASE).replace("```", "").replace("`", "").strip()
    neg = re.sub(r"^negative\s*:\s*", "", neg, flags=re.IGNORECASE).strip()

    return pos, neg

@bot.command(name="size")
async def size_cmd(ctx, *, ratio: str = ""):
    """Set or inspect default aspect ratio for image generation"""
    ratio = ratio.strip().lower()
    global channel_default_ratio
    current = channel_default_ratio.get(ctx.channel.id, "1:1")

    if not ratio:
        embed = discord.Embed(
            title="📐 画像サイズ・アスペクト比 設定",
            description=f"現在のチャンネル設定: **`{current}`** ({HQ_ASPECT_RATIO_DESCS.get(current, '1024×1024')})\n\n`!size <比率>` でデフォルトを変更できます！\n（例: `!size 9:16` または `!size 縦長`）",
            color=0x3498DB
        )
        embed.add_field(name="📱 `9:16` (832×1216)", value="スマホ壁紙・全身ショット・立ち絵に最適！", inline=False)
        embed.add_field(name="🖼️ `3:4` (896×1152)", value="ポートレート・ポスター・人物中心に最適！", inline=False)
        embed.add_field(name="⏹️ `1:1` (1024×1024)", value="標準正方形・アイコン・SNS向け！", inline=False)
        embed.add_field(name="🎬 `16:9` (1216×832)", value="PC壁紙・シネマティック・横長風景向け！", inline=False)
        embed.add_field(name="📷 `4:3` (1152×896)", value="クラシック写真・横長構図向け！", inline=False)
        await ctx.send(embed=embed)
        return

    detected = extract_ratio_from_text(ratio)
    if detected:
        channel_default_ratio[ctx.channel.id] = detected
        desc = HQ_ASPECT_RATIO_DESCS.get(detected, detected)
        await ctx.send(f"✅ デフォルト画像サイズを **`{detected}`** ({desc}) に変更したよ！\n今後の生成や `!image` はこのサイズで出力されるよ🎨")
    else:
        await ctx.send("⚠️ 指定された比率が見つかりませんでした。\n`9:16`, `3:4`, `1:1`, `16:9`, `4:3`、または「縦長」「横長」と指定してね！")


@bot.command(name="pose")
async def generate_pose_cmd(ctx, *, prompt: str = ""):
    """Direct ControlNet pose generation from attached image"""
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

    if not attachments:
        await ctx.send("⚠️ ポーズの参考画像を一緒に添付するか、画像に返信して `!pose <プロンプト>` を実行してね！")
        return

    pos_prompt, neg_prompt = parse_direct_prompt_and_negative(prompt)
    target_ratio = extract_ratio_from_text(prompt) or channel_default_ratio.get(ctx.channel.id, "1:1")
    ratio_label = HQ_ASPECT_RATIO_DESCS.get(target_ratio, target_ratio)

    target_ratio = extract_ratio_from_text(prompt) or channel_default_ratio.get(ctx.channel.id, "1:1")
    ratio_label = HQ_ASPECT_RATIO_DESCS.get(target_ratio, target_ratio)

    if not pos_prompt:
        pos_prompt = "1girl, solo, adult woman, mature female, 25 years old, highly detailed, photorealistic 8k, RAW photo"

    status_msg = await ctx.send(f"🦴 参考画像から骨格を抽出し、ControlNetでポーズを完全固定して生成中... (`{pos_prompt[:50]}...`)")

    try:
        raw_b = await attachments[0].read()
        pose_data_url = process_image_to_data_url(raw_b)
    except Exception as e:
        await status_msg.edit(content=f"⚠️ 画像の読み込みに失敗しました: {e}")
        return

    async with ctx.typing():
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=600)) as session:
            try:
                global current_selected_lora
                payload = {
                    "prompt": pos_prompt,
                    "negative_prompt": neg_prompt or "child, loli, teen, young, underage, school uniform, bad hands, extra fingers, blurry, low quality",
                    "enhance_prompt": False,
                    "lora_name": current_selected_lora,
                    "lora_scale": 0.8,
                    "steps": 30,
                    "guidance_scale": 7.5,
                    "aspect_ratio": target_ratio,
                    "pose_image": pose_data_url,
                    "controlnet_scale": 0.85
                }
                async with session.post(f"{API_BASE_URL}/api/hq/generate", json=payload) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        img_data = data.get("image_url", "")
                        skel_data = data.get("pose_skeleton_url")
                        if img_data.startswith("data:image/png;base64,"):
                            raw_bytes = base64.b64decode(img_data.split(",", 1)[1])
                            files_to_send = [discord.File(io.BytesIO(raw_bytes), filename="generated.png")]
                            embed = discord.Embed(
                                title="🕺 ポーズ完全固定 ControlNet 生成完了！",
                                description=f"**プロンプト**:\n```{pos_prompt[:900]}```",
                                color=0x00FF88
                            )
                            embed.set_footer(text=f"OpenPose XL ControlNet 1024x1024 | Steps: {data.get('steps', 30)} | Seed: {data.get('seed')} | Time: {data.get('elapsed_seconds', 0)}s")
                            embed.set_image(url="attachment://generated.png")
                            if skel_data and skel_data.startswith("data:image/png;base64,"):
                                skel_bytes = base64.b64decode(skel_data.split(",", 1)[1])
                                files_to_send.append(discord.File(io.BytesIO(skel_bytes), filename="skeleton.png"))
                                embed.set_thumbnail(url="attachment://skeleton.png")
                                embed.add_field(name="🦴 抽出された骨格ワイヤーフレーム", value="右上のサムネイルに骨格抽出結果を表示しています！", inline=False)
                            await ctx.send(embed=embed, files=files_to_send)
                            await status_msg.delete()
                        else:
                            await status_msg.edit(content="⚠️ 画像データのデコードに失敗しました。")
                    else:
                        err = await resp.text()
                        await status_msg.edit(content=f"⚠️ 生成エラー: {err[:200]}")
            except Exception as e:
                await status_msg.edit(content=f"⚠️ 通信エラー: {e}")

@bot.command(name="char")
async def char_mode_cmd(ctx, *, prompt: str = ""):
    """Mode 2: Extract character identity/DNA from attached image"""
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

    if not attachments:
        await ctx.send("⚠️ 人物を学習・再現したい画像を添付するか、画像に返信して `!char <追加指示>` を実行してね！")
        return

    status_msg = await ctx.send("👤 画像の女性の顔立ち・髪型・体型DNAを抽出中...")
    try:
        raw_b = await attachments[0].read()
        img_url = process_image_to_data_url(raw_b)
        res = await analyze_image_for_mode(img_url, mode="character_identity", user_instruction=prompt)
        pos = res["positive"]
        neg = res["negative"]
        clean_reply = f"👤 **この女性の顔立ち・髪型・体型DNAを忠実に抽出したよ！**\nこの人物の同一性をキープしたまま、別のシーンやポーズでも生成できるように組んだよ✨\n\n**🎨 プロンプト (Positive)**\n```prompt\n{pos}\n```\n\n**🛡️ 除外タグ (Negative)**\n```negative\n{neg}\n```"
        view = PersistentGenerateButtonView(pos, neg, pose_image=None)
        await ctx.send(clean_reply, view=view)
        await status_msg.delete()
    except Exception as e:
        await status_msg.edit(content=f"⚠️ 人物抽出エラー: {e}")

@bot.command(name="scene")
async def scene_mode_cmd(ctx, *, prompt: str = ""):
    """Mode 4: Extract both pose and complete scene/environment context"""
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

    if not attachments:
        await ctx.send("⚠️ シチュエーションとポーズを再現したい画像を添付するか、画像に返信して `!scene <追加指示>` を実行してね！")
        return

    status_msg = await ctx.send("📸 ポーズの骨格および背景・照明シチュエーションを丸ごと抽出中...")
    try:
        raw_b = await attachments[0].read()
        img_url = process_image_to_data_url(raw_b)
        res = await analyze_image_for_mode(img_url, mode="scene_and_pose", user_instruction=prompt)
        pos = res["positive"]
        neg = res["negative"]
        clean_reply = f"📸 **ポーズの骨格と、背景・照明・部屋のシチュエーションを丸ごと再現したよ！**\nこの空間と姿勢を完璧にそのまま出力できるように組んだよ✨\n\n**🎨 プロンプト (Positive)**\n```prompt\n{pos}\n```\n\n**🛡️ 除外タグ (Negative)**\n```negative\n{neg}\n```"
        view = PersistentGenerateButtonView(pos, neg, pose_image=img_url)
        await ctx.send(clean_reply, view=view)
        await status_msg.delete()
    except Exception as e:
        await status_msg.edit(content=f"⚠️ シチュエーション抽出エラー: {e}")

@bot.command(name="image")
async def generate_image_cmd(ctx, *, prompt: str = ""):
    pos_prompt, neg_prompt = parse_direct_prompt_and_negative(prompt)
    target_ratio = extract_ratio_from_text(prompt) or channel_default_ratio.get(ctx.channel.id, "1:1")
    ratio_label = HQ_ASPECT_RATIO_DESCS.get(target_ratio, target_ratio)
    if not pos_prompt.strip():
        await ctx.send("⚠️ 画像のプロンプトを入力してね！\n例: `!image 1girl, solo, dramatic lighting, RAW photo`")
        return

    # Check if user attached reference image to enable ControlNet
    pose_data_url = None
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

    if attachments:
        try:
            raw_b = await attachments[0].read()
            pose_data_url = process_image_to_data_url(raw_b)
        except Exception:
            pass

    status_text = f"🦴 画像から骨格を抽出し、**{ratio_label}** でポーズ固定生成中... (`{pos_prompt[:40]}...`)" if pose_data_url else f"🎨 RealVisXL **{ratio_label}** で画像を生成中... (`{pos_prompt[:40]}...`)"
    msg = await ctx.send(status_text)
    
    async with ctx.typing():
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=600)) as session:
            try:
                global current_selected_lora
                payload = {
                    "prompt": pos_prompt,
                    "negative_prompt": neg_prompt or "child, loli, teen, young, underage, school uniform, bad hands, extra fingers, blurry, low quality",
                    "enhance_prompt": False,
                    "lora_name": current_selected_lora,
                    "lora_scale": 0.8,
                    "steps": 30,
                    "guidance_scale": 7.5,
                    "aspect_ratio": target_ratio,
                    "pose_image": pose_data_url,
                    "controlnet_scale": 0.85
                }
                async with session.post(f"{API_BASE_URL}/api/hq/generate", json=payload) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        img_data = data.get("image_url", "")
                        skel_data = data.get("pose_skeleton_url")
                        if img_data.startswith("data:image/png;base64,"):
                            raw_bytes = base64.b64decode(img_data.split(",", 1)[1])
                            files_to_send = [discord.File(io.BytesIO(raw_bytes), filename="generated.png")]
                            
                            is_cnet = data.get("controlnet_active", False)
                            embed = discord.Embed(
                                title="🕺 ポーズ完全固定 ControlNet 生成完了！" if is_cnet else "✨ 画像生成が完了したよ！",
                                description=f"**プロンプト**:\n```{pos_prompt[:900]}```",
                                color=0x00FF88 if is_cnet else 0x5865F2
                            )
                            mode_lbl = "OpenPose XL ControlNet" if is_cnet else "RealVisXL Standard"
                            embed.set_footer(text=f"{mode_lbl} 1024x1024 | Steps: {data.get('steps', 30)} | Seed: {data.get('seed')} | Time: {data.get('elapsed_seconds', 0)}s")
                            embed.set_image(url="attachment://generated.png")

                            if skel_data and skel_data.startswith("data:image/png;base64,"):
                                skel_bytes = base64.b64decode(skel_data.split(",", 1)[1])
                                files_to_send.append(discord.File(io.BytesIO(skel_bytes), filename="skeleton.png"))
                                embed.set_thumbnail(url="attachment://skeleton.png")
                                embed.add_field(name="🦴 抽出された骨格ワイヤーフレーム", value="右上のサムネイルに骨格抽出結果を表示しています！", inline=False)

                            await ctx.send(embed=embed, files=files_to_send)
                            await msg.delete()
                        else:
                            await msg.edit(content="⚠️ 画像データのデコードに失敗しました。")
                    else:
                        err = await resp.text()
                        await msg.edit(content=f"⚠️ 生成エラー: {err[:200]}")
            except Exception as e:
                await msg.edit(content=f"⚠️ 通信エラー: {e}")

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

            # 1. First, check if the user is replying to a previous image generation result or prompt
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

            # Fallback: If user refers to "この画像" or mentions image without attaching, resolve from channel cache/history
            if not attached_images and any(k in clean_text for k in ["この画像", "その画像", "元の画像", "元画像", "画像に"]):
                cached_img = channel_last_image.get(message.channel.id)
                if cached_img:
                    attached_images.append(cached_img)
                    print(f"[Bot] Resolved reference image from channel cache for prompt request: '{clean_text}'", flush=True)

            # 3. Branching logic:
            has_modification_intent = bool(last_positive_prompt) and bool(clean_text) and (
                is_reply_to_generation
                or any(k in clean_text for k in [
                    "にして", "に変えて", "に変更", "消して", "削除", "なくして", "追加", "足して",
                    "着せて", "着て", "和服", "着物", "ドレス", "服", "水着", "衣装", "ポーズ",
                    "顔", "歳", "才", "体型", "胸", "背景", "夜", "昼", "全身", "アップ", "表情",
                    "笑", "泣", "タトゥー", "ピアス", "眼鏡", "脱", "ブラ", "画像に", "この画像"
                ])
                or not attached_images
            )

            # Direct Video Intent Routing (e.g. 「動画にして」「アニメーションにして」「動かして」)
            is_video_intent = any(k in clean_text for k in ["動画", "アニメーション", "動かして", "動かす", "video", "clip", "アニメ化", "走らせて", "歩かせて"])
            if is_video_intent:
                status_msg = await message.reply("🎬 **Wan 2.2 3Dレンダー風アニメーション生成ジョブを受け付けたよ！**\nプロンプト構想とキーフレーム生成を開始します... (約1〜2分)")
                ref_img = attached_images[0] if attached_images else channel_last_image.get(message.channel.id)
                char_id = "elena_valkyrie" if any(k in clean_text for k in ["エレナ", "elena", "女戦士"]) else None
                await execute_and_track_video_job(
                    message,
                    user_instruction=clean_text,
                    reference_image=ref_img,
                    character_id=char_id,
                    status_message=status_msg
                )
                return

            if attached_images:
                # Case A: User uploaded/referenced an image - Prioritize analyzing the image!
                print(f"[Bot] Attached {len(attached_images)} reference image(s) for Vision LLM", flush=True)
                channel_last_image[message.channel.id] = attached_images[0]
                target_mode = detect_requested_image_mode(clean_text)

                # Check if user asks for dress/outfit extraction
                is_outfit_ref = any(k in clean_text for k in [
                    "ドレス", "服", "衣装", "着て", "着せ", "コスチューム", "下着", "水着",
                    "ブラ", "ランジェリー", "ワンピ", "スカート", "シャツ", "装飾", "outfit", "dress", "clothes", "和服", "着物"
                ])

                if is_outfit_ref:
                    user_content = (
                        f"【添付画像解析：ドレス・衣装・服装の完全抽出と適用】\n"
                        f"ユーザー要望: {clean_text}\n\n"
                        f"添付画像に写っているドレスや衣装（デザイン、色、生地の質感、装飾、胸元の開き具合、シルエット、アクセサリーなど）を最高解像度で精緻に解析・抽出し、それを完璧に反映したRealVisXL用最高峰の英語プロンプトを構築してください。\n"
                    )
                    if last_positive_prompt:
                        user_content += (
                            f"\n【前回の人物・キャラクターベースプロンプト】\n"
                            f"Positive: {last_positive_prompt}\n"
                            f"Negative: {last_negative_prompt}\n"
                            f"（※最重要指示: 上記の前回プロンプトの人物（顔立ち・髪色・髪型・体型など）の魅力を100%維持しつつ、衣装・服装タグのみを添付画像のドレス・衣装に正確に差し替えて融合してください）"
                        )
                elif target_mode:
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
                    if last_positive_prompt:
                        user_content += f"\n\n【参考ベースプロンプト】\nPositive: {last_positive_prompt}\nNegative: {last_negative_prompt}"
                elif not clean_text or len(clean_text) < 15:
                    embed = discord.Embed(
                        title="📸 画像を受け取ったよ！どう活用する？",
                        description=(
                            "目的に合わせて下のボタンをタップしてね！\n\n"
                            "👗 **衣装・ドレス参考**: 画像のドレス・衣装デザインを抽出して着用\n"
                            "🎨 **1. 画風学習**: 絵柄・タッチ・色彩・質感のみを抽出\n"
                            "👤 **2. 人物学習**: 顔立ち・髪型・体型DNAを抽出して同一人物を再現\n"
                            "🦴 **3. ポーズのみ固定**: 骨格ワイヤーフレーム（ControlNet）で姿勢を100%固定\n"
                            "🔄 **4. 構図固定リメイク**: 後ろから掴む手・小道具・配置を完全固定して実写化 (img2img)"
                        ),
                        color=0x9B59B6
                    )
                    mode_view = ImageModeSelectView(image_data_url=attached_images[0], user_prompt=clean_text)
                    await message.reply(embed=embed, view=mode_view)
                    return
                else:
                    user_content = (
                        f"【添付画像解析とプロンプト構築】\n"
                        f"添付画像の特徴をVision LLMとWD14タグで精緻に分析し、ユーザー要望『{clean_text}』に沿ったRealVisXL用の最高峰のプロンプトを作成してください。\n"
                    )
                    if last_positive_prompt:
                        user_content += f"\n【前回のベースプロンプト】\nPositive: {last_positive_prompt}\nNegative: {last_negative_prompt}"

            elif has_modification_intent:
                # Case B: Text-only prompt modification request (no new image attached)
                print(f"[Bot] Detected prompt revision/transformation request: '{clean_text}' (Base prompt: '{last_positive_prompt[:40]}...')", flush=True)
                user_content = (
                    f"【返信元のベースプロンプト】\n"
                    f"Positive: {last_positive_prompt}\n"
                    f"Negative: {last_negative_prompt}\n\n"
                    f"【ユーザーからの最新の変更・変身要望】\n{clean_text}\n\n"
                    f"（※最重要指示：上記の【返信元のベースプロンプト】を100%土台として使用し、ユーザーの最新の変更要望（例：髪型、衣装・服装、年齢、表情、ポーズ、シチュエーション、体型など）に該当する部分だけを正確に差し替え・加筆・削除してください。変更指示のない他の魅力的な要素（画質タグ、顔立ち、質感、雰囲気など）は絶対に消去せず完全に維持してください）"
                )
                if any(k in clean_text for k in ["着せて", "着て", "和服", "着物", "ドレス", "服", "水着", "着用", "コスチューム", "衣装"]):
                    user_content += "\n（※重要：衣服の着用・着せ替え指示です。Positiveプロンプトから `topless, bare breasts, nude, naked, exposed breasts, nipple` などの裸・露出タグを完全に削除し、指示された衣装（和服の場合は `kimono, japanese traditional clothes, ornate floral kimono, elegant obi sash` など）を明確に追加してください。Negativeプロンプトにも `topless, bare breasts, nude, naked, exposed breasts` を必ず追加してください）"
                elif any(k in clean_text for k in ["服", "ブラ", "脱", "排除", "外して", "消して", "なくして", "topless", "naked", "素肌"]):
                    user_content += "\n（※衣服・下着の完全排除指示です。Positiveプロンプトからbraやclothingを完全排除して `topless, bare breasts, no clothes` を指定し、Negativeプロンプトに必ず `bra, clothing, shirt, top, underwear` を追加してください）"

            else:
                user_content = clean_text

            # Channel history management (Store ONLY text to prevent Base64 image accumulation)
            hist = channel_history.setdefault(message.channel.id, [])
            hist.append({
                "role": "user",
                "content": user_content
            })
            if len(hist) > 6:
                hist.pop(0)

            # Luka system prompt and build payload messages
            system_prompt = get_bot_system_prompt("creative_buddy_luka")
            payload_messages = [{"role": "system", "content": system_prompt}]
            for h in hist[:-1]:
                payload_messages.append({"role": h["role"], "content": h["content"], "images": []})

            # Pass the single latest image to the current turn only
            curr_images = [attached_images[0]] if attached_images else []
            payload_messages.append({
                "role": "user",
                "content": user_content,
                "images": curr_images
            })

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

                                                        # Smart fallback post-processing: guarantee age and full body if requested by user
                            if "18" in clean_text and ("才" in clean_text or "歳" in clean_text or "years old" in clean_text.lower()):
                                reply_text = re.sub(r"\b(?:19|20|21|22|23|24|25)\s+years\s+old\b", "18 years old", reply_text)
                                if "18 years old" not in reply_text:
                                    reply_text = re.sub(r"(\badult woman\b)", r"\1, 18 years old", reply_text)

                            if "19" in clean_text and ("才" in clean_text or "歳" in clean_text or "years old" in clean_text.lower()):
                                reply_text = re.sub(r"\b(?:18|20|21|22|23|24|25)\s+years\s+old\b", "19 years old", reply_text)
                                if "19 years old" not in reply_text:
                                    reply_text = re.sub(r"(\badult woman\b)", r"\1, 19 years old", reply_text)

                            if any(k in clean_text for k in ["mature femaleを削除", "mature female削除", "mature female消して"]):
                                reply_text = re.sub(r"\bmature female,?\s*", "", reply_text)

                            if any(k in clean_text for k in ["全身", "足先まで", "head to toe"]):
                                if "full body shot" not in reply_text.lower():
                                    reply_text = re.sub(r"(\b1girl,\s*solo,?\s*)", r"\1(full body shot:1.4), (head-to-toe in frame:1.3), whole body visible, ", reply_text)

                            # Format into lively, natural dialogue without robotic meta headers
                            reply_text = format_luka_natural_response(reply_text, has_reference_image=bool(attached_images))

                            hist.append({"role": "assistant", "content": reply_text})

                            # Check and robustly extract prompt to attach Interactive Button
                            extracted_prompt = extract_prompt_robust(reply_text)
                            extracted_neg = extract_negative_robust(reply_text)
                            
                            view = None
                            if extracted_prompt:
                                detected_mode = detect_requested_image_mode(clean_text)
                                # Only attach pose ControlNet if explicitly requested for pose
                                attach_cnet = None
                                if attached_images:
                                    if is_outfit_ref or detected_mode in ("art_style", "character_identity", "remake"):
                                        attach_cnet = None
                                    elif detected_mode in ("pose_only", "scene_and_pose") or ("ポーズ" in clean_text):
                                        attach_cnet = attached_images[0]
                                user_req_ratio = extract_ratio_from_text(clean_text) or channel_default_ratio.get(message.channel.id, "1:1")
                                view = PersistentGenerateButtonView(extracted_prompt, extracted_neg, pose_image=attach_cnet, default_ratio=user_req_ratio)

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

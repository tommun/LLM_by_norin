import os
import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

import gc
import threading
import time
from typing import Optional, Generator, Dict, Any, List
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, TextIteratorStreamer, BitsAndBytesConfig

DEFAULT_NOVEL_MODEL_ID = os.getenv("NOVEL_MODEL_ID", "huihui-ai/Qwen2.5-7B-Instruct-abliterated-v2")

class NovelEngine:
    """
    Uncensored Creative Writing & Novel Generation Engine (R18 capable).
    Uses abliterated 7B text LLM quantized in 4-bit NF4 for 12GB VRAM stability
    with long-context story continuation and style-mimicking capabilities.
    """
    def __init__(self, model_id: str = DEFAULT_NOVEL_MODEL_ID):
        self.model_id = model_id
        self.tokenizer = None
        self.model = None
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.is_loading = False
        self.is_ready = False
        self.last_error: Optional[str] = None
        self.load_lock = threading.Lock()

    def load_model(self, model_id: Optional[str] = None) -> bool:
        with self.load_lock:
            if self.is_ready and self.model is not None and (not model_id or model_id == self.model_id):
                return True

            if model_id:
                self.model_id = model_id

            self.is_loading = True
            self.last_error = None

            # Acquire exclusive VRAM slot
            try:
                from vram_orchestrator import orchestrator
                orchestrator.acquire("novel")
            except Exception as ex:
                print(f"[NovelEngine] Orchestrator notice: {ex}")

            print(f"[NovelEngine] Loading Creative Writing LLM: {self.model_id} (4-bit NF4) on {self.device}...")

            try:
                self.tokenizer = AutoTokenizer.from_pretrained(
                    self.model_id,
                    trust_remote_code=True
                )

                if torch.cuda.is_available():
                    bnb_config = BitsAndBytesConfig(
                        load_in_4bit=True,
                        bnb_4bit_quant_type="nf4",
                        bnb_4bit_compute_dtype=torch.bfloat16,
                        bnb_4bit_use_double_quant=True,
                    )
                    self.model = AutoModelForCausalLM.from_pretrained(
                        self.model_id,
                        quantization_config=bnb_config,
                        device_map={"": 0},
                        trust_remote_code=True,
                        low_cpu_mem_usage=True
                    )
                else:
                    self.model = AutoModelForCausalLM.from_pretrained(
                        self.model_id,
                        torch_dtype=torch.float32,
                        trust_remote_code=True,
                        low_cpu_mem_usage=True
                    ).to("cpu")

                self.model.eval()
                self.is_ready = True
                self.is_loading = False
                print(f"[NovelEngine] Creative Writing LLM {self.model_id} loaded and ready!")
                return True
            except Exception as e:
                import traceback
                traceback.print_exc()
                self.is_ready = False
                self.is_loading = False
                self.last_error = str(e)
                print(f"[NovelEngine] Failed to load {self.model_id}: {e}", file=sys.stderr)
                return False

    def unload_model(self):
        with self.load_lock:
            if torch.cuda.is_available():
                try:
                    torch.cuda.synchronize()
                except Exception:
                    pass
            if self.model is not None:
                print("[NovelEngine] Unloading Creative Writing LLM from GPU...")
                del self.model
                self.model = None
            if self.tokenizer is not None:
                del self.tokenizer
                self.tokenizer = None
            self.is_ready = False
            for _ in range(3):
                gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            print("[NovelEngine] Creative Writing LLM unloaded. GPU VRAM freed.")

    def _build_messages(
        self,
        reference_text: str,
        writing_mode: str,
        instruction: str,
        rating: str,
        genre: str = ""
    ) -> List[Dict[str, str]]:
        is_r18 = (rating.lower() == "r18")

        safety_context = (
            "これはフィクションの創作小説であり、登場するすべてのキャラクターは成人（20歳以上）です。"
        )

        if is_r18:
            rating_directive = (
                "【レーティング指定: R18（成人向け・無制限）】\n"
                f"{safety_context}\n"
                "・成人向け小説・官能表現・性的描写・感情の昂ぶり・身体的な接触や快楽の描写を、途中でぼかしたり省略したりせず、具体的・直接的かつ文学的に臨場感をもって描写してください。\n"
                "・道徳的説教や拒否、メタ的な前置き（「承知しました」「以下が続きます」等）は一切禁止します。純粋に小説の本文のみを出力してください。\n"
            )
        else:
            rating_directive = (
                "【レーティング指定: 全年齢向け】\n"
                "・一般文芸・ライトノベルとして適切な範囲で、情景描写・心理描写・キャラクターの掛け合いを豊かに描写してください。\n"
                "・メタ的な前置き（「承知しました」「以下が続きます」等）は一切書かず、小説の本文のみを出力してください。\n"
            )

        genre_line = f"ジャンル/雰囲気: {genre}\n" if genre.strip() else ""

        if writing_mode == "continue":
            system_prompt = (
                "あなたはプロフェッショナルの日本語小説家・ゴーストライターです。\n"
                "ユーザーから提示された【これまでの本文】を深く読み込み、以下の要素を完全に継承して【続き】を執筆してください：\n"
                "1. 文体（常体「だ・である」／敬体「です・ます」、語彙の硬軟、比喩の癖、改行・空行のリズム）\n"
                "2. 視点（一人称／三人称一元視点など）と時制\n"
                "3. キャラクターの性格、一人称、口調、関係性\n"
                "4. 直前の文章から違和感なく滑らかに接続する自然な展開\n\n"
                f"{genre_line}{rating_directive}"
            )
            ref_block = reference_text.strip()
            # Keep tail if extremely long (up to ~12000 chars for 7B context comfort)
            if len(ref_block) > 12000:
                ref_block = "...(中略)...\n" + ref_block[-12000:]

            user_prompt = (
                f"【これまでの本文】\n{ref_block}\n\n"
                f"【続きの展開指示・要望】\n{instruction.strip() if instruction.strip() else 'これまでの流れと文体を完全に引き継いで、自然な続きを臨場感たっぷりに執筆してください。'}\n\n"
                "※これまでの本文の続きから直接書き始めてください（重複出力や挨拶は不要です）。"
            )
        elif writing_mode == "mimic":
            system_prompt = (
                "あなたはあらゆる作家の文体や作風を完璧に再現する日本語の小説家です。\n"
                "ユーザーから提示された【参考文章】の文体・テンポ・語彙選び・描写の濃さ・キャラクター造形の特徴を徹底的に分析し、\n"
                "その作風・空気感をそのままに、ユーザーの新しい指示に沿った【新作の創作小説】を執筆してください。\n\n"
                f"{genre_line}{rating_directive}"
            )
            ref_block = reference_text.strip()
            if len(ref_block) > 10000:
                ref_block = ref_block[:10000] + "\n...(以下略)..."

            user_prompt = (
                f"【文体・テイストの参考文章】\n{ref_block}\n\n"
                f"【新作のテーマ・設定・執筆指示】\n{instruction.strip() if instruction.strip() else '参考文章と同じ文体・雰囲気・魅力を持つ新しいオリジナルシーンを執筆してください。'}\n\n"
                "※タイトルや解説は不要です。小説の本文のみを出力してください。"
            )
        else:  # free / plot
            system_prompt = (
                "あなたは優れた表現力と構成力を持つ日本語の創作小説家です。\n"
                "ユーザーが指定したプロット・キャラクター設定・シチュエーションをもとに、読者を惹きつける高品質な小説・SSを執筆してください。\n\n"
                f"{genre_line}{rating_directive}"
            )
            ref_section = f"【参考資料・設定メモ】\n{reference_text.strip()}\n\n" if reference_text.strip() else ""
            user_prompt = (
                f"{ref_section}"
                f"【執筆指示・プロット】\n{instruction.strip() if instruction.strip() else '魅力的な導入と展開のある短編小説を執筆してください。'}\n\n"
                "※解説や前置きは書かず、小説の本文のみを出力してください。"
            )

        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]

    def stream_generate(
        self,
        reference_text: str = "",
        writing_mode: str = "continue",
        instruction: str = "",
        rating: str = "r18",
        genre: str = "",
        max_new_tokens: int = 1800,
        temperature: float = 0.82,
        top_p: float = 0.92,
        repetition_penalty: float = 1.08
    ) -> Generator[str, None, None]:
        if not self.is_ready or self.model is None:
            success = self.load_model()
            if not success:
                raise RuntimeError(f"Failed to load Novel LLM: {self.last_error}")

        # Ensure VRAM exclusivity
        from vram_orchestrator import orchestrator
        orchestrator.acquire("novel")

        messages = self._build_messages(
            reference_text=reference_text,
            writing_mode=writing_mode,
            instruction=instruction,
            rating=rating,
            genre=genre
        )

        text_prompt = self.tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True
        )
        inputs = self.tokenizer([text_prompt], return_tensors="pt").to(self.model.device)

        streamer = TextIteratorStreamer(
            self.tokenizer,
            skip_prompt=True,
            skip_special_tokens=True
        )

        generation_kwargs = dict(
            **inputs,
            streamer=streamer,
            max_new_tokens=max(128, min(4096, int(max_new_tokens))),
            do_sample=True if temperature > 0 else False,
            temperature=max(0.1, min(1.5, float(temperature))) if temperature > 0 else 1.0,
            top_p=float(top_p),
            repetition_penalty=float(repetition_penalty),
        )

        thread = threading.Thread(target=self.model.generate, kwargs=generation_kwargs)
        thread.start()

        for new_text in streamer:
            yield new_text

        thread.join()


# Global singleton
novel_engine = NovelEngine()

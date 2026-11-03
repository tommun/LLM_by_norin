import os

bot_path = r"C:\Users\owner\.gemini\antigravity\scratch\LLM_by_norin\backend\discord_bot.py"
with open(bot_path, "r", encoding="utf-8") as f:
    text = f.read()

text = text.replace(
    'await ctx.send("⚠️ 元画像を添付するか、画像に返信して `!remake [denoise値 (0.55-0.65)] [プロンプト]` を実行してね！\n（配置・手・母乳・机などを元画像からそのまま完全固定して再描画します）")',
    'await ctx.send("⚠️ 元画像を添付するか、画像に返信して `!remake [denoise値 (0.55-0.65)] [プロンプト]` を実行してね！\\n（配置・手・母乳・机などを元画像からそのまま完全固定して再描画します）")'
)

with open(bot_path, "w", encoding="utf-8") as f:
    f.write(text)

print("Fixed line 768")

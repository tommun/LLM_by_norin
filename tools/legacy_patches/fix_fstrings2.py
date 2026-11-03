import os

bot_path = r"C:\Users\owner\.gemini\antigravity\scratch\LLM_by_norin\backend\discord_bot.py"
with open(bot_path, "r", encoding="utf-8") as f:
    text = f.read()

broken_str = '''    embed.add_field(name="💡 ワンクリック機能一覧", value=(
        "・**画像サイズ切替**: 下の `📱 縦長` や `⏹️ 正方形` ボタンをタップ\n"
        "・**プロンプト微調整**: 生成後の `✏️ プロンプト微調整` ボタンで手動編集\n"
        "・**シード変更**: 生成後の `🎲 シード変更` ボタンで無限バリエーション"
    ), inline=False)'''

fixed_str = '''    embed.add_field(name="💡 ワンクリック機能一覧", value="・画像サイズ切替: 下のボタンをタップ\\n・プロンプト微調整: 生成後の [✏️ プロンプト微調整] で直接編集\\n・シード変更: 生成後の [🎲 シード変更] で無限バリエーション", inline=False)'''

text = text.replace(broken_str, fixed_str)

with open(bot_path, "w", encoding="utf-8") as f:
    f.write(text)

print("Fixed line 1045")

bot_path = r"C:\Users\owner\.gemini\antigravity\scratch\LLM_by_norin\backend\discord_bot.py"
with open(bot_path, "r", encoding="utf-8") as f:
    code = f.read()

idx = code.find('# Find the most recent prompt in this channel to enable smooth incremental editing')
idx_else_end = code.find('            # Channel history management', idx)
print("=== REGION TO REPLACE ===")
print(code[idx:idx_else_end])
print("=========================")

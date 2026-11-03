import os

bot_path = r"C:\Users\owner\.gemini\antigravity\scratch\LLM_by_norin\backend\discord_bot.py"
with open(bot_path, "r", encoding="utf-8") as f:
    text = f.read()

# Replace the broken button block in PersistentGenerateButtonView
broken_block = '''    @discord.ui.button(label="🎬 横長 (16:9)", style=discord.ButtonStyle.secondary, emoji="🎬", custom_id="luka_btn_16_9")

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

    async def btn_16_9(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._execute_generate(interaction, "16:9")'''

fixed_block = '''    @discord.ui.button(label="🎬 横長 (16:9)", style=discord.ButtonStyle.secondary, emoji="🎬", custom_id="luka_btn_16_9")
    async def btn_16_9(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._execute_generate(interaction, "16:9")

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
        await interaction.response.send_modal(modal)'''

if broken_block in text:
    text = text.replace(broken_block, fixed_block)
    print("Successfully fixed button decorator alignment!")
else:
    print("Warning: broken block not matched exactly, checking alternative pattern...")

# Also wrap the button style update in try-except in PersistentGenerateButtonView.__init__
init_style_block = '''        # Highlight primary button based on requested default ratio
        if self.default_ratio == "9:16":
            self.btn_9_16.style = discord.ButtonStyle.success if self.pose_image else discord.ButtonStyle.primary
        elif self.default_ratio == "3:4":
            self.btn_3_4.style = discord.ButtonStyle.success if self.pose_image else discord.ButtonStyle.primary
        elif self.default_ratio == "16:9":
            self.btn_16_9.style = discord.ButtonStyle.success if self.pose_image else discord.ButtonStyle.primary
        else:
            self.btn_1_1.style = discord.ButtonStyle.success if self.pose_image else discord.ButtonStyle.primary

        if self.pose_image:
            self.btn_9_16.label = "🦴 縦長 (9:16)"
            self.btn_3_4.label = "🦴 縦長 (3:4)"
            self.btn_1_1.label = "🦴 正方形 (1:1)"
            self.btn_16_9.label = "🦴 横長 (16:9)"'''

safe_style_block = '''        # Highlight primary button based on requested default ratio safely
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
            print(f"Warning updating PersistentGenerateButtonView button styles: {e}", flush=True)'''

if init_style_block in text:
    text = text.replace(init_style_block, safe_style_block)
    print("Successfully added safe guard to __init__ style updates!")

with open(bot_path, "w", encoding="utf-8") as f:
    f.write(text)

print("Saved discord_bot.py.")

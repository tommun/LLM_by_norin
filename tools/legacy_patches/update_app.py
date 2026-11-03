import os

app_path = r"C:\Users\owner\.gemini\antigravity\scratch\LLM_by_norin\frontend\src\App.tsx"
with open(app_path, "r", encoding="utf-8") as f:
    text = f.read()

target = 'onChange={(e) => setHqNegativePrompt(e.target.value)}\n              />\n            </div>'
if target not in text:
    target = 'onChange={(e) => setHqNegativePrompt(e.target.value)}\r\n              />\r\n            </div>'

replacement = '''onChange={(e) => setHqNegativePrompt(e.target.value)}
              />
            </div>

            {/* img2img Remake & ControlNet Settings */}
            <div className="param-group" style={{ marginTop: '12px', borderTop: '1px solid rgba(255,255,255,0.08)', paddingTop: '10px' }}>
              <div className="param-label">
                <span>🔄 構図固定リメイク (img2img)</span>
                <input
                  type="checkbox"
                  checked={isRemakeMode}
                  onChange={(e) => {
                    setIsRemakeMode(e.target.checked);
                    if (e.target.checked) setIsPoseMode(false);
                  }}
                  style={{ cursor: 'pointer' }}
                />
              </div>
              <div style={{ fontSize: '0.7rem', color: '#94a3b8', marginBottom: '4px' }}>
                画像を添付して実行。手や小道具・デスク配置を固定して実写化
              </div>
              {isRemakeMode && (
                <div style={{ marginTop: '6px' }}>
                  <div className="param-label" style={{ fontSize: '0.7rem' }}>
                    <span>Denoise強度 (保持度)</span>
                    <span className="param-value">{remakeDenoise.toFixed(2)}</span>
                  </div>
                  <input
                    type="range"
                    min="0.40"
                    max="0.80"
                    step="0.05"
                    value={remakeDenoise}
                    onChange={(e) => setRemakeDenoise(parseFloat(e.target.value))}
                    className="param-slider"
                  />
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.65rem', color: '#64748b' }}>
                    <span>0.50 (元画像強)</span>
                    <span>0.60 (推奨)</span>
                    <span>0.70 (質感強)</span>
                  </div>
                </div>
              )}
            </div>

            <div className="param-group">
              <div className="param-label">
                <span>🦴 ポーズ骨格固定 (ControlNet)</span>
                <input
                  type="checkbox"
                  checked={isPoseMode}
                  onChange={(e) => {
                    setIsPoseMode(e.target.checked);
                    if (e.target.checked) setIsRemakeMode(false);
                  }}
                  style={{ cursor: 'pointer' }}
                />
              </div>
              <div style={{ fontSize: '0.7rem', color: '#94a3b8' }}>
                参考画像の人物姿勢をOpenPoseで抽出して100%ポーズ固定
              </div>
            </div>'''

if target in text:
    text = text.replace(target, replacement, 1)
    with open(app_path, "w", encoding="utf-8") as f:
        f.write(text)
    print("Successfully updated App.tsx controls!")
else:
    print("Error: Target not found in App.tsx")

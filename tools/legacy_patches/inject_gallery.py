import os

app_path = r"C:\Users\owner\.gemini\antigravity\scratch\LLM_by_norin\frontend\src\App.tsx"
with open(app_path, "r", encoding="utf-8") as f:
    code = f.read()

# 1. Update Lucide icons import to include Grid, Eye
if "Grid," not in code:
    code = code.replace(
        "  Share2\n} from 'lucide-react';",
        "  Share2,\n  Grid,\n  Eye,\n  Search,\n  Clock\n} from 'lucide-react';"
    )

# 2. Update ChatSession mode type to include 'gallery'
if "'gallery'" not in code:
    code = code.replace(
        "mode: 'chat' | 'image' | 'train' | 'bots' | 'prompt_master' | 'style_master';",
        "mode: 'chat' | 'image' | 'train' | 'bots' | 'prompt_master' | 'style_master' | 'gallery';"
    )

# 3. Add GalleryItem interface and gallery states
gallery_states = '''
interface GalleryItem {
  filename: string;
  url: string;
  size_bytes: number;
  created_at: number;
  created_at_iso: string;
  prompt: string;
  negative_prompt?: string;
  seed?: number;
  steps?: number;
  aspect_ratio?: string;
  width?: number;
  height?: number;
  model_id?: string;
  lora_name?: string;
  elapsed_seconds?: number;
}
'''

if "interface GalleryItem" not in code:
    code = code.replace("export default function App() {", gallery_states + "\nexport default function App() {")

# 4. Add gallery hooks inside App component
gallery_hooks = '''  // Gallery States
  const [galleryItems, setGalleryItems] = useState<GalleryItem[]>([]);
  const [gallerySearch, setGallerySearch] = useState('');
  const [isLoadingGallery, setIsLoadingGallery] = useState(false);
  const [selectedGalleryItem, setSelectedGalleryItem] = useState<GalleryItem | null>(null);

  const fetchGallery = async () => {
    setIsLoadingGallery(true);
    try {
      const res = await fetch(`${BACKEND_URL}/api/gallery?limit=300`);
      if (res.ok) {
        const data = await res.json();
        setGalleryItems(data.items || []);
      }
    } catch (err) {
      console.error('Failed to fetch gallery:', err);
    } finally {
      setIsLoadingGallery(false);
    }
  };

  useEffect(() => {
    if (activeSession.mode === 'gallery') {
      fetchGallery();
    }
  }, [activeSession.mode]);

  const handleDeleteGalleryItem = async (filename: string, e?: React.MouseEvent) => {
    if (e) e.stopPropagation();
    if (!confirm(`画像 "${filename}" を削除してもよろしいですか？`)) return;
    try {
      const res = await fetch(`${BACKEND_URL}/api/gallery/${filename}`, { method: 'DELETE' });
      if (res.ok) {
        setGalleryItems(prev => prev.filter(item => item.filename !== filename));
        if (selectedGalleryItem?.filename === filename) {
          setSelectedGalleryItem(null);
        }
      }
    } catch (err) {
      alert('削除に失敗しました: ' + err);
    }
  };
'''

if "const [galleryItems, setGalleryItems]" not in code:
    code = code.replace(
        "  // Style Training States",
        gallery_hooks + "\n  // Style Training States"
    )

# 5. Add Mode tab button for Gallery
gallery_tab_btn = '''              <button
                className={`mode-tab ${activeSession.mode === 'gallery' ? 'active-gallery' : ''}`}
                onClick={() => updateActiveSession(s => ({ ...s, mode: 'gallery' }))}
                title="今までに作成した画像をすべて閲覧・管理"
              >
                <Grid size={14} color="#38bdf8" />
                <span>🖼️ ギャラリー</span>
              </button>'''

if "active-gallery" not in code:
    code = code.replace(
        "              <button\n                className={`mode-tab ${activeSession.mode === 'bots' ? 'active-bots' : ''}`}",
        gallery_tab_btn + "\n              <button\n                className={`mode-tab ${activeSession.mode === 'bots' ? 'active-bots' : ''}`}"
    )

# 6. Add Gallery View rendering in main content area
gallery_view_render = '''        {/* Gallery View */}
        {activeSession.mode === 'gallery' ? (
          <div className="gallery-container">
            <div className="gallery-header">
              <div className="gallery-title">
                <Grid size={24} color="#38bdf8" />
                <span>作成済み画像ギャラリー ({galleryItems.length} 枚)</span>
              </div>
              <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
                <input
                  type="text"
                  className="gallery-search-input"
                  placeholder="🔍 プロンプトやファイル名で検索..."
                  value={gallerySearch}
                  onChange={(e) => setGallerySearch(e.target.value)}
                />
                <button
                  className="icon-button"
                  onClick={fetchGallery}
                  disabled={isLoadingGallery}
                  title="一覧を更新"
                  style={{ background: 'rgba(56, 189, 248, 0.15)', color: '#38bdf8', border: '1px solid #38bdf8' }}
                >
                  <RefreshCw size={16} className={isLoadingGallery ? 'spin' : ''} />
                </button>
              </div>
            </div>

            {galleryItems.length === 0 ? (
              <div style={{ textAlign: 'center', padding: '60px 20px', color: '#94a3b8' }}>
                <ImageIcon size={48} style={{ opacity: 0.3, margin: '0 auto 16px' }} />
                <h3>まだ保存された画像がありません</h3>
                <p style={{ fontSize: '0.85rem', marginTop: 8 }}>「🎨 プロンプト追求」や「⚡ 高速プレビュー」で画像を作成すると、ここに自動保存されます。</p>
              </div>
            ) : (
              <div className="gallery-grid">
                {galleryItems
                  .filter(item => {
                    if (!gallerySearch.trim()) return true;
                    const q = gallerySearch.toLowerCase();
                    return item.filename.toLowerCase().includes(q) || (item.prompt && item.prompt.toLowerCase().includes(q));
                  })
                  .map(item => (
                    <div
                      key={item.filename}
                      className="gallery-card"
                      onClick={() => setSelectedGalleryItem(item)}
                    >
                      <img
                        src={`${BACKEND_URL}${item.url}`}
                        alt={item.prompt || item.filename}
                        className="gallery-card-img"
                        loading="lazy"
                      />
                      <div className="gallery-card-overlay">
                        {item.prompt && (
                          <div className="gallery-card-prompt" title={item.prompt}>
                            {item.prompt}
                          </div>
                        )}
                        <div className="gallery-card-meta">
                          <span>{item.created_at_iso?.split(' ')[0] || ''}</span>
                          <div style={{ display: 'flex', gap: 6 }}>
                            <a
                              href={`${BACKEND_URL}${item.url}`}
                              download={item.filename}
                              onClick={(e) => e.stopPropagation()}
                              className="icon-btn-micro"
                              title="画像をダウンロード"
                              style={{ color: '#38bdf8' }}
                            >
                              <Download size={13} />
                            </a>
                            <button
                              onClick={(e) => handleDeleteGalleryItem(item.filename, e)}
                              className="icon-btn-micro"
                              title="画像を削除"
                              style={{ color: '#ef4444', background: 'none', border: 'none', cursor: 'pointer' }}
                            >
                              <Trash2 size={13} />
                            </button>
                          </div>
                        </div>
                      </div>
                    </div>
                  ))}
              </div>
            )}

            {/* Gallery Item Detail Modal */}
            {selectedGalleryItem && (
              <div className="gallery-modal-backdrop" onClick={() => setSelectedGalleryItem(null)}>
                <div className="gallery-modal-content" onClick={(e) => e.stopPropagation()}>
                  <div style={{ flex: 1.2, background: '#020617', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16 }}>
                    <img
                      src={`${BACKEND_URL}${selectedGalleryItem.url}`}
                      alt={selectedGalleryItem.prompt || selectedGalleryItem.filename}
                      style={{ maxWidth: '100%', maxHeight: '78vh', objectFit: 'contain', borderRadius: 8 }}
                    />
                  </div>
                  <div style={{ flex: 1, padding: 24, display: 'flex', flexDirection: 'column', gap: 16, overflowY: 'auto' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <h3 style={{ margin: 0, fontSize: '1.1rem', color: '#f8fafc' }}>画像詳細</h3>
                      <button
                        onClick={() => setSelectedGalleryItem(null)}
                        style={{ background: 'none', border: 'none', color: '#94a3b8', cursor: 'pointer' }}
                      >
                        <X size={20} />
                      </button>
                    </div>

                    <div>
                      <label style={{ fontSize: '0.75rem', color: '#94a3b8', fontWeight: 600 }}>プロンプト</label>
                      <div style={{ background: '#1e293b', padding: 12, borderRadius: 8, fontSize: '0.82rem', color: '#e2e8f0', marginTop: 4, lineHeight: 1.4, maxHeight: 160, overflowY: 'auto', userSelect: 'text' }}>
                        {selectedGalleryItem.prompt || '(プロンプト記録なし)'}
                      </div>
                      {selectedGalleryItem.prompt && (
                        <button
                          className="copy-button"
                          style={{ marginTop: 8 }}
                          onClick={() => {
                            navigator.clipboard.writeText(selectedGalleryItem.prompt);
                            alert('プロンプトをクリップボードにコピーしました！');
                          }}
                        >
                          <Copy size={13} /> プロンプトをコピー
                        </button>
                      )}
                    </div>

                    {selectedGalleryItem.negative_prompt && (
                      <div>
                        <label style={{ fontSize: '0.75rem', color: '#94a3b8', fontWeight: 600 }}>除外タグ (Negative Prompt)</label>
                        <div style={{ background: '#1e293b', padding: 10, borderRadius: 8, fontSize: '0.78rem', color: '#cbd5e1', marginTop: 4 }}>
                          {selectedGalleryItem.negative_prompt}
                        </div>
                      </div>
                    )}

                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, fontSize: '0.75rem', color: '#94a3b8', background: 'rgba(255,255,255,0.03)', padding: 12, borderRadius: 8 }}>
                      <div>ファイル名: <span style={{ color: '#f1f5f9' }}>{selectedGalleryItem.filename}</span></div>
                      <div>作成日時: <span style={{ color: '#f1f5f9' }}>{selectedGalleryItem.created_at_iso}</span></div>
                      {selectedGalleryItem.seed !== undefined && <div>シード: <span style={{ color: '#f1f5f9' }}>{selectedGalleryItem.seed}</span></div>}
                      {selectedGalleryItem.steps !== undefined && <div>ステップ: <span style={{ color: '#f1f5f9' }}>{selectedGalleryItem.steps}</span></div>}
                      {selectedGalleryItem.aspect_ratio && <div>比率: <span style={{ color: '#f1f5f9' }}>{selectedGalleryItem.aspect_ratio}</span></div>}
                      {selectedGalleryItem.elapsed_seconds && <div>生成時間: <span style={{ color: '#f1f5f9' }}>{selectedGalleryItem.elapsed_seconds}秒</span></div>}
                    </div>

                    <div style={{ marginTop: 'auto', display: 'flex', gap: 10, flexWrap: 'wrap', paddingTop: 16, borderTop: '1px solid rgba(255,255,255,0.08)' }}>
                      {selectedGalleryItem.prompt && (
                        <button
                          className="action-button primary"
                          style={{ flex: 1, minWidth: 160 }}
                          onClick={() => {
                            const p = selectedGalleryItem.prompt;
                            const neg = selectedGalleryItem.negative_prompt;
                            setSelectedGalleryItem(null);
                            handleSendPromptToGenerator(p, neg);
                          }}
                        >
                          <Sparkles size={16} /> このプロンプトで再生成
                        </button>
                      )}
                      <a
                        href={`${BACKEND_URL}${selectedGalleryItem.url}`}
                        download={selectedGalleryItem.filename}
                        className="action-button secondary"
                        style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', textDecoration: 'none' }}
                      >
                        <Download size={16} /> 保存
                      </a>
                      <button
                        className="action-button danger"
                        onClick={() => handleDeleteGalleryItem(selectedGalleryItem.filename)}
                      >
                        <Trash2 size={16} />
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>
        ) : activeSession.mode === 'bots' ? ('''

if "/* Gallery View */" not in code:
    code = code.replace(
        "        {/* Bot Management View */}\n        {activeSession.mode === 'bots' ? (",
        gallery_view_render
    )

with open(app_path, "w", encoding="utf-8") as f:
    f.write(code)

print("Successfully injected Gallery component and view into App.tsx!")

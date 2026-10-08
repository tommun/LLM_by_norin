import React, { useState, useEffect, useRef } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
  Cpu,
  Send,
  Trash2,
  Sparkles,
  Bot,
  User,
  Activity,
  HardDrive,
  RefreshCw,
  AlertCircle,
  Image as ImageIcon,
  MessageSquare,
  Download,
  X,
  Maximize2,
  Paperclip,
  ThumbsUp,
  ThumbsDown,
  RotateCw,
  Copy,
  Check,
  GitBranch,
  MoreHorizontal,
  Plus,
  Palette,
  Edit2
} from 'lucide-react';
import './style.css';

interface Message {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  images?: string[]; // Attached images for vision
  isImage?: boolean; // True if this was an SD-Turbo generated image
  imageUrl?: string;
  imageMeta?: {
    seed: number;
    steps: number;
    elapsed_seconds: number;
    width?: number;
    height?: number;
    style?: string;
    style_name?: string;
  };
  feedback?: 'like' | 'dislike' | null;
}

type AspectRatio = '1:1' | '16:9' | '9:16' | '4:3' | '3:4';

const ASPECT_RATIO_CONFIG: Record<AspectRatio, { label: string; width: number; height: number; desc: string }> = {
  '1:1': { label: '1:1', width: 512, height: 512, desc: '正方形 (512×512)' },
  '16:9': { label: '16:9', width: 640, height: 360, desc: 'ワイド横長 (640×360)' },
  '9:16': { label: '9:16', width: 360, height: 640, desc: 'スマホ縦長 (360×640)' },
  '4:3': { label: '4:3', width: 576, height: 432, desc: '写真横長 (576×432)' },
  '3:4': { label: '3:4', width: 432, height: 576, desc: 'ポスター縦長 (432×576)' },
};

const STYLE_PRESETS = [
  { key: 'none', name: '標準 (Default)' },
  { key: 'anime', name: 'アニメ調 (Anime / Manga)' },
  { key: 'photorealistic', name: '写実・写真 (Photo)' },
  { key: 'watercolor', name: '水彩画 (Watercolor)' },
  { key: 'oil', name: '油絵 (Oil Painting)' },
  { key: 'cyberpunk', name: 'サイバーパンク (Cyberpunk)' },
  { key: 'pixel', name: 'ピクセルアート (Pixel Art)' },
  { key: '3d', name: '3Dデジタル (3D Render)' },
];

interface ChatSession {
  id: string;
  title: string;
  createdAt: number;
  messages: Message[];
  mode: 'chat' | 'image';
  aspectRatio: AspectRatio;
  style: string;
  loraName?: string;
}

interface GpuStatus {
  cuda_available: boolean;
  device: string;
  device_name: string;
  vram_total_mb: number;
  vram_used_mb: number;
  vram_reserved_mb: number;
  vram_percent: number;
  ram_total_mb: number;
  ram_used_mb: number;
  ram_percent: number;
  model_id: string;
  model_loaded: boolean;
  is_loading: boolean;
  image_model_id?: string;
  image_model_loaded?: boolean;
  image_is_loading?: boolean;
}

const BACKEND_URL = 'http://localhost:8000';
const SESSIONS_STORAGE_KEY = 'norin_llm_sessions_v2';
const ACTIVE_SESSION_STORAGE_KEY = 'norin_llm_active_session_id_v2';

export default function App() {
  // Load sessions from localStorage or initialize with a default one
  const [sessions, setSessions] = useState<ChatSession[]>(() => {
    try {
      const saved = localStorage.getItem(SESSIONS_STORAGE_KEY);
      if (saved) {
        const parsed = JSON.parse(saved);
        if (Array.isArray(parsed) && parsed.length > 0) return parsed;
      }
    } catch {
      // Fallback
    }
    return [{
      id: `session-${Date.now()}`,
      title: '会話 1',
      createdAt: Date.now(),
      messages: [],
      mode: 'chat',
      aspectRatio: '1:1',
      style: 'none',
    }];
  });

  const [activeSessionId, setActiveSessionId] = useState<string>(() => {
    try {
      const saved = localStorage.getItem(ACTIVE_SESSION_STORAGE_KEY);
      if (saved && sessions.some(s => s.id === saved)) return saved;
    } catch {
      // Fallback
    }
    return sessions[0]?.id || `session-${Date.now()}`;
  });

  // Current active session
  const activeSession = sessions.find(s => s.id === activeSessionId) || sessions[0];

  // Save to localStorage whenever sessions change
  useEffect(() => {
    try {
      localStorage.setItem(SESSIONS_STORAGE_KEY, JSON.stringify(sessions));
      localStorage.setItem(ACTIVE_SESSION_STORAGE_KEY, activeSessionId);
    } catch {
      // Ignore quota errors
    }
  }, [sessions, activeSessionId]);

  // UI States
  const [input, setInput] = useState('');
  const [attachments, setAttachments] = useState<string[]>([]);
  const [isGenerating, setIsGenerating] = useState(false);
  const [gpuStatus, setGpuStatus] = useState<GpuStatus | null>(null);
  const [selectedImage, setSelectedImage] = useState<string | null>(null);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [isSyncingGit, setIsSyncingGit] = useState(false);
  const [editingTabId, setEditingTabId] = useState<string | null>(null);
  const [editingTitle, setEditingTitle] = useState('');
  const [availableLoras, setAvailableLoras] = useState<string[]>([]);

  // Settings
  const [systemPrompt, setSystemPrompt] = useState('あなたは親切で有能なAIアシスタントです。画像やテキストの内容を正確に読み取り、分かりやすく日本語で回答してください。');
  const [temperature, setTemperature] = useState(0.7);
  const [maxTokens, setMaxTokens] = useState(1024);
  const [imageSteps, setImageSteps] = useState(1);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [activeSession.messages, isGenerating]);

  // Poll GPU Status & fetch LoRAs
  const fetchGpuStatus = async () => {
    try {
      const res = await fetch(`${BACKEND_URL}/api/gpu`);
      if (res.ok) {
        const data = await res.json();
        setGpuStatus(data);
      }
    } catch {
      // Backend initializing
    }
  };

  const fetchLoras = async () => {
    try {
      const res = await fetch(`${BACKEND_URL}/api/loras`);
      if (res.ok) {
        const data = await res.json();
        setAvailableLoras(data);
      }
    } catch {
      // Ignore
    }
  };

  useEffect(() => {
    fetchGpuStatus();
    fetchLoras();
    const interval = setInterval(fetchGpuStatus, 3000);
    return () => clearInterval(interval);
  }, []);

  // Update active session helper
  const updateActiveSession = (updater: (prev: ChatSession) => ChatSession) => {
    setSessions(prev => prev.map(s => s.id === activeSessionId ? updater(s) : s));
  };

  // Tab management functions
  const handleCreateNewTab = () => {
    const newSession: ChatSession = {
      id: `session-${Date.now()}`,
      title: `会話 ${sessions.length + 1}`,
      createdAt: Date.now(),
      messages: [],
      mode: 'chat',
      aspectRatio: '1:1',
      style: 'none',
    };
    setSessions(prev => [...prev, newSession]);
    setActiveSessionId(newSession.id);
  };

  const handleCloseTab = (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (sessions.length === 1) {
      // If closing the only tab, reset it
      setSessions([{
        id: `session-${Date.now()}`,
        title: '会話 1',
        createdAt: Date.now(),
        messages: [],
        mode: 'chat',
        aspectRatio: '1:1',
        style: 'none',
      }]);
      setActiveSessionId(`session-${Date.now()}`);
      return;
    }

    const filtered = sessions.filter(s => s.id !== id);
    setSessions(filtered);
    if (activeSessionId === id) {
      setActiveSessionId(filtered[filtered.length - 1].id);
    }
  };

  const startRenameTab = (s: ChatSession, e: React.MouseEvent) => {
    e.stopPropagation();
    setEditingTabId(s.id);
    setEditingTitle(s.title);
  };

  const saveRenameTab = () => {
    if (editingTabId && editingTitle.trim()) {
      setSessions(prev => prev.map(s => s.id === editingTabId ? { ...s, title: editingTitle.trim() } : s));
    }
    setEditingTabId(null);
  };

  // Handle Clipboard Image Paste (Ctrl+V)
  const handlePaste = (e: React.ClipboardEvent<HTMLTextAreaElement>) => {
    const items = e.clipboardData?.items;
    if (!items) return;

    for (let i = 0; i < items.length; i++) {
      if (items[i].type.indexOf('image') !== -1) {
        const file = items[i].getAsFile();
        if (file) {
          const reader = new FileReader();
          reader.onload = (event) => {
            if (event.target?.result) {
              setAttachments((prev) => [...prev, event.target!.result as string]);
            }
          };
          reader.readAsDataURL(file);
        }
      }
    }
  };

  // Handle File Input Select
  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files) return;

    Array.from(files).forEach((file) => {
      const reader = new FileReader();
      reader.onload = (event) => {
        if (event.target?.result) {
          setAttachments((prev) => [...prev, event.target!.result as string]);
        }
      };
      reader.readAsDataURL(file);
    });

    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  };

  const removeAttachment = (index: number) => {
    setAttachments((prev) => prev.filter((_, i) => i !== index));
  };

  const downloadImage = (dataUrl: string, prompt: string) => {
    const a = document.createElement('a');
    a.href = dataUrl;
    const sanitizedPrompt = prompt.slice(0, 20).replace(/[^a-zA-Z0-9_\u3000-\u303f\u3040-\u309f\u30a0-\u30ff\uff00-\uffef\u4e00-\u9faf]/g, '_');
    a.download = `gpu_image_${sanitizedPrompt || 'generated'}.png`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  };

  const copyToClipboard = (id: string, text: string) => {
    navigator.clipboard.writeText(text);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 2000);
  };

  const toggleFeedback = (id: string, type: 'like' | 'dislike') => {
    updateActiveSession(s => ({
      ...s,
      messages: s.messages.map(m => m.id === id ? { ...m, feedback: m.feedback === type ? null : type } : m)
    }));
  };

  // Image Generation Handler
  const handleImageGenerate = async (promptText: string) => {
    setIsGenerating(true);
    const userMsg: Message = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: `[画像生成] ${promptText}`
    };
    const placeholderMsg: Message = {
      id: `ai-${Date.now()}`,
      role: 'assistant',
      content: '🎨 画像を生成中... (RTX 4070 Ti で推論実行中)',
      isImage: true
    };

    // Auto rename tab title if default
    updateActiveSession(s => {
      const isDefault = s.title.startsWith('会話 ') || s.title.startsWith('新規');
      return {
        ...s,
        title: isDefault ? (promptText.slice(0, 14) + (promptText.length > 14 ? '...' : '')) : s.title,
        messages: [...s.messages, userMsg, placeholderMsg]
      };
    });

    try {
      const config = ASPECT_RATIO_CONFIG[activeSession.aspectRatio];
      const res = await fetch(`${BACKEND_URL}/api/generate-image`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          prompt: promptText,
          style: activeSession.style,
          lora_name: activeSession.loraName || null,
          lora_weight: 1.0,
          steps: imageSteps,
          guidance_scale: 0.0,
          width: config.width,
          height: config.height
        })
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `Server error: ${res.status}`);
      }

      const data = await res.json();

      updateActiveSession(s => {
        const updated = [...s.messages];
        updated[updated.length - 1] = {
          ...updated[updated.length - 1],
          content: `プロンプト: ${data.prompt}`,
          isImage: true,
          imageUrl: data.image_url,
          imageMeta: {
            seed: data.seed,
            steps: data.steps,
            elapsed_seconds: data.elapsed_seconds,
            width: data.width || config.width,
            height: data.height || config.height,
            style: data.style,
            style_name: data.style_name
          }
        };
        return { ...s, messages: updated };
      });
    } catch (err: any) {
      updateActiveSession(s => {
        const updated = [...s.messages];
        updated[updated.length - 1] = {
          ...updated[updated.length - 1],
          content: `⚠️ 画像生成エラー: ${err.message || '生成に失敗しました'}`
        };
        return { ...s, messages: updated };
      });
    } finally {
      setIsGenerating(false);
      fetchGpuStatus();
    }
  };

  // Chat Streaming Handler (Vision & Text)
  const handleChatStream = async (userText: string, attachedImages: string[]) => {
    const userMsg: Message = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: userText,
      images: attachedImages.length > 0 ? attachedImages : undefined
    };

    const assistantMsgId = `ai-${Date.now()}`;
    const newMessages = [...activeSession.messages, userMsg];

    // Auto rename tab title if default
    updateActiveSession(s => {
      const isDefault = s.title.startsWith('会話 ') || s.title.startsWith('新規');
      return {
        ...s,
        title: isDefault ? (userText.slice(0, 14) + (userText.length > 14 ? '...' : '')) : s.title,
        messages: [...newMessages, { id: assistantMsgId, role: 'assistant', content: '' }]
      };
    });

    setIsGenerating(true);

    const requestPayload = {
      messages: [
        ...(systemPrompt ? [{ role: 'system', content: systemPrompt }] : []),
        ...newMessages.filter((m) => !m.isImage).map((m) => ({
          role: m.role,
          content: m.content,
          images: m.images || null
        }))
      ],
      temperature: temperature,
      max_new_tokens: maxTokens,
      top_p: 0.9
    };

    try {
      const response = await fetch(`${BACKEND_URL}/api/chat/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(requestPayload)
      });

      if (!response.ok) {
        const errJson = await response.json().catch(() => ({}));
        throw new Error(errJson.detail || `Server error: ${response.status}`);
      }

      if (!response.body) throw new Error('No response body returned');

      const reader = response.body.getReader();
      const decoder = new TextDecoder('utf-8');
      let assistantText = '';

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        const chunk = decoder.decode(value, { stream: true });
        const lines = chunk.split('\n');

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const jsonStr = line.slice(6).trim();
            if (!jsonStr) continue;

            try {
              const data = JSON.parse(jsonStr);
              if (data.token) {
                assistantText += data.token;
                updateActiveSession(s => {
                  const updated = [...s.messages];
                  const lastIdx = updated.length - 1;
                  updated[lastIdx] = {
                    ...updated[lastIdx],
                    content: assistantText
                  };
                  return { ...s, messages: updated };
                });
              }
              if (data.done) break;
            } catch {
              // Ignore partial JSON
            }
          }
        }
      }
    } catch (err: any) {
      updateActiveSession(s => {
        const updated = [...s.messages];
        const lastIdx = updated.length - 1;
        updated[lastIdx] = {
          ...updated[lastIdx],
          content: `⚠️ エラーが発生しました: ${err.message || '推論サーバーと通信できませんでした。'}`
        };
        return { ...s, messages: updated };
      });
    } finally {
      setIsGenerating(false);
      fetchGpuStatus();
    }
  };

  // Regenerate last assistant response
  const handleRegenerate = () => {
    if (isGenerating || activeSession.messages.length < 2) return;
    const msgs = activeSession.messages;
    const lastUserIdx = [...msgs].reverse().findIndex((m) => m.role === 'user');
    if (lastUserIdx === -1) return;
    const actualUserIdx = msgs.length - 1 - lastUserIdx;
    const lastUserMsg = msgs[actualUserIdx];

    const trimmed = msgs.slice(0, actualUserIdx);
    updateActiveSession(s => ({ ...s, messages: trimmed }));

    if (lastUserMsg.isImage || lastUserMsg.content.startsWith('[画像生成]')) {
      const cleanPrompt = lastUserMsg.content.replace('[画像生成]', '').trim();
      handleImageGenerate(cleanPrompt);
    } else {
      handleChatStream(lastUserMsg.content, lastUserMsg.images || []);
    }
  };

  // Main Submit Handler
  const handleSubmit = () => {
    if ((!input.trim() && attachments.length === 0) || isGenerating) return;
    const text = input.trim();
    const currentAttachments = [...attachments];
    setInput('');
    setAttachments([]);

    if (activeSession.mode === 'image' || text.startsWith('/image ')) {
      const cleanPrompt = text.startsWith('/image ') ? text.replace('/image ', '').trim() : text;
      handleImageGenerate(cleanPrompt);
    } else {
      handleChatStream(text, currentAttachments);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  // Git Sync Handler
  const handleGitSync = async () => {
    setIsSyncingGit(true);
    try {
      const generatedImages = activeSession.messages
        .filter((m) => m.isImage && m.imageUrl)
        .map((m) => m.imageUrl!);

      const res = await fetch(`${BACKEND_URL}/api/git/sync-outputs`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          image_data_urls: generatedImages,
          commit_message: `feat(outputs): sync ${generatedImages.length} generated images from tab "${activeSession.title}"`
        })
      });

      if (!res.ok) throw new Error('Git sync API failed');
      const data = await res.json();
      alert(`Git同期完了！\n${data.saved_count} 枚の画像を outputs/ に保存して GitHub (main) にプッシュしました。`);
    } catch (err: any) {
      alert(`Git同期エラー: ${err.message}`);
    } finally {
      setIsSyncingGit(false);
    }
  };

  const clearChat = () => {
    updateActiveSession(s => ({ ...s, messages: [] }));
    setAttachments([]);
  };

  return (
    <div className="app-container">
      {/* Sidebar */}
      <aside className="sidebar">
        <div className="sidebar-title">
          <Cpu className="text-emerald-400" size={24} />
          <span>Local GPU Studio</span>
        </div>

        {/* GPU Status Card */}
        <div className="gpu-card">
          <div className="gpu-card-header">
            <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <HardDrive size={14} /> GPU Acceleration
            </span>
            {gpuStatus?.model_loaded ? (
              <span className="status-badge status-ready">
                <span className="pulse-dot" /> Ready
              </span>
            ) : gpuStatus?.is_loading ? (
              <span className="status-badge status-loading">
                <RefreshCw size={12} className="animate-spin" /> Loading
              </span>
            ) : (
              <span className="status-badge status-error">
                <AlertCircle size={12} /> Offline
              </span>
            )}
          </div>

          <div className="gpu-name">
            {gpuStatus?.device_name || 'Detecting GPU...'}
          </div>

          <div className="gpu-metric">
            <div className="gpu-metric-labels">
              <span>VRAM Usage</span>
              <span>
                {gpuStatus
                  ? `${(gpuStatus.vram_reserved_mb / 1024).toFixed(1)} GB / ${(gpuStatus.vram_total_mb / 1024).toFixed(1)} GB (${gpuStatus.vram_percent || 0}%)`
                  : '-- / --'}
              </span>
            </div>
            <div className="progress-bar">
              <div
                className="progress-fill"
                style={{ width: `${Math.min(gpuStatus?.vram_percent || 0, 100)}%` }}
              />
            </div>
          </div>

          <div className="models-list">
            <div className="model-item">
              <span>👁️ Vision LLM:</span>
              <span style={{ color: '#e5e7eb' }}>Qwen2-VL-2B</span>
            </div>
            <div className="model-item">
              <span>🎨 Image Gen:</span>
              <span style={{ color: '#a78bfa' }}>SD-Turbo (Lightning)</span>
            </div>
          </div>
        </div>

        {/* LLM Settings */}
        {activeSession.mode === 'chat' && (
          <>
            <div className="param-group">
              <div className="param-label">
                <span>System Prompt</span>
              </div>
              <textarea
                className="param-textarea"
                value={systemPrompt}
                onChange={(e) => setSystemPrompt(e.target.value)}
                placeholder="AIへの指示や役割を入力..."
                rows={3}
              />
            </div>

            <div className="param-group">
              <div className="param-label">
                <span>Temperature (創造性)</span>
                <span>{temperature.toFixed(2)}</span>
              </div>
              <input
                type="range"
                min="0.0"
                max="1.5"
                step="0.05"
                value={temperature}
                onChange={(e) => setTemperature(parseFloat(e.target.value))}
                className="param-slider"
              />
            </div>

            <div className="param-group">
              <div className="param-label">
                <span>Max New Tokens</span>
                <span>{maxTokens}</span>
              </div>
              <input
                type="range"
                min="128"
                max="2048"
                step="64"
                value={maxTokens}
                onChange={(e) => setMaxTokens(parseInt(e.target.value))}
                className="param-slider"
              />
            </div>
          </>
        )}

        {/* Image Generation Settings */}
        {activeSession.mode === 'image' && (
          <>
            <div className="param-group">
              <div className="param-label">
                <span>画風スタイル (Style)</span>
              </div>
              <select
                className="style-select"
                value={activeSession.style}
                onChange={(e) => updateActiveSession(s => ({ ...s, style: e.target.value }))}
              >
                {STYLE_PRESETS.map((p) => (
                  <option key={p.key} value={p.key}>
                    {p.name}
                  </option>
                ))}
              </select>
            </div>

            {availableLoras.length > 0 && (
              <div className="param-group">
                <div className="param-label">
                  <span>画風学習 LoRA</span>
                </div>
                <select
                  className="style-select"
                  value={activeSession.loraName || ''}
                  onChange={(e) => updateActiveSession(s => ({ ...s, loraName: e.target.value || undefined }))}
                >
                  <option value="">なし (標準)</option>
                  {availableLoras.map((l) => (
                    <option key={l} value={l}>
                      {l}
                    </option>
                  ))}
                </select>
              </div>
            )}

            <div className="param-group">
              <div className="param-label">
                <span>縦横比 (Aspect Ratio)</span>
              </div>
              <div className="aspect-ratio-selector">
                {(Object.keys(ASPECT_RATIO_CONFIG) as AspectRatio[]).map((ratio) => (
                  <button
                    key={ratio}
                    type="button"
                    className={`aspect-ratio-btn ${activeSession.aspectRatio === ratio ? 'active' : ''}`}
                    onClick={() => updateActiveSession(s => ({ ...s, aspectRatio: ratio }))}
                  >
                    {ratio}
                  </button>
                ))}
              </div>
              <div className="aspect-ratio-info">
                <span>{ASPECT_RATIO_CONFIG[activeSession.aspectRatio].desc}</span>
              </div>
            </div>

            <div className="param-group">
              <div className="param-label">
                <span>Inference Steps</span>
                <span>{imageSteps} Step(s)</span>
              </div>
              <input
                type="range"
                min="1"
                max="4"
                step="1"
                value={imageSteps}
                onChange={(e) => setImageSteps(parseInt(e.target.value))}
                className="param-slider image-accent"
              />
              <span style={{ fontSize: '0.75rem', color: '#9ca3af' }}>
                SD-Turboは1ステップで最高速（約0.5秒）に生成されます。
              </span>
            </div>
          </>
        )}

        {/* Action Buttons */}
        <div className="sidebar-actions">
          <button
            onClick={handleGitSync}
            disabled={isSyncingGit}
            className="git-sync-btn"
            title="生成画像をGitへ保存してプッシュ"
          >
            <GitBranch size={16} />
            <span>{isSyncingGit ? 'Git同期中...' : '生成画像をGitへプッシュ'}</span>
          </button>

          <button onClick={clearChat} className="clear-btn" title="会話履歴をクリア">
            <Trash2 size={16} />
            <span>履歴をクリア</span>
          </button>
        </div>
      </aside>

      {/* Main Chat Area */}
      <main className="chat-main">
        {/* Header */}
        <header className="chat-header">
          <div className="chat-title">
            <Sparkles size={20} color={activeSession.mode === 'chat' ? '#10b981' : '#8b5cf6'} />
            <span>Vision LLM & Image Studio (RTX 4070 Ti)</span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: '0.85rem', color: '#9ca3af' }}>
            <Activity size={16} color="#3b82f6" />
            <span>Multimodal Vision + ADD Diffusion</span>
          </div>
        </header>

        {/* Conversation Tabs Bar */}
        <div className="tabs-bar">
          {sessions.map((s) => (
            <div
              key={s.id}
              className={`tab-item ${s.id === activeSessionId ? 'active' : ''}`}
              onClick={() => setActiveSessionId(s.id)}
            >
              {editingTabId === s.id ? (
                <input
                  type="text"
                  value={editingTitle}
                  onChange={(e) => setEditingTitle(e.target.value)}
                  onBlur={saveRenameTab}
                  onKeyDown={(e) => e.key === 'Enter' && saveRenameTab()}
                  autoFocus
                  style={{
                    background: 'var(--bg-tertiary)',
                    border: '1px solid #3b82f6',
                    color: 'white',
                    fontSize: '0.8rem',
                    padding: '2px 4px',
                    borderRadius: '4px',
                    outline: 'none',
                    width: '100px'
                  }}
                  onClick={(e) => e.stopPropagation()}
                />
              ) : (
                <span
                  className="tab-title"
                  onDoubleClick={(e) => startRenameTab(s, e)}
                  title="ダブルクリックでタイトルを変更"
                >
                  {s.mode === 'image' ? '🎨 ' : '💬 '}
                  {s.title}
                </span>
              )}

              <button
                className="tab-close-btn"
                onClick={(e) => handleCloseTab(s.id, e)}
                title="タブを閉じる"
              >
                ×
              </button>
            </div>
          ))}

          <button
            className="tab-new-btn"
            onClick={handleCreateNewTab}
            title="新しい会話タブを作成"
          >
            <Plus size={14} />
            <span>新しいタブ</span>
          </button>
        </div>

        {/* Messages */}
        <div className="chat-messages">
          {activeSession.messages.length === 0 ? (
            <div className="empty-chat">
              {activeSession.mode === 'chat' ? (
                <Bot className="empty-icon" />
              ) : (
                <ImageIcon className="empty-icon" style={{ color: '#8b5cf6' }} />
              )}
              <h3>
                {activeSession.mode === 'chat'
                  ? 'マルチモーダル Vision AI アシスタント'
                  : '高速ローカル画像生成スタジオ'}
              </h3>
              <p>
                {activeSession.mode === 'chat'
                  ? 'テキストの会話はもちろん、画像を貼り付け（Ctrl+V）または添付すると、AIが画像を視覚的に認識して解説します。'
                  : 'SD-Turbo を使用し、RTX 4070 Ti の圧倒的なパワーでわずか1秒未満で画像を生成します。'}
              </p>
              <p style={{ fontSize: '0.85rem' }}>
                {activeSession.mode === 'chat'
                  ? '下のクリップボタンまたは Ctrl+V でスクリーンショットを直接貼り付けて質問できます。'
                  : '生成したい画像のプロンプトを入力してください。画風や縦横比も選べます。'}
              </p>
            </div>
          ) : (
            activeSession.messages.map((msg) => (
              <div key={msg.id} className={`message-row ${msg.role === 'user' ? 'user' : 'ai'}`}>
                {msg.role !== 'user' && (
                  <div className={`message-avatar ${msg.isImage ? 'avatar-image-ai' : 'avatar-ai'}`}>
                    {msg.isImage ? <ImageIcon size={18} /> : <Bot size={18} />}
                  </div>
                )}

                <div className="message-content-wrapper">
                  {/* User Attached Images */}
                  {msg.role === 'user' && msg.images && msg.images.length > 0 && (
                    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
                      {msg.images.map((img, i) => (
                        <img
                          key={i}
                          src={img}
                          alt="Attached"
                          className="user-attached-image"
                          onClick={() => setSelectedImage(img)}
                          title="クリックして拡大"
                        />
                      ))}
                    </div>
                  )}

                  <div className="message-bubble">
                    {msg.role === 'user' ? (
                      msg.content
                    ) : msg.isImage && msg.imageUrl ? (
                      <div className="generated-image-card">
                        <img
                          src={msg.imageUrl}
                          alt="Generated"
                          className="image-preview"
                          onClick={() => setSelectedImage(msg.imageUrl || null)}
                          title="クリックして拡大"
                        />
                        <div className="image-meta-bar">
                          <span>
                            ⏱️ {msg.imageMeta?.elapsed_seconds}s | {msg.imageMeta?.width}×{msg.imageMeta?.height} | {msg.imageMeta?.style_name || '標準'}
                          </span>
                          <div style={{ display: 'flex', gap: 6 }}>
                            <button
                              className="image-download-btn"
                              onClick={() => setSelectedImage(msg.imageUrl || null)}
                              title="拡大表示"
                            >
                              <Maximize2 size={13} />
                            </button>
                            <button
                              className="image-download-btn"
                              onClick={() => downloadImage(msg.imageUrl!, msg.content)}
                              title="保存"
                            >
                              <Download size={13} /> 保存
                            </button>
                          </div>
                        </div>
                      </div>
                    ) : (
                      <>
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>
                          {msg.content}
                        </ReactMarkdown>
                        {isGenerating && msg.id === activeSession.messages[activeSession.messages.length - 1]?.id && (
                          <span className="cursor-blink" />
                        )}
                      </>
                    )}
                  </div>

                  {/* AI Response Action Toolbar */}
                  {msg.role === 'assistant' && !msg.isImage && msg.content && (
                    <div className="message-action-bar">
                      <button
                        className={`action-btn ${msg.feedback === 'like' ? 'active' : ''}`}
                        onClick={() => toggleFeedback(msg.id, 'like')}
                        title="良い回答"
                      >
                        <ThumbsUp size={14} />
                      </button>
                      <button
                        className={`action-btn ${msg.feedback === 'dislike' ? 'active' : ''}`}
                        onClick={() => toggleFeedback(msg.id, 'dislike')}
                        title="不適切な回答"
                      >
                        <ThumbsDown size={14} />
                      </button>
                      <button
                        className="action-btn"
                        onClick={handleRegenerate}
                        title="再生成"
                        disabled={isGenerating}
                      >
                        <RotateCw size={14} />
                      </button>
                      <button
                        className="action-btn"
                        onClick={() => copyToClipboard(msg.id, msg.content)}
                        title="回答をコピー"
                      >
                        {copiedId === msg.id ? <Check size={14} color="#10b981" /> : <Copy size={14} />}
                      </button>
                      <button className="action-btn" title="詳細オプション">
                        <MoreHorizontal size={14} />
                      </button>
                    </div>
                  )}
                </div>

                {msg.role === 'user' && (
                  <div className="message-avatar avatar-user">
                    <User size={18} />
                  </div>
                )}
              </div>
            ))
          )}
          <div ref={messagesEndRef} />
        </div>

        {/* Input Form Area */}
        <div className="chat-input-container">
          {/* Mode Switch Tabs & Controls */}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 8 }}>
            <div className="mode-tabs">
              <button
                className={`mode-tab ${activeSession.mode === 'chat' ? 'active-chat' : ''}`}
                onClick={() => updateActiveSession(s => ({ ...s, mode: 'chat' }))}
              >
                <MessageSquare size={14} />
                <span>対話 & 画像認識</span>
              </button>
              <button
                className={`mode-tab ${activeSession.mode === 'image' ? 'active-image' : ''}`}
                onClick={() => updateActiveSession(s => ({ ...s, mode: 'image' }))}
              >
                <ImageIcon size={14} />
                <span>画像生成 (SD-Turbo)</span>
              </button>
            </div>

            {activeSession.mode === 'image' && (
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                {/* Style Preset Selector */}
                <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                  <Palette size={14} color="#c4b5fd" />
                  <select
                    className="style-select"
                    value={activeSession.style}
                    onChange={(e) => updateActiveSession(s => ({ ...s, style: e.target.value }))}
                    style={{ padding: '3px 6px', fontSize: '0.75rem' }}
                  >
                    {STYLE_PRESETS.map((p) => (
                      <option key={p.key} value={p.key}>
                        {p.name}
                      </option>
                    ))}
                  </select>
                </div>

                {/* Aspect Ratio Selector */}
                <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                  <span style={{ fontSize: '0.75rem', color: '#9ca3af' }}>比率:</span>
                  <div style={{ display: 'flex', gap: 3 }}>
                    {(Object.keys(ASPECT_RATIO_CONFIG) as AspectRatio[]).map((ratio) => (
                      <button
                        key={ratio}
                        type="button"
                        className={`aspect-ratio-btn ${activeSession.aspectRatio === ratio ? 'active' : ''}`}
                        onClick={() => updateActiveSession(s => ({ ...s, aspectRatio: ratio }))}
                        style={{ padding: '3px 6px', fontSize: '0.75rem', minWidth: '40px' }}
                        title={ASPECT_RATIO_CONFIG[ratio].desc}
                      >
                        {ratio}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* Attachment Preview Chips */}
          {attachments.length > 0 && (
            <div className="attachment-preview-bar">
              <span style={{ fontSize: '0.8rem', color: '#9ca3af' }}>添付画像 ({attachments.length}):</span>
              {attachments.map((att, i) => (
                <div key={i} className="attachment-chip">
                  <img src={att} alt="Thumb" className="attachment-thumb" />
                  <button
                    className="attachment-remove-btn"
                    onClick={() => removeAttachment(i)}
                    title="削除"
                  >
                    ×
                  </button>
                </div>
              ))}
            </div>
          )}

          <div className={`chat-input-box ${activeSession.mode === 'image' ? 'image-mode-focus' : ''}`}>
            {/* Attachment Button for Vision Mode */}
            {activeSession.mode === 'chat' && (
              <>
                <button
                  type="button"
                  className="attach-btn"
                  onClick={() => fileInputRef.current?.click()}
                  title="画像を添付 (または直接Ctrl+Vで貼り付け)"
                >
                  <Paperclip size={18} />
                </button>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept="image/*"
                  multiple
                  style={{ display: 'none' }}
                  onChange={handleFileSelect}
                />
              </>
            )}

            <textarea
              ref={textareaRef}
              className="chat-textarea"
              placeholder={
                activeSession.mode === 'image'
                  ? '生成したい画像のプロンプトを入力 (英語推奨, 画風と比率は上で選択可能)...'
                  : 'メッセージを入力... (画像はCtrl+Vで貼り付け可能 / Shift+Enterで改行)'
              }
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              onPaste={handlePaste}
              rows={2}
            />
            <button
              className={`send-button ${activeSession.mode === 'image' ? 'image-send' : ''}`}
              onClick={handleSubmit}
              disabled={isGenerating || (!input.trim() && attachments.length === 0) || gpuStatus?.is_loading}
              title={activeSession.mode === 'image' ? '画像を生成' : 'メッセージ送信'}
            >
              {activeSession.mode === 'image' ? <ImageIcon size={18} /> : <Send size={18} />}
            </button>
          </div>

          <div className="input-footer">
            <span>Powered by PyTorch CUDA & Qwen2-VL (Multimodal) + SD-Turbo</span>
            <span>Target GPU: GeForce RTX 4070 Ti (12GB)</span>
          </div>
        </div>
      </main>

      {/* Image Preview Modal */}
      {selectedImage && (
        <div className="modal-overlay" onClick={() => setSelectedImage(null)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <button className="modal-close-btn" onClick={() => setSelectedImage(null)}>
              <X size={24} />
            </button>
            <img src={selectedImage} alt="Enlarged" className="modal-image" />
          </div>
        </div>
      )}
    </div>
  );
}

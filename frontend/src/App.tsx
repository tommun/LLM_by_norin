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
  Maximize2
} from 'lucide-react';
import './style.css';

interface Message {
  role: 'user' | 'assistant' | 'system';
  content: string;
  isImage?: boolean;
  imageUrl?: string;
  imageMeta?: {
    seed: number;
    steps: number;
    elapsed_seconds: number;
  };
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

export default function App() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [isGenerating, setIsGenerating] = useState(false);
  const [gpuStatus, setGpuStatus] = useState<GpuStatus | null>(null);
  const [mode, setMode] = useState<'chat' | 'image'>('chat');
  const [selectedImage, setSelectedImage] = useState<string | null>(null);

  // Settings
  const [systemPrompt, setSystemPrompt] = useState('あなたは親切で有能なAIアシスタントです。質問に対して分かりやすく日本語で回答してください。');
  const [temperature, setTemperature] = useState(0.7);
  const [maxTokens, setMaxTokens] = useState(1024);
  const [imageSteps, setImageSteps] = useState(1);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Auto scroll to bottom
  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, isGenerating]);

  // Poll GPU Status
  const fetchGpuStatus = async () => {
    try {
      const res = await fetch(`${BACKEND_URL}/api/gpu`);
      if (res.ok) {
        const data = await res.json();
        setGpuStatus(data);
      }
    } catch {
      // Backend might be initializing
    }
  };

  useEffect(() => {
    fetchGpuStatus();
    const interval = setInterval(fetchGpuStatus, 3000);
    return () => clearInterval(interval);
  }, []);

  // Download image helper
  const downloadImage = (dataUrl: string, prompt: string) => {
    const a = document.createElement('a');
    a.href = dataUrl;
    const sanitizedPrompt = prompt.slice(0, 20).replace(/[^a-zA-Z0-9_\u3000-\u303f\u3040-\u309f\u30a0-\u30ff\uff00-\uffef\u4e00-\u9faf]/g, '_');
    a.download = `gpu_image_${sanitizedPrompt || 'generated'}.png`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  };

  // Image Generation Handler
  const handleImageGenerate = async (promptText: string) => {
    setIsGenerating(true);
    const userMsg: Message = { role: 'user', content: `[画像生成] ${promptText}` };
    const placeholderMsg: Message = {
      role: 'assistant',
      content: '🎨 画像を生成中... (RTX 4070 Ti で推論実行中)',
      isImage: true
    };

    setMessages((prev) => [...prev, userMsg, placeholderMsg]);

    try {
      const res = await fetch(`${BACKEND_URL}/api/generate-image`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          prompt: promptText,
          steps: imageSteps,
          guidance_scale: 0.0,
          width: 512,
          height: 512
        })
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `Server error: ${res.status}`);
      }

      const data = await res.json();

      setMessages((prev) => {
        const updated = [...prev];
        updated[updated.length - 1] = {
          role: 'assistant',
          content: `プロンプト: ${data.prompt}`,
          isImage: true,
          imageUrl: data.image_url,
          imageMeta: {
            seed: data.seed,
            steps: data.steps,
            elapsed_seconds: data.elapsed_seconds
          }
        };
        return updated;
      });
    } catch (err: any) {
      setMessages((prev) => {
        const updated = [...prev];
        updated[updated.length - 1] = {
          role: 'assistant',
          content: `⚠️ 画像生成エラー: ${err.message || '生成に失敗しました'}`
        };
        return updated;
      });
    } finally {
      setIsGenerating(false);
      fetchGpuStatus();
    }
  };

  // Chat Streaming Handler
  const handleChatStream = async (userText: string) => {
    const newMessages: Message[] = [
      ...messages,
      { role: 'user', content: userText }
    ];

    setMessages(newMessages);
    setIsGenerating(true);
    setMessages((prev) => [...prev, { role: 'assistant', content: '' }]);

    const requestPayload = {
      messages: [
        ...(systemPrompt ? [{ role: 'system', content: systemPrompt }] : []),
        ...newMessages.filter((m) => !m.isImage)
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
                setMessages((prev) => {
                  const updated = [...prev];
                  updated[updated.length - 1] = {
                    role: 'assistant',
                    content: assistantText
                  };
                  return updated;
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
      setMessages((prev) => {
        const updated = [...prev];
        updated[updated.length - 1] = {
          role: 'assistant',
          content: `⚠️ エラーが発生しました: ${err.message || '推論サーバーと通信できませんでした。'}`
        };
        return updated;
      });
    } finally {
      setIsGenerating(false);
      fetchGpuStatus();
    }
  };

  // Main Submit Handler
  const handleSubmit = () => {
    if (!input.trim() || isGenerating) return;
    const text = input.trim();
    setInput('');

    // Check if input is image command or currently in image mode
    if (mode === 'image' || text.startsWith('/image ')) {
      const cleanPrompt = text.startsWith('/image ') ? text.replace('/image ', '').trim() : text;
      handleImageGenerate(cleanPrompt);
    } else {
      handleChatStream(text);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const clearChat = () => {
    setMessages([]);
  };

  return (
    <div className="app-container">
      {/* Sidebar */}
      <aside className="sidebar">
        <div className="sidebar-title">
          <Cpu className="text-emerald-400" size={24} />
          <span>Local GPU Engine</span>
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
              <span>💬 LLM:</span>
              <span style={{ color: '#e5e7eb' }}>Qwen2.5-3B-Instruct</span>
            </div>
            <div className="model-item">
              <span>🎨 Image:</span>
              <span style={{ color: '#a78bfa' }}>SD-Turbo (Lightning)</span>
            </div>
          </div>
        </div>

        {/* LLM Settings */}
        {mode === 'chat' && (
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
        {mode === 'image' && (
          <>
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
                SD-Turboは1〜2ステップで最高画質・超高速（1秒未満）に生成されます。
              </span>
            </div>

            <div className="param-group">
              <div className="param-label">
                <span>Resolution</span>
                <span>512 x 512 px</span>
              </div>
            </div>
          </>
        )}

        {/* Clear Chat Button */}
        <button onClick={clearChat} className="clear-btn" title="会話履歴をクリア">
          <Trash2 size={16} />
          <span>履歴をクリア</span>
        </button>
      </aside>

      {/* Main Chat Area */}
      <main className="chat-main">
        {/* Header */}
        <header className="chat-header">
          <div className="chat-title">
            <Sparkles size={20} color={mode === 'chat' ? '#10b981' : '#8b5cf6'} />
            <span>LLM & Image Studio by norin (RTX 4070 Ti)</span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: '0.85rem', color: '#9ca3af' }}>
            <Activity size={16} color="#3b82f6" />
            <span>Dual Model Acceleration: LLM + Diffusion</span>
          </div>
        </header>

        {/* Messages Container */}
        <div className="chat-messages">
          {messages.length === 0 ? (
            <div className="empty-chat">
              {mode === 'chat' ? <Bot className="empty-icon" /> : <ImageIcon className="empty-icon" style={{ color: '#8b5cf6' }} />}
              <h3>
                {mode === 'chat'
                  ? 'ローカルGPUアシスタントへようこそ'
                  : 'ローカル画像生成スタジオへようこそ'}
              </h3>
              <p>
                {mode === 'chat'
                  ? 'GeForce RTX 4070 Ti (12GB) を使用し、完全ローカルで高速なテキスト生成を行います。'
                  : 'SD-Turbo を使用し、RTX 4070 Ti の圧倒的なパワーでわずか1秒で高精細な画像を生成します。'}
              </p>
              <p style={{ fontSize: '0.85rem' }}>
                {mode === 'chat'
                  ? '下の入力欄にメッセージを入力してください。「/image <内容>」で直接画像生成も可能です。'
                  : '生成したい画像のプロンプトを入力してください (例: A futuristic cyberpunk city with neon lights, 8k resolution)。'}
              </p>
            </div>
          ) : (
            messages.map((msg, idx) => (
              <div key={idx} className={`message-row ${msg.role === 'user' ? 'user' : 'ai'}`}>
                {msg.role !== 'user' && (
                  <div className={`message-avatar ${msg.isImage ? 'avatar-image-ai' : 'avatar-ai'}`}>
                    {msg.isImage ? <ImageIcon size={18} /> : <Bot size={18} />}
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
                          ⏱️ {msg.imageMeta?.elapsed_seconds}s | Steps: {msg.imageMeta?.steps} | Seed: {msg.imageMeta?.seed}
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
                      {isGenerating && idx === messages.length - 1 && (
                        <span className="cursor-blink" />
                      )}
                    </>
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
          {/* Mode Switch Tabs */}
          <div className="mode-tabs">
            <button
              className={`mode-tab ${mode === 'chat' ? 'active-chat' : ''}`}
              onClick={() => setMode('chat')}
            >
              <MessageSquare size={14} />
              <span>テキスト対話</span>
            </button>
            <button
              className={`mode-tab ${mode === 'image' ? 'active-image' : ''}`}
              onClick={() => setMode('image')}
            >
              <ImageIcon size={14} />
              <span>画像生成 (SD-Turbo)</span>
            </button>
          </div>

          <div className={`chat-input-box ${mode === 'image' ? 'image-mode-focus' : ''}`}>
            <textarea
              ref={textareaRef}
              className="chat-textarea"
              placeholder={
                mode === 'image'
                  ? '生成したい画像のプロンプトを入力 (英語推奨, 例: A majestic dragon flying over mountains, cinematic lighting)...'
                  : 'メッセージを入力... (Shift+Enterで改行, Enterで送信)'
              }
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              rows={2}
            />
            <button
              className={`send-button ${mode === 'image' ? 'image-send' : ''}`}
              onClick={handleSubmit}
              disabled={isGenerating || !input.trim() || gpuStatus?.is_loading}
              title={mode === 'image' ? '画像を生成' : 'メッセージ送信'}
            >
              {mode === 'image' ? <ImageIcon size={18} /> : <Send size={18} />}
            </button>
          </div>

          <div className="input-footer">
            <span>Powered by PyTorch CUDA & Diffusers (SD-Turbo) + Qwen2.5</span>
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

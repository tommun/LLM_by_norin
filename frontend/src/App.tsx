import React, { useState, useEffect, useRef } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
  Cpu,
  Send,
  Trash2,
  Sliders,
  Sparkles,
  Bot,
  User,
  Activity,
  HardDrive,
  RefreshCw,
  AlertCircle
} from 'lucide-react';
import './style.css';

interface Message {
  role: 'user' | 'assistant' | 'system';
  content: string;
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
}

const BACKEND_URL = 'http://localhost:8000';

export default function App() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [isGenerating, setIsGenerating] = useState(false);
  const [gpuStatus, setGpuStatus] = useState<GpuStatus | null>(null);
  
  // Settings
  const [systemPrompt, setSystemPrompt] = useState('あなたは親切で有能なAIアシスタントです。質問に対して分かりやすく日本語で回答してください。');
  const [temperature, setTemperature] = useState(0.7);
  const [maxTokens, setMaxTokens] = useState(1024);
  const [showSettings, setShowSettings] = useState(true);

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
      // Backend might still be starting up
    }
  };

  useEffect(() => {
    fetchGpuStatus();
    const interval = setInterval(fetchGpuStatus, 3000);
    return () => clearInterval(interval);
  }, []);

  // Send message and stream response
  const handleSend = async () => {
    if (!input.trim() || isGenerating) return;

    const userText = input.trim();
    setInput('');

    // Build context messages
    const newMessages: Message[] = [
      ...messages,
      { role: 'user', content: userText }
    ];

    setMessages(newMessages);
    setIsGenerating(true);

    // Placeholder for assistant streaming output
    setMessages((prev) => [...prev, { role: 'assistant', content: '' }]);

    const requestPayload = {
      messages: [
        ...(systemPrompt ? [{ role: 'system', content: systemPrompt }] : []),
        ...newMessages
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

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
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

          <div style={{ marginTop: 12, fontSize: '0.8rem', color: '#9ca3af' }}>
            <span style={{ fontWeight: 600 }}>Active Model:</span>
            <div style={{ color: '#e5e7eb', marginTop: 2, wordBreak: 'break-all' }}>
              {gpuStatus?.model_id || 'Qwen/Qwen2.5-3B-Instruct'}
            </div>
          </div>
        </div>

        {/* Hyperparameters Controls */}
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

        {/* Clear Chat Button */}
        <button onClick={clearChat} className="clear-btn" title="会話履歴をクリア">
          <Trash2 size={16} />
          <span>チャット履歴をクリア</span>
        </button>
      </aside>

      {/* Main Chat Area */}
      <main className="chat-main">
        {/* Header */}
        <header className="chat-header">
          <div className="chat-title">
            <Sparkles size={20} color="#10b981" />
            <span>LLM by norin - GeForce RTX 4070 Ti Edition</span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: '0.85rem', color: '#9ca3af' }}>
            <Activity size={16} color="#3b82f6" />
            <span>High-Speed Local CUDA Inference</span>
          </div>
        </header>

        {/* Messages */}
        <div className="chat-messages">
          {messages.length === 0 ? (
            <div className="empty-chat">
              <Bot className="empty-icon" />
              <h3>ローカルGPU推論アシスタントへようこそ</h3>
              <p>搭載されている RTX 4070 Ti (12GB VRAM) を使用して、端末内で完全にオフライン・高速推論を実行します。</p>
              <p style={{ fontSize: '0.85rem' }}>下の入力欄からメッセージを送信してください。</p>
            </div>
          ) : (
            messages.map((msg, idx) => (
              <div key={idx} className={`message-row ${msg.role === 'user' ? 'user' : 'ai'}`}>
                {msg.role !== 'user' && (
                  <div className="message-avatar avatar-ai">
                    <Bot size={18} />
                  </div>
                )}
                <div className="message-bubble">
                  {msg.role === 'user' ? (
                    msg.content
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

        {/* Input Area */}
        <div className="chat-input-container">
          <div className="chat-input-box">
            <textarea
              ref={textareaRef}
              className="chat-textarea"
              placeholder={
                gpuStatus?.is_loading
                  ? 'GPUへモデルをロード中です... 少々お待ちください'
                  : 'メッセージを入力... (Shift+Enterで改行, Enterで送信)'
              }
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              rows={2}
            />
            <button
              className="send-button"
              onClick={handleSend}
              disabled={isGenerating || !input.trim() || gpuStatus?.is_loading}
              title="送信"
            >
              <Send size={18} />
            </button>
          </div>
          <div className="input-footer">
            <span>Powered by PyTorch CUDA & Hugging Face Transformers</span>
            <span>Target GPU: RTX 4070 Ti</span>
          </div>
        </div>
      </main>
    </div>
  );
}

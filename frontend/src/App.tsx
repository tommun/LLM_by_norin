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
  Edit2,
  GraduationCap,
  FolderUp,
  Play,
  Square,
  Folder,
  Wand2
} from 'lucide-react';
import './style.css';

interface Message {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  images?: string[]; // Attached images for vision
  isImage?: boolean; // True if this was an AI-generated image
  imageUrl?: string;
  imageMeta?: {
    seed: number;
    steps: number;
    elapsed_seconds: number;
    width?: number;
    height?: number;
    style?: string;
    style_name?: string;
    enhanced_prompt?: string;
    final_prompt?: string;
    lora_name?: string;
    lora_scale?: number;
    guidance_scale?: number;
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

const HQ_ASPECT_RATIO_CONFIG: Record<AspectRatio, { label: string; width: number; height: number; desc: string }> = {
  '1:1': { label: '1:1', width: 1024, height: 1024, desc: '高精細正方形 (1024×1024)' },
  '16:9': { label: '16:9', width: 1216, height: 832, desc: 'シネマ横長 (1216×832)' },
  '9:16': { label: '9:16', width: 832, height: 1216, desc: 'スマホ縦長 (832×1216)' },
  '4:3': { label: '4:3', width: 1152, height: 896, desc: '写真横長 (1152×896)' },
  '3:4': { label: '3:4', width: 896, height: 1152, desc: 'ポスター縦長 (896×1152)' },
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

export interface BotConfig {
  id: string;
  name: string;
  description: string;
  category: string;
  avatar: string;
  avatar_image: string;
  system_prompt: string;
  greeting: string;
  quick_prompts: string[];
  is_preset?: boolean;
}

interface ChatSession {
  id: string;
  title: string;
  createdAt: number;
  messages: Message[];
  mode: 'chat' | 'image' | 'train' | 'bots' | 'prompt_master' | 'style_master';
  aspectRatio: AspectRatio;
  style: string;
  loraName?: string;
  botId?: string;
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
  hq_model_id?: string;
  hq_model_loaded?: boolean;
  hq_is_loading?: boolean;
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

  // Style Training States
  const [trainStyleName, setTrainStyleName] = useState('');
  const [trainSteps, setTrainSteps] = useState(300);
  const [trainAutoCaption, setTrainAutoCaption] = useState(true);
  const [trainImages, setTrainImages] = useState<string[]>([]);
  const [datasets, setDatasets] = useState<any[]>([]);
  const [trainingStatus, setTrainingStatus] = useState<any>(null);
  const [isUploadingDataset, setIsUploadingDataset] = useState(false);
  const trainFileInputRef = useRef<HTMLInputElement>(null);

  // Bot Management States
  const [bots, setBots] = useState<BotConfig[]>([]);
  const [isEditingBot, setIsEditingBot] = useState(false);
  const [editingBot, setEditingBot] = useState<Partial<BotConfig>>({
    name: '',
    description: '',
    category: 'カスタム',
    avatar: '🤖',
    avatar_image: '',
    system_prompt: '',
    greeting: '',
    quick_prompts: []
  });
  const [quickPromptInput, setQuickPromptInput] = useState('');
  const [isGeneratingAvatar, setIsGeneratingAvatar] = useState(false);
  const [botCategoryFilter, setBotCategoryFilter] = useState<string>('all');

  // High-Quality Generation States (Prompt Master & Style Master)
  const [hqSteps, setHqSteps] = useState(30);
  const [hqGuidanceScale, setHqGuidanceScale] = useState(7.5);
  const [hqEnhancePrompt, setHqEnhancePrompt] = useState(true);
  const [hqLoraScale, setHqLoraScale] = useState(0.8);
  const [hqNegativePrompt, setHqNegativePrompt] = useState('');
  const [enhancedPromptPreview, setEnhancedPromptPreview] = useState<string | null>(null);
  const [isEnhancingPrompt, setIsEnhancingPrompt] = useState(false);

  // Derived Bot values
  const currentBot = bots.find(b => b.id === activeSession.botId);
  const filteredBots = botCategoryFilter === 'all' ? bots : bots.filter(b => b.category === botCategoryFilter);

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

  const fetchDatasets = async () => {
    try {
      const res = await fetch(`${BACKEND_URL}/api/train/datasets`);
      if (res.ok) {
        const data = await res.json();
        setDatasets(data.datasets || []);
      }
    } catch {
      // Ignore
    }
  };

  const fetchTrainingStatus = async () => {
    try {
      const res = await fetch(`${BACKEND_URL}/api/train/status`);
      if (res.ok) {
        const data = await res.json();
        setTrainingStatus(data);
        if (!data.is_training && data.saved_lora_path) {
          fetchLoras(); // Refresh LoRAs once training finishes
        }
      }
    } catch {
      // Ignore
    }
  };

  // Poll training status if training is in progress
  useEffect(() => {
    let interval: any = null;
    if (trainingStatus?.is_training) {
      interval = setInterval(fetchTrainingStatus, 1000);
    } else {
      interval = setInterval(fetchTrainingStatus, 3000);
    }
    return () => {
      if (interval) clearInterval(interval);
    };
  }, [trainingStatus?.is_training]);

  useEffect(() => {
    fetchDatasets();
    fetchTrainingStatus();
    fetchBots();
  }, []);

  const fetchBots = async () => {
    try {
      const res = await fetch(`${BACKEND_URL}/api/bots`);
      if (res.ok) {
        const data = await res.json();
        setBots(data.bots || []);
      }
    } catch {
      // Ignore
    }
  };

  const handleSaveBot = async () => {
    if (!editingBot.name?.trim() || !editingBot.system_prompt?.trim()) {
      alert('ボットの名前と役割（システムプロンプト）は必須です。');
      return;
    }
    try {
      const res = await fetch(`${BACKEND_URL}/api/bots`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(editingBot)
      });
      if (res.ok) {
        setIsEditingBot(false);
        fetchBots();
      } else {
        const err = await res.json();
        alert(`保存失敗: ${err.detail || 'エラー'}`);
      }
    } catch (e: any) {
      alert(`通信エラー: ${e.message}`);
    }
  };

  const handleDeleteBot = async (botId: string) => {
    if (!confirm('このボットを削除してもよろしいですか？')) return;
    try {
      const res = await fetch(`${BACKEND_URL}/api/bots/${botId}`, { method: 'DELETE' });
      if (res.ok) {
        fetchBots();
      } else {
        const err = await res.json();
        alert(err.detail || '削除に失敗しました');
      }
    } catch (e: any) {
      alert(`通信エラー: ${e.message}`);
    }
  };

  const handleGenerateBotAvatar = async () => {
    if (!editingBot.name?.trim()) {
      alert('ボットの名前を先に入力してください。');
      return;
    }
    setIsGeneratingAvatar(true);
    try {
      const res = await fetch(`${BACKEND_URL}/api/bots/generate-avatar`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: editingBot.name,
          prompt: editingBot.description || editingBot.name
        })
      });
      if (res.ok) {
        const data = await res.json();
        setEditingBot(prev => ({ ...prev, avatar_image: data.avatar_image }));
      } else {
        const err = await res.json();
        alert(`生成失敗: ${err.detail || 'エラー'}`);
      }
    } catch (e: any) {
      alert(`アバター生成エラー: ${e.message}`);
    } finally {
      setIsGeneratingAvatar(false);
    }
  };

  const startCreateBot = () => {
    setEditingBot({
      name: '',
      description: '',
      category: 'カスタム',
      avatar: '🤖',
      avatar_image: '',
      system_prompt: 'あなたは親切で有能なAIアシスタントです。',
      greeting: 'こんにちは！何をお手伝いしましょうか？',
      quick_prompts: []
    });
    setQuickPromptInput('');
    setIsEditingBot(true);
  };

  const startEditBot = (bot: BotConfig) => {
    setEditingBot({
      ...bot,
      quick_prompts: bot.quick_prompts ? [...bot.quick_prompts] : []
    });
    setQuickPromptInput('');
    setIsEditingBot(true);
  };

  const handleAddQuickPrompt = () => {
    if (!quickPromptInput.trim()) return;
    setEditingBot(prev => ({
      ...prev,
      quick_prompts: [...(prev.quick_prompts || []), quickPromptInput.trim()]
    }));
    setQuickPromptInput('');
  };

  const handleRemoveQuickPrompt = (index: number) => {
    setEditingBot(prev => ({
      ...prev,
      quick_prompts: (prev.quick_prompts || []).filter((_, i) => i !== index)
    }));
  };

  const handleSelectQuickPrompt = (promptText: string) => {
    setInput(promptText);
    textareaRef.current?.focus();
  };

  const startChatWithBot = (bot: BotConfig) => {
    const newSessionId = `session-${Date.now()}`;
    const newSession: ChatSession = {
      id: newSessionId,
      title: `${bot.name}`,
      createdAt: Date.now(),
      messages: bot.greeting ? [{
        id: `greeting-${Date.now()}`,
        role: 'assistant',
        content: bot.greeting
      }] : [],
      mode: 'chat',
      aspectRatio: '1:1',
      style: 'none',
      botId: bot.id
    };
    setSystemPrompt(bot.system_prompt);
    setSessions(prev => [newSession, ...prev]);
    setActiveSessionId(newSessionId);
  };

  const handleTrainImagesSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files) return;
    Array.from(files).forEach(file => {
      if (file.type.startsWith('image/')) {
        const reader = new FileReader();
        reader.onload = (event) => {
          if (event.target?.result) {
            setTrainImages(prev => [...prev, event.target!.result as string]);
          }
        };
        reader.readAsDataURL(file);
      }
    });
  };

  const handleUploadAndPrepareDataset = async () => {
    const cleanName = trainStyleName.trim().replace(/[^a-zA-Z0-9_-]/g, '_');
    if (!cleanName) {
      alert('画風名（英数字推奨）を入力してください。例: my_anime_style');
      return;
    }
    if (trainImages.length === 0) {
      alert('学習用の画像を1枚以上選択またはドロップしてください。');
      return;
    }

    setIsUploadingDataset(true);
    try {
      const res = await fetch(`${BACKEND_URL}/api/train/dataset/upload`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          style_name: cleanName,
          images: trainImages
        })
      });
      if (res.ok) {
        alert(`データセット '${cleanName}' に ${trainImages.length} 枚の画像を登録しました！`);
        setTrainImages([]);
        fetchDatasets();
      } else {
        const err = await res.json();
        alert(`アップロード失敗: ${err.detail || 'エラー'}`);
      }
    } catch (e: any) {
      alert(`通信エラー: ${e.message}`);
    } finally {
      setIsUploadingDataset(false);
    }
  };

  const handleStartLoRATraining = async (selectedStyleName?: string) => {
    const targetStyle = (selectedStyleName || trainStyleName).trim().replace(/[^a-zA-Z0-9_-]/g, '_');
    if (!targetStyle) {
      alert('画風名を入力するか、登録済みデータセットを選択してください。');
      return;
    }

    try {
      const res = await fetch(`${BACKEND_URL}/api/train/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          style_name: targetStyle,
          total_steps: trainSteps,
          auto_caption: trainAutoCaption
        })
      });
      if (res.ok) {
        fetchTrainingStatus();
      } else {
        const err = await res.json();
        alert(`学習開始失敗: ${err.detail || 'エラー'}`);
      }
    } catch (e: any) {
      alert(`通信エラー: ${e.message}`);
    }
  };

  const handleStopLoRATraining = async () => {
    try {
      await fetch(`${BACKEND_URL}/api/train/stop`, { method: 'POST' });
      fetchTrainingStatus();
    } catch (e) {
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

  // High-Quality SDXL Generation Handler (Prompt Master & Style Master)
  const handleHQGenerate = async (promptText: string) => {
    setIsGenerating(true);
    const isStyleMode = activeSession.mode === 'style_master';
    const modeLabel = isStyleMode ? '画風継承' : 'プロンプト追求';
    
    const userMsg: Message = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: `[${modeLabel}] ${promptText}`
    };
    const placeholderMsg: Message = {
      id: `ai-${Date.now()}`,
      role: 'assistant',
      content: `✨ ${modeLabel} AIが推論中... (SDXL 1024×1024 / ${hqSteps} Steps, 丁寧なディテール構築中)`,
      isImage: true
    };

    updateActiveSession(s => {
      const isDefault = s.title.startsWith('会話 ') || s.title.startsWith('新規');
      return {
        ...s,
        title: isDefault ? (promptText.slice(0, 14) + (promptText.length > 14 ? '...' : '')) : s.title,
        messages: [...s.messages, userMsg, placeholderMsg]
      };
    });

    try {
      const res = await fetch(`${BACKEND_URL}/api/hq/generate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          prompt: promptText,
          negative_prompt: hqNegativePrompt || null,
          enhance_prompt: hqEnhancePrompt,
          lora_name: isStyleMode ? (activeSession.loraName || null) : null,
          lora_scale: hqLoraScale,
          steps: hqSteps,
          guidance_scale: hqGuidanceScale,
          aspect_ratio: activeSession.aspectRatio,
          seed: null
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
          content: data.enhanced_prompt ? `✨ 拡張プロンプト: ${data.enhanced_prompt}` : `プロンプト: ${data.original_prompt}`,
          isImage: true,
          imageUrl: data.image_url,
          imageMeta: {
            seed: data.seed,
            steps: data.steps,
            elapsed_seconds: data.elapsed_seconds,
            width: data.width,
            height: data.height,
            enhanced_prompt: data.enhanced_prompt,
            final_prompt: data.final_prompt,
            lora_name: data.lora_name,
            lora_scale: data.lora_scale,
            guidance_scale: data.guidance_scale
          }
        };
        return { ...s, messages: updated };
      });
    } catch (err: any) {
      updateActiveSession(s => {
        const updated = [...s.messages];
        updated[updated.length - 1] = {
          ...updated[updated.length - 1],
          content: `⚠️ 生成エラー: ${err.message || '生成に失敗しました'}`
        };
        return { ...s, messages: updated };
      });
    } finally {
      setIsGenerating(false);
      fetchGpuStatus();
    }
  };

  const handlePreviewEnhancedPrompt = async () => {
    if (!input.trim()) return;
    setIsEnhancingPrompt(true);
    try {
      const res = await fetch(`${BACKEND_URL}/api/hq/enhance-prompt`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt: input.trim() })
      });
      if (res.ok) {
        const data = await res.json();
        setEnhancedPromptPreview(data.enhanced_prompt);
      }
    } catch (e: any) {
      alert(`プロンプト拡張エラー: ${e.message}`);
    } finally {
      setIsEnhancingPrompt(false);
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

    if (lastUserMsg.content.startsWith('[プロンプト追求]') || lastUserMsg.content.startsWith('[画風継承]')) {
      const cleanPrompt = lastUserMsg.content.replace(/\[(プロンプト追求|画風継承)\]/, '').trim();
      handleHQGenerate(cleanPrompt);
    } else if (lastUserMsg.isImage || lastUserMsg.content.startsWith('[画像生成]')) {
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

    if (activeSession.mode === 'prompt_master' || activeSession.mode === 'style_master') {
      handleHQGenerate(text);
    } else if (activeSession.mode === 'image' || text.startsWith('/image ')) {
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
              <span style={{ color: '#e5e7eb' }}>Qwen2.5-VL-7B (4-bit)</span>
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

        {/* High-Quality Settings (Prompt Master & Style Master) */}
        {(activeSession.mode === 'prompt_master' || activeSession.mode === 'style_master') && (
          <>
            <div className="sidebar-section-title">
              {activeSession.mode === 'prompt_master' ? '🎨 プロンプト追求設定' : '🖌️ 画風継承設定'}
            </div>

            {activeSession.mode === 'style_master' && (
              <>
                <div className="param-group">
                  <div className="param-label">
                    <span>適用する画風 (LoRA)</span>
                  </div>
                  <select
                    className="style-select"
                    value={activeSession.loraName || ''}
                    onChange={(e) => updateActiveSession(s => ({ ...s, loraName: e.target.value || undefined }))}
                  >
                    <option value="">(画風を選択してください)</option>
                    {availableLoras.map((l) => (
                      <option key={l} value={l}>
                        {l}
                      </option>
                    ))}
                  </select>
                </div>

                <div className="param-group">
                  <div className="param-label">
                    <span>画風の適用強度</span>
                    <span>{hqLoraScale}</span>
                  </div>
                  <input
                    type="range"
                    min="0.2"
                    max="1.3"
                    step="0.05"
                    value={hqLoraScale}
                    onChange={(e) => setHqLoraScale(parseFloat(e.target.value))}
                    className="param-slider"
                  />
                  <span style={{ fontSize: '0.73rem', color: '#9ca3af' }}>
                    0.8前後が最も自然に画風が反映されます。
                  </span>
                </div>
              </>
            )}

            <div className="param-group">
              <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: '0.8rem', cursor: 'pointer', color: '#f59e0b' }}>
                <input
                  type="checkbox"
                  checked={hqEnhancePrompt}
                  onChange={(e) => setHqEnhancePrompt(e.target.checked)}
                />
                <span>🪄 Midjourney風 プロンプト自動拡張</span>
              </label>
              <span style={{ fontSize: '0.72rem', color: '#94a3b8', display: 'block', marginTop: 2 }}>
                Qwen2.5-VL が情景・ライティング・構図を最高峰英語プロンプトに昇華します。
              </span>
            </div>

            <div className="param-group">
              <div className="param-label">
                <span>縦横比 (高解像度 1024px基準)</span>
              </div>
              <div className="aspect-ratio-selector">
                {(Object.keys(HQ_ASPECT_RATIO_CONFIG) as AspectRatio[]).map((ratio) => (
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
                <span>{HQ_ASPECT_RATIO_CONFIG[activeSession.aspectRatio].desc}</span>
              </div>
            </div>

            <div className="param-group">
              <div className="param-label">
                <span>推論ステップ数 (DPM++ 2M)</span>
                <span>{hqSteps} Steps</span>
              </div>
              <input
                type="range"
                min="20"
                max="45"
                step="5"
                value={hqSteps}
                onChange={(e) => setHqSteps(parseInt(e.target.value))}
                className="param-slider"
              />
              <span style={{ fontSize: '0.73rem', color: '#9ca3af' }}>
                30ステップで緻密な質感とプロンプト再現性を追求します。
              </span>
            </div>

            <div className="param-group">
              <div className="param-label">
                <span>プロンプト忠実度 (CFG Scale)</span>
                <span>{hqGuidanceScale}</span>
              </div>
              <input
                type="range"
                min="5.0"
                max="12.0"
                step="0.5"
                value={hqGuidanceScale}
                onChange={(e) => setHqGuidanceScale(parseFloat(e.target.value))}
                className="param-slider"
              />
            </div>

            <div className="param-group">
              <div className="param-label">
                <span>除外したい要素 (Negative Prompt)</span>
              </div>
              <input
                type="text"
                className="bot-form-input"
                style={{ fontSize: '0.75rem', padding: '6px 8px' }}
                placeholder="例: text, watermark, blurry..."
                value={hqNegativePrompt}
                onChange={(e) => setHqNegativePrompt(e.target.value)}
              />
            </div>
          </>
        )}

        {/* Turbo Image Generation Settings */}
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
                  {s.mode === 'prompt_master' ? '🎨 ' : s.mode === 'style_master' ? '🖌️ ' : s.mode === 'bots' ? '🤖 ' : s.mode === 'train' ? '🎓 ' : s.mode === 'image' ? '⚡ ' : (s.botId && bots.find(b => b.id === s.botId)?.avatar) ? `${bots.find(b => b.id === s.botId)?.avatar} ` : '💬 '}
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

        {/* Messages or Training Studio */}
        <div className="chat-messages">
          {activeSession.mode === 'train' ? (
            <div className="style-training-studio">
              <div className="training-header">
                <div className="training-title-row">
                  <GraduationCap size={28} color="#c084fc" />
                  <div>
                    <h2>画風追加学習スタジオ (LoRA Training)</h2>
                    <p>手持ちのイラスト画像を読み込ませ、RTX 4070 Ti (12GB) のGPUパワーであなただけの画風LoRAモデルを作成します（個人利用専用）。</p>
                  </div>
                </div>
              </div>

              {/* Training Progress / Status Card */}
              {trainingStatus && (trainingStatus.is_training || trainingStatus.saved_lora_path) && (
                <div className={`training-status-card ${trainingStatus.is_training ? 'active' : 'success'}`}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      {trainingStatus.is_training ? (
                        <RotateCw size={18} className="animate-spin text-purple-400" />
                      ) : (
                        <Check size={18} color="#10b981" />
                      )}
                      <span style={{ fontWeight: 600 }}>
                        {trainingStatus.is_training ? `学習中: ${trainingStatus.style_name}` : `学習完了: ${trainingStatus.style_name}`}
                      </span>
                    </div>
                    {trainingStatus.is_training && (
                      <button className="stop-train-btn" onClick={handleStopLoRATraining}>
                        <Square size={12} /> 中止
                      </button>
                    )}
                    {!trainingStatus.is_training && trainingStatus.saved_lora_path && (
                      <button
                        className="try-lora-btn"
                        onClick={() => {
                          updateActiveSession(s => ({ ...s, mode: 'image', loraName: trainingStatus.style_name }));
                        }}
                      >
                        🎨 この画風で画像生成を試す
                      </button>
                    )}
                  </div>

                  {/* Progress bar */}
                  <div className="training-progress-container">
                    <div
                      className="training-progress-fill"
                      style={{ width: `${trainingStatus.progress_percent || 0}%` }}
                    />
                  </div>

                  <div className="training-stats-row">
                    <span>進捗: {trainingStatus.progress_percent}% ({trainingStatus.current_step} / {trainingStatus.total_steps} Steps)</span>
                    <span>Loss: {trainingStatus.current_loss}</span>
                    <span>経過: {trainingStatus.elapsed_seconds}s</span>
                    {trainingStatus.is_training && trainingStatus.estimated_remaining_seconds > 0 && (
                      <span>残り約: {Math.round(trainingStatus.estimated_remaining_seconds)}s</span>
                    )}
                  </div>
                  <div style={{ fontSize: '0.8rem', color: '#cbd5e1', marginTop: 4 }}>
                    {trainingStatus.status_message}
                  </div>
                </div>
              )}

              {/* Dataset & Training Grid */}
              <div className="training-grid">
                {/* 1. Dataset upload & folder card */}
                <div className="training-card">
                  <h3>1. 画風名 & 学習画像の追加</h3>
                  <div style={{ marginBottom: 12 }}>
                    <label style={{ display: 'block', fontSize: '0.8rem', color: '#94a3b8', marginBottom: 4 }}>
                      画風の名前（英数字・アンダースコア）
                    </label>
                    <input
                      type="text"
                      className="train-input"
                      placeholder="例: my_anime_style, watercolor_girl"
                      value={trainStyleName}
                      onChange={(e) => setTrainStyleName(e.target.value)}
                    />
                  </div>

                  <div
                    className="train-dropzone"
                    onClick={() => trainFileInputRef.current?.click()}
                  >
                    <FolderUp size={32} color="#c084fc" />
                    <p>クリックして画像を選択、またはドラッグ＆ドロップ</p>
                    <span>PNG, JPG, WEBP 対応 (5〜15枚推奨)</span>
                    <input
                      type="file"
                      ref={trainFileInputRef}
                      onChange={handleTrainImagesSelect}
                      multiple
                      accept="image/*"
                      style={{ display: 'none' }}
                    />
                  </div>

                  {trainImages.length > 0 && (
                    <div style={{ marginTop: 12 }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                        <span style={{ fontSize: '0.8rem', color: '#cbd5e1' }}>選択画像: {trainImages.length}枚</span>
                        <button
                          style={{ fontSize: '0.75rem', color: '#ef4444', background: 'none', border: 'none', cursor: 'pointer' }}
                          onClick={() => setTrainImages([])}
                        >
                          すべて解除
                        </button>
                      </div>
                      <div className="train-image-grid">
                        {trainImages.map((img, i) => (
                          <div key={i} className="train-image-thumb">
                            <img src={img} alt={`train-${i}`} />
                            <button
                              className="train-image-remove"
                              onClick={(e) => {
                                e.stopPropagation();
                                setTrainImages(prev => prev.filter((_, idx) => idx !== i));
                              }}
                            >
                              ×
                            </button>
                          </div>
                        ))}
                      </div>

                      <button
                        className="save-dataset-btn"
                        onClick={handleUploadAndPrepareDataset}
                        disabled={isUploadingDataset}
                      >
                        {isUploadingDataset ? 'フォルダ保存中...' : `📁 フォルダ 'training_data/${trainStyleName || '...'}' に登録する`}
                      </button>
                    </div>
                  )}

                  <div className="folder-tip">
                    💡 <strong>直接フォルダに配置する場合:</strong><br />
                    <code>backend/training_data/&lt;画風名&gt;/</code> フォルダにイラストを直接配置しても自動検出されます。
                  </div>
                </div>

                {/* 2. Training configuration & execution */}
                <div className="training-card">
                  <h3>2. 学習設定 & 実行</h3>
                  <div style={{ marginBottom: 14 }}>
                    <label style={{ display: 'block', fontSize: '0.8rem', color: '#94a3b8', marginBottom: 4 }}>
                      学習ステップ数: {trainSteps} Steps (目安: 300 stepsで約2分)
                    </label>
                    <input
                      type="range"
                      min="100"
                      max="800"
                      step="50"
                      value={trainSteps}
                      onChange={(e) => setTrainSteps(parseInt(e.target.value))}
                      className="param-slider image-accent"
                    />
                  </div>

                  <div style={{ marginBottom: 16 }}>
                    <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: '0.85rem', cursor: 'pointer', color: '#e2e8f0' }}>
                      <input
                        type="checkbox"
                        checked={trainAutoCaption}
                        onChange={(e) => setTrainAutoCaption(e.target.checked)}
                      />
                      <span>🤖 Vision LLM による自動キャプション付与（推奨）</span>
                    </label>
                    <span style={{ fontSize: '0.75rem', color: '#94a3b8', display: 'block', marginLeft: 24, marginTop: 2 }}>
                      Vision AI が各画像の構図を言語化し、画風の特徴を綺麗に分離して高精度に学習します。
                    </span>
                  </div>

                  <div style={{ marginBottom: 16 }}>
                    <span style={{ fontSize: '0.8rem', color: '#94a3b8', display: 'block', marginBottom: 6 }}>
                      登録済みデータセット一覧:
                    </span>
                    {datasets.length === 0 ? (
                      <div style={{ fontSize: '0.8rem', color: '#64748b', fontStyle: 'italic' }}>
                        登録済みデータセットがありません。左のフォームから作成してください。
                      </div>
                    ) : (
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                        {datasets.map((ds) => (
                          <div key={ds.style_name} className="dataset-item-row">
                            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                              <Folder size={16} color="#38bdf8" />
                              <div>
                                <span style={{ fontWeight: 600, fontSize: '0.85rem', color: '#f8fafc' }}>{ds.style_name}</span>
                                <span style={{ fontSize: '0.75rem', color: '#94a3b8', marginLeft: 6 }}>({ds.image_count}枚)</span>
                              </div>
                            </div>
                            <button
                              className="start-single-train-btn"
                              onClick={() => handleStartLoRATraining(ds.style_name)}
                              disabled={trainingStatus?.is_training}
                            >
                              <Play size={12} /> 学習開始
                            </button>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>

                  <div style={{ marginTop: 'auto' }}>
                    <button
                      className="start-main-train-btn"
                      onClick={() => handleStartLoRATraining()}
                      disabled={trainingStatus?.is_training || (!trainStyleName && datasets.length === 0)}
                    >
                      <Play size={16} />
                      <span>{trainingStatus?.is_training ? '学習進行中...' : `🚀 '${trainStyleName || (datasets[0]?.style_name || '選択中')}' の画風学習を開始`}</span>
                    </button>
                  </div>
                </div>
              </div>
            </div>
          ) : activeSession.mode === 'bots' ? (
            <div className="bot-studio">
              {/* Studio Header */}
              <div className="bot-studio-header">
                <div className="bot-studio-title-box">
                  <div className="bot-studio-icon">🤖</div>
                  <div>
                    <h2>カスタムボットスタジオ (Custom Bot Studio)</h2>
                    <p>
                      RTX 4070 Ti のローカルLLM（Qwen2.5-VL-7B）で動作する専門特化AIボットを作成・管理できます。
                    </p>
                  </div>
                </div>
                <button className="create-bot-btn" onClick={startCreateBot}>
                  <Plus size={16} /> 新規ボットを作成
                </button>
              </div>

              {/* Category Filter Tabs */}
              <div className="bot-category-bar">
                {['all', '教育・学習', 'プログラミング', '語学・翻訳', '汎用アシスタント', 'カスタム'].map(cat => (
                  <button
                    key={cat}
                    className={`bot-cat-btn ${botCategoryFilter === cat ? 'active' : ''}`}
                    onClick={() => setBotCategoryFilter(cat)}
                  >
                    {cat === 'all' ? 'すべて表示' : cat}
                  </button>
                ))}
              </div>

              {/* Bots Cards Grid */}
              <div className="bot-cards-grid">
                {filteredBots.map(bot => (
                  <div key={bot.id} className="bot-card">
                    <div className="bot-card-top">
                      <div className="bot-card-avatar">
                        {bot.avatar_image ? (
                          <img src={bot.avatar_image} alt={bot.name} />
                        ) : (
                          <span className="bot-card-emoji">{bot.avatar || '🤖'}</span>
                        )}
                      </div>
                      <div className="bot-card-info">
                        <div className="bot-card-title-row">
                          <h4>{bot.name}</h4>
                          {bot.is_preset ? (
                            <span className="bot-preset-badge">公式</span>
                          ) : (
                            <span className="bot-custom-badge">カスタム</span>
                          )}
                        </div>
                        <span className="bot-card-cat">{bot.category}</span>
                      </div>
                    </div>

                    <p className="bot-card-desc">{bot.description}</p>

                    {/* Quick Prompts Preview */}
                    {bot.quick_prompts && bot.quick_prompts.length > 0 && (
                      <div className="bot-card-prompts">
                        <span className="prompts-label">質問例:</span>
                        <div className="prompts-chips">
                          {bot.quick_prompts.slice(0, 2).map((qp, idx) => (
                            <span key={idx} className="prompt-preview-chip">
                              "{qp}"
                            </span>
                          ))}
                        </div>
                      </div>
                    )}

                    <div className="bot-card-actions">
                      <button
                        className="bot-chat-btn"
                        onClick={() => startChatWithBot(bot)}
                        title="このボットと会話を開始"
                      >
                        <MessageSquare size={14} /> 対話を開始
                      </button>
                      <button
                        className="bot-edit-btn"
                        onClick={() => startEditBot(bot)}
                        title="設定を編集"
                      >
                        <Edit2 size={13} />
                      </button>
                      {!bot.is_preset && (
                        <button
                          className="bot-delete-btn"
                          onClick={() => handleDeleteBot(bot.id)}
                          title="削除"
                        >
                          <Trash2 size={13} />
                        </button>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ) : activeSession.messages.length === 0 ? (
            <div className="empty-chat">
              {activeSession.mode === 'chat' && currentBot ? (
                <div className="empty-bot-welcome">
                  <div className="empty-bot-avatar-large">
                    {currentBot.avatar_image ? (
                      <img src={currentBot.avatar_image} alt={currentBot.name} />
                    ) : (
                      <span>{currentBot.avatar || '🤖'}</span>
                    )}
                  </div>
                  <h3>{currentBot.name}</h3>
                  <span className="empty-bot-category">{currentBot.category}</span>
                  <p className="empty-bot-description">{currentBot.description}</p>

                  {currentBot.greeting && (
                    <div className="empty-bot-greeting-quote">
                      「{currentBot.greeting}」
                    </div>
                  )}

                  {currentBot.quick_prompts && currentBot.quick_prompts.length > 0 && (
                    <div className="empty-bot-prompts-section">
                      <div className="empty-bot-prompts-title">
                        <Sparkles size={14} color="#38bdf8" />
                        <span>ワンクリックで質問を始める:</span>
                      </div>
                      <div className="empty-bot-prompts-grid">
                        {currentBot.quick_prompts.map((qp, idx) => (
                          <button
                            key={idx}
                            className="empty-prompt-card"
                            onClick={() => handleSelectQuickPrompt(qp)}
                          >
                            <span>💡 {qp}</span>
                          </button>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              ) : activeSession.mode === 'chat' ? (
                <>
                  <Bot className="empty-icon" />
                  <h3>マルチモーダル Vision AI アシスタント</h3>
                  <p>
                    テキストの会話はもちろん、画像を貼り付け（Ctrl+V）または添付すると、AIが画像を視覚的に認識して解説します。
                  </p>
                  <p style={{ fontSize: '0.85rem' }}>
                    下のクリップボタンまたは Ctrl+V でスクリーンショットを直接貼り付けて質問できます。
                  </p>

                  {/* Suggest starting with a bot */}
                  {bots.length > 0 && (
                    <div className="empty-suggest-bots">
                      <div className="suggest-title">🤖 専門特化ボットを選んでチャットを開始:</div>
                      <div className="suggest-bots-row">
                        {bots.slice(0, 4).map(b => (
                          <button
                            key={b.id}
                            className="suggest-bot-chip"
                            onClick={() => startChatWithBot(b)}
                          >
                            <span className="suggest-bot-avatar">
                              {b.avatar_image ? <img src={b.avatar_image} alt={b.name} /> : b.avatar}
                            </span>
                            <span className="suggest-bot-name">{b.name}</span>
                          </button>
                        ))}
                      </div>
                    </div>
                  )}
                </>
              ) : activeSession.mode === 'prompt_master' ? (
                <div className="empty-hq-welcome">
                  <div className="empty-hq-badge" style={{ background: 'rgba(245, 158, 11, 0.15)', borderColor: '#f59e0b', color: '#fbbf24' }}>
                    <Sparkles size={16} /> Midjourney級 プロンプト追求スタジオ
                  </div>
                  <h3>プロンプト忠実・超高精細 AI (SDXL 1024×1024)</h3>
                  <p>
                    速度ではなく「構図の忠実度・圧倒的な質感・ライティング」を最優先して、25〜35ステップかけて緻密に描き出します。
                  </p>
                  <p style={{ fontSize: '0.85rem', color: '#94a3b8' }}>
                    日本語でイメージを入力すると、Vision LLM が Midjourney 風の最高峰英語プロンプトへと自動拡張します（左下でON/OFF可能）。
                  </p>

                  <div className="empty-suggest-prompts">
                    <span className="suggest-title">💡 おすすめの高品質プロンプト例（クリックで入力）:</span>
                    <div className="suggest-prompts-grid">
                      {[
                        '雨上がりの夜、ネオンに照らされた路地裏を歩く猫、水たまりの反射',
                        'サイバーパンクの未来都市、空飛ぶ車と高層ビル、雨に濡れたサイバー少女',
                        '水彩画の透明感あふれる星空と古城の湖畔、幻想的な光の粒子',
                        '木漏れ日が差し込む静かなアンティーク図書館で読書する少女、詳細な絵画'
                      ].map((pr, idx) => (
                        <button
                          key={idx}
                          type="button"
                          className="empty-prompt-card"
                          onClick={() => handleSelectQuickPrompt(pr)}
                        >
                          <span>✨ {pr}</span>
                        </button>
                      ))}
                    </div>
                  </div>
                </div>
              ) : activeSession.mode === 'style_master' ? (
                <div className="empty-hq-welcome">
                  <div className="empty-hq-badge" style={{ background: 'rgba(236, 72, 153, 0.15)', borderColor: '#ec4899', color: '#f472b6' }}>
                    <Palette size={16} /> 画風継承 AI スタジオ
                  </div>
                  <h3>学んだ画風で、あなたが望む新しい絵を描く</h3>
                  <p>
                    フォルダから学習したイラストの「筆致・タッチ・色彩」を完全に引き継ぎ、あなたが望む新しいテーマを1024×1024で描きます。
                  </p>

                  {availableLoras.length === 0 ? (
                    <div className="empty-style-no-lora">
                      <p style={{ color: '#cbd5e1', fontSize: '0.9rem', marginBottom: 12 }}>
                        まだ学習済みの画風（LoRA）がありません。まずは「画風学習 (LoRA)」タブでイラストフォルダから画風を学習しましょう！
                      </p>
                      <button
                        className="start-train-shortcut-btn"
                        onClick={() => updateActiveSession(s => ({ ...s, mode: 'train' }))}
                      >
                        <GraduationCap size={16} /> 🎓 画風学習スタジオへ移動する
                      </button>
                    </div>
                  ) : (
                    <div className="empty-suggest-prompts">
                      <span className="suggest-title">🎨 現在利用可能な画風ライブラリ（クリックで選択）:</span>
                      <div className="suggest-style-chips">
                        {availableLoras.map((lora) => (
                          <button
                            key={lora}
                            type="button"
                            className={`style-chip-btn ${activeSession.loraName === lora ? 'selected' : ''}`}
                            onClick={() => updateActiveSession(s => ({ ...s, loraName: lora }))}
                          >
                            <Palette size={13} />
                            <span>{lora}</span>
                          </button>
                        ))}
                      </div>
                      <p style={{ fontSize: '0.8rem', color: '#94a3b8', marginTop: 12 }}>
                        画風を選択後、下の入力欄に「描いてほしいもの（例: 夕暮れの草原、宇宙服の少年）」を入力して送信してください。
                      </p>
                    </div>
                  )}
                </div>
              ) : (
                <>
                  <ImageIcon className="empty-icon" style={{ color: '#8b5cf6' }} />
                  <h3>高速ローカル画像生成スタジオ (SD-Turbo)</h3>
                  <p>
                    SD-Turbo を使用し、RTX 4070 Ti の圧倒的なパワーでわずか1秒未満で画像を生成します。
                  </p>
                  <p style={{ fontSize: '0.85rem' }}>
                    生成したい画像のプロンプトを入力してください。画風や縦横比も選べます。
                  </p>
                </>
              )}
            </div>
          ) : (
            activeSession.messages.map((msg) => (
              <div key={msg.id} className={`message-row ${msg.role === 'user' ? 'user' : 'ai'}`}>
                {msg.role !== 'user' && (
                  <div className={`message-avatar ${msg.isImage ? 'avatar-image-ai' : 'avatar-ai'}`}>
                    {msg.isImage ? (
                      <ImageIcon size={18} />
                    ) : currentBot?.avatar_image ? (
                      <img src={currentBot.avatar_image} alt="Bot" style={{ width: '100%', height: '100%', borderRadius: '50%', objectFit: 'cover' }} />
                    ) : currentBot?.avatar ? (
                      <span style={{ fontSize: '1.1rem' }}>{currentBot.avatar}</span>
                    ) : (
                      <Bot size={18} />
                    )}
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
                            ⏱️ {msg.imageMeta?.elapsed_seconds}s | {msg.imageMeta?.width}×{msg.imageMeta?.height} | {msg.imageMeta?.steps} steps
                            {msg.imageMeta?.lora_name ? ` | 🎨 画風: ${msg.imageMeta.lora_name}` : ''}
                            {msg.imageMeta?.style_name ? ` | ${msg.imageMeta.style_name}` : ''}
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
                        {msg.imageMeta?.enhanced_prompt && (
                          <div className="enhanced-prompt-accordion">
                            <div className="ep-label">
                              <Sparkles size={12} color="#f59e0b" />
                              <span>Midjourney風 拡張プロンプト:</span>
                            </div>
                            <div className="ep-content">{msg.imageMeta.enhanced_prompt}</div>
                          </div>
                        )}
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
                className={`mode-tab ${activeSession.mode === 'prompt_master' ? 'active-prompt-master' : ''}`}
                onClick={() => updateActiveSession(s => ({ ...s, mode: 'prompt_master' }))}
                title="Midjourney級のプロンプト忠実度・最高画質生成 (SDXL 1024×1024)"
              >
                <Sparkles size={14} color="#f59e0b" />
                <span>🎨 プロンプト追求</span>
              </button>
              <button
                className={`mode-tab ${activeSession.mode === 'style_master' ? 'active-style-master' : ''}`}
                onClick={() => updateActiveSession(s => ({ ...s, mode: 'style_master' }))}
                title="学習した画風のタッチで望むものを描く"
              >
                <Palette size={14} color="#ec4899" />
                <span>🖌️ 画風継承</span>
              </button>
              <button
                className={`mode-tab ${activeSession.mode === 'train' ? 'active-train' : ''}`}
                onClick={() => updateActiveSession(s => ({ ...s, mode: 'train' }))}
              >
                <GraduationCap size={14} />
                <span>画風学習 (LoRA)</span>
              </button>
              <button
                className={`mode-tab ${activeSession.mode === 'image' ? 'active-image' : ''}`}
                onClick={() => updateActiveSession(s => ({ ...s, mode: 'image' }))}
                title="0.1秒台の超高速プレビュー生成 (SD-Turbo)"
              >
                <ImageIcon size={14} />
                <span>⚡ 高速プレビュー</span>
              </button>
              <button
                className={`mode-tab ${activeSession.mode === 'bots' ? 'active-bots' : ''}`}
                onClick={() => updateActiveSession(s => ({ ...s, mode: 'bots' }))}
              >
                <Bot size={14} />
                <span>🤖 ボット管理</span>
              </button>
            </div>

            {/* Prompt Master Controls */}
            {activeSession.mode === 'prompt_master' && (
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                <label style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: '0.78rem', color: '#f59e0b', cursor: 'pointer' }}>
                  <input
                    type="checkbox"
                    checked={hqEnhancePrompt}
                    onChange={(e) => setHqEnhancePrompt(e.target.checked)}
                  />
                  <span>🪄 Midjourney風 自動拡張</span>
                </label>

                {input.trim() && (
                  <button
                    type="button"
                    className="enhance-preview-btn"
                    onClick={handlePreviewEnhancedPrompt}
                    disabled={isEnhancingPrompt}
                    title="Vision LLM による英語拡張結果をプレビュー"
                  >
                    <Wand2 size={12} />
                    <span>{isEnhancingPrompt ? '拡張中...' : '拡張プレビュー'}</span>
                  </button>
                )}

                {/* Aspect Ratio Selector */}
                <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                  <span style={{ fontSize: '0.75rem', color: '#9ca3af' }}>比率:</span>
                  <div style={{ display: 'flex', gap: 3 }}>
                    {(Object.keys(HQ_ASPECT_RATIO_CONFIG) as AspectRatio[]).map((ratio) => (
                      <button
                        key={ratio}
                        type="button"
                        className={`aspect-ratio-btn ${activeSession.aspectRatio === ratio ? 'active' : ''}`}
                        onClick={() => updateActiveSession(s => ({ ...s, aspectRatio: ratio }))}
                        style={{ padding: '3px 6px', fontSize: '0.75rem', minWidth: '38px' }}
                        title={HQ_ASPECT_RATIO_CONFIG[ratio].desc}
                      >
                        {ratio}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            )}

            {/* Style Master Controls */}
            {activeSession.mode === 'style_master' && (
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                  <Palette size={14} color="#ec4899" />
                  <span style={{ fontSize: '0.75rem', color: '#f472b6' }}>画風:</span>
                  <select
                    className="style-select"
                    value={activeSession.loraName || ''}
                    onChange={(e) => updateActiveSession(s => ({ ...s, loraName: e.target.value || undefined }))}
                    style={{ padding: '3px 6px', fontSize: '0.75rem', borderColor: '#ec4899' }}
                  >
                    <option value="">(画風を選択)</option>
                    {availableLoras.map((lora) => (
                      <option key={lora} value={lora}>
                        {lora}
                      </option>
                    ))}
                  </select>
                </div>

                <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                  <span style={{ fontSize: '0.75rem', color: '#9ca3af' }}>強度: {hqLoraScale}</span>
                  <input
                    type="range"
                    min="0.2"
                    max="1.3"
                    step="0.05"
                    value={hqLoraScale}
                    onChange={(e) => setHqLoraScale(parseFloat(e.target.value))}
                    style={{ width: '60px' }}
                    className="param-slider"
                  />
                </div>

                <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                  <span style={{ fontSize: '0.75rem', color: '#9ca3af' }}>比率:</span>
                  <div style={{ display: 'flex', gap: 3 }}>
                    {(Object.keys(HQ_ASPECT_RATIO_CONFIG) as AspectRatio[]).map((ratio) => (
                      <button
                        key={ratio}
                        type="button"
                        className={`aspect-ratio-btn ${activeSession.aspectRatio === ratio ? 'active' : ''}`}
                        onClick={() => updateActiveSession(s => ({ ...s, aspectRatio: ratio }))}
                        style={{ padding: '3px 6px', fontSize: '0.75rem', minWidth: '38px' }}
                        title={HQ_ASPECT_RATIO_CONFIG[ratio].desc}
                      >
                        {ratio}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            )}

            {/* Turbo Mode Controls */}
            {activeSession.mode === 'image' && (
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                {availableLoras.length > 0 && (
                  <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                    <span style={{ fontSize: '0.75rem', color: '#c084fc' }}>LoRA:</span>
                    <select
                      className="style-select"
                      value={activeSession.loraName || ''}
                      onChange={(e) => updateActiveSession(s => ({ ...s, loraName: e.target.value || undefined }))}
                      style={{ padding: '3px 6px', fontSize: '0.75rem', borderColor: '#a855f7' }}
                    >
                      <option value="">なし (Default)</option>
                      {availableLoras.map((lora) => (
                        <option key={lora} value={lora}>
                          {lora}
                        </option>
                      ))}
                    </select>
                  </div>
                )}

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

          {/* Enhanced Prompt Preview Banner */}
          {enhancedPromptPreview && (
            <div className="enhanced-prompt-preview-bar">
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
                <Sparkles size={14} color="#f59e0b" />
                <span style={{ fontSize: '0.8rem', fontWeight: 600, color: '#f59e0b' }}>
                  Midjourney風 拡張英語プロンプトのプレビュー:
                </span>
              </div>
              <div className="preview-text">{enhancedPromptPreview}</div>
              <div style={{ display: 'flex', gap: 8, marginTop: 6, justifyContent: 'flex-end' }}>
                <button
                  type="button"
                  className="preview-action-btn apply"
                  onClick={() => {
                    setInput(enhancedPromptPreview);
                    setEnhancedPromptPreview(null);
                  }}
                >
                  この英語プロンプトを入力欄に適用
                </button>
                <button
                  type="button"
                  className="preview-action-btn cancel"
                  onClick={() => setEnhancedPromptPreview(null)}
                >
                  閉じる
                </button>
              </div>
            </div>
          )}

          {/* Quick Prompts Bar for Chat Mode with Active Bot */}
          {activeSession.mode === 'chat' && currentBot && currentBot.quick_prompts && currentBot.quick_prompts.length > 0 && (
            <div className="active-bot-prompts-bar">
              <span className="abp-label">
                <Sparkles size={12} color="#38bdf8" />
                <span>{currentBot.name} のおすすめ質問:</span>
              </span>
              <div className="abp-list">
                {currentBot.quick_prompts.map((qp, idx) => (
                  <button
                    key={idx}
                    type="button"
                    className="abp-chip"
                    onClick={() => handleSelectQuickPrompt(qp)}
                    title="クリックして入力欄にセット"
                  >
                    {qp}
                  </button>
                ))}
              </div>
            </div>
          )}

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

          {activeSession.mode === 'bots' ? (
            <div className="bot-studio-guide-bar">
              <span>💡 ボットスタジオを閲覧中。お好みのボットのカードから「💬 対話を開始」を押すと、専用のチャットが開始します。</span>
              <button className="guide-create-bot-btn" onClick={startCreateBot}>
                <Plus size={14} /> 新規作成
              </button>
            </div>
          ) : (
            <div className={`chat-input-box ${activeSession.mode === 'prompt_master' ? 'prompt-master-focus' : activeSession.mode === 'style_master' ? 'style-master-focus' : activeSession.mode === 'image' ? 'image-mode-focus' : ''}`}>
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
                  activeSession.mode === 'prompt_master'
                    ? '【プロンプト追求】描きたい情景・ライティング・質感を日本語または英語で入力... (Shift+Enterで改行)'
                    : activeSession.mode === 'style_master'
                    ? '【画風継承】選択した画風で描いてほしいテーマを入力... (例: 夕暮れの海辺を散歩する少女)'
                    : activeSession.mode === 'image'
                    ? '【高速プレビュー】生成したい画像のプロンプトを入力 (SD-Turbo 0.1秒)...'
                    : currentBot
                    ? `${currentBot.name} へ質問を入力... (画像はCtrl+Vで貼り付け可能 / Shift+Enterで改行)`
                    : 'メッセージを入力... (画像はCtrl+Vで貼り付け可能 / Shift+Enterで改行)'
                }
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                onPaste={handlePaste}
                rows={2}
              />
              <button
                className={`send-button ${activeSession.mode === 'prompt_master' ? 'prompt-master-send' : activeSession.mode === 'style_master' ? 'style-master-send' : activeSession.mode === 'image' ? 'image-send' : ''}`}
                onClick={handleSubmit}
                disabled={isGenerating || (!input.trim() && attachments.length === 0) || gpuStatus?.is_loading}
                title={activeSession.mode === 'prompt_master' ? 'プロンプト追求 高品質画像を生成 (SDXL)' : activeSession.mode === 'style_master' ? '学習した画風で画像を生成 (SDXL+LoRA)' : activeSession.mode === 'image' ? '高速プレビュー生成' : 'メッセージ送信'}
              >
                {activeSession.mode === 'prompt_master' ? <Sparkles size={18} /> : activeSession.mode === 'style_master' ? <Palette size={18} /> : activeSession.mode === 'image' ? <ImageIcon size={18} /> : <Send size={18} />}
              </button>
            </div>
          )}

          <div className="input-footer">
            <span>Powered by PyTorch CUDA & Qwen2.5-VL-7B (4-bit) + SDXL (1024px) / SD-Turbo</span>
            <span>Target GPU: GeForce RTX 4070 Ti (12GB)</span>
          </div>
        </div>
      </main>

      {/* Bot Create / Edit Modal */}
      {isEditingBot && (
        <div className="modal-overlay" onClick={() => setIsEditingBot(false)}>
          <div className="bot-modal-content" onClick={(e) => e.stopPropagation()}>
            <div className="bot-modal-header">
              <h3>{editingBot.id ? '🤖 ボットの編集' : '✨ 新しいカスタムボットの作成'}</h3>
              <button className="modal-close-btn" onClick={() => setIsEditingBot(false)}>
                <X size={20} />
              </button>
            </div>

            <div className="bot-form-body">
              {/* Name & Category */}
              <div className="form-row-2">
                <div className="form-group">
                  <label>ボット名 *</label>
                  <input
                    type="text"
                    className="bot-form-input"
                    placeholder="例: 高校数学・物理アシスタント"
                    value={editingBot.name || ''}
                    onChange={(e) => setEditingBot({ ...editingBot, name: e.target.value })}
                  />
                </div>
                <div className="form-group">
                  <label>カテゴリ</label>
                  <select
                    className="bot-form-select"
                    value={editingBot.category || 'カスタム'}
                    onChange={(e) => setEditingBot({ ...editingBot, category: e.target.value })}
                  >
                    <option value="教育・学習">教育・学習</option>
                    <option value="プログラミング">プログラミング</option>
                    <option value="語学・翻訳">語学・翻訳</option>
                    <option value="汎用アシスタント">汎用アシスタント</option>
                    <option value="業務効率化">業務効率化</option>
                    <option value="クリエイティブ">クリエイティブ</option>
                    <option value="カスタム">カスタム</option>
                  </select>
                </div>
              </div>

              {/* Avatar Setup */}
              <div className="avatar-config-box">
                <div className="avatar-preview-box">
                  {editingBot.avatar_image ? (
                    <img src={editingBot.avatar_image} alt="Avatar" className="avatar-preview-img" />
                  ) : (
                    <span className="avatar-preview-emoji">{editingBot.avatar || '🤖'}</span>
                  )}
                </div>
                <div className="avatar-inputs">
                  <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                    <input
                      type="text"
                      className="bot-form-input"
                      style={{ width: '70px', textAlign: 'center', fontSize: '1.2rem' }}
                      placeholder="絵文字"
                      value={editingBot.avatar || '🤖'}
                      onChange={(e) => setEditingBot({ ...editingBot, avatar: e.target.value })}
                    />
                    <button
                      type="button"
                      className="generate-avatar-btn"
                      onClick={handleGenerateBotAvatar}
                      disabled={isGeneratingAvatar || !editingBot.name?.trim()}
                      title="ボット名と説明からSD-Turboで専用アバター画像を即座に生成"
                    >
                      <Wand2 size={14} />
                      <span>{isGeneratingAvatar ? 'アバター生成中...' : '🎨 AIでアバター画像を自動生成'}</span>
                    </button>
                    {editingBot.avatar_image && (
                      <button
                        type="button"
                        className="remove-avatar-btn"
                        onClick={() => setEditingBot({ ...editingBot, avatar_image: '' })}
                      >
                        クリア
                      </button>
                    )}
                  </div>
                  <span style={{ fontSize: '0.75rem', color: '#94a3b8' }}>
                    絵文字、または「AIでアバター画像を自動生成」でSD-Turboが専用イラストアイコンを瞬時に作成します。
                  </span>
                </div>
              </div>

              {/* Description */}
              <div className="form-group">
                <label>説明文</label>
                <input
                  type="text"
                  className="bot-form-input"
                  placeholder="例: 数学や物理の難問をステップ順に分かりやすく解説するボット"
                  value={editingBot.description || ''}
                  onChange={(e) => setEditingBot({ ...editingBot, description: e.target.value })}
                />
              </div>

              {/* System Prompt */}
              <div className="form-group">
                <label>システムプロンプト（役割・口調・指導方針など） *</label>
                <textarea
                  className="bot-form-textarea"
                  rows={4}
                  placeholder="あなたはプロの塾講師です。生徒の質問に対して答えをすぐ言うのではなく、考え方のヒントを順序立てて教えてください。"
                  value={editingBot.system_prompt || ''}
                  onChange={(e) => setEditingBot({ ...editingBot, system_prompt: e.target.value })}
                />
              </div>

              {/* Greeting Message */}
              <div className="form-group">
                <label>初回メッセージ（会話開始時の挨拶）</label>
                <input
                  type="text"
                  className="bot-form-input"
                  placeholder="例: こんにちは！数学の疑問や宿題のつまずきがあれば何でも聞いてね！"
                  value={editingBot.greeting || ''}
                  onChange={(e) => setEditingBot({ ...editingBot, greeting: e.target.value })}
                />
              </div>

              {/* Quick Prompts */}
              <div className="form-group">
                <label>クイック質問候補（ユーザーがワンクリックで送れる質問例）</label>
                <div style={{ display: 'flex', gap: 6, marginBottom: 8 }}>
                  <input
                    type="text"
                    className="bot-form-input"
                    placeholder="例: 二次関数の頂点の求め方を教えて"
                    value={quickPromptInput}
                    onChange={(e) => setQuickPromptInput(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && (e.preventDefault(), handleAddQuickPrompt())}
                  />
                  <button type="button" className="add-prompt-btn" onClick={handleAddQuickPrompt}>
                    追加
                  </button>
                </div>
                <div className="quick-prompts-list">
                  {(editingBot.quick_prompts || []).map((qp, idx) => (
                    <span key={idx} className="quick-prompt-tag">
                      {qp}
                      <button type="button" onClick={() => handleRemoveQuickPrompt(idx)}>×</button>
                    </span>
                  ))}
                </div>
              </div>
            </div>

            <div className="bot-modal-footer">
              <button className="bot-cancel-btn" onClick={() => setIsEditingBot(false)}>
                キャンセル
              </button>
              <button className="bot-save-btn" onClick={handleSaveBot}>
                <Check size={16} /> 保存する
              </button>
            </div>
          </div>
        </div>
      )}

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

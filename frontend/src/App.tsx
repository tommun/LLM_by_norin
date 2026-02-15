import React, { useState } from 'react';
import axios from 'axios';

function App() {
  const [message, setMessage] = useState('');
  const [repo, setRepo] = useState('');
  const [chatLog, setChatLog] = useState<{role: string, text: string}[]>([]);
  const [loading, setLoading] = useState(false);

  const handleSend = async () => {
    if (!message) return;
    setLoading(true);
    const newLog = [...chatLog, { role: 'user', text: message }];
    setChatLog(newLog);
    
    try {
      const res = await axios.post('http://localhost:8000/chat', {
        message: message,
        repo_name: repo || null
      });
      setChatLog([...newLog, { role: 'ai', text: res.data.response }]);
    } catch (err) {
      setChatLog([...newLog, { role: 'ai', text: 'Error: Could not connect to backend' }]);
    }
    setMessage('');
    setLoading(false);
  };

  return (
    <div style={{ padding: '20px', fontFamily: 'sans-serif', maxWidth: '800px', margin: '0 auto' }}>
      <h1>QA LLM Assistant (Gemini)</h1>
      <div style={{ marginBottom: '10px' }}>
        <input 
          placeholder="GitHub Repo (e.g. owner/repo)" 
          value={repo} 
          onChange={(e) => setRepo(e.target.value)}
          style={{ width: '100%', padding: '8px', marginBottom: '10px' }}
        />
      </div>
      <div style={{ border: '1px solid #ccc', height: '400px', overflowY: 'scroll', padding: '10px', marginBottom: '10px' }}>
        {chatLog.map((log, i) => (
          <div key={i} style={{ marginBottom: '10px', textAlign: log.role === 'user' ? 'right' : 'left' }}>
            <div style={{ display: 'inline-block', padding: '8px', borderRadius: '8px', background: log.role === 'user' ? '#007bff' : '#f1f1f1', color: log.role === 'user' ? '#fff' : '#000' }}>
              {log.text}
            </div>
          </div>
        ))}
      </div>
      <div style={{ display: 'flex' }}>
        <input 
          style={{ flex: 1, padding: '8px' }} 
          value={message} 
          onChange={(e) => setMessage(e.target.value)} 
          onKeyPress={(e) => e.key === 'Enter' && handleSend()}
          placeholder="Ask a question..."
        />
        <button onClick={handleSend} disabled={loading} style={{ padding: '8px 16px' }}>
          {loading ? '...' : 'Send'}
        </button>
      </div>
    </div>
  );
}

export default App;

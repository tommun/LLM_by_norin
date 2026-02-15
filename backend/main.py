from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import os
import google.generativeai as genai
from dotenv import load_dotenv
from github import Github

load_dotenv(dotenv_path="../.env")

# Initialize APIs
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
github_client = Github(os.getenv("GITHUB_TOKEN"))

app = FastAPI()

class ChatRequest(BaseModel):
    message: str
    repo_name: str = None  # Optional: "username/repo"

@app.get("/")
def read_root():
    return {"status": "ok", "message": "QA LLM Backend is running"}

@app.post("/chat")
async def chat(request: ChatRequest):
    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        
        context = ""
        if request.repo_name:
            # Simple GitHub integration: fetch README as context
            try:
                repo = github_client.get_repo(request.repo_name)
                readme = repo.get_readme()
                context = f"Context from GitHub repository ({request.repo_name}):\n{readme.decoded_content.decode('utf-8')}\n\n"
            except Exception as e:
                context = f"Could not fetch context from GitHub: {str(e)}\n\n"

        prompt = f"{context}User message: {request.message}"
        response = model.generate_content(prompt)
        
        return {"response": response.text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

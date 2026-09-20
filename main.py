from pathlib import Path
from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
import duckdb
import os
import shutil

app = FastAPI(title="Florence Insights API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Get the absolute directory path of main.py
BASE_DIR = Path(__file__).resolve().parent

@app.get("/", response_class=HTMLResponse)
async def serve_homepage():
    html_path = BASE_DIR / "index.html"
    if not html_path.exists():
        return HTMLResponse(content=f"<h1>Error</h1><p>index.html not found in {BASE_DIR}</p>", status_code=500)
    
    with open(html_path, "r", encoding="utf-8") as f:
        return f.read()
      

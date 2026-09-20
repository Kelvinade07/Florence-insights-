from pathlib import Path
from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
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

BASE_DIR = Path(__file__).resolve().parent

@app.get("/", response_class=HTMLResponse)
async def serve_homepage():
    html_path = BASE_DIR / "index.html"
    if not html_path.exists():
        return HTMLResponse(content=f"<h1>Error</h1><p>index.html not found</p>", status_code=500)
    with open(html_path, "r", encoding="utf-8") as f:
        return f.read()

@app.post("/analyze")
async def analyze_file(file: UploadFile = File(...)):
    temp_path = f"temp_{file.filename}"
    
    with open(temp_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    conn = duckdb.connect(database=':memory:')
    
    try:
        # Load CSV using DuckDB
        conn.execute(f"CREATE VIEW raw_data AS SELECT * FROM read_csv_auto('{temp_path}', ignore_errors=true)")
        row_count = conn.execute("SELECT COUNT(*) FROM raw_data").fetchone()[0]
        schema = conn.execute("DESCRIBE raw_data").fetchall()
        cols = [col[0] for col in schema]
        
        # Convert preview data and replace NaN/NULL values with empty strings
        df = conn.execute("SELECT * FROM raw_data LIMIT 10").df()
        df = df.fillna("")  # Cleans missing values so JSON serialization doesn't crash
        preview_data = df.to_dict(orient="records")
        
        return {
            "status": "success",
            "total_rows": row_count,
            "columns": cols,
            "preview": preview_data
        }
    except Exception as e:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": str(e)}
        )
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)
      

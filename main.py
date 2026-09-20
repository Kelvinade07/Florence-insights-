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
        return HTMLResponse(content="<h1>Error</h1><p>index.html not found</p>", status_code=500)
    with open(html_path, "r", encoding="utf-8") as f:
        return f.read()

@app.post("/analyze")
async def analyze_file(file: UploadFile = File(...)):
    temp_path = f"temp_{file.filename}"
    
    with open(temp_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    # Set DuckDB memory limit strictly to 256MB to avoid Render out-of-memory crashes
    conn = duckdb.connect(database=':memory:')
    conn.execute("SET max_memory='256MB';")
    
    try:
        # Get total row count directly via DuckDB stream
        row_count = conn.execute(f"SELECT COUNT(*) FROM read_csv_auto('{temp_path}', ignore_errors=true)").fetchone()[0]
        
        # Extract column names
        schema = conn.execute(f"DESCRIBE SELECT * FROM read_csv_auto('{temp_path}', ignore_errors=true)").fetchall()
        cols = [col[0] for col in schema]
        
        # Fetch only 10 sample rows directly without loading entire dataset into Python Pandas
        preview_rows = conn.execute(f"SELECT * FROM read_csv_auto('{temp_path}', ignore_errors=true) LIMIT 10").fetchall()
        
        # Convert tuples to list of dictionaries
        preview_data = [dict(zip(cols, [str(item) if item is not None else "" for item in row])) for row in preview_rows]
        
        return {
            "status": "success",
            "total_rows": row_count,
            "columns": cols,
            "preview": preview_data
        }
    except Exception as e:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": f"Memory limit exceeded or invalid CSV: {str(e)}"}
        )
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)
                        

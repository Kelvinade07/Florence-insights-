from pathlib import Path
from fastapi import FastAPI, UploadFile, File, Form
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
        
    conn = duckdb.connect(database=':memory:')
    conn.execute("SET max_memory='256MB';")
    
    try:
        # Load raw data into DuckDB view
        conn.execute(f"CREATE VIEW raw_data AS SELECT * FROM read_csv_auto('{temp_path}', ignore_errors=true)")
        
        # Clean view: treat common dirty strings as NULL
        conn.execute("""
            CREATE VIEW clean_data AS 
            SELECT * REPLACE (
                CASE WHEN TRY_CAST(col AS VARCHAR) IN ('ERROR', 'UNKNOWN', 'null', 'None') THEN NULL ELSE col END AS col
            ) 
            FROM raw_data
        """)

        row_count = conn.execute("SELECT COUNT(*) FROM clean_data").fetchone()[0]
        schema = conn.execute("DESCRIBE clean_data").fetchall()
        cols = [col[0] for col in schema]
        
        preview_rows = conn.execute("SELECT * FROM clean_data LIMIT 10").fetchall()
        preview_data = [dict(zip(cols, [str(item) if item is not None else "" for item in row])) for row in preview_rows]

        # Extract top dynamic categorical column for Chart 1
        cat_col = cols[1] if len(cols) > 1 else cols[0]
        cat_counts = conn.execute(f"""
            SELECT "{cat_col}", COUNT(*) as count 
            FROM clean_data 
            WHERE "{cat_col}" IS NOT NULL AND "{cat_col}" != '' 
            GROUP BY "{cat_col}" 
            ORDER BY count DESC 
            LIMIT 5
        """).fetchall()

        # Extract secondary dynamic column for Chart 2
        sec_col = cols[5] if len(cols) > 5 else (cols[2] if len(cols) > 2 else cols[0])
        sec_counts = conn.execute(f"""
            SELECT "{sec_col}", COUNT(*) as count 
            FROM clean_data 
            WHERE "{sec_col}" IS NOT NULL AND "{sec_col}" != '' 
            GROUP BY "{sec_col}" 
            ORDER BY count DESC 
            LIMIT 5
        """).fetchall()

        chart_data = {
            "cat_title": f"Top Distributions: {cat_col}",
            "categories": {
                "labels": [str(r[0]) for r in cat_counts],
                "values": [r[1] for r in cat_counts]
            },
            "sec_title": f"Breakdown: {sec_col}",
            "secondary": {
                "labels": [str(r[0]) for r in sec_counts],
                "values": [r[1] for r in sec_counts]
            }
        }

        return {
            "status": "success",
            "total_rows": row_count,
            "columns": cols,
            "preview": preview_data,
            "chart_data": chart_data
        }
    except Exception as e:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": f"Processing error: {str(e)}"}
        )
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

@app.post("/ask")
async def ask_question(question: str = Form(...)):
    # Direct response placeholder for conversational queries
    return {
        "status": "success",
        "result": f"Query executed successfully for: '{question}'."
  }
      

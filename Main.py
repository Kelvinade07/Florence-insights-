from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
import duckdb
import os
import shutil

app = FastAPI(title="Florence Insights API")

# Enable CORS so your custom HTML frontend can talk to this API backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post("/analyze")
async def analyze_file(file: UploadFile = File(...)):
    temp_path = f"temp_{file.filename}"
    
    # Save uploaded file
    with open(temp_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    conn = duckdb.connect(database=':memory:')
    
    try:
        # Load CSV/Excel into DuckDB
        conn.execute(f"CREATE VIEW raw_data AS SELECT * FROM read_csv_auto('{temp_path}', ignore_errors=true)")
        
        # Fast aggregations on 1M+ rows using DuckDB
        row_count = conn.execute("SELECT COUNT(*) FROM raw_data").fetchone()[0]
        schema = conn.execute("DESCRIBE raw_data").fetchall()
        cols = [col[0] for col in schema]
        
        # Sample preview
        preview_data = conn.execute("SELECT * FROM raw_data LIMIT 10").df().to_dict(orient="records")
        
        return {
            "status": "success",
            "total_rows": row_count,
            "columns": cols,
            "preview": preview_data
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

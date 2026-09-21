from pathlib import Path
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
import duckdb
import os
import shutil
import json
from openai import OpenAI

app = FastAPI(title="Florence Insights API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).resolve().parent
ACTIVE_FILE_PATH = "current_dataset.csv"

# Global In-Memory Chat History
chat_history = []

# Initialize OpenAI Client (Make sure OPENAI_API_KEY is set in environment)
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def get_duckdb_conn():
    conn = duckdb.connect(database=':memory:')
    conn.execute("SET max_memory='256MB';")
    return conn

@app.get("/", response_class=HTMLResponse)
async def serve_homepage():
    html_path = BASE_DIR / "index.html"
    if not html_path.exists():
        return HTMLResponse(content="<h1>Error</h1><p>index.html not found</p>", status_code=500)
    with open(html_path, "r", encoding="utf-8") as f:
        return f.read()

def process_dataset(filepath: str):
    conn = get_duckdb_conn()
    conn.execute(f"CREATE VIEW raw_data AS SELECT * FROM read_csv_auto('{filepath}', ignore_errors=true)")
    
    conn.execute("""
        CREATE VIEW clean_data AS 
        SELECT * REPLACE (
            CASE WHEN TRY_CAST(col AS VARCHAR) IN ('ERROR', 'UNKNOWN', 'null', 'None', 'N/A', '') THEN NULL ELSE col END AS col
        ) 
        FROM raw_data
    """)

    row_count = conn.execute("SELECT COUNT(*) FROM clean_data").fetchone()[0]
    schema = conn.execute("DESCRIBE clean_data").fetchall()
    cols = [col[0] for col in schema]
    
    # Fetch first 50 rows for spreadsheet preview
    preview_rows = conn.execute("SELECT * FROM clean_data LIMIT 50").fetchall()
    preview_data = [dict(zip(cols, [str(item) if item is not None else "" for item in row])) for row in preview_rows]

    # Auto-generate basic charts
    cat_cols = [col_name for col_name, col_type, *_ in schema if "VARCHAR" in col_type.upper() or "STRING" in col_type.upper()]
    if not cat_cols:
        cat_cols = cols

    col1 = cat_cols[0]
    cat_counts = conn.execute(f'SELECT "{col1}", COUNT(*) as count FROM clean_data WHERE "{col1}" IS NOT NULL GROUP BY "{col1}" ORDER BY count DESC LIMIT 5').fetchall()

    col2 = cat_cols[1] if len(cat_cols) > 1 else cols[-1]
    sec_counts = conn.execute(f'SELECT "{col2}", COUNT(*) as count FROM clean_data WHERE "{col2}" IS NOT NULL GROUP BY "{col2}" ORDER BY count DESC LIMIT 5').fetchall()

    chart_data = {
        "cat_title": f"Top Distributions: {col1}",
        "categories": {"labels": [str(r[0]) for r in cat_counts], "values": [r[1] for r in cat_counts]},
        "sec_title": f"Breakdown: {col2}",
        "secondary": {"labels": [str(r[0]) for r in sec_counts], "values": [r[1] for r in sec_counts]}
    }

    return {
        "status": "success",
        "total_rows": row_count,
        "columns": cols,
        "preview": preview_data,
        "schema": [{"column": col[0], "type": col[1]} for col in schema],
        "chart_data": chart_data
    }

@app.post("/analyze")
async def analyze_file(file: UploadFile = File(...)):
    global chat_history
    try:
        with open(ACTIVE_FILE_PATH, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        chat_history = []  # Reset chat history on new upload
        data = process_dataset(ACTIVE_FILE_PATH)
        
        system_msg = f"Dataset loaded: {file.filename} with {data['total_rows']} rows and columns: {', '.join(data['columns'])}."
        chat_history.append({"role": "assistant", "content": system_msg})
        
        data["history"] = chat_history
        return data
    except Exception as e:
        return JSONResponse(status_code=400, content={"status": "error", "message": str(e)})

@app.post("/ask")
async def ask_question(question: str = Form(...)):
    global chat_history
    if not os.path.exists(ACTIVE_FILE_PATH):
        return JSONResponse(status_code=400, content={"status": "error", "message": "Please upload a dataset first."})

    try:
        conn = get_duckdb_conn()
        conn.execute(f"CREATE VIEW clean_data AS SELECT * FROM read_csv_auto('{ACTIVE_FILE_PATH}', ignore_errors=true)")
        schema_info = conn.execute("DESCRIBE clean_data").fetchall()
        columns_desc = ", ".join([f"{col[0]} ({col[1]})" for col in schema_info])

        # Add user query to conversation history
        chat_history.append({"role": "user", "content": question})

        # Step 1: Prompt AI to generate SQL
        prompt = f"""You are an expert Data Analyst AI. You are querying a DuckDB SQL view named `clean_data`.
Table Schema: {columns_desc}

Conversation History:
{json.dumps(chat_history[-5:])}

Write a single executable SQL query to answer the user's latest question. Return ONLY valid JSON with keys:
"sql": "<SQL QUERY>" or "explanation": "<EXPLANATION IF NO QUERY NEEDED>"
Do not include markdown blocks or code formatting outside JSON."""

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": prompt}],
            temperature=0.1
        )

        res_content = response.choices[0].message.content.strip()
        
        # Clean JSON markdown if generated
        if res_content.startswith("```"):
            res_content = res_content.replace("```json", "").replace("```", "").strip()
            
        ai_parsed = json.loads(res_content)

        if "sql" in ai_parsed and ai_parsed["sql"]:
            sql_query = ai_parsed["sql"]
            query_result = conn.execute(sql_query).fetchdf().head(10).to_dict(orient="records")
            
            # Step 2: Prompt AI to summarize SQL results in plain conversational text
            summary_prompt = f"""User Asked: {question}
Executed SQL: {sql_query}
Query Output: {json.dumps(query_result)}

Provide a concise, conversational explanation of the findings."""

            summary_res = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "system", "content": summary_prompt}]
            )
            ai_answer = summary_res.choices[0].message.content.strip()
        else:
            ai_answer = ai_parsed.get("explanation", "I couldn't generate a query for that question.")

        chat_history.append({"role": "assistant", "content": ai_answer})

        return {
            "status": "success",
            "history": chat_history
        }

    except Exception as e:
        err_msg = f"Analysis Error: {str(e)}"
        chat_history.append({"role": "assistant", "content": err_msg})
        return JSONResponse(status_code=200, content={"status": "success", "history": chat_history})
  

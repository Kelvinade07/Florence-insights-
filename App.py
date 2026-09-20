import streamlit as st
import duckdb
import plotly.express as px
import os
import polars as pl

# --- PAGE CONFIGURATION ---
st.set_page_config(
    page_title="Florence Insights | Florence.ai",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- HEADER & BRANDING ---
st.markdown("### **Florence.ai**")
st.title("⚡ Florence Insights")
st.caption("Automated 1M+ Row Data Cleaner, Engine & Executive Dashboard")
st.divider()

# --- SIDEBAR FILE UPLOADER ---
st.sidebar.header("📥 Data Input")
uploaded_file = st.sidebar.file_uploader(
    "Upload CSV or Excel File (1M+ Rows Supported)", 
    type=["csv", "xlsx", "xls"]
)

if uploaded_file:
    # Save uploaded file temporarily to disk for DuckDB fast disk-scanning
    file_ext = os.path.splitext(uploaded_file.name)[1].lower()
    temp_path = f"temp_upload{file_ext}"
    
    with open(temp_path, "wb") as f:
        f.write(uploaded_file.getbuffer())

    # Initialize DuckDB In-Memory C++ Engine
    conn = duckdb.connect(database=':memory:')

    try:
        # Load raw file into DuckDB
        if file_ext == '.csv':
            conn.execute(f"CREATE VIEW raw_data AS SELECT * FROM read_csv_auto('{temp_path}', ignore_errors=true)")
        else:
            df_polars = pl.read_excel(temp_path, engine="fastexcel")
            conn.register('raw_data', df_polars)

        row_count = conn.execute("SELECT COUNT(*) FROM raw_data").fetchone()[0]
        columns_info = conn.execute("DESCRIBE raw_data").fetchall()
        cols = [col[0] for col in columns_info]

        st.sidebar.success(f"File Loaded Successfully!")
        st.metric(label="Total Rows Detected", value=f"{row_count:,}")

        # --- DATA SANITIZATION CONFIGURATION ---
        st.subheader("🧹 Automatic Data Sanitization")
        
        c1, c2, c3 = st.columns(3)
        with c1:
            clean_currency = st.checkbox("Strip Currency & Percentage Symbols ($, %, ,)", value=True)
        with c2:
            trim_strings = st.checkbox("Trim String Whitespace", value=True)
        with c3:
            deduplicate = st.checkbox("Remove Duplicate Rows", value=True)

        # Build Dynamic SQL Sanitization Query
        cleaning_exprs = []
        for col in cols:
            col_safe = f'"{col}"'
            expr = col_safe
            if clean_currency:
                # Strip $, %, commas and convert to DOUBLE if numeric
                expr = f"REGEXP_REPLACE(CAST({col_safe} AS VARCHAR), '[$,% ]', '', 'g')"
            elif trim_strings:
                expr = f"TRIM(CAST({col_safe} AS VARCHAR))"
            
            cleaning_exprs.append(f"{expr} AS {col_safe}")

        sanitized_sql = f"SELECT {', '.join(cleaning_exprs)} FROM raw_data"
        if deduplicate:
            sanitized_sql = f"SELECT DISTINCT * FROM ({sanitized_sql})"

        # Execute Sanitization Pipeline in DuckDB
        conn.execute(f"CREATE VIEW cleaned_data AS {sanitized_sql}")

        # --- MAIN WORKFLOW TABS ---
        tab_dashboard, tab_preview, tab_code, tab_export = st.tabs([
            "📊 Executive Dashboard", 
            "📋 Cleaned Data Preview", 
            "🔍 Inspect Query & Code", 
            "⚙️ Export Data"
        ])

        # --- TAB 1: EXECUTIVE DASHBOARD ---
        with tab_dashboard:
            st.subheader("Auto-Generated Metrics & Visualizations")
            
            # Identify Schema Types
            schema = conn.execute("DESCRIBE cleaned_data").fetchall()
            all_cols = [r[0] for r in schema]
            
            # Simple numeric detection heuristic
            sample_df = conn.execute("SELECT * FROM cleaned_data LIMIT 100").df()
            numeric_cols = []
            for col in all_cols:
                try:
                    conn.execute(f'SELECT TRY_CAST("{col}" AS DOUBLE) FROM cleaned_data LIMIT 10')
                    numeric_cols.append(col)
                except:
                    pass
            
            categorical_cols = [c for c in all_cols if c not in numeric_cols]

            # High-Level KPIs
            k1, k2 = st.columns(2)
            if numeric_cols:
                target_num = k1.selectbox("Select Numerical Metric to Aggregate:", numeric_cols)
                agg_res = conn.execute(f'SELECT SUM(TRY_CAST("{target_num}" AS DOUBLE)), AVG(TRY_CAST("{target_num}" AS DOUBLE)) FROM cleaned_data').fetchone()
                
                total_val = agg_res[0] if agg_res[0] is not None else 0
                avg_val = agg_res[1] if agg_res[1] is not None else 0
                
                k1.metric(f"Total {target_num}", f"{total_val:,.2f}")
                k2.metric(f"Average {target_num}", f"{avg_val:,.2f}")

            # Visualizations
            v1, v2 = st.columns(2)
            
            with v1:
                if categorical_cols and numeric_cols:
                    group_cat = st.selectbox("Group By (Category):", categorical_cols, index=0)
                    agg_num = st.selectbox("Value Metric:", numeric_cols, index=0)
                    
                    chart_sql = f'''
                        SELECT "{group_cat}", SUM(TRY_CAST("{agg_num}" AS DOUBLE)) as Total 
                        FROM cleaned_data 
                        GROUP BY "{group_cat}" 
                        ORDER BY Total DESC 
                        LIMIT 10
                    '''
                    agg_df = conn.execute(chart_sql).df()
                    
                    fig_bar = px.bar(agg_df, x=group_cat, y="Total", title=f"Top 10 {group_cat} by {agg_num}")
                    st.plotly_chart(fig_bar, use_container_width=True)

            with v2:
                if len(numeric_cols) >= 2:
                    x_axis = st.selectbox("X-Axis Metric:", numeric_cols, index=0)
                    y_axis = st.selectbox("Y-Axis Metric:", numeric_cols, index=1 if len(numeric_cols) > 1 else 0)
                    
                    # Downsample 10k points directly in DuckDB for lag-free rendering
                    scatter_sql = f'SELECT TRY_CAST("{x_axis}" AS DOUBLE) AS "{x_axis}", TRY_CAST("{y_axis}" AS DOUBLE) AS "{y_axis}" FROM cleaned_data USING SAMPLE 10000'
                    sampled_df = conn.execute(scatter_sql).df()
                    
                    fig_scatter = px.scatter(sampled_df, x=x_axis, y=y_axis, title=f"Correlation Plot (Sampled 10k Rows)")
                    st.plotly_chart(fig_scatter, use_container_width=True)

        # --- TAB 2: DATA PREVIEW ---
        with tab_preview:
            st.subheader("Sanitized Dataset Preview (First 100 Rows)")
            preview_data = conn.execute("SELECT * FROM cleaned_data LIMIT 100").df()
            st.dataframe(preview_data, use_container_width=True)

        # --- TAB 3: CODE TRANSPARENCY (INSPECT QUERY) ---
        with tab_code:
            st.subheader("Transparent Execution Trace")
            st.write("Audit the exact DuckDB SQL query executed behind this pipeline:")
            st.code(sanitized_sql, language="sql")

        # --- TAB 4: EXPORTS ---
        with tab_export:
            st.subheader("Export Cleaned Dataset")
            export_fmt = st.radio("Select File Format:", ["Parquet (Optimized, Compressed)", "CSV"])
            
            if st.button("Generate Download Package"):
                if export_fmt == "Parquet":
                    out_path = "cleaned_data.parquet"
                    conn.execute(f"COPY cleaned_data TO '{out_path}' (FORMAT PARQUET)")
                    with open(out_path, "rb") as f:
                        st.download_button("Download Parquet File", f, file_name="cleaned_data.parquet")
                else:
                    out_path = "cleaned_data.csv"
                    conn.execute(f"COPY cleaned_data TO '{out_path}' (HEADER, DELIMITER ',')")
                    with open(out_path, "rb") as f:
                        st.download_button("Download CSV File", f, file_name="cleaned_data.csv")

    except Exception as err:
        st.error(f"Error executing data engine: {err}")
    finally:
        # Clean up temporary disk files
        if os.path.exists(temp_path):
            os.remove(temp_path)
else:
    st.info("👈 Upload a CSV or Excel file via the sidebar to launch Florence Insights.")
      

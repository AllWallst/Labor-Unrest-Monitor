import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import yfinance as yf
import requests
from thefuzz import process
from datetime import datetime, timedelta
import os

# --- PAGE CONFIGURATION ---
st.set_page_config(
    page_title="NLRB Labor Monitor", 
    layout="wide", 
    page_icon="🛠️"
)

# --- CONFIGURATION ---
DATA_FILE = "recent_filings.csv"

# --- HEADER ---
st.title("🛠️ The Labor Unrest Monitor")
st.markdown(f"""
**Status:** Monitoring local data feed.
**Data Source:** `{DATA_FILE}` (Updated daily via internal cron job).
""")

# --- 1. DATA LOADING FUNCTIONS ---

@st.cache_data(ttl=86400)
def get_sec_tickers():
    """Fetches the official list of all US public companies from the SEC."""
    headers = {'User-Agent': 'LaborMonitorProject/1.0 (contact@allwallst.com)'}
    try:
        r = requests.get("https://www.sec.gov/files/company_tickers.json", headers=headers)
        r.raise_for_status()
        df = pd.DataFrame.from_dict(r.json(), orient='index')
        return df
    except Exception as e:
        st.error(f"⚠️ SEC Ticker List unavailable: {e}")
        return pd.DataFrame()

# --- 2. MATCHING LOGIC ---

@st.cache_data(ttl=3600) # Cache the matching so it doesn't re-run on every click
def process_local_data(file_path, sec_df):
    """Reads local CSV, cleans it, and matches tickers."""
    
    # Load Data
    try:
        nlrb_df = pd.read_csv(file_path)
    except Exception as e:
        return pd.DataFrame(), f"Error reading CSV: {e}"

    if sec_df.empty: 
        return nlrb_df, "SEC Data missing, skipping matching."
    
    # standardizing column names (handle both Scraped and Exported formats)
    nlrb_df.columns = nlrb_df.columns.str.strip()
    
    # Map CSV columns to our standard names if they differ
    # Adjust these keys based on exactly what your cron job saves
    col_map = {
        'Case Name': 'Labor_Name', 
        'Date Filed': 'Date', 
        'No Employees': 'Employees',
        'Case Number': 'Case_Type'
    }
    nlrb_df = nlrb_df.rename(columns=col_map)
    
    # Filter for Union Votes (RC/RD/RM) immediately
    if 'Case_Type' in nlrb_df.columns:
        nlrb_df = nlrb_df[nlrb_df['Case_Type'].str.contains("-RC-|-RD-|-RM-", na=False)]
    
    # Convert Date
    nlrb_df['Date'] = pd.to_datetime(nlrb_df['Date'], errors='coerce')

    # Create lookup: Name -> Ticker
    company_map = dict(zip(sec_df['title'], sec_df['ticker']))
    public_names = list(company_map.keys())
    
    matched_data = []
    
    # Matching Loop
    for index, row in nlrb_df.iterrows():
        labor_name = str(row.get('Labor_Name', ''))
        
        if len(labor_name) < 4: continue

        # FUZZY MATCHING
        # score_cutoff=88 keeps accuracy high
        match_name, score = process.extractOne(labor_name, public_names, score_cutoff=88)
        
        if match_name:
            ticker = company_map[match_name]
            matched_data.append({
                "Date": row['Date'],
                "Labor_Name": labor_name,
                "Public_Name": match_name,
                "Ticker": ticker,
                "City": row.get('City'),
                "State": row.get('State'),
                "Employees": row.get('Employees'),
                "Case_Type": row.get('Case_Type')
            })
            
    if not matched_data:
        return pd.DataFrame(), "No public companies found in the latest batch."
        
    return pd.DataFrame(matched_data), None

# --- 3. MAIN APP EXECUTION ---

# Check if data exists
if not os.path.exists(DATA_FILE):
    st.warning(f"⚠️ Data file `{DATA_FILE}` not found.")
    st.info("System is waiting for the Cron Job to generate the initial dataset.")
    st.stop()

# Load SEC Data
df_sec = get_sec_tickers()

# Process Local CSV
with st.spinner('Processing daily data feed...'):
    df_final, error_msg = process_local_data(DATA_FILE, df_sec)

if df_final.empty:
    st.warning(error_msg)
    st.write("Raw File Preview:")
    st.dataframe(pd.read_csv(DATA_FILE).head())
    st.stop()

# --- 4. DASHBOARD UI ---

# Sidebar Selector
ticker_list = df_final['Ticker'].unique().tolist()
selected_ticker = st.sidebar.selectbox("Select Company to Analyze", ticker_list)

ticker_data = df_final[df_final['Ticker'] == selected_ticker]

# Metrics
m1, m2, m3 = st.columns(3)
m1.metric("Union Filings", len(ticker_data))
m2.metric("States", ticker_data['State'].nunique())
total_emp = pd.to_numeric(ticker_data['Employees'], errors='coerce').sum()
m3.metric("Employees Affected", f"{int(total_emp)}")

# Tabs
tab1, tab2, tab3 = st.tabs(["🗺️ Heatmap", "📉 Stock Overlay", "📄 Raw Data"])

with tab1:
    st.subheader(f"Union Hotspots: {selected_ticker}")
    state_counts = ticker_data.groupby('State').size().reset_index(name='Filings')
    
    fig_map = px.choropleth(
        state_counts,
        locations='State',
        locationmode="USA-states",
        color='Filings',
        scope="usa",
        color_continuous_scale="Reds"
    )
    # Dark Mode Fix
    fig_map.update_layout(
        geo=dict(bgcolor= 'rgba(0,0,0,0)', lakecolor='rgba(0,0,0,0)'),
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
        margin=dict(l=0, r=0, t=0, b=0)
    )
    st.plotly_chart(fig_map, use_container_width=True)

with tab2:
    st.subheader("Does this impact the stock?")
    if selected_ticker:
        end = datetime.now()
        start = end - timedelta(days=365)
        try:
            stock_df = yf.download(selected_ticker, start=start, end=end, progress=False)
            stock_df = stock_df.reset_index()
            
            if not stock_df.empty:
                fig = go.Figure()
                fig.add_trace(go.Scatter(x=stock_df['Date'], y=stock_df['Close'], name='Price', line=dict(color='#00CC96')))
                
                # Markers
                filing_dates = pd.to_datetime(ticker_data['Date']).dt.date.unique()
                for f_date in filing_dates:
                    mask = stock_df['Date'].dt.date == f_date
                    if mask.any():
                        price = stock_df.loc[mask, 'Close'].values[0]
                        fig.add_trace(go.Scatter(
                            x=[f_date], y=[price],
                            mode='markers',
                            marker=dict(color='#EF553B', size=12, symbol='diamond'),
                            name='Filing', showlegend=False
                        ))
                
                fig.update_layout(title=f"{selected_ticker} Price vs Union News", hovermode="x unified")
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.warning("Could not fetch stock data for this ticker.")
        except Exception as e:
            st.warning(f"Stock data error: {e}")

with tab3:
    st.dataframe(ticker_data)

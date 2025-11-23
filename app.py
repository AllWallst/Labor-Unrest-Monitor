import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import yfinance as yf
import requests
from thefuzz import process
from datetime import datetime, timedelta
import io

# --- PAGE CONFIGURATION ---
st.set_page_config(
    page_title="NLRB Labor Monitor", 
    layout="wide", 
    page_icon="🛠️"
)

# --- HEADER ---
st.title("🛠️ The Labor Unrest Monitor")
st.markdown("""
**Status:** The NLRB website now blocks simple scrapers. 
*   **Solution:** Download the official daily CSV from [NLRB Recent Filings](https://www.nlrb.gov/reports/graphs-data/recent-filings) and drop it below.
*   **Demo Mode:** Loading historical data for demonstration.
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

def load_demo_data():
    """Provides a fallback dataset so the app works immediately."""
    data = [
        {"Date": "2023-11-21", "Labor_Name": "Starbucks Coffee Co", "City": "Buffalo", "State": "NY", "Employees": 25, "Case_Type": "RC"},
        {"Date": "2023-11-20", "Labor_Name": "Starbucks Coffee Co", "City": "Mesa", "State": "AZ", "Employees": 15, "Case_Type": "RC"},
        {"Date": "2023-11-18", "Labor_Name": "Amazon Services LLC", "City": "Staten Island", "State": "NY", "Employees": 2000, "Case_Type": "RC"},
        {"Date": "2023-11-15", "Labor_Name": "Wells Fargo Bank", "City": "Albuquerque", "State": "NM", "Employees": 12, "Case_Type": "RC"},
        {"Date": "2023-11-10", "Labor_Name": "Apple Retail", "City": "Towson", "State": "MD", "Employees": 85, "Case_Type": "RC"},
    ]
    return pd.DataFrame(data)

# --- 2. MATCHING LOGIC ---

def match_tickers(nlrb_df, sec_df):
    """Matches messy government names to clean Stock Tickers."""
    if sec_df.empty: return nlrb_df
    
    # Clean up column names from the CSV upload
    nlrb_df.columns = nlrb_df.columns.str.strip()
    
    # Map CSV columns to our standard names
    # The NLRB CSV usually has columns: 'Case Name', 'Date Filed', 'City', 'State', 'No Employees'
    col_map = {
        'Case Name': 'Labor_Name', 
        'Date Filed': 'Date', 
        'No Employees': 'Employees',
        'Case Number': 'Case_Type'
    }
    nlrb_df = nlrb_df.rename(columns=col_map)
    
    # Convert Date
    nlrb_df['Date'] = pd.to_datetime(nlrb_df['Date'], errors='coerce')

    # Create lookup: Name -> Ticker
    company_map = dict(zip(sec_df['title'], sec_df['ticker']))
    public_names = list(company_map.keys())
    
    matched_data = []
    
    # Show progress
    progress_bar = st.progress(0, text="Analyzing filings...")
    total_rows = len(nlrb_df)
    
    for index, row in nlrb_df.iterrows():
        labor_name = str(row.get('Labor_Name', ''))
        
        if len(labor_name) < 4: continue

        # FUZZY MATCHING
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
            
        if index % 10 == 0:
            progress_bar.progress(min(index / total_rows, 1.0))
            
    progress_bar.empty()
    
    if not matched_data:
        return pd.DataFrame()
        
    return pd.DataFrame(matched_data)

# --- 3. MAIN APP EXECUTION ---

# SIDEBAR: DATA UPLOAD
st.sidebar.header("📁 Data Source")
uploaded_file = st.sidebar.file_uploader("Drop 'Recent Filings.csv' here", type="csv")

df_sec = get_sec_tickers()

if uploaded_file is not None:
    st.sidebar.success("✅ Custom Data Loaded")
    df_raw = pd.read_csv(uploaded_file)
    # Filter for RC/RD/RM (Union Votes) immediately
    if 'Case Number' in df_raw.columns:
         df_raw = df_raw[df_raw['Case Number'].str.contains("-RC-|-RD-|-RM-", na=False)]
    
    # Run Matcher
    if 'matched_df' not in st.session_state or st.sidebar.button("Re-run Matcher"):
        st.session_state['matched_df'] = match_tickers(df_raw.head(200), df_sec)
else:
    st.sidebar.info("Using Demo Data (Upload CSV for real results)")
    # For demo data, we simulate the matching result directly
    demo_df = load_demo_data()
    # Add dummy tickers for the demo
    demo_df['Ticker'] = ['SBUX', 'SBUX', 'AMZN', 'WFC', 'AAPL']
    demo_df['Public_Name'] = ['Starbucks Corp', 'Starbucks Corp', 'Amazon.com Inc', 'Wells Fargo & Co', 'Apple Inc.']
    st.session_state['matched_df'] = demo_df

df_final = st.session_state['matched_df']

if df_final.empty:
    st.warning("No public companies matched in the uploaded file.")
    st.stop()

# --- 4. DASHBOARD UI ---

ticker_list = df_final['Ticker'].unique().tolist()
selected_ticker = st.selectbox("Select Company to Analyze", ticker_list)

ticker_data = df_final[df_final['Ticker'] == selected_ticker]

# METRICS
m1, m2, m3 = st.columns(3)
m1.metric("Union Filings", len(ticker_data))
m2.metric("States", ticker_data['State'].nunique())
total_emp = pd.to_numeric(ticker_data['Employees'], errors='coerce').sum()
m3.metric("Employees Affected", f"{int(total_emp)}")

# TABS
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
    st.plotly_chart(fig_map, use_container_width=True)

with tab2:
    st.subheader("Does this impact the stock?")
    if selected_ticker:
        end = datetime.now()
        start = end - timedelta(days=365)
        
        # Safe fetch
        try:
            stock_df = yf.download(selected_ticker, start=start, end=end, progress=False)
            stock_df = stock_df.reset_index()
            
            if not stock_df.empty:
                fig = go.Figure()
                fig.add_trace(go.Scatter(x=stock_df['Date'], y=stock_df['Close'], name='Price', line=dict(color='blue')))
                
                # Add Markers
                filing_dates = pd.to_datetime(ticker_data['Date']).dt.date.unique()
                for f_date in filing_dates:
                    # Find closest price
                    mask = stock_df['Date'].dt.date == f_date
                    if mask.any():
                        price = stock_df.loc[mask, 'Close'].values[0]
                        fig.add_trace(go.Scatter(
                            x=[f_date], y=[price],
                            mode='markers',
                            marker=dict(color='red', size=12, symbol='star'),
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

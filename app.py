import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import yfinance as yf
import requests
from thefuzz import process
from datetime import datetime, timedelta
import io # Required for the new scraping method

# --- PAGE CONFIGURATION ---
st.set_page_config(
    page_title="NLRB Labor Monitor", 
    layout="wide", 
    page_icon="🛠️"
)

# --- HEADER & CSS ---
st.title("🛠️ The Labor Unrest Monitor")
st.markdown("""
**Alpha Strategy:** This tool monitors **National Labor Relations Board (NLRB)** filings.
Sudden spikes in "Representation Petitions" (Union Votes) can signal rising labor costs, internal friction, or operational risk before it hits the news.
""")

# --- 1. DATA FETCHING FUNCTIONS ---

@st.cache_data(ttl=86400) # Cache SEC tickers for 24 hours
def get_sec_tickers():
    """Fetches the official list of all US public companies from the SEC."""
    # FIX 1: SEC requires a User-Agent with an email to allow access
    headers = {
        'User-Agent': 'LaborMonitorProject/1.0 (contact@allwallst.com)',
        'Accept-Encoding': 'gzip, deflate',
        'Host': 'www.sec.gov'
    }
    url = "https://www.sec.gov/files/company_tickers.json"
    try:
        r = requests.get(url, headers=headers)
        r.raise_for_status() # Check for 403/404 errors
        data = r.json()
        # Convert SEC format to DataFrame
        df = pd.DataFrame.from_dict(data, orient='index')
        return df
    except Exception as e:
        st.error(f"Error fetching SEC tickers: {e}")
        return pd.DataFrame()

@st.cache_data(ttl=3600) # Cache NLRB data for 1 hour
def get_nlrb_data():
    """Scrapes the 'Recent Filings' table directly from the NLRB website."""
    url = "https://www.nlrb.gov/reports/graphs-data/recent-filings"
    
    # FIX 2: Better Headers to look like a real browser
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8'
    }
    
    try:
        # FIX 3: Fetch content with requests first, THEN pass to pandas
        # This fixes the "unexpected keyword argument 'headers'" error
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        
        # We wrap the text in StringIO so pandas treats it like a file
        dfs = pd.read_html(io.StringIO(response.text))
        
        if len(dfs) > 0:
            df = dfs[0]
            
            # FILTERING LOGIC:
            # We only want case numbers with "RC", "RD", or "RM" (Union Elections)
            # We filter out NaN case numbers first
            df = df.dropna(subset=['Case Number'])
            df_union = df[df['Case Number'].str.contains("-RC-|-RD-|-RM-", na=False)].copy()
            
            # Convert Dates
            df_union['Date Filed'] = pd.to_datetime(df_union['Date Filed'], errors='coerce')
            return df_union
        return pd.DataFrame()
    except Exception as e:
        st.error(f"Could not scrape NLRB.gov. Error: {e}")
        return pd.DataFrame()

# --- 2. INTELLIGENT MATCHING LOGIC ---

def match_tickers(nlrb_df, sec_df):
    """Matches messy government names to clean Stock Tickers."""
    if sec_df.empty:
        return pd.DataFrame()

    # Create lookup: Name -> Ticker
    company_map = dict(zip(sec_df['title'], sec_df['ticker']))
    public_names = list(company_map.keys())
    
    matched_data = []
    
    progress_text = "Matching government filings to Stock Tickers..."
    my_bar = st.progress(0, text=progress_text)
    total_rows = len(nlrb_df)
    
    for index, row in nlrb_df.iterrows():
        labor_name = str(row['Case Name'])
        
        if len(labor_name) < 4:
            continue

        # FUZZY MATCHING
        match_name, score = process.extractOne(labor_name, public_names, score_cutoff=88)
        
        if match_name:
            ticker = company_map[match_name]
            matched_data.append({
                "Date": row['Date Filed'],
                "Labor_Name": labor_name,
                "Public_Name": match_name,
                "Ticker": ticker,
                "City": row['City'],
                "State": row['State'],
                "Employees": row['No Employees'],
                "Case_Type": row['Case Number']
            })
            
        if index % 5 == 0:
            percent = min(index / total_rows, 1.0)
            my_bar.progress(percent, text=progress_text)
            
    my_bar.empty()
    return pd.DataFrame(matched_data)

# --- 3. MAIN APP EXECUTION ---

# A. Load Data
with st.spinner('Connecting to Federal Databases...'):
    df_sec = get_sec_tickers()
    df_nlrb = get_nlrb_data()

if df_nlrb.empty:
    st.warning("No recent union filings found. This might be a holiday or the government site is blocking the scraper.")
    st.stop()

if df_sec.empty:
    st.error("Failed to load SEC Ticker list. Cannot perform matching.")
    st.stop()

# B. Run Matching
if 'matched_df' not in st.session_state:
    # Limit to 100 for performance on Cloud Free Tier
    st.session_state['matched_df'] = match_tickers(df_nlrb.head(100), df_sec)
    
df_final = st.session_state['matched_df']

if df_final.empty:
    st.info("Data fetched successfully, but no public companies were found in the most recent 100 filings.")
    st.write("Here is the raw data from the government:")
    st.dataframe(df_nlrb.head())
    st.stop()

# --- 4. DASHBOARD UI ---

st.sidebar.header("Filter Settings")
ticker_list = df_final['Ticker'].unique().tolist()
selected_ticker = st.sidebar.selectbox("Select Company", ticker_list)

ticker_data = df_final[df_final['Ticker'] == selected_ticker]

# METRICS
col1, col2, col3 = st.columns(3)
col1.metric("Total Locations Filing", len(ticker_data))
col2.metric("States Affected", ticker_data['State'].nunique())
total_employees = pd.to_numeric(ticker_data['Employees'], errors='coerce').sum()
col3.metric("Total Employees Involved", f"{int(total_employees)}")

# TABS
tab1, tab2, tab3, tab4 = st.tabs(["🗺️ Heatmap", "📊 Trend", "📉 Price Correlation", "📄 Raw Data"])

with tab1:
    st.subheader(f"Geographic Hotspots: {selected_ticker}")
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
    st.subheader(f"Momentum: Filing Frequency")
    ticker_data['Week'] = ticker_data['Date'].dt.to_period('W').dt.start_time
    weekly_counts = ticker_data.groupby('Week').size().reset_index(name='Count')
    fig_bar = px.bar(weekly_counts, x='Week', y='Count', title="Weekly Union Petitions Filed")
    st.plotly_chart(fig_bar, use_container_width=True)

with tab3:
    st.subheader(f"Impact Analysis: {selected_ticker}")
    end_date = datetime.now()
    start_date = end_date - timedelta(days=365)
    stock_df = yf.download(selected_ticker, start=start_date, end=end_date, progress=False)
    stock_df = stock_df.reset_index()
    
    fig_combo = go.Figure()
    fig_combo.add_trace(go.Scatter(x=stock_df['Date'], y=stock_df['Close'], name="Stock Price", line=dict(color='blue')))
    
    filing_dates = ticker_data['Date'].dt.date.unique()
    for f_date in filing_dates:
        try:
            price_at_date = stock_df.loc[stock_df['Date'].dt.date == f_date]['Close'].values[0]
            fig_combo.add_trace(go.Scatter(
                x=[f_date], y=[price_at_date], mode='markers',
                marker=dict(color='red', size=10, symbol='diamond'),
                name='Union Filing', showlegend=False
            ))
        except IndexError: pass

    fig_combo.update_layout(title=f"{selected_ticker} Stock Price vs. Union Filings", hovermode="x unified")
    st.plotly_chart(fig_combo, use_container_width=True)

with tab4:
    st.dataframe(ticker_data.sort_values(by='Date', ascending=False), use_container_width=True)

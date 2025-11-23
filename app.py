import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import yfinance as yf
import requests
from thefuzz import process
from datetime import datetime, timedelta

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
    headers = {'User-Agent': 'Mozilla/5.0 (LaborMonitorProject)'}
    url = "https://www.sec.gov/files/company_tickers.json"
    try:
        r = requests.get(url, headers=headers)
        data = r.json()
        # Convert SEC format to DataFrame (SEC uses a dict with index keys)
        df = pd.DataFrame.from_dict(data, orient='index')
        return df
    except Exception as e:
        st.error(f"Error fetching SEC tickers: {e}")
        return pd.DataFrame()

@st.cache_data(ttl=3600) # Cache NLRB data for 1 hour
def get_nlrb_data():
    """Scrapes the 'Recent Filings' table directly from the NLRB website."""
    # The NLRB URL for recent filings
    url = "https://www.nlrb.gov/reports/graphs-data/recent-filings"
    # We need a browser-like header to avoid being blocked
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    try:
        # Pandas can scrape <table> tags directly from HTML
        dfs = pd.read_html(url, headers=headers)
        if len(dfs) > 0:
            df = dfs[0]
            
            # FILTERING LOGIC:
            # We only want case numbers with "RC", "RD", or "RM" 
            # These represent petitions for elections (Union Votes).
            # We exclude "C" cases (Unfair Labor Practice charges) as they are too noisy.
            df_union = df[df['Case Number'].str.contains("-RC-|-RD-|-RM-", na=False)].copy()
            
            # Convert Dates to datetime objects
            df_union['Date Filed'] = pd.to_datetime(df_union['Date Filed'], errors='coerce')
            return df_union
        return pd.DataFrame()
    except Exception as e:
        st.error(f"Could not scrape NLRB.gov. The site may be blocking the request or down. Error: {e}")
        return pd.DataFrame()

# --- 2. INTELLIGENT MATCHING LOGIC ---

def match_tickers(nlrb_df, sec_df):
    """
    Matches messy government names (e.g. 'Starbucks Coffee #2405') 
    to clean Stock Tickers (e.g. 'SBUX') using fuzzy logic.
    """
    # create a quick lookup dictionary: Name -> Ticker
    company_map = dict(zip(sec_df['title'], sec_df['ticker']))
    public_names = list(company_map.keys())
    
    matched_data = []
    
    # Progress bar for UI feedback
    progress_text = "Matching government filings to Stock Tickers..."
    my_bar = st.progress(0, text=progress_text)
    total_rows = len(nlrb_df)
    
    for index, row in nlrb_df.iterrows():
        labor_name = str(row['Case Name'])
        
        # Skip very short names to reduce false positives
        if len(labor_name) < 4:
            continue

        # FUZZY MATCHING:
        # extractOne finds the closest string in our SEC list to the Labor Filing name.
        # We use a score_cutoff of 88 to be safe (higher = stricter).
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
            
        # Update progress bar
        if index % 5 == 0:
            percent = min(index / total_rows, 1.0)
            my_bar.progress(percent, text=progress_text)
            
    my_bar.empty() # Clear bar when done
    return pd.DataFrame(matched_data)

# --- 3. MAIN APP EXECUTION ---

# A. Load Data
with st.spinner('Connecting to Federal Databases...'):
    df_sec = get_sec_tickers()
    df_nlrb = get_nlrb_data()

if df_nlrb.empty:
    st.warning("No recent union filings found. This might be a holiday or the government site is blocking the scraper.")
    st.stop()

# B. Run Matching (Session State avoids re-running matching if you change a filter)
if 'matched_df' not in st.session_state:
    # We take the top 100 rows for speed in this demo. In production, remove .head(100)
    st.session_state['matched_df'] = match_tickers(df_nlrb.head(100), df_sec)
    
df_final = st.session_state['matched_df']

if df_final.empty:
    st.write("Data fetched, but no public companies matched in the recent batch.")
    st.write("Raw Data Preview:", df_nlrb.head())
    st.stop()

# --- 4. DASHBOARD UI ---

# SIDEBAR FILTERS
st.sidebar.header("Filter Settings")
ticker_list = df_final['Ticker'].unique().tolist()
selected_ticker = st.sidebar.selectbox("Select Company", ticker_list)

# Filter the dataset
ticker_data = df_final[df_final['Ticker'] == selected_ticker]

# TOP METRICS ROW
col1, col2, col3 = st.columns(3)
col1.metric("Total Locations Filing", len(ticker_data))
col2.metric("States Affected", ticker_data['State'].nunique())
total_employees = pd.to_numeric(ticker_data['Employees'], errors='coerce').sum()
col3.metric("Total Employees Involved", f"{int(total_employees)}")

# --- VISUALIZATION TABS ---
tab1, tab2, tab3, tab4 = st.tabs(["🗺️ Heatmap", "📊 Trend Bar Chart", "📉 Price Correlation", "📄 Raw Data"])

# TAB 1: HEATMAP
with tab1:
    st.subheader(f"Geographic Hotspots: {selected_ticker}")
    state_counts = ticker_data.groupby('State').size().reset_index(name='Filings')
    
    fig_map = px.choropleth(
        state_counts,
        locations='State',
        locationmode="USA-states",
        color='Filings',
        scope="usa",
        color_continuous_scale="Reds",
        title=f"Where are {selected_ticker} employees unionizing?"
    )
    st.plotly_chart(fig_map, use_container_width=True)

# TAB 2: BAR CHART (MOMENTUM)
with tab2:
    st.subheader(f"Momentum: Filing Frequency")
    # Group by week to see spikes
    ticker_data['Week'] = ticker_data['Date'].dt.to_period('W').dt.start_time
    weekly_counts = ticker_data.groupby('Week').size().reset_index(name='Count')
    
    fig_bar = px.bar(
        weekly_counts,
        x='Week',
        y='Count',
        title="Weekly Union Petitions Filed",
        color='Count',
        color_continuous_scale='OrRd'
    )
    st.plotly_chart(fig_bar, use_container_width=True)

# TAB 3: STOCK OVERLAY
with tab3:
    st.subheader(f"Impact Analysis: {selected_ticker}")
    
    # 1. Get Stock Data
    end_date = datetime.now()
    start_date = end_date - timedelta(days=365)
    stock_df = yf.download(selected_ticker, start=start_date, end=end_date, progress=False)
    stock_df = stock_df.reset_index()
    
    # 2. Build Combo Chart
    fig_combo = go.Figure()
    
    # Line: Stock Price
    fig_combo.add_trace(
        go.Scatter(x=stock_df['Date'], y=stock_df['Close'], name="Stock Price", line=dict(color='blue'))
    )
    
    # Markers: Union Filings
    # We extract unique dates where a filing occurred
    filing_dates = ticker_data['Date'].dt.date.unique()
    
    # Loop to add markers at the specific dates
    for f_date in filing_dates:
        # Find stock price closest to that date
        try:
            price_at_date = stock_df.loc[stock_df['Date'].dt.date == f_date]['Close'].values[0]
            fig_combo.add_trace(
                go.Scatter(
                    x=[f_date], 
                    y=[price_at_date],
                    mode='markers',
                    marker=dict(color='red', size=10, symbol='diamond'),
                    name='Union Filing',
                    showlegend=False
                )
            )
        except IndexError:
            pass # Date might be a weekend/holiday

    fig_combo.update_layout(
        title=f"{selected_ticker} Stock Price vs. Union Filings",
        yaxis_title="Price ($)",
        hovermode="x unified"
    )
    st.plotly_chart(fig_combo, use_container_width=True)

# TAB 4: RAW DATA
with tab4:
    st.subheader("Detailed Filings Log")
    display_cols = ['Date', 'Labor_Name', 'City', 'State', 'Employees', 'Case_Type']
    st.dataframe(ticker_data[display_cols].sort_values(by='Date', ascending=False), use_container_width=True)

# Footer / Disclaimer
st.divider()
st.caption("Data Source: National Labor Relations Board (NLRB). Matches are generated via fuzzy logic algorithms and should be verified manually before trading.")

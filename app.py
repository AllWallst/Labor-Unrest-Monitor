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
st.set_page_config(page_title="NLRB Labor Monitor", layout="wide", page_icon="🛠️")

st.title("🛠️ The Labor Unrest Monitor")
st.markdown("""
**Alpha Strategy:** This tool scrapes **NLRB Representation Petitions** (union elections) and maps them to public tickers.
*   **Why it works:** Union filings often precede news cycles about labor costs or strikes.
*   **Data Source:** National Labor Relations Board (Live Scrape) & SEC Ticker List.
""")

# --- 1. DATA FETCHING ---

@st.cache_data(ttl=86400) # Cache for 24 hours
def get_sec_tickers():
    """Fetches the official list of all US public companies from the SEC."""
    headers = {'User-Agent': 'Mozilla/5.0 (LaborMonitorProject)'}
    url = "https://www.sec.gov/files/company_tickers.json"
    try:
        r = requests.get(url, headers=headers)
        data = r.json()
        # Convert SEC format to DataFrame
        df = pd.DataFrame.from_dict(data, orient='index')
        return df
    except Exception as e:
        st.error(f"Error fetching SEC tickers: {e}")
        return pd.DataFrame()

@st.cache_data(ttl=3600) # Cache for 1 hour
def get_nlrb_data():
    """Scrapes the 'Recent Filings' table directly from the NLRB website."""
    url = "https://www.nlrb.gov/reports/graphs-data/recent-filings"
    headers = {'User-Agent': 'Mozilla/5.0'}
    
    try:
        # We use pandas to scrape the HTML table directly
        dfs = pd.read_html(url, headers=headers)
        if len(dfs) > 0:
            df = dfs[0]
            # Filter for only "R" (Representation) cases - these are union votes
            # "C" cases are Unfair Labor Practices (also useful, but noisier)
            df_union = df[df['Case Number'].str.contains("-RC-|-RD-|-RM-", na=False)].copy()
            
            # Clean Dates
            df_union['Date Filed'] = pd.to_datetime(df_union['Date Filed'], errors='coerce')
            return df_union
        return pd.DataFrame()
    except Exception as e:
        st.error(f"Error scraping NLRB data. The government site might be down or blocking requests. Error: {e}")
        return pd.DataFrame()

# --- 2. INTELLIGENT MATCHING (THE ALPHA) ---

def match_tickers(nlrb_df, sec_df):
    """Matches messy government company names to clean Stock Tickers."""
    
    # Prepare the Master List of Public Companies
    # Create a dictionary: {"Apple Inc.": "AAPL", "Microsoft": "MSFT"}
    company_map = dict(zip(sec_df['title'], sec_df['ticker']))
    public_names = list(company_map.keys())
    
    matched_data = []
    
    # Create a progress bar because fuzzy matching is slow
    progress_bar = st.progress(0)
    total_rows = len(nlrb_df)
    
    for index, row in nlrb_df.iterrows():
        labor_name = str(row['Case Name'])
        
        # Fast skip: If name is too short or generic
        if len(labor_name) < 4:
            continue

        # Use 'extractOne' to find the closest match in the SEC list
        # We use a high cutoff (score > 85) to avoid bad matches
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
                "Unit_Count": row['No Employees']
            })
        
        # Update progress
        if index % 10 == 0:
            progress_bar.progress(min(index / total_rows, 1.0))
            
    progress_bar.empty()
    return pd.DataFrame(matched_data)

# --- LOAD DATA ---
with st.spinner('Fetching live government data...'):
    df_sec = get_sec_tickers()
    df_nlrb = get_nlrb_data()

if df_nlrb.empty:
    st.warning("No recent union filings found or NLRB site is blocking connections. Try again later.")
    st.stop()

# Run the Matcher (Only runs if we have data)
if 'matched_df' not in st.session_state:
    st.session_state['matched_df'] = match_tickers(df_nlrb.head(50), df_sec) # Limit to 50 for speed in demo
    
df_final = st.session_state['matched_df']

# --- 3. DASHBOARD ---

col1, col2 = st.columns([1, 3])

with col1:
    st.subheader("🔍 Filters")
    if not df_final.empty:
        ticker_list = df_final['Ticker'].unique().tolist()
        selected_ticker = st.selectbox("Select a Company", ticker_list)
        
        # Filter Logic
        filtered_df = df_final[df_final['Ticker'] == selected_ticker]
    else:
        st.write("No public companies matched in the last batch.")
        st.stop()

with col2:
    # METRICS ROW
    m1, m2, m3 = st.columns(3)
    m1.metric("Total Filings Found", len(filtered_df))
    m2.metric("Locations Affected", filtered_df['City'].nunique())
    # Sum of 'No Employees' (handling NaNs)
    employees_impacted = pd.to_numeric(filtered_df['Unit_Count'], errors='coerce').sum()
    m3.metric("Est. Employees Unionizing", f"{int(employees_impacted)}")

# --- VISUALIZATIONS ---

tab1, tab2, tab3 = st.tabs(["🗺️ Heatmap", "📉 Price Impact", "📄 Raw Filings"])

with tab1:
    st.subheader(f"Union Activity Map: {selected_ticker}")
    
    # Aggregate by State
    state_counts = filtered_df.groupby('State').size().reset_index(name='Count')
    
    fig_map = px.choropleth(
        state_counts,
        locations='State',
        locationmode="USA-states",
        color='Count',
        scope="usa",
        color_continuous_scale="Reds",
        title=f"Hot Zones for {selected_ticker} Union Drives"
    )
    st.plotly_chart(fig_map, use_container_width=True)

with tab2:
    st.subheader(f"Does this move the stock?")
    
    # Get Stock Data
    if selected_ticker:
        end = datetime.now()
        start = end - timedelta(days=365)
        stock_data = yf.download(selected_ticker, start=start, end=end, progress=False)
        stock_data = stock_data.reset_index()
        
        # Create Plot
        fig = go.Figure()
        
        # Stock Price Line
        fig.add_trace(go.Scatter(
            x=stock_data['Date'], 
            y=stock_data['Close'], 
            mode='lines', 
            name='Stock Price',
            line=dict(color='royalblue', width=2)
        ))
        
        # Add Markers for Filing Dates
        # We filter filing dates to match the stock chart range
        filing_dates = filtered_df['Date'].dt.date.unique()
        
        for date in filing_dates:
            # Find closest stock price to this date for the marker height
            # (Simple approximation for viz)
            try:
                closest_price = stock_data.loc[stock_data['Date'].dt.date == date]['Close'].values[0]
                fig.add_trace(go.Scatter(
                    x=[date], 
                    y=[closest_price],
                    mode='markers',
                    marker=dict(color='red', size=12, symbol='x'),
                    name='Filing Date',
                    showlegend=False
                ))
            except:
                pass # Date might be a weekend
                
        fig.update_layout(title=f"{selected_ticker} Price vs. Filing Events", hovermode="x unified")
        st.plotly_chart(fig, use_container_width=True)

with tab3:
    st.subheader("Latest Government Filings")
    st.dataframe(filtered_df[['Date', 'Labor_Name', 'City', 'State', 'Unit_Count']].sort_values(by='Date', ascending=False))

st.sidebar.info("Note: This tool matches messy government names (e.g. 'Starbucks Coffee #240') to tickers (SBUX) using fuzzy logic. Some matches may require manual verification.")

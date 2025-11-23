import requests
import pandas as pd
import os
from datetime import datetime

# URL for the NLRB Recent Filings
# Note: Since NLRB changes URLs occasionally, if this breaks, you check the "Export" button link on their site.
# For now, we will try to scrape the page properly or use the CSV export if available.
# Since the page is JS rendered, the most reliable "headless" way is often to use the API endpoint that feeds the table.
# However, for simplicity here, we will attempt a direct requests fetch with high-end headers.

OUTPUT_FILE = "recent_filings.csv"

def download_data():
    print(f"[{datetime.now()}] Starting Data Update...")
    
    # The URL that populates the data (often found via Network Tab in Developer Tools)
    # If this specific endpoint changes, you may need to update it.
    # Currently, this is the main report page.
    url = "https://www.nlrb.gov/reports/graphs-data/recent-filings"
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
    }

    try:
        response = requests.get(url, headers=headers, timeout=20)
        response.raise_for_status()
        
        # Use Pandas to parse table
        dfs = pd.read_html(response.text)
        
        if len(dfs) > 0:
            df = dfs[0]
            print(f"[{datetime.now()}] Successfully scraped {len(df)} rows.")
            
            # Save to CSV
            df.to_csv(OUTPUT_FILE, index=False)
            print(f"[{datetime.now()}] Saved to {OUTPUT_FILE}")
            return True
        else:
            print(f"[{datetime.now()}] Error: No tables found in response.")
            return False

    except Exception as e:
        print(f"[{datetime.now()}] Failed: {e}")
        return False

if __name__ == "__main__":
    download_data()

import requests
import time
import os
from datetime import datetime

# --- CONFIGURATION ---
# Replace this with the specific market ticker you are watching
TICKER = "KXNBAGAME-25DEC06NOPBKN-BKN"

# Public endpoint (No API Key needed for market data)
URL = f"https://api.elections.kalshi.com/trade-api/v2/markets/{TICKER}/orderbook"


def clear_screen():
    # Clears terminal for a clean dashboard look
    os.system('cls' if os.name == 'nt' else 'clear')


def get_orderbook():
    try:
        r = requests.get(URL)
        if r.status_code == 200:
            return r.json()['orderbook']
        else:
            return None
    except Exception as e:
        return None


def format_depth(level, side_data, is_ask=False):
    """Safely retrieves price/qty for a specific depth level."""
    # Safety check: If side_data is empty or None, return empty string
    if not side_data or len(side_data) <= level:
        return "       "

    # Get the item from the end of the list (Best prices are at the end)
    idx = -1 - level
    price, qty = side_data[idx]

    if is_ask:
        # CONVERSION LOGIC:
        # A "No" Bid at 40c == A "Yes" Ask at 60c
        price = 100 - price

    return f"{price:>2}¢ ({qty:<4})"


while True:
    data = get_orderbook()
    clear_screen()

    print(f"--- KALSHI LIVE BOOK: {TICKER} ---")
    print(f"Time: {datetime.now().strftime('%H:%M:%S')}")
    print("-" * 34)
    print("   BID (Qty)    ||    ASK (Qty)")
    print("-" * 34)

    if data:
        # FIX: Use 'or []' to handle cases where API returns None (null)
        yes_bids = data.get('yes') or []
        no_bids = data.get('no') or []  # 'No' bids act as 'Yes' asks

        # Show top 5 levels of depth
        for i in range(5):
            bid_str = format_depth(i, yes_bids, is_ask=False)
            ask_str = format_depth(i, no_bids, is_ask=True)
            print(f" {bid_str}  ||  {ask_str}")

        print("-" * 34)

        # Calculate Spread
        if yes_bids and no_bids:
            best_bid = yes_bids[-1][0]
            best_ask = 100 - no_bids[-1][0]
            spread = best_ask - best_bid
            print(f"SPREAD: {spread} cents")

            if spread > 5:
                print(">> WIDE SPREAD WARNING <<")
        else:
            print("Spread: N/A (One side empty)")
    else:
        print("Waiting for data...")

    # Don't spam the API too fast (Public endpoint limit)
    time.sleep(1)

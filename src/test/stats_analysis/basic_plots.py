import json
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import os
import argparse
from pandas import json_normalize


def load_and_process_json(filepath):
    """
    Loads the JSON file, handles column name conflicts, and 
    calculates per-tick volume changes.
    """
    if not os.path.exists(filepath):
        print(f"Error: File not found at {filepath}")
        return None

    print(f"Loading data from {filepath}...")

    with open(filepath, 'r') as f:
        data = json.load(f)

    meta_cols = [
        'timestamp', 'event_ticker', 'game_id', 'home_team', 'away_team',
        'score_home', 'score_away', 'score_diff', 'quarter', 'time_remaining_minutes'
    ]

    df = json_normalize(
        data,
        record_path=['markets'],
        meta=meta_cols,
        meta_prefix='game_',
        errors='ignore'
    )

    # Handle mixed timestamp formats automatically
    df['game_timestamp'] = pd.to_datetime(df['game_timestamp'], format='mixed')

    cols_to_numeric = ['price', 'volume',
                       'open_interest', 'yes_bid_prob', 'yes_ask_prob']
    for col in cols_to_numeric:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')

    df = df.sort_values(by=['market_id', 'game_timestamp'])

    # Calculate volume delta
    # Grouping by market_id ensures we don't diff across different bet types
    df['volume_delta'] = df.groupby('market_id')['volume'].diff().fillna(0)

    # DEBUG: Print volume stats to ensure we actually have data
    max_vol = df['volume_delta'].max()
    sum_vol = df['volume_delta'].sum()
    print(
        f"Volume Check -> Max Delta: {max_vol}, Total Volume Traded: {sum_vol}")

    df = df.dropna(subset=['price'])

    print(f"Data loaded: {len(df)} records found.")
    return df


def plot_interactive(df, output_dir=None):
    """
    Generates an interactive HTML plot using Plotly.
    """
    if 'game_home_team' not in df.columns:
        print("Error: 'game_home_team' column missing.")
        return

    home_team_name = df['game_home_team'].iloc[0]

    # Filter for home team
    if 'side' in df.columns:
        home_df = df[df['side'] == 'home'].copy()
    else:
        home_df = df[df['team'] == home_team_name].copy()

    if home_df.empty:
        print("No home team market data found.")
        return

    home_df = home_df.sort_values('game_timestamp')

    # Create subplots: Top plot has 2 Y-axes (Price & Score), Bottom is Volume
    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.05,  # Decreased spacing to keep alignment tight
        row_heights=[0.7, 0.3],
        specs=[[{"secondary_y": True}], [{"secondary_y": False}]]
    )

    # --- Trace 1: Price (Top Left Axis) ---
    fig.add_trace(
        go.Scatter(
            x=home_df['game_timestamp'],
            y=home_df['price'],
            name=f"{home_team_name} Price",
            line=dict(color='blue', width=1.5)
        ),
        row=1, col=1, secondary_y=False
    )

    # --- Trace 2: Score Diff (Top Right Axis) ---
    fig.add_trace(
        go.Scatter(
            x=home_df['game_timestamp'],
            y=home_df['game_score_diff'],
            name="Score Diff",
            line=dict(color='red', width=1.5, dash='dot', shape='hv')
        ),
        row=1, col=1, secondary_y=True
    )

    # --- Trace 3: Volume Delta (Bottom Axis) ---
    # FIXED: Changed from go.Bar to go.Scatter with fill='tozeroy'
    # This creates an "Area Chart" which is visible even at high zoom levels
    fig.add_trace(
        go.Scatter(
            x=home_df['game_timestamp'],
            y=home_df['volume_delta'],
            name="Vol Change",
            mode='lines',
            fill='tozeroy',           # Fills area under the line
            line=dict(color='gray', width=1),
            opacity=0.6
        ),
        row=2, col=1
    )

    # --- Layout & Styling ---
    fig.update_layout(
        title=f"Interactive Market Analysis: {home_team_name}",
        hovermode="x unified",
        height=800,
        xaxis_rangeslider_visible=False
    )

    # Y-Axis Labels
    fig.update_yaxes(title_text="Implied Prob (Price)", range=[
                     0, 1], row=1, col=1, secondary_y=False)
    fig.update_yaxes(title_text="Score Differential",
                     row=1, col=1, secondary_y=True)
    fig.update_yaxes(title_text="Volume Delta", row=2, col=1)

    # Save to HTML
    if output_dir:
        output_file = os.path.join(output_dir, 'interactive_chart.html')
        fig.write_html(output_file)
        print(f"Interactive chart saved to {output_file}")
    else:
        fig.write_html("interactive_chart.html")
        print("Interactive chart saved to interactive_chart.html")


def main():
    parser = argparse.ArgumentParser(description="Analyze NBA Market Data")
    parser.add_argument('filename', type=str,
                        help="The JSON filename in ../data/")
    args = parser.parse_args()

    script_dir = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.join(script_dir, '../data')
    file_path = os.path.join(data_dir, args.filename)

    df = load_and_process_json(file_path)

    if df is not None and not df.empty:
        plot_interactive(df, output_dir=script_dir)
    else:
        print("DataFrame is empty or could not be loaded.")


if __name__ == "__main__":
    main()

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
    df['volume_delta'] = df.groupby('market_id')['volume'].diff().fillna(0)

    # Clip negative values just in case of data glitches, but keep linear scale
    df['volume_delta'] = df['volume_delta'].clip(lower=0)

    df = df.dropna(subset=['price'])

    print(f"Data loaded: {len(df)} records found.")
    return df


def plot_interactive(df, output_path, volume_max):
    """
    Generates an interactive HTML plot using Plotly and saves to output_path.
    """
    if 'game_home_team' not in df.columns:
        print("Error: 'game_home_team' column missing.")
        return

    home_team_name = df['game_home_team'].iloc[0]
    game_id = df['game_game_id'].iloc[0]

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
        vertical_spacing=0.05,
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
    fig.add_trace(
        go.Scatter(
            x=home_df['game_timestamp'],
            y=home_df['volume_delta'],
            name="Vol Change",
            mode='lines',
            fill='tozeroy',
            line=dict(color='gray', width=1),
            opacity=0.6
        ),
        row=2, col=1
    )

    # --- Layout & Styling ---
    fig.update_layout(
        title=f"Game {game_id}: {home_team_name} (Vol Max={volume_max})",
        hovermode="x unified",
        height=800,
        xaxis_rangeslider_visible=False
    )

    # Y-Axis Labels
    fig.update_yaxes(title_text="Implied Prob (Price)", range=[
                     0, 1], row=1, col=1, secondary_y=False)
    fig.update_yaxes(title_text="Score Differential",
                     row=1, col=1, secondary_y=True)

    # FIXED: Absolute Volume Scale with User Defined Limit
    fig.update_yaxes(title_text="Volume Delta (Qty)",
                     range=[0, volume_max], row=2, col=1)

    # Save to HTML
    fig.write_html(output_path)
    print(f"Interactive chart saved to {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Analyze NBA Market Data")
    parser.add_argument('filename', type=str,
                        help="The JSON filename in ../data/")

    # New Argument: --volume-max
    parser.add_argument('--volume-max', type=int, default=5000,
                        help="The Y-axis limit for the volume chart (default: 5000)")

    args = parser.parse_args()

    # Paths
    script_dir = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.join(script_dir, '../data')
    file_path = os.path.join(data_dir, args.filename)

    df = load_and_process_json(file_path)

    if df is not None and not df.empty:
        # 1. Extract Game ID for filename
        try:
            game_id = str(df['game_game_id'].iloc[0])
        except (KeyError, IndexError):
            print("Warning: Could not extract game_id from data. Using 'unknown_game'.")
            game_id = "unknown_game"

        # 2. Construct Output Path
        plots_dir = os.path.join(data_dir, 'plots', 'basic')
        os.makedirs(plots_dir, exist_ok=True)

        output_path = os.path.join(plots_dir, f"{game_id}.html")

        # Pass the volume_max argument to the plotter
        plot_interactive(df, output_path, args.volume_max)
    else:
        print("DataFrame is empty or could not be loaded.")


if __name__ == "__main__":
    main()

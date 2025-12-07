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

    # Handle mixed timestamp formats
    df['game_timestamp'] = pd.to_datetime(df['game_timestamp'], format='mixed')

    # Ensure numeric columns
    cols_to_numeric = ['price', 'volume', 'open_interest', 'yes_bid_prob',
                       'yes_ask_prob', 'game_score_home', 'game_score_away', 'game_quarter']
    for col in cols_to_numeric:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')

    # Recalculate Score Diff Manually
    if 'game_score_home' in df.columns and 'game_score_away' in df.columns:
        df['calculated_score_diff'] = df['game_score_home'] - df['game_score_away']
    else:
        df['calculated_score_diff'] = df['game_score_diff']

    df = df.sort_values(by=['market_id', 'game_timestamp'])

    # Calculate volume delta
    df['volume_delta'] = df.groupby('market_id')['volume'].diff().fillna(0)
    df['volume_delta'] = df['volume_delta'].clip(lower=0)

    df = df.dropna(subset=['price'])

    print(f"Data loaded: {len(df)} records found.")
    return df


def plot_interactive(df, output_path, volume_max):
    """
    Generates an interactive HTML plot with toggleable reference zones.
    """
    if 'game_home_team' not in df.columns or 'game_away_team' not in df.columns:
        print("Error: Team names missing in data.")
        return

    home_team_name = df['game_home_team'].iloc[0]
    away_team_name = df['game_away_team'].iloc[0]
    game_id = df['game_game_id'].iloc[0]

    # --- Filter Data ---
    if 'side' in df.columns:
        home_df = df[df['side'] == 'home'].copy()
        away_df = df[df['side'] == 'away'].copy()
    else:
        home_df = df[df['team'] == home_team_name].copy()
        away_df = df[df['team'] == away_team_name].copy()

    if home_df.empty and away_df.empty:
        print("No market data found.")
        return

    home_df = home_df.sort_values('game_timestamp')
    away_df = away_df.sort_values('game_timestamp')
    timeline_df = home_df if not home_df.empty else away_df

    # Create Subplots
    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.05,
        row_heights=[0.7, 0.3],
        specs=[[{"secondary_y": True}], [{"secondary_y": False}]]
    )

    # --- Traces ---
    if not home_df.empty:
        fig.add_trace(go.Scatter(x=home_df['game_timestamp'], y=home_df['price'],
                                 name=f"{home_team_name} Price", line=dict(color='blue', width=1.5)),
                      row=1, col=1, secondary_y=False)

    if not away_df.empty:
        fig.add_trace(go.Scatter(x=away_df['game_timestamp'], y=away_df['price'],
                                 name=f"{away_team_name} Price", line=dict(color='red', width=1.5)),
                      row=1, col=1, secondary_y=False)

    fig.add_trace(go.Scatter(x=timeline_df['game_timestamp'], y=timeline_df['calculated_score_diff'],
                             name="Score Diff", line=dict(color='green', width=1.5, dash='dot', shape='hv'), opacity=0.8),
                  row=1, col=1, secondary_y=True)

    fig.add_trace(go.Scatter(x=timeline_df['game_timestamp'], y=timeline_df['volume_delta'],
                             name="Vol Change", mode='lines', fill='tozeroy', line=dict(color='gray', width=1), opacity=0.6),
                  row=2, col=1)

    # --- QUARTER LINES (Vertical) ---
    timeline_df['prev_quarter'] = timeline_df['game_quarter'].shift(
        1).fillna(0)
    quarter_changes = timeline_df[
        (timeline_df['game_quarter'] != timeline_df['prev_quarter']) &
        (timeline_df['game_quarter'] > 0)
    ]

    # We collect quarter shapes to add them permanently (we won't toggle these)
    shapes = []
    annotations = []

    for _, row in quarter_changes.iterrows():
        shapes.append(dict(
            type="line", x0=row['game_timestamp'], x1=row['game_timestamp'],
            y0=0, y1=1, xref="x", yref="paper",
            line=dict(color="black", width=1, dash="dash"), opacity=0.5
        ))
        annotations.append(dict(
            x=row['game_timestamp'], y=1.02, xref="x", yref="paper",
            text=f"Q{int(row['game_quarter'])}", showarrow=False, font=dict(size=10, color="black")
        ))

    # --- PRICE ZONES (Rectangles) ---
    # These are the specific shapes we want to toggle on/off
    # We define them but don't add them to 'layout.shapes' immediately if we want them managed by buttons,
    # but the easiest way to toggle is to update the 'visible' property of shapes.
    # However, Plotly buttons toggle TRACES easily, but SHAPES require a 'relayout' method which is trickier.
    #
    # TRICK: We will add the rectangles to the 'shapes' list, but we will create two layout states for the button:
    # 1. Shapes with rectangles visible
    # 2. Shapes without rectangles

    rect_low = dict(
        type="rect", x0=timeline_df['game_timestamp'].min(), x1=timeline_df['game_timestamp'].max(),
        y0=0.29, y1=0.31, xref="x", yref="y",
        fillcolor="black", opacity=0.1, line_width=0, layer="below"
    )

    rect_high = dict(
        type="rect", x0=timeline_df['game_timestamp'].min(), x1=timeline_df['game_timestamp'].max(),
        y0=0.69, y1=0.71, xref="x", yref="y",
        fillcolor="black", opacity=0.1, line_width=0, layer="below"
    )

    # List of shapes WITH the zones
    shapes_with_zones = shapes + [rect_low, rect_high]
    # List of shapes WITHOUT the zones
    shapes_without_zones = shapes

    # Start with zones visible
    fig.update_layout(shapes=shapes_without_zones, annotations=annotations)

    # --- INTERACTIVE TOGGLE BUTTON ---
    fig.update_layout(
        updatemenus=[
            dict(
                type="buttons",
                direction="left",
                buttons=[
                    dict(
                        label="Show Levels",
                        method="relayout",
                        args=["shapes", shapes_with_zones]
                    ),
                    dict(
                        label="Hide Levels",
                        method="relayout",
                        args=["shapes", shapes_without_zones]
                    )
                ],
                pad={"r": 10, "t": 10},
                showactive=True,
                x=0.05,
                xanchor="left",
                y=1.15,
                yanchor="top"
            ),
        ]
    )

    # --- Final Layout ---
    fig.update_layout(
        title=f"Game {game_id}: {home_team_name} vs {away_team_name}",
        hovermode="x unified",
        height=800,
        xaxis_rangeslider_visible=False
    )

    fig.update_yaxes(title_text="Implied Prob", range=[
                     0, 1], row=1, col=1, secondary_y=False)
    fig.update_yaxes(title_text="Score Diff", row=1, col=1, secondary_y=True)
    fig.update_yaxes(title_text="Volume Delta", range=[
                     0, volume_max], row=2, col=1)

    fig.write_html(output_path)
    print(f"Interactive chart saved to {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Analyze NBA Market Data")
    parser.add_argument('filename', type=str,
                        help="The JSON filename in ../data/")
    parser.add_argument('--volume-max', type=int,
                        default=5000, help="Y-axis limit for volume")
    args = parser.parse_args()

    script_dir = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.join(script_dir, '../data')
    file_path = os.path.join(data_dir, args.filename)

    df = load_and_process_json(file_path)

    if df is not None and not df.empty:
        try:
            game_id = str(df['game_game_id'].iloc[0])
        except:
            game_id = "unknown_game"

        plots_dir = os.path.join(data_dir, 'plots', 'basic')
        os.makedirs(plots_dir, exist_ok=True)
        output_path = os.path.join(plots_dir, f"{game_id}.html")

        plot_interactive(df, output_path, args.volume_max)
    else:
        print("DataFrame is empty.")


if __name__ == "__main__":
    main()

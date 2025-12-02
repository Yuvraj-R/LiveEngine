# src/app/main.py
from flask import Flask
from src.app.backtests import bp as backtests_bp

app = Flask(__name__)
app.register_blueprint(backtests_bp)

if __name__ == "__main__":
    app.run(debug=True)

# Chesso ♞

Streamlit chess app with a Neon (Postgres) database.

- **Click to move** – click a piece (legal destinations get dots), then click where it goes; illegal moves are ignored and pawn promotion shows a picker.
- **Save / Load vs AI** – 💾 Save stores the game in progress; 📂 Load (or choosing *Play vs AI* in the menu) lists your saved games to resume. Starting a new game or loading another asks whether to save the current one first. Finished games are saved automatically and appear under *Saved games*.
- **Play vs AI** – 3 levels (Easy / Medium / Hard), pick your colour. Finished games (or resignations) are saved automatically.
- **Training mode** – move both sides, undo/redo/flip, and save the line with a title.
- **Saved games** – replay any saved game move by move, download PGN, delete.

The AI is a built-in negamax/alpha-beta engine (`chess_ai.py`); no Stockfish install needed.

## Run
```bash
pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml   # then paste your Neon URL
streamlit run app.py
```
`DATABASE_URL` can also be an environment variable. Without it the app falls back to a local SQLite file (dev only). Tables are created automatically.

## Test
`pytest tests`

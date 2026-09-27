import chess
import chess.engine


stockfish_path = (
    r"Engines\Stockfish\stockfish-windows-x86-64-avx2"
    r"\stockfish\stockfish-windows-x86-64-avx2.exe"
)

engine = chess.engine.SimpleEngine.popen_uci(stockfish_path)

board = chess.Board()

info = engine.analyse(
    board,
    chess.engine.Limit(depth=10)
)

print("Stockfish is connected!")
print("Starting position evaluation:", info["score"])

engine.quit()
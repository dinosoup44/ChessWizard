"""Hand-authored legacy records; no personal games or recorded engine evidence."""
from contextlib import closing
from pathlib import Path
import ast
import json
import sqlite3
import chess


def synthetic_rows() -> list[dict]:
    """Build three synthetic records with positive, rejected and named-negative IDs.

    Returns:
        Detached row dictionaries using public developer-puzzle constants as data.
    """
    tree=ast.parse((Path(__file__).resolve().parents[2]/'seed_dev_test_puzzle.py').read_text(encoding='utf-8-sig'))
    constants={n.targets[0].id:ast.literal_eval(n.value) for n in tree.body
        if isinstance(n,ast.Assign) and isinstance(n.targets[0],ast.Name)}
    base=dict(game_id=4,move_id=4,candidate_id=4,user_color='white',color='white',
        source='synthetic',source_game_id='synthetic-legacy-4',ply_number=1,is_user_move=1,
        fen_before='r3k3/8/8/3N4/8/8/8/4K3 w - - 0 1',uci_played='e1f1',
        tactic_type='missed_fork',candidate_status='candidate',confidence=0.9,detector_version=2,
        solution_move_uci='d5c7',solution_move_san='Nc7+',solution_line='Nc7+ Kf7 Nxa8',
        created_at='2000-01-01',reviewed_at=None,notes='',metadata_json='{}')
    dev={**base,'game_id':-1,'move_id':-1,'candidate_id':-1,'source':constants['TEST_SOURCE'],
        'source_game_id':constants['TEST_SOURCE_GAME_ID'],'fen_before':constants['FEN_BEFORE'],
        'solution_move_uci':constants['SOLUTION_UCI'],'metadata_json':json.dumps({'developer_test':True,'detector':'developer_test'})}
    board=chess.Board(dev['fen_before'])
    dev['solution_move_san']=board.san(chess.Move.from_uci(dev['solution_move_uci']))
    dev['solution_line']=dev['solution_move_san']
    dev['uci_played']=next(m.uci() for m in board.legal_moves if m.uci()!=dev['solution_move_uci'])
    return [dev,base,{**base,'game_id':5,'move_id':5,'candidate_id':5,
        'source_game_id':'synthetic-legacy-5','candidate_status':'rejected'}]


def fixture_source(path: Path) -> None:
    """Create a synthetic legacy database, including the named developer puzzle.

    Args:
        path: New temporary database file owned by the calling test.

    Raises:
        sqlite3.DatabaseError: Fixture schema or row creation fails.
    """
    rows=synthetic_rows()
    with closing(sqlite3.connect(path)) as c:
        c.executescript('''
            CREATE TABLE games(game_id INTEGER PRIMARY KEY,user_color TEXT,source TEXT,source_game_id TEXT);
            CREATE TABLE moves(move_id INTEGER PRIMARY KEY,game_id INTEGER REFERENCES games,ply_number INTEGER,
                fen_before TEXT,color TEXT,uci_played TEXT,is_user_move INTEGER);
            CREATE TABLE tactic_candidates(candidate_id INTEGER PRIMARY KEY,move_id INTEGER REFERENCES moves,
                tactic_type TEXT,candidate_status TEXT,confidence REAL,detector_version INTEGER,
                solution_move_uci TEXT,solution_move_san TEXT,solution_line TEXT,created_at TEXT,reviewed_at TEXT,
                notes TEXT,metadata_json TEXT);
            CREATE TABLE analysis_coverage(move_id INTEGER,analysis_type TEXT,status TEXT);
            CREATE TABLE training_attempts(training_attempt_id INTEGER PRIMARY KEY,candidate_id INTEGER REFERENCES tactic_candidates);
        ''')
        for row in rows:
            for table,keys in (('games',('game_id','user_color','source','source_game_id')),
                    ('moves',('move_id','game_id','ply_number','fen_before','color','uci_played','is_user_move')),
                    ('tactic_candidates',('candidate_id','move_id','tactic_type','candidate_status','confidence',
                     'detector_version','solution_move_uci','solution_move_san','solution_line','created_at','reviewed_at','notes','metadata_json'))):
                c.execute(f"INSERT OR IGNORE INTO {table} ({','.join(keys)}) VALUES ({','.join('?' for _ in keys)})",
                    tuple(row[k] for k in keys))
        c.executemany('INSERT INTO training_attempts VALUES (?,?)',[(1,-1),(2,4)])
        c.commit()


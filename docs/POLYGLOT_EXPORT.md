# Polyglot export from the rich authoring graph

The .cwbook library is authoritative. A .bin contains only active, root-reachable
move entries; inactive/detached theory and rich editorial data remain in the library.

## Encoding

Each record is exactly 16 bytes in big-endian order: 64-bit key, 16-bit encoded
move, 16-bit weight, 32-bit learn. Learn is zero. Records sort deterministically by
unsigned key then encoded move. There is at most one equivalent (key, move) entry.

The move is destination square in bits 0–5, source in 6–11, promotion code in 12–14
(knight=1, bishop=2, rook=3, queen=4). Standard castling is encoded king-to-rook:
e1h1/e1a1 or e8h8/e8a8; the independent reader returns ordinary legal castling moves.
En passant uses its ordinary source/destination encoding.

Authoring weights **1–100 map directly to Polyglot weights 1–100**. No normalization,
engine quality estimate or preferred-flag bonus is applied. Preferred is separate
rich metadata; set its numerical weight intentionally if an external weighted
reader should favor it. Notes, references, instructional text, tags, versions and
the preferred flag are not carried by .bin.

Position hashing uses python-chess's official Polyglot implementation. Canonical
position state and the pinned-pawn EP detail are documented in
[OPENING_BOOK_ARCHITECTURE.md](OPENING_BOOK_ARCHITECTURE.md). The export implementation
was checked against the installed library and the
[official reader/hash source](https://python-chess.readthedocs.io/en/latest/_modules/chess/polyglot.html).

## Export boundary and verification

OpeningBookService supplies a coherent immutable snapshot. Export validates stored
hashes, legal edge/destination binding, weights, duplicates and hash collisions.
It creates a new .bin with exclusive mode; existing files cannot be overwritten.
If writing or verification fails, only the newly created failed output is removed.
There is no production-game write or cache/search fallback.

verify_polyglot independently reopens the file through chess.polyglot.open_reader.
It verifies file length and every raw record, then queries each exported position
through find_all(board) to check legal decoded moves, weights and branch counts.
This tests castling, all four promotion types, en passant and shared transpositions.
A terminal/leaf position with no outgoing moves has no Polyglot entry; it remains a
known rich-authoring position. An empty active graph yields a valid empty file.

The receipt records path, counts/bytes, file SHA256, book ID/version/revision and
snapshot hash. Timestamp/authoring note changes do not affect binary bytes unless
they change active exported moves/weights, while the rich snapshot identity can
change. Re-exporting unchanged active theory to another new file is byte-identical.

## Verified V1 fixture

The original isolated proof library has 28 edges over 28 positions. Export includes
28 entries from 22 source positions, **448 bytes**. Two independent export paths
produced SHA256:

cfeed61208d8d821b5abc43c902092b39b5bc0e0745567f57ef30b5248170cba

The graph has four branching positions and one transposition reference. The reader
returns the same legal move/weight sets at both transposed move orders. The separate
castling, promotion, EP, disabled, empty, overwrite and corruption regressions pass.

There is no .bin import/editor, book download, PGN branch import, engine book mode,
or bundled opening content in this foundation.


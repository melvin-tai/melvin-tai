"""
The great horned owl on the card, as code.

You design the LEFT half (columns 0..15); the right half is mirrored, so the
owl stays perfectly symmetric. Rows in FULL are written out as-is (the branch).
Run `python tools/owl_builder.py` to rewrite ascii.txt, then `python preview.py`.

Classes: "" outline · brow (blue, bold) · disc (facial disc) · dim (feathers)
         talon (amber) · branch · glare (vector eye) · beak (vector beak)
"""
from pathlib import Path
W, MID = 31, 15                  # columns 0..30, mirror axis = column 15
SWAP = str.maketrans("/\\()<>[]", "\\/)(><][")

# Each row: (col, text, cls) on the LEFT half (cols 0..15); the right half is mirrored.
# cls: "" outline, "brow", "disc", "dim" feathers, "talon", "branch", "glare" eye, "beak".
L = {
 0: [(3, ".", "brow")],
 1: [(3, "|", ""), (4, "\\_", "brow")],
 2: [(3, "|", ""), (6, "\\_", "brow")],
 3: [(3, "|", ""), (8, "\\_", "brow")],
 4: [(2, "/", ""), (10, "\\_", "brow")],
 5: [(1, "/", ""), (12, "\\_", "brow")],
 6: [(1, "|", ""), (14, "\\_", "brow")],
 7: [(1, "|", ""), (7, ".---.", "disc")],
 8: [(1, "|", ""), (6, "(", "disc"), (9, "@", "glare"), (12, ")", "disc")],
 9: [(1, "|", ""), (3, "\\", "disc"), (7, "'---'", "disc"), (15, "v", "beak")],
10: [(1, "|", ""), (4, "'-.", "disc")],
11: [(1, "|", ""), (7, "'--..____", "disc")],
12: [(1, "|", ""), (4, ".", ""), (9, "v", "dim"), (13, "v", "dim")],
13: [(0, "/", ""), (5, "\\", ""), (11, "v", "dim"), (15, "v", "dim")],
14: [(0, "|", ""), (2, "\\", "dim"), (6, "\\", ""), (9, "v", "dim"), (13, "v", "dim")],
15: [(0, "|", ""), (2, "\\\\", "dim"), (7, "|", ""), (11, "v", "dim"), (15, "v", "dim")],
16: [(0, "|", ""), (2, "\\\\\\", "dim"), (7, "|", ""), (9, "v", "dim"), (13, "v", "dim")],
17: [(0, "|", ""), (3, "\\\\\\", "dim"), (7, "|", ""), (11, "v", "dim"), (15, "v", "dim")],
18: [(0, "\\", ""), (4, "\\\\", "dim"), (7, ")", ""), (9, "v", "dim"), (13, "v", "dim")],
19: [(1, "\\", ""), (5, "\\", "dim"), (7, "/", ""), (11, "v", "dim"), (15, "v", "dim")],
20: [(2, "'.", ""), (6, "/", ""), (13, "v", "dim")],
21: [(4, "'-.___", ""), (10, "/|\\", "talon"), (13, "___", "")],
}
FULL = {   # asymmetric rows, written out in full
22: [(0, "━" * 31, "branch")],
23: [(21, "'-._", "branch")],
24: [(25, "'-.,", "branch")],
}

def blank(): return [[" ", ""] for _ in range(W)]

grid = {}
for r, items in L.items():
    row = blank()
    for c, text, cls in items:
        for i, ch in enumerate(text):
            row[c + i] = [ch, cls]
    for c in range(MID):
        ch, cls = row[c]
        if ch != " ":
            row[2 * MID - c] = [ch.translate(SWAP), cls]
    grid[r] = row
for r, items in FULL.items():
    row = grid.get(r, blank())
    for c, text, cls in items:
        for i, ch in enumerate(text):
            row[c + i] = [ch, cls]
    grid[r] = row

def markup(row):
    out, i = "", 0
    while i < len(row):
        ch, cls = row[i]; j = i
        while j < len(row) and row[j][1] == cls and (cls or True):
            if row[j][1] != cls: break
            j += 1
        text = "".join(c for c, _ in row[i:j])
        out += f"{{{cls}:{text}}}" if cls and text.strip() else text
        i = j
    return out.rstrip()

rows = [grid.get(r, blank()) for r in range(max(grid) + 1)]
plain = ["".join(c for c, _ in row).rstrip() for row in rows]
print("\n".join(f"{i:2d}|{l}" for i, l in enumerate(plain)))
(Path(__file__).resolve().parent.parent / "ascii.txt").open("w", encoding="utf-8").write("\n".join(markup(r) for r in rows) + "\n")

"""
Tetris - desktop version (Python + pygame-ce)
Run:  python tetris.py
Keys: Arrows = move / rotate, Space = hard drop, Z = rotate CCW,
      P = pause, M = music on/off, N = sounds on/off, Enter = start / restart
"""
import io
import math
import struct
import sys
import threading
import time
import wave

import pygame

COLS, ROWS = 10, 20
BLOCK = 30
BOARD_W, BOARD_H = COLS * BLOCK, ROWS * BLOCK
PANEL_W = 170
MARGIN = 14
WIN_W, WIN_H = BOARD_W + PANEL_W + MARGIN * 3, BOARD_H + MARGIN * 2

SHAPES = {
    "I": [[0, 0, 0, 0], [1, 1, 1, 1], [0, 0, 0, 0], [0, 0, 0, 0]],
    "J": [[1, 0, 0], [1, 1, 1], [0, 0, 0]],
    "L": [[0, 0, 1], [1, 1, 1], [0, 0, 0]],
    "O": [[1, 1], [1, 1]],
    "S": [[0, 1, 1], [1, 1, 0], [0, 0, 0]],
    "T": [[0, 1, 0], [1, 1, 1], [0, 0, 0]],
    "Z": [[1, 1, 0], [0, 1, 1], [0, 0, 0]],
}
COLORS = {
    "I": (0, 229, 229), "J": (58, 92, 240), "L": (240, 154, 46),
    "O": (240, 212, 34), "S": (62, 207, 74), "T": (164, 74, 240),
    "Z": (239, 74, 85),
}
BG = (17, 19, 31)
PANEL_BG = (13, 15, 26)
TEXT = (238, 238, 238)
DIM = (154, 160, 195)
ACCENT = (255, 213, 74)

MELODY = [
    (76, 1), (71, .5), (72, .5), (74, 1), (72, .5), (71, .5),
    (69, 1), (69, .5), (72, .5), (76, 1), (74, .5), (72, .5),
    (71, 1.5), (72, .5), (74, 1), (76, 1),
    (72, 1), (69, 1), (69, 2),
    (0, .5), (74, 1), (77, .5), (81, 1), (79, .5), (77, .5),
    (76, 1.5), (72, .5), (76, 1), (74, .5), (72, .5),
    (71, 1), (71, .5), (72, .5), (74, 1), (76, 1),
    (72, 1), (69, 1), (69, 2),
]
BEAT = 0.4


def tone_wav(freq, dur, vol=0.5, shape="sine"):
    sr = 22050
    n = int(sr * dur)
    frames = bytearray()
    attack = max(1, int(sr * 0.008))
    release = max(1, int(sr * 0.05))
    for i in range(n):
        t = i / sr
        if shape == "square":
            v = 1.0 if math.sin(2 * math.pi * freq * t) >= 0 else -1.0
        elif shape == "saw":
            v = 2.0 * ((freq * t) % 1.0) - 1.0
        else:
            v = math.sin(2 * math.pi * freq * t)
        env = min(1.0, i / attack)
        if i > n - release:
            env *= (n - i) / release
        frames += struct.pack("<h", int(max(-1.0, min(1.0, v * env * vol)) * 32767))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(bytes(frames))
    buf.seek(0)
    return buf


class Audio:
    def __init__(self):
        self.ok = False
        self.sfx_on = True
        self.music_on = True
        try:
            pygame.mixer.init(frequency=22050, size=-16, channels=1, buffer=512)
            self.ok = True
        except pygame.error:
            return
        self.sfx = {
            "move": pygame.mixer.Sound(file=tone_wav(200, 0.05, 0.10, "square")),
            "rotate": pygame.mixer.Sound(file=tone_wav(320, 0.07, 0.12, "square")),
            "soft": pygame.mixer.Sound(file=tone_wav(150, 0.04, 0.08, "square")),
            "hard": pygame.mixer.Sound(file=tone_wav(110, 0.15, 0.30, "saw")),
            "lock": pygame.mixer.Sound(file=tone_wav(90, 0.08, 0.16, "square")),
            "line": pygame.mixer.Sound(file=tone_wav(523, 0.12, 0.14, "square")),
            "level": pygame.mixer.Sound(file=tone_wav(659, 0.14, 0.16, "sine")),
            "over": pygame.mixer.Sound(file=tone_wav(196, 0.25, 0.18, "sine")),
        }
        self.note_cache = {}
        for midi, _ in MELODY:
            if midi > 0:
                f = 440 * 2 ** ((midi - 69) / 12)
                self.note_cache[midi] = pygame.mixer.Sound(
                    file=tone_wav(f, BEAT * 0.9, 0.10, "sine"))

    def play(self, name):
        if self.ok and self.sfx_on:
            self.sfx[name].play()

    def music_thread(self):
        while True:
            if not (self.ok and self.music_on and self.playing and not self.paused):
                time.sleep(0.1)
                continue
            for midi, beats in MELODY:
                if not (self.music_on and self.playing and not self.paused):
                    break
                if midi > 0:
                    self.note_cache[midi].play()
                time.sleep(beats * BEAT * 0.9)
            time.sleep(BEAT * 0.2)


def rotate_matrix(m, direction):
    n = len(m)
    return [[m[n - 1 - c][r] if direction > 0 else m[c][n - 1 - r]
             for c in range(n)] for r in range(n)]


class Game:
    def __init__(self):
        self.reset()

    def reset(self):
        self.board = [[None] * COLS for _ in range(ROWS)]
        self.bag = []
        self.score = 0
        self.lines = 0
        self.level = 1
        self.drop_interval = 800
        self.over = False
        self.playing = False
        self.paused = False
        self.piece = None
        self.next_type = None

    def refill_bag(self):
        types = list(SHAPES.keys())
        for i in range(len(types) - 1, 0, -1):
            j = (i * 7 + 3) % (i + 1)
            types[i], types[j] = types[j], types[i]
        self.bag.extend(types)

    def next_from_bag(self):
        if len(self.bag) < 2:
            self.refill_bag()
        return self.bag.pop(0)

    def spawn(self, kind):
        m = [row[:] for row in SHAPES[kind]]
        return {"type": kind, "matrix": m,
                "x": (COLS - len(m[0])) // 2, "y": 0}

    def collides(self, matrix, px, py):
        for r, row in enumerate(matrix):
            for c, cell in enumerate(row):
                if not cell:
                    continue
                x, y = px + c, py + r
                if x < 0 or x >= COLS or y >= ROWS:
                    return True
                if y >= 0 and self.board[y][x]:
                    return True
        return False

    def start(self):
        self.reset()
        self.refill_bag()
        self.playing = True
        self.next_type = self.next_from_bag()
        self.piece = self.spawn(self.next_type)
        self.next_type = self.next_from_bag()

    def move(self, dx):
        p = self.piece
        if p and not self.collides(p["matrix"], p["x"] + dx, p["y"]):
            p["x"] += dx
            return True
        return False

    def rotate(self, direction):
        p = self.piece
        if not p:
            return
        m = rotate_matrix(p["matrix"], direction)
        for kick in (0, -1, 1, -2, 2):
            if not self.collides(m, p["x"] + kick, p["y"]):
                p["matrix"] = m
                p["x"] += kick
                return True
        return False

    def soft_drop(self):
        p = self.piece
        if not p:
            return
        if not self.collides(p["matrix"], p["x"], p["y"] + 1):
            p["y"] += 1
            self.score += 1
        else:
            self.lock()
        return True

    def hard_drop(self):
        p = self.piece
        if not p:
            return
        dist = 0
        while not self.collides(p["matrix"], p["x"], p["y"] + 1):
            p["y"] += 1
            dist += 1
        self.score += dist * 2
        self.lock()

    def lock(self):
        p = self.piece
        for r, row in enumerate(p["matrix"]):
            for c, cell in enumerate(row):
                if cell:
                    y, x = p["y"] + r, p["x"] + c
                    if y < 0:
                        self.game_over()
                        return
                    self.board[y][x] = p["type"]
        self.clear_lines()
        self.piece = self.spawn(self.next_type)
        self.next_type = self.next_from_bag()
        if self.collides(self.piece["matrix"], self.piece["x"], self.piece["y"]):
            self.game_over()

    def clear_lines(self):
        cleared = 0
        for r in range(ROWS - 1, -1, -1):
            if all(self.board[r]):
                del self.board[r]
                self.board.insert(0, [None] * COLS)
                cleared += 1
        if cleared:
            self.score += [0, 100, 300, 500, 800][cleared] * self.level
            self.lines += cleared
            new_level = self.lines // 10 + 1
            if new_level > self.level:
                self.level = new_level
                self.drop_interval = max(120, 800 - (self.level - 1) * 70)
                return "level"
            return "line"
        return None

    def game_over(self):
        self.over = True
        self.playing = False

    def ghost_y(self):
        p = self.piece
        gy = p["y"]
        while not self.collides(p["matrix"], p["x"], gy + 1):
            gy += 1
        return gy


def draw_cell(surface, x, y, color, size):
    rect = pygame.Rect(x * size, y * size, size, size)
    pygame.draw.rect(surface, color, rect)
    highlight = rect.copy()
    highlight.height = max(2, size // 6)
    pygame.draw.rect(surface, tuple(min(255, c + 60) for c in color), highlight)
    shadow = pygame.Rect(x * size, y * size + size - max(2, size // 6),
                         size, max(2, size // 6))
    pygame.draw.rect(surface, tuple(max(0, c - 60) for c in color), shadow)
    pygame.draw.rect(surface, (0, 0, 0), rect, 1)


def draw_piece(surface, piece, ox, oy, size, alpha_color=None):
    for r, row in enumerate(piece["matrix"]):
        for c, cell in enumerate(row):
            if cell and piece["y"] + r >= 0:
                color = alpha_color or COLORS[piece["type"]]
                draw_cell(surface, ox + piece["x"] + c, oy + piece["y"] + r,
                          color, size)


def main():
    pygame.init()
    pygame.key.set_repeat(170, 45)
    screen = pygame.display.set_mode((WIN_W, WIN_H))
    pygame.display.set_caption("Tetris")
    clock = pygame.time.Clock()
    font_big = pygame.font.SysFont("arial", 30, bold=True)
    font_mid = pygame.font.SysFont("arial", 22, bold=True)
    font_small = pygame.font.SysFont("arial", 16)

    game = Game()
    audio = Audio()
    audio.playing = False
    audio.paused = False
    threading.Thread(target=audio.music_thread, daemon=True).start()

    drop_counter = 0.0
    last_time = time.time()

    while True:
        now = time.time()
        delta = (now - last_time) * 1000
        last_time = now

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit()
            if event.type != pygame.KEYDOWN:
                continue
            if event.key == pygame.K_RETURN and not game.playing:
                game.start()
                audio.playing = True
                continue
            if not game.playing:
                continue
            if event.key == pygame.K_LEFT:
                if game.move(-1):
                    audio.play("move")
            elif event.key == pygame.K_RIGHT:
                if game.move(1):
                    audio.play("move")
            elif event.key == pygame.K_DOWN:
                game.soft_drop()
                audio.play("soft")
                drop_counter = 0
            elif event.key in (pygame.K_UP, pygame.K_x):
                if game.rotate(1):
                    audio.play("rotate")
            elif event.key == pygame.K_z:
                if game.rotate(-1):
                    audio.play("rotate")
            elif event.key == pygame.K_SPACE:
                game.hard_drop()
                audio.play("hard")
                drop_counter = 0
            elif event.key in (pygame.K_p, pygame.K_ESCAPE):
                game.paused = not game.paused
                audio.paused = game.paused
            elif event.key == pygame.K_m:
                audio.music_on = not audio.music_on
            elif event.key == pygame.K_n:
                audio.sfx_on = not audio.sfx_on

        if game.playing and not game.paused and not game.over:
            drop_counter += delta
            if drop_counter > game.drop_interval:
                p = game.piece
                if not game.collides(p["matrix"], p["x"], p["y"] + 1):
                    p["y"] += 1
                else:
                    game.lock()
                drop_counter = 0

        screen.fill(BG)
        board_rect = pygame.Rect(MARGIN, MARGIN, BOARD_W, BOARD_H)
        pygame.draw.rect(screen, PANEL_BG, board_rect)
        pygame.draw.rect(screen, (61, 68, 112), board_rect, 2)

        board_layer = pygame.Surface((BOARD_W, BOARD_H), pygame.SRCALPHA)
        for r in range(ROWS):
            for c in range(COLS):
                if game.board[r][c]:
                    draw_cell(board_layer, c, r,
                              COLORS[game.board[r][c]], BLOCK)
        if game.piece and game.playing:
            gy = game.ghost_y()
            ghost = dict(game.piece)
            ghost["y"] = gy
            for r, row in enumerate(ghost["matrix"]):
                for c, cell in enumerate(row):
                    if cell and gy + r >= 0:
                        draw_cell(board_layer, ghost["x"] + c, gy + r,
                                  (*COLORS[game.piece["type"]], 60), BLOCK)
            for r, row in enumerate(game.piece["matrix"]):
                for c, cell in enumerate(row):
                    if cell and game.piece["y"] + r >= 0:
                        draw_cell(board_layer, game.piece["x"] + c,
                                  game.piece["y"] + r,
                                  COLORS[game.piece["type"]], BLOCK)
        screen.blit(board_layer, (MARGIN, MARGIN))

        panel_x = MARGIN * 2 + BOARD_W
        pygame.draw.rect(screen, PANEL_BG,
                         (panel_x, MARGIN, PANEL_W, BOARD_H))
        pygame.draw.rect(screen, (61, 68, 112),
                         (panel_x, MARGIN, PANEL_W, BOARD_H), 2)

        def panel_text(text, y, font=font_mid, color=TEXT):
            label = font.render(text, True, color)
            screen.blit(label, (panel_x + (PANEL_W - label.get_width()) // 2, y))

        panel_text("SCORE", MARGIN + 16, font_small, DIM)
        panel_text(str(game.score), MARGIN + 36)
        panel_text("LINES", MARGIN + 84, font_small, DIM)
        panel_text(str(game.lines), MARGIN + 104)
        panel_text("LEVEL", MARGIN + 152, font_small, DIM)
        panel_text(str(game.level), MARGIN + 172)
        panel_text("NEXT", MARGIN + 224, font_small, DIM)

        next_rect = pygame.Rect(panel_x + (PANEL_W - 96) // 2, MARGIN + 246, 96, 96)
        pygame.draw.rect(screen, BG, next_rect)
        if game.next_type:
            m = SHAPES[game.next_type]
            size = 20
            cells = [(r, c) for r, row in enumerate(m)
                     for c, cell in enumerate(row) if cell]
            min_c = min(c for _, c in cells)
            max_c = max(c for _, c in cells)
            min_r = min(r for r, _ in cells)
            max_r = max(r for r, _ in cells)
            ox = next_rect.x + (96 - (max_c - min_c + 1) * size) // 2 - min_c * size
            oy = next_rect.y + (96 - (max_r - min_r + 1) * size) // 2 - min_r * size
            for r, c in cells:
                draw_cell(screen, (ox + c * size) // size,
                          (oy + r * size) // size, COLORS[game.next_type], size)

        panel_text("M: music " + ("ON " if audio.music_on else "OFF"),
                   MARGIN + 380, font_small, DIM)
        panel_text("N: sound " + ("ON " if audio.sfx_on else "OFF"),
                   MARGIN + 404, font_small, DIM)
        panel_text("P: pause", MARGIN + 428, font_small, DIM)

        if not game.playing:
            overlay = pygame.Surface((WIN_W, WIN_H), pygame.SRCALPHA)
            overlay.fill((5, 5, 15, 200))
            screen.blit(overlay, (0, 0))
            title = font_big.render("TETRIS", True, ACCENT)
            screen.blit(title, ((WIN_W - title.get_width()) // 2, WIN_H // 2 - 80))
            if game.over:
                msg = font_mid.render(
                    "Game Over   Score: %d" % game.score, True, TEXT)
                screen.blit(msg, ((WIN_W - msg.get_width()) // 2, WIN_H // 2 - 10))
            hint = font_small.render("Press ENTER to play", True, DIM)
            screen.blit(hint, ((WIN_W - hint.get_width()) // 2, WIN_H // 2 + 40))
        elif game.paused:
            overlay = pygame.Surface((WIN_W, WIN_H), pygame.SRCALPHA)
            overlay.fill((5, 5, 15, 160))
            screen.blit(overlay, (0, 0))
            title = font_big.render("PAUSED", True, ACCENT)
            screen.blit(title, ((WIN_W - title.get_width()) // 2, WIN_H // 2 - 30))

        pygame.display.flip()
        clock.tick(60)


if __name__ == "__main__":
    main()

import pygame
import random
import math
import sys

# -----------------------------
# Configuration / Constants
# -----------------------------
WIDTH, HEIGHT = 1000, 600
FPS = 60

# Colors
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
SKY = (200, 220, 255)
SAND = (210, 185, 140)
DARK_OVERLAY = (0, 0, 0, 120)

# Positions
GROUND_Y = HEIGHT - 120
PLAYER_X = WIDTH * 0.25
ENEMY_X = WIDTH * 0.75
COWBOY_WIDTH, COWBOY_HEIGHT = 40, 100

# Deadeye timings (seconds)
MIN_DRAW_DELAY = 1.0
MAX_DRAW_DELAY = 3.5
DEADEYE_DURATION = 2.2  # seconds allowed to mark shots (1-3 recommended)
SHOT_RESOLVE_DELAY = 0.25  # seconds between each marked shot resolving visually

# Enemy stats (tweakable)
ENEMY_BASE_REACTION = 0.5  # base seconds before enemy fires after DRAW!
ENEMY_REACTION_VARIANCE = 0.3
ENEMY_ACCURACY = 0.7  # probability to hit if not disarmed/shot first

# Shot hitzones relative to enemy rect (for easier aiming & resolution)
HITZONES = {
    'head': lambda r: pygame.Rect(r.centerx - 12, r.top - 10, 24, 24),
    'chest': lambda r: pygame.Rect(r.centerx - 18, r.top + 20, 36, 36),
    'arm': lambda r: pygame.Rect(r.left - 8, r.top + 30, 28, 28),
    'leg': lambda r: pygame.Rect(r.centerx - 14, r.bottom - 30, 28, 30),
}

# -----------------------------
# Game States
# -----------------------------
STATE_STANDOFF = 'standoff'
STATE_DEADEYE = 'deadeye'
STATE_RESOLUTION = 'resolution'
STATE_RESULT = 'result'

# -----------------------------
# Utility functions
# -----------------------------

def clamp(n, minn, maxn):
    return max(min(maxn, n), minn)

# -----------------------------
# Classes
# -----------------------------
class Bullet:
    def __init__(self, x, y, direction):
        self.x = x
        self.y = y
        self.speed = 900
        self.direction = direction
        self.active = True

    def update(self, dt):
        self.x += self.speed * self.direction * dt
        if self.x < 0 or self.x > WIDTH:
            self.active = False

    def draw(self, surf):
        pygame.draw.circle(surf, (255,220,120), (int(self.x), int(self.y)), 4)

class Cowboy:
    def __init__(self, x, y, facing_right=False):
        self.x = x
        self.y = y
        self.facing_right = facing_right
        self.rect = pygame.Rect(0, 0, COWBOY_WIDTH, COWBOY_HEIGHT)
        self.rect.midbottom = (x, y)
        self.alive = True
        self.disarmed = False  # gun-hand shot

    def draw(self, surf):
        if not self.alive:
            # Draw slumped sprite (simple)
            pygame.draw.rect(surf, (80, 80, 80), self.rect)
            return
        # body
        pygame.draw.rect(surf, (120, 30, 10), self.rect)
        # hat
        hat = pygame.Rect(self.rect.left - 6, self.rect.top - 18, self.rect.width + 12, 14)
        pygame.draw.rect(surf, (60, 40, 20), hat)
        # gun (simple rectangle on the gun-hand side)
        if not self.disarmed:
            gw = pygame.Rect(0, 0, 18, 6)
            if self.facing_right:
                gw.midleft = (self.rect.right - 6, self.rect.top + 42)
            else:
                gw.midright = (self.rect.left + 6, self.rect.top + 42)
            pygame.draw.rect(surf, (40, 40, 40), gw)


class Tumbleweed:
    def __init__(self):
        self.x = random.choice([-50, WIDTH + 50])
        self.y = GROUND_Y - 30
        self.vx = random.uniform(30, 70) * (1 if self.x < 0 else -1)
        self.radius = random.randint(10, 18)

    def update(self, dt):
        self.x += self.vx * dt
        if self.x < -80 or self.x > WIDTH + 80:
            self.__init__()

    def draw(self, surf):
        pygame.draw.circle(surf, (150, 120, 80), (int(self.x), int(self.y)), self.radius, 2)


# -----------------------------
# Main Game Class
# -----------------------------

class WesternDuelGame:
    def __init__(self):
        pygame.init()
        pygame.display.set_caption('Western Deadeye Duel')
        self.screen = pygame.display.set_mode((WIDTH, HEIGHT))
        self.clock = pygame.time.Clock()
        self.font = pygame.font.SysFont('dejavusans', 28)
        self.large_font = pygame.font.SysFont('dejavusans', 64)

        # Audio placeholders (optional files)
        try:
            pygame.mixer.init()
            self.snd_shot = pygame.mixer.Sound('shot.wav')
            self.snd_disarm = pygame.mixer.Sound('disarm.wav')
        except Exception:
            self.snd_shot = None
            self.snd_disarm = None

        self.reset()

    def reset(self):
        # Entities
        self.player = Cowboy(PLAYER_X, GROUND_Y, facing_right=True)
        self.enemy = Cowboy(ENEMY_X, GROUND_Y, facing_right=False)
        self.tumbleweed = Tumbleweed()

        # Reticle
        self.reticle_pos = [ENEMY_X - 40, GROUND_Y - 60]
        self.reticle_speed = 300.0  # pixels/sec

        # Game state
        self.state = STATE_STANDOFF
        self.result_text = ''

        # Timers
        self.time_since_start = 0.0
        self.draw_time = random.uniform(MIN_DRAW_DELAY, MAX_DRAW_DELAY)
        self.deadeye_time_left = 0.0

        # Marks: list of dicts {pos: (x,y), zone: 'head'/'chest'..., timestamp}
        self.marks = []

        # Resolution helpers
        self.resolve_queue = []
        self.resolve_timer = 0.0

        # Enemy shot scheduling
        self.enemy_will_shoot = True
        self.enemy_shot_time = None

        # Early-shoot penalty flag
        self.early_shot = False

    def play_sound(self, snd):
        try:
            if snd:
                snd.play()
        except Exception:
            pass

    def update(self, dt):
        self.time_since_start += dt
        if self.state == STATE_STANDOFF:
            self.update_standoff(dt)
        elif self.state == STATE_DEADEYE:
            self.update_deadeye(dt)
        elif self.state == STATE_RESOLUTION:
            self.update_resolution(dt)
        # update ambient
        self.tumbleweed.update(dt)

    def update_standoff(self, dt):
        # When draw_time hits, switch to Deadeye
        if self.time_since_start >= self.draw_time:
            self.begin_deadeye()

    def begin_deadeye(self):
        self.state = STATE_DEADEYE
        self.deadeye_time_left = DEADEYE_DURATION
        # schedule enemy shot (enemy reaction happens in real-time but will be slowed visually)
        reaction = ENEMY_BASE_REACTION + random.uniform(-ENEMY_REACTION_VARIANCE, ENEMY_REACTION_VARIANCE)
        self.enemy_shot_time = self.time_since_start + reaction
        self.enemy_will_shoot = True
        # Player reticle starts near enemy center
        self.reticle_pos = [ENEMY_X - 40, GROUND_Y - 60]

    def update_deadeye(self, dt):
        # During Deadeye we allow player to move reticle and mark shots
        # Visual slow-motion: we simply reduce the effective dt for enemy timers
        self.deadeye_time_left -= dt
        if self.deadeye_time_left <= 0:
            # leave Deadeye and resolve shots
            self.begin_resolution()

        # Optionally clamp reticle to area around enemy
        self.reticle_pos[0] = clamp(self.reticle_pos[0], ENEMY_X - 120, ENEMY_X + 120)
        self.reticle_pos[1] = clamp(self.reticle_pos[1], GROUND_Y - 160, GROUND_Y - 20)

    def begin_resolution(self):
        self.state = STATE_RESOLUTION
        # Prepare resolve queue from marks (shots are resolved oldest-first). Add small delays between them.
        self.resolve_queue = list(self.marks)
        self.resolve_timer = 0.0

        # If enemy's scheduled shot time is in the future, keep it; otherwise, if it should have fired during deadeye,
        # it will fire now in resolution. We'll treat enemy shot as scheduled at enemy_shot_time.

    def update_resolution(self, dt):
        # increment the resolve timer and process shots in queue
        self.resolve_timer += dt
        # Enemy shooting: if enemy is scheduled to shoot and its shot time <= current game time, let it shoot
        # But if enemy is disarmed or dead, it won't.
        if self.enemy_will_shoot and self.enemy.alive and not self.enemy.disarmed:
            # enemy_shot_time is an absolute time in game seconds
            if self.time_since_start >= self.enemy_shot_time:
                self.enemy_fire()
                # ensure enemy fires only once
                self.enemy_will_shoot = False

        # Resolve player's marked shots in sequence with a small delay
        if self.resolve_queue and self.resolve_timer >= SHOT_RESOLVE_DELAY:
            shot = self.resolve_queue.pop(0)
            self.resolve_timer = 0.0
            self.resolve_player_shot(shot)
            # If the enemy died because of the shot, the remaining shots still 'fire' but have no effect.

        # Check for end conditions: if both no resolve queue and enemy won't/hasn't shot, then conclude
        if not self.resolve_queue and (not self.enemy_will_shoot or not self.enemy.alive):
            # small pause then show result
            pygame.time.set_timer(pygame.USEREVENT + 1, 800, loops=1)  # trigger result display

    def enemy_fire(self):
        # Enemy fires at player. Determine if hit based on accuracy and whether player was hit earlier.
        # We'll pick a simple mechanic: enemy picks a zone to aim for (randomly prefers center)
        if not self.player.alive:
            return
        hit = random.random() < ENEMY_ACCURACY
        if hit:
            # player hit -> die
            self.player.alive = False
            self.result_text = 'YOU LOSE'
            self.state = STATE_RESULT
        else:
            # miss (dramatic)
            pass
        self.play_sound(self.snd_shot)

    def resolve_player_shot(self, shot):
        # shot: dict with 'pos' and 'zone' keys
        # Visual: play shot sound, apply effects
        self.play_sound(self.snd_shot)

        # If enemy already dead, nothing happens
        if not self.enemy.alive:
            return

        # Resolve zone
        zone = shot.get('zone')
        if zone == 'arm':
            # Disarm the enemy (if we hit gun-hand)
            self.enemy.disarmed = True
            # if disarmed before enemy shot, enemy won't shoot
            if self.time_since_start <= self.enemy_shot_time:
                self.enemy_will_shoot = False
            # Visual feedback: enemy still alive
        elif zone == 'head' or zone == 'chest':
            # chest/head are lethal
            self.enemy.alive = False
            # If enemy not dead before it fired, but we killed it before its shot event, it'll never fire
            if self.time_since_start <= self.enemy_shot_time:
                self.enemy_will_shoot = False
            # set result
            self.result_text = 'YOU WIN'
            self.state = STATE_RESULT
        elif zone == 'leg':
            # Non-lethal, maybe slow enemy (not used further in this simple demo)
            # We can mark as wounded; not lethal in this simple version
            pass

    def handle_event(self, event):
        # Global event handler
        if event.type == pygame.QUIT:
            pygame.quit()
            sys.exit()
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_r:
                self.reset()
            if event.key == pygame.K_SPACE:
                self.on_fire()
        if event.type == pygame.MOUSEBUTTONDOWN:
            if event.button == 1:
                # Left click acts as mark/shot if in deadeye, otherwise it may be early-shoot
                self.on_fire()
        if event.type == pygame.USEREVENT + 1:
            # time to show result if not already set
            if self.state != STATE_RESULT:
                # If enemy is dead and player alive -> win; else lose
                if not self.enemy.alive and self.player.alive:
                    self.result_text = 'YOU WIN'
                elif not self.player.alive:
                    self.result_text = 'YOU LOSE'
                else:
                    # if both alive and enemy still exists, decide by who fired - default lose
                    self.result_text = 'YOU LOSE'
                self.state = STATE_RESULT

    def on_fire(self):
        # Called when player presses SPACE or clicks
        if self.state == STATE_STANDOFF:
            # Early shoot penalty
            self.early_shot = True
            self.player.alive = False
            self.result_text = 'YOU SHOT TOO EARLY! YOU LOSE'
            self.state = STATE_RESULT
            self.play_sound(self.snd_shot)
            return

        if self.state == STATE_DEADEYE:
            # Register a mark at the reticle's current position. Determine zone intersecting enemy
            shot_zone = self.get_zone_for_pos(tuple(self.reticle_pos))
            self.marks.append({'pos': tuple(self.reticle_pos), 'zone': shot_zone})
            # Visual feedback: small push to reticle
            self.reticle_pos[0] += 8 if self.player.facing_right else -8
            # Allow multiple marks within deadeye_time_left
            # Play mark sound if available
            return

        # In other states, pressing fire does nothing

    def get_zone_for_pos(self, pos):
        # Determine which hitzone that position intersects on the enemy
        ex_rect = self.enemy.rect
        for name, fn in HITZONES.items():
            hz = fn(ex_rect)
            if hz.collidepoint(pos):
                return name
        # Fallback mapping by Y coordinate
        x, y = pos
        rely = y - ex_rect.top
        if rely < 30:
            return 'head'
        elif rely < 70:
            return 'chest'
        elif rely < 110:
            return 'arm'
        else:
            return 'leg'

    def draw_background(self):
        self.screen.fill(SKY)
        # distant mountains
        pygame.draw.polygon(self.screen, (170, 160, 160), [(0, GROUND_Y - 140), (120, GROUND_Y - 240), (260, GROUND_Y - 140)])
        pygame.draw.polygon(self.screen, (160, 150, 150), [(160, GROUND_Y - 140), (360, GROUND_Y - 260), (520, GROUND_Y - 140)])
        # ground
        pygame.draw.rect(self.screen, SAND, (0, GROUND_Y, WIDTH, HEIGHT - GROUND_Y))
        # saloon simple rectangle
        saloon = pygame.Rect(WIDTH * 0.1, GROUND_Y - 120, 160, 120)
        pygame.draw.rect(self.screen, (90, 50, 30), saloon)
        door = pygame.Rect(saloon.centerx - 20, saloon.bottom - 60, 40, 60)
        pygame.draw.rect(self.screen, (60, 30, 15), door)
        # windows
        pygame.draw.rect(self.screen, (180, 210, 230), (saloon.left + 10, saloon.top + 18, 36, 30))
        pygame.draw.rect(self.screen, (180, 210, 230), (saloon.left + 110, saloon.top + 18, 36, 30))

    def draw(self):
        # If in deadeye, we dim the screen and draw UI differently
        self.draw_background()

        # Draw tumbleweed
        self.tumbleweed.draw(self.screen)

        # Draw cowboys
        self.player.draw(self.screen)
        self.enemy.draw(self.screen)

        # Draw horizon line/street
        pygame.draw.line(self.screen, (120, 100, 80), (0, GROUND_Y), (WIDTH, GROUND_Y), 2)

        # display messages depending on state
        if self.state == STATE_STANDOFF:
            prompt = 'Stand off... wait for the DRAW!'
            txt = self.font.render(prompt, True, BLACK)
            self.screen.blit(txt, (WIDTH // 2 - txt.get_width() // 2, 30))
            # show subtle cue about early fire
            hint = self.font.render('Don\'t press SPACE until DRAW!', True, (80, 80, 80))
            self.screen.blit(hint, (WIDTH // 2 - hint.get_width() // 2, 60))

        if self.state == STATE_DEADEYE:
            # slow motion overlay: dim and show timer
            overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
            overlay.fill(DARK_OVERLAY)
            self.screen.blit(overlay, (0, 0))
            de_txt = self.font.render('DEADEYE - Mark shots (SPACE). Time left: {:.1f}s'.format(max(0, self.deadeye_time_left)), True, WHITE)
            self.screen.blit(de_txt, (20, 20))

            # Draw marks so far
            for i, m in enumerate(self.marks):
                pygame.draw.circle(self.screen, (200, 30, 30), (int(m['pos'][0]), int(m['pos'][1])), 8, 2)
                num = self.font.render(str(i + 1), True, WHITE)
                self.screen.blit(num, (m['pos'][0] - 6, m['pos'][1] - 22))

            # Draw reticle
            pygame.draw.circle(self.screen, WHITE, (int(self.reticle_pos[0]), int(self.reticle_pos[1])), 12, 2)
            pygame.draw.line(self.screen, WHITE, (self.reticle_pos[0] - 18, self.reticle_pos[1]), (self.reticle_pos[0] + 18, self.reticle_pos[1]), 1)
            pygame.draw.line(self.screen, WHITE, (self.reticle_pos[0], self.reticle_pos[1] - 18), (self.reticle_pos[0], self.reticle_pos[1] + 18), 1)

        if self.state == STATE_RESOLUTION:
            info = self.font.render('Resolving shots...', True, BLACK)
            self.screen.blit(info, (20, 20))

            # Draw marked shots still to resolve
            y = 60
            for i, m in enumerate(self.resolve_queue):
                s = self.font.render(f'Mark {i+1}: {m["zone"]}', True, BLACK)
                self.screen.blit(s, (20, y))
                y += 26

        if self.state == STATE_RESULT:
            # big text in middle
            big = self.large_font.render(self.result_text, True, BLACK)
            self.screen.blit(big, (WIDTH // 2 - big.get_width() // 2, HEIGHT // 2 - big.get_height() // 2))
            sub = self.font.render('Press R to play again', True, BLACK)
            self.screen.blit(sub, (WIDTH // 2 - sub.get_width() // 2, HEIGHT // 2 + big.get_height() // 2 + 10))

        # Draw enemies health/status as small UI
        self.draw_enemy_ui()

        pygame.display.flip()

    def draw_enemy_ui(self):
        # small info box top-right
        boxw, boxh = 220, 90
        box = pygame.Rect(WIDTH - boxw - 12, 12, boxw, boxh)
        pygame.draw.rect(self.screen, (250, 245, 235), box)
        pygame.draw.rect(self.screen, (120, 100, 80), box, 2)
        lines = [f'Enemy: "Outlaw"', f'Alive: {self.enemy.alive}', f'Disarmed: {self.enemy.disarmed}']
        for i, l in enumerate(lines):
            t = self.font.render(l, True, BLACK)
            self.screen.blit(t, (box.left + 8, box.top + 8 + i * 24))

    def run(self):
        # main loop
        while True:
            dt = self.clock.tick(FPS) / 1000.0

            # Input and reticle control
            for event in pygame.event.get():
                self.handle_event(event)
            keys = pygame.key.get_pressed()

            # Movement controls for reticle
            if self.state == STATE_DEADEYE:
                # allow both arrow keys and mouse movement
                if keys[pygame.K_LEFT]:
                    self.reticle_pos[0] -= self.reticle_speed * dt
                if keys[pygame.K_RIGHT]:
                    self.reticle_pos[0] += self.reticle_speed * dt
                if keys[pygame.K_UP]:
                    self.reticle_pos[1] -= self.reticle_speed * dt
                if keys[pygame.K_DOWN]:
                    self.reticle_pos[1] += self.reticle_speed * dt
                if pygame.mouse.get_focused():
                    mx, my = pygame.mouse.get_pos()
                    # gentle blending to allow keyboard precision
                    self.reticle_pos[0] = self.reticle_pos[0] * 0.85 + mx * 0.15
                    self.reticle_pos[1] = self.reticle_pos[1] * 0.85 + my * 0.15

            # Update game state
            self.update(dt)

            # Draw everything
            self.draw()


# -----------------------------
# Run the game
# -----------------------------

if __name__ == '__main__':
    game = WesternDuelGame()
    game.run()

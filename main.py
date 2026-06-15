import math
from kaggle_environments.envs.orbit_wars.orbit_wars import Planet, Fleet

CENTER = (50.0, 50.0)
SUN_RADIUS = 10.5

# --- קבועי הגנה ---
MIN_PRODUCTION_TO_DEFEND = 2
DEFENDER_RESERVE_RATIO = 0.4

# --- קבועי Surplus dispatching ---
SURPLUS_RATIO = 0.7

# --- קבועי 4 שחקנים ---
WEAKEST_ENEMY_BONUS = 1.5

# --- Forward simulation ---
SIM_TURNS = 110
GAME_LENGTH = 500

# --- שלבי משחק ---
EARLY_GAME_TURNS = 80
MID_GAME_TURNS   = 250

# --- מכפילים לפי סוג מטרה ---
MULT_ENEMY_MOVING     = 2.05
MULT_ENEMY_STATIC     = 1.65
MULT_NEUTRAL_STATIC   = 1.4
MULT_NEUTRAL_ATTACKED = 0.7
MULT_FRESHLY_CAPTURED = 2.0

# --- SNIPE/CRASH ---
SNIPE_SHIPS_THRESHOLD = 0.3
CRASH_SHIPS_THRESHOLD = 0.4

# --- Elimination bonus ---
ELIMINATION_THRESHOLD = 110   # אויב עם פחות מזה ספינות — בונוס לסיים אותו
ELIMINATION_BONUS     = 2.5

# --- אופטימיזציית גודל צי ---
# מהירות אופטימלית: מספיק מהיר אבל לא מיותר גדול
MIN_FLEET_SIZE = 3   # לא שולחים פחות מזה

# --- באג כוכב נופל (comet bug) ---
# כוכב שמסלולו חותך את השמש עלול להימחק — נימנע מתקיפתו
COMET_ORBIT_THRESHOLD = 12.0  # רדיוס מסלול קטן מזה = סכנת comet


# ─────────────────────────── פונקציות עזר ───────────────────────────

def get_fleet_speed(ships, max_speed=6.0):
    if ships <= 0: return 0
    clamped_ships = min(ships, 1000)
    speed = 1.0 + (max_speed - 1.0) * ((math.log(clamped_ships) / math.log(1000)) ** 1.5)
    return min(speed, max_speed)


def optimal_fleet_size(dist, ships_needed, min_size=MIN_FLEET_SIZE):
    """
    סעיף 9: מוצא גודל צי שמגיע בדיוק בזמן — לא גדול מדי (איטי) ולא קטן מדי.
    מחזיר את הגודל האופטימלי שמגיע מהר אך לא יותר מ-ships_needed.
    """
    if dist <= 0:
        return max(min_size, ships_needed)

    # חפש את הגודל הקטן ביותר שמהירותו מספיקה להגיע בזמן סביר
    # arrival_time = dist / speed(fleet_size)
    # נרצה arrival_time קטן כמה שאפשר, אבל fleet_size <= ships_needed
    best_size = ships_needed
    best_time = dist / max(get_fleet_speed(ships_needed), 0.01)

    # נסה גדלים קטנים יותר — אם מגיעים באותו זמן (עגול לתור), עדיף קטן יותר
    for size in [ships_needed // 2, ships_needed // 3, min_size]:
        if size < min_size:
            continue
        speed = get_fleet_speed(size)
        if speed <= 0:
            continue
        t = dist / speed
        # קטן יותר = מהיר יותר, אבל אם המהירות דומה — שמור על המספר הנדרש
        if t < best_time * 0.85:  # מהיר ב-15%+ → עדיף
            best_time = t
            best_size = size

    return max(min_size, min(best_size, ships_needed))


def get_future_position(planet, t, angular_velocity):
    orbital_radius = math.hypot(planet.x - CENTER[0], planet.y - CENTER[1])
    if orbital_radius + planet.radius >= 50.0 or angular_velocity == 0:
        return planet.x, planet.y
    current_angle = math.atan2(planet.y - CENTER[1], planet.x - CENTER[0])
    future_angle = current_angle + angular_velocity * t
    fx = CENTER[0] + orbital_radius * math.cos(future_angle)
    fy = CENTER[1] + orbital_radius * math.sin(future_angle)
    return fx, fy


def is_planet_moving(planet, angular_velocity):
    orbital_radius = math.hypot(planet.x - CENTER[0], planet.y - CENTER[1])
    return (orbital_radius + planet.radius < 50.0) and (angular_velocity != 0)


def is_comet_risk(planet, angular_velocity):
    """
    סעיף 15: האם הכוכב נמצא בסכנת comet bug?
    כוכב עם מסלול קטן מאוד שעלול לחתוך את השמש.
    """
    orbital_radius = math.hypot(planet.x - CENTER[0], planet.y - CENTER[1])
    return orbital_radius < COMET_ORBIT_THRESHOLD and angular_velocity != 0


def get_interception_point(source, target, angular_velocity):
    moving = is_planet_moving(target, angular_velocity)
    for t in range(1, 200):
        fx, fy = get_future_position(target, t, angular_velocity)
        enemy_growth = target.production * t if target.owner != -1 else 0
        ships_needed = target.ships + enemy_growth + 1
        speed = get_fleet_speed(ships_needed)
        if not moving:
            dist = math.hypot(fx - source.x, fy - source.y)
            if dist <= speed * t:
                return fx, fy, ships_needed
        else:
            dist_to_intercept = math.hypot(fx - source.x, fy - source.y)
            if dist_to_intercept > speed * t:
                continue
            fleet_x, fleet_y = source.x, source.y
            for step in range(1, t + 1):
                angle = math.atan2(fy - fleet_y, fx - fleet_x)
                fleet_x += math.cos(angle) * speed
                fleet_y += math.sin(angle) * speed
                px, py = get_future_position(target, step, angular_velocity)
                if math.hypot(fleet_x - px, fleet_y - py) <= target.radius + speed:
                    return px, py, ships_needed
    return None, None, None


def intersects_sun(x1, y1, x2, y2):
    dx = x2 - x1
    dy = y2 - y1
    length_sq = dx ** 2 + dy ** 2
    if length_sq == 0:
        return False
    t = ((CENTER[0] - x1) * dx + (CENTER[1] - y1) * dy) / length_sq
    t = max(0.0, min(1.0, t))
    closest_x = x1 + t * dx
    closest_y = y1 + t * dy
    dist_sq = (closest_x - CENTER[0]) ** 2 + (closest_y - CENTER[1]) ** 2
    return dist_sq <= SUN_RADIUS ** 2


# ─────────────────────────── מודלינג יריב (סעיף 13) ───────────────────────────

def profile_enemies(planets, fleets, player):
    """
    סעיף 13: מאפיין כל אויב לפי קצב התרחבות, תוקפנות, ופיזור ציים.
    מחזיר dict: {owner: {"aggression", "expansion_rate", "total_strength"}}
    """
    enemy_owners = set(p.owner for p in planets if p.owner not in (-1, player))
    profiles = {}

    for owner in enemy_owners:
        owner_planets = [p for p in planets if p.owner == owner]
        owner_fleets  = [f for f in fleets  if f.owner == owner]

        total_ships  = sum(p.ships for p in owner_planets)
        total_prod   = sum(p.production for p in owner_planets)
        fleet_ships  = sum(f.ships for f in owner_fleets)
        num_planets  = len(owner_planets)

        # תוקפנות: כמה ספינות בציים ביחס לכוכבים
        aggression = fleet_ships / max(total_ships + fleet_ships, 1)

        # קצב התרחבות: production ביחס למספר כוכבים
        expansion_rate = total_prod / max(num_planets, 1)

        # חוזק כולל
        total_strength = total_ships + fleet_ships + total_prod * 10

        profiles[owner] = {
            "aggression": aggression,
            "expansion_rate": expansion_rate,
            "total_strength": total_strength,
            "num_planets": num_planets,
        }

    return profiles


# ─────────────────────────── סימולציה ───────────────────────────

def simulate_future(planets, fleets, player, angular_velocity, turns=SIM_TURNS):
    p_ships  = {p.id: float(p.ships)  for p in planets}
    p_owner  = {p.id: p.owner         for p in planets}
    p_prod   = {p.id: p.production    for p in planets}
    fell_at  = {p.id: None            for p in planets}
    keep_needed   = {p.id: 0          for p in planets}
    snipe_targets = {}
    # סעיף 14: RECAPTURE — כוכבים שנפלו לאחרונה
    recapture_targets = {}  # pid -> {"fell_at", "ships_then"}

    p_pos = {p.id: (p.x, p.y) for p in planets}

    active_fleets = []
    for f in fleets:
        best_planet = None
        best_dot = -1
        for p in planets:
            if p.owner == f.owner:
                continue
            dx = p.x - f.x
            dy = p.y - f.y
            dist = math.hypot(dx, dy)
            if dist == 0:
                continue
            dot = math.cos(f.angle) * (dx / dist) + math.sin(f.angle) * (dy / dist)
            if dot > best_dot:
                best_dot = dot
                best_planet = p
        if best_planet and best_dot > 0.95:
            active_fleets.append({
                "x": f.x, "y": f.y,
                "ships": f.ships,
                "owner": f.owner,
                "target_id": best_planet.id,
                "speed": get_fleet_speed(f.ships),
            })

    for t in range(1, turns + 1):
        remaining_fleets = []
        arrivals = {}

        for fl in active_fleets:
            tid = fl["target_id"]
            tx, ty = p_pos[tid]
            dist = math.hypot(fl["x"] - tx, fl["y"] - ty)
            if dist <= fl["speed"]:
                arrivals.setdefault(tid, []).append((fl["owner"], fl["ships"]))
            else:
                angle_to = math.atan2(ty - fl["y"], tx - fl["x"])
                fl["x"] += math.cos(angle_to) * fl["speed"]
                fl["y"] += math.sin(angle_to) * fl["speed"]
                remaining_fleets.append(fl)

        active_fleets = remaining_fleets

        for pid, arr_list in arrivals.items():
            current_owner = p_owner[pid]
            current_ships = p_ships[pid]

            by_owner = {}
            for (owner, ships) in arr_list:
                by_owner[owner] = by_owner.get(owner, 0) + ships

            for att_owner, att_ships in by_owner.items():
                if att_owner != current_owner and current_owner == player:
                    keep_needed[pid] = max(keep_needed[pid], int(att_ships) + 1)

            # SNIPE/CRASH
            enemy_total = sum(s for o, s in by_owner.items() if o != current_owner)
            if enemy_total > 0 and current_owner != player:
                ships_after_battle = abs(current_ships - enemy_total)
                original_ships = current_ships
                if original_ships > 0:
                    weakness_ratio = ships_after_battle / original_ships
                    if current_owner == -1 and weakness_ratio < SNIPE_SHIPS_THRESHOLD:
                        snipe_targets[pid] = {"eta": t, "ships_after": ships_after_battle, "type": "snipe"}
                    elif current_owner != -1 and weakness_ratio < CRASH_SHIPS_THRESHOLD:
                        snipe_targets[pid] = {"eta": t, "ships_after": ships_after_battle, "type": "crash"}

            friendly = by_owner.pop(current_owner, 0)
            current_ships += friendly

            prev_owner = current_owner
            for att_owner, att_ships in by_owner.items():
                if att_ships > current_ships:
                    if current_owner == player and fell_at[pid] is None:
                        fell_at[pid] = t
                    current_ships = att_ships - current_ships
                    current_owner = att_owner
                else:
                    current_ships -= att_ships

            # RECAPTURE: כוכב שלנו שנפל — רשום לכיבוש מחדש
            if prev_owner == player and current_owner != player and t <= 20:
                recapture_targets[pid] = {"fell_at": t, "ships_then": current_ships}

            p_ships[pid] = current_ships
            p_owner[pid] = current_owner

        for pid in p_ships:
            p_ships[pid] += p_prod[pid]

        for p in planets:
            nx, ny = get_future_position(p, t, angular_velocity)
            p_pos[p.id] = (nx, ny)

    planet_states = {
        pid: {"owner": p_owner[pid], "ships": p_ships[pid], "fell_at": fell_at[pid]}
        for pid in p_owner
    }
    return planet_states, keep_needed, snipe_targets, recapture_targets


def get_threats_from_simulation(sim_result, planets, player):
    planet_by_id = {p.id: p for p in planets}
    threats = []
    for pid, state in sim_result.items():
        p = planet_by_id[pid]
        if p.owner != player or state["fell_at"] is None:
            continue
        eta = state["fell_at"]
        our_ships_then = p.ships + p.production * eta
        deficit = max(1, int(our_ships_then * 0.5) + 1)
        threats.append({
            "planet": p, "eta": eta,
            "our_ships_at_eta": our_ships_then,
            "deficit": deficit, "will_fall": True,
        })
    return threats


def defend_planets(my_planets, threats, available_ships, keep_needed, moves, angular_velocity):
    used_as_defenders = set()
    sorted_threats = sorted(threats, key=lambda t: t["planet"].production, reverse=True)

    for threat in sorted_threats:
        if not threat["will_fall"]:
            continue
        planet = threat["planet"]
        if planet.production < MIN_PRODUCTION_TO_DEFEND:
            continue

        ships_needed = max(threat["deficit"], keep_needed.get(planet.id, 0))
        ships_gathered = 0

        potential_defenders = sorted(
            [p for p in my_planets if p.id != planet.id],
            key=lambda p: math.hypot(p.x - planet.x, p.y - planet.y)
        )

        for defender in potential_defenders:
            if ships_gathered >= ships_needed:
                break
            defender_keep = max(int(defender.ships * DEFENDER_RESERVE_RATIO), keep_needed.get(defender.id, 0))
            sendable = available_ships[defender.id] - defender_keep
            if sendable <= 0:
                continue
            fx, fy, _ = get_interception_point(defender, planet, angular_velocity)
            if fx is None or intersects_sun(defender.x, defender.y, fx, fy):
                continue
            to_send = min(sendable, ships_needed - ships_gathered)
            angle = math.atan2(fy - defender.y, fx - defender.x)
            moves.append([defender.id, angle, to_send])
            available_ships[defender.id] -= to_send
            ships_gathered += to_send
            used_as_defenders.add(defender.id)

    return used_as_defenders


def get_game_phase(turn, my_planets, all_planets, player):
    if turn <= EARLY_GAME_TURNS:
        return "early"
    enemy_planets = [p for p in all_planets if p.owner not in (-1, player)]
    my_prod    = sum(p.production for p in my_planets)
    enemy_prod = sum(p.production for p in enemy_planets)
    if turn <= MID_GAME_TURNS:
        return "mid"
    elif my_prod > enemy_prod * 1.5:
        return "finishing"
    else:
        return "total_war"


def get_target_multiplier(target, is_moving, game_phase, incoming_enemy_ships, player):
    is_neutral  = (target.owner == -1)
    is_attacked = incoming_enemy_ships > 0

    if is_neutral:
        mult = MULT_NEUTRAL_ATTACKED if is_attacked else MULT_NEUTRAL_STATIC
    else:
        mult = MULT_ENEMY_MOVING if is_moving else MULT_ENEMY_STATIC
        if target.ships < target.production * 3:
            mult = max(mult, MULT_FRESHLY_CAPTURED)

    if game_phase == "early" and is_neutral:
        mult *= 1.3
    elif game_phase == "finishing" and not is_neutral:
        mult *= 1.4
    elif game_phase == "total_war":
        mult *= 1.6

    return mult


# ─────────────────────────── AGENT ───────────────────────────

def agent(obs, config=None):
    moves = []

    # --- חילוץ נתונים ---
    player = obs.get("player", 0) if isinstance(obs, dict) else obs.player
    raw_planets = obs.get("planets", []) if isinstance(obs, dict) else obs.planets
    planets = [Planet(*p) for p in raw_planets]
    raw_fleets = obs.get("fleets", []) if isinstance(obs, dict) else obs.fleets
    fleets = [Fleet(*f) for f in raw_fleets]
    angular_velocity = obs.get("angular_velocity", 0.0) if isinstance(obs, dict) else obs.angular_velocity
    turn = obs.get("step", 0) if isinstance(obs, dict) else getattr(obs, "step", 0)

    my_planets     = [p for p in planets if p.owner == player]
    targets        = [p for p in planets if p.owner != player]
    neutral_planets = [p for p in planets if p.owner == -1]

    if not targets:
        return moves

    game_phase = get_game_phase(turn, my_planets, planets, player)

    # סעיף 13: מאפיין יריבים
    enemy_profiles = profile_enemies(planets, fleets, player)

    # --- Forward simulation ---
    sim_result, keep_needed, snipe_targets, recapture_targets = simulate_future(
        planets, fleets, player, angular_velocity, turns=SIM_TURNS
    )

    available_ships = {p.id: p.ships for p in my_planets}

    # --- התרחבות מוקדמת ---
    expansion_claimed = set()
    if neutral_planets and game_phase in ("early", "mid"):
        neutrals_per_mine = 3 if game_phase == "early" else 1
        for mine in my_planets:
            nearby_neutrals = sorted(
                neutral_planets,
                key=lambda p: math.hypot(p.x - mine.x, p.y - mine.y)
            )
            for neutral in nearby_neutrals[:neutrals_per_mine]:
                if neutral.id in expansion_claimed:
                    continue
                # סעיף 15: דלג על כוכבים בסכנת comet
                if is_comet_risk(neutral, angular_velocity):
                    continue
                fx, fy, ships_needed = get_interception_point(mine, neutral, angular_velocity)
                if fx is None or intersects_sun(mine.x, mine.y, fx, fy):
                    continue
                garrison = max(keep_needed.get(mine.id, 0), 5)
                sendable = available_ships[mine.id] - garrison
                if sendable >= ships_needed:
                    angle = math.atan2(fy - mine.y, fx - mine.x)
                    moves.append([mine.id, angle, ships_needed])
                    available_ships[mine.id] -= ships_needed
                    expansion_claimed.add(neutral.id)
                    break

    # --- הגנה ---
    threats = get_threats_from_simulation(sim_result, planets, player)
    used_as_defenders = defend_planets(
        my_planets, threats, available_ships, keep_needed, moves, angular_velocity
    )

    # --- מיפוי ציים ---
    # סעיף 11: incoming_allied_ships כולל גם ציים שנשלחו באותו תור
    incoming_enemy_to_target = {t.id: 0 for t in targets}
    incoming_allied_ships    = {t.id: 0 for t in targets}

    for f in fleets:
        for t in targets:
            angle_to_target = math.atan2(t.y - f.y, t.x - f.x)
            diff = (f.angle - angle_to_target + math.pi) % (2 * math.pi) - math.pi
            if abs(diff) < 0.2:
                if f.owner == player:
                    incoming_allied_ships[t.id] += f.ships
                else:
                    incoming_enemy_to_target[t.id] += f.ships
                break

    # גם ספינות שנשלחו בתור הנוכחי (מ-moves שכבר נוספו)
    for move in moves:
        source_id, angle, ships = move[0], move[1], move[2]
        for t in targets:
            angle_to_target = math.atan2(t.y - next((p.y for p in planets if p.id == source_id), 0),
                                          t.x - next((p.x for p in planets if p.id == source_id), 0))
            diff = (angle - angle_to_target + math.pi) % (2 * math.pi) - math.pi
            if abs(diff) < 0.2:
                incoming_allied_ships[t.id] += ships
                break

    # --- זיהוי האויב החלש ביותר ---
    enemy_owners = set(p.owner for p in planets if p.owner not in (-1, player))
    weakest_enemy = None
    if len(enemy_owners) > 1:
        weakest_enemy = min(enemy_owners, key=lambda o: enemy_profiles.get(o, {}).get("total_strength", 9999))

    # --- בניית רשימת מטרות ---
    attackers      = [p for p in my_planets if p.id not in used_as_defenders]
    planet_by_id   = {p.id: p for p in planets}
    remaining_turns = max(1, GAME_LENGTH - turn)

    target_scores = []

    def score_target(target, fx, fy, ships_needed, mult_override=None):
        """חישוב ציון אחיד לכל סוגי המטרות."""
        if is_comet_risk(target, angular_velocity):  # סעיף 15
            return None

        best_source = min(
            attackers,
            key=lambda p: math.hypot(p.x - target.x, p.y - target.y),
            default=None
        )
        if best_source is None:
            return None

        dist = math.hypot(fx - best_source.x, fy - best_source.y)

        # סעיף 9: גודל צי אופטימלי
        opt_size = optimal_fleet_size(dist, ships_needed)
        speed = get_fleet_speed(opt_size)
        arrival_turns = max(1, dist / speed) if speed > 0 else 999

        if mult_override is not None:
            mult = mult_override
        else:
            moving = is_planet_moving(target, angular_velocity)
            mult = get_target_multiplier(
                target, moving, game_phase,
                incoming_enemy_to_target.get(target.id, 0), player
            )
            if weakest_enemy is not None and target.owner == weakest_enemy:
                mult *= WEAKEST_ENEMY_BONUS

            # סעיף 10: Elimination bonus
            if target.owner != -1 and target.owner in enemy_profiles:
                profile = enemy_profiles[target.owner]
                if profile["total_strength"] < ELIMINATION_THRESHOLD:
                    mult *= ELIMINATION_BONUS

            # סעיף 13: התאמה לפי פרופיל אויב
            if target.owner != -1 and target.owner in enemy_profiles:
                profile = enemy_profiles[target.owner]
                if profile["aggression"] > 0.6:
                    mult *= 1.2  # אויב תוקפני — כדאי לחסל אותו מהר

        score = (target.production * mult * remaining_turns) / (ships_needed + arrival_turns * 0.5 + 1)
        return score, opt_size

    # מטרות רגילות
    for target in targets:
        if is_comet_risk(target, angular_velocity):  # סעיף 15
            continue

        best_source = min(
            attackers,
            key=lambda p: math.hypot(p.x - target.x, p.y - target.y),
            default=None
        )
        if best_source is None:
            continue

        fx, fy, required_ships = get_interception_point(best_source, target, angular_velocity)
        if fx is None or intersects_sun(best_source.x, best_source.y, fx, fy):
            continue

        # סעיף 12: ספינות קטנות מהירות לניטרליים קרובים
        dist_to_target = math.hypot(fx - best_source.x, fy - best_source.y)
        if target.owner == -1 and dist_to_target < 20 and required_ships <= 10:
            # שלח צי קטן ומהיר
            fast_size = max(MIN_FLEET_SIZE, required_ships)
            ships_needed = fast_size
        else:
            ships_needed = required_ships

        ships_needed -= incoming_allied_ships.get(target.id, 0)
        if ships_needed <= 0:
            continue

        total_available = sum(
            max(0, available_ships[p.id] - max(keep_needed.get(p.id, 0), 5))
            for p in attackers
        )
        if total_available < ships_needed:
            continue

        result = score_target(target, fx, fy, ships_needed)
        if result is None:
            continue
        score, opt_size = result
        target_scores.append((target, fx, fy, score, ships_needed))

    # SNIPE + CRASH
    for pid, snipe_info in snipe_targets.items():
        if pid not in planet_by_id:
            continue
        target = planet_by_id[pid]
        if target.owner == player or is_comet_risk(target, angular_velocity):
            continue

        fx, fy = get_future_position(target, snipe_info["eta"], angular_velocity)
        if intersects_sun(
            min(attackers, key=lambda p: math.hypot(p.x - target.x, p.y - target.y), default=Planet(0,0,0,0,0,0,0)).x,
            min(attackers, key=lambda p: math.hypot(p.x - target.x, p.y - target.y), default=Planet(0,0,0,0,0,0,0)).y,
            fx, fy
        ):
            continue

        snipe_ships = max(MIN_FLEET_SIZE, int(snipe_info["ships_after"]) + 1)
        ships_needed_snipe = snipe_ships - incoming_allied_ships.get(target.id, 0)
        if ships_needed_snipe <= 0:
            continue

        snipe_mult = 3.0 if snipe_info["type"] == "crash" else 2.5
        if game_phase in ("finishing", "total_war"):
            snipe_mult *= 1.3

        result = score_target(target, fx, fy, ships_needed_snipe, mult_override=snipe_mult)
        if result:
            score, _ = result
            target_scores.append((target, fx, fy, score, ships_needed_snipe))

    # סעיף 14: RECAPTURE — כוכבים שלנו שנפלו לאחרונה
    for pid, rc_info in recapture_targets.items():
        if pid not in planet_by_id:
            continue
        target = planet_by_id[pid]
        if target.owner == player or is_comet_risk(target, angular_velocity):
            continue

        fx, fy, rc_ships = get_interception_point(
            min(attackers, key=lambda p: math.hypot(p.x - target.x, p.y - target.y), default=None) or my_planets[0],
            target, angular_velocity
        )
        if fx is None:
            continue

        ships_needed_rc = rc_ships - incoming_allied_ships.get(target.id, 0)
        if ships_needed_rc <= 0:
            continue

        # בונוס גדול — כוכב שלנו שאבד, נרצה אותו בחזרה מיד
        rc_mult = 3.5
        result = score_target(target, fx, fy, ships_needed_rc, mult_override=rc_mult)
        if result:
            score, _ = result
            target_scores.append((target, fx, fy, score, ships_needed_rc))

    # --- תקיפה מתואמת ---
    target_scores.sort(key=lambda x: x[3], reverse=True)
    attacked_targets = set()

    for target, fx, fy, score, ships_needed in target_scores:
        if target.id in attacked_targets:
            continue

        ships_gathered = 0
        sorted_attackers = sorted(
            attackers,
            key=lambda p: math.hypot(p.x - target.x, p.y - target.y)
        )

        for attacker in sorted_attackers:
            if ships_gathered >= ships_needed:
                break
            garrison = max(keep_needed.get(attacker.id, 0), 5)
            if game_phase == "total_war":
                garrison = max(garrison // 2, 2)

            sendable = available_ships[attacker.id] - garrison
            if sendable <= 0:
                continue

            afx, afy, _ = get_interception_point(attacker, target, angular_velocity)
            if afx is None or intersects_sun(attacker.x, attacker.y, afx, afy):
                continue

            to_send = min(sendable, ships_needed - ships_gathered)
            angle = math.atan2(afy - attacker.y, afx - attacker.x)
            moves.append([attacker.id, angle, to_send])
            available_ships[attacker.id] -= to_send
            ships_gathered += to_send

        if ships_gathered > 0:
            # סעיף 11: עדכן incoming_allied_ships מיד אחרי שליחה
            incoming_allied_ships[target.id] = incoming_allied_ships.get(target.id, 0) + ships_gathered
            attacked_targets.add(target.id)

    # --- Surplus dispatching ---
    if game_phase != "total_war" and len(my_planets) > 1 and targets:
        def forward_base_score(p):
            return min(math.hypot(p.x - t.x, p.y - t.y) for t in targets)
        forward_base = min(my_planets, key=forward_base_score)

        for mine in my_planets:
            if mine.id in used_as_defenders:
                continue
            if mine.id == forward_base.id:
                continue
            garrison = max(keep_needed.get(mine.id, 0), 5)
            surplus = available_ships[mine.id] - garrison
            if surplus <= 0:
                continue
            already_sent = any(m[0] == mine.id for m in moves)
            if already_sent:
                continue
            my_dist   = forward_base_score(mine)
            fb_dist   = forward_base_score(forward_base)
            if fb_dist >= my_dist * 0.9:
                continue
            to_send = int(surplus * SURPLUS_RATIO)
            if to_send <= 0:
                continue
            fx, fy, _ = get_interception_point(mine, forward_base, angular_velocity)
            if fx is None or intersects_sun(mine.x, mine.y, fx, fy):
                continue
            angle = math.atan2(fy - mine.y, fx - mine.x)
            moves.append([mine.id, angle, to_send])
            available_ships[mine.id] -= to_send

    return moves
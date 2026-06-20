import math
from kaggle_environments.envs.orbit_wars.orbit_wars import Planet, Fleet

CENTER = (50.0, 50.0)
SUN_RADIUS = 10.5

# --- קבועי הגנה ---
MIN_PRODUCTION_TO_DEFEND = 2
DEFENDER_RESERVE_RATIO = 0.35

# --- קבועי Surplus dispatching ---
SURPLUS_RATIO = 0.68

# --- קבועי 4 שחקנים ---
WEAKEST_ENEMY_BONUS = 1.55

# --- Forward simulation ---
SIM_TURNS = 110
GAME_LENGTH = 500

# --- שלבי משחק ---
EARLY_GAME_TURNS = 80
MID_GAME_TURNS   = 250

# --- מכפילים לפי סוג מטרה ---
MULT_ENEMY_MOVING     = 2.15
MULT_ENEMY_STATIC     = 1.75
MULT_NEUTRAL_STATIC   = 1.48
MULT_NEUTRAL_ATTACKED = 0.68
MULT_FRESHLY_CAPTURED = 2.3

# --- SNIPE/CRASH ---
SNIPE_SHIPS_THRESHOLD = 0.28
CRASH_SHIPS_THRESHOLD = 0.38

# --- Elimination bonus ---
ELIMINATION_THRESHOLD = 115
ELIMINATION_BONUS     = 2.9

# --- אופטימיזציית גודל צי ---
MIN_FLEET_SIZE = 3

# --- comet bug ---
COMET_ORBIT_THRESHOLD = 12.0

# --- Early aggression ---
EARLY_NEUTRAL_LIMIT = 6

# --- Adaptive Garrison ---
BASE_GARRISON = 5


# ─────────────────────────── פונקציות עזר ───────────────────────────

def get_fleet_speed(ships, max_speed=6.0):
    if ships <= 0: return 0
    clamped_ships = min(ships, 1000)
    speed = 1.0 + (max_speed - 1.0) * ((math.log(clamped_ships) / math.log(1000)) ** 1.5)
    return min(speed, max_speed)


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
    orbital_radius = math.hypot(planet.x - CENTER[0], planet.y - CENTER[1])
    return orbital_radius < COMET_ORBIT_THRESHOLD and angular_velocity != 0


def get_interception_point(source, target, angular_velocity):
    """מחזיר (fx, fy, ships_needed, t_travel)"""
    moving = is_planet_moving(target, angular_velocity)
    for t in range(1, 200):
        fx, fy = get_future_position(target, t, angular_velocity)
        enemy_growth = target.production * t if target.owner != -1 else 0
        ships_needed = target.ships + enemy_growth + 1
        speed = get_fleet_speed(ships_needed)
        if not moving:
            dist = math.hypot(fx - source.x, fy - source.y)
            if dist <= speed * t:
                return fx, fy, ships_needed, t
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
                    return px, py, ships_needed, t
    return None, None, None, None


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


def profile_enemies(planets, fleets, player):
    enemy_owners = set(p.owner for p in planets if p.owner not in (-1, player))
    profiles = {}
    for owner in enemy_owners:
        owner_planets = [p for p in planets if p.owner == owner]
        owner_fleets  = [f for f in fleets  if f.owner == owner]
        total_ships  = sum(p.ships for p in owner_planets)
        total_prod   = sum(p.production for p in owner_planets)
        fleet_ships  = sum(f.ships for f in owner_fleets)
        num_planets  = len(owner_planets)
        aggression = fleet_ships / max(total_ships + fleet_ships, 1)
        expansion_rate = total_prod / max(num_planets, 1)
        total_strength = total_ships + fleet_ships + total_prod * 10
        profiles[owner] = {
            "aggression": aggression,
            "expansion_rate": expansion_rate,
            "total_strength": total_strength,
            "num_planets": num_planets,
            "planets": owner_planets,
        }
    return profiles


def get_nearest_enemy_distance(planet, planets, player):
    enemies = [p for p in planets if p.owner not in (-1, player)]
    if not enemies:
        return 9999
    return min(math.hypot(planet.x - e.x, planet.y - e.y) for e in enemies)


# ─────────────────────────── סימולציה ───────────────────────────

def simulate_future(planets, fleets, player, angular_velocity, turns=SIM_TURNS):
    p_ships  = {p.id: float(p.ships)  for p in planets}
    p_owner  = {p.id: p.owner         for p in planets}
    p_prod   = {p.id: p.production    for p in planets}
    fell_at  = {p.id: None            for p in planets}
    keep_needed   = {p.id: 0          for p in planets}
    snipe_targets = {}
    recapture_targets = {}

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
        deficit = max(1, int(our_ships_then * 0.72) + 1)  # הגנה חזקה יותר
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
            fx, fy, _, _ = get_interception_point(defender, planet, angular_velocity)
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
        mult *= 1.32
    elif game_phase == "finishing" and not is_neutral:
        mult *= 1.45
    elif game_phase == "total_war":
        mult *= 1.65

    return mult


# ─────────────────────────── AGENT ───────────────────────────

def agent(obs, config=None):
    moves = []

    player = obs.get("player", 0) if isinstance(obs, dict) else obs.player
    raw_planets = obs.get("planets", []) if isinstance(obs, dict) else obs.planets
    planets = [Planet(*p) for p in raw_planets]
    raw_fleets = obs.get("fleets", []) if isinstance(obs, dict) else obs.fleets
    fleets = [Fleet(*f) for f in raw_fleets]
    angular_velocity = obs.get("angular_velocity", 0.0) if isinstance(obs, dict) else obs.angular_velocity
    turn = obs.get("step", 0) if isinstance(obs, dict) else getattr(obs, "step", 0)

    my_planets      = [p for p in planets if p.owner == player]
    targets         = [p for p in planets if p.owner != player]
    neutral_planets = [p for p in planets if p.owner == -1]

    if not targets or not my_planets:
        return moves

    game_phase = get_game_phase(turn, my_planets, planets, player)
    enemy_profiles = profile_enemies(planets, fleets, player)

    sim_result, keep_needed, snipe_targets, recapture_targets = simulate_future(
        planets, fleets, player, angular_velocity, turns=SIM_TURNS
    )

    available_ships = {p.id: p.ships for p in my_planets}

    # ─── שלב 1: התרחבות מוקדמת ───
    expansion_claimed = set()
    if neutral_planets and game_phase in ("early", "mid"):
        all_neutrals_sorted = sorted(
            [n for n in neutral_planets if not is_comet_risk(n, angular_velocity)],
            key=lambda n: n.production / max(
                min(math.hypot(n.x - m.x, n.y - m.y) for m in my_planets), 1
            ),
            reverse=True
        )
        limit = EARLY_NEUTRAL_LIMIT if game_phase == "early" else 3
        for neutral in all_neutrals_sorted[:limit]:
            if neutral.id in expansion_claimed:
                continue
            best_mine = min(my_planets, key=lambda m: math.hypot(m.x - neutral.x, m.y - neutral.y))
            fx, fy, ships_needed, _ = get_interception_point(best_mine, neutral, angular_velocity)
            if fx is None or intersects_sun(best_mine.x, best_mine.y, fx, fy):
                continue
            garrison = max(keep_needed.get(best_mine.id, 0), BASE_GARRISON)
            sendable = available_ships[best_mine.id] - garrison
            if sendable >= ships_needed:
                angle = math.atan2(fy - best_mine.y, fx - best_mine.x)
                moves.append([best_mine.id, angle, ships_needed])
                available_ships[best_mine.id] -= ships_needed
                expansion_claimed.add(neutral.id)

    # ─── שלב 2: הגנה ───
    threats = get_threats_from_simulation(sim_result, planets, player)
    used_as_defenders = defend_planets(
        my_planets, threats, available_ships, keep_needed, moves, angular_velocity
    )

    # ─── מיפוי ציים נכנסים ───
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

    for move in moves:
        source_id, angle, ships = move[0], move[1], move[2]
        for t in targets:
            src_planet = next((p for p in planets if p.id == source_id), None)
            if src_planet is None:
                continue
            angle_to_target = math.atan2(t.y - src_planet.y, t.x - src_planet.x)
            diff = (angle - angle_to_target + math.pi) % (2 * math.pi) - math.pi
            if abs(diff) < 0.2:
                incoming_allied_ships[t.id] += ships
                break

    # ─── זיהוי האויב החלש ביותר + Kingmaker logic ───
    enemy_owners = set(p.owner for p in planets if p.owner not in (-1, player))
    weakest_enemy = None
    if len(enemy_owners) > 1:
        weakest_enemy = min(enemy_owners, key=lambda o: enemy_profiles.get(o, {}).get("total_strength", 9999))

    # Kingmaker: אם שני אויבים חזקים נלחמים, עדיף לתקוף את החזק יותר כדי להחליש אותו
    kingmaker_target = None
    if len(enemy_owners) >= 2:
        sorted_enemies = sorted(enemy_owners, key=lambda o: enemy_profiles.get(o, {}).get("total_strength", 0), reverse=True)
        if sorted_enemies:
            kingmaker_target = sorted_enemies[0]  # תוקף את החזק כדי למנוע dominance

    # ─── Adaptive Garrison ───
    def get_adaptive_garrison(p):
        dist_to_enemy = get_nearest_enemy_distance(p, planets, player)
        if dist_to_enemy < 18:
            return 24
        elif dist_to_enemy < 28:
            return 14
        else:
            return BASE_GARRISON

    # ─── שלב 3: בניית רשימת מטרות עם ROI משופר ───
    attackers = [p for p in my_planets if p.id not in used_as_defenders]
    planet_by_id = {p.id: p for p in planets}
    remaining_turns = max(1, GAME_LENGTH - turn)
    target_scores = []

    intercept_cache = {}

    def get_intercept_cached(attacker, target):
        key = (attacker.id, target.id)
        if key not in intercept_cache:
            intercept_cache[key] = get_interception_point(attacker, target, angular_velocity)
        return intercept_cache[key]

    def score_target(target, fx, fy, ships_needed, t_travel, mult_override=None):
        if is_comet_risk(target, angular_velocity):
            return None

        if target.production == 0 and target.owner == -1 and remaining_turns < 60:
            return None

        arrival_turns = max(1, t_travel) if t_travel else max(1, math.hypot(fx - 0, fy - 0))

        # ROI מדויק עם opportunity cost
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
            if kingmaker_target is not None and target.owner == kingmaker_target:
                mult *= 1.6  # עדיפות גבוהה להחלשת המוביל

            if target.owner != -1 and target.owner in enemy_profiles:
                profile = enemy_profiles[target.owner]
                if profile["total_strength"] < ELIMINATION_THRESHOLD:
                    mult *= ELIMINATION_BONUS
                if profile["aggression"] > 0.6:
                    mult *= 1.25

        gross_value = target.production * mult * remaining_turns
        net_value = gross_value - ships_needed * 1.1  # opportunity cost
        score = net_value / (ships_needed + arrival_turns * 0.6 + 1)
        return score

    # מטרות רגילות
    for target in targets:
        if is_comet_risk(target, angular_velocity):
            continue

        best_source = min(
            attackers,
            key=lambda p: math.hypot(p.x - target.x, p.y - target.y),
            default=None
        )
        if best_source is None:
            continue

        fx, fy, required_ships, t_travel = get_intercept_cached(best_source, target)
        if fx is None or intersects_sun(best_source.x, best_source.y, fx, fy):
            continue

        dist_to_target = math.hypot(fx - best_source.x, fy - best_source.x)
        if target.owner == -1 and dist_to_target < 22 and required_ships <= 12:
            ships_needed = max(MIN_FLEET_SIZE, required_ships)
        else:
            ships_needed = required_ships

        ships_needed -= incoming_allied_ships.get(target.id, 0)
        if ships_needed <= 0:
            continue

        total_available = sum(
            max(0, available_ships[p.id] - max(keep_needed.get(p.id, 0), 5))
            for p in attackers
        )
        if total_available < ships_needed * 0.85:  # קצת buffer
            continue

        sc = score_target(target, fx, fy, ships_needed, t_travel)
        if sc is None:
            continue
        target_scores.append((target, fx, fy, sc, ships_needed, best_source))

    # SNIPE + CRASH + RECAPTURE (ללא שינוי גדול)
    for pid, snipe_info in snipe_targets.items():
        if pid not in planet_by_id: continue
        target = planet_by_id[pid]
        if target.owner == player or is_comet_risk(target, angular_velocity): continue

        best_source = min(attackers, key=lambda p: math.hypot(p.x - target.x, p.y - target.y), default=None)
        if best_source is None: continue

        fx, fy = get_future_position(target, snipe_info["eta"], angular_velocity)
        if intersects_sun(best_source.x, best_source.y, fx, fy): continue

        snipe_ships = max(MIN_FLEET_SIZE, int(snipe_info["ships_after"]) + 1)
        ships_needed_snipe = snipe_ships - incoming_allied_ships.get(target.id, 0)
        if ships_needed_snipe <= 0: continue

        snipe_mult = 3.1 if snipe_info["type"] == "crash" else 2.6
        if game_phase in ("finishing", "total_war"):
            snipe_mult *= 1.35

        sc = score_target(target, fx, fy, ships_needed_snipe, snipe_info["eta"], mult_override=snipe_mult)
        if sc:
            target_scores.append((target, fx, fy, sc, ships_needed_snipe, best_source))

    for pid, rc_info in recapture_targets.items():
        if pid not in planet_by_id: continue
        target = planet_by_id[pid]
        if target.owner == player or is_comet_risk(target, angular_velocity): continue

        best_source = min(attackers, key=lambda p: math.hypot(p.x - target.x, p.y - target.y), default=None)
        if best_source is None: continue

        fx, fy, rc_ships, t_travel = get_intercept_cached(best_source, target)
        if fx is None: continue

        ships_needed_rc = rc_ships - incoming_allied_ships.get(target.id, 0)
        if ships_needed_rc <= 0: continue

        sc = score_target(target, fx, fy, ships_needed_rc, t_travel, mult_override=3.6)
        if sc:
            target_scores.append((target, fx, fy, sc, ships_needed_rc, best_source))

    # ─── שלב 4: תקיפה + Multi-Wave Coordination פשוט ───
    target_scores.sort(key=lambda x: x[3], reverse=True)
    attacked_targets = set()

    for target, fx, fy, score, ships_needed, _ in target_scores:
        if target.id in attacked_targets:
            continue

        ships_gathered = 0
        sorted_attackers = sorted(
            attackers,
            key=lambda p: math.hypot(p.x - target.x, p.y - target.y)
        )

        for attacker in sorted_attackers:
            if ships_gathered >= ships_needed + 8:  # מאפשר גל שני קטן
                break
            garrison = max(keep_needed.get(attacker.id, 0), get_adaptive_garrison(attacker))
            if game_phase == "total_war":
                garrison = max(garrison // 2, 3)

            sendable = available_ships[attacker.id] - garrison
            if sendable <= 0:
                continue

            afx, afy, _, _ = get_intercept_cached(attacker, target)
            if afx is None or intersects_sun(attacker.x, attacker.y, afx, afy):
                continue

            to_send = min(sendable, ships_needed - ships_gathered + 6)  # multi-wave buffer
            angle = math.atan2(afy - attacker.y, afx - attacker.x)
            moves.append([attacker.id, angle, to_send])
            available_ships[attacker.id] -= to_send
            ships_gathered += to_send

        if ships_gathered > 0:
            incoming_allied_ships[target.id] = incoming_allied_ships.get(target.id, 0) + ships_gathered
            attacked_targets.add(target.id)

    # ─── שלב 5: Surplus dispatching עם Forward Base ───
    if game_phase != "total_war" and len(my_planets) > 1 and targets:
        def forward_base_score(p):
            return min(math.hypot(p.x - t.x, p.y - t.y) for t in targets)

        forward_base = min(my_planets, key=forward_base_score)

        for mine in my_planets:
            if mine.id in used_as_defenders or mine.id == forward_base.id:
                continue
            garrison = max(keep_needed.get(mine.id, 0), get_adaptive_garrison(mine))
            surplus = available_ships[mine.id] - garrison
            if surplus <= 0 or any(m[0] == mine.id for m in moves):
                continue
            my_dist = forward_base_score(mine)
            fb_dist = forward_base_score(forward_base)
            if fb_dist >= my_dist * 0.88:
                continue
            to_send = int(surplus * SURPLUS_RATIO)
            if to_send < MIN_FLEET_SIZE:
                continue
            fx, fy, _, _ = get_interception_point(mine, forward_base, angular_velocity)
            if fx is None or intersects_sun(mine.x, mine.y, fx, fy):
                continue
            angle = math.atan2(fy - mine.y, fx - mine.x)
            moves.append([mine.id, angle, to_send])
            available_ships[mine.id] -= to_send

    return moves
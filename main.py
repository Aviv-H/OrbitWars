import math
from kaggle_environments.envs.orbit_wars.orbit_wars import Planet, Fleet

# הגדרת מרכז הלוח באופן ידני כנקודת ציון מפורשת (X, Y)
CENTER = (50.0, 50.0)
SUN_RADIUS = 10.5

# --- קבועי הגנה ---
MIN_PRODUCTION_TO_DEFEND = 2   # כוכב שמייצר פחות מזה — לא שווה להגן
DEFENDER_RESERVE_RATIO = 0.4   # שומרים 40% מהספינות בכוכב המגן

# --- קבועי תעדוף מטרות ---
DIST_WEIGHT = 0.02  # עונש על מרחק (קטן — לא רוצים שמרחק ידכא לגמרי)
ENEMY_BONUS = 2.0  # כפל ל-production של כוכב אויב (כיבושו מחליש אותו)

# --- קבועי Surplus dispatching ---
MIN_GARRISON = 10         # מינימום ספינות שכל כוכב שומר תמיד
SURPLUS_RATIO = 0.7       # שולח עד 70% מהעודף (לא הכל, כדי לא להישאר חשוף)

# --- קבועי 4 שחקנים ---
WEAKEST_ENEMY_BONUS = 1.5  # בונוס נוסף לכוכבי האויב החלש ביותר

# --- קבועי תזמון תקיפה ---
ATTACK_RATIO = 1.5         # לא תוקפים אויב שיש לו יותר מ-1.5x הספינות שלנו
ANCHOR_GARRISON_RATIO = 3  # כוכב עוגן שומר פי 3 מהמינימום הרגיל


def get_fleet_speed(ships, max_speed=6.0):
    """חישוב מהירות הצי לפי מספר הספינות"""
    if ships <= 0: return 0
    # חסם עליון של 1000 ספינות לנוסחה
    clamped_ships = min(ships, 1000)
    speed = 1.0 + (max_speed - 1.0) * ((math.log(clamped_ships) / math.log(1000)) ** 1.5)
    return min(speed, max_speed)


def get_future_position(planet, t, angular_velocity):
    """מחשב את מיקום כוכב הלכת בעוד t תורות"""
    orbital_radius = math.hypot(planet.x - CENTER[0], planet.y - CENTER[1])
    # בדיקה האם זה כוכב פנימי שמסתובב (לפי חוקי המשחק)
    if orbital_radius + planet.radius >= 50.0 or angular_velocity == 0:
        return planet.x, planet.y
    current_angle = math.atan2(planet.y - CENTER[1], planet.x - CENTER[0])
    future_angle = current_angle + angular_velocity * t
    fx = CENTER[0] + orbital_radius * math.cos(future_angle)
    fy = CENTER[1] + orbital_radius * math.sin(future_angle)
    return fx, fy


def get_interception_point(source, target, angular_velocity):
    """
    מוצא נקודת יירוט מדויקת.
    לכוכב נייח — בדיקה ישירה (מהיר).
    לכוכב זז — מסמלץ את נתיב הצי כדי לוודא שהוא אכן פוגש את הכוכב.
    """
    orbital_radius = math.hypot(target.x - CENTER[0], target.y - CENTER[1])
    is_moving = (orbital_radius + target.radius < 50.0) and (angular_velocity != 0)

    for t in range(1, 200):
        fx, fy = get_future_position(target, t, angular_velocity)
        enemy_growth = target.production * t if target.owner != -1 else 0
        ships_needed = target.ships + enemy_growth + 1
        speed = get_fleet_speed(ships_needed)

        if not is_moving:
            # כוכב נייח — בדיקה ישירה
            dist = math.hypot(fx - source.x, fy - source.y)
            if dist <= speed * t:
                return fx, fy, ships_needed
        else:
            # כוכב זז — בדוק שהצי מספיק להגיע לנקודה החזויה
            dist_to_intercept = math.hypot(fx - source.x, fy - source.y)
            if dist_to_intercept > speed * t:
                continue

            # סמלץ את נתיב הצי ובדוק פגיעה בכל שלב
            angle = math.atan2(fy - source.y, fx - source.x)
            fleet_x, fleet_y = source.x, source.y
            for step in range(1, t + 1):
                fleet_x += math.cos(angle) * speed
                fleet_y += math.sin(angle) * speed
                px, py = get_future_position(target, step, angular_velocity)
                if math.hypot(fleet_x - px, fleet_y - py) <= target.radius + speed:
                    return px, py, ships_needed

    return None, None, None


def intersects_sun(x1, y1, x2, y2):
    """בדיקה האם קטע התנועה חותך את השמש"""
    dx = x2 - x1
    dy = y2 - y1
    length_sq = dx ** 2 + dy ** 2
    if length_sq == 0:
        return False
    # מציאת הפרמטר t של ההיטל ממרכז השמש על הישר
    t = ((CENTER[0] - x1) * dx + (CENTER[1] - y1) * dy) / length_sq
    t = max(0.0, min(1.0, t))# חותך את הקטע כדי לא להמשיך מעבר לנקודות הקצה
    # הנקודה הקרובה ביותר על קטע הישר למרכז השמש
    closest_x = x1 + t * dx
    closest_y = y1 + t * dy
    dist_sq = (closest_x - CENTER[0]) ** 2 + (closest_y - CENTER[1]) ** 2
    return dist_sq <= SUN_RADIUS ** 2


def simulate_future(planets, fleets, player, angular_velocity, turns=30):
    """
    מסמלץ את המשחק turns תורות קדימה ללא ניבוי מהלכי שחקנים.
    מחזיר: planet_states — מילון {planet_id: {"owner", "ships", "fell_at"}}
    fell_at = התור שבו כוכב שלנו נפל לאויב (None אם לא נפל).
    """
    # העתק מצב כוכבים
    p_ships   = {p.id: float(p.ships)   for p in planets}
    p_owner   = {p.id: p.owner          for p in planets}
    p_prod    = {p.id: p.production     for p in planets}
    p_pos     = {p.id: (p.x, p.y)       for p in planets}
    p_radius  = {p.id: p.radius         for p in planets}
    fell_at   = {p.id: None             for p in planets}

    # העתק ציים: [x, y, angle, ships, owner, target_approx]
    # נשמור רק ציים שיש להם יעד ברור — נזהה לפי קרבה לכוכב
    active_fleets = []
    for f in fleets:
        # מצא את הכוכב הכי קרוב לכיוון הצי (בהנחת יעד)
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
        # 1. הזז ציים והנח אם הגיעו
        remaining_fleets = []
        arrivals = {}  # planet_id -> [(owner, ships)]

        for fl in active_fleets:
            tid = fl["target_id"]
            tx, ty = p_pos[tid]
            dist = math.hypot(fl["x"] - tx, fl["y"] - ty)
            if dist <= fl["speed"]:
                arrivals.setdefault(tid, []).append((fl["owner"], fl["ships"]))
            else:
                # הזז קדימה
                angle_to = math.atan2(ty - fl["y"], tx - fl["x"])
                fl["x"] += math.cos(angle_to) * fl["speed"]
                fl["y"] += math.sin(angle_to) * fl["speed"]
                remaining_fleets.append(fl)

        active_fleets = remaining_fleets

        # 2. עדכן כוכבים מציים שנחתו
        for pid, arr_list in arrivals.items():
            current_owner = p_owner[pid]
            current_ships = p_ships[pid]

            # קבץ לפי בעלים
            by_owner = {}
            for (owner, ships) in arr_list:
                by_owner[owner] = by_owner.get(owner, 0) + ships

            # הוסף ספינות ידידותיות לבעל הכוכב
            friendly = by_owner.pop(current_owner, 0)
            current_ships += friendly

            # כל אויב תוקף לפי תור
            for att_owner, att_ships in by_owner.items():
                if att_ships > current_ships:
                    # הכוכב נכבש
                    if current_owner == player and fell_at[pid] is None:
                        fell_at[pid] = t
                    current_ships = att_ships - current_ships
                    current_owner = att_owner
                else:
                    current_ships -= att_ships

            p_ships[pid] = current_ships
            p_owner[pid] = current_owner

        # 3. ייצור ספינות
        for pid in p_ships:
            p_ships[pid] += p_prod[pid]

        # 4. עדכן מיקומי כוכבים (סיבוב)
        for p in planets:
            nx, ny = get_future_position(p, t, angular_velocity)
            p_pos[p.id] = (nx, ny)

    return {
        pid: {
            "owner": p_owner[pid],
            "ships": p_ships[pid],
            "fell_at": fell_at[pid],
        }
        for pid in p_owner
    }


def get_threats_from_simulation(sim_result, planets, player):
    """
    מחיר הסימולציה → רשימת איומים על כוכבים שלנו.
    מחליף את get_planet_threat הישן.
    """
    planet_by_id = {p.id: p for p in planets}
    threats = []

    for pid, state in sim_result.items():
        p = planet_by_id[pid]
        if p.owner != player:
            continue
        if state["fell_at"] is None:
            continue

        # הכוכב עתיד ליפול בתור fell_at
        eta = state["fell_at"]
        our_ships_then = p.ships + p.production * eta
        # deficit: כמה ספינות נוספות נצטרך (אומדן שמרני)
        deficit = max(1, int(our_ships_then * 0.5) + 1)

        threats.append({
            "planet": p,
            "eta": eta,
            "enemy_ships": None,  # לא ידוע במדויק מהסימולציה
            "our_ships_at_eta": our_ships_then,
            "deficit": deficit,
            "will_fall": True,
        })

    return threats

#  שליחת תגבורת
def defend_planets(my_planets, threats, available_ships, moves, angular_velocity):
    """
    לכל כוכב מותקף שכדאי להגן עליו — שולח ספינות מכוכבים קרובים.
    מחזיר set של מזהי כוכבים שכבר שלחו ספינות להגנה.
    """
    used_as_defenders = set()

    # מגנים קודם על הכי יצרניים
    sorted_threats = sorted(
        threats,
        key=lambda t: t["planet"].production,
        reverse=True
    )

    for threat in sorted_threats:
        if not threat["will_fall"]:
            continue

        planet = threat["planet"]

        if planet.production < MIN_PRODUCTION_TO_DEFEND:
            continue

        ships_needed = threat["deficit"]
        ships_gathered = 0

        # מיין מגנים פוטנציאליים לפי קרבה
        potential_defenders = sorted(
            [p for p in my_planets if p.id != planet.id],
            key=lambda p: math.hypot(p.x - planet.x, p.y - planet.y)
        )

        for defender in potential_defenders:
            if ships_gathered >= ships_needed:
                break

            reserve = int(defender.ships * DEFENDER_RESERVE_RATIO)
            sendable = available_ships[defender.id] - reserve

            if sendable <= 0:
                continue

            fx, fy, _ = get_interception_point(defender, planet, angular_velocity)
            if fx is None:
                continue
            if intersects_sun(defender.x, defender.y, fx, fy):
                continue

            to_send = min(sendable, ships_needed - ships_gathered)
            angle = math.atan2(fy - defender.y, fx - defender.x)

            moves.append([defender.id, angle, to_send])
            available_ships[defender.id] -= to_send
            ships_gathered += to_send
            used_as_defenders.add(defender.id)

    return used_as_defenders


def agent(obs):
    moves = []

    # --- חילוץ נתונים ---
    player = obs.get("player", 0) if isinstance(obs, dict) else obs.player
    raw_planets = obs.get("planets", []) if isinstance(obs, dict) else obs.planets
    planets = [Planet(*p) for p in raw_planets]
    raw_fleets = obs.get("fleets", []) if isinstance(obs, dict) else obs.fleets
    fleets = [Fleet(*f) for f in raw_fleets]
    angular_velocity = obs.get("angular_velocity", 0.0) if isinstance(obs, dict) else obs.angular_velocity

    my_planets = [p for p in planets if p.owner == player]
    targets = [p for p in planets if p.owner != player]

    if not targets:
        return moves

    available_ships = {p.id: p.ships for p in my_planets}

    # --- הגנה (לפני ההתקפה) ---
    sim_result = simulate_future(planets, fleets, player, angular_velocity, turns=30)
    threats = get_threats_from_simulation(sim_result, planets, player)

    used_as_defenders = defend_planets(
        my_planets, threats, available_ships, moves, angular_velocity
    )

    # --- מיפוי ציים ידידותיים שכבר בדרך ---
    incoming_allied_ships = {t.id: 0 for t in targets}
    for f in fleets:
        if f.owner == player:
            for t in targets:
                angle_to_target = math.atan2(t.y - f.y, t.x - f.x)
                diff = (f.angle - angle_to_target + math.pi) % (2 * math.pi) - math.pi
                if abs(diff) < 0.2:
                    incoming_allied_ships[t.id] += f.ships
                    break
   # --- זיהוי האויב החלש ביותר (רלוונטי ל-4 שחקנים) ---
    enemy_owners = set(p.owner for p in planets if p.owner not in (-1, player))
    weakest_enemy = None
    if len(enemy_owners) > 1:
        def enemy_strength(owner):
            owner_planets = [p for p in planets if p.owner == owner]
            total_ships = sum(p.ships for p in owner_planets)
            total_prod = sum(p.production for p in owner_planets)
            fleet_ships = sum(f.ships for f in fleets if f.owner == owner)
            return total_ships + fleet_ships + total_prod * 10  # production שווה הרבה לטווח ארוך

        weakest_enemy = min(enemy_owners, key=enemy_strength)
    # --- זיהוי כוכב עוגן — הכי יצרני שלנו ---
    anchor = max(my_planets, key=lambda p: p.production) if my_planets else None
    anchor_garrison = MIN_GARRISON * ANCHOR_GARRISON_RATIO
    # --- התקפה (רק מכוכבים שלא נשלחו להגנה) ---
    for mine in my_planets:
        if mine.id in used_as_defenders:
            continue

        valid_targets = []

        for target in targets:
            fx, fy, required_ships = get_interception_point(mine, target, angular_velocity)
            if fx is None:
                continue

            ships_needed = required_ships - incoming_allied_ships[target.id]
            if ships_needed <= 0:
                continue

            if available_ships[mine.id] >= ships_needed:
                if not intersects_sun(mine.x, mine.y, fx, fy):
                    # תזמון תקיפה: דלג אם האויב חזק מדי ביחס לכוחנו הכולל
                    my_total = sum(available_ships[p.id] for p in my_planets)
                    if target.owner != -1 and target.ships > my_total * ATTACK_RATIO:
                        continue
                    dist = math.hypot(fx - mine.x, fy - mine.y)
                    # production_value: כפול אם כוכב אויב, בונוס נוסף אם הוא האויב החלש ביותר
                    production_value = target.production * (ENEMY_BONUS if target.owner != -1 else 1.0)
                    if weakest_enemy is not None and target.owner == weakest_enemy:
                        production_value *= WEAKEST_ENEMY_BONUS
                    # ציון גבוה = מטרה עדיפה
                    score = (production_value / (ships_needed + 1)) / (1 + dist * DIST_WEIGHT)
                    valid_targets.append((target, fx, fy, score, ships_needed))

        if valid_targets:
            best_target, fx, fy, _, ships_to_send = max(valid_targets, key=lambda item: item[3])
            angle = math.atan2(fy - mine.y, fx - mine.x)
            moves.append([mine.id, angle, ships_to_send])
            available_ships[mine.id] -= ships_to_send
            # רושמים מקומית את הצי החדש שיצרנו כדי שכוכבים אחרים שלנו באותו תור לא ישגרו אליו גם
            incoming_allied_ships[best_target.id] += ships_to_send

    # --- Surplus dispatching: כוכבים שלא מצאו מטרה — שולחים עודף לכוכב שלנו הכי חלש ---
    if len(my_planets) > 1 and targets:
        # מצא כוכב קדמי — שלנו, עם מרחק מינימלי לכוכב האויב הקרוב ביותר
        def forward_base_score(p):
            return min(
                math.hypot(p.x - t.x, p.y - t.y)
                for t in targets
            )
        forward_base = min(my_planets, key=forward_base_score)

        for mine in my_planets:
            if mine.id in used_as_defenders:
                continue
            if mine.id == forward_base.id:
                continue  # הכוכב הקדמי עצמו לא שולח לעצמו

            # כוכב עוגן — שומר רזרבה גדולה יותר
            garrison = anchor_garrison if (anchor and mine.id == anchor.id) else MIN_GARRISON

            surplus = available_ships[mine.id] - garrison
            if surplus <= 0:
                continue

            # בדוק אם כבר שלח ספינות לתקיפה בתור הזה
            already_sent = any(m[0] == mine.id for m in moves)
            if already_sent:
                continue

            # שלח רק אם הכוכב הקדמי קרוב לאויב יותר ממני
            my_dist_to_enemy = forward_base_score(mine)
            fb_dist_to_enemy = forward_base_score(forward_base)
            if fb_dist_to_enemy >= my_dist_to_enemy * 0.9:
                continue  # אני כבר קדמי מספיק, אין טעם לשלוח

            to_send = int(surplus * SURPLUS_RATIO)
            if to_send <= 0:
                continue

            fx, fy, _ = get_interception_point(mine, forward_base, angular_velocity)
            if fx is None:
                continue
            if intersects_sun(mine.x, mine.y, fx, fy):
                continue

            angle = math.atan2(fy - mine.y, fx - mine.x)
            moves.append([mine.id, angle, to_send])
            available_ships[mine.id] -= to_send
    return moves
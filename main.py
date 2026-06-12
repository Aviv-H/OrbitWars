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
    מוצא את נקודת המפגש ואת כמות הספינות הנדרשת,
    תוך שקלול קצב ייצור הספינות של המטרה לאורך זמן הטיסה.
    """
    # מריצים סימולציה עד 200 תורות קדימה
    for t in range(1, 200):
        fx, fy = get_future_position(target, t, angular_velocity)
        dist = math.hypot(fx - source.x, fy - source.y)
        # כוכבים ניטרליים לא מייצרים ספינות, רק אויבים
        enemy_growth = target.production * t if target.owner != -1 else 0
        ships_needed = target.ships + enemy_growth + 1
        # חישוב המהירות מבוסס על הכוח שנצטרך לשלוח
        speed = get_fleet_speed(ships_needed)
        if dist <= speed * t:
            return fx, fy, ships_needed
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

# זיהוי האיום
def get_planet_threat(planet, fleets, player, angular_velocity):
    """
    מחזיר מילון עם פרטי האיום על הכוכב, או None אם אין איום.
    """
    if planet.owner != player:
        return None

    enemy_fleets = [f for f in fleets if f.owner != player]
    if not enemy_fleets:
        return None

    total_enemy_arriving = 0
    earliest_eta = 999

    for f in enemy_fleets:
        dist = math.hypot(f.x - planet.x, f.y - planet.y)
        speed = get_fleet_speed(f.ships)
        eta = max(1, int(dist / speed))
        total_enemy_arriving += f.ships
        earliest_eta = min(earliest_eta, eta)

    if total_enemy_arriving == 0:
        return None

    # כמה ספינות יהיו לנו ברגע ההגעה הראשון
    our_ships_at_eta = planet.ships + planet.production * earliest_eta
    deficit = total_enemy_arriving - our_ships_at_eta + 1
    will_fall = deficit > 0

    return {
        "planet": planet,
        "eta": earliest_eta,
        "enemy_ships": total_enemy_arriving,
        "our_ships_at_eta": our_ships_at_eta,
        "deficit": deficit,
        "will_fall": will_fall,
    }

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
    threats = []
    for mine in my_planets:
        threat = get_planet_threat(mine, fleets, player, angular_velocity)
        if threat:
            threats.append(threat)

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
                    dist = math.hypot(fx - mine.x, fy - mine.y)
                    # production_value: כפול אם כוכב אויב (כיבושו גם מחליש אותו)
                    production_value = target.production * (ENEMY_BONUS if target.owner != -1 else 1.0)
                    # ציון גבוה = מטרה עדיפה
                    score = (production_value / (ships_needed + 1)) / (1 + dist * DIST_WEIGHT)
                    valid_targets.append((target, fx, fy, score, ships_needed))

        if valid_targets:
            # תעדוף מטרה הקרובה ביותר לאחר תנועה
            best_target, fx, fy, _, ships_to_send = min(valid_targets, key=lambda item: item[3])
            angle = math.atan2(fy - mine.y, fx - mine.x)
            moves.append([mine.id, angle, ships_to_send])
            available_ships[mine.id] -= ships_to_send
            # רושמים מקומית את הצי החדש שיצרנו כדי שכוכבים אחרים שלנו באותו תור לא ישגרו אליו גם
            incoming_allied_ships[best_target.id] += ships_to_send

    return moves
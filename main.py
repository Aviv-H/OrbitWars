import math
from kaggle_environments.envs.orbit_wars.orbit_wars import Planet, Fleet

# הגדרת מרכז הלוח באופן ידני כנקודת ציון מפורשת (X, Y)
CENTER = (50.0, 50.0)
SUN_RADIUS = 10.5


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
    t = max(0.0, min(1.0, t)) # חותך את הקטע כדי לא להמשיך מעבר לנקודות הקצה
    # הנקודה הקרובה ביותר על קטע הישר למרכז השמש
    closest_x = x1 + t * dx
    closest_y = y1 + t * dy

    dist_sq = (closest_x - CENTER[0]) ** 2 + (closest_y - CENTER[1]) ** 2
    return dist_sq <= SUN_RADIUS ** 2


def agent(obs):
    moves = []

    # חילוץ נתונים
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

    # מיפוי סטטלס: זיהוי ציים שלנו שכבר בדרך למטרות
    incoming_allied_ships = {t.id: 0 for t in targets}
    for f in fleets:
        if f.owner == player:
            for t in targets:
                # חישוב זווית מהצי למיקום (הנוכחי) של המטרה
                angle_to_target = math.atan2(t.y - f.y, t.x - f.x)
                # נרמול הזווית כדי לבדוק סטייה
                diff = (f.angle - angle_to_target + math.pi) % (2 * math.pi) - math.pi
                if abs(diff) < 0.2:  # טולרנס של כ-11 מעלות. הצי מכוון למטרה זו!
                    incoming_allied_ships[t.id] += f.ships
                    break

    for mine in my_planets:
        valid_targets = []

        for target in targets:
            # הפונקציה מחזירה עכשיו גם את הכוח הנדרש לאחר הגידול הטבעי
            fx, fy, required_ships = get_interception_point(mine, target, angular_velocity)

            if fx is None:
                continue

            # נחסיר את הכוח שכבר נמצא בדרך למטרה הזו מאחד הכוכבים האחרים שלנו
            ships_needed = required_ships - incoming_allied_ships[target.id]

            # אם כבר יש מספיק ספינות באוויר כדי לכבוש, נדלג על המטרה
            if ships_needed <= 0:
                continue

            if available_ships[mine.id] >= ships_needed:
                if not intersects_sun(mine.x, mine.y, fx, fy):
                    dist = math.hypot(fx - mine.x, fy - mine.y)
                    valid_targets.append((target, fx, fy, dist, ships_needed))

        if valid_targets:
            # תעדוף מטרה הקרובה ביותר לאחר תנועה
            best_target, fx, fy, _, ships_to_send = min(valid_targets, key=lambda item: item[3])

            angle = math.atan2(fy - mine.y, fx - mine.x)
            moves.append([mine.id, angle, ships_to_send])

            available_ships[mine.id] -= ships_to_send

            # רושמים מקומית את הצי החדש שיצרנו כדי שכוכבים אחרים שלנו באותו תור לא ישגרו אליו גם
            incoming_allied_ships[best_target.id] += ships_to_send

    return moves
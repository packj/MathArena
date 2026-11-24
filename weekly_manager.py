"""
weekly_manager.py

Handles:
- Determining the weekly cycle (resets every Tuesday at 5:00 PM US/Eastern).
- Triggering the weekly reset when the current time crosses Tuesday 5:00 PM ET.
- Fast comparison of awarded points with the top 3 (Gold, Silver, Bronze) in `weekly_podium`.
"""

import zoneinfo
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import sqlalchemy

EASTERN_TZ = zoneinfo.ZoneInfo("America/New_York")


def get_current_cycle_start(dt: Optional[datetime] = None) -> datetime:
    """
    Returns the datetime of the start of the current cycle (the most recent Tuesday at 17:00:00 US/Eastern).
    Tuesday is weekday 1 in Python (Monday=0, Tuesday=1, ..., Sunday=6).
    """
    if dt is None:
        dt = datetime.now(EASTERN_TZ)
    elif dt.tzinfo is None:
        dt = dt.replace(tzinfo=EASTERN_TZ)
    else:
        dt = dt.astimezone(EASTERN_TZ)

    # Days since Tuesday
    days_since_tuesday = (dt.weekday() - 1) % 7
    candidate = dt.replace(hour=17, minute=0, second=0, microsecond=0) - timedelta(days=days_since_tuesday)
    if candidate > dt:
        candidate -= timedelta(days=7)
    return candidate


def get_next_cycle_reset(dt: Optional[datetime] = None) -> datetime:
    """Returns the datetime of the upcoming Tuesday 5:00 PM US/Eastern reset."""
    return get_current_cycle_start(dt) + timedelta(days=7)


def check_and_apply_weekly_reset(conn) -> bool:
    """
    Checks if a weekly reset is due. If so, clears the weekly_leaderboard,
    resets weekly_podium to 0, and updates weekly_reset_meta.
    Returns True if a reset occurred, False otherwise.
    """
    now_et = datetime.now(EASTERN_TZ)
    cycle_start = get_current_cycle_start(now_et)
    cycle_start_str = cycle_start.isoformat()

    row = conn.execute(sqlalchemy.text(
        "SELECT last_reset_time FROM weekly_reset_meta WHERE id = 1"
    )).fetchone()

    if row and row[0] == cycle_start_str:
        return False  # Already on the current cycle

    # Needs reset
    try:
        conn.execute(sqlalchemy.text("TRUNCATE TABLE weekly_leaderboard"))
    except Exception:
        conn.execute(sqlalchemy.text("DELETE FROM weekly_leaderboard"))

    # Reset podium scores to 0 and username to NULL
    for r in (1, 2, 3):
        conn.execute(sqlalchemy.text('''
            INSERT INTO weekly_podium (rank_pos, username, score)
            VALUES (:r, NULL, 0)
            ON DUPLICATE KEY UPDATE username = NULL, score = 0
        '''), {'r': r})

    # Update or insert reset meta
    conn.execute(sqlalchemy.text('''
        INSERT INTO weekly_reset_meta (id, last_reset_time)
        VALUES (1, :t)
        ON DUPLICATE KEY UPDATE last_reset_time = :t
    '''), {'t': cycle_start_str})

    conn.commit()
    return True


def get_weekly_podium(conn) -> List[Dict]:
    """
    Returns the current podium as a list of dicts:
    [{'rank_pos': 1, 'username': ..., 'score': ...}, ...]
    sorted by rank_pos.
    """
    rows = conn.execute(sqlalchemy.text('''
        SELECT rank_pos, username, score
        FROM weekly_podium
        ORDER BY rank_pos ASC
    ''')).fetchall()

    podium = []
    found_ranks = set()
    for row in rows:
        r_pos = int(row[0])
        found_ranks.add(r_pos)
        podium.append({
            'rank_pos': r_pos,
            'username': row[1],
            'score': float(row[2]) if row[2] is not None else 0.0
        })

    for r in (1, 2, 3):
        if r not in found_ranks:
            podium.append({'rank_pos': r, 'username': None, 'score': 0.0})

    podium.sort(key=lambda x: x['rank_pos'])
    return podium


def add_weekly_points(conn, username: str, points: float) -> Tuple[float, Optional[str]]:
    """
    Adds points to the user's weekly total and compares ONLY against the 3 podium scores.
    Returns:
        (new_weekly_score, star_earned)
        where star_earned is 'gold', 'silver', 'bronze', or None.
    """
    # 1. Ensure cycle is current
    check_and_apply_weekly_reset(conn)

    # 2. Update user's weekly score
    conn.execute(sqlalchemy.text('''
        INSERT INTO weekly_leaderboard (username, points)
        VALUES (:username, :points)
        ON DUPLICATE KEY UPDATE points = points + :points
    '''), {'username': username, 'points': points})

    row = conn.execute(sqlalchemy.text(
        "SELECT points FROM weekly_leaderboard WHERE username = :u"
    ), {'u': username}).fetchone()
    new_score = float(row[0]) if row and row[0] is not None else float(points)

    # 3. Fast comparison against only the top 3 values in weekly_podium
    podium = get_weekly_podium(conn)

    # Check podium entries
    podium_usernames = {p['username'] for p in podium if p['username']}
    bronze_score = podium[2]['score'] if len(podium) >= 3 else 0.0

    # Determine previous star tier for this user before points were added
    prev_tier = None
    for p in podium:
        if p['username'] == username and p['score'] > 0:
            if p['rank_pos'] == 1:
                prev_tier = 'gold'
            elif p['rank_pos'] == 2:
                prev_tier = 'silver'
            elif p['rank_pos'] == 3:
                prev_tier = 'bronze'
            break

    # User affects podium if:
    # - User was already in the podium (their score increased, might change rank or solidify rank)
    # - OR user's new score is greater than the bronze score
    # - OR podium has empty slots (< 3 players with score > 0)
    has_empty_slot = any(p['username'] is None or p['score'] == 0 for p in podium)

    if (username in podium_usernames) or (new_score > bronze_score) or (has_empty_slot and new_score > 0):
        # Recompute podium with the new user score
        current_entries = [
            {'username': p['username'], 'score': p['score']}
            for p in podium
            if p['username'] != username and p['username'] is not None and p['score'] > 0
        ]
        if new_score > 0:
            current_entries.append({'username': username, 'score': new_score})

        # Sort descending by score
        current_entries.sort(key=lambda x: x['score'], reverse=True)

        # Update weekly_podium table for ranks 1, 2, 3
        for r in (1, 2, 3):
            if r - 1 < len(current_entries):
                entry = current_entries[r - 1]
                conn.execute(sqlalchemy.text('''
                    UPDATE weekly_podium
                    SET username = :u, score = :s
                    WHERE rank_pos = :r
                '''), {'u': entry['username'], 's': entry['score'], 'r': r})
            else:
                conn.execute(sqlalchemy.text('''
                    UPDATE weekly_podium
                    SET username = NULL, score = 0
                    WHERE rank_pos = :r
                '''), {'r': r})
        conn.commit()

        # Determine user's star status (only award banner if newly earned or upgraded)
        new_tier = None
        for idx, entry in enumerate(current_entries[:3]):
            if entry['username'] == username:
                if idx == 0:
                    new_tier = 'gold'
                elif idx == 1:
                    new_tier = 'silver'
                elif idx == 2:
                    new_tier = 'bronze'
                break

        tier_order = {'bronze': 1, 'silver': 2, 'gold': 3}
        star_earned = None
        if new_tier:
            if prev_tier is None or tier_order.get(new_tier, 0) > tier_order.get(prev_tier, 0):
                star_earned = new_tier

        conn.commit()
        return new_score, star_earned

    conn.commit()
    return new_score, None

"""
badges.py

Defines all badge categories, tiers, thresholds, and achievement calculation logic.
Categories:
1. Points Milestones
2. Accuracy & Hot Streaks
3. Difficult Problem Mastery (Endgame Sprint)
4. Subject Mastery
5. Consistent Practice (Daily & Weekly Streaks)
6. Community Contributor (Recommending tags, links, videos, classifications)
"""

import collections
import datetime
from typing import Any, Dict, List, Optional, Tuple
import sqlalchemy


# ── Category 1: Points Milestones ───────────────────────────────────────────
POINT_BADGES = [
    {'id': 'pts_500', 'name': 'Number Novice', 'category': 'Points', 'tier': 'bronze', 'target': 500, 'desc': 'Earn 500 cumulative points.'},
    {'id': 'pts_1500', 'name': 'Problem Solver', 'category': 'Points', 'tier': 'bronze', 'target': 1500, 'desc': 'Earn 1,500 cumulative points.'},
    {'id': 'pts_4000', 'name': 'Equation Duelist', 'category': 'Points', 'tier': 'bronze', 'target': 4000, 'desc': 'Earn 4,000 cumulative points.'},
    {'id': 'pts_8000', 'name': 'Logic Tactician', 'category': 'Points', 'tier': 'silver', 'target': 8000, 'desc': 'Earn 8,000 cumulative points.'},
    {'id': 'pts_15000', 'name': 'Calculation Captain', 'category': 'Points', 'tier': 'silver', 'target': 15000, 'desc': 'Earn 15,000 cumulative points.'},
    {'id': 'pts_25000', 'name': 'Theorem Champion', 'category': 'Points', 'tier': 'silver', 'target': 25000, 'desc': 'Earn 25,000 cumulative points.'},
    {'id': 'pts_40000', 'name': 'Olympiad Contender', 'category': 'Points', 'tier': 'gold', 'target': 40000, 'desc': 'Earn 40,000 cumulative points.'},
    {'id': 'pts_80000', 'name': 'Arena Grandmaster', 'category': 'Points', 'tier': 'gold', 'target': 80000, 'desc': 'Earn 80,000 cumulative points.'},
    {'id': 'pts_120000', 'name': 'Math Legend', 'category': 'Points', 'tier': 'gold', 'target': 120000, 'desc': 'Earn 120,000 cumulative points.'},
]

# ── Category 2: Accuracy & Hot Streaks ──────────────────────────────────────
STREAK_BADGES = [
    {'id': 'streak_5', 'name': 'On Fire', 'category': 'Accuracy', 'tier': 'bronze', 'target': 5, 'desc': 'Answer 5 problems correctly in a row.'},
    {'id': 'streak_10', 'name': 'Blazing Streak', 'category': 'Accuracy', 'tier': 'silver', 'target': 10, 'desc': 'Answer 10 problems correctly in a row.'},
    {'id': 'streak_20', 'name': 'Unstoppable', 'category': 'Accuracy', 'tier': 'gold', 'target': 20, 'desc': 'Answer 20 problems correctly in a row.'},
]

# ── Category 3: Difficult Problem Mastery ──────────────────────────────────
# Thresholds: 15 / 40 / 100 on endgame sprint problems
# School (22-30), Chapter (18-30), State (15-30), National (11-30)
DIFFICULTY_BADGES = [
    {'id': 'diff_15', 'name': 'Gauntlet Runner', 'category': 'Difficult Problems', 'tier': 'bronze', 'target': 15, 'desc': 'Solve 15 endgame Sprint problems correctly.'},
    {'id': 'diff_40', 'name': 'Deep End Champion', 'category': 'Difficult Problems', 'tier': 'silver', 'target': 40, 'desc': 'Solve 40 endgame Sprint problems correctly.'},
    {'id': 'diff_100', 'name': 'Boss Slayer', 'category': 'Difficult Problems', 'tier': 'gold', 'target': 100, 'desc': 'Solve 100 endgame Sprint problems correctly.'},
]

# ── Category 4: Subject Mastery ─────────────────────────────────────────────
# Core categories: Algebra, Geometry, Number Theory, Probability and Counting, Arithmetic, Statistics
SUBJECT_BADGES = [
    {'id': 'subj_scholar', 'name': 'Subject Scholar', 'category': 'Subject Mastery', 'tier': 'bronze', 'target': 25, 'desc': 'Solve at least 25 problems correctly in any single subject.'},
    {'id': 'subj_polymath', 'name': 'Polymath', 'category': 'Subject Mastery', 'tier': 'silver', 'target': 3, 'desc': 'Solve at least 25 problems correctly across 3 different subjects.'},
    {'id': 'subj_renaissance', 'name': 'Renaissance Master', 'category': 'Subject Mastery', 'tier': 'gold', 'target': 5, 'desc': 'Solve at least 25 problems correctly across 5 different subjects.'},
]

# ── Category 5: Consistent Practice ─────────────────────────────────────────
CONSISTENCY_BADGES = [
    {'id': 'consist_7d', 'name': 'Daily Dedication', 'category': 'Consistency', 'tier': 'bronze', 'target': 7, 'desc': 'Practice math at least 7 consecutive days.'},
    {'id': 'consist_4w', 'name': 'Weekly Habit', 'category': 'Consistency', 'tier': 'silver', 'target': 4, 'desc': 'Practice every week for 4 consecutive weeks.'},
    {'id': 'consist_12w', 'name': 'Iron Discipline', 'category': 'Consistency', 'tier': 'gold', 'target': 12, 'desc': 'Practice every week for 12 consecutive weeks.'},
]

# ── Category 6: Community Contributor ───────────────────────────────────────
# Based on contribution points earned by recommending tags, classifications, links, videos, suggestions
CONTRIBUTION_BADGES = [
    {'id': 'contrib_bronze', 'name': 'Community Contributor', 'category': 'Contributions', 'tier': 'bronze', 'target': 5, 'desc': 'Earn 5 contribution points helping improve Math Arena.'},
    {'id': 'contrib_silver', 'name': 'Content Curator', 'category': 'Contributions', 'tier': 'silver', 'target': 25, 'desc': 'Earn 25 contribution points helping improve Math Arena.'},
    {'id': 'contrib_gold', 'name': 'Arena Pillar', 'category': 'Contributions', 'tier': 'gold', 'target': 100, 'desc': 'Earn 100 contribution points helping improve Math Arena.'},
]

ALL_BADGE_DEFINITIONS = (
    POINT_BADGES
    + STREAK_BADGES
    + DIFFICULTY_BADGES
    + SUBJECT_BADGES
    + CONSISTENCY_BADGES
    + CONTRIBUTION_BADGES
)

TIER_ORDER = {'bronze': 1, 'silver': 2, 'gold': 3}


def is_difficult_problem(level: str, fmt: str, qnum: int) -> bool:
    """Check if problem matches the endgame sprint range criteria."""
    if not fmt or fmt.strip().lower() != 'sprint':
        return False
    lvl = (level or '').strip().lower()
    if lvl == 'school':
        return 22 <= qnum <= 30
    elif lvl == 'chapter':
        return 18 <= qnum <= 30
    elif lvl == 'state':
        return 15 <= qnum <= 30
    elif lvl == 'national':
        return 11 <= qnum <= 30
    return False


def get_user_stats(conn, username: str) -> Dict[str, Any]:
    """Fetch all raw performance stats for a user from the DB."""
    stats = {
        'practice_points': 0.0,
        'contribution_points': 0,
        'max_streak': 0,
        'difficult_solved': 0,
        'subject_counts': collections.defaultdict(int),
        'max_day_streak': 0,
        'max_week_streak': 0,
    }

    if not username or not username.isalnum():
        return stats

    # 1. Practice Points
    try:
        row = conn.execute(
            sqlalchemy.text('SELECT points FROM leaderboard WHERE username = :u'),
            {'u': username}
        ).fetchone()
        if row and row[0] is not None:
            stats['practice_points'] = float(row[0])
    except Exception:
        pass

    # 2. Contribution Points
    try:
        crow = conn.execute(
            sqlalchemy.text('SELECT points FROM contribution_points WHERE username = :u'),
            {'u': username}
        ).fetchone()
        if crow and crow[0] is not None:
            stats['contribution_points'] = int(crow[0])
    except Exception:
        pass

    # 3. Results History Analysis
    tbl_name = f"results_{username}"
    try:
        has_tbl = conn.execute(
            sqlalchemy.text(f"SHOW TABLES LIKE '{tbl_name}'")
        ).fetchone()
        if not has_tbl:
            return stats

        rows = conn.execute(sqlalchemy.text(f'''
            SELECT r.result, r.time, p.level, p.format, p.question_number, p.classification
            FROM {tbl_name} r
            LEFT JOIN problems p ON r.problem_id = p.id
            ORDER BY r.time ASC, r.id ASC
        ''')).fetchall()

        if not rows:
            return stats

        # Consecutive correct streak
        max_streak = 0
        cur_streak = 0
        dates = set()

        for r in rows:
            res = r[0]
            t = r[1]
            lvl = r[2]
            fmt = r[3]
            qnum = r[4]
            classification = r[5]

            if res == 2:
                cur_streak += 1
                if cur_streak > max_streak:
                    max_streak = cur_streak

                # Difficult sprint solved
                if qnum is not None and is_difficult_problem(lvl, fmt, int(qnum)):
                    stats['difficult_solved'] += 1

                # Subject classification
                if classification and classification.strip():
                    c_clean = classification.strip()
                    if c_clean.lower() != 'none':
                        stats['subject_counts'][c_clean] += 1
            else:
                cur_streak = 0

            if t:
                dates.add(t.date())

        stats['max_streak'] = max_streak

        # Date and week streaks
        sorted_dates = sorted(dates)
        if sorted_dates:
            # Day streak
            max_day_streak = 0
            cur_day_streak = 0
            prev_d = None
            for d in sorted_dates:
                if prev_d and d == prev_d + datetime.timedelta(days=1):
                    cur_day_streak += 1
                else:
                    cur_day_streak = 1
                if cur_day_streak > max_day_streak:
                    max_day_streak = cur_day_streak
                prev_d = d
            stats['max_day_streak'] = max_day_streak

            # Week streak
            weeks = sorted(set((d.isocalendar()[0], d.isocalendar()[1]) for d in sorted_dates))
            max_week_streak = 0
            cur_week_streak = 0
            prev_w_d = None
            for y, w in weeks:
                cur_w_d = datetime.date.fromisocalendar(y, w, 1)
                if prev_w_d and cur_w_d == prev_w_d + datetime.timedelta(days=7):
                    cur_week_streak += 1
                else:
                    cur_week_streak = 1
                if cur_week_streak > max_week_streak:
                    max_week_streak = cur_week_streak
                prev_w_d = cur_w_d
            stats['max_week_streak'] = max_week_streak

    except Exception as e:
        print(f"Error computing user stats for {username}: {e}")

    return stats


def evaluate_all_badges(stats: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], int, Optional[str]]:
    """
    Evaluates all badges against computed stats.
    Returns: (badges_list, earned_count, highest_tier)
    """
    badges = []
    earned_count = 0
    highest_tier = None

    pts = stats.get('practice_points', 0.0)
    contrib = stats.get('contribution_points', 0)
    max_streak = stats.get('max_streak', 0)
    diff_solved = stats.get('difficult_solved', 0)
    max_days = stats.get('max_day_streak', 0)
    max_weeks = stats.get('max_week_streak', 0)
    subject_counts = stats.get('subject_counts', {})

    # Subject metrics:
    max_single_subject = max(subject_counts.values()) if subject_counts else 0
    subjects_with_25 = sum(1 for v in subject_counts.values() if v >= 25)

    for b in ALL_BADGE_DEFINITIONS:
        bid = b['id']
        tier = b['tier']
        target = b['target']
        current = 0
        earned = False

        if bid.startswith('pts_'):
            current = pts
            earned = current >= target
        elif bid.startswith('streak_'):
            current = max_streak
            earned = current >= target
        elif bid.startswith('diff_'):
            current = diff_solved
            earned = current >= target
        elif bid == 'subj_scholar':
            current = max_single_subject
            earned = current >= target
        elif bid == 'subj_polymath':
            current = subjects_with_25
            earned = current >= target
        elif bid == 'subj_renaissance':
            current = subjects_with_25
            earned = current >= target
        elif bid == 'consist_7d':
            current = max_days
            earned = current >= target
        elif bid in ('consist_4w', 'consist_12w'):
            current = max_weeks
            earned = current >= target
        elif bid.startswith('contrib_'):
            current = contrib
            earned = current >= target

        if earned:
            earned_count += 1
            if highest_tier is None or TIER_ORDER.get(tier, 0) > TIER_ORDER.get(highest_tier, 0):
                highest_tier = tier

        badges.append({
            'id': bid,
            'name': b['name'],
            'category': b['category'],
            'tier': tier,
            'target': target,
            'current': current,
            'desc': b['desc'],
            'earned': earned,
        })

    return badges, earned_count, highest_tier

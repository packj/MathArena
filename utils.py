from flask import session, redirect, url_for, render_template_string
import random
import sqlalchemy

def login_required(f):
    def wrapper(*args, **kwargs):
        if 'username' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    wrapper.__name__ = f.__name__
    return wrapper

def award_contribution_points(sql_db, username, points):
    """Award contribution points to a user."""
    try:
        with sql_db.connect() as conn:
            # Create the contribution_points table if it doesn't exist
            conn.execute(sqlalchemy.text('''
                CREATE TABLE IF NOT EXISTS contribution_points (
                    username VARCHAR(255) PRIMARY KEY,
                    points INT NOT NULL
                )
            '''))
            # Insert or update the user's points
            conn.execute(sqlalchemy.text('''
                INSERT INTO contribution_points (username, points)
                VALUES (:username, :points)
                ON DUPLICATE KEY UPDATE points = points + :points
            '''), {'username': username, 'points': points})
            conn.commit()
    except Exception as e:
        print(f"Error awarding contribution points: {e}")

import re
import json

def normalize_math_answer(ans: str) -> str:
    """
    Normalizes a mathematical answer string for comparison:
    - Strips leading/trailing spaces and lowercases
    - Strips surrounding currency symbols ($) and percent (%)
    - Strips commas in numbers (e.g. 1,000 -> 1000)
    - Replaces LaTeX commands: \pi -> pi, \sqrt -> sqrt, \cdot/\times -> *
    - Removes whitespace
    - Replaces implicit multiplication: 2pi -> 2*pi, 3sqrt(2) -> 3*sqrt(2)
    """
    if not ans:
        return ""
    s = str(ans).strip().lower()

    # Strip surrounding currency/units/percent symbols
    s = s.lstrip('$').rstrip('%')

    # Strip commas between digits (e.g., 1,000 -> 1000)
    s = re.sub(r'(?<=\d),(?=\d)', '', s)

    # Canonicalize common LaTeX syntax
    s = s.replace(r'\pi', 'pi')
    s = s.replace(r'\sqrt', 'sqrt')
    s = s.replace(r'\cdot', '*')
    s = s.replace(r'\times', '*')

    # Remove all internal whitespace
    s = re.sub(r'\s+', '', s)

    # Canonicalize implicit multiplication with pi and sqrt
    s = re.sub(r'(\d)(pi|sqrt)', r'\1*\2', s)

    return s


def is_unambiguous_math_answer(ans: str) -> bool:
    """
    Returns True if an answer is non-ambiguous:
    e.g. an integer (42, -5), a decimal (5.82, 0.32), or a simple fraction (4/5, -13/16),
    with optional $, %, or commas.
    Ambiguous answers like expressions (3*sqrt(2), 4+3i, 9\\pi, tuples, equations) return False.
    """
    if not ans:
        return False
    s = str(ans).strip().lower()
    s = s.lstrip('$').rstrip('%')
    s = re.sub(r'(?<=\d),(?=\d)', '', s)
    s = re.sub(r'\s+', '', s)
    # Integer or decimal
    if re.fullmatch(r'-?\d+(\.\d+)?', s):
        return True
    # Simple fraction a/b
    if re.fullmatch(r'-?\d+/\d+', s):
        return True
    return False


def _parse_numeric_value(s: str):
    """Parses a normalized string into float if it is a number or simple fraction."""
    if not s:
        return None
    clean = s.lstrip('$').rstrip('%')
    clean = re.sub(r'(?<=\d),(?=\d)', '', clean)
    clean = re.sub(r'\s+', '', clean)
    if re.fullmatch(r'-?\d+(\.\d+)?', clean):
        try:
            return float(clean)
        except Exception:
            return None
    if re.fullmatch(r'-?\d+/\d+', clean):
        try:
            num, denom = clean.split('/')
            denom_f = float(denom)
            if denom_f != 0:
                return float(num) / denom_f
        except Exception:
            return None
    return None


def check_answer_match(user_answer: str, accepted_answers_json: str, true_answer: str = None) -> bool:
    """
    Checks if user_answer matches any accepted answer for a problem.
    Also handles equivalent numeric representations (e.g. 0.8 vs 4/5, 42.0 vs 42).
    """
    norm_user = normalize_math_answer(user_answer)
    if not norm_user:
        return False

    candidates = []
    if accepted_answers_json:
        try:
            parsed = json.loads(accepted_answers_json)
            if isinstance(parsed, list):
                candidates.extend(parsed)
            elif isinstance(parsed, str):
                candidates.append(parsed)
        except Exception:
            candidates.append(accepted_answers_json)

    if true_answer and true_answer not in candidates:
        candidates.append(true_answer)

    user_val = _parse_numeric_value(norm_user)

    for cand in candidates:
        norm_cand = normalize_math_answer(cand)
        if norm_cand == norm_user:
            return True
        if user_val is not None:
            cand_val = _parse_numeric_value(norm_cand)
            if cand_val is not None and abs(user_val - cand_val) < 1e-9:
                return True

    return False



def fetch_problems_by_filter(sql_db, filter_criteria, room_id=None):
    """
    Fetch problem IDs from the database based on the given filter criteria.

    Args:
        sql_db: Connection to the database.
        filter_criteria (dict): The filter criteria to apply.
        room_id (int, optional): The ID of the room, used as a seed for shuffling. Defaults to None.

    Returns:
        problem_ids (list): A list of problem IDs that match the filter criteria.
    """
    try:
        with sql_db.connect() as conn:
            query = '''
                SELECT id FROM problems
                WHERE year BETWEEN :start_year AND :end_year
                AND format IN :formats
                AND level IN :levels
            '''
            params = {
                'start_year': filter_criteria['start_year'],
                'end_year': filter_criteria['end_year'],
                'formats': tuple(filter_criteria['formats']),
                'levels': tuple(filter_criteria['levels']),
                'start_question': filter_criteria['start_question'],
                'end_question': filter_criteria['end_question'],
            }

            if filter_criteria.get('classifications'):
                query += " AND classification IN :classifications"
                params['classifications'] = tuple(filter_criteria['classifications'])

            if filter_criteria.get('tags'):
                tag_conditions = []
                for i, tag in enumerate(filter_criteria['tags']):
                    tag_param = f"tag_{i}"
                    tag_conditions.append(f"tags LIKE :{tag_param}")
                    params[tag_param] = f"%{tag}%"
                query += f" AND ({' OR '.join(tag_conditions)})"

            query += " AND question_number BETWEEN :start_question AND :end_question"

            if filter_criteria.get('even_only') and not filter_criteria.get('odd_only'):
                query += " AND CAST(question_number AS UNSIGNED) % 2 = 0"
            elif filter_criteria.get('odd_only') and not filter_criteria.get('even_only'):
                query += " AND CAST(question_number AS UNSIGNED) % 2 != 0"
            elif filter_criteria.get('even_only') and filter_criteria.get('odd_only'):
                query += " AND 1=0"  # Return no results if both are checked

            # Add sorting logic for deterministic results
            query += " ORDER BY CAST(question_number AS UNSIGNED), id"

            # Execute the query
            result = conn.execute(sqlalchemy.text(query), params).fetchall()

            if not result:
                print("No problems found matching the filter criteria.")

            problem_ids = [row[0] for row in result]

            # Shuffle the problem IDs in Python if shuffle is enabled
            if filter_criteria.get('shuffle', False):
                if room_id is not None:
                    random.Random(room_id).shuffle(problem_ids)
                else:
                    # Fallback for contexts where room_id is not available
                    random.shuffle(problem_ids)

    except Exception as e:
        print(f"Error fetching problems by filter: {e}")
        problem_ids = []
    return problem_ids


def get_all_filters(sql_db):
    try:
        with sql_db.connect() as conn:
            # Fetch all usernames from the filters table that start with an underscore and sort them alphabetically
            all_filters = conn.execute(sqlalchemy.text('''
                SELECT DISTINCT username FROM filters WHERE username LIKE '\\_%' ORDER BY username ASC
            ''')).fetchall()
    except Exception as e:
        print(f"Error fetching filters: {e}")
        all_filters = []
    return all_filters

def get_sorted_tag_set1(conn):
    # Fetch all unique tags from the database
    results = conn.execute(sqlalchemy.text('''
        SELECT DISTINCT tags FROM problems
    ''')).fetchall()

    # Split and collect unique tags, separating them by commas
    tag_set = set()
    for row in results:
        if (row[0]):
            cleaned_tags = row[0].replace('[', '').replace(']', '').replace("`", '')
            tag_set.update(tag.strip() for tag in cleaned_tags.split(',') if tag.strip())  # Exclude empty tags
    tags = sorted(tag_set)
    return tags

def get_sorted_tag_set(sql_db):
    try:
        with sql_db.connect() as conn:
            # Fetch all unique tags from the database
            results = conn.execute(sqlalchemy.text('''
                SELECT DISTINCT tags FROM problems
            ''')).fetchall()

            # Split and collect unique tags, separating them by commas
            tag_set = set()
            for row in results:
                if row[0]:
                    cleaned_tags = row[0].replace('[', '').replace(']', '').replace("`", '')
                    tag_set.update(tag.strip() for tag in cleaned_tags.split(',') if tag.strip())  # Exclude empty tags

            tags = sorted(tag_set)
    except Exception as e:
        print(f"Error fetching tags: {e}")
        tags = []
    return tags

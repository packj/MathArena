from flask import session, redirect, url_for, render_template_string
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

def fetch_problems_by_filter(sql_db, filter_criteria):
    """
    Fetch problem IDs from the database based on the given filter criteria.

    Args:
        sql_db: Connection to the database.
        filter_criteria (dict): The filter criteria to apply.

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

            # Add sorting logic
            if not filter_criteria.get('shuffle', False):
                query += " ORDER BY CAST(question_number AS UNSIGNED)"  # Sort numerically by question_number

            # Execute the query
            result = conn.execute(sqlalchemy.text(query), params).fetchall()

            if not result:
                print("No problems found matching the filter criteria.")

            # Shuffle the problem IDs if shuffle is enabled
            problem_ids = [row[0] for row in result]

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


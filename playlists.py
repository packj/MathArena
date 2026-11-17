"""
Playlist management routes for MathArena.

A playlist is a named, ordered list of specific problem IDs that any logged-in user
can create. Playlists can be loaded in the Arena Setup (instead of a criteria-based
filter) so a coach or student can curate an exact set of problems.
"""

from flask import Blueprint, request, redirect, url_for, session, render_template, jsonify
import sqlalchemy
from utils import login_required
from db_aws import sql_db

playlists_bp = Blueprint('playlists', __name__)


@playlists_bp.route('/playlists')
@login_required
def list_playlists():
    """Show all playlists and let the user create / edit their own."""
    username = session.get('username')
    try:
        with sql_db.connect() as conn:
            playlists = conn.execute(sqlalchemy.text('''
                SELECT id, name, description, created_by,
                       (LENGTH(problem_ids) - LENGTH(REPLACE(problem_ids, ',', '')) + 1) AS problem_count,
                       created_at
                FROM playlists
                ORDER BY created_by = :username DESC, name ASC
            '''), {'username': username}).fetchall()
    except Exception as e:
        print(f"Error fetching playlists: {e}")
        playlists = []

    return render_template('playlists.html', playlists=playlists, username=username)


@playlists_bp.route('/playlists/new', methods=['GET', 'POST'])
@login_required
def new_playlist():
    """Create a new playlist via a browse-and-add problem UI."""
    username = session.get('username')
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip()
        # problem_ids come as a comma-separated string from the hidden field
        raw_ids = request.form.get('problem_ids', '').strip()
        # Validate: must be non-empty name and at least one problem
        if not name:
            return render_template('playlist_editor.html', error="Playlist name is required.",
                                   problems=[], playlist=None, username=username)
        if not raw_ids:
            return render_template('playlist_editor.html', error="Please add at least one problem.",
                                   problems=[], playlist=None, username=username)
        # Clean the IDs (digits only, comma-separated)
        ids = [i.strip() for i in raw_ids.split(',') if i.strip().isdigit()]
        if not ids:
            return render_template('playlist_editor.html', error="No valid problem IDs found.",
                                   problems=[], playlist=None, username=username)
        try:
            with sql_db.connect() as conn:
                conn.execute(sqlalchemy.text('''
                    INSERT INTO playlists (name, description, created_by, problem_ids)
                    VALUES (:name, :description, :created_by, :problem_ids)
                '''), {
                    'name': name,
                    'description': description,
                    'created_by': username,
                    'problem_ids': ','.join(ids)
                })
                conn.commit()
        except sqlalchemy.exc.IntegrityError:
            return render_template('playlist_editor.html',
                                   error=f"A playlist named \"{name}\" already exists. Choose a different name.",
                                   problems=[], playlist=None, username=username)
        except Exception as e:
            print(f"Error creating playlist: {e}")
            return render_template('playlist_editor.html', error="An error occurred while saving.",
                                   problems=[], playlist=None, username=username)
        return redirect(url_for('playlists.list_playlists'))

    return render_template('playlist_editor.html', error=None, problems=[], playlist=None, username=username)


@playlists_bp.route('/playlists/<int:playlist_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_playlist(playlist_id):
    """Edit an existing playlist. Only the creator (or admin) may edit."""
    username = session.get('username')
    try:
        with sql_db.connect() as conn:
            row = conn.execute(sqlalchemy.text('''
                SELECT id, name, description, created_by, problem_ids
                FROM playlists WHERE id = :id
            '''), {'id': playlist_id}).fetchone()
    except Exception as e:
        print(f"Error fetching playlist {playlist_id}: {e}")
        row = None

    if not row:
        return redirect(url_for('playlists.list_playlists'))

    playlist = {'id': row[0], 'name': row[1], 'description': row[2],
                'created_by': row[3], 'problem_ids': row[4]}

    if username != playlist['created_by'] and username != 'admin':
        return redirect(url_for('playlists.list_playlists'))

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip()
        raw_ids = request.form.get('problem_ids', '').strip()
        ids = [i.strip() for i in raw_ids.split(',') if i.strip().isdigit()]
        if not name or not ids:
            return render_template('playlist_editor.html',
                                   error="Name and at least one problem are required.",
                                   problems=[], playlist=playlist, username=username)
        try:
            with sql_db.connect() as conn:
                conn.execute(sqlalchemy.text('''
                    UPDATE playlists
                    SET name = :name, description = :description, problem_ids = :problem_ids
                    WHERE id = :id
                '''), {
                    'name': name,
                    'description': description,
                    'problem_ids': ','.join(ids),
                    'id': playlist_id
                })
                conn.commit()
        except Exception as e:
            print(f"Error updating playlist {playlist_id}: {e}")
        return redirect(url_for('playlists.list_playlists'))

    return render_template('playlist_editor.html', error=None, problems=[], playlist=playlist, username=username)


@playlists_bp.route('/playlists/<int:playlist_id>/delete', methods=['POST'])
@login_required
def delete_playlist(playlist_id):
    """Delete a playlist. Only the creator (or admin) may delete."""
    username = session.get('username')
    try:
        with sql_db.connect() as conn:
            row = conn.execute(sqlalchemy.text(
                'SELECT created_by FROM playlists WHERE id = :id'
            ), {'id': playlist_id}).fetchone()
            if row and (row[0] == username or username == 'admin'):
                conn.execute(sqlalchemy.text(
                    'DELETE FROM playlists WHERE id = :id'
                ), {'id': playlist_id})
                conn.commit()
    except Exception as e:
        print(f"Error deleting playlist {playlist_id}: {e}")
    return redirect(url_for('playlists.list_playlists'))


@playlists_bp.route('/playlists/<int:playlist_id>/load')
@login_required
def load_playlist(playlist_id):
    """
    Load a playlist into the session as the active problem list.
    Works from both the Arena Setup page and from the main training view.
    """
    try:
        with sql_db.connect() as conn:
            row = conn.execute(sqlalchemy.text('''
                SELECT id, name, problem_ids FROM playlists WHERE id = :id
            '''), {'id': playlist_id}).fetchone()
    except Exception as e:
        print(f"Error loading playlist {playlist_id}: {e}")
        row = None

    if not row:
        return redirect(request.referrer or url_for('playlists.list_playlists'))

    ids = [int(i) for i in row[2].split(',') if i.strip().isdigit()]
    session['problem_ids'] = ids
    session['problem_index'] = 0
    session['show_answer'] = False
    session['display_tags'] = False
    session['points'] = 0
    session['awarded_problems'] = []
    session['playlist_id'] = row[0]
    session['playlist_name'] = row[1]
    # Clear filter_criteria so the arena setup shows the playlist name, not stale filter info
    session['filter_criteria'] = None
    session['filter_name'] = f"playlist_{playlist_id}"

    if request.referrer and '/arena_setup' in request.referrer:
        room_id = session.get('room_id')
        if room_id:
            return redirect(url_for('arena.arena_setup', room_id=room_id))
        return redirect(url_for('arena.arena_setup'))
    return redirect(url_for('landing'))


@playlists_bp.route('/api/problems/search')
@login_required
def api_problem_search():
    """
    JSON API for the playlist editor's problem browser.
    Accepts query params: year, format, level, q (question number), page.
    Returns paginated problem metadata.
    """
    year = request.args.get('year', type=int)
    fmt = request.args.get('format', '')
    level = request.args.get('level', '')
    q_num = request.args.get('q', type=int)
    ids_param = request.args.get('ids', '')
    page = request.args.get('page', 1, type=int)
    per_page = 20

    conditions = []
    params = {}

    if ids_param:
        clean_ids = [int(i.strip()) for i in ids_param.split(',') if i.strip().isdigit()]
        if clean_ids:
            # Fetch by explicit problem IDs (for playlist editor initial loading)
            placeholders = ', '.join([f":id_{i}" for i in range(len(clean_ids))])
            conditions.append(f"id IN ({placeholders})")
            for i, pid in enumerate(clean_ids):
                params[f"id_{i}"] = pid
            per_page = len(clean_ids)

    if year:
        conditions.append('year = :year')
        params['year'] = year
    if fmt:
        conditions.append('format = :format')
        params['format'] = fmt
    if level:
        conditions.append('level = :level')
        params['level'] = level
    if q_num:
        conditions.append('question_number = :q_num')
        params['q_num'] = q_num

    where_clause = ('WHERE ' + ' AND '.join(conditions)) if conditions else ''
    params['offset'] = (page - 1) * per_page
    params['limit'] = per_page

    try:
        with sql_db.connect() as conn:
            rows = conn.execute(sqlalchemy.text(f'''
                SELECT id, year, format, level, question_number, classification
                FROM problems
                {where_clause}
                ORDER BY year DESC, format, level, CAST(question_number AS UNSIGNED)
                LIMIT :limit OFFSET :offset
            '''), params).fetchall()

            total = conn.execute(sqlalchemy.text(f'''
                SELECT COUNT(*) FROM problems {where_clause}
            '''), {k: v for k, v in params.items() if k not in ('limit', 'offset')}).scalar()
    except Exception as e:
        print(f"Error searching problems: {e}")
        return jsonify({'problems': [], 'total': 0, 'page': page, 'per_page': per_page})

    problems = [
        {
            'id': r[0],
            'year': r[1],
            'format': r[2],
            'level': r[3],
            'question_number': r[4],
            'classification': r[5],
            'label': f"{r[1]} {r[3].capitalize()} {r[2].capitalize()} #{r[4]}"
        }
        for r in rows
    ]
    return jsonify({'problems': problems, 'total': total, 'page': page, 'per_page': per_page})


@playlists_bp.route('/api/problems/missed')
@login_required
def api_problems_missed():
    """
    JSON API to fetch problems attempted by the user that resulted in 0 (wrong)
    or 1 (figured out after seeing answer) within an optional time range.
    Includes any problem with result 0 or 1 even if the user subsequently got it right.
    """
    username = session.get('username')
    if not username or not username.isalnum():
        return jsonify({'error': 'Invalid username'}), 400

    start_date = request.args.get('start_date', '').strip()
    end_date = request.args.get('end_date', '').strip()

    table_name = f"results_{username}"
    time_conditions = ["r.result IN (0, 1)"]
    params = {}

    if start_date:
        time_conditions.append("r.time >= :start_time")
        params['start_time'] = f"{start_date} 00:00:00"
    if end_date:
        time_conditions.append("r.time <= :end_time")
        params['end_time'] = f"{end_date} 23:59:59"

    where_sql = " AND ".join(time_conditions)

    try:
        with sql_db.connect() as conn:
            # Check if user results table exists
            check_table = conn.execute(sqlalchemy.text(f"SHOW TABLES LIKE '{table_name}'")).fetchone()
            if not check_table:
                return jsonify({'problems': [], 'total': 0})

            query = sqlalchemy.text(f'''
                SELECT p.id, p.year, p.format, p.level, p.question_number, p.classification,
                       MAX(r.time) AS latest_attempt,
                       COUNT(r.id) AS attempt_count
                FROM {table_name} r
                JOIN problems p ON r.problem_id = p.id
                WHERE {where_sql}
                GROUP BY p.id, p.year, p.format, p.level, p.question_number, p.classification
                ORDER BY latest_attempt DESC
            ''')
            rows = conn.execute(query, params).fetchall()

            problems = [
                {
                    'id': r[0],
                    'year': r[1],
                    'format': r[2],
                    'level': r[3],
                    'question_number': r[4],
                    'classification': r[5],
                    'latest_attempt': r[6].strftime('%Y-%m-%d %H:%M') if r[6] else '',
                    'attempt_count': r[7],
                    'label': f"{r[1]} {str(r[3]).capitalize()} {str(r[2]).capitalize()} #{r[4]}"
                }
                for r in rows
            ]
            return jsonify({'problems': problems, 'total': len(problems)})
    except Exception as e:
        print(f"Error fetching missed problems for {username}: {e}")
        return jsonify({'error': str(e), 'problems': [], 'total': 0}), 500

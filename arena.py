from flask import Blueprint, request, redirect, url_for, session, render_template, jsonify, current_app
import sqlalchemy
import time
import datetime
from utils import login_required, fetch_problems_by_filter, get_all_filters
from db_aws import sql_db

arena_bp = Blueprint('arena', __name__)


def update_in_lobby_flag(username, set_flag):
    """Updates the in_room flag in the arena table."""
    with sql_db.connect() as conn:
        try:
            conn.execute(sqlalchemy.text('''
                UPDATE arena SET in_room = :set_flag, last_active_time = CURRENT_TIMESTAMP WHERE username = :username
            '''), {'username': username, 'set_flag': set_flag})
            conn.commit()
        except Exception as e:
            print(f"Error updating arena table: {e}")


@arena_bp.route('/math_arena')
@login_required
def math_arena():
    # make a list of any rooms that have been busy for more than 70 minutes
    # determine the codename from the form info passed in
    codename = request.args.get('codename', None)
    if codename:
        session['codename'] = codename
    else:
        session['codename'] = None
    try:
        with sql_db.connect() as conn:
            dead_rooms = conn.execute(sqlalchemy.text('''
                SELECT id FROM rooms WHERE room_state = 'busy' AND start_time < NOW() - INTERVAL 70 MINUTE
            ''')).fetchall()
            for room in dead_rooms:
                room_id = room[0]
                conn.execute(sqlalchemy.text('''
                    UPDATE rooms SET room_state = 'empty' WHERE id = :room_id
                '''), {'room_id': room_id})
                conn.commit()
                # Remove users from the room table
                room_table_name = f"room{room_id}"
                conn.execute(sqlalchemy.text(f'''
                    DELETE FROM {room_table_name}
                '''))
    except Exception as e:
        print(f"Error updating busy rooms: {e}")

    username = session.get('username')
    try:
        with sql_db.connect() as conn:
            # Check if the user already exists in the arena table
            existing_user = conn.execute(sqlalchemy.text('''
                SELECT username FROM arena WHERE username = :username
            '''), {'username': username}).fetchone()

            if existing_user is None:
                # Insert a new row if the user doesn't exist
                conn.execute(sqlalchemy.text('''
                    INSERT INTO arena (username) VALUES (:username)
                '''), {'username': username})
            conn.commit()
            update_in_lobby_flag(username, True)
    except Exception as e:
        print(f"Error updating arena table: {e}")

    try:
        with sql_db.connect() as conn:
            users = conn.execute(sqlalchemy.text('''
                SELECT username FROM arena WHERE in_room = TRUE
            ''')).fetchall()
    except Exception as e:
        print(f"Error fetching users from arena table: {e}")
        users = []

    try:
        with sql_db.connect() as conn:
            rooms = conn.execute(sqlalchemy.text('''
                SELECT id, room_state FROM rooms
            ''')).fetchall()
            room_states = {room[0]: room[1] for room in rooms}  # Create a dictionary of room states
    except Exception as e:
        print(f"Error fetching room states: {e}")
        room_states = {}  # Default to empty dictionary if there's an error

    error_message = request.args.get('error_message')

    #get list of users in each room
    users_in_rooms = {} 
    for room_id in room_states.keys():
        try:
            with sql_db.connect() as conn:
                users_in_rooms[room_id] = conn.execute(sqlalchemy.text(f'''
                    SELECT username FROM room{room_id}
                ''')).fetchall()
        except Exception as e:
            print(f"Error fetching users in room {room_id}: {e}")
            users_in_rooms[room_id] = []

    return render_template('math_arena.html', users=users, room_states=room_states, error_message=error_message, users1=users_in_rooms.get(1, []), users2=users_in_rooms.get(2, []), users3=users_in_rooms.get(3, []), users4=users_in_rooms.get(4, []), users5=users_in_rooms.get(5, []))

def id_to_color_and_name(room_id):
    room_colors = {
        '1': '#3498db',  # Blue
        '2': '#e74c3c',  # Red
        '3': '#9b59b6',  # Purple
        '4': '#f39c12',  # Orange
        '5': '#16823e',  # Green
    }
    room_names = {
        '1': 'Blue',
        '2': 'Red',
        '3': 'Purple',
        '4': 'Orange',
        '5': 'Green'
    }
    return room_colors.get(room_id), room_names.get(room_id)    

def join_room(room_table_name, username, conn, room_id):
    # Check if the user is already in the room
    existing_user = conn.execute(sqlalchemy.text(f'''
        SELECT username FROM {room_table_name} WHERE username = :username
    '''), {'username': username}).fetchone()

    if not existing_user:
        # Insert the user into the room table
        conn.execute(sqlalchemy.text(f'''
            INSERT INTO {room_table_name} (username) VALUES (:username)
        '''), {'username': username})
        conn.commit()
        # if user is in another roomN, delete that row
        for i in range(1, 6):
            if i != int(room_id):
                conn.execute(sqlalchemy.text(f'''
                    DELETE FROM room{i} WHERE username = :username
                '''), {'username': username})
                conn.commit()


@arena_bp.route('/arena_setup', methods=['GET'])
@login_required
def arena_setup():
    username = session.get('username')
    print(f"username: {username}")
    room_id = request.args.get('room_id',None)
    if room_id:
        session['room_id'] = room_id
    else:
        room_id = session.get('room_id')
    room_color, room_name = id_to_color_and_name(room_id)
    try:
        with sql_db.connect() as conn:
            # Check the room_state
            room = conn.execute(sqlalchemy.text('''
                SELECT room_state FROM rooms WHERE id = :room_id
            '''), {'room_id': room_id}).fetchone()

            room_number = room_id
            room_table_name = f"room{room_number}"

            print("room state:", room[0])

            if room and room[0] == 'empty':
                print("Room is empty, setting up...")
                # Update the room_state to 'init'
                conn.execute(sqlalchemy.text('''
                    UPDATE rooms SET room_state = 'init' WHERE id = :room_id
                '''), {'room_id': room_id})
                # we remove all users and scores from the room
                conn.execute(sqlalchemy.text(f'''
                    DELETE FROM {room_table_name}
                '''))
                conn.commit()
                #session['filter_criteria'] = None
                session['filter_name'] = f"arena_{room_id}"
                return redirect(url_for('arena.arena_setup', room_id=room_id))
            elif room and room[0] == 'init':
                print("Room is init...")
                # Add the username to the room
                join_room(room_table_name, username, conn, room_id)
                # Set the room_state to 'setup'
                conn.execute(sqlalchemy.text('''
                    UPDATE rooms SET room_state = 'setup' WHERE id = :room_id
                '''), {'room_id': room_id})
                conn.commit()
            elif room and room[0] == 'setup':
                print("Room is being set up...")
                # check if the user is already in the room
                existing_user = conn.execute(sqlalchemy.text(f'''
                    SELECT username FROM {room_table_name} WHERE username = :username
                '''), {'username': username}).fetchone()
                if not existing_user:
                    # Add the username to the room
                    return redirect(url_for('arena.math_arena', error_message="This room is being set up. Please wait a bit."))
            elif room and room[0] == 'joinable':
                print("Room is joinable...")
                # Add the username to the room
                join_room(room_table_name, username, conn, room_id)
                # Redirect to waiting_room
                update_in_lobby_flag(username, False)
                from main import load_filter
                #read the rooms db to get various parameters
                try:
                    with sql_db.connect() as conn:
                        room_id = session.get('room_id')
                        room = conn.execute(sqlalchemy.text('''
                            SELECT collaborative, filter_name, time_limit, live_scoreboard FROM rooms WHERE id = :room_id
                        '''), {'room_id': room_id}).fetchone()
                    if room:
                        session['collaborative'] = 'collaborative' if room[0]==1 else 'competitive'
                        session['filter_name'] = room[1]
                        session['time_limit'] = room[2]
                        session['live_scoreboard'] = True if room[3]==1 else False
                    else:
                        print(f"Room {room_id} not found in the database.")
                    # load the filter
                    filter_name = session.get('filter_name')
                    if filter_name:
                        load_filter(filter_name)
                        filter_criteria = session.get('filter_criteria', None)
                        problem_ids = fetch_problems_by_filter(sql_db, filter_criteria)

                        session['problem_ids'] = problem_ids
                        session['problem_index'] = 0  # Start with the first problem
                        session['show_answer'] = False  # Hide answer
                        session['points'] = 0  # Reset score to 0
                        session['awarded_problems'] = []
                except Exception as e:
                    print(f"Error reading rooms db: {e}")
                return redirect(url_for('arena.waiting_room', room_id=room_id, time_limit=session['time_limit'], mode=session['collaborative'], show_live_score=session['live_scoreboard']))
            else:
                # Redirect back to math_arena with an error message
                return redirect(url_for('arena.math_arena', error_message="Sorry, this room is currently busy."))

        update_in_lobby_flag(username, False)
    except Exception as e:
        print(f"Error updating arena table: {e}")

    print("Room ID:", room_id)
    all_filters = get_all_filters(sql_db)

    # Filter out filters with more than 30 problems
    filters = []
    for filter_username in all_filters:
        filter_username = filter_username[0]
        try:
            with sql_db.connect() as conn:
                # Query for the filter settings of the specified username
                result = conn.execute(sqlalchemy.text('''
                    SELECT start_year, end_year, formats, levels, classifications, tags, start_question, end_question, shuffle
                    FROM filters
                    WHERE username = :username
                    ORDER BY id DESC LIMIT 1
                '''), {'username': filter_username}).fetchone()

                if result:
                    filter_criteria = {
                        'start_year': result[0],
                        'end_year': result[1],
                        'formats': result[2].split(','),
                        'levels': result[3].split(','),
                        'classifications': result[4].split(',') if result[4] else [],
                        'tags': result[5].split(',') if result[5] else [],
                        'start_question': result[6],
                        'end_question': result[7],
                        'shuffle': bool(result[8])
                    }
                    problem_ids = fetch_problems_by_filter(sql_db, filter_criteria)
                    if len(problem_ids) <= 30:
                        filters.append((filter_username,))
        except Exception as e:
            print(f"Error loading filter for {filter_username}: {e}")

    return render_template('arena_setup.html', room_color=room_color, room_name=room_name, filters=filters)

@arena_bp.route('/waiting_room')
@login_required
def waiting_room():
    time_limit = request.args.get('time_limit', None)
    mode = request.args.get('mode', None)
    show_live_score = request.args.get('show_live_score', None)
    room_id = request.args.get('room_id')  # Get the room ID from the request

    room_color, room_name = id_to_color_and_name(room_id)
    # Validate room_color, default to white if invalid
    if not room_color or not room_color.startswith('#') or len(room_color) != 7:
        room_color = '#FFFFFF'

    from db_aws import get_users_in_room  # Import the new function
    users = get_users_in_room(sql_db, room_id)  # Fetch the users in the room
    #determine whether the current user is first in the list of users
    username = session.get('username')
    is_first_user = False
    if users and users[0] == username:
        is_first_user = True

    try:
        with sql_db.connect() as conn:
            room = conn.execute(sqlalchemy.text('''
                SELECT room_state FROM rooms WHERE id = :room_id
            '''), {'room_id': room_id}).fetchone()
            room_state = room[0] if room else 'unknown'
    except Exception as e:
        print(f"Error fetching room state: {e}")
        room_state = 'unknown'

    return render_template('waiting_room.html', time_limit=time_limit, mode=mode, show_live_score=show_live_score, users=users, room_color=room_color, room_name=room_name, room_id=room_id, room_state=room_state, is_first_user=is_first_user)

@arena_bp.route('/get_users_in_room/<room_id>')
@login_required
def get_users_in_room_api(room_id):
    from db_aws import get_users_in_room
    users = get_users_in_room(sql_db, room_id)
    return jsonify(users)

@arena_bp.route('/exit_room')
@login_required
def exit_room():
    username = session.get('username')
    room_id = session.get('room_id')
    print(f"Exiting room {room_id} for user {username}")
    try:
        with sql_db.connect() as conn:
            room_number = room_id
            room_table_name = f"room{room_number}"
            conn.execute(sqlalchemy.text(f'''
                DELETE FROM {room_table_name} WHERE username = :username
            '''), {'username': username})
            conn.commit()
    except Exception as e:
        print(f"Error exiting room: {e}")

    # check if there are any users in the room
    try:
        with sql_db.connect() as conn:
            users_in_room = conn.execute(sqlalchemy.text(f'''
                SELECT username FROM {room_table_name}
            ''')).fetchall()
            if not users_in_room:
                # If no users are left, set room_state to empty
                conn.execute(sqlalchemy.text('''
                    UPDATE rooms SET room_state = 'empty' WHERE id = :room_id
                '''), {'room_id': room_id})
                conn.commit()
    except Exception as e:
        print(f"Error checking users in room: {e}")

    update_in_lobby_flag(username, True)
    session.pop('room_id', None)  # Remove room_id from session
    return redirect(url_for('arena.math_arena'))

@arena_bp.route('/start_contest/<room_id>')
@login_required
def start_contest(room_id):
    try:
        with sql_db.connect() as conn:
            conn.execute(sqlalchemy.text('''
                UPDATE rooms SET room_state = 'busy' WHERE id = :room_id
            '''), {'room_id': room_id})
            conn.commit()
    except Exception as e:
        print(f"Error updating room state: {e}")
    session['room_id'] = room_id
    # add timestamp column to rooms table
    #try:
    #    with sql_db.connect() as conn:
    #        conn.execute(sqlalchemy.text('''
    #            ALTER TABLE rooms ADD COLUMN start_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    #        '''))
    #        conn.commit()
    #except Exception as e:
    #    print(f"Error adding start_time column: {e}")

    #set the timestamp for the current room to the current time
    try:
        with sql_db.connect() as conn:
            conn.execute(sqlalchemy.text('''
                UPDATE rooms SET start_time = CURRENT_TIMESTAMP WHERE id = :room_id
            '''), {'room_id': room_id})
            conn.commit()
    except Exception as e:
        print(f"Error updating start_time: {e}")

    return redirect(url_for('arena.arena_problem'))

@arena_bp.route('/leave_room_and_logout')
@login_required
def leave_room_and_logout():
    username = session.get('username')
    room_id = session.get('room_id')

    try:
        with sql_db.connect() as conn:
            room_number = room_id
            room_table_name = f"room{room_number}"
            conn.execute(sqlalchemy.text(f'''
                DELETE FROM {room_table_name} WHERE username = :username
            '''), {'username': username})
            conn.commit()
    except Exception as e:
        print(f"Error exiting room: {e}")

    # check if there are any users in the room
    try:
        with sql_db.connect() as conn:
            users_in_room = conn.execute(sqlalchemy.text(f'''
                SELECT username FROM {room_table_name}
            ''')).fetchall()
            if not users_in_room:
                # If no users are left, set room_state to empty
                conn.execute(sqlalchemy.text('''
                    UPDATE rooms SET room_state = 'empty' WHERE id = :room_id
                '''), {'room_id': room_id})
                conn.commit()
    except Exception as e:
        print(f"Error checking users in room: {e}")

    update_in_lobby_flag(username, False)
    return redirect(url_for('logout'))


@arena_bp.route('/arena_problem')
@login_required
def arena_problem():
    read_db = request.args.get('read_db', None)
    dont_read_db = True
    if read_db == '1' and not dont_read_db:
        from main import load_filter
        #read the rooms db to get various parameters
        try:
            with sql_db.connect() as conn:
                room_id = session.get('room_id')
                room = conn.execute(sqlalchemy.text('''
                    SELECT collaborative, filter_name, time_limit, live_scoreboard FROM rooms WHERE id = :room_id
                '''), {'room_id': room_id}).fetchone()
            if room:
                session['collaborative'] = room[0]
                session['filter_name'] = room[1]
                session['time_limit'] = room[2]
                session['live_scoreboard'] = room[3]
            else:
                print(f"Room {room_id} not found in the database.")
            # load the filter
            filter_name = session.get('filter_name')
            if filter_name:
                load_filter(filter_name)
                filter_criteria = session.get('filter_criteria', None)
                problem_ids = fetch_problems_by_filter(sql_db, filter_criteria)
                    
                session['problem_ids'] = problem_ids
                session['problem_index'] = 0  # Start with the first problem
                session['show_answer'] = False  # Hide answer
                session['points'] = 0  # Reset score to 0
                session['awarded_problems'] = []
        except Exception as e:
            print(f"Error reading rooms db: {e}")
    else:
        print("Not reading rooms db...")
    elapsed_time = 0  # Initialize elapsed_time
    # grab the timestamp from the rooms table
    try:
        with sql_db.connect() as conn:
            room_id = session.get('room_id')
            start_time_result = conn.execute(sqlalchemy.text('''
                SELECT start_time FROM rooms WHERE id = :room_id
            '''), {'room_id': room_id}).fetchone()

            if start_time_result and start_time_result[0]:
                start_time = start_time_result[0]
                current_time = datetime.datetime.utcnow()

                start_time_epoch = time.mktime(start_time.timetuple())
                current_time_epoch = time.mktime(current_time.timetuple())

                elapsed_time = current_time_epoch - start_time_epoch
            conn.commit()
    except Exception as e:
        print(f"Error fetching start_time: {e}")
    room_id = session.get('room_id')
    time_limit = session.get('time_limit')
    remaining_time_sec = time_limit * 60 - elapsed_time if time_limit else None

    if remaining_time_sec <= 0:
        return redirect(url_for('arena.contest_summary', room_id=room_id))

    room_color, room_name = id_to_color_and_name(room_id)
    # Validate room_color, default to white if invalid
    if not room_color or not room_color.startswith('#') or len(room_color) != 7:
        room_color = '#FFFFFF'
    try:
        with sql_db.connect() as conn:
            problem_ids = session.get('problem_ids', [])
            problem_index = session.get('problem_index', 0)
            my_id = problem_ids[problem_index]
            problem_query = '''
                SELECT classification, link, tags, question_ref, answer_ref, year, level, format, question_number FROM problems WHERE id = :id
            '''
            problem = conn.execute(sqlalchemy.text(problem_query), {'id': my_id}).fetchone()
            if not problem:
                return "Problem not found."
            current_year = problem[5]
            current_format = problem[7]
            current_level = problem[6]
            question_number = problem[8]
            current_classification = problem[0]
            Q_name = problem[3].replace('Questions/', '')
            A_name = problem[4].replace('Answers/', '')
            Q_url = url_for('serve_image', image_type='Questions', image_name=Q_name)
            A_url = url_for('serve_image', image_type='Answers', image_name=A_name)
            show_answer = session.get('show_answer', False)
            user_answer = session.get('user_answer', '')
            problem_index_display = f"{problem_index + 1}/{len(problem_ids)}"
            # Fetch points from the room table
            room_number = room_id
            room_table_name = f"room{room_number}"
            points_query = f'''
                SELECT score FROM {room_table_name} WHERE username = :username
            '''
            points_result = conn.execute(sqlalchemy.text(points_query), {'username': session.get('username')}).fetchone()
            points = points_result[0] if points_result else 0

            return render_template(
                'arena_problem.html',
                question_number=question_number,
                current_year=current_year,
                current_format=current_format,
                current_level=current_level,
                current_classification=current_classification,
                Q_url=Q_url,
                A_url=A_url,
                show_answer=show_answer,
                points=points,
                problem_index_display=problem_index_display,
                my_id=my_id,
                user_answer=user_answer,
                room_id=room_id,
                time_limit=remaining_time_sec,
                room_color=room_color,
                room_name=room_name
            )
    except Exception as e:
        print(f"Error during display problem: {e}")
        return "An error occurred while displaying the problem."

@arena_bp.route('/contest_summary/<room_id>')
@login_required
def contest_summary(room_id):
    room_color, room_name = id_to_color_and_name(room_id)
    try:
        with sql_db.connect() as conn:
            room_number = room_id
            room_table_name = f"room{room_number}"
            scores_query = f'''
                SELECT username, score FROM {room_table_name}
            '''
            scores_result = conn.execute(sqlalchemy.text(scores_query)).fetchall()
            scores = [(row[0], row[1]) for row in scores_result]
    except Exception as e:
        print(f"Error fetching scores from room {room_id}: {e}")
        scores = []

    return render_template('contest_summary.html', room_color=room_color, room_name=room_name, room_id=room_id, scores=scores)

@arena_bp.route('/get_room_state/<room_id>')
@login_required
def get_room_state(room_id):
    try:
        with sql_db.connect() as conn:
            room = conn.execute(sqlalchemy.text('''
                SELECT room_state FROM rooms WHERE id = :room_id
            '''), {'room_id': room_id}).fetchone()
            room_state = room[0] if room else 'unknown'
        return jsonify({'room_state': room_state})
    except Exception as e:
        print(f"Error getting room state: {e}")
        return jsonify({'room_state': 'unknown'})

@arena_bp.route('/update_room_state')
@login_required
def update_room_state():
    room_id = request.args.get('room_id')
    state = request.args.get('state')

    try:
        with sql_db.connect() as conn:
            conn.execute(sqlalchemy.text('''
                UPDATE rooms SET room_state = :state WHERE id = :room_id
            '''), {'room_id': room_id, 'state': state})
            conn.commit()
    except Exception as e:
        print(f"Error updating room state: {e}")

    return redirect(url_for('arena.math_arena'))

@arena_bp.route('/arena_setup', methods=['POST'])
@login_required
def arena_setup_post():
    num_problems = int(request.form['num_problems'])
    if num_problems > 30:
        num_problems = 30

    filter_name = session.get('filter_name', None)
    print(f"----------------filter_name: {filter_name}")
    filter_criteria = session.get('filter_criteria', None)
    if not filter_criteria:
        return "No filter criteria found. Please set up filter criteria first."

    problem_ids = fetch_problems_by_filter(sql_db, filter_criteria)
    if len(problem_ids) > num_problems:
        problem_ids = problem_ids[:num_problems]

    session['problem_ids'] = problem_ids
    session['problem_index'] = 0  # Start with the first problem
    session['show_answer'] = False  # Hide answer
    session['display_tags'] = False  # Hide tags
    session['points'] = 0  # Reset score to 0
    session['awarded_problems'] = []

    time_limit = int(request.form['time_limit'])
    mode = request.form['mode']
    show_live_score = 'show_live_score' in request.form
    session['time_limit'] = time_limit  # Store time_limit in session

    '''
        collaborative BOOLEAN,
        filter_name VARCHAR(255),
        time_limit INT,
        live_scoreboard BOOLEAN 
    '''
    # set the parameters in the rooms dbase
    room_id = session.get('room_id')
    with sql_db.connect() as conn:
        conn.execute(sqlalchemy.text('''
            UPDATE rooms SET collaborative = :collaborative, filter_name = :filter_name, time_limit = :time_limit, live_scoreboard = :live_scoreboard WHERE id = :room_id
        '''), {'collaborative': mode == 'collaborative', 'filter_name': filter_name, 'time_limit': time_limit, 'live_scoreboard': show_live_score, 'room_id': room_id})
        conn.commit()

    # set room_status to joinable
    room_id = session.get('room_id')
    with sql_db.connect() as conn:
        conn.execute(sqlalchemy.text('''
            UPDATE rooms SET room_state = 'joinable' WHERE id = :room_id
        '''), {'room_id': room_id})
        conn.commit()

    return redirect(url_for('arena.waiting_room', time_limit=time_limit, mode=mode, show_live_score=show_live_score, room_id=room_id))

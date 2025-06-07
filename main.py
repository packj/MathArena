from flask import Flask, send_file, abort, render_template_string, request, redirect, url_for, session, render_template, jsonify
from google.cloud import storage
from datetime import timedelta
from google.cloud.storage import Blob
from io import BytesIO
import sqlalchemy
import random
import yaml # Import yaml
#from connect_connector import connect_with_connector
from db import init_connection_pool  # Import the database setup function
from user_logs_routes import user_logs_bp
from admin_routes import admin_bp  # Import the Blueprint
from arena import arena_bp, update_in_lobby_flag  # Import the Blueprint
from contributions import contrib_bp
from utils import login_required, fetch_problems_by_filter, get_all_filters, get_sorted_tag_set  # Import from utils
from db import sql_db  # Import the SQLAlchemy engine


app = Flask(__name__)

# Load sensitive information from math_arena.yaml
with open('math_arena.yaml', 'r') as file:
    config = yaml.safe_load(file)

app.secret_key = config['secret_key']  # Secret key for session management

@app.before_request
def init_sql_db() -> None:
    """Initiates connection to database and its structure."""
    if sql_db is None:
        init_connection_pool()
        print("Database connection pool initialized.")

# Register the Blueprints
app.register_blueprint(admin_bp, url_prefix='/admin')
app.register_blueprint(arena_bp, url_prefix='/arena')
app.register_blueprint(contrib_bp, url_prefix='/contrib')
app.register_blueprint(user_logs_bp)


def render_register_form(error_message=None, username=""):
    """Helper function to render the registration form with an optional error message."""
    return render_template('register.html', error_message=error_message, username=username)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        grade = request.form['grade']
        email = request.form.get('email', '')  # Email is optional
        note = request.form.get('note', '') # Note is optional
        is_13_or_older = request.form.get('is_13_or_older', False)

        if email and not is_13_or_older:
            return render_register_form(
                error_message='If you supply an email address, you must affirm that the email owner is 13 or older.',
                username=username
            )

        if not username.isalnum():
            return render_register_form(
                error_message=f'The username "{username}" contains invalid characters. Please use only letters and numbers.',
                username=username
            )

        try:
            with sql_db.connect() as conn:
                # Check if the username already exists
                existing_user = conn.execute(sqlalchemy.text('''
                    SELECT id FROM users WHERE username = :username
                '''), {'username': username}).fetchone()

                if existing_user:
                    return render_register_form(
                        error_message=f'The username "{username}" is already in use. Please choose a different username.',
                        username=username
                    )

                # If the users table doesn't have a note column, add it
                result = conn.execute(sqlalchemy.text('''
                    SHOW COLUMNS FROM users LIKE 'note'
                ''')).fetchone()
                if not result:
                    conn.execute(sqlalchemy.text('''
                        ALTER TABLE users ADD COLUMN note TEXT
                    '''))

                # Execute the INSERT query
                conn.execute(sqlalchemy.text('''
                    INSERT INTO users (username, password, first_name, last_name, grade, school, email, note)
                    VALUES (:username, :password, 'Not collected', 'Not collected', :grade, 'Not collected', :email, :note)
                '''), {
                    'username': username,
                    'password': password,
                    'grade': grade,
                    'email': email,
                    'note': note
                })
                conn.commit()
            return render_template_string('''
                <!doctype html>
                <title>Registration Successful</title>
                <h1>Thank you for registering!</h1>
                <p>Your application has been submittted. Please wait for an admin to approve your account.</p>
                <a href="/login">Return to Login</a>
            ''')
        except Exception as e:
            print(f"Error inserting user into database: {e}")
            return 'An error occurred while creating the account.'

    return render_register_form()

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        try:
            with sql_db.connect() as conn:
                # Query the database for the user
                result = conn.execute(sqlalchemy.text('''
                    SELECT * FROM users WHERE username = :username AND (password = :password OR temp_password = :password) AND approved = 1
                '''), {
                    'username': username,
                    'password': password
                }).fetchone()

                if result:
                    session['logged_in'] = True
                    session['username'] = username  # Store the username in the session
                    session['filter_criteria'] = None  # Reset filter criteria in the session
                    
                    print(result[10])  # Debugging line to check temp_password value
                    # Redirect to change_password to change password if logged in with temp_password
                    if result[10] is not None:  # Assuming temp_password is the 7th column in the users table
                        return redirect(url_for('change_password'))
                    else:
                        return redirect(url_for('landing'))  # Redirect to landing page
                else:
                    return 'Invalid credentials or account not approved'
        except Exception as e:
            # Debugging: Log any errors
            print(f"Error during login: {e}")
            return 'An error occurred during login.'
    return render_template('login.html')

import secrets

@app.route('/logout')
def logout():
    username = session.get('username')
    try:
        update_in_lobby_flag(username, False)
    except Exception as e:
        print(f"Error updating arena table: {e}")
    session.pop('logged_in', None)
    session.pop('username', None)  # Remove the username from the session
    return redirect(url_for('login'))


@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        try:
            with sql_db.connect() as conn:
                # Check if the username and email match
                user = conn.execute(sqlalchemy.text('''
                    SELECT * FROM users WHERE username = :username
                '''), {'username': username}).fetchone()
                print(user)  # Debugging line to check user details
                if user is None or user[8] != email:  # Assuming email is the 9th column (index 8)
                    return render_template_string('''
                        <!doctype html>
                        <title>Password Reset Failed</title>
                        <h1>Password Reset Failed</h1>
                        <p>Username and email do not match.</p>
                        <a href="/forgot_password">Try Again</a>
                    ''')

                # Generate a temporary password
                temp_password = secrets.token_urlsafe(16)

                # Check if the temp_password column exists, and add it if missing
                result = conn.execute(sqlalchemy.text('''
                    SHOW COLUMNS FROM users LIKE 'temp_password'
                ''')).fetchone()
                if not result:
                    conn.execute(sqlalchemy.text('''
                        ALTER TABLE users ADD COLUMN temp_password TEXT
                    '''))
                    conn.commit()

                # Update the user's temp_password in the database
                conn.execute(sqlalchemy.text('''
                    UPDATE users SET temp_password = :temp_password WHERE username = :username
                '''), {
                    'username': username,
                    'temp_password': temp_password
                })
                conn.commit()
                # Display a success message
                return render_template_string('''
                    <!doctype html>
                    <title>Password Reset</title>
                    <h1>Password Reset Initiated</h1>
                    <p>A temporary password has been generated for your account.</p>
                    <p>You will eventually receive an email from the website admin with this temporary password.</p>
                    <p>If you are in a hurry, you may want to email the admin and ask him to check on this.</p>
                    <p>Alternatively, you can just create a new account and try not to forget your password this time.</p>
                    <a href="/login">Return to Login</a>
                ''')
        except Exception as e:
            print(f"Error updating password: {e}")
            return 'An error occurred while resetting the password.'
    return render_template('forgot_password.html')

@app.route('/serve_image/<path:image_type>/<path:image_name>')
@login_required
def serve_image(image_type, image_name):
    """
    Serve images (questions or answers) from Google Cloud Storage to avoid CORB issues.
    """
    bucket_name = "mflashcards"
    storage_client = storage.Client()
    bucket = storage_client.bucket(bucket_name)
    blob_name = f"{image_type}/{image_name}"
    blob = bucket.blob(blob_name)

    if not blob.exists(storage_client):
        # Serve the backup image if the requested image does not exist
        backup_blob_name = "cards/noImage.png"
        backup_blob = bucket.blob(backup_blob_name)
        if not backup_blob.exists(storage_client):
            return abort(404)  # Return 404 if the backup image also does not exist
        image_data = backup_blob.download_as_bytes()
        return send_file(BytesIO(image_data), mimetype='image/png')

    # Fetch the requested image content
    image_data = blob.download_as_bytes()
    return send_file(BytesIO(image_data), mimetype='image/png')

@app.route('/')
@login_required
def index():
    return redirect(url_for('landing'))

@app.route('/landing', methods=['GET', 'POST'])
@login_required
def landing():
    """Redirect to the appropriate landing page based on the username."""
    if session.get('username') == 'admin':
        return redirect(url_for('admin.admin_landing'))
    return redirect(url_for('main_landing'))

@app.route('/change_password', methods=['GET', 'POST'])
@login_required
def change_password():
    """Page for users to change their password."""
    username = session.get('username')
    if request.method == 'POST':
        old_password = request.form['old_password']
        new_password = request.form['new_password']
        try:
            with sql_db.connect() as conn:
                # Verify the old password
                result = conn.execute(sqlalchemy.text('''
                    SELECT * FROM users WHERE username = :username AND (password = :old_password OR temp_password = :old_password)
                '''), {
                    'username': username,
                    'old_password': old_password
                }).fetchone()

                if not result:
                    return render_template_string('''
                        <!doctype html>
                        <title>My Account</title>
                        <h1>My Account</h1>
                        <p>Incorrect old password.</p>
                        <button onclick="window.location.href='/change_password'">Try Again</button>
                    ''')

                # Update the password
                conn.execute(sqlalchemy.text('''
                    UPDATE users SET password = :new_password WHERE username = :username
                '''), {
                    'username': username,
                    'new_password': new_password
                })

                # Clear the temporary password if it was used
                conn.execute(sqlalchemy.text('''
                    UPDATE users SET temp_password = NULL WHERE username = :username AND temp_password = :old_password
                '''), {
                    'username': username,
                    'old_password': old_password
                })
                conn.commit()

                return render_template_string('''
                    <!doctype html>
                    <title>My Account</title>
                    <h1>My Account</h1>
                    <p>Password changed successfully.</p>
                    <button onclick="window.location.href='/main_landing'">Back to Home</button>
                ''')
        except Exception as e:
            print(f"Error updating password: {e}")
            return 'An error occurred while changing the password.'

    return render_template('change_password.html')

def get_question_count(filter_criteria):
    if filter_criteria:
        problem_ids = fetch_problems_by_filter(sql_db, filter_criteria)
        question_count = len(problem_ids)
    else:
        question_count = 0
    return question_count

@app.route('/refresh_count', methods=['POST'])
@login_required
def refresh_count():
    start_year = int(request.form.get('start_year', 2000))
    end_year = int(request.form.get('end_year', 2024))
    start_question = int(request.form.get('start_question', 1))
    end_question = int(request.form.get('end_question', 30))
    print(f"start_year: {start_year}, end_year: {end_year}, start_question: {start_question}, end_question: {end_question}")

    filter_criteria = {
        'start_year': start_year,
        'end_year': end_year,
        'formats': request.form.getlist('formats'),
        'levels': request.form.getlist('levels'),
        'classifications': request.form.getlist('classifications'),
        'tags': request.form.getlist('tags'),
        'start_question': start_question,
        'end_question': end_question,
        'shuffle': 'shuffle' in request.form
    }

    session['question_count'] = get_question_count(filter_criteria)


    return jsonify({'count': session['question_count']})

@app.route('/main_landing', methods=['GET', 'POST'])
@login_required
def main_landing():
    """Landing page for regular users."""
    filter_criteria = session.get('filter_criteria', None)
    username = session.get('username', '')
    update_in_lobby_flag(username, False)

    if request.method == 'POST':
        codename = request.form.get('codename', '').strip()
        if codename:
            session['codename'] = codename
        return redirect(url_for('launch_training'))

    # Fetch the latest filter criteria from the session or database
    # ...existing code for fetching filter_criteria...
    if not filter_criteria:
        try:
            with sql_db.connect() as conn:
                # Query for the last saved filter for the current user
                result = conn.execute(sqlalchemy.text('''
                    SELECT start_year, end_year, formats, levels, classifications, tags, start_question, end_question, shuffle
                    FROM filters
                    WHERE username = :username
                    ORDER BY id DESC LIMIT 1
                '''), {'username': session.get('username')}).fetchone()

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
                    session['filter_criteria'] = filter_criteria  # Save to session
                else:
                    # If no user-specific filters, query for admin filters
                    admin_result = conn.execute(sqlalchemy.text('''
                        SELECT start_year, end_year, formats, levels, classifications, tags, start_question, end_question, shuffle
                        FROM filters
                        WHERE username = 'admin'
                        ORDER BY id DESC LIMIT 1
                    ''')).fetchone()

                    if admin_result:
                        filter_criteria = {
                            'start_year': admin_result[0],
                            'end_year': admin_result[1],
                            'formats': admin_result[2].split(','),
                            'levels': admin_result[3].split(','),
                            'classifications': admin_result[4].split(',') if admin_result[4] else [],
                            'tags': admin_result[5].split(',') if admin_result[5] else [],
                            'start_question': admin_result[6],
                            'end_question': admin_result[7],
                            'shuffle': bool(admin_result[8])
                        }
                        session['filter_criteria'] = filter_criteria  # Save to session
                    else:
                        filter_criteria = None  # No filters found for admin or user
        except Exception as e:
            print(f"Error fetching filter criteria: {e}")
            filter_criteria = None

    if filter_criteria:
        problem_ids = fetch_problems_by_filter(sql_db, filter_criteria)
        question_count = len(problem_ids)
    else:
        question_count = 0

    filters = get_all_filters(sql_db)
    filter_loaded_message = session.pop('filter_loaded_message', None)  # Retrieve and clear the success message

    return render_template(
        'main_landing.html',
        filter_criteria=filter_criteria,
        question_count=question_count,
        filters=filters,
        filter_loaded_message=filter_loaded_message
    )

@app.route('/load_filter/<username>')
@login_required
def load_filter(username):
    """
    Load filter settings for the specified username and redirect back to the landing page.
    """
    # store username in session as filter_name
    session['filter_name'] = username
    print("session filter_name: ", session['filter_name'])
    try:
        with sql_db.connect() as conn:
            # Query for the filter settings of the specified username
            result = conn.execute(sqlalchemy.text('''
                SELECT start_year, end_year, formats, levels, classifications, tags, start_question, end_question, shuffle
                FROM filters
                WHERE username = :username
                ORDER BY id DESC LIMIT 1
            '''), {'username': username}).fetchone()

            if result:
                # Update session with the loaded filter settings
                session['filter_criteria'] = {
                    'start_year': result[0],
                    'end_year': result[1],
                    'formats': result[2].split(','),
                    'levels': result[3].split(','),
                    'classifications': result[4].split(',') if result[4] else [],  # Handle NULL classifications
                    'tags': result[5].split(',') if result[5] else [],  # Handle NULL tags
                    'start_question': result[6],
                    'end_question': result[7],
                    'shuffle': bool(result[8])
                }
                # Ensure session variables are properly set for training
                session['problem_ids'] = []
                session['problem_index'] = 0
                session['show_answer'] = False
                session['display_tags'] = False
                session['points'] = 0
                session['awarded_problems'] = []
                filter_clean = username[1:]  # Remove the leading underscore for display
                session['filter_loaded_message'] = f"""Filter "{filter_clean}" was successfully loaded."""  # Add success message
                if request.referrer and '/arena_setup' in request.referrer:
                    return redirect(url_for('arena.arena_setup'))
                else:
                    return redirect(url_for('landing'))  # Redirect back to the landing page
            else:
                return f"No filters found for user: {username}"
    except Exception as e:
        print(f"Error loading filter for {username}: {e}")
        return "An error occurred while loading the filter."

@app.route('/setup_filter', methods=['GET', 'POST'])
@login_required
def setup_filter():
    if request.method == 'POST':
        start_year = int(request.form.get('start_year', 2000))
        end_year = int(request.form.get('end_year', 2024))

        # check if the user is in a room
        room_id = session.get('room_id', None)
        if room_id:
            filter_name = f"arena_{room_id}"
            session['filter_name'] = filter_name  # Store the filter name in the session
        else:
            # Add an underscore to the filter name if the user is admin
            filter_name = f"_{request.form.get('filter_name')}" if session.get('username') == 'admin' else session['username']
        filter_criteria = {
            'start_year': start_year,
            'end_year': end_year,
            'formats': request.form.getlist('formats'),
            'levels': request.form.getlist('levels'),
            'classifications': request.form.getlist('classifications'),
            'tags': request.form.getlist('tags'),
            'start_question': int(request.form.get('start_question', 1)),
            'end_question': int(request.form.get('end_question', 30)),
            'shuffle': 'shuffle' in request.form
        }
        session['filter_criteria'] = filter_criteria

        # Save or update filter criteria in the database
        try:
            with sql_db.connect() as conn:
                # Check if a row already exists for the filter name
                existing_row = conn.execute(sqlalchemy.text('''
                    SELECT id FROM filters WHERE username = :username
                '''), {'username': filter_name}).fetchone()

                if existing_row:
                    # Update the existing filter
                    conn.execute(sqlalchemy.text('''
                        UPDATE filters
                        SET start_year = :start_year, end_year = :end_year, formats = :formats,
                            levels = :levels, classifications = :classifications, tags = :tags,
                            start_question = :start_question, end_question = :end_question, shuffle = :shuffle
                        WHERE username = :username
                    '''), {
                        'username': filter_name,
                        'start_year': filter_criteria['start_year'],
                        'end_year': filter_criteria['end_year'],
                        'formats': ','.join(filter_criteria['formats']),
                        'levels': ','.join(filter_criteria['levels']),
                        'classifications': ','.join(filter_criteria['classifications']),
                        'tags': ','.join(filter_criteria['tags']),
                        'start_question': filter_criteria['start_question'],
                        'end_question': filter_criteria['end_question'],
                        'shuffle': int(filter_criteria['shuffle'])  # Convert boolean to integer
                    })
                else:
                    # Insert a new row if no existing row is found
                    conn.execute(sqlalchemy.text('''
                        INSERT INTO filters (username, start_year, end_year, formats, levels, classifications, tags, start_question, end_question, shuffle)
                        VALUES (:username, :start_year, :end_year, :formats, :levels, :classifications, :tags, :start_question, :end_question, :shuffle)
                    '''), {
                        'username': filter_name,
                        'start_year': filter_criteria['start_year'],
                        'end_year': filter_criteria['end_year'],
                        'formats': ','.join(filter_criteria['formats']),
                        'levels': ','.join(filter_criteria['levels']),
                        'classifications': ','.join(filter_criteria['classifications']),
                        'tags': ','.join(filter_criteria['tags']),
                        'start_question': filter_criteria['start_question'],
                        'end_question': filter_criteria['end_question'],
                        'shuffle': int(filter_criteria['shuffle'])  # Convert boolean to integer
                    })
                conn.commit()
        except Exception as e:
            print(f"Error saving filters to database: {e}")
            return 'An error occurred while saving the filters.'
        if room_id:
            return redirect(url_for('arena.arena_setup'))
        else:
            return redirect(url_for('landing'))

    # Fetch the current filter criteria from the session or use defaults this is line 482
    filter_criteria = session.get('filter_criteria')
    if filter_criteria is None:
        filter_criteria = {
            'start_year': 2000,
            'end_year': 2024,
            'formats': ['sprint'],
            'levels': ['chapter'],
            'classifications': [],
            'tags': [],
            'start_question': 1,
            'end_question': 30,
            'shuffle': False
        }
    filter_criteria['start_question'] = int(filter_criteria.get('start_question', 1))
    filter_criteria['end_question'] = int(filter_criteria.get('end_question', 30))
    print("filter_criteria: ", filter_criteria)

    # Add a session variable to track tag visibility
    if 'show_tags' not in session:
        session['show_tags'] = False
    #test
    years = range(2000, 2025)
    formats = ['sprint', 'target', 'team']
    levels = ['school', 'chapter', 'state', 'national']
    classifications = ['Arithmetic', 'Statistics', 'Number Theory', 'Algebra', 'Probability and Counting', 'Geometry', 'None']

    tags = get_sorted_tag_set(sql_db)

    question_count = session.get('question_count', 0)
    print("filter_criteria2: ", filter_criteria)

    return render_template('setup_filter.html', years=years, formats=formats, levels=levels, classifications=classifications, tags=tags, filter_criteria=filter_criteria, question_count=question_count)

@app.route('/toggle_tags_visibility', methods=['POST'])
@login_required
def toggle_tags_visibility():
    session['show_tags'] = not session.get('show_tags', False)
    return '', 204

@app.route('/launch_training')
@login_required
def launch_training():
    filter_criteria = session.get('filter_criteria', {})
    if not filter_criteria:
        return "No filter criteria found. Please set up filter criteria first."

    problem_ids = fetch_problems_by_filter(sql_db, filter_criteria)  # Updated to use utils.fetch_problems_by_filter
    if filter_criteria.get('shuffle', False):
        random.shuffle(problem_ids)

    # Update session with the problem IDs
    session['problem_ids'] = problem_ids
    session['problem_index'] = 0  # Start with the first problem
    session['show_answer'] = False  # Hide answer
    session['display_tags'] = False  # Hide tags
    session['points'] = 0  # Reset score to 0
    session['awarded_problems'] = []  # Reset awarded_problems to an empty set

    return redirect(url_for('display_problem'))

@app.route('/display_problem', methods=['GET', 'POST'])
@login_required
def display_problem():
    if request.method == 'POST':
        print("we got a post request")
        # Im not sure this code is ever used now that we have submit_answer:
        user_answer = request.form.get('user_answer', '').strip()  # Get the user's answer from the form
        session['user_answer'] = user_answer  # Store the user's answer in the session
        session['show_answer'] = True  # Show answer after submission
        return redirect(url_for('display_problem'))

    problem_ids = session.get('problem_ids', [])
    problem_index = session.get('problem_index', 0)

    if not problem_ids or problem_index >= len(problem_ids):
        return "No problems to display. Please restart training."

    try:
        with sql_db.connect() as conn:
            # Fetch the problem details for the current ID
            my_id = problem_ids[problem_index]
            problem_query = '''
                SELECT classification, link, tags, question_ref, answer_ref, year, level, format, question_number FROM problems WHERE id = :id
            '''
            problem = conn.execute(sqlalchemy.text(problem_query), {'id': my_id}).fetchone()

            if not problem:
                return "Problem not found."

            current_classification = problem[0]
            current_link = problem[1]
            current_tags = problem[2]
            Q_name = problem[3].replace('cards/', '')
            A_name = problem[4].replace('Answers/', '')
            current_year = problem[5]
            current_level = problem[6]
            current_format = problem[7]
            question_number = problem[8]

            # Display the image referenced by question_ref
            Q_url = url_for('serve_image', image_type='cards', image_name=Q_name)
            A_url = url_for('serve_image', image_type='Answers', image_name=A_name)

            # Toggle answer and tags visibility
            show_answer = session.get('show_answer', False)
            display_tags = session.get('display_tags', False)
            points = session.get('points', 0)
            user_answer = session.get('user_answer', '')

            # Calculate problem index display
            problem_index_display = f"{problem_index + 1}/{len(problem_ids)}"

            embed_link = None
            if current_link:
                if 'youtu.be' in current_link:
                    embed_link = current_link.replace("youtu.be/", "youtube.com/embed/").replace("?t=", "?start=")
                elif 'youtube.com' in current_link:
                    embed_link = current_link.replace("youtube.com/watch?v=", "youtube.com/embed/").replace("&t=", "?start=")
                else:
                    embed_link = current_link


            # Fetch attempt history for the current problem
            attempt_history = []
            try:
                table_name = f"results_{session.get('username')}"
                results = conn.execute(sqlalchemy.text(f'''
                    SELECT result FROM {table_name} WHERE problem_id = :problem_id ORDER BY time ASC
                '''), {'problem_id': my_id}).fetchall()
                for row in results:
                    if row[0] == 2:
                        attempt_history.append('<span class="square green"></span>')
                    elif row[0] == 1:
                        attempt_history.append('<span class="square yellow"></span>')
                    elif row[0] == 0:
                        attempt_history.append('<span class="square orange"></span>')
            except Exception as e:
                print(f"Error fetching attempt history: {e}")

            # Check for invalid response message
            invalid_response_message = None
            if session.pop('invalid_response', False):
                invalid_response_message = "Invalid response"

            return render_template(
                'display_problem.html',
                question_number=question_number,
                current_year=current_year,
                current_format=current_format,
                current_level=current_level,
                current_classification=current_classification,
                current_tags=current_tags,
                Q_url=Q_url,
                A_url=A_url,
                show_answer=show_answer,
                display_tags=display_tags,
                current_link=current_link,
                points=points,
                problem_index_display=problem_index_display,
                my_id=my_id,
                embed_link=embed_link,
                attempt_history=''.join(attempt_history),
                user_answer=user_answer,
                invalid_response_message=invalid_response_message
            )

    except Exception as e:
        print(f"Error during display problem: {e}")
        return "An error occurred while displaying the problem."

def next_question_url():
    room_id = session.get('room_id', None)
    if room_id:
        url = url_for('arena.arena_problem')
    else:
        print("redirecting to display problem")
        url = url_for('display_problem')
    return url

@app.route('/submit_answer', methods=['POST'])
@login_required
def submit_answer():
    user_answer = request.form.get('user_answer', '').strip()  # Get the user's answer from the form

    # Validate user_answer
    if ';' in user_answer or len(user_answer) > 30:
        session['invalid_response'] = True
        return redirect(url_for('display_problem'))

    session['user_answer'] = user_answer  # Store the user's answer in the session
    session['show_answer'] = True  # Show answer after submission
    url = next_question_url()  # Redirect to the next question
    return redirect(url)

@app.route('/toggle_tags')
@login_required
def toggle_tags():
    session['display_tags'] = not session.get('display_tags', False)
    return redirect(url_for('display_problem'))

@app.route('/decrement_problem')
@login_required
def decrement_problem():
    problem_ids = session.get('problem_ids', [])
    if problem_ids:
        session['problem_index'] = (session.get('problem_index', 0) - 1) % len(problem_ids)
        session['show_answer'] = False
        session['display_tags'] = False
    return redirect(request.referrer or url_for('arena.arena_problem'))

@app.route('/increment_problem')
@login_required
def increment_problem():
    problem_ids = session.get('problem_ids', [])
    if problem_ids:
        session['problem_index'] = (session.get('problem_index', 0) + 1) % len(problem_ids)
        session['show_answer'] = False
        session['display_tags'] = False
    return redirect(request.referrer or url_for('arena.arena_problem'))

@app.route('/award_points/<int:button_factor>')
@login_required
def award_points(button_factor):
    problem_ids = session.get('problem_ids', [])
    problem_index = session.get('problem_index', 0)
    user_answer = session.get('user_answer', '').strip()
    print(f"User answer: {user_answer}")  # Debugging line to check user answer
    # Remove any semicolons from user_answer
    user_answer = user_answer.replace(';', '')

    if problem_ids:
        current_problem_id = problem_ids[problem_index]
        awarded_problems = set(session.get('awarded_problems', []))  # Convert list back to a set

        if current_problem_id not in awarded_problems:
            # Fetch problem details
            try:
                with sql_db.connect() as conn:
                    # Validate table name
                    if not session.get('username').isalnum():
                        raise ValueError("Invalid username")

                    # Create user-specific results table if it doesn't exist
                    table_name = f"results_{session.get('username')}"
                    conn.execute(sqlalchemy.text(f'''
                        CREATE TABLE IF NOT EXISTS {table_name} (
                            id INT AUTO_INCREMENT PRIMARY KEY,
                            problem_id INT NOT NULL,
                            username VARCHAR(255) NOT NULL,
                            result INT NOT NULL,
                            user_answer TEXT,
                            time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    '''))

                    # Check if the user_answer column exists, and add it if missing
                    result = conn.execute(sqlalchemy.text(f'''
                        SHOW COLUMNS FROM {table_name} LIKE 'user_answer'
                    ''')).fetchone()
                    if not result:
                        conn.execute(sqlalchemy.text(f'''
                            ALTER TABLE {table_name} ADD COLUMN user_answer TEXT
                        '''))

                    # Log the result in the results table
                    conn.execute(sqlalchemy.text(f'''
                        INSERT INTO {table_name} (problem_id, username, result, user_answer)
                        VALUES (:problem_id, :username, :result, :user_answer)
                    '''), {
                        'problem_id': current_problem_id,
                        'username': session.get('username'),
                        'result': button_factor,
                        'user_answer': user_answer
                    })

                    # Fetch problem details for scoring
                    problem = conn.execute(sqlalchemy.text('''
                        SELECT question_number, level, format FROM problems WHERE id = :id
                    '''), {'id': current_problem_id}).fetchone()

                    if problem:
                        question_number = problem[0]
                        level = problem[1].lower()
                        format = problem[2].lower()

                        # Compute level factor
                        level_factors = {"school": 1, "chapter": 2, "state": 3, "national": 4}
                        level_factor = level_factors.get(level, 1)

                        # Compute button factor
                        button_factors = {0: 0, 1: 1, 2: 1.5}
                        button_multiplier = button_factors.get(button_factor, 0)

                        target_factor = [8,15,10,18,14,23,16,30]

                        # Calculate points
                        if format == 'target':
                            points_awarded = target_factor[question_number] * level_factor * button_multiplier
                        elif format == 'team':
                            points_awarded = (question_number * 3 + 10) * level_factor * button_multiplier
                        else: 
                            #should be sprint
                            points_awarded = (question_number + 5) * level_factor * button_multiplier

                        # Update session points
                        session['points'] = session.get('points', 0) + points_awarded
                        awarded_problems.add(current_problem_id)
                        session['awarded_problems'] = list(awarded_problems)  # Convert set back to a list for JSON serialization

                        # check if room_id is set in session
                        room_id = session.get('room_id', None)
                        print(f"Room ID: {room_id}")  # Debugging line to check room_id
                        if room_id:
                            print(f"Room ID is set: {room_id}")  # Debugging line to check room_id  
                            # Update the room table with the new points
                            room_table = f"room{room_id}"
                            print(f"Room table: {room_table}")  # Debugging line to check room_table
                            conn.execute(sqlalchemy.text(f'''
                                UPDATE {room_table} SET score = score + :points WHERE username = :username
                            '''), {
                                'points': points_awarded,
                                'username': session.get('username')
                            })
                            conn.commit()
                            print(f"Points awarded to room {room_id}: {points_awarded}")  # Debugging line to check points awarded
                        else:   
                            # Write the new point total to the scoreboard table
                            conn.execute(sqlalchemy.text('''
                                INSERT INTO scoreboard (username, codename, points)
                                VALUES (:username, :codename, :points)
                                ON DUPLICATE KEY UPDATE points = :points
                            '''), {
                                'username': session.get('username'),
                                'codename': session.get('codename', session.get('username')),
                                'points': session['points']
                            })

                        # Write the cumulative points to the leaderboard table
                        conn.execute(sqlalchemy.text('''
                            INSERT INTO leaderboard (username, points)
                            VALUES (:username, :points)
                            ON DUPLICATE KEY UPDATE points = points + :points
                        '''), {
                            'username': session.get('username'),
                            'points': points_awarded
                        })
                        conn.commit()
            except Exception as e:
                print(f"Error updating scoreboard/leaderboard or fetching problem details: {e}")

    # Automatically advance to the next problem
    session['problem_index'] = (problem_index + 1) % len(problem_ids)
    session['show_answer'] = False  # Hide answer
    session['display_tags'] = False  # Hide tags

    url = next_question_url()  # Redirect to the next question
    return redirect(url)

@app.route('/leaderboard')
@login_required
def leaderboard():
    """
    Display the leaderboard with usernames and cumulative point totals.
    """
    try:
        with sql_db.connect() as conn:
            # Fetch leaderboard data sorted by points (descending) and username (alphabetically)
            results = conn.execute(sqlalchemy.text('''
                SELECT username, points
                FROM leaderboard
                ORDER BY points DESC, username ASC
            ''')).fetchall()
    except Exception as e:
        # Log the error details for debugging
        print(f"Error fetching leaderboard: {e}")
        return render_template_string('''
            <!doctype html>
            <title>Error</title>
            <h1>An error occurred while fetching the leaderboard.</h1>
            <p>{{ error_message }}</p>
            <button onclick="window.location.href='/landing'">Exit</button>
        ''', error_message=str(e))

    return render_template_string('''
        <!doctype html>
        <title>Leaderboard</title>
        <link rel="stylesheet" href="{{ url_for('static', filename='arena_setup.css') }}">
        <style>
            body {
                background-color: #f5e6c8; /* Light brown */
                font-family: Arial, sans-serif;
                margin: 0;
                text-align: center;
            }
        </style>
        <div class="banner" style="display: flex; width: 100%; height: 50px; background-color: #333; color: white; align-items: center;">
            <div class="banner-section" style="flex: 1; text-align: center; cursor: pointer;" onclick="window.location.href='/main_landing'" title="Back to Home">Home</div>
            <div class="banner-section" style="flex: 1; text-align: center; cursor: pointer;" onclick="window.location.href='/logout'">Logout</div>
        </div>
        <h1>Practice Leaderboard</h1>
        <button onclick="window.location.href='/contributor_leaderboard'" style="background-color: #6C6F20; color: white; padding: 12px 20px; border: none; border-radius: 5px; font-size: 16px; cursor: pointer; margin-top: 10px; margin-bottom: 10px;">View Contributor Leaderboard</button>
        <p>Points are awarded as follows:</p>
        <ul style="padding-left: 20px; list-style-position: inside;">
            <li><strong>Correct answers:</strong> Earn points based on the problem's difficulty level.</li>
            <li><strong>Figuring out after seeing the answer:</strong> Earn partial points.</li>
        </ul>
        <table border="1" style="border-collapse: collapse; width: 50%; margin: auto;">
            <thead>
                <tr>
                    <th>Username</th>
                    <th>Points</th>
                </tr>
            </thead>
            <tbody>
                {% for row in results %}
                <tr>
                    <td>{{ row[0] }}</td>
                    <td>{{ row[1] }}</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
        <br>
    ''', results=results)

@app.route('/contributor_leaderboard')
@login_required
def contributor_leaderboard():
    """
    Display the contributor leaderboard with usernames and contribution point totals.
    """
    try:
        with sql_db.connect() as conn:
            # Fetch contributor leaderboard data sorted by points (descending) and username (alphabetically)
            results = conn.execute(sqlalchemy.text('''
                SELECT username, points
                FROM contribution_points
                ORDER BY points DESC, username ASC
            ''')).fetchall()
    except Exception as e:
        # Log the error details for debugging
        print(f"Error fetching contributor leaderboard: {e}")
        return render_template_string('''
            <!doctype html>
            <title>Error</title>
            <h1>An error occurred while fetching the contributor leaderboard.</h1>
            <p>{{ error_message }}</p>
            <button onclick="window.location.href='/landing'">Exit</button>
        ''', error_message=str(e))

    return render_template_string('''
        <!doctype html>
        <title>Contributor Leaderboard</title>
        <style>
            body {
                background-color: #e6d4f1; /* Light purple */
                font-family: Arial, sans-serif;
                margin: 0;
            }
        </style>
        <div class="banner" style="display: flex; width: 100%; height: 50px; background-color: #333; color: white; align-items: center;">
            <div class="banner-section" style="flex: 1; text-align: center; cursor: pointer;" onclick="window.location.href='/main_landing'" title="Back to Home">Home</div>
            <div class="banner-section" style="flex: 1; text-align: center; cursor: pointer;" onclick="window.location.href='/logout'">Logout</div>
        </div>
        <div style="text-align: center;">
        <h1>Contributor Leaderboard</h1>
            <button style="background-color: #8e44ad !important; color: white !important; padding: 15px 30px !important; font-size: 18px !important; border: none !important; border-radius: 5px !important; cursor: pointer !important; text-decoration: none !important; display: inline-block !important;" onclick="window.location.href='/leaderboard'">View Leaderboard</button>
        </div>
        <p>Points are awarded as follows:</p>
        <ul>
            <li><strong>3 points</strong> for accepted Classification recommendations</li>
            <li><strong>5 points</strong> for accepted Tag recommendations</li>
            <li><strong>10 points</strong> for accepted Video link recommendations</li>
            <li><strong>Up to 100 points</strong> for accepted website improvement recommendations</li>
        </ul>
        <table border="1" style="border-collapse: collapse; width: 50%; margin: auto;">
            <thead>
                <tr>
                    <th>Username</th>
                    <th>Contribution Points</th>
                </tr>
            </thead>
            <tbody>
                {% for row in results %}
                <tr>
                    <td>{{ row[0] }}</td>
                    <td>{{ row[1] }}</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
        <br>
    ''', results=results)

if __name__ == '__main__':
    app.run(debug=True)

from flask import Flask, send_file, abort, render_template_string, request, redirect, url_for, session, render_template, jsonify
from datetime import timedelta
from io import BytesIO
import os
import sqlalchemy
import random
import yaml # Import yaml
import boto3 # Import boto3 for AWS S3 interaction
from botocore.exceptions import ClientError # Import ClientError for S3 error handling

#from connect_connector import connect_with_connector
from db_aws import init_connection_pool  # Import the database setup function
from user_logs_routes import user_logs_bp
from admin_routes import admin_bp  # Import the Blueprint
from arena import arena_bp, update_in_lobby_flag  # Import the Blueprint
from contributions import contrib_bp
from playlists import playlists_bp  # Import the playlists Blueprint
from utils import login_required, fetch_problems_by_filter, get_all_filters, get_sorted_tag_set, check_answer_match, is_unambiguous_math_answer  # Import from utils
from badges import get_user_stats, evaluate_all_badges, ALL_BADGE_DEFINITIONS
from db_aws import sql_db  # Import the SQLAlchemy engine
import weekly_manager

app = Flask(__name__)

# Load secret key from environment or .env file
def _get_secret_key() -> str:
    key = os.environ.get('FLASK_SECRET_KEY') or os.environ.get('MATHARENA_SECRET_KEY')
    if key:
        return key
    # Attempt to read from local .env if present
    env_path = os.path.join(os.path.dirname(__file__), '.env')
    if os.path.exists(env_path):
        try:
            with open(env_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line.startswith('FLASK_SECRET_KEY='):
                        return line.split('=', 1)[1].strip().strip('"').strip("'")
        except Exception:
            pass
    # Secure fallback if no env variable or .env file is found
    return 'fallback_matharena_dev_secret_key_change_in_production'

app.secret_key = _get_secret_key()

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
app.register_blueprint(playlists_bp)  # Registers /playlists/* and /api/problems/search


def render_register_form(error_message=None, username=""):
    """Helper function to render the registration form with an optional error message."""
    return render_template('register.html', error_message=error_message, username=username)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form['password']
        grade = request.form['grade']
        email = request.form.get('email', '')  # Email is optional
        note = request.form.get('note', '') # Note is optional
        is_13_or_older = request.form.get('is_13_or_older', False)

        if email and not is_13_or_older:
            return render_register_form(
                error_message='If you supply an email address, you must affirm that the email owner is 13 or older.',
                username=username if username is not None else ""
            )

        if not username or not username.isalnum():
            return render_register_form(
                error_message=f'The username "{username}" contains invalid characters or is empty. Please use only letters and numbers.',
                username=username if username is not None else ""
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
    room_id = session.get('room_id')

    # Clean up room membership so rooms don't get stuck when users log out mid-session.
    if room_id:
        try:
            room_table_name = f"room{room_id}"
            with sql_db.connect() as conn:
                conn.execute(sqlalchemy.text(
                    f'DELETE FROM {room_table_name} WHERE username = :username'
                ), {'username': username})
                conn.commit()
                remaining = conn.execute(sqlalchemy.text(
                    f'SELECT COUNT(*) FROM {room_table_name}'
                )).fetchone()[0]
                if remaining == 0:
                    conn.execute(sqlalchemy.text(
                        'UPDATE rooms SET room_state = :state WHERE id = :id'
                    ), {'state': 'empty', 'id': room_id})
                    conn.commit()
        except Exception as e:
            print(f"Error cleaning up room on logout: {e}")

    try:
        update_in_lobby_flag(username, False)
    except Exception as e:
        print(f"Error updating arena table: {e}")
    session.clear()
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
    Serve images (questions or answers) from AWS S3 to avoid CORB issues.
    """
    aws_bucket_name = "math-arena-bucket" # Your S3 bucket name
    s3_client = boto3.client('s3')

    image_name = image_name.replace('cards/','')

    object_key = f"{image_type}/{image_name}"

    print('\n\nobject_key: \n\n', object_key)
    print('\n\nimage_name: \n\n', image_name)

    try:
        # Check if the object exists
        s3_client.head_object(Bucket=aws_bucket_name, Key=object_key)
        # If it exists, download and serve it
        response = s3_client.get_object(Bucket=aws_bucket_name, Key=object_key)
        image_data = response['Body'].read()
        return send_file(BytesIO(image_data), mimetype='image/png')
    except ClientError as e:
        if e.response['Error']['Code'] == '404':
            # If the requested image does not exist, serve the backup image
            backup_object_key = "Questions/noImage.png"
            try:
                s3_client.head_object(Bucket=aws_bucket_name, Key=backup_object_key)
                backup_response = s3_client.get_object(Bucket=aws_bucket_name, Key=backup_object_key)
                backup_image_data = backup_response['Body'].read()
                return send_file(BytesIO(backup_image_data), mimetype='image/png')
            except ClientError as backup_e:
                if backup_e.response['Error']['Code'] == '404':
                    return abort(404) # Return 404 if the backup image also does not exist
                else:
                    print(f"Error accessing backup image from S3: {backup_e}")
                    return "An error occurred while accessing the backup image.", 500
        else:
            print(f"Error accessing image from S3: {e}")
            return "An error occurred while accessing the image.", 500

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
        'shuffle': 'shuffle' in request.form,
        'even_only': 'even_only' in request.form,
        'odd_only': 'odd_only' in request.form
    }

    session['question_count'] = get_question_count(filter_criteria)


    return jsonify({'count': session['question_count']})

@app.route('/main_landing', methods=['GET', 'POST'])
@login_required
def main_landing():
    """Landing page for regular users."""
    filter_criteria = session.get('filter_criteria', None)
    playlist_id = session.get('playlist_id', None)
    playlist_name = session.get('playlist_name', None)
    username = session.get('username', '')
    update_in_lobby_flag(username, False)

    if request.method == 'POST':
        codename = request.form.get('codename', '').strip()
        if codename:
            session['codename'] = codename
        return redirect(url_for('launch_training'))

    # If a playlist is active, determine problem count from session or DB
    if playlist_id and not filter_criteria:
        problem_ids = session.get('problem_ids', [])
        if not problem_ids:
            try:
                with sql_db.connect() as conn:
                    pl_row = conn.execute(sqlalchemy.text('SELECT problem_ids FROM playlists WHERE id = :id'), {'id': playlist_id}).fetchone()
                    if pl_row and pl_row[0]:
                        problem_ids = [int(i) for i in pl_row[0].split(',') if i.strip().isdigit()]
                        session['problem_ids'] = problem_ids
            except Exception as e:
                print(f"Error fetching playlist problem_ids for main_landing: {e}")
                problem_ids = []
        question_count = len(problem_ids)
    else:
        # Fetch the latest filter criteria from the session or database
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
    badge_notification = session.pop('badge_notification', None)
    star_notification = session.pop('star_notification', None)

    return render_template(
        'main_landing.html',
        filter_criteria=filter_criteria,
        playlist_name=playlist_name if (playlist_id and not filter_criteria) else None,
        question_count=question_count,
        filters=filters,
        filter_loaded_message=filter_loaded_message,
        badge_notification=badge_notification,
        star_notification=star_notification
    )

@app.route('/load_filter/<path:username>')
@login_required
def load_filter(username):
    """
    Load filter settings for the specified username and redirect back to the landing page.
    """
    # store username in session as filter_name
    session['filter_name'] = username
    session.pop('playlist_id', None)
    session.pop('playlist_name', None)
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
            'shuffle': 'shuffle' in request.form,
            'even_only': 'even_only' in request.form,
            'odd_only': 'odd_only' in request.form
        }
        session['filter_criteria'] = filter_criteria
        session.pop('playlist_id', None)
        session.pop('playlist_name', None)

        # Save or update filter criteria in the database
        try:
            with sql_db.connect() as conn:
                # Check if even_only column exists and add it if not
                result = conn.execute(sqlalchemy.text("SHOW COLUMNS FROM filters LIKE 'even_only'")).fetchone()
                if not result:
                    conn.execute(sqlalchemy.text("ALTER TABLE filters ADD COLUMN even_only INT DEFAULT 0"))

                # Check if odd_only column exists and add it if not
                result = conn.execute(sqlalchemy.text("SHOW COLUMNS FROM filters LIKE 'odd_only'")).fetchone()
                if not result:
                    conn.execute(sqlalchemy.text("ALTER TABLE filters ADD COLUMN odd_only INT DEFAULT 0"))
                conn.commit()  # Commit schema changes

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
                            start_question = :start_question, end_question = :end_question, shuffle = :shuffle,
                            even_only = :even_only, odd_only = :odd_only
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
                        'shuffle': int(filter_criteria['shuffle']),  # Convert boolean to integer
                        'even_only': int(filter_criteria['even_only']),
                        'odd_only': int(filter_criteria['odd_only'])
                    })
                else:
                    # Insert a new row if no existing row is found
                    conn.execute(sqlalchemy.text('''
                        INSERT INTO filters (username, start_year, end_year, formats, levels, classifications, tags, start_question, end_question, shuffle, even_only, odd_only)
                        VALUES (:username, :start_year, :end_year, :formats, :levels, :classifications, :tags, :start_question, :end_question, :shuffle, :even_only, :odd_only)
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
                        'shuffle': int(filter_criteria['shuffle']),  # Convert boolean to integer
                        'even_only': int(filter_criteria['even_only']),
                        'odd_only': int(filter_criteria['odd_only'])
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
            'shuffle': False,
            'even_only': False,
            'odd_only': False
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
    filter_criteria = session.get('filter_criteria', None)
    playlist_id = session.get('playlist_id', None)

    if playlist_id and not filter_criteria:
        problem_ids = session.get('problem_ids', [])
        if not problem_ids:
            try:
                with sql_db.connect() as conn:
                    pl_row = conn.execute(sqlalchemy.text('SELECT problem_ids FROM playlists WHERE id = :id'), {'id': playlist_id}).fetchone()
                    if pl_row and pl_row[0]:
                        problem_ids = [int(i) for i in pl_row[0].split(',') if i.strip().isdigit()]
            except Exception as e:
                print(f"Error fetching playlist problem_ids for launch_training: {e}")
                problem_ids = []
    elif filter_criteria:
        problem_ids = fetch_problems_by_filter(sql_db, filter_criteria)
        if filter_criteria.get('shuffle', False):
            random.shuffle(problem_ids)
    else:
        return "No filter criteria or playlist found. Please select a filter or playlist first."

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
            Q_name = problem[3].replace('Questions/', '')
            A_name = problem[4].replace('Answers/', '')
            current_year = problem[5]
            current_level = problem[6]
            current_format = problem[7]
            question_number = problem[8]

            # Display the image referenced by question_ref
            Q_url = url_for('serve_image', image_type='Questions', image_name=Q_name)
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

            # Check for auto_correct feedback message
            auto_correct_message = None
            if session.pop('auto_correct', False):
                auto_correct_message = "✓ Correct! Points awarded."

            # Check for incorrect feedback message
            incorrect_message = None
            if session.pop('incorrect', False):
                incorrect_message = "✗ Incorrect."

            # Check for invalid response message
            invalid_response_message = None
            if session.pop('invalid_response', False):
                invalid_response_message = "Invalid response"

            # Check for badge unlock notification
            badge_notification = session.pop('badge_notification', None)

            # Check for star notification
            star_notification = session.pop('star_notification', None)

            allow_self_grade = session.get('allow_self_grade', False)

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
                invalid_response_message=invalid_response_message,
                auto_correct_message=auto_correct_message,
                incorrect_message=incorrect_message,
                allow_self_grade=allow_self_grade,
                badge_notification=badge_notification,
                star_notification=star_notification
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
        return redirect(next_question_url())

    session['user_answer'] = user_answer  # Store the user's answer in the session

    # Check if this answer matches any accepted/true answers in the database
    problem_ids = session.get('problem_ids', [])
    problem_index = session.get('problem_index', 0)
    matched = False
    is_unambiguous = False

    if problem_ids and problem_index < len(problem_ids):
        current_problem_id = problem_ids[problem_index]
        try:
            with sql_db.connect() as conn:
                prob = conn.execute(sqlalchemy.text('''
                    SELECT accepted_answers, true_answer FROM problems WHERE id = :id
                '''), {'id': current_problem_id}).fetchone()
                if prob:
                    accepted_answers_json = prob[0]
                    true_answer = prob[1]
                    if (accepted_answers_json or true_answer) and check_answer_match(user_answer, accepted_answers_json, true_answer):
                        matched = True

                    # Determine if the correct answer is non-ambiguous
                    # Check true_answer or any accepted answer
                    cand_answers = []
                    if true_answer:
                        cand_answers.append(true_answer)
                    if accepted_answers_json:
                        try:
                            parsed = json.loads(accepted_answers_json)
                            if isinstance(parsed, list):
                                cand_answers.extend(parsed)
                            elif isinstance(parsed, str):
                                cand_answers.append(parsed)
                        except Exception:
                            cand_answers.append(accepted_answers_json)

                    if cand_answers:
                        is_unambiguous = any(is_unambiguous_math_answer(c) for c in cand_answers)
        except Exception as e:
            print(f"Error checking answer match: {e}")

    if matched:
        # User is automatically verified correct! Award max points (button_factor = 2) on current problem
        session['auto_correct'] = True
        session['show_answer'] = True
        session['allow_self_grade'] = False
        return award_points(button_factor=2, advance=False)

    if is_unambiguous:
        # Non-ambiguous answer and user did not match: definitely wrong!
        # Do not allow self-grade/points cheating. Record as incorrect (0 points) on current problem.
        session['incorrect'] = True
        session['show_answer'] = True
        session['allow_self_grade'] = False
        return award_points(button_factor=0, advance=False)

    # If ambiguous answer (e.g. 3*sqrt(2), 4+3i, 9pi) or answer not known in DB,
    # show the answer and let the user select among the 3 options.
    session['show_answer'] = True
    session['allow_self_grade'] = True
    url = next_question_url()
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
        session['allow_self_grade'] = False
        session['display_tags'] = False
    return redirect(request.referrer or url_for('arena.arena_problem'))

@app.route('/increment_problem')
@login_required
def increment_problem():
    problem_ids = session.get('problem_ids', [])
    if problem_ids:
        session['problem_index'] = (session.get('problem_index', 0) + 1) % len(problem_ids)
        session['show_answer'] = False
        session['allow_self_grade'] = False
        session['display_tags'] = False
    return redirect(request.referrer or url_for('arena.arena_problem'))

@app.route('/award_points/<int:button_factor>')
@login_required
def award_points_route(button_factor):
    session['allow_self_grade'] = False
    session['show_answer'] = False
    return award_points(button_factor=button_factor, advance=True)

def award_points(button_factor, advance=True):
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
                    username_from_session = session.get('username')
                    if not username_from_session or not username_from_session.isalnum():
                        raise ValueError("Invalid username in session")

                    # Create user-specific results table if it doesn't exist
                    table_name = f"results_{username_from_session}"
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
                            points_awarded = target_factor[question_number - 1] * level_factor * button_multiplier
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

                        # Fetch stats before points awarded to detect any newly unlocked badges
                        uname = session.get('username')
                        stats_before = get_user_stats(conn, uname)
                        badges_before, _, _ = evaluate_all_badges(stats_before)
                        earned_before_ids = {b['id'] for b in badges_before if b['earned']}

                        # Write the cumulative points to the leaderboard table
                        conn.execute(sqlalchemy.text('''
                            INSERT INTO leaderboard (username, points)
                            VALUES (:username, :points)
                            ON DUPLICATE KEY UPDATE points = points + :points
                        '''), {
                            'username': uname,
                            'points': points_awarded
                        })
                        conn.commit()

                        # Update weekly leaderboard and check podium status (compared only against top 3)
                        try:
                            weekly_score, star_earned = weekly_manager.add_weekly_points(conn, uname, points_awarded)
                            if star_earned:
                                star_emoji = '⭐' if star_earned == 'gold' else ('🥈' if star_earned == 'silver' else '🥉')
                                session['star_notification'] = {
                                    'tier': star_earned,
                                    'emoji': star_emoji,
                                    'score': weekly_score
                                }
                        except Exception as we:
                            print(f"Error updating weekly points: {we}")

                        # Evaluate badges after points & answer logging
                        stats_after = get_user_stats(conn, uname)
                        badges_after, _, _ = evaluate_all_badges(stats_after)
                        newly_unlocked = [b for b in badges_after if b['earned'] and b['id'] not in earned_before_ids]

                        if newly_unlocked:
                            # Notify about the most prestigious or first newly earned badge
                            nb = newly_unlocked[0]
                            tier_emoji = '🥇' if nb['tier'] == 'gold' else ('🥈' if nb['tier'] == 'silver' else '🥉')
                            session['badge_notification'] = {
                                'name': nb['name'],
                                'tier': nb['tier'],
                                'desc': nb['desc'],
                                'category': nb['category'],
                                'emoji': tier_emoji
                            }
            except Exception as e:
                print(f"Error updating scoreboard/leaderboard or fetching problem details: {e}")

    if advance:
        # Automatically advance to the next problem
        session['problem_index'] = (problem_index + 1) % len(problem_ids)
        session['show_answer'] = False  # Hide answer
        session['allow_self_grade'] = False
        session['display_tags'] = False  # Hide tags

    url = next_question_url()  # Redirect to the question display
    return redirect(url)

@app.route('/leaderboard')
@login_required
def leaderboard():
    """
    Display the leaderboard with tabs for Weekly and All-Time practice points.
    """
    active_tab = request.args.get('tab', 'weekly')  # default to weekly tab

    try:
        with sql_db.connect() as conn:
            # 1. Ensure weekly cycle is current
            weekly_manager.check_and_apply_weekly_reset(conn)

            # 2. Fetch Weekly Leaderboard
            weekly_db = conn.execute(sqlalchemy.text('''
                SELECT username, points
                FROM weekly_leaderboard
                ORDER BY points DESC, username ASC
            ''')).fetchall()

            # Podium information for top 3 stars
            podium = weekly_manager.get_weekly_podium(conn)
            podium_stars = {}
            for p in podium:
                if p['username'] and p['score'] > 0:
                    if p['rank_pos'] == 1:
                        podium_stars[p['username']] = ('gold', '⭐ Gold Star (1st)')
                    elif p['rank_pos'] == 2:
                        podium_stars[p['username']] = ('silver', '🥈 Silver Star (2nd)')
                    elif p['rank_pos'] == 3:
                        podium_stars[p['username']] = ('bronze', '🥉 Bronze Star (3rd)')

            weekly_results = []
            for idx, row in enumerate(weekly_db):
                uname = row[0]
                pts = float(row[1]) if row[1] is not None else 0.0
                star_info = podium_stars.get(uname)
                weekly_results.append({
                    'rank': idx + 1,
                    'username': uname,
                    'points': pts,
                    'star_tier': star_info[0] if star_info else None,
                    'star_label': star_info[1] if star_info else None
                })

            # Next reset time formatted in Eastern Time
            next_reset = weekly_manager.get_next_cycle_reset()
            next_reset_str = next_reset.strftime("%A, %b %d at %I:%M %p %Z")

            # 3. Fetch All-Time Leaderboard
            all_time_db = conn.execute(sqlalchemy.text('''
                SELECT username, points
                FROM leaderboard
                ORDER BY points DESC, username ASC
            ''')).fetchall()

            all_time_results = []
            for row in all_time_db:
                uname = row[0]
                pts = float(row[1]) if row[1] is not None else 0.0
                user_stats = get_user_stats(conn, uname)
                _, count, tier = evaluate_all_badges(user_stats)
                all_time_results.append({
                    'username': uname,
                    'points': pts,
                    'badge_count': count,
                    'tier': tier
                })
    except Exception as e:
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
            .user-link {
                text-decoration: none;
                font-weight: bold;
                transition: opacity 0.2s;
            }
            .user-link:hover {
                text-decoration: underline;
                opacity: 0.85;
            }
            .tier-bronze {
                color: #b85d19 !important;
            }
            .tier-silver {
                color: #5c6b73 !important;
            }
            .tier-gold {
                color: #c98a00 !important;
            }
            .tier-none {
                color: #333333 !important;
            }
            .badge-count-tag {
                font-size: 13px;
                font-weight: normal;
                margin-left: 6px;
                color: #444;
            }
            .tab-btn {
                padding: 10px 24px;
                font-size: 16px;
                font-weight: bold;
                border: 2px solid #8e44ad;
                cursor: pointer;
                border-radius: 6px;
                margin: 0 5px;
                transition: all 0.2s ease;
            }
            .tab-btn.active {
                background-color: #8e44ad;
                color: white;
            }
            .tab-btn.inactive {
                background-color: white;
                color: #8e44ad;
            }
            .tab-btn.inactive:hover {
                background-color: #f4ecf7;
            }
            .star-badge-gold {
                background: linear-gradient(135deg, #ffd700, #ffb300);
                color: #5a3800;
                padding: 3px 8px;
                border-radius: 12px;
                font-size: 12px;
                font-weight: bold;
                display: inline-block;
                margin-left: 8px;
                box-shadow: 0 1px 3px rgba(0,0,0,0.2);
            }
            .star-badge-silver {
                background: linear-gradient(135deg, #e0e0e0, #b0bec5);
                color: #263238;
                padding: 3px 8px;
                border-radius: 12px;
                font-size: 12px;
                font-weight: bold;
                display: inline-block;
                margin-left: 8px;
                box-shadow: 0 1px 3px rgba(0,0,0,0.2);
            }
            .star-badge-bronze {
                background: linear-gradient(135deg, #ffcc80, #d7ccc8);
                color: #4e342e;
                padding: 3px 8px;
                border-radius: 12px;
                font-size: 12px;
                font-weight: bold;
                display: inline-block;
                margin-left: 8px;
                box-shadow: 0 1px 3px rgba(0,0,0,0.2);
            }
            .countdown-banner {
                background-color: #fff9e6;
                border: 1px solid #ffe082;
                color: #6d4c41;
                padding: 8px 16px;
                border-radius: 6px;
                display: inline-block;
                margin: 10px auto;
                font-size: 14px;
            }
        </style>
        <div class="banner" style="display: flex; width: 100%; height: 50px; background-color: #333; color: white; align-items: center;">
            <div class="banner-section" style="flex: 1; text-align: center; cursor: pointer;" onclick="window.location.href='/main_landing'" title="Back to Home">Home</div>
            <div class="banner-section" style="flex: 1; text-align: center; cursor: pointer;" onclick="window.location.href='/logout'">Logout</div>
        </div>
        <h1>Practice Leaderboard</h1>
        <div style="margin: 15px 0;">
            <button class="tab-btn {{ 'active' if active_tab == 'weekly' else 'inactive' }}" onclick="switchTab('weekly')">📅 Weekly Leaderboard</button>
            <button class="tab-btn {{ 'active' if active_tab == 'all_time' else 'inactive' }}" onclick="switchTab('all_time')">🏆 All-Time Leaderboard</button>
            <button onclick="window.location.href='/contributor_leaderboard'" style="background-color: #6C6F20; color: white; padding: 10px 18px; border: none; border-radius: 6px; font-size: 15px; cursor: pointer; margin-left: 10px;">Contributor Leaderboard</button>
        </div>

        <!-- Weekly Leaderboard Tab -->
        <div id="tab-weekly" style="display: {{ 'block' if active_tab == 'weekly' else 'none' }};">
            <div class="countdown-banner">
                ⏳ <strong>Weekly Cycle:</strong> Resets every <strong>Tuesday at 5:00 PM Eastern</strong>.<br>
                Next reset: <strong>{{ next_reset_str }}</strong>
            </div>
            <p style="font-size: 14px; color: #555;">Live top 3 earn ⭐ Gold, 🥈 Silver, and 🥉 Bronze Star status!</p>
            <table border="1" style="border-collapse: collapse; width: 60%; margin: auto;">
                <thead>
                    <tr style="background-color: #eae1d0;">
                        <th style="width: 10%;">Rank</th>
                        <th style="width: 60%;">Username</th>
                        <th style="width: 30%;">Weekly Points</th>
                    </tr>
                </thead>
                <tbody>
                    {% if weekly_results %}
                        {% for row in weekly_results %}
                        <tr>
                            <td>{{ row.rank }}</td>
                            <td style="text-align: left; padding-left: 20px;">
                                <a href="/profile/{{ row.username }}" class="user-link tier-none">
                                    {{ row.username }}
                                </a>
                                {% if row.star_tier == 'gold' %}
                                    <span class="star-badge-gold">⭐ Gold Star (1st)</span>
                                {% elif row.star_tier == 'silver' %}
                                    <span class="star-badge-silver">🥈 Silver Star (2nd)</span>
                                {% elif row.star_tier == 'bronze' %}
                                    <span class="star-badge-bronze">🥉 Bronze Star (3rd)</span>
                                {% endif %}
                            </td>
                            <td><strong>{{ row.points }}</strong></td>
                        </tr>
                        {% endfor %}
                    {% else %}
                        <tr>
                            <td colspan="3" style="padding: 20px; color: #777;">No points earned yet in this week's cycle. Be the first to solve a problem and take 1st place!</td>
                        </tr>
                    {% endif %}
                </tbody>
            </table>
        </div>

        <!-- All-Time Leaderboard Tab -->
        <div id="tab-all-time" style="display: {{ 'block' if active_tab == 'all_time' else 'none' }};">
            <p>Cumulative points across all practice sessions.</p>
            <p style="font-size: 14px; color: #555;">💡 Click on any username to view their profile and earned badges!</p>
            <table border="1" style="border-collapse: collapse; width: 60%; margin: auto;">
                <thead>
                    <tr style="background-color: #eae1d0;">
                        <th style="width: 65%;">Username</th>
                        <th style="width: 35%;">Cumulative Points</th>
                    </tr>
                </thead>
                <tbody>
                    {% for row in all_time_results %}
                    <tr>
                        <td style="text-align: left; padding-left: 20px;">
                            <a href="/profile/{{ row.username }}" class="user-link tier-{{ row.tier if row.tier else 'none' }}">
                                {% if row.tier == 'bronze' %}🥉
                                {% elif row.tier == 'silver' %}🥈
                                {% elif row.tier == 'gold' %}🥇
                                {% else %}👤{% endif %}
                                {{ row.username }}
                            </a>
                            <span class="badge-count-tag">({{ row.badge_count }} badge{{ 's' if row.badge_count != 1 else '' }})</span>
                        </td>
                        <td>{{ row.points }}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>

        <br>
        <script>
            function switchTab(tabName) {
                const url = new URL(window.location.href);
                url.searchParams.set('tab', tabName);
                window.history.replaceState({}, '', url);

                document.getElementById('tab-weekly').style.display = tabName === 'weekly' ? 'block' : 'none';
                document.getElementById('tab-all-time').style.display = tabName === 'all_time' ? 'block' : 'none';

                const buttons = document.querySelectorAll('.tab-btn');
                buttons[0].className = 'tab-btn ' + (tabName === 'weekly' ? 'active' : 'inactive');
                buttons[1].className = 'tab-btn ' + (tabName === 'all_time' ? 'active' : 'inactive');
            }
        </script>
    ''',
    active_tab=active_tab,
    weekly_results=weekly_results,
    next_reset_str=next_reset_str,
    all_time_results=all_time_results)


@app.route('/profile')
@app.route('/profile/<username>')
@login_required
def view_profile(username=None):
    """Display user profile page with cumulative points and full badge achievements across categories."""
    if not username:
        username = session.get('username')

    try:
        with sql_db.connect() as conn:
            user_stats = get_user_stats(conn, username)
            points = user_stats.get('practice_points', 0.0)
            contrib_points = user_stats.get('contribution_points', 0)
            badges, earned_count, highest_tier = evaluate_all_badges(user_stats)
    except Exception as e:
        print(f"Error fetching profile points for {username}: {e}")
        points = 0.0
        contrib_points = 0
        user_stats = {}
        badges = []
        earned_count = 0
        highest_tier = None

    return render_template(
        'profile.html',
        user=username,
        points=points,
        contrib_points=contrib_points,
        user_stats=user_stats,
        badges=badges,
        earned_count=earned_count,
        total_count=len(badges),
        highest_tier=highest_tier
    )

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
                    <td><a href="/profile/{{ row[0] }}" style="color: #6a1b9a; text-decoration: none; font-weight: bold;">👤 {{ row[0] }}</a></td>
                    <td>{{ row[1] }}</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
        <br>
    ''', results=results)

if __name__ == '__main__':
    app.run(debug=True)

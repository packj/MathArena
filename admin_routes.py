from flask import Blueprint, render_template_string, render_template, request, redirect, url_for, session
import sqlalchemy
from utils import login_required, award_contribution_points, fetch_problems_by_filter
admin_bp = Blueprint('admin', __name__)
from db_aws import sql_db

@admin_bp.route('/show_live_scores', methods=['GET'])
@login_required
def show_live_scores():
    """Display the live scores."""
    #if session.get('username') != 'admin':
    #    return redirect(url_for('login'))

    room_scores = []
    try:
        with sql_db.connect() as conn:
            # look in the rooms table to find the ids of all rooms that are busy (room_state == 'busy')
            busy_rooms = conn.execute(sqlalchemy.text('''
                SELECT id FROM rooms WHERE room_state = 'busy'
            ''')).fetchall()
            busy_room_ids = [row[0] for row in busy_rooms]

            # build the table names for the busy rooms
            room_tables = [f'room{room_id}' for room_id in busy_room_ids]

            # build color list for the busy rooms
            from arena import id_to_color_and_name
       
            room_scores = []
            for table in room_tables:
                # get the scores for all users in the room
                scores = conn.execute(sqlalchemy.text(f'''
                    SELECT username, score FROM {table}
                ''')).fetchall()
                # pass the scores to the template
                scores = [{'username': row[0], 'score': row[1]} for row in scores]
                # sort scores by score in descending order
                scores.sort(key=lambda x: x['score'], reverse=True)
                # store the scores for this table along with the table name
                rm_id = table.replace('room', '')
                room_color, rm_name = id_to_color_and_name(rm_id)
                room_scores.append({
                    'table_name': table,
                    'heading': rm_name + ' Room',
                    'color': room_color,
                    'scores': scores
                })

    except Exception as e:
        print(f"Error fetching scores: {e}")
        return "An error occurred while fetching scores."


    return render_template('show_live_scores.html', room_scores=room_scores)



def convert_image(image_path):
    """
    Placeholder function to convert images.
    """
    import numpy as np
    from PIL import Image
    import io
    import boto3 # Import boto3 for AWS S3 interaction

    # AWS S3 bucket details
    aws_bucket_name = "math-arena-bucket" # Your S3 bucket name

    # Initialize S3 client
    s3_client = boto3.client('s3')

    A_name = image_path.replace('Answers/', '')
    object_key = f"Answers/{A_name}"

    try:
        # Read the image from S3
        response = s3_client.get_object(Bucket=aws_bucket_name, Key=object_key)
        img_data = response['Body'].read()

        # Open the image using PIL
        image = Image.open(io.BytesIO(img_data))

        # Convert the image to a NumPy array
        img_array = np.array(image)

        # Check to see if the first pixel is more red or more blue
        img1 = img_array[1, 1, :].reshape(1, 1, 3)
        if img1[0][0][0] > img1[0][0][2]:
            # if the first pixel is more red, swap the red and blue channels
            img_array = img_array[:, :, [2, 1, 0]]
            #convert the numpy array back to a PIL image
            image2 = Image.fromarray(img_array)
            # convert PIL image image2 to a byte array
            img_byte_arr = io.BytesIO()
            image2.save(img_byte_arr, format='PNG')
            img_byte_arr = img_byte_arr.getvalue()

            # Upload the modified image back to S3
            s3_client.put_object(Bucket=aws_bucket_name, Key=object_key, Body=img_byte_arr, ContentType='image/png')
            print("Image uploaded successfully to S3.")
    except Exception as e:
        print(f"Error processing image with S3: {e}")
        raise # Re-raise the exception to indicate failure



@admin_bp.route('/convert_images')
@login_required
def convert_images():
    """Admin page to convert images."""
    if session.get('username') != 'admin':
        return redirect(url_for('login'))
    # Get the list of problems from the database
    try:
        with sql_db.connect() as conn:
            print("Fetching problems...")
            problems = conn.execute(sqlalchemy.text('''
                SELECT id, answer_ref FROM problems
            ''')).fetchall()
            problems = [{'id': row[0], 'answer_ref': row[1]} for row in problems]
            print(len(problems))
            for problem in problems[:850]:
                # Fetch the answer image from the database
                print(problem)
                answer_ref = problem['answer_ref']
                if answer_ref:
                    # Assuming you have a function to convert the image
                    convert_image(answer_ref)  # Placeholder for actual conversion logic
                        
    except Exception as e:
        print(f"Error fetching problems: {e}")
        return "An error occurred while fetching problems."

    return render_template_string('''
        <!doctype html>
        <title>Convert Images</title>
        <h1>Convert Images</h1>
        <p>This page will be used to convert images.</p>
        <button onclick="window.location.href='/admin/admin_landing'">Back to Admin Landing</button>
    ''')

@admin_bp.route('/review_tag_recommendations', methods=['GET', 'POST'])
@login_required
def review_tag_recommendations():
    if session.get('username') != 'admin':  # Restrict access to admin
        return redirect(url_for('login'))

    try:
        with sql_db.connect() as conn:
            if request.method == 'POST':
                action = request.form.get('action')
                selected_ids = request.form.getlist('recommendation_id')

                if action in ['approve', 'reject'] and selected_ids:
                    for recommendation_id in selected_ids:
                        recommendation = conn.execute(sqlalchemy.text('''
                            SELECT problem_id, tags, username FROM tag_recommendations WHERE id = :id
                        '''), {'id': recommendation_id}).fetchone()

                        if recommendation and action == 'approve':
                            problem_id, new_tags, username = recommendation
                            # Fetch existing tags
                            existing_tags = conn.execute(sqlalchemy.text('''
                                SELECT tags FROM problems WHERE id = :problem_id
                            '''), {'problem_id': problem_id}).fetchone()[0]

                            # Merge tags
                            updated_tags = set()
                            if existing_tags and existing_tags != '[]':
                                updated_tags.update(existing_tags.strip('[]').replace('`', '').split(','))
                            updated_tags.update(new_tags.strip('[]').replace('`', '').split(','))
                            updated_tags = [f"`{tag.strip()}`" for tag in updated_tags if tag.strip()]
                            conn.execute(sqlalchemy.text('''
                                UPDATE problems SET tags = :tags WHERE id = :problem_id
                            '''), {'tags': f"[{','.join(updated_tags)}]", 'problem_id': problem_id})

                            # Award points to the contributor
                            award_contribution_points(sql_db, username, 5)  # Pass sql_db explicitly

                        # Delete the recommendation
                        conn.execute(sqlalchemy.text('''
                            DELETE FROM tag_recommendations WHERE id = :id
                        '''), {'id': recommendation_id})
                    conn.commit()

            # Fetch all tag recommendations
            recommendations = conn.execute(sqlalchemy.text('''
                SELECT tr.id, tr.problem_id, tr.username, tr.tags, p.tags AS existing_tags, p.question_ref
                FROM tag_recommendations tr
                LEFT JOIN problems p ON tr.problem_id = p.id
            ''')).fetchall()
    except Exception as e:
        print(f"Error reviewing tag recommendations: {e}")
        return "An error occurred while reviewing tag recommendations."

    return render_template_string('''
        <!doctype html>
        <title>Review Tag Recommendations</title>
        <h1>Review Tag Recommendations</h1>
        <form method="post">
            <button type="button" onclick="selectAll()">Select All</button>
            <button type="submit" name="action" value="approve">Approve Selected</button>
            <button type="submit" name="action" value="reject">Reject Selected</button>
            <table border="1" style="border-collapse: collapse; width: 100%;">
                <thead>
                    <tr>
                        <th>Select</th>
                        <th style="width: 45%;">Problem Image</th>
                        <th>Problem ID</th>
                        <th>Username</th>
                        <th>Existing Tags</th>
                        <th>Recommended Tags</th>
                    </tr>
                </thead>
                <tbody>
                    {% for rec in recommendations %}
                    <tr>
                        <td><input type="checkbox" name="recommendation_id" value="{{ rec[0] }}"></td>
                        <td>
                            <div style="width: 100%; aspect-ratio: 16/9; overflow: hidden; display: flex; justify-content: center; align-items: center;">
                                <img src="{{ url_for('serve_image', image_type='Questions', image_name=rec[5].replace('Questions/', '')) }}" 
                                     alt="Problem Image" 
                                     style="width: 100%; height: auto;">
                            </div>
                        </td>
                        <td>{{ rec[1] }}</td>
                        <td>{{ rec[2] }}</td>
                        <td>{{ rec[4] }}</td>
                        <td>{{ rec[3] }}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </form>
        <script>
            function selectAll() {
                document.querySelectorAll('input[type="checkbox"]').forEach(cb => cb.checked = true);
            }
        </script>
        <br>
        <button onclick="window.location.href='/landing'">Back to Admin Landing</button>
    ''', recommendations=recommendations)

@admin_bp.route('/review_classification_recommendations', methods=['GET', 'POST'])
@login_required
def review_classification_recommendations():
    if session.get('username') != 'admin':  # Restrict access to admin
        return redirect(url_for('login'))

    try:
        with sql_db.connect() as conn:
            if request.method == 'POST':
                action = request.form.get('action')
                selected_ids = request.form.getlist('recommendation_id')

                if action in ['approve', 'reject'] and selected_ids:
                    for recommendation_id in selected_ids:
                        recommendation = conn.execute(sqlalchemy.text('''
                            SELECT problem_id, classification, username FROM recommendations WHERE id = :id
                        '''), {'id': recommendation_id}).fetchone()

                        if recommendation and action == 'approve':
                            problem_id, new_classification, username = recommendation
                            conn.execute(sqlalchemy.text('''
                                UPDATE problems SET classification = :classification WHERE id = :problem_id
                            '''), {'classification': new_classification, 'problem_id': problem_id})

                            # Award points to the contributor
                            award_contribution_points(sql_db, username, 3)  # Pass sql_db explicitly

                        # Delete the recommendation
                        conn.execute(sqlalchemy.text('''
                            DELETE FROM recommendations WHERE id = :id
                        '''), {'id': recommendation_id})
                    conn.commit()

            # Fetch all classification recommendations
            recommendations = conn.execute(sqlalchemy.text('''
                SELECT r.id, r.problem_id, r.username, r.classification, p.classification AS existing_classification, p.question_ref
                FROM recommendations r
                LEFT JOIN problems p ON r.problem_id = p.id
            ''')).fetchall()
    except Exception as e:
        print(f"Error reviewing classification recommendations: {e}")
        return "An error occurred while reviewing classification recommendations."

    return render_template_string('''
        <!doctype html>
        <title>Review Classification Recommendations</title>
        <h1>Review Classification Recommendations</h1>
        <form method="post">
            <button type="button" onclick="selectAll()">Select All</button>
            <button type="submit" name="action" value="approve">Approve Selected</button>
            <button type="submit" name="action" value="reject">Reject Selected</button>
            <table border="1" style="border-collapse: collapse; width: 100%;">
                <thead>
                    <tr>
                        <th>Select</th>
                        <th style="width: 45%;">Problem Image</th>
                        <th>Problem ID</th>
                        <th>Username</th>
                        <th>Existing Classification</th>
                        <th>Recommended Classification</th>
                    </tr>
                </thead>
                <tbody>
                    {% for rec in recommendations %}
                    <tr>
                        <td><input type="checkbox" name="recommendation_id" value="{{ rec[0] }}"></td>
                        <td>
                            <div style="width: 100%; aspect-ratio: 16/9; overflow: hidden; display: flex; justify-content: center; align-items: center;">
                                <img src="{{ url_for('serve_image', image_type='Questions', image_name=rec[5].replace('Questions/', '')) }}" 
                                     alt="Problem Image" 
                                     style="width: 100%; height: auto;">
                            </div>
                        </td>
                        <td>{{ rec[1] }}</td>
                        <td>{{ rec[2] }}</td>
                        <td>{{ rec[4] }}</td>
                        <td>{{ rec[3] }}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </form>
        <script>
            function selectAll() {
                document.querySelectorAll('input[type="checkbox"]').forEach(cb => cb.checked = true);
            }
        </script>
        <br>
        <button onclick="window.location.href='/landing'">Back to Admin Landing</button>
    ''', recommendations=recommendations)

@admin_bp.route('/review_videos', methods=['GET', 'POST'])
@login_required
def review_videos():
    if session.get('username') != 'admin':  # Restrict access to admin
        return redirect(url_for('login'))

    try:
        with sql_db.connect() as conn:
            if request.method == 'POST':
                action = request.form.get('action')
                selected_ids = request.form.getlist('suggested_link_id')

                if action in ['approve', 'reject'] and selected_ids:
                    for link_id in selected_ids:
                        link = conn.execute(sqlalchemy.text('''
                            SELECT problem_id, suggested_link, username FROM suggested_links WHERE id = :id
                        '''), {'id': link_id}).fetchone()

                        if link and action == 'approve':
                            problem_id, suggested_link, username = link
                            conn.execute(sqlalchemy.text('''
                                UPDATE problems SET link = :link WHERE id = :problem_id
                            '''), {'link': suggested_link, 'problem_id': problem_id})

                            # Award points to the contributor
                            award_contribution_points(sql_db, username, 10)

                        # Delete the suggestion
                        conn.execute(sqlalchemy.text('''
                            DELETE FROM suggested_links WHERE id = :id
                        '''), {'id': link_id})
                    conn.commit()

            # Fetch all suggested links
            suggestions = conn.execute(sqlalchemy.text('''
                SELECT sl.id, sl.problem_id, sl.username, sl.suggested_link, p.link AS existing_link, p.question_ref
                FROM suggested_links sl
                LEFT JOIN problems p ON sl.problem_id = p.id
            ''')).fetchall()
    except Exception as e:
        print(f"Error reviewing video suggestions: {e}")
        return "An error occurred while reviewing video suggestions."

    return render_template_string('''
        <!doctype html>
        <title>Review Video Suggestions</title>
        <h1>Review Video Suggestions</h1>
        <form method="post">
            <button type="button" onclick="selectAll()">Select All</button>
            <button type="submit" name="action" value="approve">Approve Selected</button>
            <button type="submit" name="action" value="reject">Reject Selected</button>
            <table border="1" style="border-collapse: collapse; width: 100%;">
                <thead>
                    <tr>
                        <th>Select</th>
                        <th style="width: 45%;">Problem Image</th>
                        <th>Problem ID</th>
                        <th>Username</th>
                        <th>Existing Link</th>
                        <th>Suggested Link</th>
                    </tr>
                </thead>
                <tbody>
                    {% for suggestion in suggestions %}
                    <tr>
                        <td><input type="checkbox" name="suggested_link_id" value="{{ suggestion[0] }}"></td>
                        <td>
                            <div style="width: 100%; aspect-ratio: 16/9; overflow: hidden; display: flex; justify-content: center; align-items: center;">
                                <img src="{{ url_for('serve_image', image_type='Questions', image_name=suggestion[5].replace('Questions/', '')) }}" 
                                     alt="Problem Image" 
                                     style="width: 100%; height: auto;">
                            </div>
                        </td>
                        <td>{{ suggestion[1] }}</td>
                        <td>{{ suggestion[2] }}</td>
                        <td>{{ suggestion[4] }}</td>
                        <td>{{ suggestion[3] }}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </form>
        <script>
            function selectAll() {
                document.querySelectorAll('input[type="checkbox"]').forEach(cb => cb.checked = true);
            }
        </script>
        <br>
        <button onclick="window.location.href='/landing'">Back to Admin Landing</button>
    ''', suggestions=suggestions)

@admin_bp.route('/review_suggestions', methods=['GET', 'POST'])
@login_required
def review_suggestions():
    """
    Admin page to review user suggestions.
    """
    if session.get('username') != 'admin':  # Restrict access to admin
        return redirect(url_for('login'))

    try:
        with sql_db.connect() as conn:
            if request.method == 'POST':
                action = request.form.get('action')
                selected_ids = request.form.getlist('suggestion_id')
                #alternate_scores = request.form.getlist('alternate_score')
                
                if action in ['accept', 'reject'] and selected_ids:
                    for suggestion_id in selected_ids:
                        # Find the index of the suggestion_id in the form data
                        index = request.form.getlist('suggestion_id').index(suggestion_id)
                        suggestion = conn.execute(sqlalchemy.text('''
                            SELECT username, suggestion_text FROM suggestions WHERE id = :id
                        '''), {'id': suggestion_id}).fetchone()

                        if suggestion and action == 'accept':
                            username, suggestion_text = suggestion
                            alternate_score_name = f'alternate_score_{suggestion_id}'
                            alternate_score = request.form.get(alternate_score_name)
                            score = int(alternate_score) if alternate_score and alternate_score.isdigit() else 100
                            # Create the accepted_suggestions table if it doesn't exist
                            conn.execute(sqlalchemy.text('''
                               CREATE TABLE IF NOT EXISTS accepted_suggestions (
                                    id INT AUTO_INCREMENT PRIMARY KEY,
                                    username VARCHAR(255) NOT NULL,
                                    suggestion_text TEXT NOT NULL,
                                    accepted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                                )
                            '''))

                            # Insert the suggestion into the accepted_suggestions table
                            conn.execute(sqlalchemy.text('''
                                INSERT INTO accepted_suggestions (username, suggestion_text)
                                VALUES (:username, :suggestion_text)
                            '''), {
                                'username': username,
                                'suggestion_text': suggestion_text
                            })

                            # Award the specified contributor points to the user
                            award_contribution_points(sql_db, username, score)

                        # Delete the suggestion from the suggestions table
                        conn.execute(sqlalchemy.text('''
                            DELETE FROM suggestions WHERE id = :id
                        '''), {'id': suggestion_id})

                    conn.commit()

            # Fetch all suggestions
            suggestions = conn.execute(sqlalchemy.text('''
                SELECT id, username, suggestion_text, created_at FROM suggestions
            ''')).fetchall()

    except Exception as e:
        return "An error occurred while reviewing suggestions."

    return render_template_string('''
        <!doctype html>
        <title>Review Suggestions</title>
        <h1>Review Suggestions</h1>
        <form method="post">
            <button type="button" onclick="selectAll()">Select All</button>
            <button type="submit" name="action" value="accept">Accept Selected</button>
            <button type="submit" name="action" value="reject">Reject Selected</button>
            <table border="1" style="border-collapse: collapse; width: 100%;">
                <thead>
                    <tr>
                        <th>Select</th>
                        <th>Username</th>
                        <th>Suggestion</th>
                        <th>Submitted At</th>
                        <th>Alternate Score</th>
                    </tr>
                </thead>
                <tbody>
                    {% for suggestion in suggestions %}
                    <tr>
                        <td><input type="checkbox" name="suggestion_id" value="{{ suggestion[0] }}"></td>
                        <td>{{ suggestion[1] }}</td>
                        <td>{{ suggestion[2] }}</td>
                        <td>{{ suggestion[3] }}</td>
                        <td><input type="number" name="alternate_score_{{ suggestion[0] }}" placeholder="100" style="width: 60px;"></td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </form>
        <script>
            function selectAll() {
                document.querySelectorAll('input[type="checkbox"]').forEach(cb => cb.checked = true);
            }
        </script>
        <br>
        <button onclick="window.location.href='/landing'">Back to Admin Landing</button>
    ''', suggestions=suggestions)

@admin_bp.route('/review_problem_reports', methods=['GET', 'POST'])
@login_required
def review_problem_reports():
    if session.get('username') != 'admin':  # Restrict access to admin
        return redirect(url_for('login'))

    try:
        with sql_db.connect() as conn:
            if request.method == 'POST':
                action = request.form.get('action')
                selected_ids = request.form.getlist('report_id')

                if action in ['resolve', 'reject'] and selected_ids:
                    for report_id in selected_ids:
                        # Fetch the report details
                        report = conn.execute(sqlalchemy.text('''
                            SELECT username, problem_id, report_text, date
                            FROM problem_reports
                            WHERE id = :id
                        '''), {'id': report_id}).fetchone()

                        if report:
                            username, problem_id, report_text, report_date = report

                            if action == 'resolve':
                                # Create resolved_reports table if it doesn't exist
                                conn.execute(sqlalchemy.text('''
                                    CREATE TABLE IF NOT EXISTS resolved_reports (
                                        id INT AUTO_INCREMENT PRIMARY KEY,
                                        username VARCHAR(255) NOT NULL,
                                        problem_id INT NOT NULL,
                                        report_text TEXT NOT NULL,
                                        report_date TIMESTAMP NOT NULL,
                                        resolution_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                                    )
                                '''))

                                # Insert the report into resolved_reports
                                conn.execute(sqlalchemy.text('''
                                    INSERT INTO resolved_reports (username, problem_id, report_text, report_date)
                                    VALUES (:username, :problem_id, :report_text, :report_date)
                                '''), {
                                    'username': username,
                                    'problem_id': problem_id,
                                    'report_text': report_text,
                                    'report_date': report_date
                                })

                            elif action == 'reject':
                                # Create rejected_reports table if it doesn't exist
                                conn.execute(sqlalchemy.text('''
                                    CREATE TABLE IF NOT EXISTS rejected_reports (
                                        id INT AUTO_INCREMENT PRIMARY KEY,
                                        username VARCHAR(255) NOT NULL,
                                        problem_id INT NOT NULL,
                                        report_text TEXT NOT NULL,
                                        report_date TIMESTAMP NOT NULL,
                                        rejection_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                                    )
                                '''))

                                # Insert the report into rejected_reports
                                conn.execute(sqlalchemy.text('''
                                    INSERT INTO rejected_reports (username, problem_id, report_text, report_date)
                                    VALUES (:username, :problem_id, :report_text, :report_date)
                                '''), {
                                    'username': username,
                                    'problem_id': problem_id,
                                    'report_text': report_text,
                                    'report_date': report_date
                                })

                            # Delete the report from problem_reports
                            conn.execute(sqlalchemy.text('''
                                DELETE FROM problem_reports WHERE id = :id
                            '''), {'id': report_id})

                    conn.commit()

            # Fetch all problem reports
            reports = conn.execute(sqlalchemy.text('''
                SELECT id, username, problem_id, report_text, date
                FROM problem_reports
            ''')).fetchall()

    except Exception as e:
        print(f"Error reviewing problem reports: {e}")
        return "An error occurred while reviewing problem reports."

    return render_template_string('''
        <!doctype html>
        <title>Review Problem Reports</title>
        <h1>Review Problem Reports</h1>
        <form method="post">
            <button type="button" onclick="selectAll()">Select All</button>
            <button type="button" onclick="deselectAll()">Deselect All</button>
            <button type="submit" name="action" value="resolve">Resolve Selected</button>
            <button type="submit" name="action" value="reject">Reject Selected</button>
            <table border="1" style="border-collapse: collapse; width: 100%;">
                <thead>
                    <tr>
                        <th>Select</th>
                        <th>Username</th>
                        <th>Problem ID</th>
                        <th>Report Text</th>
                        <th>Report Date</th>
                    </tr>
                </thead>
                <tbody>
                    {% for report in reports %}
                    <tr>
                        <td><input type="checkbox" name="report_id" value="{{ report[0] }}"></td>
                        <td>{{ report[1] }}</td>
                        <td>{{ report[2] }}</td>
                        <td>{{ report[3] }}</td>
                        <td>{{ report[4] }}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </form>
        <script>
            function selectAll() {
                document.querySelectorAll('input[type="checkbox"]').forEach(cb => cb.checked = true);
            }
            function deselectAll() {
                document.querySelectorAll('input[type="checkbox"]').forEach(cb => cb.checked = false);
            }
        </script>
        <br>
        <button onclick="window.location.href='/landing'">Back to Admin Landing</button>
    ''', reports=reports)

@admin_bp.route('/list_users', methods=['GET'])
@login_required
def list_users():
    """
    List all users from the Cloud SQL database.
    """
    if session.get('username') != 'admin':  # Restrict access to admin
        return redirect(url_for('login'))

    users = []
    try:
        with sql_db.connect() as conn:
            # Fetch all users from the database
            myusers = conn.execute(sqlalchemy.text('''
                SELECT id, username, first_name, last_name, grade, school, email, approved
                FROM users
            ''')).fetchall()

            # Convert the results into a list of dicts
            for row in myusers:
                users.append({
                    "id": row[0],
                    "username": row[1],
                    "first_name": row[2],
                    "last_name": row[3],
                    "grade": row[4],
                    "school": row[5],
                    "email": row[6],
                    "approved": row[7]
                })
    except Exception as e:
        print(f"Error fetching users: {e}")
        return "An error occurred while fetching the users."

    return render_template_string('''
        <!doctype html>
        <title>List of Users</title>
        <h1>All Users</h1>
        <table border="1" style="border-collapse: collapse; width: 100%;">
            <thead>
                <tr>
                    <th>ID</th>
                    <th>Username</th>
                    <th>First Name</th>
                    <th>Last Name</th>
                    <th>Grade</th>
                    <th>School</th>
                    <th>Email</th>
                    <th>Approved</th>
                </tr>
            </thead>
            <tbody>
                {% for user in users %}
                <tr>
                    <td>{{ user['id'] }}</td>
                    <td>{{ user['username'] }}</td>
                    <td>{{ user['first_name'] }}</td>
                    <td>{{ user['last_name'] }}</td>
                    <td>{{ user['grade'] }}</td>
                    <td>{{ user['school'] }}</td>
                    <td>{{ user['email'] }}</td>
                    <td>{{ 'Yes' if user['approved'] else 'No' }}</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
        <br>
        <button onclick="window.location.href='/landing'">Back to Admin Landing</button>
    ''', users=users)

@admin_bp.route('/approve', methods=['GET', 'POST'])
@login_required
def approve_users():
    """
    Admin page to approve or disapprove user accounts.
    """
    if session.get('username') != 'admin':  # Restrict access to admin
        return redirect(url_for('login'))

    try:
        with sql_db.connect() as conn:
            if request.method == 'POST':
                user_id = request.form.get('user_id')
                action = request.form.get('action')

                if not user_id or not action:
                    return 'Invalid request. Missing user_id or action.'

                if action == 'approve':
                    # Approve the user by updating the database
                    conn.execute(sqlalchemy.text('''
                        UPDATE users SET approved = 1 WHERE id = :user_id
                    '''), {'user_id': user_id})
                elif action == 'disapprove':
                    # Disapprove the user by deleting the row
                    conn.execute(sqlalchemy.text('''
                        DELETE FROM users WHERE id = :user_id
                    '''), {'user_id': user_id})
                else:
                    return 'Invalid action.'

                conn.commit()

            # Fetch all pending users
            pending_users = conn.execute(sqlalchemy.text('''
                SELECT id, username, first_name, last_name, grade, school, email, note
                FROM users
                WHERE approved = 0
            ''')).fetchall()
    except Exception as e:
        print(f"Error during user approval/disapproval: {e}")
        return 'An error occurred while approving or disapproving users.'

    return render_template_string('''
        <!doctype html>
        <title>Approve Users</title>
        <h1>Pending User Approvals</h1>
        <form method="post">
            <table border="1" style="border-collapse: collapse; width: 100%;">
                <thead>
                    <tr>
                        <th>Username</th>
                        <th>First Name</th>
                        <th>Last Name</th>
                        <th>Grade</th>
                        <th>School</th>
                        <th>Email</th>
                        <th>Note</th>
                        <th>Actions</th>
                    </tr>
                </thead>
                <tbody>
                    {% for user in pending_users %}
                    <tr>
                        <td>{{ user[1] }}</td>
                        <td>{{ user[2] }}</td>
                        <td>{{ user[3] }}</td>
                        <td>{{ user[4] }}</td>
                        <td>{{ user[5] }}</td>
                        <td>{{ user[6] }}</td>
                        <td>{{ user[7] }}</td>
                        <td>
                            <form method="post" style="display:inline;">
                                <input type="hidden" name="user_id" value="{{ user[0] }}">
                                <button type="submit" name="action" value="approve">Approve</button>
                            </form>
                            <form method="post" style="display:inline;">
                                <input type="hidden" name="user_id" value="{{ user[0] }}">
                                <button type="submit" name="action" value="disapprove">Disapprove</button>
                            </form>
                        </td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </form>
        <br>
        <button onclick="window.location.href='/landing'">Back to Admin Landing</button>
    ''', pending_users=pending_users)

@admin_bp.route('/list_tags', methods=['GET', 'POST'])
@login_required
def list_tags():
    if session.get('username') != 'admin':  # Restrict access to admin
        return redirect(url_for('login'))

    tags = []
    try:
        with sql_db.connect() as conn:
            if request.method == 'POST':
                # Handle tag replacement
                old_tag = request.form.get('old_tag', '').strip()
                new_tag = request.form.get('new_tag', '').strip()

                # Validate that both old_tag and new_tag are not empty
                if not old_tag or not new_tag:
                    print("Error: Old tag or New tag is empty.")
                    return "Error: Both Old tag and New tag must be provided."

                # Debugging: Print the query and parameters
                query = '''
                    UPDATE problems
                    SET tags = REPLACE(tags, :old_tag, :new_tag)
                    WHERE tags LIKE :like_old_tag
                '''
                params = {
                    'old_tag': old_tag,
                    'new_tag': new_tag,
                    'like_old_tag': f"%{old_tag}%"
                }

                # Execute the query
                conn.execute(sqlalchemy.text(query), params)
                conn.commit()

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
    except Exception as e:
        print(f"Error fetching or updating tags: {e}")
        return "An error occurred while fetching or updating tags."

    return render_template_string('''
        <!doctype html>
        <title>List Tags</title>
        <h1>List of Tags</h1>
        <table border="1" style="border-collapse: collapse; width: 100%;">
            <thead>
                <tr>
                    <th>Tag</th>
                    <th>Replace With</th>
                    <th>Action</th>
                </tr>
            </thead>
            <tbody>
                {% for tag in tags %}
                <tr>
                    <form method="post">
                        <td>{{ tag }}</td>
                        <td>
                            <input type="text" name="new_tag" placeholder="New tag for '{{ tag }}'">
                            <input type="hidden" name="old_tag" value="{{ tag }}">
                        </td>
                        <td>
                            <button type="submit">Replace</button>
                        </td>
                    </form>
                </tr>
                {% endfor %}
            </tbody>
        </table>
        <br>
        <button onclick="window.location.href='/landing'">Back to Admin Landing</button>
    ''', tags=tags)

@admin_bp.route('/scoreboard', methods=['GET'])
@login_required
def scoreboard():
    """
    Display the scoreboard with codenames and point totals.
    """
    if session.get('username') != 'admin':  # Restrict access to admin
        return redirect(url_for('login'))

    try:
        with sql_db.connect() as conn:
            # Fetch scoreboard data sorted by points (descending) and codename (alphabetically)
            results = conn.execute(sqlalchemy.text('''
                SELECT codename, points
                FROM scoreboard
                ORDER BY points DESC, codename ASC
            ''')).fetchall()
    except Exception as e:
        print(f"Error fetching scoreboard: {e}")
        return "An error occurred while fetching the scoreboard."

    return render_template_string('''
        <!doctype html>
        <title>Scoreboard</title>
        <meta http-equiv="refresh" content="120"> <!-- Refresh every 120 seconds -->
        <style>
            body {
                background-color: #d4e9d4; /* Light forest green */
                font-family: Arial, sans-serif;
            }
        </style>
        <h1>Scoreboard</h1>
        <form method="post" action="/admin/reset_scores">
            <button type="submit" style="background-color: red; color: white; padding: 10px; border: none; border-radius: 5px; cursor: pointer;">
                Reset All Scores
            </button>
        </form>
        <button onclick="window.location.reload()" style="background-color: blue; color: white; padding: 10px; border: none; border-radius: 5px; cursor: pointer; margin-top: 10px;">
            Refresh Page
        </button>
        <table border="1" style="border-collapse: collapse; width: 50%; margin: auto;">
            <thead>
                <tr>
                    <th>Codename</th>
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
        <div style="text-align: center;">
            <button onclick="window.location.href='/landing'">Back to Admin Landing</button>
        </div>
    ''', results=results)

@admin_bp.route('/reset_scores', methods=['POST'])
@login_required
def reset_scores():
    """
    Reset all scores on the scoreboard to zero. Admin only.
    """
    if session.get('username') != 'admin':  # Restrict access to admin
        return redirect(url_for('login'))

    try:
        with sql_db.connect() as conn:
            # Reset all scores to zero
            conn.execute(sqlalchemy.text('''
                UPDATE scoreboard SET points = 0
            '''))
            conn.commit()
    except Exception as e:
        print(f"Error resetting scores: {e}")
        return "An error occurred while resetting scores."

    return redirect(url_for('admin.scoreboard'))

@admin_bp.route('/list_filters', methods=['GET', 'POST'])
@login_required
def list_filters():
    if session.get('username') != 'admin':  # Restrict access to admin
        return redirect(url_for('login'))

    filters = []
    try:
        with sql_db.connect() as conn:
            if request.method == 'POST':
                # Handle filter deletion
                filter_name = request.form.get('filter_name')
                if filter_name:
                    conn.execute(sqlalchemy.text('''
                        DELETE FROM filters WHERE username = :username
                    '''), {'username': filter_name})
                    conn.commit()

            # Fetch all filters with usernames starting with "_"
            results = conn.execute(sqlalchemy.text('''
                SELECT username, start_year, end_year, formats, levels, classifications, tags, start_question, end_question, shuffle
                FROM filters
                WHERE username LIKE '\\_%'
            ''')).fetchall()

            for row in results:
                # Prepare filter criteria for each filter
                filter_criteria = {
                    'start_year': row[1],
                    'end_year': row[2],
                    'formats': row[3].split(','),
                    'levels': row[4].split(','),
                    'classifications': row[5].split(',') if row[5] else [],
                    'tags': row[6].split(',') if row[6] else [],
                    'start_question': row[7],
                    'end_question': row[8],
                    'shuffle': bool(row[9])
                }

                # Use fetch_problems_by_filter to count matching questions
                problem_ids = fetch_problems_by_filter(sql_db, filter_criteria)  # Pass sql_db explicitly
                question_count = len(problem_ids)

                filters.append({
                    'username': row[0],
                    'question_count': question_count
                })
    except Exception as e:
        print(f"Error fetching filters: {e}")
        return "An error occurred while fetching the filters."

    return render_template_string('''
        <!doctype html>
        <title>List Filters</title>
        <h1>List of Filters</h1>
        <table border="1" style="border-collapse: collapse; width: 100%;">
            <thead>
                <tr>
                    <th>Filter Name</th>
                    <th>Number of Questions</th>
                    <th>Actions</th>
                </tr>
            </thead>
            <tbody>
                {% for filter in filters %}
                <tr>
                    <td>{{ filter['username'] }}</td>
                    <td>{{ filter['question_count'] }}</td>
                    <td>
                        <form method="post" style="display:inline;">
                            <input type="hidden" name="filter_name" value="{{ filter['username'] }}">
                            <button type="submit">Delete</button>
                        </form>
                    </td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
        <br>
        <button onclick="window.location.href='/landing'">Back to Admin Landing</button>
    ''', filters=filters)

@admin_bp.route('/verify_answers', methods=['GET', 'POST'])
@login_required
def verify_answers():
    """
    Verify answers by checking results_* tables for entries with result = 2
    and corresponding problems without a true_answer.
    """
    if session.get('username') != 'admin':  # Restrict access to admin
        return redirect(url_for('login'))

    if request.method == 'POST':
        action = request.form.get('action')
        selected_rows = request.form.getlist('selected_rows')
        print("action:", action)
        print("selected_rows:", selected_rows)

        # Retrieve collected_data from the session
        collected_data = session.get('collected_data', [])
        try:
            with sql_db.connect() as conn:
                # Ensure the user_fidelity table exists
                conn.execute(sqlalchemy.text('''
                    CREATE TABLE IF NOT EXISTS user_fidelity (
                        username VARCHAR(255) PRIMARY KEY,
                        accept_count INT DEFAULT 0,
                        reject_count INT DEFAULT 0
                    )
                '''))

                for row in selected_rows:
                    problem_id, username = row.split('|')
                    problem_id = int(problem_id.strip())
                    if action == 'approve':
                        # Approve: Update the true_answer column
                        print(f"Approving answer for problem_id: {problem_id}, username: {username}")
                        
                        # Use the user_answer from collected_data
                        user_answer = next(
                            (data['user_answer'] for data in collected_data 
                             if data['problem_id'] == problem_id and data['username'] == username), 
                            None
                        )
                        
                        print(f"User answer: {user_answer}")
                        if user_answer:
                            conn.execute(sqlalchemy.text('''
                                UPDATE problems SET true_answer = :true_answer
                                WHERE id = :problem_id
                            '''), {'true_answer': user_answer, 'problem_id': problem_id})
                            print(f"Updated true_answer for problem_id: {problem_id} to {user_answer}")
                        
                        # Increment accept_count in user_fidelity
                        conn.execute(sqlalchemy.text('''
                            INSERT INTO user_fidelity (username, accept_count, reject_count)
                            VALUES (:username, 1, 0)
                            ON DUPLICATE KEY UPDATE accept_count = accept_count + 1
                        '''), {'username': username})
                            
                    elif action == 'reject':
                        # Reject: Clear the user_answer from the results_<user> table
                        conn.execute(sqlalchemy.text('''UPDATE results_:username
                            SET user_answer = NULL
                            WHERE problem_id = :problem_id
                        '''.replace(':username', username)), {'problem_id': problem_id})
                        
                        # Increment reject_count in user_fidelity
                        conn.execute(sqlalchemy.text('''
                            INSERT INTO user_fidelity (username, accept_count, reject_count)
                            VALUES (:username, 0, 1)
                            ON DUPLICATE KEY UPDATE reject_count = reject_count + 1
                        '''), {'username': username})
                    else:
                        print(f"Unknown action: {action}")
                conn.commit()
        except Exception as e:
            print(f"Error processing verify answers: {e}")
            return "An error occurred while processing the selected answers."
        return redirect(url_for('admin.verify_answers'))

    # Handle GET request
    collected_data = []
    try:
        with sql_db.connect() as conn:
            # Ensure the `true_answer` column exists in the `problems` table
            try:
                conn.execute(sqlalchemy.text('''
                    ALTER TABLE problems ADD COLUMN true_answer TEXT
                '''))
            except sqlalchemy.exc.OperationalError as e:
                # Ignore error if the column already exists
                if "Duplicate column name" not in str(e):
                    raise

            # Fetch all tables with names starting with "results_"
            result_tables = conn.execute(sqlalchemy.text('''
                SELECT table_name
                FROM information_schema.tables
                WHERE table_name LIKE 'results_%'
            ''')).fetchall()

            # Collect data from each table
            for table in result_tables:
                table_name = table[0]

                # Check if the `user_answer` column exists in the table
                columns = conn.execute(sqlalchemy.text(f'''
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_name = :table_name
                '''), {'table_name': table_name}).fetchall()

                column_names = [col[0] for col in columns]
                if 'user_answer' not in column_names:
                    continue

                # Fetch entries with result = 2 and missing true_answer
                entries = conn.execute(sqlalchemy.text(f'''
                    SELECT r.problem_id, r.user_answer, r.username, p.answer_ref
                    FROM {table_name} r
                    LEFT JOIN problems p ON r.problem_id = p.id
                    WHERE r.result = 2 AND (p.true_answer IS NULL OR p.true_answer = '')
                ''')).fetchall()

                for entry in entries:
                    if entry[1] is not None and entry[1].strip():  # Exclude entries where user_answer is None or empty
                        collected_data.append({
                            'problem_id': entry[0],
                            'user_answer': entry[1],
                            'username': entry[2],
                            'answer_ref': entry[3]
                        })

            # Limit to the first 20 rows
            collected_data = collected_data[:80]

            # Store collected_data in the session
            session['collected_data'] = collected_data

    except Exception as e:
        print(f"Error verifying answers: {e}")
        return "An error occurred while verifying answers."

    # Render the collected data in a table
    return render_template_string('''
        <!doctype html>
        <title>Verify Answers</title>
        <h1>Verify Answers</h1>
        <form method="post">
            <div>
                <button type="button" onclick="selectAll()">Select All</button>
                <button type="button" onclick="deselectAll()">Deselect All</button>
                <button type="button" onclick="selectByUser()">Select All from User</button>
                <button type="submit" name="action" value="approve">Approve Selected</button>
                <button type="submit" name="action" value="reject">Reject Selected</button>
            </div>
            <table border="1" style="border-collapse: collapse; width: 100%;">
                <thead>
                    <tr>
                        <th>Select</th>
                        <th>Problem ID</th>
                        <th style="width: 16.67%;">Answer Image</th>
                        <th>User Answer</th>
                        <th>Username</th>
                    </tr>
                </thead>
                <tbody>
                    {% for row in collected_data %}
                    <tr>
                        <td><input type="checkbox" name="selected_rows" value="{{ row['problem_id'] }}|{{ row['username'] }}"></td>
                        <td>{{ row['problem_id'] }}</td>
                        <td>
                            <div style="width: 100%; aspect-ratio: 16/9; overflow: hidden; display: flex; justify-content: center; align-items: center;">
                                <img src="{{ url_for('serve_image', image_type='Answers', image_name=row['answer_ref'].replace('Answers/', '')) }}" 
                                     alt="Answer Image" 
                                     style="width: 100%; height: auto;">
                            </div>
                        </td>
                        <td>{{ row['user_answer'] }}</td>
                        <td>{{ row['username'] }}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </form>
        <script>
            function selectAll() {
                document.querySelectorAll('input[type="checkbox"]').forEach(cb => cb.checked = true);
            }
            function deselectAll() {
                document.querySelectorAll('input[type="checkbox"]').forEach(cb => cb.checked = false);
            }
            function selectByUser() {
                const username = prompt("Enter the username to select all their answers:");
                if (username) {
                    document.querySelectorAll('input[type="checkbox"]').forEach(cb => {
                        if (cb.value.includes(`|${username}`)) cb.checked = true;
                    });
                }
            }
        </script>
        <br>
        <button onclick="window.location.href='/admin/admin_landing'">Back to Admin Landing</button>
    ''', collected_data=collected_data)

@admin_bp.route('/admin_landing', methods=['GET', 'POST'])
@login_required
def admin_landing():
    """Landing page for admin users."""
    if session.get('username') != 'admin':  # Restrict access to admin
        return redirect(url_for('login'))

    try:
        with sql_db.connect() as conn:
            pending_users_count = conn.execute(sqlalchemy.text('''
                SELECT COUNT(*) FROM users WHERE approved = 0
            ''')).scalar()

            tag_recommendations_count = conn.execute(sqlalchemy.text('''
                SELECT COUNT(*) FROM tag_recommendations
            ''')).scalar()

            classification_recommendations_count = conn.execute(sqlalchemy.text('''
                SELECT COUNT(*) FROM recommendations
            ''')).scalar()

            problem_reports_count = conn.execute(sqlalchemy.text('''
                SELECT COUNT(*) FROM problem_reports
            ''')).scalar()

            video_suggestions_count = conn.execute(sqlalchemy.text('''
                SELECT COUNT(*) FROM suggested_links
            ''')).scalar()

            suggestions_count = conn.execute(sqlalchemy.text('''
                SELECT COUNT(*) FROM suggestions
            ''')).scalar()
    except Exception as e:
        print(f"Error fetching counts for admin actions: {e}")
        pending_users_count = tag_recommendations_count = classification_recommendations_count = 0
        problem_reports_count = video_suggestions_count = suggestions_count = 0

    return render_template(
        'admin_landing.html',
        pending_users_count=pending_users_count,
        tag_recommendations_count=tag_recommendations_count,
        classification_recommendations_count=classification_recommendations_count,
        problem_reports_count=problem_reports_count,
        video_suggestions_count=video_suggestions_count,
        suggestions_count=suggestions_count
    )

@admin_bp.route('/clear_rooms', methods=['GET'])
@login_required
def clear_rooms():
    """
    Clear all rooms by removing all users and resetting the room_state to 'empty'.
    """
    if session.get('username') != 'admin':
        return redirect(url_for('login'))

    try:
        for room_id in range(1, 6):
            # Clear all users from the room table
            with sql_db.connect() as conn:
                room_table_name = f"room{room_id}"
                conn.execute(sqlalchemy.text(f'''
                    DELETE FROM {room_table_name}
                '''))
                conn.commit()
    except Exception as e:
        print(f"Error clearing rooms: {e}")
        return "An error occurred while clearing the rooms."

    # set room_state to 'empty' in the rooms table
    try:
        with sql_db.connect() as conn:
            conn.execute(sqlalchemy.text('''
                UPDATE rooms SET room_state = 'empty'
            '''))
            conn.commit()
    except Exception as e:
        print(f"Error resetting room states: {e}")
        return "An error occurred while resetting the room states."

    return redirect(url_for('admin.admin_landing'))


@admin_bp.route('/temp_passwords')
@login_required
def temp_passwords():
    """Display temporary passwords."""
    if session.get('username') != 'admin':
        return redirect(url_for('login'))

    try:
        with sql_db.connect() as conn:
            # Fetch usernames and temporary passwords from the users table
            temp_passwords = conn.execute(sqlalchemy.text('''
                SELECT username, temp_password FROM users WHERE temp_password IS NOT NULL
            ''')).fetchall()
    except Exception as e:
        print(f"Error fetching temporary passwords: {e}")
        return "An error occurred while fetching temporary passwords."

    return render_template('temp_passwords.html', temp_passwords=temp_passwords)

@admin_bp.route('/grant_points', methods=['POST'])
@login_required
def grant_points():
    """Grant points to a specified user."""
    if session.get('username') != 'admin':
        return redirect(url_for('login'))

    username = request.form.get('username')
    points_str = request.form.get('points')

    if not username or not points_str:
        return "Missing username or points.", 400

    try:
        points = int(points_str)
        if points <= 0:
            return "Points must be a positive number.", 400
    except ValueError:
        return "Invalid points value. Must be a number.", 400

    try:
        with sql_db.connect() as conn:
            # Check if the user exists in the users table
            user_exists = conn.execute(sqlalchemy.text('''
                SELECT 1 FROM users WHERE username = :username
            '''), {'username': username}).fetchone()

            if not user_exists:
                return f"User '{username}' not found.", 404

            # Update points in the scoreboard table
            # If the user is not in the scoreboard, insert them with the given points
            conn.execute(sqlalchemy.text('''
                INSERT INTO scoreboard (username, codename, points)
                VALUES (:username, :username, :points)
                ON DUPLICATE KEY UPDATE points = points + :points
            '''), {'username': username, 'points': points})
            conn.commit()
    except Exception as e:
        print(f"Error granting points: {e}")
        return "An error occurred while granting points.", 500

    return redirect(url_for('admin.admin_landing'))

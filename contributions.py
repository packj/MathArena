from flask import Blueprint, render_template_string, request, redirect, url_for, session, render_template
import sqlalchemy
from utils import login_required, get_sorted_tag_set
from db import sql_db

contrib_bp = Blueprint('contrib', __name__)  # Create a Blueprint 

@contrib_bp.route('/recommend_classification/<int:problem_id>', methods=['GET', 'POST'])
@login_required
def recommend_classification(problem_id):
    classifications = ['Arithmetic', 'Statistics', 'Number Theory', 'Algebra', 'Probability and Counting', 'Geometry', 'None']
    if request.method == 'POST':
        selected_classification = request.form.get('classification')
        if selected_classification:
            try:
                with sql_db.connect() as conn:
                    conn.execute(sqlalchemy.text('''
                        INSERT INTO recommendations (problem_id, username, classification)
                        VALUES (:problem_id, :username, :classification)
                    '''), {
                        'problem_id': problem_id,
                        'username': session.get('username'),
                        'classification': selected_classification
                    })
                    conn.commit()
                return redirect(url_for('display_problem'))
            except Exception as e:
                print(f"Error saving recommendation: {e}")
                return "An error occurred while saving the recommendation."
    return render_template('recommend_classification.html', classifications=classifications)

@contrib_bp.route('/recommend_tags/<int:problem_id>', methods=['GET', 'POST'])
@login_required
def recommend_tags(problem_id):
    from main import sql_db
    try:
        with sql_db.connect() as conn:
            # Fetch the problem details for the current ID
            problem_query = '''
                SELECT question_ref FROM problems WHERE id = :id
            '''
            problem = conn.execute(sqlalchemy.text(problem_query), {'id': problem_id}).fetchone()

            if not problem:
                return "Problem not found."

            Q_name = problem[0].replace('cards/', '')
            Q_url = url_for('serve_image', image_type='cards', image_name=Q_name)

            tags = get_sorted_tag_set(sql_db)

            if request.method == 'POST':
                # Collect selected tags and new tags
                selected_tags = request.form.getlist('tags')
                new_tags = request.form.get('new_tags', '').strip()

                # Add new tags to the selected tags list
                if new_tags:
                    selected_tags.extend(tag.strip() for tag in new_tags.split(',') if tag.strip())

                # Convert tags to a comma-separated string
                tag_string = ','.join(selected_tags)

                # Insert the recommendation into the database
                conn.execute(sqlalchemy.text('''
                    INSERT INTO tag_recommendations (problem_id, username, tags)
                    VALUES (:problem_id, :username, :tags)
                '''), {
                    'problem_id': problem_id,
                    'username': session.get('username'),
                    'tags': tag_string
                })
                conn.commit()

                return redirect(url_for('display_problem'))

    except Exception as e:
        print(f"Error during recommend tags: {e}")
        return "An error occurred while recommending tags."

    return render_template('recommend_tags.html', Q_url=Q_url, tags=tags)

@contrib_bp.route('/suggestions', methods=['GET', 'POST'])
@login_required
def suggestions():
    """
    Handle user suggestions for improving the website.
    """
    if request.method == 'POST':
        suggestion_text = request.form.get('suggestion_text', '').strip()
        if suggestion_text:
            try:
                with sql_db.connect() as conn:
                    # Create the suggestions table if it doesn't exist
                    conn.execute(sqlalchemy.text('''
                        CREATE TABLE IF NOT EXISTS suggestions (
                            id INT AUTO_INCREMENT PRIMARY KEY,
                            username VARCHAR(255) NOT NULL,
                            suggestion_text TEXT NOT NULL,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    '''))

                    # Insert the suggestion into the table
                    conn.execute(sqlalchemy.text('''
                        INSERT INTO suggestions (username, suggestion_text)
                        VALUES (:username, :suggestion_text)
                    '''), {
                        'username': session.get('username'),
                        'suggestion_text': suggestion_text
                    })

                    conn.commit()
                return redirect(url_for('landing'))
            except Exception as e:
                print(f"Error saving suggestion: {e}")
                return "An error occurred while submitting your suggestion."

    return render_template_string('''
        <!doctype html>
        <title>Suggestions</title>
        <h1>Suggestions</h1>
        <form method="post">
            <label for="suggestion_text">Your Suggestion:</label><br>
            <textarea id="suggestion_text" name="suggestion_text" rows="10" cols="50" required></textarea><br><br>
            <input type="submit" value="Submit Suggestion">
        </form>
        <br>
        <button onclick="window.location.href='/landing'">Cancel</button>
    ''')


@contrib_bp.route('/recommend_link/<int:problem_id>', methods=['GET', 'POST'])
@login_required
def recommend_link(problem_id):
    if request.method == 'POST':
        suggested_link = request.form.get('suggested_link', '').strip()
        if suggested_link:
            try:
                with sql_db.connect() as conn:
                    # Create the suggested_links table if it doesn't exist
                    conn.execute(sqlalchemy.text('''
                        CREATE TABLE IF NOT EXISTS suggested_links (
                            id INT AUTO_INCREMENT PRIMARY KEY,
                            problem_id INT NOT NULL,
                            username VARCHAR(255) NOT NULL,
                            suggested_link TEXT NOT NULL,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    '''))

                    # Insert the suggested link into the table
                    conn.execute(sqlalchemy.text('''
                        INSERT INTO suggested_links (problem_id, username, suggested_link)
                        VALUES (:problem_id, :username, :suggested_link)
                    '''), {
                        'problem_id': problem_id,
                        'username': session.get('username'),
                        'suggested_link': suggested_link
                    })

                    conn.commit()
                return redirect(url_for('display_problem'))
            except Exception as e:
                print(f"Error saving suggested link: {e}")
                return "An error occurred while submitting the suggested link."

    return render_template_string('''
        <!doctype html>
        <title>Recommend Link</title>
        <h1>Recommend Link</h1>
        <form method="post">
            <label for="suggested_link">Enter the link:</label><br>
            <input type="url" id="suggested_link" name="suggested_link" required style="width: 100%;"><br><br>
            <input type="submit" value="Submit Recommendation">
        </form>
        <br>
        <button onclick="window.location.href='/display_problem'">Cancel</button>
    ''')


@contrib_bp.route('/report_problem/<int:problem_id>', methods=['GET', 'POST'])
@login_required
def report_problem(problem_id):
    if request.method == 'POST':
        report_text = request.form.get('report_text', '').strip()
        if report_text:
            try:
                with sql_db.connect() as conn:
                    # Create the problem_reports table if it doesn't exist
                    conn.execute(sqlalchemy.text('''
                        CREATE TABLE IF NOT EXISTS problem_reports (
                            id INT AUTO_INCREMENT PRIMARY KEY,
                            username VARCHAR(255) NOT NULL,
                            problem_id INT NOT NULL,
                            report_text TEXT NOT NULL,
                            date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    '''))

                    # Insert the report into the table
                    conn.execute(sqlalchemy.text('''
                        INSERT INTO problem_reports (username, problem_id, report_text)
                        VALUES (:username, :problem_id, :report_text)
                    '''), {
                        'username': session.get('username'),
                        'problem_id': problem_id,
                        'report_text': report_text
                    })

                    conn.commit()
                return redirect(url_for('display_problem'))
            except Exception as e:
                print(f"Error saving problem report: {e}")
                return "An error occurred while submitting the problem report."

    return render_template_string('''
        <!doctype html>
        <title>Report Problem</title>
        <h1>Report Problem</h1>
        <form method="post">
            <label for="report_text">Describe the issue:</label><br>
            <textarea id="report_text" name="report_text" rows="10" cols="50" required></textarea><br><br>
            <input type="submit" value="Submit Report">
        </form>
        <br>
        <button onclick="window.location.href='/display_problem'">Cancel</button>
    ''')

from flask import Blueprint, render_template, session, redirect, url_for
import sqlalchemy
from utils import login_required # Assuming login_required might be needed later, or for consistency
from db_aws import sql_db

user_logs_bp = Blueprint('user_logs', __name__)

@user_logs_bp.route('/my_log')
@login_required
def my_log():
    try:
        table_name = f"results_{session.get('username')}"
        with sql_db.connect() as conn:
            results = conn.execute(sqlalchemy.text(f'''
                SELECT p.year, p.level, p.format, p.question_number, r.result, r.user_answer, r.time, p.id
                FROM {table_name} r
                JOIN problems p ON r.problem_id = p.id
                WHERE r.time > '2025-04-11 00:00:00'
            ''')).fetchall()
        
        transformed_results = []
        for row in results:
            year, level, format_val, q_num, result_val, user_ans, time_val, problem_id = row
            if result_val == 0:
                result_str = "wrong"
            elif result_val == 1:
                result_str = "second attempt right"
            elif result_val == 2:
                result_str = "right"
            else:
                result_str = str(result_val) # fallback for unexpected values
            transformed_results.append((year, level, format_val, q_num, result_str, user_ans, time_val, problem_id))
            
        return render_template('my_log.html', results=transformed_results)
    except Exception as e:
        print(f"Error fetching results: {e}")
        return 'An error occurred while fetching the results.'


@user_logs_bp.route('/username_bird987_log')
def username_bird987_log():
    try:
        with sql_db.connect() as conn:
            results = conn.execute(sqlalchemy.text('''
                SELECT p.year, p.level, p.format, p.question_number, r.result, r.user_answer, r.time, p.id
                FROM results_bird987 r
                JOIN problems p ON r.problem_id = p.id
                WHERE r.time > '2025-04-11 00:00:00'
            ''')).fetchall()
        
        transformed_results = []
        for row in results:
            year, level, format_val, q_num, result_val, user_ans, time_val, problem_id = row
            if result_val == 0:
                result_str = "wrong"
            elif result_val == 1:
                result_str = "second attempt right"
            elif result_val == 2:
                result_str = "right"
            else:
                result_str = str(result_val) # fallback for unexpected values
            transformed_results.append((year, level, format_val, q_num, result_str, user_ans, time_val, problem_id))
            
        return render_template('username_bird987_log.html', results=transformed_results)
    except Exception as e:
        print(f"Error fetching results for username_bird987_log: {e}")
        return 'An error occurred while fetching the results.'

@user_logs_bp.route('/display_one_problem/<int:problem_id>')
@login_required
def display_one_problem(problem_id):
    session['problem_ids'] = [problem_id]
    session['problem_index'] = 0
    session['show_answer'] = False
    session['display_tags'] = False

    return redirect(url_for('display_problem'))

import os
from flask import Flask, render_template, request, redirect, url_for
from werkzeug.utils import secure_filename
from datetime import datetime
import sqlite3
import atexit
import shutil

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'your_secret_key_change_in_production')

UPLOAD_FOLDER = 'static/uploads/'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'pdf'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Database will be in the same directory as app.py
DATABASE = os.path.join(os.path.dirname(__file__), 'tabit.db')

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_db():
    """Get database connection"""
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initialize database with tables"""
    conn = get_db()
    conn.execute('''
        CREATE TABLE IF NOT EXISTS groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            members TEXT NOT NULL,
            photo TEXT,
            created_at TEXT NOT NULL
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id INTEGER NOT NULL,
            payer TEXT NOT NULL,
            description TEXT NOT NULL,
            amount REAL NOT NULL,
            shared_with TEXT NOT NULL,
            bill TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (group_id) REFERENCES groups (id)
        )
    ''')
    conn.commit()
    conn.close()

# Initialize database on startup
init_db()

# --- 1. Route for GROUP CREATION & DISPLAY ---
@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        group_name = request.form['group_name']
        members = request.form['members'].split(',')
        members = [m.strip() for m in members if m.strip()]
        
        if not members:
            return redirect(url_for('index'))
        
        file = request.files.get('group_photo')
        filename = None
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        
        # Save to database
        conn = get_db()
        conn.execute(
            'INSERT INTO groups (name, members, photo, created_at) VALUES (?, ?, ?, ?)',
            (group_name, ','.join(members), filename, datetime.now().strftime('%Y-%m-%d %H:%M'))
        )
        conn.commit()
        conn.close()
        
        return redirect(url_for('index'))
    
    # Get all groups from database
    conn = get_db()
    groups_raw = conn.execute('SELECT * FROM groups ORDER BY created_at DESC').fetchall()
    conn.close()
    
    # Convert to list of dicts
    groups = []
    for g in groups_raw:
        groups.append({
            'id': g['id'],
            'name': g['name'],
            'members': g['members'].split(','),
            'photo': g['photo'],
            'created_at': g['created_at']
        })
    
    return render_template('index.html', groups=groups)

# --- 2. Route for ADDING EXPENSES ---
@app.route('/expenses/<int:group_id>', methods=['GET', 'POST'])
def expenses(group_id):
    conn = get_db()
    group_raw = conn.execute('SELECT * FROM groups WHERE id = ?', (group_id,)).fetchone()
    
    if not group_raw:
        conn.close()
        return redirect(url_for('index'))
    
    # Convert group to dict
    group = {
        'id': group_raw['id'],
        'name': group_raw['name'],
        'members': group_raw['members'].split(','),
        'photo': group_raw['photo']
    }
    
    if request.method == 'POST':
        payers = request.form.getlist('payer')
        description = request.form['description']
        amount = float(request.form['amount'])
        shared_with = request.form.getlist('shared_with')
        
        if not payers or not shared_with:
            conn.close()
            return redirect(url_for('expenses', group_id=group_id))
        
        proof = request.files.get('bill_upload')
        bill_filename = None
        if proof and allowed_file(proof.filename):
            bill_filename = secure_filename(proof.filename)
            proof.save(os.path.join(app.config['UPLOAD_FOLDER'], bill_filename))
        
        # Save expense to database
        conn.execute(
            'INSERT INTO expenses (group_id, payer, description, amount, shared_with, bill, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)',
            (group_id, ','.join(payers), description, amount, ','.join(shared_with), bill_filename, datetime.now().strftime('%Y-%m-%d %H:%M'))
        )
        conn.commit()
        conn.close()
        
        return redirect(url_for('expenses', group_id=group_id))
    
    # Get expenses for this group
    expenses_raw = conn.execute('SELECT * FROM expenses WHERE group_id = ? ORDER BY created_at DESC', (group_id,)).fetchall()
    conn.close()
    
    # Convert expenses to list of dicts
    expenses_list = []
    for e in expenses_raw:
        expenses_list.append({
            'payer': e['payer'].split(','),
            'desc': e['description'],
            'amount': e['amount'],
            'shared_with': e['shared_with'].split(','),
            'bill': e['bill']
        })
    
    group['expenses'] = expenses_list
    
    return render_template('expenses.html', group=group)

# --- 3. Route for SPLIT VIEW ---
@app.route('/transactions/<int:group_id>')
def transactions(group_id):
    conn = get_db()
    group_raw = conn.execute('SELECT * FROM groups WHERE id = ?', (group_id,)).fetchone()
    
    if not group_raw:
        conn.close()
        return redirect(url_for('index'))
    
    # Convert group to dict
    members = group_raw['members'].split(',')
    group = {
        'id': group_raw['id'],
        'name': group_raw['name'],
        'members': members
    }
    
    # Get expenses
    expenses_raw = conn.execute('SELECT * FROM expenses WHERE group_id = ?', (group_id,)).fetchall()
    conn.close()
    
    # Calculate balances
    balances = {m: 0 for m in members}
    
    for e in expenses_raw:
        total_amount = e['amount']
        payers = e['payer'].split(',')
        amount_per_payer = total_amount / len(payers) if payers else total_amount
        shared_with = e['shared_with'].split(',')
        amount_per_person = total_amount / len(shared_with) if shared_with else 0
        
        for m in shared_with:
            balances[m] -= amount_per_person
        for p in payers:
            balances[p] += amount_per_payer
    
    # Check if all dues are settled
    all_settled = all(abs(balance) < 0.01 for balance in balances.values())
    
    return render_template('transactions.html', group=group, balances=balances, all_settled=all_settled)

# --- 4. DELETE GROUP ROUTE ---
@app.route('/delete_group/<int:group_id>', methods=['POST'])
def delete_group(group_id):
    deleter_name = request.form.get('deleter_name', '').strip()
    SECRET_CODE = '1986'
    
    conn = get_db()
    group_raw = conn.execute('SELECT * FROM groups WHERE id = ?', (group_id,)).fetchone()
    
    if not group_raw:
        conn.close()
        return redirect(url_for('index'))
    
    # Calculate balances to check if settled
    members = group_raw['members'].split(',')
    balances = {m: 0 for m in members}
    
    expenses_raw = conn.execute('SELECT * FROM expenses WHERE group_id = ?', (group_id,)).fetchall()
    
    for e in expenses_raw:
        total_amount = e['amount']
        payers = e['payer'].split(',')
        amount_per_payer = total_amount / len(payers) if payers else total_amount
        shared_with = e['shared_with'].split(',')
        amount_per_person = total_amount / len(shared_with) if shared_with else 0
        
        for m in shared_with:
            balances[m] -= amount_per_person
        for p in payers:
            balances[p] += amount_per_payer
    
    all_settled = all(abs(balance) < 0.01 for balance in balances.values())
    
    # Check if deletion is allowed
    if not all_settled and deleter_name != SECRET_CODE:
        conn.close()
        return """
        <html>
        <head>
            <meta charset="UTF-8">
            <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
        </head>
        <body>
            <div class="container mt-5">
                <div class="alert alert-danger">
                    <h4>Cannot Delete Group</h4>
                    <p>Settle all dues before deleting this group, or enter the secret code (1986) in the name field.</p>
                    <a href="/" class="btn btn-primary">Back to Groups</a>
                </div>
            </div>
        </body>
        </html>
        """, 403
    
    # Delete expenses first (foreign key constraint)
    conn.execute('DELETE FROM expenses WHERE group_id = ?', (group_id,))
    # Delete group
    conn.execute('DELETE FROM groups WHERE id = ?', (group_id,))
    conn.commit()
    conn.close()
    
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run()


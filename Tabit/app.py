import os
from flask import Flask, render_template, request, redirect, url_for, session
from werkzeug.utils import secure_filename
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'your_secret_key'

UPLOAD_FOLDER = 'static/uploads/'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'pdf'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# --- 1. Route for GROUP CREATION & DISPLAY ---
@app.route('/', methods=['GET', 'POST'])
def index():
    # Initialize session if needed
    if 'all_groups' not in session:
        session['all_groups'] = []
    
    if request.method == 'POST':
        group_name = request.form['group_name']
        members = request.form['members'].split(',')
        members = [m.strip() for m in members if m.strip()]  # Clean up
        file = request.files.get('group_photo')
        filename = None
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        
        # Create group with unique ID
        group_id = len(session.get('all_groups', [])) + 1
        new_group = {
            'id': group_id,
            'name': group_name,
            'members': members,
            'photo': filename,
            'expenses': [],
            'created_at': datetime.now().strftime('%Y-%m-%d %H:%M')
        }
        
        all_groups = session.get('all_groups', [])
        all_groups.append(new_group)
        session['all_groups'] = all_groups
        session.modified = True
        
        return redirect(url_for('index'))
    
    # Display all groups
    all_groups = session.get('all_groups', [])
    return render_template('index.html', groups=all_groups)

# --- 2. Route for ADDING EXPENSES ---
@app.route('/expenses/<int:group_id>', methods=['GET', 'POST'])
def expenses(group_id):
    all_groups = session.get('all_groups', [])
    group = next((g for g in all_groups if g['id'] == group_id), None)
    
    if not group:
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        payers = request.form.getlist('payer')
        description = request.form['description']
        amount = float(request.form['amount'])
        shared_with = request.form.getlist('shared_with')
        proof = request.files.get('bill_upload')
        bill_filename = None
        if proof and allowed_file(proof.filename):
            bill_filename = secure_filename(proof.filename)
            proof.save(os.path.join(app.config['UPLOAD_FOLDER'], bill_filename))
        
        expense = {
            'payer': payers,
            'desc': description,
            'amount': amount,
            'shared_with': shared_with,
            'bill': bill_filename
        }
        group['expenses'].append(expense)
        
        # Update session
        for i, g in enumerate(all_groups):
            if g['id'] == group_id:
                all_groups[i] = group
        session['all_groups'] = all_groups
        session.modified = True
        
        return redirect(url_for('expenses', group_id=group_id))
    
    return render_template('expenses.html', group=group)

# --- 3. Route for SPLIT VIEW ---
@app.route('/transactions/<int:group_id>')
def transactions(group_id):
    all_groups = session.get('all_groups', [])
    group = next((g for g in all_groups if g['id'] == group_id), None)
    
    if not group:
        return redirect(url_for('index'))
    
    members = group.get('members', [])
    expenses = group.get('expenses', [])
    balances = {m: 0 for m in members}
    
    for e in expenses:
        total_amount = e['amount']
        payers = e['payer']
        amount_per_payer = total_amount / len(payers) if payers else total_amount
        shared_with = e['shared_with']
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
    SECRET_CODE = '1986'  # The bypass code
    
    all_groups = session.get('all_groups', [])
    group = next((g for g in all_groups if g['id'] == group_id), None)
    
    if not group:
        return redirect(url_for('index'))
    
    # Check if all dues are settled
    members = group.get('members', [])
    expenses = group.get('expenses', [])
    balances = {m: 0 for m in members}
    
    for e in expenses:
        total_amount = e['amount']
        payers = e['payer']
        amount_per_payer = total_amount / len(payers) if payers else total_amount
        shared_with = e['shared_with']
        amount_per_person = total_amount / len(shared_with) if shared_with else 0
        for m in shared_with:
            balances[m] -= amount_per_person
        for p in payers:
            balances[p] += amount_per_payer
    
    all_settled = all(abs(balance) < 0.01 for balance in balances.values())
    
    # Check if secret code is entered in the name field OR dues are settled
    if not all_settled and deleter_name != SECRET_CODE:
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
                    <p>Settle all dues before deleting this group.</p>
                    <a href="/" class="btn btn-primary">Back to Groups</a>
                </div>
            </div>
        </body>
        </html>
        """, 403
    
    # Store deletion info
    if deleter_name == SECRET_CODE:
        group['deleted_by'] = 'Admin (Secret Code)'
        group['deleted_with_code'] = True
    else:
        group['deleted_by'] = deleter_name
    
    group['deleted_at'] = datetime.now().strftime('%Y-%m-%d %H:%M')
    
    # Remove group
    all_groups = [g for g in all_groups if g['id'] != group_id]
    session['all_groups'] = all_groups
    session.modified = True
    
    return redirect(url_for('index'))

if __name__ == '__main__':
    # For production (Render)
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)


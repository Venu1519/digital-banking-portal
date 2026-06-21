from flask import Flask, render_template, request, redirect, session
from werkzeug.security import generate_password_hash, check_password_hash
from flask_mysqldb import MySQL
from flask import send_file
from reportlab.pdfgen import canvas
import io

app = Flask(__name__)
app.secret_key = "bank123"

app.config['MYSQL_HOST'] = 'localhost'
app.config['MYSQL_USER'] = 'bankuser'
app.config['MYSQL_PASSWORD'] = 'bank123'
app.config['MYSQL_DB'] = 'banking_db'

mysql = MySQL(app)

# Home
@app.route('/')
def home():
    return redirect('/login')

# Register
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = generate_password_hash(request.form['password'])

        cur = mysql.connection.cursor()
        cur.execute(
            "INSERT INTO users(username,password) VALUES(%s,%s)",
            (username,password)
        )
        mysql.connection.commit()
        cur.close()

        return redirect('/login')

    return render_template('register.html')

# Login
@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        cur = mysql.connection.cursor()
        cur.execute("SELECT * FROM users WHERE username=%s", (username,))
        user = cur.fetchone()

        if user and check_password_hash(user[2], password):
            session['user_id'] = user[0]
            session['role'] = user[4]
            return redirect('/dashboard')
        else:
            return "Invalid username or password"

    return render_template('login.html')
    

# Dashboard
@app.route('/dashboard')
def dashboard():
    cur = mysql.connection.cursor()

    cur.execute(
        "SELECT username,balance FROM users WHERE id=%s",
        (session['user_id'],)
    )

    user = cur.fetchone()

    return render_template(
        'dashboard.html',
        username=user[0],
        balance=user[1]
    )

# Logout
@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')


@app.route('/transfer', methods=['GET', 'POST'])
def transfer():
    if 'user_id' not in session:
        return redirect('/login')

    if request.method == 'POST':
        receiver = request.form['receiver']
        amount = float(request.form['amount'])

        cur = mysql.connection.cursor()

        cur.execute("SELECT id, balance FROM users WHERE username=%s", (receiver,))
        receiver_user = cur.fetchone()

        cur.execute("SELECT balance FROM users WHERE id=%s", (session['user_id'],))
        sender_balance = cur.fetchone()[0]

        if receiver_user and sender_balance >= amount:
            receiver_id = receiver_user[0]

            cur.execute("UPDATE users SET balance = balance - %s WHERE id=%s", (amount, session['user_id']))
            cur.execute("UPDATE users SET balance = balance + %s WHERE id=%s", (amount, receiver_id))
            cur.execute(
                "INSERT INTO transactions(sender_id, receiver_id, amount) VALUES(%s,%s,%s)",
                (session['user_id'], receiver_id, amount)
            )

            mysql.connection.commit()
            cur.close()
            return redirect('/dashboard')

    return render_template('transfer.html')


@app.route('/transactions')
def transactions():
    if 'user_id' not in session:
        return redirect('/login')

    cur = mysql.connection.cursor()

    cur.execute("""
        SELECT 
            t.id,
            u1.username AS sender,
            u2.username AS receiver,
            t.amount,
            t.created_at
        FROM transactions t
        JOIN users u1 ON t.sender_id = u1.id
        JOIN users u2 ON t.receiver_id = u2.id
        WHERE t.sender_id = %s OR t.receiver_id = %s
        ORDER BY t.created_at DESC
    """, (session['user_id'], session['user_id']))

    transactions = cur.fetchall()
    cur.close()

    return render_template('transactions.html', transactions=transactions)

@app.route('/deposit', methods=['GET', 'POST'])
def deposit():
    if 'user_id' not in session:
        return redirect('/login')

    if request.method == 'POST':
        amount = float(request.form['amount'])

        cur = mysql.connection.cursor()
        cur.execute(
            "UPDATE users SET balance = balance + %s WHERE id = %s",
            (amount, session['user_id'])
        )
        mysql.connection.commit()
        cur.close()

        return redirect('/dashboard')

    return render_template('deposit.html')

@app.route('/withdraw', methods=['GET', 'POST'])
def withdraw():
    if 'user_id' not in session:
        return redirect('/login')

    if request.method == 'POST':
        amount = float(request.form['amount'])

        cur = mysql.connection.cursor()
        cur.execute("SELECT balance FROM users WHERE id=%s", (session['user_id'],))
        balance = cur.fetchone()[0]

        if balance >= amount:
            cur.execute(
                "UPDATE users SET balance = balance - %s WHERE id = %s",
                (amount, session['user_id'])
            )
            mysql.connection.commit()

        cur.close()
        return redirect('/dashboard')

    return render_template('withdraw.html')


@app.route('/admin')
def admin():
    if 'user_id' not in session:
        return redirect('/login')

    if session.get('role') != 'admin':
        return "Access Denied! Admin only."

    cur = mysql.connection.cursor()

    cur.execute("SELECT id, username, balance, role FROM users")
    users = cur.fetchall()

    cur.execute("""
        SELECT 
            t.id,
            u1.username,
            u2.username,
            t.amount,
            t.created_at
        FROM transactions t
        JOIN users u1 ON t.sender_id = u1.id
        JOIN users u2 ON t.receiver_id = u2.id
        ORDER BY t.created_at DESC
    """)
    transactions = cur.fetchall()

    cur.close()

    return render_template(
        'admin.html',
        users=users,
        transactions=transactions
    )

@app.route('/profile')
def profile():
    if 'user_id' not in session:
        return redirect('/login')

    cur = mysql.connection.cursor()
    cur.execute(
        "SELECT id, username, balance, role FROM users WHERE id=%s",
        (session['user_id'],)
    )
    user = cur.fetchone()
    cur.close()

    return render_template('profile.html', user=user)

@app.route('/statement')
def statement():
    if 'user_id' not in session:
        return redirect('/login')

    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT 
            t.id,
            u1.username,
            u2.username,
            t.amount,
            t.created_at
        FROM transactions t
        JOIN users u1 ON t.sender_id = u1.id
        JOIN users u2 ON t.receiver_id = u2.id
        WHERE t.sender_id = %s OR t.receiver_id = %s
        ORDER BY t.created_at DESC
    """, (session['user_id'], session['user_id']))

    transactions = cur.fetchall()
    cur.close()

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer)

    pdf.drawString(200, 800, "Digital Banking Statement")
    y = 760

    for t in transactions:
        line = f"ID:{t[0]} Sender:{t[1]} Receiver:{t[2]} Amount:Rs.{t[3]} Date:{t[4]}"
        pdf.drawString(40, y, line)
        y -= 25

    pdf.save()
    buffer.seek(0)

    return send_file(
        buffer,
        as_attachment=True,
        download_name="bank_statement.pdf",
        mimetype="application/pdf"
    )


@app.route('/api/balance')
def api_balance():
    if 'user_id' not in session:
        return {"error": "Unauthorized"}, 401

    cur = mysql.connection.cursor()
    cur.execute(
        "SELECT username, balance FROM users WHERE id=%s",
        (session['user_id'],)
    )

    user = cur.fetchone()
    cur.close()

    return {
        "username": user[0],
        "balance": float(user[1])
    }


if __name__ == '__main__':
    app.run(debug=True)
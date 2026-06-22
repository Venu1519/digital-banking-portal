from flask import Flask, render_template, request, redirect, session, send_file
from werkzeug.security import generate_password_hash, check_password_hash
from reportlab.pdfgen import canvas
import psycopg2
import os
import io

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "bank123")

DATABASE_URL = os.environ.get("DATABASE_URL")

def get_db_connection():
    return psycopg2.connect(DATABASE_URL)


@app.route('/')
def home():
    return redirect('/login')


@app.route('/init-db')
def init_db():
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username VARCHAR(100) UNIQUE NOT NULL,
            password VARCHAR(255) NOT NULL,
            balance NUMERIC(10,2) DEFAULT 1000.00,
            role VARCHAR(20) DEFAULT 'customer'
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id SERIAL PRIMARY KEY,
            sender_id INTEGER REFERENCES users(id),
            receiver_id INTEGER REFERENCES users(id),
            amount NUMERIC(10,2),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    conn.commit()
    cur.close()
    conn.close()

    return "Database tables created successfully!"


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = generate_password_hash(request.form['password'])

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users(username, password) VALUES(%s, %s)",
            (username, password)
        )
        conn.commit()
        cur.close()
        conn.close()

        return redirect('/login')

    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE username=%s", (username,))
        user = cur.fetchone()
        cur.close()
        conn.close()

        if user and check_password_hash(user[2], password):
            session['user_id'] = user[0]
            session['role'] = user[4]
            return redirect('/dashboard')
        else:
            return "Invalid username or password"

    return render_template('login.html')


@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect('/login')

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT username, balance FROM users WHERE id=%s",
        (session['user_id'],)
    )
    user = cur.fetchone()
    cur.close()
    conn.close()

    return render_template('dashboard.html', username=user[0], balance=user[1])


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

        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("SELECT id, balance FROM users WHERE username=%s", (receiver,))
        receiver_user = cur.fetchone()

        cur.execute("SELECT balance FROM users WHERE id=%s", (session['user_id'],))
        sender_balance = cur.fetchone()[0]

        if receiver_user and sender_balance >= amount:
            receiver_id = receiver_user[0]

            cur.execute(
                "UPDATE users SET balance = balance - %s WHERE id=%s",
                (amount, session['user_id'])
            )
            cur.execute(
                "UPDATE users SET balance = balance + %s WHERE id=%s",
                (amount, receiver_id)
            )
            cur.execute(
                "INSERT INTO transactions(sender_id, receiver_id, amount) VALUES(%s, %s, %s)",
                (session['user_id'], receiver_id, amount)
            )

            conn.commit()

        cur.close()
        conn.close()
        return redirect('/dashboard')

    return render_template('transfer.html')


@app.route('/transactions')
def transactions():
    if 'user_id' not in session:
        return redirect('/login')

    conn = get_db_connection()
    cur = conn.cursor()

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
    conn.close()

    return render_template('transactions.html', transactions=transactions)


@app.route('/deposit', methods=['GET', 'POST'])
def deposit():
    if 'user_id' not in session:
        return redirect('/login')

    if request.method == 'POST':
        amount = float(request.form['amount'])

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "UPDATE users SET balance = balance + %s WHERE id=%s",
            (amount, session['user_id'])
        )
        conn.commit()
        cur.close()
        conn.close()

        return redirect('/dashboard')

    return render_template('deposit.html')


@app.route('/withdraw', methods=['GET', 'POST'])
def withdraw():
    if 'user_id' not in session:
        return redirect('/login')

    if request.method == 'POST':
        amount = float(request.form['amount'])

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT balance FROM users WHERE id=%s", (session['user_id'],))
        balance = cur.fetchone()[0]

        if balance >= amount:
            cur.execute(
                "UPDATE users SET balance = balance - %s WHERE id=%s",
                (amount, session['user_id'])
            )
            conn.commit()

        cur.close()
        conn.close()
        return redirect('/dashboard')

    return render_template('withdraw.html')


@app.route('/admin')
def admin():
    if 'user_id' not in session:
        return redirect('/login')

    if session.get('role') != 'admin':
        return "Access Denied! Admin only."

    conn = get_db_connection()
    cur = conn.cursor()

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
    conn.close()

    return render_template('admin.html', users=users, transactions=transactions)


@app.route('/profile')
def profile():
    if 'user_id' not in session:
        return redirect('/login')

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, username, balance, role FROM users WHERE id=%s",
        (session['user_id'],)
    )
    user = cur.fetchone()
    cur.close()
    conn.close()

    return render_template('profile.html', user=user)


@app.route('/statement')
def statement():
    if 'user_id' not in session:
        return redirect('/login')

    conn = get_db_connection()
    cur = conn.cursor()
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
    conn.close()

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

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT username, balance FROM users WHERE id=%s",
        (session['user_id'],)
    )
    user = cur.fetchone()
    cur.close()
    conn.close()

    return {
        "username": user[0],
        "balance": float(user[1])
    }


if __name__ == '__main__':
    app.run(debug=True)
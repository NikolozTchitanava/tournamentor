import sqlite3
import random
from flask import Flask, g, render_template, request, redirect, url_for, flash

app = Flask(__name__)
app.secret_key = "change-this-to-a-secret-key"

DATABASE = 'tournaments.db'

def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(exc):
    db = g.pop('db', None)
    if db is not None:
        db.close()

def init_db():
    db = sqlite3.connect(DATABASE)
    db.executescript("""
    CREATE TABLE IF NOT EXISTS tournament (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        num_pots INTEGER NOT NULL,
        num_groups INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS player (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tourn_id INTEGER NOT NULL,
        pot INTEGER NOT NULL,
        name TEXT NOT NULL,
        grp INTEGER,
        FOREIGN KEY(tourn_id) REFERENCES tournament(id)
    );
    """)
    db.commit()
    db.close()

@app.route('/', methods=('GET','POST'))
def index():
    if request.method == 'POST':
        try:
            num_pots = int(request.form['num_pots'])
            num_groups = int(request.form['num_groups'])
        except ValueError:
            flash("Please enter valid integers.")
            return redirect(url_for('index'))

        db = get_db()
        cur = db.execute(
            "INSERT INTO tournament (num_pots,num_groups) VALUES (?,?)",
            (num_pots, num_groups)
        )
        db.commit()
        tourn_id = cur.lastrowid
        return redirect(url_for('enter_players', tourn_id=tourn_id))

    return render_template('create_tournament.html')

@app.route('/t/<int:tourn_id>/pots', methods=('GET','POST'))
def enter_players(tourn_id):
    db = get_db()
    tourn = db.execute(
        "SELECT * FROM tournament WHERE id = ?", (tourn_id,)
    ).fetchone()

    if tourn is None:
        flash("Tournament not found.")
        return redirect(url_for('index'))

    if request.method == 'POST':
        db.execute("DELETE FROM player WHERE tourn_id = ?", (tourn_id,))
        db.commit()

        for pot in range(1, tourn['num_pots']+1):
            raw = request.form.get(f'pot_{pot}', '')
            names = [n.strip() for n in raw.splitlines() if n.strip()]
            random.shuffle(names)
            for idx, name in enumerate(names):
                grp = (idx % tourn['num_groups']) + 1
                db.execute(
                    "INSERT INTO player (tourn_id,pot,name,grp) VALUES (?,?,?,?)",
                    (tourn_id, pot, name, grp)
                )
        db.commit()
        return redirect(url_for('show_draw', tourn_id=tourn_id))

    return render_template('pots.html', num_pots=tourn['num_pots'])

@app.route('/t/<int:tourn_id>/draw')
def show_draw(tourn_id):
    db = get_db()
    tourn = db.execute(
        "SELECT * FROM tournament WHERE id = ?", (tourn_id,)
    ).fetchone()
    if not tourn:
        flash("Tournament not found.")
        return redirect(url_for('index'))

    rows = db.execute(
        "SELECT name,pot,grp FROM player WHERE tourn_id = ? ORDER BY grp,pot",
        (tourn_id,)
    ).fetchall()

    groups = {g: [] for g in range(1, tourn['num_groups']+1)}
    for r in rows:
        groups[r['grp']].append((r['name'], r['pot']))

    return render_template('assignments.html', groups=groups)

if __name__ == '__main__':
    init_db()
    app.run(debug=True, port=5001)

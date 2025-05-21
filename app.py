import sqlite3
import random
import itertools
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
    CREATE TABLE IF NOT EXISTS result (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tourn_id INTEGER NOT NULL,
        grp INTEGER NOT NULL,
        p1 TEXT NOT NULL,
        p2 TEXT NOT NULL,
        g1 INTEGER NOT NULL,
        g2 INTEGER NOT NULL,
        UNIQUE(tourn_id, grp, p1, p2)
    );
    """)
    db.commit()
    db.close()

def compute_standings(tourn_id, grp):
    """Return sorted standings list for group."""
    db = get_db()
    players = [r['name'] for r in db.execute(
        "SELECT name FROM player WHERE tourn_id=? AND grp=?",
        (tourn_id, grp)
    ).fetchall()]
    stats = {p: {'MP':0,'W':0,'D':0,'L':0,'GS':0,'GC':0,'Pts':0} for p in players}

    for r in db.execute(
        "SELECT p1,p2,g1,g2 FROM result WHERE tourn_id=? AND grp=?",
        (tourn_id, grp)
    ).fetchall():
        p1, p2, g1, g2 = r['p1'], r['p2'], r['g1'], r['g2']
        stats[p1]['MP'] += 1; stats[p2]['MP'] += 1
        stats[p1]['GS'] += g1; stats[p1]['GC'] += g2
        stats[p2]['GS'] += g2; stats[p2]['GC'] += g1
        if g1 > g2:
            stats[p1]['W'] += 1; stats[p2]['L'] += 1; stats[p1]['Pts'] += 3
        elif g2 > g1:
            stats[p2]['W'] += 1; stats[p1]['L'] += 1; stats[p2]['Pts'] += 3
        else:
            stats[p1]['D'] += 1; stats[p2]['D'] += 1
            stats[p1]['Pts'] += 1; stats[p2]['Pts'] += 1

    table = []
    for p, s in stats.items():
        s['GD'] = s['GS'] - s['GC']
        table.append({'team': p, **s})
    # sort by points, then GD, then GS
    table.sort(key=lambda x: (x['Pts'], x['GD'], x['GS']), reverse=True)
    return table

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
        return redirect(url_for('enter_players', tourn_id=cur.lastrowid))
    return render_template('create_tournament.html')

@app.route('/t/<int:tourn_id>/pots', methods=('GET','POST'))
def enter_players(tourn_id):
    db = get_db()
    tourn = db.execute("SELECT * FROM tournament WHERE id=?", (tourn_id,)).fetchone()
    if not tourn:
        flash("Tournament not found."); return redirect(url_for('index'))

    if request.method == 'POST':
        db.execute("DELETE FROM player WHERE tourn_id=?", (tourn_id,))
        db.commit()
        G = tourn['num_groups']
        # gather & shuffle each pot
        pots = []
        for pot_idx in range(1, tourn['num_pots']+1):
            raw = request.form.get(f'pot_{pot_idx}', '')
            names = [n.strip() for n in raw.splitlines() if n.strip()]
            random.shuffle(names)
            pots.append((pot_idx, names))
        # track group sizes to minimize variance
        group_totals = [0]*G
        for pot_idx, names in pots:
            N = len(names)
            q, r = divmod(N, G)
            # assign extras to currently smallest groups
            sorted_idxs = sorted(range(G), key=lambda i: group_totals[i])
            counts = [q]*G
            for i in sorted_idxs[:r]:
                counts[i] += 1
            i0 = 0
            for gi, cnt in enumerate(counts):
                for _ in range(cnt):
                    db.execute(
                        "INSERT INTO player (tourn_id,pot,name,grp) VALUES (?,?,?,?)",
                        (tourn_id, pot_idx, names[i0], gi+1)
                    )
                    group_totals[gi] += 1
                    i0 += 1
        db.commit()
        return redirect(url_for('show_draw', tourn_id=tourn_id))

    return render_template('pots.html', num_pots=tourn['num_pots'])

@app.route('/t/<int:tourn_id>/draw')
def show_draw(tourn_id):
    db = get_db()
    tourn = db.execute("SELECT * FROM tournament WHERE id=?", (tourn_id,)).fetchone()
    if not tourn:
        flash("Tournament not found."); return redirect(url_for('index'))

    rows = db.execute(
        "SELECT name,pot,grp FROM player WHERE tourn_id=? ORDER BY grp,pot",
        (tourn_id,)
    ).fetchall()
    groups = {g: [] for g in range(1, tourn['num_groups']+1)}
    for r in rows:
        groups[r['grp']].append((r['name'], r['pot']))

    # build live standings for every group
    standings = {g: compute_standings(tourn_id, g) for g in groups}

    return render_template(
        'assignments.html',
        tourn_id=tourn_id,
        groups=groups,
        standings=standings
    )

@app.route('/t/<int:tourn_id>/group/<int:grp>/matches', methods=('GET','POST'))
def enter_results(tourn_id, grp):
    db = get_db()
    players = [r['name'] for r in db.execute(
        "SELECT name FROM player WHERE tourn_id=? AND grp=? ORDER BY pot,name",
        (tourn_id, grp)
    ).fetchall()]
    if not players:
        flash("Group not found or empty."); return redirect(url_for('show_draw', tourn_id=tourn_id))

    pairings = list(itertools.combinations(players, 2))
    if request.method == 'POST':
        for p1, p2 in pairings:
            try:
                g1 = int(request.form[f"{p1}_vs_{p2}_g1"])
                g2 = int(request.form[f"{p1}_vs_{p2}_g2"])
            except ValueError:
                continue
            # normalize order
            if p1 < p2:
                a, b, ga, gb = p1, p2, g1, g2
            else:
                a, b, ga, gb = p2, p1, g2, g1
            db.execute("""
              INSERT INTO result (tourn_id,grp,p1,p2,g1,g2)
              VALUES (?,?,?,?,?,?)
              ON CONFLICT(tourn_id,grp,p1,p2)
              DO UPDATE SET g1=excluded.g1,g2=excluded.g2
            """, (tourn_id, grp, a, b, ga, gb))
        db.commit()
        return redirect(url_for('enter_results', tourn_id=tourn_id, grp=grp))

    # load existing results for form prefill
    rows = db.execute(
        "SELECT p1,p2,g1,g2 FROM result WHERE tourn_id=? AND grp=?",
        (tourn_id, grp)
    ).fetchall()
    results = {}
    for p1, p2 in pairings:
        key = f"{p1}|{p2}"
        match = next((r for r in rows if (r['p1'],r['p2'])==(p1,p2)), None)
        if match:
            ga, gb = match['g1'], match['g2']
        else:
            match = next((r for r in rows if (r['p1'],r['p2'])==(p2,p1)), None)
            if match:
                ga, gb = match['g2'], match['g1']
            else:
                ga = gb = None
        results[key] = (ga, gb)

    # live standings for this group
    standings = compute_standings(tourn_id, grp)

    return render_template(
        'matches.html',
        tourn_id=tourn_id,
        grp=grp,
        pairings=pairings,
        results=results,
        standings=standings
    )

if __name__ == '__main__':
    init_db()
    app.run(debug=True)

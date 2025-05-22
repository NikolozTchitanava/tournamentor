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
    DROP TABLE IF EXISTS tournament;
    CREATE TABLE tournament (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        num_pots INTEGER NOT NULL,
        num_groups INTEGER NOT NULL
    );
    DROP TABLE IF EXISTS player;
    CREATE TABLE player (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tourn_id INTEGER NOT NULL,
        pot INTEGER NOT NULL,
        name TEXT NOT NULL,
        grp INTEGER,
        FOREIGN KEY(tourn_id) REFERENCES tournament(id)
    );
    DROP TABLE IF EXISTS result;
    CREATE TABLE result (
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
        p1,p2,g1,g2 = r['p1'], r['p2'], r['g1'], r['g2']
        stats[p1]['MP']+=1; stats[p2]['MP']+=1
        stats[p1]['GS']+=g1; stats[p1]['GC']+=g2
        stats[p2]['GS']+=g2; stats[p2]['GC']+=g1
        if g1>g2:
            stats[p1]['W']+=1; stats[p2]['L']+=1; stats[p1]['Pts']+=3
        elif g2>g1:
            stats[p2]['W']+=1; stats[p1]['L']+=1; stats[p2]['Pts']+=3
        else:
            stats[p1]['D']+=1; stats[p2]['D']+=1
            stats[p1]['Pts']+=1; stats[p2]['Pts']+=1
    table=[]
    for p,s in stats.items():
        s['GD']=s['GS']-s['GC']
        table.append({'team':p,**s})
    table.sort(key=lambda x:(x['Pts'],x['GD'],x['GS']),reverse=True)
    return table

@app.route('/', methods=('GET','POST'))
def index():
    db = get_db()
    if request.method=='POST':
        # Create new tournament
        name = request.form.get('name','').strip()
        try:
            num_pots = int(request.form['num_pots'])
            num_groups = int(request.form['num_groups'])
            assert name
        except:
            flash("Please provide a name and valid numbers.")
            return redirect(url_for('index'))
        cur = db.execute(
            "INSERT INTO tournament (name,num_pots,num_groups) VALUES (?,?,?)",
            (name,num_pots,num_groups)
        )
        db.commit()
        return redirect(url_for('enter_players', tourn_id=cur.lastrowid))

    # GET: list tournaments
    tournaments = db.execute(
        "SELECT * FROM tournament ORDER BY id DESC"
    ).fetchall()
    return render_template('index.html', tournaments=tournaments)

@app.route('/t/<int:tourn_id>/delete', methods=('POST',))
def delete_tournament(tourn_id):
    db = get_db()
    db.execute("DELETE FROM result WHERE tourn_id=?", (tourn_id,))
    db.execute("DELETE FROM player WHERE tourn_id=?", (tourn_id,))
    db.execute("DELETE FROM tournament WHERE id=?", (tourn_id,))
    db.commit()
    flash("Tournament deleted.")
    return redirect(url_for('index'))

@app.route('/t/<int:tourn_id>/pots', methods=('GET','POST'))
def enter_players(tourn_id):
    db = get_db()
    tourn = db.execute("SELECT * FROM tournament WHERE id=?", (tourn_id,)).fetchone()
    if not tourn:
        flash("Tournament not found."); return redirect(url_for('index'))

    if request.method=='POST':
        db.execute("DELETE FROM player WHERE tourn_id=?", (tourn_id,))
        db.commit()
        G = tourn['num_groups']
        # collect & shuffle each pot
        pots=[]
        for i in range(1, tourn['num_pots']+1):
            raw = request.form.get(f'pot_{i}','')
            names=[n.strip() for n in raw.splitlines() if n.strip()]
            random.shuffle(names)
            pots.append((i,names))
        # balance group sizes
        totals=[0]*G
        for pot_idx,names in pots:
            N=len(names); q,r=divmod(N,G)
            order=sorted(range(G), key=lambda x:totals[x])
            sizes=[q]*G
            for x in order[:r]: sizes[x]+=1
            idx=0
            for gi,sz in enumerate(sizes):
                for _ in range(sz):
                    db.execute(
                        "INSERT INTO player (tourn_id,pot,name,grp) VALUES (?,?,?,?)",
                        (tourn_id,pot_idx,names[idx],gi+1)
                    )
                    totals[gi]+=1; idx+=1
        db.commit()
        return redirect(url_for('show_draw', tourn_id=tourn_id))

    return render_template('pots.html', num_pots=tourn['num_pots'], tourn=tourn)

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
    groups = {g:[] for g in range(1,tourn['num_groups']+1)}
    for r in rows: groups[r['grp']].append((r['name'],r['pot']))
    standings = {g: compute_standings(tourn_id,g) for g in groups}
    return render_template('assignments.html',
                           tourn_id=tourn_id,
                           tourn=tourn,
                           groups=groups,
                           standings=standings)

@app.route('/t/<int:tourn_id>/group/<int:grp>/matches', methods=('GET','POST'))
def enter_results(tourn_id, grp):
    db = get_db()
    # fetch players
    players = [r['name'] for r in db.execute(
        "SELECT name FROM player WHERE tourn_id=? AND grp=? ORDER BY pot,name",
        (tourn_id,grp)
    ).fetchall()]
    if not players:
        flash("No players in that group."); return redirect(url_for('show_draw', tourn_id=tourn_id))
    pairings = list(itertools.combinations(players,2))

    if request.method=='POST':
        for p1,p2 in pairings:
            try:
                g1=int(request.form[f"{p1}_vs_{p2}_g1"])
                g2=int(request.form[f"{p1}_vs_{p2}_g2"])
            except:
                continue
            if p1<p2: a,b,ga,gb = p1,p2,g1,g2
            else:      a,b,ga,gb = p2,p1,g2,g1
            db.execute("""
              INSERT INTO result(tourn_id,grp,p1,p2,g1,g2)
              VALUES(?,?,?,?,?,?)
              ON CONFLICT(tourn_id,grp,p1,p2)
              DO UPDATE SET g1=excluded.g1,g2=excluded.g2
            """,(tourn_id,grp,a,b,ga,gb))
        db.commit()
        return redirect(url_for('enter_results', tourn_id=tourn_id, grp=grp))

    # prefill existing
    rows = db.execute(
        "SELECT p1,p2,g1,g2 FROM result WHERE tourn_id=? AND grp=?",
        (tourn_id,grp)
    ).fetchall()
    results={}
    for p1,p2 in pairings:
        key=f"{p1}|{p2}"
        m = next((r for r in rows if (r['p1'],r['p2'])==(p1,p2)),None)
        if m:    ga,gb = m['g1'],m['g2']
        else:
            m = next((r for r in rows if (r['p1'],r['p2'])==(p2,p1)),None)
            ga,gb = (m['g2'],m['g1']) if m else (None,None)
        results[key]=(ga,gb)

    standings = compute_standings(tourn_id,grp)
    return render_template('matches.html',
                           tourn_id=tourn_id,
                           grp=grp,
                           pairings=pairings,
                           results=results,
                           standings=standings)
    
if __name__=='__main__':
    init_db()
    app.run(debug=True)

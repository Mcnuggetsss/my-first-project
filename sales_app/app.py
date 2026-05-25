from flask import Flask, render_template, request, jsonify, redirect, url_for, abort
import sqlite3
import os
from datetime import datetime

app = Flask(__name__)
DATABASE = os.path.join(os.path.dirname(__file__), 'sales.db')

# ─── Database ─────────────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    conn = get_db()
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            contact TEXT DEFAULT '',
            phone TEXT DEFAULT '',
            email TEXT DEFAULT '',
            address TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            series TEXT NOT NULL,
            large_category TEXT NOT NULL,
            small_category TEXT NOT NULL,
            name TEXT NOT NULL,
            unit TEXT DEFAULT 'kg',
            price REAL NOT NULL DEFAULT 0,
            stock REAL DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_number TEXT UNIQUE NOT NULL,
            customer_id INTEGER,
            customer_name TEXT NOT NULL DEFAULT '',
            order_date TEXT NOT NULL,
            total REAL DEFAULT 0,
            status TEXT DEFAULT 'confirmed',
            notes TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS order_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            product_id INTEGER,
            product_name TEXT NOT NULL,
            series TEXT DEFAULT '',
            large_category TEXT DEFAULT '',
            small_category TEXT DEFAULT '',
            unit TEXT DEFAULT '',
            quantity REAL NOT NULL,
            unit_price REAL NOT NULL,
            subtotal REAL NOT NULL,
            FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE,
            FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE SET NULL
        );
    ''')
    conn.commit()
    conn.close()

def gen_order_number():
    today = datetime.now().strftime('%Y%m%d')
    conn = get_db()
    row = conn.execute(
        "SELECT COUNT(*) as c FROM orders WHERE order_number LIKE ?",
        (f'ORD-{today}-%',)
    ).fetchone()
    conn.close()
    seq = row['c'] + 1
    return f'ORD-{today}-{seq:03d}'

# ─── Dashboard ────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    conn = get_db()
    stats = {
        'orders_total': conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0],
        'orders_month': conn.execute(
            "SELECT COUNT(*) FROM orders WHERE order_date LIKE ?",
            (datetime.now().strftime('%Y-%m') + '%',)
        ).fetchone()[0],
        'revenue_month': conn.execute(
            "SELECT COALESCE(SUM(total),0) FROM orders WHERE order_date LIKE ?",
            (datetime.now().strftime('%Y-%m') + '%',)
        ).fetchone()[0],
        'customers': conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0],
        'products': conn.execute("SELECT COUNT(*) FROM products").fetchone()[0],
        'low_stock': conn.execute("SELECT COUNT(*) FROM products WHERE stock < 10").fetchone()[0],
    }
    recent_orders = conn.execute(
        "SELECT * FROM orders ORDER BY created_at DESC LIMIT 8"
    ).fetchall()
    conn.close()
    return render_template('index.html', stats=stats, recent_orders=recent_orders)

# ─── Orders ───────────────────────────────────────────────────────────────────

@app.route('/orders')
def orders_list():
    q = request.args.get('q', '')
    status = request.args.get('status', '')
    conn = get_db()
    sql = "SELECT * FROM orders WHERE 1=1"
    params = []
    if q:
        sql += " AND (order_number LIKE ? OR customer_name LIKE ?)"
        params += [f'%{q}%', f'%{q}%']
    if status:
        sql += " AND status = ?"
        params.append(status)
    sql += " ORDER BY created_at DESC"
    orders = conn.execute(sql, params).fetchall()
    conn.close()
    return render_template('orders_list.html', orders=orders, q=q, status=status)

@app.route('/orders/new', methods=['GET', 'POST'])
def order_new():
    if request.method == 'POST':
        data = request.get_json()
        conn = get_db()
        order_number = gen_order_number()
        total = sum(item['subtotal'] for item in data['items'])
        conn.execute(
            "INSERT INTO orders (order_number,customer_id,customer_name,order_date,total,status,notes) VALUES (?,?,?,?,?,?,?)",
            (order_number, data.get('customer_id') or None, data['customer_name'],
             data['order_date'], total, 'confirmed', data.get('notes', ''))
        )
        order_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        for item in data['items']:
            conn.execute(
                "INSERT INTO order_items (order_id,product_id,product_name,series,large_category,small_category,unit,quantity,unit_price,subtotal) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (order_id, item.get('product_id'), item['product_name'], item.get('series',''),
                 item.get('large_category',''), item.get('small_category',''), item.get('unit',''),
                 item['quantity'], item['unit_price'], item['subtotal'])
            )
            if item.get('product_id'):
                conn.execute("UPDATE products SET stock = stock - ? WHERE id = ?",
                             (item['quantity'], item['product_id']))
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'order_id': order_id, 'order_number': order_number})

    conn = get_db()
    customers = conn.execute("SELECT * FROM customers ORDER BY name").fetchall()
    conn.close()
    return render_template('order_new.html', customers=customers,
                           today=datetime.now().strftime('%Y-%m-%d'))

@app.route('/orders/<int:oid>')
def order_detail(oid):
    conn = get_db()
    order = conn.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
    if not order:
        abort(404)
    items = conn.execute("SELECT * FROM order_items WHERE order_id=?", (oid,)).fetchall()
    conn.close()
    return render_template('order_detail.html', order=order, items=items)

@app.route('/orders/<int:oid>/delete', methods=['POST'])
def order_delete(oid):
    conn = get_db()
    conn.execute("DELETE FROM orders WHERE id=?", (oid,))
    conn.commit()
    conn.close()
    return redirect(url_for('orders_list'))

@app.route('/orders/<int:oid>/status', methods=['POST'])
def order_status(oid):
    status = request.json.get('status')
    conn = get_db()
    conn.execute("UPDATE orders SET status=? WHERE id=?", (status, oid))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

# ─── Products ─────────────────────────────────────────────────────────────────

@app.route('/products')
def products_list():
    conn = get_db()
    products = conn.execute("SELECT * FROM products ORDER BY series,large_category,small_category,name").fetchall()
    conn.close()
    return render_template('products.html', products=products)

@app.route('/products/save', methods=['POST'])
def product_save():
    data = request.get_json()
    conn = get_db()
    pid = data.get('id')
    if pid:
        conn.execute(
            "UPDATE products SET series=?,large_category=?,small_category=?,name=?,unit=?,price=?,stock=? WHERE id=?",
            (data['series'], data['large_category'], data['small_category'], data['name'],
             data['unit'], data['price'], data['stock'], pid)
        )
    else:
        conn.execute(
            "INSERT INTO products (series,large_category,small_category,name,unit,price,stock) VALUES (?,?,?,?,?,?,?)",
            (data['series'], data['large_category'], data['small_category'], data['name'],
             data['unit'], data['price'], data.get('stock', 0))
        )
        pid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'id': pid})

@app.route('/products/<int:pid>/delete', methods=['POST'])
def product_delete(pid):
    conn = get_db()
    conn.execute("DELETE FROM products WHERE id=?", (pid,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

# ─── Customers ────────────────────────────────────────────────────────────────

@app.route('/customers')
def customers_list():
    conn = get_db()
    customers = conn.execute("SELECT * FROM customers ORDER BY name").fetchall()
    conn.close()
    return render_template('customers.html', customers=customers)

@app.route('/customers/save', methods=['POST'])
def customer_save():
    data = request.get_json()
    conn = get_db()
    cid = data.get('id')
    if cid:
        conn.execute(
            "UPDATE customers SET name=?,contact=?,phone=?,email=?,address=?,notes=? WHERE id=?",
            (data['name'], data.get('contact',''), data.get('phone',''),
             data.get('email',''), data.get('address',''), data.get('notes',''), cid)
        )
    else:
        conn.execute(
            "INSERT INTO customers (name,contact,phone,email,address,notes) VALUES (?,?,?,?,?,?)",
            (data['name'], data.get('contact',''), data.get('phone',''),
             data.get('email',''), data.get('address',''), data.get('notes',''))
        )
        cid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'id': cid})

@app.route('/customers/<int:cid>/delete', methods=['POST'])
def customer_delete(cid):
    conn = get_db()
    conn.execute("DELETE FROM customers WHERE id=?", (cid,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

# ─── Inventory ────────────────────────────────────────────────────────────────

@app.route('/inventory')
def inventory():
    conn = get_db()
    products = conn.execute(
        "SELECT * FROM products ORDER BY series,large_category,small_category,name"
    ).fetchall()
    conn.close()
    return render_template('inventory.html', products=products)

@app.route('/inventory/<int:pid>/update', methods=['POST'])
def inventory_update(pid):
    data = request.get_json()
    conn = get_db()
    conn.execute("UPDATE products SET stock=? WHERE id=?", (data['stock'], pid))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

# ─── API ──────────────────────────────────────────────────────────────────────

@app.route('/api/products')
def api_products():
    conn = get_db()
    products = conn.execute(
        "SELECT * FROM products ORDER BY series,large_category,small_category,name"
    ).fetchall()
    conn.close()
    return jsonify([dict(p) for p in products])

@app.route('/api/categories')
def api_categories():
    conn = get_db()
    rows = conn.execute(
        "SELECT DISTINCT series,large_category,small_category FROM products ORDER BY series,large_category,small_category"
    ).fetchall()
    conn.close()
    tree = {}
    for r in rows:
        s, lc, sc = r['series'], r['large_category'], r['small_category']
        tree.setdefault(s, {}).setdefault(lc, set()).add(sc)
    result = {s: {lc: list(scs) for lc, scs in lcs.items()} for s, lcs in tree.items()}
    return jsonify(result)

@app.route('/api/customers')
def api_customers():
    conn = get_db()
    customers = conn.execute("SELECT id,name,phone,address FROM customers ORDER BY name").fetchall()
    conn.close()
    return jsonify([dict(c) for c in customers])

# ─── Main ─────────────────────────────────────────────────────────────────────

init_db()  # always init on startup (safe to call multiple times)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print("\n" + "="*50)
    print("  食品批发销售管理系统 启动成功！")
    print(f"  请用浏览器打开: http://127.0.0.1:{port}")
    print("="*50 + "\n")
    app.run(debug=False, host='0.0.0.0', port=port)

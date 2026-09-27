from flask import Flask, render_template, request, redirect, session
import mysql.connector
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash
import os

app = Flask(__name__)
load_dotenv()
app.secret_key = "deliveryapp_secret"

def get_db_connection():
    connection = mysql.connector.connect(
        host=os.getenv("DB_HOST"),
        port=int(os.getenv("DB_PORT")),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        database=os.getenv("DB_NAME")
    )
    return connection

@app.route("/")
def home():
    connection = get_db_connection()
    cursor = connection.cursor()

    search = request.args.get("search", "")

    if search:
        cursor.execute("""
            SELECT DISTINCT r.id, r.name, r.category, r.description
            FROM restaurants r
            LEFT JOIN menus m ON r.id = m.restaurant_id
            WHERE r.name LIKE %s
               OR m.name LIKE %s
        """, (f"%{search}%", f"%{search}%"))
    else:
        cursor.execute("""
            SELECT id, name, category, description
            FROM restaurants
        """)

    restaurants = cursor.fetchall()

    cursor.close()
    connection.close()

    nickname = session.get("nickname")

    return render_template(
        "index.html",
        restaurants=restaurants,
        nickname=nickname,
        search=search
    )


@app.route("/restaurant/<int:restaurant_id>")
def restaurant_detail(restaurant_id):
    connection = get_db_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT id, name, category, description
        FROM restaurants
        WHERE id = %s
    """, (restaurant_id,))

    restaurant = cursor.fetchone()

    cursor.execute("""
        SELECT id, name, price, calories, description
        FROM menus
        WHERE restaurant_id = %s
    """, (restaurant_id,))

    menus = cursor.fetchall()

    cursor.close()
    connection.close()

    return render_template(
        "restaurant.html",
        restaurant=restaurant,
        menus=menus
    )

@app.route("/cart/add", methods=["POST"])
def add_cart():
    if not session.get("user_id"):
        return redirect("/login")

    menu_id = request.form["menu_id"]
    cart = session.get("cart", {})

    if isinstance(cart, list):
        cart = {}

    if menu_id in cart:
        cart[menu_id] += 1
    else:
        cart[menu_id] = 1

    session["cart"] = cart

    return redirect("/cart")


@app.route("/cart")
def cart():
    if not session.get("user_id"):
        return redirect("/login")

    cart = session.get("cart", {})

    connection = get_db_connection()
    cursor = connection.cursor()

    menus = []

    for menu_id, quantity in cart.items():
        cursor.execute("""
            SELECT id, name, price, calories
            FROM menus
            WHERE id = %s
        """, (menu_id,))

        menu = cursor.fetchone()

        if menu:
            menus.append((menu, quantity))

    cursor.close()
    connection.close()

    return render_template("cart.html", menus=menus)


@app.route("/cart/minus", methods=["POST"])
def cart_minus():
    if not session.get("user_id"):
        return redirect("/login")

    menu_id = request.form["menu_id"]
    cart = session.get("cart", {})

    if menu_id in cart:
        cart[menu_id] -= 1

        if cart[menu_id] <= 0:
            del cart[menu_id]

    session["cart"] = cart

    return redirect("/cart")


@app.route("/cart/delete", methods=["POST"])
def cart_delete():
    if not session.get("user_id"):
        return redirect("/login")

    menu_id = request.form["menu_id"]
    cart = session.get("cart", {})

    if menu_id in cart:
        del cart[menu_id]

    session["cart"] = cart

    return redirect("/cart")

@app.route("/order", methods=["POST"])
def order():
    cart = session.get("cart", {})

    if not cart:
        return redirect("/cart")

    connection = get_db_connection()
    cursor = connection.cursor()

    user_id = session.get("user_id")

    if not user_id:
        return redirect("/login")

    total_price = 0
    total_calories = 0

    for menu_id, quantity in cart.items():
        cursor.execute("""
            SELECT price, calories
            FROM menus
            WHERE id = %s
        """, (menu_id,))

        menu = cursor.fetchone()

        if menu:
            total_price += menu[0] * quantity
            total_calories += menu[1] * quantity

    cursor.execute("""
        INSERT INTO orders (user_id, total_price, total_calories)
        VALUES (%s, %s, %s)
    """, (user_id, total_price, total_calories))

    order_id = cursor.lastrowid

    for menu_id, quantity in cart.items():
        cursor.execute("""
            SELECT price, calories
            FROM menus
            WHERE id = %s
        """, (menu_id,))

        menu = cursor.fetchone()

        if menu:
            cursor.execute("""
                INSERT INTO order_items
                (order_id, menu_id, quantity, price, calories)
                VALUES (%s, %s, %s, %s, %s)
            """, (
                order_id,
                menu_id,
                quantity,
                menu[0],
                menu[1]
            ))

    connection.commit()

    cursor.close()
    connection.close()

    session["last_order_price"] = total_price
    session["last_order_calories"] = total_calories

    session["cart"] = {}

    return redirect("/order/complete")

@app.route("/order/complete")
def order_complete():
    if not session.get("user_id"):
        return redirect("/login")

    saved_price = session.get("last_order_price")
    saved_calories = session.get("last_order_calories")

    if saved_price is None or saved_calories is None:
        return redirect("/orders")

    return render_template(
        "order_complete.html",
        saved_price=saved_price,
        saved_calories=saved_calories
    )

@app.route("/orders")
def orders():
    connection = get_db_connection()
    cursor = connection.cursor()

    user_id = session.get("user_id")

    if not user_id:
        return redirect("/login")

    cursor.execute("""
        SELECT id, order_date, total_price, total_calories
        FROM orders
        WHERE user_id = %s
        ORDER BY order_date DESC
    """, (user_id,))

    orders = cursor.fetchall()

    cursor.close()
    connection.close()

    return render_template("orders.html", orders=orders)

@app.route("/orders/<int:order_id>")
def order_detail(order_id):
    user_id = session.get("user_id")

    if not user_id:
        return redirect("/login")

    connection = get_db_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT id, order_date, total_price, total_calories
        FROM orders
        WHERE id = %s AND user_id = %s
    """, (order_id, user_id))

    order = cursor.fetchone()

    if not order:
        cursor.close()
        connection.close()
        return redirect("/orders")

    cursor.execute("""
        SELECT
            m.name,
            oi.quantity,
            oi.price,
            oi.calories,
            r.name
        FROM order_items oi
        JOIN menus m ON oi.menu_id = m.id
        JOIN restaurants r ON m.restaurant_id = r.id
        WHERE oi.order_id = %s
    """, (order_id,))

    order_items = cursor.fetchall()

    cursor.close()
    connection.close()

    return render_template(
        "order_detail.html",
        order=order,
        order_items=order_items
    )

@app.route("/saving")
def saving():
    connection = get_db_connection()
    cursor = connection.cursor()

    user_id = session.get("user_id")

    if not user_id:
        cursor.close()
        connection.close()
        return redirect("/login")

    cursor.execute("""
        SELECT
            COUNT(*),
            COALESCE(SUM(total_price), 0),
            COALESCE(SUM(total_calories), 0)
        FROM orders
        WHERE user_id = %s
    """, (user_id,))

    saving_data = cursor.fetchone()

    cursor.close()
    connection.close()

    return render_template(
        "saving.html",
        saving_data=saving_data
    )

@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "GET":
        return render_template("signup.html")

    username = request.form["username"]
    password = request.form["password"]
    nickname = request.form["nickname"]

    connection = get_db_connection()
    cursor = connection.cursor(buffered=True)

    cursor.execute(
        "SELECT id FROM users WHERE username = %s",
        (username,)
    )

    existing_user = cursor.fetchone()

    if existing_user:
        cursor.close()
        connection.close()
        return "이미 사용 중인 아이디입니다."

    hashed_password = generate_password_hash(password)

    cursor.execute("""
        INSERT INTO users (username, password, nickname)
        VALUES (%s, %s, %s)
    """, (username, hashed_password, nickname))

    connection.commit()
    cursor.close()
    connection.close()

    return redirect("/login")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        connection = get_db_connection()
        cursor = connection.cursor(buffered=True)

        cursor.execute(
            "SELECT id, nickname, password FROM users WHERE username = %s",
            (username,)
        )

        user = cursor.fetchone()
        cursor.close()

        if user:
            stored_password = user[2]
            password_ok = False

            if stored_password.startswith(("scrypt:", "pbkdf2:")):
                password_ok = check_password_hash(
                    stored_password,
                    password
                )
            else:
                password_ok = stored_password == password

                if password_ok:
                    new_password = generate_password_hash(password)

                    update_cursor = connection.cursor(buffered=True)

                    update_cursor.execute(
                        "UPDATE users SET password = %s WHERE id = %s",
                        (new_password, user[0])
                    )

                    connection.commit()
                    update_cursor.close()

            if password_ok:
                session["user_id"] = user[0]
                session["nickname"] = user[1]

                connection.close()

                return redirect("/")

        connection.close()

        return "아이디 또는 비밀번호가 틀렸습니다."

    return render_template("login.html")

@app.route("/logout")
def logout():
    session.pop("user_id", None)
    session.pop("nickname", None)
    session.pop("cart", None)
    session.pop("last_order_price", None)
    session.pop("last_order_calories", None)

    return redirect("/")

@app.route("/address", methods=["GET", "POST"])
def address():
    user_id = session.get("user_id")

    if not user_id:
        return redirect("/login")

    connection = get_db_connection()
    cursor = connection.cursor(buffered=True)

    if request.method == "POST":
        user_address = request.form["address"]

        cursor.execute("""
            UPDATE users
            SET address = %s
            WHERE id = %s
        """, (user_address, user_id))

        connection.commit()
        cursor.close()
        connection.close()

        return redirect("/address")

    cursor.execute("""
        SELECT address
        FROM users
        WHERE id = %s
    """, (user_id,))

    user = cursor.fetchone()

    cursor.close()
    connection.close()

    current_address = user[0] if user else None

    return render_template(
        "address.html",
        current_address=current_address
    )

if __name__ == "__main__":
    app.run(debug=True)
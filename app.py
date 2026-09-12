from flask import Flask, render_template, request, redirect, session
import mysql.connector
from dotenv import load_dotenv
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

    cursor.execute("""
        SELECT id, name, category, description
        FROM restaurants
    """)

    restaurants = cursor.fetchall()

    cursor.close()
    connection.close()

    return render_template("index.html", restaurants=restaurants)


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

    user_id = 1

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

    session["cart"] = {}

    return redirect("/order/complete")

@app.route("/order/complete")
def order_complete():
    return render_template("order_complete.html")

if __name__ == "__main__":
    app.run(debug=True)
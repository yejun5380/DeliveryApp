from flask import Flask, render_template, request, redirect, session
import mysql.connector
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash
import requests
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
        database=os.getenv("DB_NAME"),
    )
    return connection


@app.route("/")
def home():
    connection = get_db_connection()
    cursor = connection.cursor()

    search = request.args.get("search", "")

    if search:
        cursor.execute(
            """
            SELECT DISTINCT r.id, r.name, r.category, r.description
            FROM restaurants r
            LEFT JOIN menus m ON r.id = m.restaurant_id
            WHERE r.name LIKE %s
               OR m.name LIKE %s
        """,
            (f"%{search}%", f"%{search}%"),
        )
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
        "index.html", restaurants=restaurants, nickname=nickname, search=search
    )


@app.route("/restaurant/<int:restaurant_id>")
def restaurant_detail(restaurant_id):
    connection = get_db_connection()
    cursor = connection.cursor()

    cursor.execute(
        """
        SELECT id, name, category, description
        FROM restaurants
        WHERE id = %s
    """,
        (restaurant_id,),
    )

    restaurant = cursor.fetchone()

    cursor.execute(
        """
        SELECT id, name, price, calories, description
        FROM menus
        WHERE restaurant_id = %s
    """,
        (restaurant_id,),
    )

    menus = cursor.fetchall()

    cursor.close()
    connection.close()

    return render_template("restaurant.html", restaurant=restaurant, menus=menus)


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
        cursor.execute(
            """
            SELECT id, name, price, calories
            FROM menus
            WHERE id = %s
        """,
            (menu_id,),
        )

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
    user_id = session.get("user_id")

    if not user_id:
        return redirect("/login")

    cart = session.get("cart", {})

    if not cart:
        return redirect("/cart")

    connection = get_db_connection()
    cursor = connection.cursor()

    try:
        # 회원 배달 주소 조회
        cursor.execute("SELECT address FROM users WHERE id = %s", (user_id,))
        user = cursor.fetchone()

        if not user or not user[0]:
            return redirect("/address")

        delivery_address = user[0]

        # 장바구니 메뉴 및 음식점 정보 조회
        total_price = 0
        total_calories = 0
        restaurant_addresses = set()
        order_items = []

        for menu_id, quantity in cart.items():
            cursor.execute(
                """
                SELECT m.price, m.calories, r.name, r.address
                FROM menus m
                JOIN restaurants r ON m.restaurant_id = r.id
                WHERE m.id = %s
            """,
                (menu_id,),
            )

            menu = cursor.fetchone()

            if not menu:
                return "존재하지 않는 메뉴가 장바구니에 있습니다.", 400

            price, calories, restaurant_name, restaurant_address = menu

            if not restaurant_address:
                return f"{restaurant_name}: 음식점 주소가 없습니다.", 400

            quantity = int(quantity)

            if quantity <= 0:
                return "잘못된 주문 수량입니다.", 400

            total_price += price * quantity
            total_calories += calories * quantity

            restaurant_addresses.add((restaurant_name, restaurant_address))

            order_items.append((menu_id, quantity, price, calories))

        kakao_api_key = os.getenv("KAKAO_REST_API_KEY")

        if not kakao_api_key:
            return "카카오 REST API 키가 설정되지 않았습니다.", 503

        headers = {"Authorization": f"KakaoAK {kakao_api_key}"}

        def address_to_coords(address):
            response = requests.get(
                "https://dapi.kakao.com/v2/local/search/address.json",
                headers=headers,
                params={"query": address},
                timeout=10,
            )
            response.raise_for_status()

            documents = response.json().get("documents", [])

            if not documents:
                return None

            return (documents[0]["x"], documents[0]["y"])

        # 배달 주소 좌표 조회
        destination = address_to_coords(delivery_address)

        if not destination:
            return "배달 주소의 위치를 확인할 수 없습니다.", 400

        MAX_DELIVERY_DISTANCE = 5000

        # 장바구니에 포함된 모든 음식점 검사
        for restaurant_name, restaurant_address in sorted(restaurant_addresses):
            origin = address_to_coords(restaurant_address)

            if not origin:
                return f"{restaurant_name}: 음식점 위치를 확인할 수 없습니다.", 400

            response = requests.get(
                "https://apis-navi.kakaomobility.com/v1/directions",
                headers=headers,
                params={
                    "origin": f"{origin[0]},{origin[1]}",
                    "destination": f"{destination[0]},{destination[1]}",
                    "priority": "DISTANCE",
                },
                timeout=10,
            )
            response.raise_for_status()

            data = response.json()
            routes = data.get("routes", [])

            if not routes or routes[0].get("result_code") != 0:
                return f"{restaurant_name}: 배달 경로를 찾을 수 없습니다.", 400

            distance = routes[0]["summary"]["distance"]

            if distance > MAX_DELIVERY_DISTANCE:
                distance_km = distance / 1000

                return (
                    f"{restaurant_name}은(는) 배달 가능 거리 5km를 초과했습니다. "
                    f"실제 도로 거리: {distance_km:.2f}km. "
                    "장바구니에서 해당 메뉴를 삭제하거나 배달 주소를 변경해 주세요.",
                    400,
                )

        # 모든 음식점이 5km 이내일 때만 주문 저장
        cursor.execute(
            """
            INSERT INTO orders
            (user_id, total_price, total_calories, delivery_address)
            VALUES (%s, %s, %s, %s)
        """,
            (user_id, total_price, total_calories, delivery_address),
        )

        order_id = cursor.lastrowid

        for menu_id, quantity, price, calories in order_items:
            cursor.execute(
                """
                INSERT INTO order_items
                (order_id, menu_id, quantity, price, calories)
                VALUES (%s, %s, %s, %s, %s)
            """,
                (order_id, menu_id, quantity, price, calories),
            )

        connection.commit()

        session["last_order_price"] = total_price
        session["last_order_calories"] = total_calories
        session["cart"] = {}

        return redirect("/order/complete")

    except (requests.RequestException, ValueError, KeyError, TypeError) as error:
        connection.rollback()
        app.logger.warning("주문 거리 검증 실패: %s", error)
        return "배달 거리 확인 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.", 503

    except Exception:
        connection.rollback()
        app.logger.exception("주문 처리 실패")
        return "주문 처리 중 오류가 발생했습니다.", 500

    finally:
        cursor.close()
        connection.close()


@app.route("/order/complete")
def order_complete():
    if not session.get("user_id"):
        return redirect("/login")

    saved_price = session.get("last_order_price")
    saved_calories = session.get("last_order_calories")

    if saved_price is None or saved_calories is None:
        return redirect("/orders")

    return render_template(
        "order_complete.html", saved_price=saved_price, saved_calories=saved_calories
    )


@app.route("/orders")
def orders():
    connection = get_db_connection()
    cursor = connection.cursor()

    user_id = session.get("user_id")

    if not user_id:
        return redirect("/login")

    cursor.execute(
        """
        SELECT id, order_date, total_price, total_calories
        FROM orders
        WHERE user_id = %s
        ORDER BY order_date DESC
    """,
        (user_id,),
    )

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

    cursor.execute(
        """
        SELECT id, order_date, total_price, total_calories, delivery_address
        FROM orders
        WHERE id = %s AND user_id = %s
    """,
        (order_id, user_id),
    )

    order = cursor.fetchone()

    if not order:
        cursor.close()
        connection.close()
        return redirect("/orders")

    cursor.execute(
        """
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
    """,
        (order_id,),
    )

    order_items = cursor.fetchall()

    cursor.close()
    connection.close()

    return render_template("order_detail.html", order=order, order_items=order_items)


@app.route("/saving")
def saving():
    connection = get_db_connection()
    cursor = connection.cursor()

    user_id = session.get("user_id")

    if not user_id:
        cursor.close()
        connection.close()
        return redirect("/login")

    cursor.execute(
        """
        SELECT
            COUNT(*),
            COALESCE(SUM(total_price), 0),
            COALESCE(SUM(total_calories), 0)
        FROM orders
        WHERE user_id = %s
    """,
        (user_id,),
    )

    saving_data = cursor.fetchone()

    cursor.close()
    connection.close()

    return render_template("saving.html", saving_data=saving_data)


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "GET":
        return render_template("signup.html")

    username = request.form["username"]
    password = request.form["password"]
    nickname = request.form["nickname"]

    connection = get_db_connection()
    cursor = connection.cursor(buffered=True)

    cursor.execute("SELECT id FROM users WHERE username = %s", (username,))

    existing_user = cursor.fetchone()

    if existing_user:
        cursor.close()
        connection.close()
        return "이미 사용 중인 아이디입니다."

    hashed_password = generate_password_hash(password)

    cursor.execute(
        """
        INSERT INTO users (username, password, nickname)
        VALUES (%s, %s, %s)
    """,
        (username, hashed_password, nickname),
    )

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
            "SELECT id, nickname, password FROM users WHERE username = %s", (username,)
        )

        user = cursor.fetchone()
        cursor.close()

        if user:
            stored_password = user[2]
            password_ok = False

            if stored_password.startswith(("scrypt:", "pbkdf2:")):
                password_ok = check_password_hash(stored_password, password)
            else:
                password_ok = stored_password == password

                if password_ok:
                    new_password = generate_password_hash(password)

                    update_cursor = connection.cursor(buffered=True)

                    update_cursor.execute(
                        "UPDATE users SET password = %s WHERE id = %s",
                        (new_password, user[0]),
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

        cursor.execute(
            """
            UPDATE users
            SET address = %s
            WHERE id = %s
        """,
            (user_address, user_id),
        )

        connection.commit()
        cursor.close()
        connection.close()

        return redirect("/address")

    cursor.execute(
        """
        SELECT address
        FROM users
        WHERE id = %s
    """,
        (user_id,),
    )

    user = cursor.fetchone()

    cursor.close()
    connection.close()

    current_address = user[0] if user else None

    return render_template("address.html", current_address=current_address)


@app.route("/delivery/<int:order_id>")
def delivery_status(order_id):
    user_id = session.get("user_id")

    if not user_id:
        return redirect("/login")

    connection = get_db_connection()
    cursor = connection.cursor()

    cursor.execute(
        """
        SELECT id, order_date, delivery_address
        FROM orders
        WHERE id = %s AND user_id = %s
    """,
        (order_id, user_id),
    )

    order = cursor.fetchone()

    if not order:
        cursor.close()
        connection.close()
        return redirect("/orders")

    cursor.execute(
        """
        SELECT DISTINCT r.name, r.address
        FROM order_items oi
        JOIN menus m ON oi.menu_id = m.id
        JOIN restaurants r ON m.restaurant_id = r.id
        WHERE oi.order_id = %s
          AND r.address IS NOT NULL
          AND TRIM(r.address) <> ''
        ORDER BY r.name
    """,
        (order_id,),
    )

    restaurants = cursor.fetchall()

    cursor.close()
    connection.close()

    kakao_javascript_key = os.getenv("KAKAO_JAVASCRIPT_KEY")
    kakao_rest_api_key = os.getenv("KAKAO_REST_API_KEY")

    road_path = []
    road_distance = None
    road_duration = None
    route_error = None

    def address_to_coords(address):
        url = "https://dapi.kakao.com/v2/local/search/address.json"

        response = requests.get(
            url,
            headers={"Authorization": f"KakaoAK {kakao_rest_api_key}"},
            params={"query": address},
            timeout=10,
        )
        response.raise_for_status()

        documents = response.json().get("documents", [])

        if not documents:
            return None

        return {"x": documents[0]["x"], "y": documents[0]["y"]}

    if not kakao_rest_api_key:
        route_error = "카카오 REST API 키가 설정되지 않았습니다."

    elif not order[2]:
        route_error = "배달 주소가 등록되지 않았습니다."

    elif not restaurants:
        route_error = "음식점 주소가 등록되지 않았습니다."

    else:
        try:
            # 현재는 첫 번째 음식점에서 출발
            restaurant_address = restaurants[0][1]
            delivery_address = order[2]

            origin = address_to_coords(restaurant_address)
            destination = address_to_coords(delivery_address)

            if not origin or not destination:
                route_error = "주소를 좌표로 변환하지 못했습니다."

            else:
                directions_url = "https://apis-navi.kakaomobility.com/v1/directions"

                response = requests.get(
                    directions_url,
                    headers={"Authorization": f"KakaoAK {kakao_rest_api_key}"},
                    params={
                        "origin": f"{origin['x']},{origin['y']}",
                        "destination": (f"{destination['x']},{destination['y']}"),
                        "priority": "DISTANCE",
                    },
                    timeout=10,
                )

                response.raise_for_status()
                data = response.json()

                routes = data.get("routes", [])

                if routes and routes[0].get("result_code") == 0:
                    route = routes[0]

                    road_distance = route["summary"]["distance"]
                    road_duration = route["summary"]["duration"]

                    for section in route.get("sections", []):
                        for road in section.get("roads", []):
                            vertices = road.get("vertexes", [])

                            for i in range(0, len(vertices) - 1, 2):
                                road_path.append(
                                    {"lng": vertices[i], "lat": vertices[i + 1]}
                                )

                    if not road_path:
                        route_error = "도로 경로 좌표가 없습니다."

                else:
                    route_error = "길찾기 가능한 경로를 찾지 못했습니다."

        except requests.RequestException as error:
            app.logger.warning("길찾기 API 요청 실패: %s", error)
            route_error = "길찾기 API 요청에 실패했습니다."

        except (KeyError, ValueError, TypeError) as error:
            app.logger.warning("길찾기 응답 처리 실패: %s", error)
            route_error = "길찾기 API 응답을 처리하지 못했습니다."

    return render_template(
        "delivery_status.html",
        order=order,
        restaurants=restaurants,
        kakao_javascript_key=kakao_javascript_key,
        road_path=road_path,
        road_distance=road_distance,
        road_duration=road_duration,
        route_error=route_error,
    )


if __name__ == "__main__":
    app.run(debug=True)

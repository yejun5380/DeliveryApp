from flask import Flask, render_template, request, redirect, session, jsonify
import mysql.connector
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash
import os
import json
import secrets
import hashlib
from delivery import DeliveryError, inspect_delivery, time_scale
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from settings import distance_policy
from display_names import (load_display_catalog, public_branch, public_route,
                           public_snapshot, virtual_place_name)
from branches import (mapping_for, search_places, save_places, load_branch, branch_digest,
                      address_context, validate_grant, split_cart_key)

app = Flask(__name__)
load_dotenv()
app.secret_key = os.getenv("FLASK_SECRET_KEY") or secrets.token_hex(32)


@app.context_processor
def shared_settings():
    return {"distance_policy": distance_policy()}


@app.errorhandler(mysql.connector.Error)
def database_unavailable(error):
    app.logger.error("DB 요청 실패 (연결 정보와 상세 예외 생략)")
    if request.path.endswith("/branches") or request.path == "/cart/delivery-check":
        return jsonify(message="DB 연결 또는 지점 마이그레이션 상태를 확인해 주세요."), 503
    return "DB 연결 또는 지점 마이그레이션 상태를 확인해 주세요.", 503


def get_db_connection():
    connection = mysql.connector.connect(
        host=os.getenv("DB_HOST"),
        port=int(os.getenv("DB_PORT", "3306")),
        connection_timeout=5,
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
        SELECT id, name, category, description, image
        FROM restaurants
        WHERE id = %s
    """,
        (restaurant_id,),
    )

    restaurant = cursor.fetchone()

    cursor.execute(
        """
        SELECT id, name, price, calories, description, image
        FROM menus
        WHERE restaurant_id = %s
    """,
        (restaurant_id,),
    )

    menus = cursor.fetchall()

    cursor.close()
    connection.close()

    if not restaurant:
        return "음식점을 찾을 수 없습니다.", 404
    return render_template("restaurant.html", restaurant=restaurant, menus=menus, reselect_key=request.args.get("reselect", ""))


def selection_signer():
    return URLSafeTimedSerializer(app.secret_key, salt="delivery-branch-selection-v1")


def member_address(cursor, user_id, lock=False):
    cursor.execute("SELECT address FROM users WHERE id=%s" + (" FOR UPDATE" if lock else ""), (user_id,))
    row = cursor.fetchone()
    if not row or not row[0]:
        raise DeliveryError("배달 주소를 먼저 등록해 주세요.")
    return row[0]


@app.route("/restaurant/<int:restaurant_id>/branches")
def nearby_branches(restaurant_id):
    user_id = session.get("user_id")
    if not user_id:
        return jsonify(message="로그인이 필요합니다."), 401
    try:
        page = int(request.args.get("page", "1"))
        if not 1 <= page <= 45:
            raise ValueError()
    except ValueError:
        return jsonify(message="잘못된 검색 페이지입니다."), 400
    connection = get_db_connection()
    cursor = connection.cursor()
    try:
        address = member_address(cursor, user_id)
        brand, aliases = mapping_for(cursor, restaurant_id)
        connection.rollback()  # 외부 API 대기 중 DB 잠금을 유지하지 않습니다.
        result = search_places(address, brand, aliases, page)
        if member_address(cursor, user_id, lock=True) != address:
            raise DeliveryError("배달 주소가 변경되었습니다. 다시 검색해 주세요.")
        current_brand, current_aliases = mapping_for(cursor, restaurant_id)
        if (current_brand, current_aliases) != (brand, aliases):
            raise DeliveryError("브랜드 설정이 변경되었습니다. 다시 검색해 주세요.")
        places = save_places(cursor, restaurant_id, result["places"])
        catalog = load_display_catalog(cursor)
        public_places = []
        for place in places:
            branch = load_branch(cursor, place["branch_id"], restaurant_id)
            place["selection_token"] = selection_signer().dumps({
                "u": user_id, "r": restaurant_id, "b": branch["branch_id"],
                "a": address_context(user_id, address), "d": branch_digest(branch)})
            display = public_branch(branch, catalog)
            public_places.append({**{k: v for k, v in place.items() if k != "place_name"},
                                  "display_name": display["display_name"]})
        connection.commit()
        response = jsonify(places=public_places, is_end=result["is_end"], page=page, **distance_policy())
        response.headers["Cache-Control"] = "no-store"
        return response
    except DeliveryError as error:
        connection.rollback()
        return jsonify(message=str(error)), 422
    finally:
        cursor.close()
        connection.close()


def selected_branch(cursor, restaurant_id, user_id, address, token):
    try:
        payload = selection_signer().loads(token, max_age=900)
        if payload["u"] != user_id or payload["r"] != restaurant_id:
            raise ValueError()
        branch = load_branch(cursor, payload["b"], restaurant_id, lock=True)
        validate_grant(branch, payload, user_id, address)
        return branch, {"a": payload["a"], "d": payload["d"]}
    except (BadSignature, SignatureExpired, KeyError, TypeError, ValueError):
        raise DeliveryError("선택 정보가 잘못되었거나 만료되었습니다. 지점을 다시 검색해 주세요.") from None


def cart_branch(cursor, menu_id, branch_id, user_id, address):
    cursor.execute("SELECT restaurant_id FROM menus WHERE id=%s", (menu_id,))
    menu = cursor.fetchone()
    if not menu:
        raise DeliveryError("존재하지 않는 메뉴입니다.")
    if branch_id is None:
        raise DeliveryError("기존 장바구니 항목의 지점을 다시 선택해 주세요.")
    branch = load_branch(cursor, branch_id, menu[0], lock=True)
    return validate_grant(branch, session.get("branch_grants", {}).get(str(branch_id)), user_id, address)


def save_cart(cart, grants=None):
    used = {str(split_cart_key(k)[1]) for k in cart if ":" in k}
    grants = session.get("branch_grants", {}) if grants is None else grants
    changes = dict(cart=cart, branch_grants={k: v for k, v in grants.items() if k in used},
                   order_token=secrets.token_hex(32))
    prospective = dict(session, **changes)
    # Flask's existing signed-cookie cart must not silently exceed browser limits.
    serializer = app.session_interface.get_signing_serializer(app)
    new_size = len(serializer.dumps(prospective).encode())
    if new_size > 3500 and new_size > len(serializer.dumps(dict(session)).encode()):
        raise DeliveryError("장바구니 저장 공간이 부족합니다. 기존 항목을 유지했으니 일부 항목을 정리해 주세요.")
    session.update(changes)


@app.route("/cart/add", methods=["POST"])
@app.route("/cart/reselect", methods=["POST"])
def add_cart():
    user_id = session.get("user_id")
    if not user_id:
        return redirect("/login")
    cart = dict(session.get("cart", {}))
    grants = dict(session.get("branch_grants", {}))
    connection = get_db_connection()
    cursor = connection.cursor()
    try:
        address = member_address(cursor, user_id, lock=True)
        old_key = request.form.get("cart_key", "")
        reselect = request.path == "/cart/reselect"
        if old_key:
            if old_key not in cart:
                raise DeliveryError("장바구니 항목을 찾을 수 없습니다.")
            menu_id, old_branch_id = split_cart_key(old_key)
        else:
            menu_id, _ = split_cart_key(request.form.get("menu_id", ""))
            old_branch_id = None
        if reselect or not old_key:
            cursor.execute("SELECT restaurant_id FROM menus WHERE id=%s", (menu_id,))
            menu = cursor.fetchone()
            if not menu:
                raise DeliveryError("존재하지 않는 메뉴입니다.")
            branch, grant = selected_branch(cursor, menu[0], user_id, address, request.form.get("selection_token", ""))
            grants[str(branch["branch_id"])] = grant
        else:
            branch = cart_branch(cursor, menu_id, old_branch_id, user_id, address)
        key = f'{menu_id}:{branch["branch_id"]}'
        if reselect:
            if not old_key:
                raise DeliveryError("변경할 장바구니 항목이 없습니다.")
            quantity = cart.pop(old_key)
        else:
            quantity = 1
        cart[key] = cart.get(key, 0) + quantity
        save_cart(cart, grants)
        return redirect("/cart")
    except DeliveryError as error:
        return app.response_class(str(error), status=422, mimetype="text/plain")
    finally:
        connection.rollback()
        cursor.close()
        connection.close()


@app.route("/cart")
def cart():
    user_id = session.get("user_id")
    if not user_id:
        return redirect("/login")
    connection = get_db_connection()
    cursor = connection.cursor()
    menus = []
    try:
        try:
            address = member_address(cursor, user_id)
        except DeliveryError:
            address = ""
        for key, quantity in session.get("cart", {}).items():
            menu_id, branch_id = split_cart_key(key)
            cursor.execute("SELECT id,name,price,calories,restaurant_id FROM menus WHERE id=%s", (menu_id,))
            menu = cursor.fetchone()
            if not menu:
                continue
            branch, error = None, None
            try:
                branch = cart_branch(cursor, menu_id, branch_id, user_id, address)
            except DeliveryError as problem:
                error = str(problem)
            menus.append((menu, quantity, key, branch, error))
        catalog = load_display_catalog(cursor) if menus else []
        menus = [(menu, quantity, key, public_branch(branch, catalog) if branch else None, error)
                 for menu, quantity, key, branch, error in menus]
    finally:
        connection.rollback()
        cursor.close()
        connection.close()
    session.setdefault("order_token", secrets.token_hex(32))
    return render_template("cart.html", menus=menus, order_token=session["order_token"])


@app.route("/cart/minus", methods=["POST"])
@app.route("/cart/delete", methods=["POST"])
def cart_change():
    if not session.get("user_id"):
        return redirect("/login")
    key = request.form.get("cart_key", request.form.get("menu_id", ""))
    cart = dict(session.get("cart", {}))
    if key in cart:
        if request.path == "/cart/delete" or cart[key] <= 1:
            del cart[key]
        else:
            cart[key] -= 1
        save_cart(cart)
    return redirect("/cart")


def checkout_data(cursor, user_id, cart):
    address = member_address(cursor, user_id, lock=True)
    if not isinstance(cart, dict) or not cart:
        raise DeliveryError("장바구니가 비어 있습니다.")
    items, branches = [], {}
    price_total = calories_total = 0
    for key, quantity in sorted(cart.items()):
        if type(quantity) is not int or quantity <= 0:
            raise DeliveryError("잘못된 주문 수량입니다.")
        menu_id, branch_id = split_cart_key(key)
        branch = cart_branch(cursor, menu_id, branch_id, user_id, address)
        cursor.execute("SELECT price,calories FROM menus WHERE id=%s", (menu_id,))
        price, calories = cursor.fetchone()
        branches[branch_id] = branch
        items.append((menu_id, quantity, price, calories, branch_id))
        price_total += price * quantity
        calories_total += calories * quantity
    restaurants = [branches[k] for k in sorted(branches)]
    fingerprint = hashlib.sha256(json.dumps([address, items, restaurants, distance_policy()], ensure_ascii=False, default=str, sort_keys=True).encode()).hexdigest()
    return address, items, restaurants, price_total, calories_total, fingerprint


@app.route("/cart/delivery-check", methods=["POST"])
def delivery_check():
    if not session.get("user_id"):
        return jsonify(message="로그인이 필요합니다."), 401
    connection = get_db_connection()
    cursor = connection.cursor()
    try:
        address, _, restaurants, _, _, fingerprint = checkout_data(cursor, session["user_id"], session.get("cart"))
        results = inspect_delivery(address, restaurants)
        catalog = load_display_catalog(cursor)
        public = [public_route({k: v for k, v in row.items() if k != "path"}, catalog) for row in results]
        state = "available" if all(r["status"] == "available" for r in results) else ("unavailable" if any(r["status"] == "unavailable" for r in results) else "unknown")
        response = jsonify(status=state, restaurants=public, fingerprint=fingerprint, **distance_policy())
        response.headers["Cache-Control"] = "no-store"
        return response
    except DeliveryError as error:
        return jsonify(status="unknown", message=str(error)), 422
    except Exception:
        app.logger.error("배달 사전 검사 처리 실패 (상세 예외 생략)")
        return jsonify(status="unknown", message="배달 확인 처리에 실패했습니다."), 503
    finally:
        connection.rollback()
        cursor.close()
        connection.close()


@app.route("/order", methods=["POST"])
def order():
    user_id = session.get("user_id")
    if not user_id:
        return redirect("/login")
    token = request.form.get("order_token", "")
    if not token or not secrets.compare_digest(token, session.get("order_token", "")):
        return "장바구니를 새로 열어 주문해 주세요.", 409
    connection = get_db_connection()
    cursor = connection.cursor()
    try:
        # 사용자 행 잠금으로 중복 요청을 직렬화합니다. 고유 토큰으로 재전송도 차단합니다.
        member_address(cursor, user_id, lock=True)
        cursor.execute("SELECT id FROM orders WHERE request_token=%s AND user_id=%s", (token, user_id))
        existing = cursor.fetchone()
        if existing:
            return redirect(f"/orders/{existing[0]}")
        address, items, restaurants, total_price, total_calories, fingerprint = checkout_data(cursor, user_id, session.get("cart"))
        if request.form.get("fingerprint") != fingerprint:
            return "주소 또는 장바구니가 변경되었습니다. 장바구니에서 다시 확인해 주세요.", 409
        results = inspect_delivery(address, restaurants)  # 사전 검사 결과와 별개로 반드시 재조회
        if any(r["status"] != "available" for r in results):
            catalog = load_display_catalog(cursor)
            results = [public_route(result, catalog) for result in results]
            messages = [f'{r["name"]}: ' + (f'실제 도로 거리 {r["distance"]:,.0f}m, {distance_policy()["limit_label"]} 초과' if r["status"] == "unavailable" else r.get("message", "확인 불가")) for r in results if r["status"] != "available"]
            return app.response_class(" / ".join(messages), status=422, mimetype="text/plain")
        representative = max(results, key=lambda r: r["duration"])
        snapshot = dict(version=2, limit_meters=distance_policy()["limit_meters"], routes=[{k: v for k, v in row.items() if k != "path"} for row in results], representative=representative["name"], path=representative["path"], duration=representative["duration"], scale=time_scale(), preparation=600)
        cursor.execute("INSERT INTO orders (user_id,total_price,total_calories,delivery_address,delivery_snapshot,request_token) VALUES (%s,%s,%s,%s,%s,%s)", (user_id,total_price,total_calories,address,json.dumps(snapshot, ensure_ascii=False),token))
        order_id = cursor.lastrowid
        order_branch_ids = {}
        for result in results:
            branch = result["branch"]
            cursor.execute("""INSERT INTO order_restaurants
                (order_id,restaurant_id,branch_id,virtual_name,brand_name,place_id,place_name,
                 road_address,lot_address,lng,lat,road_distance,road_duration,route_snapshot)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (order_id, branch["restaurant_id"], branch["branch_id"], branch["virtual_name"],
                 branch["brand_name"], branch["place_id"], branch["place_name"], branch["road_address"],
                 branch["lot_address"], branch["lng"], branch["lat"], result["distance"],
                 result["duration"], json.dumps(result["path"])))
            order_branch_ids[branch["branch_id"]] = cursor.lastrowid
        for menu_id, quantity, price, calories, branch_id in items:
            cursor.execute("INSERT INTO order_items (order_id,menu_id,quantity,price,calories,order_restaurant_id) VALUES (%s,%s,%s,%s,%s,%s)",
                           (order_id, menu_id, quantity, price, calories, order_branch_ids[branch_id]))
        connection.commit()
        session["last_order_price"] = total_price
        session["last_order_calories"] = total_calories
        session["cart"] = {}
        session.pop("branch_grants", None)
        return redirect("/order/complete")
    except DeliveryError as error:
        connection.rollback()
        return str(error), 422
    except Exception:
        connection.rollback()
        app.logger.error("주문 처리 실패 (상세 예외 및 인증 정보는 기록하지 않음)")
        return "주문 처리 중 오류가 발생했습니다. DB 마이그레이션 및 설정을 확인해 주세요.", 500
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
            COALESCE(obr.virtual_name,r.name),
            obr.place_name, COALESCE(NULLIF(obr.road_address,''),obr.lot_address), obr.brand_name, obr.place_id
        FROM order_items oi
        JOIN menus m ON oi.menu_id = m.id
        JOIN restaurants r ON m.restaurant_id = r.id
        LEFT JOIN order_restaurants obr ON obr.id=oi.order_restaurant_id AND obr.order_id=oi.order_id
        WHERE oi.order_id = %s
    """,
        (order_id,),
    )

    order_items = cursor.fetchall()
    catalog = load_display_catalog(cursor)
    order_items = [tuple(item[:5]) + ((virtual_place_name(item[5], item[4],
                    [item[7]] if len(item) > 7 and item[7] else (), catalog,
                    item[8] if len(item) > 8 else None), item[6]) if len(item) > 5 and item[5] else (None, None))
                   for item in order_items]

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
                if session.get("user_id") != user[0]:
                    session.pop("cart", None)
                    session.pop("branch_grants", None)
                    session.pop("order_token", None)
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
    session.pop("branch_grants", None)
    session.pop("order_token", None)
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
    try:
        cursor.execute("SELECT id,order_date,delivery_address,delivery_snapshot,TIMESTAMPDIFF(MICROSECOND,order_date,NOW(6))/1000000 FROM orders WHERE id=%s AND user_id=%s", (order_id,user_id))
        order = cursor.fetchone()
        catalog = load_display_catalog(cursor) if order and order[3] else []
    finally:
        cursor.close()
        connection.close()
    if not order:
        return redirect("/orders")
    snapshot = None
    error = None
    try:
        if order[3]:
            snapshot = json.loads(order[3])
            from delivery import positive
            for key in ("duration", "scale", "preparation"):
                positive(snapshot[key])
            if len(snapshot["path"]) < 2:
                raise ValueError()
            snapshot = public_snapshot(snapshot, catalog)
        else:
            error = "기존 주문에는 당시 도로 소요시간이 없어 진행 상태를 복원할 수 없습니다. 주문내역은 그대로 유지됩니다."
    except (ValueError, TypeError, KeyError, DeliveryError):
        snapshot = None
        error = "저장된 배달 정보를 읽을 수 없습니다."
    return render_template("delivery_status.html", order=order, snapshot=snapshot, route_error=error, elapsed=max(0,float(order[4] or 0)), kakao_javascript_key=os.getenv("KAKAO_JAVASCRIPT_KEY"))


if __name__ == "__main__":
    app.run(debug=os.getenv("FLASK_DEBUG") == "1")

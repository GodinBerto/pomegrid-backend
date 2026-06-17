from Flask import flask

auth = Blueprint("auth", __name__)


@auth.route("/me", methods=["GET"])
@jwt_required()
def auth_me():
    user_id = get_authenticated_user_id()
    if user_id is None:
        return jsonify(envelope(None, "Invalid token identity", 401, False)), 401
    conn, cursor = db_connection()
    cursor.execute(
        """
        SELECT id, username, email, full_name, phone, user_type, role, status,
               address, is_admin, is_active, is_verified, accepted_policy,
               date_of_birth, verified_at
        FROM Users
        WHERE id = ?
        """,
        (user_id,),
    )
    row = cursor.fetchone()
    conn.close()

    if not row:
        return jsonify({"data": None}), 404

    payload = _build_auth_user_payload(row)
    return jsonify({"data": payload}), 200
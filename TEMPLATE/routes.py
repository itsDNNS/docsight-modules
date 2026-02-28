"""Example module routes.

This Blueprint is auto-loaded by DOCSight's module loader.
The variable must be named ``bp`` or ``blueprint``.
"""

from flask import Blueprint, jsonify

bp = Blueprint("example_bp", __name__)


@bp.route("/api/example/hello")
def api_hello():
    """Example API endpoint."""
    return jsonify({"message": "Hello from the example module!"})

# ------------------------------------------------------------------------------
# MAIN
# ------------------------------------------------------------------------------
# Entry point for the Flask web application.
# Run with: python -m web.app
# ------------------------------------------------------------------------------
from web import create_app

app = create_app()


if __name__ == "__main__":
    print("Starting Data Automation UI at http://localhost:5000")
    app.run(debug=False, use_reloader=False, host="0.0.0.0", port=5000)
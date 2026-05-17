# ------------------------------------------------------------------------------
# WEB APP
# ------------------------------------------------------------------------------
# Flask web application for data automation UI.
# Uses plain SQLAlchemy 2.0.
# ------------------------------------------------------------------------------
from flask import Flask
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker


# Create engine and session factory at module level
engine = None
SessionLocal = None


def create_app(config_name=None):
    """Application factory for Flask app."""
    global engine, SessionLocal

    app = Flask(__name__)

    # App configuration
    app.config["SECRET_KEY"] = "dev-secret-key-change-in-production"

    # Initialize SQLAlchemy
    from web import models
    engine = create_engine("sqlite:///data/run_history.db", echo=False)
    SessionLocal = sessionmaker(bind=engine)

    # Create tables
    models.Base.metadata.create_all(engine)

    # Clean up orphaned running jobs from previous session
    import threading
    import time
    from datetime import datetime, timedelta
    from scheduler import HEARTBEAT_FILE

    def cleanup_stale_runs():
        try:
            engine_local = create_engine("sqlite:///data/run_history.db", echo=False, connect_args={"check_same_thread": False})
            SessionLocal = sessionmaker(bind=engine_local)
            sess = SessionLocal()
            try:
                from web.models import Run
                # Find jobs that have been 'running' for more than 5 minutes (orphaned from crashed sessions)
                cutoff = datetime.utcnow() - timedelta(minutes=5)
                stale_runs = sess.query(Run).filter(
                    Run.status == "running",
                    Run.start_time < cutoff
                ).all()
                for run in stale_runs:
                    run.status = "failed"
                    run.end_time = datetime.utcnow()
                    run.error_message = "Job was stopped - previous session was terminated while job was running"
                if stale_runs:
                    sess.commit()
            finally:
                sess.close()
        except Exception:
            pass

    cleanup_thread = threading.Thread(target=cleanup_stale_runs, daemon=True)
    cleanup_thread.start()

    def write_heartbeat():
        while True:
            try:
                HEARTBEAT_FILE.write_text(str(time.time()), encoding="utf-8")
            except Exception:
                pass
            time.sleep(10)

    heartbeat_thread = threading.Thread(target=write_heartbeat, daemon=True)
    heartbeat_thread.start()

    # Register blueprints
    from web.routes import bp
    app.register_blueprint(bp)

    # Register Jinja2 filters for timezone
    from core.timezone import format_dt, get_timezone
    app.jinja_env.filters['tzformat'] = format_dt
    app.jinja_env.globals['app_timezone'] = get_timezone

    # Make all_configsdropdown available to all templates
    @app.context_processor
    def inject_all_configs():
        from core.config_loader import get_all_configs_with_jobs
        from flask import request
        all_configs = get_all_configs_with_jobs()
        return dict(all_configsdropdown=all_configs)

    # Make engine and Session available to routes
    @app.before_request
    def before_request():
        from flask import g
        g.session = SessionLocal()

    @app.teardown_appcontext
    def close_session(exception=None):
        from flask import g
        session = g.pop('session', None)
        if session is not None:
            session.close()

    return app
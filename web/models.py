# ------------------------------------------------------------------------------
# MODELS
# ------------------------------------------------------------------------------
# Database models for run history tracking.
# Uses SQLAlchemy 2.0 style (standalone, no Flask-SQLAlchemy).
# ------------------------------------------------------------------------------
from datetime import datetime
from sqlalchemy import String, Integer, Text, DateTime, Boolean
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base class for all models."""
    pass


class Run(Base):
    """Run history model."""
    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)  # pending, running, success, failed
    start_time: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    end_time: Mapped[datetime] = mapped_column(DateTime, nullable=True, default=None)
    rows_processed: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str] = mapped_column(Text, nullable=True, default=None)
    logs: Mapped[str] = mapped_column(Text, nullable=True, default=None)
    trigger_type: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")  # manual, scheduled

    def __repr__(self):
        return f"<Run {self.job_name} - {self.status}>"

    @property
    def duration(self):
        """Calculate duration in seconds."""
        if self.end_time and self.start_time:
            return (self.end_time - self.start_time).total_seconds()
        return None
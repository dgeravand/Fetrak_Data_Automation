# ------------------------------------------------------------------------------
# FORMS
# ------------------------------------------------------------------------------
# WTForms for job configuration editing.
# ------------------------------------------------------------------------------
from flask_wtf import FlaskForm
from wtforms import StringField, SelectField, TextAreaField, BooleanField, SubmitField
from wtforms.validators import DataRequired, Optional


class JobForm(FlaskForm):
    """Form for creating/editing jobs."""

    # Basic info
    name = StringField("Job Name", validators=[DataRequired()])
    active = BooleanField("Active")
    schedule = StringField("Schedule (Cron)", validators=[Optional()])

    # Source configuration
    source_type = SelectField(
        "Source Type",
        choices=[("sqlserver", "SQL Server"), ("clickhouse", "ClickHouse")],
        validators=[DataRequired()]
    )
    query = TextAreaField("SQL Query", validators=[Optional()])
    query_file = StringField("Query File Path", validators=[Optional()])

    # SharePoint configuration
    sp_library = StringField("SharePoint Library", validators=[DataRequired()])
    sp_folder = StringField("SharePoint Folder", validators=[DataRequired()])

    # File configuration
    file_name = StringField("File Name", validators=[DataRequired()])
    write_mode = SelectField(
        "Write Mode",
        choices=[("append", "Append"), ("replace", "Replace")],
        validators=[DataRequired()]
    )
    sheet_name = StringField("Sheet Name", validators=[DataRequired()])

    # Owners
    owners = StringField("Owners (comma-separated)", validators=[Optional()])

    # Actions
    submit = SubmitField("Save Job")
    cancel = SubmitField("Cancel")
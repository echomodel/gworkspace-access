"""CLI commands for Google Sheets operations."""

import json
import click

from gwsa.sdk import sheets as sdk_sheets
from .decorators import require_scopes


@click.group()
def sheets():
    """Commands for interacting with Google Sheets."""
    pass


@sheets.command('list')
@click.option('--max-results', type=int, default=25,
              help='Maximum number of spreadsheets to return (default 25).')
@click.option('--query', '-q', default=None,
              help='Search query to filter spreadsheets.')
@require_scopes('sheets-read')
def list_sheets(max_results, query):
    """Lists the user's Google Sheets."""
    try:
        result = sdk_sheets.list_spreadsheets(
            max_results=max_results, query=query
        )
        items = result.get("spreadsheets", [])

        if not items:
            click.echo("No Google Sheets found.")
        else:
            click.echo("Google Sheets:")
            for item in items:
                click.echo(f"- {item['title']} (ID: {item['id']})")

    except Exception as e:
        raise click.ClickException(f"An error occurred: {e}")


@sheets.command('create')
@click.argument('title')
@click.option('--folder-id', default=None,
              help='Drive folder ID to create the spreadsheet in.')
@click.option('--sheet-title', default=None,
              help='Title for the first sheet (tab).')
@require_scopes('sheets')
def create_sheet(title, folder_id, sheet_title):
    """Create a new Google Sheets spreadsheet."""
    try:
        result = sdk_sheets.create_spreadsheet(
            title=title, folder_id=folder_id, sheet_title=sheet_title
        )
        click.echo("Spreadsheet created successfully!")
        click.echo(f"  Title: {result['title']}")
        click.echo(f"  ID: {result['id']}")
        click.echo(f"  URL: {result['url']}")

    except Exception as e:
        raise click.ClickException(f"An error occurred: {e}")


@sheets.command('info')
@click.argument('spreadsheet_id')
@require_scopes('sheets-read')
def sheet_info(spreadsheet_id):
    """Show spreadsheet metadata — title, URL, and sheets (tabs)."""
    try:
        result = sdk_sheets.get_spreadsheet(spreadsheet_id)
        click.echo(json.dumps(result, indent=2))

    except Exception as e:
        raise click.ClickException(f"An error occurred: {e}")


@sheets.command('read')
@click.argument('spreadsheet_id')
@click.argument('range_name')
@require_scopes('sheets-read')
def read_sheet(spreadsheet_id, range_name):
    """Reads data from a specific sheet and range."""
    try:
        result = sdk_sheets.read_values(spreadsheet_id, range_name)
        values = result.get("values", [])

        if not values:
            click.echo(f"No data found in range '{range_name}'.")
        else:
            for row in values:
                click.echo('\t'.join(map(str, row)))

    except Exception as e:
        raise click.ClickException(f"An error occurred: {e}")


@sheets.command('tail')
@click.argument('spreadsheet_id')
@click.option('-n', 'n', type=int, default=10,
              help='Number of data rows to return (default 10).')
@click.option('--sheet', default=None,
              help='Sheet (tab) title. Defaults to the first tab.')
@click.option('--before-row', type=int, default=None,
              help='Cursor: return the N rows immediately above this row '
                   'number (exclusive). Use the "rows X-Y" footer of the '
                   'previous invocation; pass X to page older.')
@require_scopes('sheets-read')
def tail_sheet(spreadsheet_id, n, sheet, before_row):
    """Read the last N data rows without loading the whole sheet.

    Repeat with --before-row to page backwards (newest to oldest).
    """
    try:
        result = sdk_sheets.read_tail(
            spreadsheet_id, n=n, sheet=sheet, before_row=before_row,
            include_header=before_row is None,
        )

        header = result.get("header")
        values = result.get("values", [])
        if header:
            click.echo('\t'.join(map(str, header)))
        if not values:
            click.echo("(no data rows)")
        else:
            for row in values:
                click.echo('\t'.join(map(str, row)))
            footer = f"# rows {result['start_row']}-{result['end_row']}"
            if result.get("has_more"):
                footer += (f" — more above; use --before-row "
                           f"{result['start_row']}")
            click.echo(footer)

    except Exception as e:
        raise click.ClickException(f"An error occurred: {e}")


@sheets.command('update-cell')
@click.argument('spreadsheet_id')
@click.argument('range_name')
@click.argument('value')
@require_scopes('sheets')
def update_cell(spreadsheet_id, range_name, value):
    """Updates a specific cell with a new value."""
    try:
        sdk_sheets.update_values(
            spreadsheet_id, range_name, [[value]],
            value_input_option="RAW",
        )
        click.echo(f"Cell '{range_name}' updated successfully.")

    except Exception as e:
        raise click.ClickException(f"An error occurred: {e}")


@sheets.command('append')
@click.argument('spreadsheet_id')
@click.argument('row_json')
@click.option('--range', 'range_name', default='A1',
              help='A1-notation anchor locating the table to append to '
                   '(default "A1"). Use "Tab!A1" to target a tab.')
@click.option('--raw', is_flag=True, default=False,
              help='Store values verbatim instead of parsing them as if '
                   'typed in the UI.')
@require_scopes('sheets')
def append_row(spreadsheet_id, row_json, range_name, raw):
    """Append row(s) to a sheet.

    ROW_JSON is a JSON array — one row (e.g. '["a", "b", 3]') or a
    list of rows (e.g. '[["a", 1], ["b", 2]]').
    """
    try:
        parsed = json.loads(row_json)
        if not isinstance(parsed, list):
            raise click.ClickException(
                "ROW_JSON must be a JSON array (a row or a list of rows)."
            )
        values = parsed if parsed and isinstance(parsed[0], list) else [parsed]

        result = sdk_sheets.append_rows(
            spreadsheet_id, values, range_name=range_name,
            value_input_option="RAW" if raw else "USER_ENTERED",
        )
        click.echo(
            f"Appended {result['updated_rows']} row(s) "
            f"to {result['updated_range']}."
        )

    except json.JSONDecodeError as e:
        raise click.ClickException(f"Invalid JSON for ROW_JSON: {e}")
    except click.ClickException:
        raise
    except Exception as e:
        raise click.ClickException(f"An error occurred: {e}")


if __name__ == '__main__':
    sheets()

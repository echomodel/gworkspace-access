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


def _echo_json(result):
    click.echo(json.dumps(result, indent=2))


@sheets.command('batch-update')
@click.argument('spreadsheet_id')
@click.option('--requests-json', '-r', required=True,
              help='JSON array of Sheets API batchUpdate request objects.')
@click.option('--allow-destructive', is_flag=True, default=False,
              help='Required to apply a batch containing deleteSheet.')
@require_scopes('sheets')
def batch_update_sheet(spreadsheet_id, requests_json, allow_destructive):
    """Apply a raw Sheets API batchUpdate (the structural-editing primitive).

    REQUESTS-JSON is a JSON array of request objects, e.g.
    '[{"addSheet": {"properties": {"title": "Archive"}}}]'.
    The batch is atomic: if any request is invalid, none are applied.
    Prints the raw API response (including per-request replies).
    """
    try:
        requests = json.loads(requests_json)
        if not isinstance(requests, list):
            raise click.ClickException(
                "--requests-json must be a JSON array of request objects."
            )
        result = sdk_sheets.batch_update(
            spreadsheet_id, requests, allow_destructive=allow_destructive,
        )
        _echo_json(result)

    except json.JSONDecodeError as e:
        raise click.ClickException(f"Invalid JSON for --requests-json: {e}")
    except click.ClickException:
        raise
    except (sdk_sheets.DestructiveRequestError, ValueError) as e:
        raise click.ClickException(str(e))
    except Exception as e:
        raise click.ClickException(f"An error occurred: {e}")


@sheets.command('add-tab')
@click.argument('spreadsheet_id')
@click.argument('title')
@click.option('--index', type=int, default=None,
              help='0-based position among the tabs (default: last).')
@click.option('--rows', 'row_count', type=int, default=None,
              help='Initial row count (API default 1000).')
@click.option('--columns', 'column_count', type=int, default=None,
              help='Initial column count (API default 26).')
@require_scopes('sheets')
def add_tab(spreadsheet_id, title, index, row_count, column_count):
    """Add a sheet (tab) to an existing spreadsheet."""
    try:
        _echo_json(sdk_sheets.add_tab(
            spreadsheet_id, title, index=index,
            row_count=row_count, column_count=column_count,
        ))
    except Exception as e:
        raise click.ClickException(f"An error occurred: {e}")


@sheets.command('insert-rows')
@click.argument('spreadsheet_id')
@click.argument('start_row', type=int)
@click.option('--count', '-c', type=int, default=1,
              help='Number of rows to insert (default 1).')
@click.option('--sheet', default=None,
              help='Sheet (tab) title. Defaults to the first tab.')
@click.option('--inherit-from-before', is_flag=True, default=False,
              help='Copy formatting from the row above instead of below.')
@require_scopes('sheets')
def insert_rows(spreadsheet_id, start_row, count, sheet, inherit_from_before):
    """Insert empty rows at START_ROW (1-based), shifting rows down."""
    try:
        result = sdk_sheets.insert_rows(
            spreadsheet_id, start_row, count=count, sheet=sheet,
            inherit_from_before=inherit_from_before,
        )
        click.echo(
            f"Inserted {result['count']} row(s): "
            f"rows {result['start_row']}-{result['end_row']}."
        )
    except ValueError as e:
        raise click.ClickException(str(e))
    except Exception as e:
        raise click.ClickException(f"An error occurred: {e}")


@sheets.command('delete-rows')
@click.argument('spreadsheet_id')
@click.argument('start_row', type=int)
@click.option('--count', '-c', type=int, default=1,
              help='Number of rows to delete (default 1).')
@click.option('--sheet', default=None,
              help='Sheet (tab) title. Defaults to the first tab.')
@require_scopes('sheets')
def delete_rows(spreadsheet_id, start_row, count, sheet):
    """Delete COUNT rows starting at START_ROW (1-based), shifting rows up."""
    try:
        result = sdk_sheets.delete_rows(
            spreadsheet_id, start_row, count=count, sheet=sheet,
        )
        click.echo(
            f"Deleted {result['count']} row(s): "
            f"rows {result['start_row']}-{result['end_row']}."
        )
    except ValueError as e:
        raise click.ClickException(str(e))
    except Exception as e:
        raise click.ClickException(f"An error occurred: {e}")


@sheets.command('set-metadata')
@click.argument('spreadsheet_id')
@click.argument('key')
@click.argument('value', required=False)
@click.option('--sheet', default=None,
              help='Tag this tab (or, with --row/--column, a row/column of it).')
@click.option('--row', type=int, default=None, help='Tag this 1-based row.')
@click.option('--column', default=None, help='Tag this column (letter, e.g. C).')
@click.option('--visibility', type=click.Choice(['DOCUMENT', 'PROJECT']),
              default='DOCUMENT', show_default=True,
              help='DOCUMENT: any client with file access can find it.')
@require_scopes('sheets')
def set_metadata(spreadsheet_id, key, value, sheet, row, column, visibility):
    """Tag the spreadsheet, a tab, a row, or a column with KEY[=VALUE]
    developer metadata, discoverable later with find-metadata."""
    try:
        _echo_json(sdk_sheets.set_metadata(
            spreadsheet_id, key, value=value, sheet=sheet,
            row=row, column=column, visibility=visibility,
        ))
    except ValueError as e:
        raise click.ClickException(str(e))
    except Exception as e:
        raise click.ClickException(f"An error occurred: {e}")


@sheets.command('find-metadata')
@click.argument('spreadsheet_id')
@click.option('--key', default=None, help='Metadata key to match.')
@click.option('--value', default=None, help='Metadata value to match.')
@require_scopes('sheets-read')
def find_metadata(spreadsheet_id, key, value):
    """Find tabs/rows/columns tagged with developer metadata."""
    try:
        _echo_json(sdk_sheets.find_by_metadata(
            spreadsheet_id, key=key, value=value,
        ))
    except ValueError as e:
        raise click.ClickException(str(e))
    except Exception as e:
        raise click.ClickException(f"An error occurred: {e}")


if __name__ == '__main__':
    sheets()

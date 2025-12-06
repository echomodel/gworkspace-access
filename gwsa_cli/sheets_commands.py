import click
from googleapiclient.discovery import build
import os
import json
from gwsa_cli.auth.check_access import get_active_credentials
from gwsa_cli.decorators import require_scopes

@click.group()
def sheets():
    """Commands for interacting with Google Sheets."""
    pass

@sheets.command('list')
@require_scopes('sheets-read')
def list_sheets():
    """Lists the user's Google Sheets."""
    creds, _ = get_active_credentials()
    drive_service = build('drive', 'v3', credentials=creds)
    
    try:
        results = drive_service.files().list(
            q="mimeType='application/vnd.google-apps.spreadsheet'",
            fields="files(id, name)"
        ).execute()
        
        items = results.get('files', [])
        
        if not items:
            click.echo("No Google Sheets found.")
        else:
            click.echo("Google Sheets:")
            for item in items:
                click.echo(f"- {item['name']} (ID: {item['id']})")

    except Exception as e:
        raise click.ClickException(f"An error occurred: {e}")

@sheets.command('read')
@click.argument('spreadsheet_id')
@click.argument('range_name')
@require_scopes('sheets-read')
def read_sheet(spreadsheet_id, range_name):
    """Reads data from a specific sheet and range."""
    creds, _ = get_active_credentials()
    sheets_service = build('sheets', 'v4', credentials=creds)
    
    try:
        result = sheets_service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=range_name
        ).execute()
        
        values = result.get('values', [])
        
        if not values:
            click.echo(f"No data found in range '{range_name}'.")
        else:
            for row in values:
                click.echo('\t'.join(map(str, row)))

    except Exception as e:
        raise click.ClickException(f"An error occurred: {e}")

@sheets.command('update-cell')
@click.argument('spreadsheet_id')
@click.argument('range_name')
@click.argument('value')
@require_scopes('sheets')
def update_cell(spreadsheet_id, range_name, value):
    """Updates a specific cell with a new value."""
    creds, _ = get_active_credentials()
    sheets_service = build('sheets', 'v4', credentials=creds)
    
    try:
        body = {
            'values': [[value]]
        }
        result = sheets_service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=range_name,
            valueInputOption='RAW',
            body=body
        ).execute()
        
        click.echo(f"Cell '{range_name}' updated successfully.")

    except Exception as e:
        raise click.ClickException(f"An error occurred: {e}")

if __name__ == '__main__':
    sheets()

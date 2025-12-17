"""Drive commands for GWSA CLI."""

import json
import click

from gwsa.sdk import drive
from .decorators import require_scopes


@click.group()
def drive_group():
    """Google Drive operations."""
    pass


@drive_group.command('list')
@click.option('--folder-id', default=None, help='Folder ID to list. Defaults to My Drive root.')
@click.option('--max-results', type=int, default=100, help='Maximum items to return.')
@require_scopes('drive')
def list_folder(folder_id, max_results):
    """List contents of a Drive folder."""
    try:
        result = drive.list_folder(folder_id=folder_id, max_results=max_results)
        click.echo(json.dumps(result, indent=2))
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)


@drive_group.command('upload')
@click.argument('local_path')
@click.option('--folder-id', default=None, help='Destination folder ID.')
@click.option('--name', default=None, help='Name for file in Drive.')
@require_scopes('drive')
def upload_file(local_path, folder_id, name):
    """Upload a file to Google Drive."""
    try:
        result = drive.upload_file(local_path=local_path, folder_id=folder_id, name=name)
        click.echo(json.dumps(result, indent=2))
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)


@drive_group.command('download')
@click.argument('file_id')
@click.argument('save_path')
@require_scopes('drive')
def download_file(file_id, save_path):
    """Download a file from Google Drive.

    FILE_ID: The Drive file ID to download
    SAVE_PATH: Local path where the file should be saved
    """
    try:
        result = drive.download_file(file_id=file_id, save_path=save_path)
        click.echo(json.dumps(result, indent=2))
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)


@drive_group.command('find-folder')
@click.argument('path')
@require_scopes('drive')
def find_folder(path):
    """Find a folder by path (e.g., 'Projects/my-project')."""
    try:
        result = drive.find_folder_by_path(path)
        click.echo(json.dumps(result, indent=2))
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)


@drive_group.command('mkdir')
@click.argument('name')
@click.option('--parent-id', default=None, help='Parent folder ID.')
@require_scopes('drive')
def create_folder(name, parent_id):
    """Create a new folder in Drive."""
    try:
        result = drive.create_folder(name=name, parent_id=parent_id)
        click.echo(json.dumps(result, indent=2))
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)

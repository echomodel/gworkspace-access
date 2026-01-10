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


@drive_group.command('update')
@click.argument('file_id')
@click.argument('local_path')
@click.option('--name', default=None, help='New name for file in Drive.')
@require_scopes('drive')
def update_file(file_id, local_path, name):
    """Update an existing file in Google Drive."""
    try:
        result = drive.update_file(file_id=file_id, local_path=local_path, new_name=name)
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


@drive_group.group('folders')
def folders_group():
    """Folder search and navigation."""
    pass


@folders_group.command('find')
@click.option('--name', default=None, help='Search folders by name (contains match by default).')
@click.option('--path', default=None, help='Navigate to folder by path (e.g., Projects/foo).')
@click.option('--match', type=click.Choice(['contains', 'exact']), default='contains',
              help='Match type for --name search.')
@click.option('--drive', 'drive_id', default='my_drive',
              help='Starting drive for --path: "my_drive" or Shared Drive ID.')
@click.option('--folder-id', default=None, help='Start --path navigation from this folder ID.')
@click.option('--limit', type=int, default=50, help='Max results for --name search.')
@require_scopes('drive')
def folders_find(name, path, match, drive_id, folder_id, limit):
    """Find folders by name or path.

    Use --name to search across all accessible folders (My Drive, Shared Drives, shared-with-me).

    Use --path to navigate from a starting point (My Drive root by default).

    \b
    Examples:
        gwsa drive folders find --name "Reports"
        gwsa drive folders find --name "Q4" --match exact
        gwsa drive folders find --path "Projects/my-project"
        gwsa drive folders find --path "subfolder" --folder-id PARENT_ID
    """
    if name and path:
        click.echo("Error: Use --name or --path, not both.", err=True)
        raise SystemExit(1)
    if not name and not path:
        click.echo("Error: Provide --name or --path.", err=True)
        raise SystemExit(1)

    try:
        if name:
            results = drive.search_folders(name, match=match, limit=limit)
            click.echo(json.dumps({"folders": results, "count": len(results)}, indent=2))
        else:
            result = drive.find_folder_by_path(path, drive=drive_id, folder_id=folder_id)
            if result:
                click.echo(json.dumps(result, indent=2))
            else:
                click.echo(f"Folder not found: {path}", err=True)
                raise SystemExit(1)
    except drive.AmbiguousFolderError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)
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

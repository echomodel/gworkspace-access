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
@click.option('--keep', is_flag=True,
              help='Pin the resulting revision (keepForever) so it is '
                   'never auto-pruned.')
@require_scopes('drive')
def upload_file(local_path, folder_id, name, keep):
    """Upload a file to Google Drive."""
    try:
        result = drive.upload_file(
            local_path=local_path, folder_id=folder_id, name=name,
            keep_revision_forever=keep,
        )
        click.echo(json.dumps(result, indent=2))
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)


@drive_group.command('update')
@click.argument('file_id')
@click.argument('local_path')
@click.option('--name', default=None, help='New name for file in Drive.')
@click.option('--keep', is_flag=True,
              help='Pin the resulting revision (keepForever) so this '
                   'version is never auto-pruned — update + pin in one step.')
@require_scopes('drive')
def update_file(file_id, local_path, name, keep):
    """Update an existing file in Google Drive."""
    try:
        result = drive.update_file(
            file_id=file_id, local_path=local_path, new_name=name,
            keep_revision_forever=keep,
        )
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


@drive_group.command('set-properties')
@click.argument('file_id')
@click.option('--prop', 'props', multiple=True, metavar='KEY=VALUE',
              help='Public property to set (repeatable). Use KEY= to '
                   'delete a key.')
@click.option('--app-prop', 'app_props', multiple=True, metavar='KEY=VALUE',
              help='App-private property to set (repeatable).')
@require_scopes('drive')
def set_properties(file_id, props, app_props):
    """Set custom key/value metadata on a Drive file or folder.

    Tags are API-only (invisible in the Drive UI) and merge per key —
    keys you don't pass are left untouched; KEY= (empty value) deletes
    a key. Discover later with: drive search "properties has { key='K'
    and value='V' }".
    """
    def _parse(pairs):
        out = {}
        for p in pairs:
            if '=' not in p:
                raise click.ClickException(
                    f"Property must be KEY=VALUE, got: {p}")
            k, v = p.split('=', 1)
            out[k] = (None if v == '' else v)
        return out

    properties = _parse(props) if props else None
    app_properties = _parse(app_props) if app_props else None
    if properties is None and app_properties is None:
        raise click.ClickException("Pass at least one --prop or --app-prop.")
    try:
        result = drive.set_properties(
            file_id, properties=properties, app_properties=app_properties)
        click.echo(json.dumps(result, indent=2))
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)


@drive_group.group('revisions')
def revisions_group():
    """File revision history — a lightweight version store for uploaded files.

    Every `drive update` mints a new revision. For uploaded (non-native)
    files you can list history, fetch the content of any past revision to
    diff, and pin milestones with `keep` so they survive auto-pruning
    (Drive prunes non-pinned revisions roughly after 100 versions or 30
    days). Native Google files (Docs/Sheets/Slides) can be listed but
    their historical content is not exportable.
    """
    pass


@revisions_group.command('list')
@click.argument('file_id')
@require_scopes('drive')
def revisions_list(file_id):
    """List a Drive file's revision history.

    FILE_ID: The Drive file ID.
    """
    try:
        result = drive.list_revisions(file_id=file_id)
        click.echo(json.dumps(result, indent=2))
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)


@revisions_group.command('get')
@click.argument('file_id')
@click.argument('revision_id')
@click.option('--out', 'out_path', default=None,
              help='Write the revision content to this path. '
                   'Omit to stream raw bytes to stdout (handy for '
                   'piping/diffing a past JSON or CSV version).')
@require_scopes('drive')
def revisions_get(file_id, revision_id, out_path):
    """Download a specific revision's content (uploaded files only).

    FILE_ID: The Drive file ID.
    REVISION_ID: The revision ID (from `revisions list`).

    Native Google files (Docs/Sheets/Slides) have no exportable
    historical content — this surfaces a clear error for them.
    """
    try:
        if out_path:
            result = drive.download_revision_file(
                file_id=file_id, revision_id=revision_id, save_path=out_path
            )
            click.echo(json.dumps(result, indent=2))
        else:
            fetched = drive.download_revision_bytes(
                file_id=file_id, revision_id=revision_id
            )
            click.get_binary_stream('stdout').write(fetched["data"])
    except drive.NativeFileRevisionError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)


@revisions_group.command('match')
@click.argument('file_id')
@click.argument('local_path')
@click.option('--pin', is_flag=True,
              help='If a revision matches, pin it (keepForever) in the '
                   'same call.')
@require_scopes('drive')
def revisions_match(file_id, local_path, pin):
    """Find the revision whose content matches a local file, by md5.

    FILE_ID: The Drive file ID.
    LOCAL_PATH: Local file whose content to look for.

    Prints the result as JSON. Exit code is the "is this content backed
    up?" contract: 0 if a matching revision is found, 1 if not, 2 on
    error (e.g. a native Google file, which has no checksum). With
    --pin, a found revision is pinned (keepForever) before returning.
    """
    try:
        result = drive.match_revision_file(
            file_id=file_id, local_path=local_path, pin=pin
        )
    except FileNotFoundError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(2)
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(2)

    click.echo(json.dumps(result, indent=2))
    if result.get("note"):
        raise SystemExit(2)
    raise SystemExit(0 if result["matched"] else 1)


@revisions_group.command('keep')
@click.argument('file_id')
@click.argument('revision_id')
@require_scopes('drive')
def revisions_keep(file_id, revision_id):
    """Pin a revision (keepForever=true) so it is never auto-pruned.

    FILE_ID: The Drive file ID.
    REVISION_ID: The revision ID to pin.
    """
    try:
        result = drive.keep_revision(file_id=file_id, revision_id=revision_id)
        click.echo(json.dumps(result, indent=2))
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)


@revisions_group.command('unkeep')
@click.argument('file_id')
@click.argument('revision_id')
@require_scopes('drive')
def revisions_unkeep(file_id, revision_id):
    """Remove the keep-forever pin from a revision (keepForever=false).

    FILE_ID: The Drive file ID.
    REVISION_ID: The revision ID to unpin.

    Note: Drive only allows unpinning the head (current) revision. Once
    an older revision is pinned, it cannot be un-pinned via the API.
    """
    try:
        result = drive.unkeep_revision(file_id=file_id, revision_id=revision_id)
        click.echo(json.dumps(result, indent=2))
    except drive.KeepForeverUnsetError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)

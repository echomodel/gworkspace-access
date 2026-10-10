"""CLI commands for Google Docs operations."""

import json
import click

from gwsa.sdk import docs as sdk_docs
from gwsa.sdk.exceptions import LocalPathError, InvalidDocIdError
from .decorators import require_scopes


@click.group()
def docs():
    """Commands for interacting with Google Docs."""
    pass


@docs.command('list')
@click.option('--max-results', type=int, default=25,
              help='Maximum number of documents to return (default 25).')
@click.option('--query', '-q', default=None,
              help='Search query to filter documents.')
@require_scopes('docs-read')
def list_docs(max_results, query):
    """List Google Docs accessible to the current user."""
    try:
        result = sdk_docs.list_documents(max_results=max_results, query=query)
        documents = result.get("documents", [])

        if not documents:
            click.echo("No Google Docs found.")
        else:
            click.echo("Google Docs:")
            for doc in documents:
                click.echo(f"- {doc['title']} (ID: {doc['id']})")

    except Exception as e:
        raise click.ClickException(f"An error occurred: {e}")


@docs.command('create')
@click.argument('title')
@click.option('--body', '-b', default=None,
              help='Initial body text for the document.')
@require_scopes('docs')
def create_doc(title, body):
    """Create a new Google Doc."""
    try:
        result = sdk_docs.create_document(title=title, body_text=body)
        click.echo(f"Document created successfully!")
        click.echo(f"  Title: {result['title']}")
        click.echo(f"  ID: {result['id']}")
        click.echo(f"  URL: {result['url']}")

    except Exception as e:
        raise click.ClickException(f"An error occurred: {e}")


@docs.command('read')
@click.argument('doc_id')
@click.option('--format', 'output_format',
              type=click.Choice(['markdown', 'text', 'content', 'map', 'raw']),
              default='markdown', show_default=True,
              help="markdown/text: Google's export (all tabs, no positions). "
                   "content: metadata + tabs + markdown (JSON). "
                   "map: paragraphs with exact index ranges. raw: Docs API JSON.")
@click.option('--tab', 'tab_id', default=None,
              help='Only this tab (map and raw formats).')
@require_scopes('docs-read')
def read_doc(doc_id, output_format, tab_id):
    """Read a Google Doc by ID."""
    try:
        if tab_id and output_format not in ('map', 'raw'):
            raise click.ClickException("--tab applies to --format map or raw.")
        if output_format == 'markdown':
            click.echo(sdk_docs.get_document_markdown(doc_id))
        elif output_format == 'text':
            click.echo(sdk_docs.get_document_text(doc_id))
        elif output_format == 'content':
            click.echo(json.dumps(sdk_docs.get_document_content(doc_id), indent=2))
        elif output_format == 'map':
            result = sdk_docs.get_document_map(doc_id, tab_id=tab_id)
            click.echo(f"# revision {result['revision_id']}")
            for seg in result['segments']:
                click.echo(f"## tab {seg['tab_id']} ({seg['tab_title']}) "
                           f"{seg['segment']} {seg['segment_id']}".rstrip())
                for line in seg['lines']:
                    click.echo(line)
        else:
            click.echo(json.dumps(sdk_docs.get_document(doc_id, tab_id=tab_id), indent=2))

    except click.ClickException:
        raise
    except (LocalPathError, InvalidDocIdError, ValueError) as e:
        raise click.ClickException(str(e))
    except Exception as e:
        raise click.ClickException(f"An error occurred: {e}")


@docs.command('find')
@click.argument('doc_id')
@click.argument('text')
@click.option('--tab', 'tab_id', default=None, help='Search only this tab.')
@click.option('--ignore-case', is_flag=True, default=False,
              help='Case-insensitive match.')
@require_scopes('docs-read')
def find_in_doc(doc_id, text, tab_id, ignore_case):
    """Print every occurrence of TEXT with its exact index range."""
    try:
        result = sdk_docs.find_in_document(
            doc_id, text, tab_id=tab_id, match_case=not ignore_case)
        click.echo(json.dumps(result, indent=2))
    except (LocalPathError, InvalidDocIdError, ValueError) as e:
        raise click.ClickException(str(e))
    except Exception as e:
        raise click.ClickException(f"An error occurred: {e}")


@docs.command('batch-update')
@click.argument('doc_id')
@click.option('--requests-json', '-r', required=True,
              help='JSON array of Docs API batchUpdate request objects. Each '
                   'index-based request also carries "expect": '
                   '{"text": ...}, {"element": "paragraph"|"table"}, '
                   '{"before": ...}/{"after": ...}, or {"unchecked": true}.')
@click.option('--required-revision-id', required=True,
              help='Revision your positions came from (printed by '
                   '"docs read --format map" and "docs find"). Refused if '
                   'the document changed since.')
@click.option('--dry-run', is_flag=True,
              help='Check and print the predicted changes without writing.')
@require_scopes('docs')
def batch_update_doc(doc_id, requests_json, required_revision_id, dry_run):
    """Apply a Docs API batchUpdate, checked against the current document.

    Every index-based request needs an "expect" stating what is at that
    position; if any does not match, nothing is written. Prints the
    revision ids, Google's replies, and the changed paragraphs.
    """
    try:
        requests = json.loads(requests_json)
        result = sdk_docs.batch_update(
            doc_id, requests, required_revision_id, dry_run=dry_run)
        click.echo(json.dumps(result, indent=2))
    except json.JSONDecodeError as e:
        raise click.ClickException(f"Invalid JSON: {e}")
    except sdk_docs.ExpectationError as e:
        raise click.ClickException(
            "Expectation check failed. Nothing was written.\n- "
            + "\n- ".join(e.failures))
    except (LocalPathError, InvalidDocIdError, ValueError) as e:
        raise click.ClickException(str(e))
    except Exception as e:
        raise click.ClickException(f"An error occurred: {e}")


if __name__ == '__main__':
    docs()

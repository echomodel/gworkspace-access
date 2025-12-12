"""CLI commands for Google Docs operations."""

import json
import click

from gwsa.sdk import docs as sdk_docs
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
@click.option('--format', 'output_format', type=click.Choice(['text', 'json']),
              default='text', help='Output format (default: text).')
@require_scopes('docs-read')
def read_doc(doc_id, output_format):
    """Read a Google Doc by ID."""
    try:
        if output_format == 'json':
            result = sdk_docs.get_document_content(doc_id)
            click.echo(json.dumps(result, indent=2))
        else:
            text = sdk_docs.get_document_text(doc_id)
            click.echo(text)

    except Exception as e:
        raise click.ClickException(f"An error occurred: {e}")


@docs.command('append')
@click.argument('doc_id')
@click.argument('text')
@require_scopes('docs')
def append_to_doc(doc_id, text):
    """Append text to a Google Doc."""
    try:
        sdk_docs.append_text(doc_id, text)
        click.echo("Text appended successfully!")

    except Exception as e:
        raise click.ClickException(f"An error occurred: {e}")


@docs.command('insert')
@click.argument('doc_id')
@click.argument('text')
@click.option('--index', '-i', type=int, default=1,
              help='Position to insert at (default: 1, beginning of document).')
@require_scopes('docs')
def insert_to_doc(doc_id, text, index):
    """Insert text at a specific position in a Google Doc."""
    try:
        sdk_docs.insert_text(doc_id, text, index=index)
        click.echo(f"Text inserted at index {index} successfully!")

    except Exception as e:
        raise click.ClickException(f"An error occurred: {e}")


@docs.command('replace')
@click.argument('doc_id')
@click.argument('find_text')
@click.argument('replace_with')
@click.option('--ignore-case', is_flag=True,
              help='Ignore case when matching.')
@require_scopes('docs')
def replace_in_doc(doc_id, find_text, replace_with, ignore_case):
    """Replace all occurrences of text in a Google Doc."""
    try:
        result = sdk_docs.replace_text(
            doc_id, find_text, replace_with, match_case=not ignore_case
        )
        # Get count of replacements
        replies = result.get("replies", [])
        if replies:
            count = replies[0].get("replaceAllText", {}).get("occurrencesChanged", 0)
            click.echo(f"Replaced {count} occurrence(s).")
        else:
            click.echo("Replace operation completed.")

    except Exception as e:
        raise click.ClickException(f"An error occurred: {e}")


if __name__ == '__main__':
    docs()

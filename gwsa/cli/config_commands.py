import click
import yaml
from . import config

import click
import yaml
from . import config

# Define the schema of allowed configuration keys and their allowed values
ALLOWED_CONFIG = {
    "auth.mode": {
        "type": str,
        "allowed_values": ["token", "adc"]
    }
}

@click.group()
def config_group():
    """Commands for managing gwsa configuration."""
    pass

@config_group.command('view')
def view_config():
    """Displays the current gwsa configuration."""
    config_data = config.load_config()
    click.echo(yaml.dump(config_data, default_flow_style=False))

@config_group.command('set')
@click.argument('key')
@click.argument('value')
def set_config(key, value):
    """
    Sets a configuration value for a supported key.

    \b
    Supported Keys:
      - auth.mode: Set the authentication mode.
                   Allowed values: 'token', 'adc'.

    \b
    Examples:
      gwsa config set auth.mode adc
      gwsa config set auth.mode token
    """
    if key not in ALLOWED_CONFIG:
        raise click.UsageError(f"Configuration key '{key}' is not supported.")

    key_schema = ALLOWED_CONFIG[key]
    
    # Validate allowed values
    if "allowed_values" in key_schema and value not in key_schema["allowed_values"]:
        allowed = ", ".join(f"'{v}'" for v in key_schema["allowed_values"])
        raise click.UsageError(f"Invalid value '{value}' for key '{key}'. Allowed values are: {allowed}.")

    # Basic type conversion for boolean and numbers
    if value.lower() in ['true', 'false']:
        value = value.lower() == 'true'
    elif value.isdigit():
        value = int(value)
    elif value.replace('.', '', 1).isdigit():
        try:
            value = float(value)
        except ValueError:
            pass # Keep as string if it's not a valid float

    config.set_config_value(key, value)
    click.echo(f"✓ Set '{key}' to: {value}")

    # Provide helpful guidance for ADC mode
    if key == "auth.mode" and value == "adc":
        click.echo("\nTo use Application Default Credentials, ensure you have authenticated with gcloud:")
        click.echo("  gcloud auth application-default login")




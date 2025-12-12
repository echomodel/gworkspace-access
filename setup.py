from setuptools import setup, find_packages
import re

# Read version from gwsa/__init__.py
with open('gwsa/__init__.py') as f:
    version = re.search(r'^__version__ = ["\']([^"\']+)["\']', f.read(), re.MULTILINE).group(1)

setup(
    name='gwsa',
    version=version,
    packages=find_packages(),
    install_requires=[
        'google-api-python-client',
        'google-auth-oauthlib',
        'python-dotenv',
        'click>=8.0',
        'PyYAML',
        'click_option_group',
        'mcp>=1.0.0',
    ],
    extras_require={
        'mcp': ['mcp>=1.0.0'],
    },
    entry_points={
        'console_scripts': [
            'gwsa=gwsa.cli.__main__:main',
            'gwsa-mcp=gwsa.mcp.server:run_server',
        ],
    },
    author='CLI Developer',
    description='Google Workspace Access - SDK, CLI, and MCP server for Gmail and Google APIs.',
    long_description=open('README.md').read(),
    long_description_content_type='text/markdown',
)

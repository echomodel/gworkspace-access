from setuptools import setup, find_packages
import re

# Read version from __init__.py
with open('gwsa_cli/__init__.py') as f:
    version = re.search(r'^__version__ = ["\']([^"\']+)["\']', f.read(), re.MULTILINE).group(1)

setup(
    name='gwsa-cli',
    version=version,
    packages=find_packages(),
    install_requires=[
        'google-api-python-client',
        'google-auth-oauthlib',
        'python-dotenv',
        'click>=8.0',
        'PyYAML',
        'click_option_group',
    ],
    entry_points={
        'console_scripts': [
            'gwsa=gwsa_cli.__main__:main',
        ],
    },
    author='CLI Developer',
    description='A personal Gmail Workspace Assistant CLI tool.',
    long_description=open('README.md').read(),
    long_description_content_type='text/markdown',
)

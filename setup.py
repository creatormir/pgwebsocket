""""""
from setuptools import setup
from os import path

with open(path.join(path.abspath(path.dirname(__file__)), 'README.rst'), encoding='utf-8') as f:
    long_description = f.read()

setup(
    name="pgwebsocket",
    version="0.0.1b1",
    description="Async websocket to PostgreSQL proxy",
    long_description=long_description,
    author="Wirehive Ltd",
    author_email="barnaby@wirehive.net",
    url="https://github.com/wirehive/pgwebsocket",
    license='GPLv2',
    keywords="aiohttp psycopg2 postgresql websocket",
    packages=[
        "pgwebsocket"
    ],
    classifiers=[
        "Development Status :: 4 - Beta",
        "Environment :: Web Environment",
        "License :: OSI Approved :: GNU General Public License v2 (GPLv2)",
        "Programming Language :: Python :: 3.5"
    ],
    install_requires=[
        "aiohttp",
        "psycopg2"
    ]
)

# -*- coding: utf-8 -*-
"""
    jQuery Example
    ~~~~~~~~~~~~~~

    A simple application that shows how Flask and jQuery get along.

    :copyright: (c) 2010 by Armin Ronacher.
    :license: BSD, see LICENSE for more details.
"""
from flask import Flask, jsonify, render_template, request
app = Flask(__name__)


@app.route('/_add_numbers')
def add_numbers():
    """
Adds two numbers together.

This function takes in two integer parameters 'a' and 'b' from the URL query string.
It returns a JSON response with the sum of 'a' and 'b'.

Parameters:
    a (int): The first number to add. Defaults to 0 if not provided.
    b (int): The second number to add. Defaults to 0 if not provided.

Returns:
    dict: A dictionary containing the result of the addition as a JSON response.
"""
a = request.args.get('a', 0, type=int)
    b = request.args.get('b', 0, type=int)
    return jsonify(result=a + b)


@app.route('/')
def index():
    """
Returns an HTML template rendered from 'index.html' using the Flask `render_template` function.

Args:
    None

Returns:
    A rendered HTML template as a string.
"""
return render_template('index.html')


if __name__ == '__main__':
    app.run()

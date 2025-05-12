from flask import Flask, abort, redirect, request, session, \
     render_template, url_for

#: create a new flask applications.  We pass it the name of our module
#: so that flask knows where to look for templates and static files.
app = Flask(__name__)


@app.route('/', methods=['GET'])
def index():
    return render_template('index.html')


@app.route('/hello/', methods=['GET', 'POST'])
def hello_user():
    if request.method == 'POST':
        return redirect(url_for('hello', name=request.form['name']))
    return render_template('hello.html', name=None)


@app.route('/hello/<name>', methods=['GET'])
def hello(name):
    return render_template('hello.html', name=name)


if __name__ == '__main__':
    app.run(debug=True)


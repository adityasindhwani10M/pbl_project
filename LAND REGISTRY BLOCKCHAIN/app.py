from flask import Flask, render_template, request, redirect, flash
from blockchain import Blockchain

app = Flask(__name__)
app.secret_key = 'secret123'

blockchain = Blockchain()

@app.route('/')
def home():
    return render_template('index.html', chain=blockchain.chain)

@app.route('/add', methods=['POST'])
def add_property():
    data = {
        "type": "ADD PROPERTY",
        "owner": request.form['owner'],
        "location": request.form['location'],
        "area": request.form['area'],
        "property_id": request.form['property_id']
    }

    prev_block = blockchain.get_last_block()
    blockchain.create_block(data=data, previous_hash=prev_block['hash'])

    flash("✅ Property successfully registered on blockchain!")

    return redirect('/')

@app.route('/records')
def records():
    return {"chain": blockchain.chain}

if __name__ == '__main__':
    app.run(debug=True)
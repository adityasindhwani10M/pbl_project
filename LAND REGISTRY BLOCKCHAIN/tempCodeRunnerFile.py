    blockchain.create_block(data=data, previous_hash=prev_block['hash'])

    return redirect('/')

@app.route('/records')
def records():
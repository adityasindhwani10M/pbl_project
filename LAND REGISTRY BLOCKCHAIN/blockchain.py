import hashlib
import json
from time import time

class Blockchain:
    def __init__(self):
        self.chain = []
        self.create_block(data="Genesis Block", previous_hash="0")

    def create_block(self, data, previous_hash):
        block = {
            'index': len(self.chain) + 1,
            'timestamp': str(time()),
            'data': data,
            'previous_hash': previous_hash
        }
        block['hash'] = self.hash(block)
        self.chain.append(block)
        return block

    def hash(self, block):
        encoded = json.dumps(block, sort_keys=True).encode()
        return hashlib.sha256(encoded).hexdigest()

    def get_last_block(self):
        return self.chain[-1]
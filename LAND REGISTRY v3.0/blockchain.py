import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone, timedelta

# Optional Web3.py integration (auto-connects if Ganache/Hardhat is running locally)
try:
    from web3 import Web3
    WEB3_AVAILABLE = True
except ImportError:
    WEB3_AVAILABLE = False

IST = timezone(timedelta(hours=5, minutes=30))


class Blockchain:
    def __init__(self, db_path=None):
        if db_path is None:
            db_path = os.environ.get('LANDCHAIN_DB_PATH')

        if db_path is None:
            db_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                'landchain.db'
            )
        self.db_path = db_path
        self.db_path = db_path
        self.chain = []
        self.w3 = None
        self.web3_connected = False
        self._init_web3()
        self._init_db()
        self._load_chain()

    def _init_web3(self):
        """Attempt non-blocking connection to local Ethereum RPC (Ganache/Hardhat)."""
        if WEB3_AVAILABLE:
            try:
                rpc_url = os.environ.get('ETH_RPC_URL', 'http://127.0.0.1:7545')
                w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={'timeout': 1.5}))
                if w3.is_connected():
                    self.w3 = w3
                    self.web3_connected = True
            except Exception:
                self.web3_connected = False

    def _get_ist_timestamp(self):
        return datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S IST')

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS blocks (
                idx INTEGER PRIMARY KEY,
                timestamp TEXT NOT NULL,
                data_json TEXT NOT NULL,
                previous_hash TEXT NOT NULL,
                block_hash TEXT NOT NULL
            )
        ''')
        conn.commit()
        conn.close()

    def _load_chain(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT idx, timestamp, data_json, previous_hash, block_hash FROM blocks ORDER BY idx ASC')
        rows = cursor.fetchall()
        conn.close()

        if rows:
            self.chain = []
            for idx, ts, data_json, prev_hash, blk_hash in rows:
                try:
                    parsed_data = json.loads(data_json)
                except Exception:
                    parsed_data = data_json
                self.chain.append({
                    'index': idx,
                    'timestamp': ts,
                    'data': parsed_data,
                    'previous_hash': prev_hash,
                    'hash': blk_hash
                })
        else:
            self.chain = []
            self.create_block(data="Genesis Block", previous_hash="0")

    def _save_block_to_db(self, block):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO blocks (idx, timestamp, data_json, previous_hash, block_hash)
            VALUES (?, ?, ?, ?, ?)
        ''', (
            block['index'],
            block['timestamp'],
            json.dumps(block['data'], sort_keys=True),
            block['previous_hash'],
            block['hash']
        ))
        conn.commit()
        conn.close()

    def create_block(self, data, previous_hash):
        # Optional: broadcast transaction anchor to local EVM node if connected
        if isinstance(data, dict) and self.web3_connected and self.w3 and self.w3.eth.accounts:
            try:
                payload_hex = self.w3.to_hex(text=json.dumps(data, sort_keys=True))
                tx_hash = self.w3.eth.send_transaction({
                    'from': self.w3.eth.accounts[0],
                    'to': self.w3.eth.accounts[0],
                    'value': 0,
                    'data': payload_hex
                })
                data['evm_tx_hash'] = self.w3.to_hex(tx_hash)
            except Exception:
                pass

        block = {
            'index': len(self.chain) + 1,
            'timestamp': self._get_ist_timestamp(),
            'data': data,
            'previous_hash': previous_hash
        }
        block['hash'] = self.hash(block)
        self.chain.append(block)
        self._save_block_to_db(block)
        return block

    def hash(self, block):
        block_copy = {
            'index': block['index'],
            'timestamp': block['timestamp'],
            'data': block['data'],
            'previous_hash': block['previous_hash']
        }
        encoded = json.dumps(block_copy, sort_keys=True).encode()
        return hashlib.sha256(encoded).hexdigest()

    def get_last_block(self):
        return self.chain[-1]

    def is_chain_valid(self):
        """Recalculates every SHA-256 digest and verifies sequential hash links."""
        for i in range(len(self.chain)):
            current = self.chain[i]
            recalculated_hash = self.hash(current)
            if current.get('hash') != recalculated_hash:
                return False, f"Tampering detected at Block #{current['index']}: Stored hash does not match recalculated SHA-256 digest."
            if i > 0:
                prev = self.chain[i - 1]
                if current.get('previous_hash') != prev.get('hash'):
                    return False, f"Broken chain link at Block #{current['index']}: previous_hash does not match Block #{prev['index']} hash."
        return True, f"All {len(self.chain)} blocks verified intact. Zero hash mismatches."

    def get_property_history(self, property_id):
        """Returns chronological list of all blocks associated with a UPIN."""
        target = str(property_id).strip().lower()
        history = []
        for block in self.chain:
            data = block.get('data')
            if isinstance(data, dict):
                blk_prop_id = str(data.get('property_id', '')).strip().lower()
                if blk_prop_id == target:
                    history.append(block)
        return history

    def get_current_owner(self, property_id):
        """Returns the latest owner and latest block for a given UPIN, or (None, None)."""
        history = self.get_property_history(property_id)
        if not history:
            return None, None
        latest_block = history[-1]
        return latest_block['data'].get('owner'), latest_block

    def verify_document_hash(self, doc_hash):
        """Checks if a PDF/Image SHA-256 fingerprint exists in any block on the chain."""
        for block in self.chain:
            data = block.get('data')
            if isinstance(data, dict) and data.get('document_hash') == doc_hash:
                return block
        return None

import os
import re
import json
import shutil
import hashlib
import requests
import urllib.parse
import pytesseract
import PyPDF2
from PIL import Image
from werkzeug.utils import secure_filename
from flask import Flask, render_template, request, redirect, flash, jsonify, session
from blockchain import Blockchain
from dotenv import load_dotenv
load_dotenv()

# Optional Google Gemini AI SDK for universal deed extraction
try:
    from google import genai
    from google.genai import types
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False

# Cross-platform Tesseract configuration (works on Windows + Linux/Cloud)
windows_tesseract = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
if os.path.exists(windows_tesseract):
    pytesseract.pytesseract.tesseract_cmd = windows_tesseract
elif shutil.which('tesseract'):
    pytesseract.pytesseract.tesseract_cmd = shutil.which('tesseract')

app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'landchain_india_zero_trust_secret_2026')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 MB max upload size

app.config['UPLOAD_FOLDER'] = 'uploads/'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

blockchain = Blockchain()


# --- HELPER: GEMINI AI + OPTIONAL REGEX EXTRACTION ---
def extract_entities_from_text(text):
    """
    PRIMARY: Google Gemini 2.5 Flash Structured JSON Extraction.
    BACKUP: Multi-Path Regex Engine (runs if offline, no API key, or if AI misses a field).
    """
    core_fields = ['owner', 'location', 'category', 'area', 'property_id']
    extracted = {
        'owner': '',
        'seller': '',
        'location': '',
        'category': '',
        'area': '',
        'property_id': '',
        'engine': '',
        'confidence': 0
    }

    # --- STEP 1: PRIMARY EXTRACTOR (GEMINI AI) ---
    api_key = os.environ.get('GEMINI_API_KEY')
    ai_succeeded = False

    if GENAI_AVAILABLE and api_key:
        try:
            client = genai.Client(api_key=api_key)
            prompt = f"""
            You are an Indian Legal Conveyance Auditor. Extract the following parameters from this Sale Deed text.
            Return ONLY valid JSON with these exact keys:
            - "owner": Full name of the Purchaser / Vendee / Buyer (include title like Mr./Ms./Dr. or corporate suffix like Pvt. Ltd./Hospital, but exclude trailing commas).
            - "seller": Full name of the Vendor / Seller.
            - "location": Property address/parcel description (between 'bearing No.'/'known as' and 'measuring', or full property address).
            - "category": Approved land use category (e.g., Residential, Commercial, Institutional (Hospital)).
            - "area": Total area with unit (e.g., 450 Sq. Meters).
            - "property_id": Unique Property ID / Document No. (digits/alphanumeric code).
            - "confidence": Integer from 0 to 100 representing extraction confidence.

            Sale Deed Text:
            {text[:8000]}
            """
            response = client.models.generate_content(
                model='gemini-3.8-flash',
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.1
                )
            )
            llm_data = json.loads(response.text)

            for key in core_fields + ['seller']:
                if llm_data.get(key):
                    extracted[key] = str(llm_data[key]).strip().strip(',')

            extracted['location'] = re.sub(r'\s+', ' ', extracted['location'])
            extracted['confidence'] = int(llm_data.get('confidence', 98))
            extracted['engine'] = 'Gemini 3.8 Flash AI (Primary)'
            ai_succeeded = True
        except Exception as e:
            print(f"[AI Primary Extractor Fallback Triggered]: {e}")

    # --- STEP 2: BACKUP EXTRACTOR (YOUR MULTI-PATH REGEX) ---
    owner_match = re.search(
        r'AND\s*\n*(?:(?:Mr\.|Ms\.|Mrs\.|Dr\.|Shri|Smt\.)\s+([A-Za-z\s\.]+),|([A-Za-z0-9\s\-\.\&]+?(?:Limited|Ltd\.?|Private|Pvt\.?|Company|LLP|Hospital|Trust|Foundation)),)',
        text,
        re.IGNORECASE
    )
    seller_match = re.search(
        r'BETWEEN\s*\n*(?:(?:Mr\.|Ms\.|Mrs\.|Dr\.|Shri|Smt\.)\s+([A-Za-z\s\.]+),|([A-Za-z0-9\s\-\.\&]+?(?:Limited|Ltd\.?|Private|Pvt\.?|Company|LLP|Authority|Development)),)',
        text,
        re.IGNORECASE
    )
    location_match = re.search(r'(?:bearing No\.|known as)\s*([\s\S]+?)\s*measuring', text, re.IGNORECASE)
    category_match = re.search(r'Approved Use[\s|]*([A-Za-z0-9\(\)/ \-]+?)(?=\s*Actual Use)', text, re.IGNORECASE)
    area_match = re.search(r'Total Area of Plot(?:/Flat|/Unit)?[\s|]*([\d.,]+\s*(?:Sq\.\s*Meters|Sq\.\s*Ft\.?|Sq\.\s*Yards|Hectares))', text, re.IGNORECASE)
    id_match = re.search(r'document No\.\s*([A-Za-z0-9\-/]+)', text, re.IGNORECASE)

    regex_data = {
        'owner': (owner_match.group(1) or owner_match.group(2)).strip() if owner_match else '',
        'seller': (seller_match.group(1) or seller_match.group(2)).strip() if seller_match else 'Original Allottee / Vendor',
        'location': re.sub(r'\s+', ' ', location_match.group(1).replace('\n', ' ').strip(', ')) if location_match else '',
        'category': category_match.group(1).strip() if category_match else '',
        'area': area_match.group(1).strip() if area_match else '',
        'property_id': id_match.group(1).strip() if id_match else ''
    }

    # Fill any field that AI left empty (or all fields if AI failed/offline)
    regex_used = False
    for key in core_fields + ['seller']:
        if not extracted.get(key) and regex_data.get(key):
            extracted[key] = regex_data[key]
            if key in core_fields:
                regex_used = True

    # Set final engine badge and confidence score
    if ai_succeeded and regex_used:
        extracted['engine'] = 'Gemini 3.8 Flash AI + Regex Backup'
    elif not ai_succeeded:
        extracted['engine'] = 'Multi-Path Regex Engine (Offline Backup)'
        matched_count = sum(1 for k in core_fields if extracted[k])
        extracted['confidence'] = int((matched_count / 5) * 96) if matched_count == 5 else int((matched_count / 5) * 80)

    return extracted


# --- ROUTES ---
@app.route('/')
def home():
    is_valid, audit_msg = blockchain.is_chain_valid()
    total_properties = len({
        b['data'].get('property_id')
        for b in blockchain.chain
        if isinstance(b.get('data'), dict) and b['data'].get('property_id')
    })
    total_transfers = sum(
        1 for b in blockchain.chain
        if isinstance(b.get('data'), dict) and b['data'].get('type') == 'TRANSFER PROPERTY'
    )
    stats = {
        'total_blocks': len(blockchain.chain),
        'total_properties': total_properties,
        'total_transfers': total_transfers,
        'chain_valid': is_valid,
        'audit_msg': audit_msg,
        'web3_connected': blockchain.web3_connected
    }
    return render_template('index.html', chain=blockchain.chain, stats=stats)


@app.route('/add', methods=['POST'])
def add_property():
    owner = request.form.get('owner', '').strip()
    location = request.form.get('location', '').strip()
    category = request.form.get('category', '').strip()
    area = request.form.get('area', '').strip()
    property_id = request.form.get('property_id', '').strip()
    document_hash = request.form.get('document_hash', '').strip()
    verified_coords = request.form.get('verified_coords', '').strip()

    # 1. Backend Validation: Prevent empty block minting
    if not all([owner, location, category, area, property_id]):
        flash("❌ Error: All fields must be extracted before registering.", "error")
        return redirect('/')

    # 2. Server-Side Zero-Trust Enforcement: Prevent DevTools tampering of readonly fields
    verified_session = session.get('verified_extraction')
    if not verified_session:
        flash("❌ Security Alert: Unverified manual form submission blocked. Please scan a valid Sale Deed first.", "error")
        return redirect('/')

    if (
        owner != verified_session.get('owner') or
        location != verified_session.get('location') or
        category != verified_session.get('category') or
        area != verified_session.get('area') or
        property_id != verified_session.get('property_id')
    ):
        flash("🛡️ Zero-Trust Security Alert: Client-side tampering of locked fields detected! Submission rejected.", "error")
        return redirect('/')

    # 3. Duplicate UPIN / Double-Spending Check
    existing_owner, existing_block = blockchain.get_current_owner(property_id)
    if existing_owner:
        flash(
            f"⚠️ Duplicate Registration Blocked: UPIN #{property_id} is already registered to '{existing_owner}' in Block #{existing_block['index']}. Use the 'Transfer Ownership' tab for property mutation.",
            "error"
        )
        return redirect('/')

    data = {
        "type": "ADD PROPERTY",
        "owner": owner,
        "seller": verified_session.get('seller', 'Initial Registration'),
        "location": location,
        "category": category,
        "area": area,
        "property_id": property_id,
        "document_hash": document_hash or verified_session.get('document_hash', 'N/A'),
        "coordinates": verified_coords or "Pending Map Pin",
        "confidence": verified_session.get('confidence', 96),
        "engine": verified_session.get('engine', 'Multi-Path Regex Engine')
    }

    prev_block = blockchain.get_last_block()
    new_block = blockchain.create_block(data=data, previous_hash=prev_block['hash'])
    session.pop('verified_extraction', None)

    flash(f"✅ Property (UPIN #{property_id}) successfully minted into Block #{new_block['index']}!", "success")
    return redirect('/')


@app.route('/transfer', methods=['POST'])
def transfer_property():
    property_id = request.form.get('property_id', '').strip()
    current_owner_input = request.form.get('current_owner', '').strip()
    new_owner = request.form.get('new_owner', '').strip()
    transfer_reason = request.form.get('transfer_reason', 'Registered Sale Deed Mutation').strip()

    if not all([property_id, current_owner_input, new_owner]):
        flash("❌ Error: UPIN, Current Owner, and New Buyer Name are required for ownership transfer.", "error")
        return redirect('/')

    actual_owner, latest_block = blockchain.get_current_owner(property_id)
    if not actual_owner:
        flash(f"❌ Error: UPIN #{property_id} does not exist on the blockchain ledger. Register the property first.", "error")
        return redirect('/')

    if actual_owner.strip().lower() != current_owner_input.lower():
        flash(
            f"🛡️ Fraud Prevention Alert: Seller mismatch! Blockchain records show '{actual_owner}' is the current legal owner of UPIN #{property_id}, not '{current_owner_input}'.",
            "error"
        )
        return redirect('/')

    if actual_owner.strip().lower() == new_owner.lower():
        flash("⚠️ Error: New buyer cannot be identical to the current owner.", "error")
        return redirect('/')

    prev_data = latest_block['data']
    data = {
        "type": "TRANSFER PROPERTY",
        "property_id": property_id,
        "previous_owner": actual_owner,
        "owner": new_owner,
        "location": prev_data.get('location', ''),
        "category": prev_data.get('category', ''),
        "area": prev_data.get('area', ''),
        "transfer_reason": transfer_reason,
        "document_hash": prev_data.get('document_hash', 'Mutation-Record')
    }

    prev_block = blockchain.get_last_block()
    new_block = blockchain.create_block(data=data, previous_hash=prev_block['hash'])

    flash(f"✅ Ownership of UPIN #{property_id} legally transferred from '{actual_owner}' to '{new_owner}' in Block #{new_block['index']}!", "success")
    return redirect('/')


@app.route('/records')
def records():
    is_valid, audit_msg = blockchain.is_chain_valid()
    return jsonify({
        "chain": blockchain.chain,
        "valid": is_valid,
        "audit_message": audit_msg
    })


@app.route('/audit_chain', methods=['GET'])
def audit_chain():
    is_valid, audit_msg = blockchain.is_chain_valid()
    return jsonify({
        "valid": is_valid,
        "message": audit_msg,
        "total_blocks": len(blockchain.chain)
    })


@app.route('/search_upin/<property_id>', methods=['GET'])
def search_upin(property_id):
    history = blockchain.get_property_history(property_id)
    if not history:
        return jsonify({'found': False, 'error': f'No blockchain records found for UPIN {property_id}'}), 404

    current_owner, latest_block = blockchain.get_current_owner(property_id)
    return jsonify({
        'found': True,
        'property_id': property_id,
        'current_owner': current_owner,
        'latest_block': latest_block,
        'history': history,
        'total_transactions': len(history)
    })


@app.route('/verify_deed_integrity', methods=['POST'])
def verify_deed_integrity():
    if 'document' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400
    file = request.files['document']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400

    file_bytes = file.read()
    computed_hash = hashlib.sha256(file_bytes).hexdigest()

    matched_block = blockchain.verify_document_hash(computed_hash)
    if matched_block:
        current_owner, _ = blockchain.get_current_owner(matched_block['data'].get('property_id'))
        return jsonify({
            'authentic': True,
            'document_hash': computed_hash,
            'block_index': matched_block['index'],
            'timestamp': matched_block['timestamp'],
            'block_hash': matched_block['hash'],
            'property_data': matched_block['data'],
            'current_owner': current_owner
        })
    else:
        return jsonify({
            'authentic': False,
            'document_hash': computed_hash,
            'message': 'ALERT: This file fingerprint does not match any registered deed on the blockchain. The document is either unregistered or has been modified/tampered with.'
        })


# --- OCR / PDF EXTRACTION ROUTE ---
@app.route('/extract', methods=['POST'])
def extract_document():
    if 'document' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400

    file = request.files['document']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400

    if file:
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)

        try:
            # 1. Compute SHA-256 Cryptographic File Hash for Document Provenance
            with open(filepath, 'rb') as f:
                file_bytes = f.read()
            document_hash = hashlib.sha256(file_bytes).hexdigest()

            # 2. Extract Raw Text from PDF or Image
            text = ""
            if filename.lower().endswith('.pdf'):
                reader = PyPDF2.PdfReader(filepath)
                for page in reader.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text += page_text + "\n"
            else:
                text = pytesseract.image_to_string(Image.open(filepath))

            # 3. Extract Structured Entities (Regex + Optional Gemini AI)
            extracted_data = extract_entities_from_text(text)
            extracted_data['document_hash'] = document_hash

            # Check if UPIN is already registered on blockchain to warn user early
            existing_owner, existing_block = blockchain.get_current_owner(extracted_data.get('property_id', ''))
            if existing_owner:
                extracted_data['already_registered'] = True
                extracted_data['existing_owner'] = existing_owner
                extracted_data['existing_block_index'] = existing_block['index']
            else:
                extracted_data['already_registered'] = False

            # Store signed extraction in server-side session for Zero-Trust validation
            session['verified_extraction'] = extracted_data

            os.remove(filepath)
            return jsonify(extracted_data)

        except Exception as e:
            if os.path.exists(filepath):
                os.remove(filepath)
            return jsonify({'error': str(e)}), 500


# --- MAP LOCATION VERIFICATION ROUTE ---
@app.route('/verify_location', methods=['POST'])
def verify_location():
    data = request.get_json() or {}
    address = data.get('address')

    if not address:
        return jsonify({'error': 'No address provided'}), 400

    url = f"https://nominatim.openstreetmap.org/search?q={urllib.parse.quote(address)}&format=json&limit=1"
    headers = {'User-Agent': 'LandChainIndia_AcademicProject/3.0'}

    try:
        response = requests.get(url, headers=headers, timeout=8)
        results = response.json()

        if results:
            return jsonify({
                'lat': results[0]['lat'],
                'lon': results[0]['lon'],
                'display_name': results[0]['display_name']
            })
        else:
            return jsonify({'error': 'Location not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    app.run(debug=True)

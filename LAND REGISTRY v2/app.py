import os
import re
import requests
import urllib.parse
import pytesseract
import PyPDF2
from PIL import Image
from werkzeug.utils import secure_filename
from flask import Flask, render_template, request, redirect, flash, jsonify
from blockchain import Blockchain

# Hardcode the Tesseract path for Windows (Required for Image OCR fallback)
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

app = Flask(__name__)
app.secret_key = 'secret123'

# Configure upload folder for temporary document storage
app.config['UPLOAD_FOLDER'] = 'uploads/'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

blockchain = Blockchain()

# --- ORIGINAL ROUTES ---
@app.route('/')
def home():
    return render_template('index.html', chain=blockchain.chain)

@app.route('/add', methods=['POST'])
def add_property():
    owner = request.form.get('owner', '').strip()
    location = request.form.get('location', '').strip()
    category = request.form.get('category', '').strip()
    area = request.form.get('area', '').strip()
    property_id = request.form.get('property_id', '').strip()

    # Backend Validation: Prevent empty block minting
    if not all([owner, location, category, area, property_id]):
        flash("❌ Error: All fields must be extracted before registering.")
        return redirect('/')

    data = {
        "type": "ADD PROPERTY",
        "owner": owner,
        "location": location,
        "category": category,
        "area": area,
        "property_id": property_id
    }

    prev_block = blockchain.get_last_block()
    blockchain.create_block(data=data, previous_hash=prev_block['hash'])

    flash("✅ Property successfully registered on blockchain!")
    return redirect('/')

@app.route('/records')
def records():
    return {"chain": blockchain.chain}

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
            text = ""
            # Handle PDF Documents natively
            if filename.lower().endswith('.pdf'):
                reader = PyPDF2.PdfReader(filepath)
                for page in reader.pages:
                    text += page.extract_text() + "\n"
            # Handle Images via OCR
            else:
                text = pytesseract.image_to_string(Image.open(filepath))
            
            # --- Tailored Regex for the Sale Deed ---
            
            # STRICT MULTI-PATH OWNER EXTRACTION
            # Path 1: Requires a Title (Mr./Ms./Mrs./Dr.)
            # Path 2: Requires a Corporate Keyword (Limited/Private/Pvt/Company)
            owner_match = re.search(r'AND\s*\n*(?:(?:Mr\.|Ms\.|Mrs\.|Dr\.)\s+([A-Za-z\s\.]+),|([A-Za-z0-9\s\-\.\&]+?(?:Limited|Ltd\.?|Private|Pvt\.?|Company|LLP)),)', text, re.IGNORECASE)
            
            location_match = re.search(r'(?:bearing No\.|known as)\s*([\s\S]+?)\s*measuring', text, re.IGNORECASE)
            category_match = re.search(r'Approved Use[\s|]*([A-Za-z0-9\(\)/ \-]+?)(?=\s*Actual Use)', text, re.IGNORECASE)
            area_match = re.search(r'Total Area of Plot(?:/Flat|/Unit)?[\s|]*([\d.,]+\s*Sq\.\s*Meters)', text, re.IGNORECASE)
            id_match = re.search(r'document No\.\s*(\d+)', text)
            
            # Resolve the owner name depending on which regex path succeeded
            if owner_match:
                extracted_owner = owner_match.group(1) or owner_match.group(2)
                final_owner = extracted_owner.strip()
            else:
                final_owner = ''
            
            extracted_data = {
                'owner': final_owner,
                'location': location_match.group(1).replace('\n', '').strip(', ') if location_match else '',
                'category': category_match.group(1).strip() if category_match else '',
                'area': area_match.group(1).strip() if area_match else '',
                'property_id': id_match.group(1).strip() if id_match else ''
            }
            
            os.remove(filepath)
            return jsonify(extracted_data)
            
        except Exception as e:
            if os.path.exists(filepath):
                os.remove(filepath)
            return jsonify({'error': str(e)}), 500

# --- MAP LOCATION VERIFICATION ROUTE ---
@app.route('/verify_location', methods=['POST'])
def verify_location():
    data = request.get_json()
    address = data.get('address')
    
    if not address:
        return jsonify({'error': 'No address provided'}), 400
        
    url = f"https://nominatim.openstreetmap.org/search?q={urllib.parse.quote(address)}&format=json&limit=1"
    headers = {'User-Agent': 'LandChainIndia_AcademicProject/1.0'}
    
    try:
        response = requests.get(url, headers=headers)
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
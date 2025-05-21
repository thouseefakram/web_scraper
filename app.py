from flask import Flask, request, jsonify, send_from_directory, send_file
from flask_cors import CORS
from playwright.sync_api import sync_playwright
import json
import os
import threading
import time
from queue import Queue
from hashlib import md5
import io

app = Flask(__name__)
CORS(app)

# Global variables
scraping_thread = None
browser_instance = None
data_queue = Queue()
scraping_active = False
output_file = 'scraped_data.json'
current_page_data = []
seen_items = set()

def get_content_hash(content):
    """Generate hash for content to detect duplicates"""
    content_str = '|'.join(content)
    return md5(content_str.encode()).hexdigest()

def run_scraper(target_url, container_classes, scrape_images):
    global browser_instance, scraping_active, current_page_data
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        browser_instance = browser
        context = browser.new_context()
        page = context.new_page()
        
        try:
            page.goto(target_url)
            last_url = page.url
            
            while scraping_active:
                # Check if URL changed
                if page.url != last_url:
                    if current_page_data:
                        data_queue.put({
                            "url": last_url,
                            "items": current_page_data.copy()
                        })
                        current_page_data.clear()
                    last_url = page.url
                
                # Scrape current page
                try:
                    # Split the container_classes string into individual class names
                    class_list = [cls.strip() for cls in container_classes.split(',')]
                    
                    # Process each class separately
                    for container_class in class_list:
                        # Remove any leading . if present
                        clean_class = container_class.lstrip('.')
                        containers = page.query_selector_all(f'.{clean_class}')
                        
                        for container in containers:
                            content = container.inner_text().strip().split("\n")
                            content = [part.strip() for part in content if part.strip()]
                            
                            if not content:
                                continue
                                
                            content_hash = get_content_hash(content)
                            if content_hash in seen_items:
                                continue
                            seen_items.add(content_hash)
                            
                            item = {
                                "content": content,
                                "source_class": clean_class  # Add which class this came from
                            }
                            
                            if scrape_images:
                                images = container.query_selector_all('img')
                                item["images"] = [
                                    img.get_attribute('src') 
                                    for img in images 
                                    if img.get_attribute('src')
                                ]
                            
                            current_page_data.append(item)
                    
                    if current_page_data:
                        save_data()
                
                except Exception as e:
                    print(f"Scraping error: {e}")
                
                try:
                    page.wait_for_timeout(3000)
                except:
                    break
                
        finally:
            if current_page_data:
                data_queue.put({
                    "url": last_url,
                    "items": current_page_data.copy()
                })
                current_page_data.clear()
                save_data()
            browser.close()
            scraping_active = False

def save_data():
    try:
        page_data = {
            "url": data_queue.queue[-1]["url"],
            "items": data_queue.queue[-1]["items"]
        }
        
        existing_data = []
        if os.path.exists(f'static/{output_file}'):
            with open(f'static/{output_file}', 'r') as f:
                existing_data = json.load(f)
        
        existing_data.append(page_data)
        
        with open(f'static/{output_file}', 'w') as f:
            json.dump(existing_data, f, indent=2)
    except Exception as e:
        print(f"Error saving data: {e}")

@app.route('/api/start_scraping', methods=['POST'])
def start_scraping():
    global scraping_thread, scraping_active, current_page_data, seen_items
    
    if scraping_active:
        return jsonify({"status": "error", "message": "Scraping already in progress"})
    
    data = request.get_json()
    target_url = data.get('target_url')
    container_classes = data.get('container_class')
    scrape_images = data.get('scrape_images', False)
    
    if not target_url or not container_classes:
        return jsonify({"status": "error", "message": "Missing required parameters"})
    
    current_page_data = []
    seen_items = set()
    if os.path.exists(f'static/{output_file}'):
        os.remove(f'static/{output_file}')
    
    scraping_active = True
    
    scraping_thread = threading.Thread(
        target=run_scraper,
        args=(target_url, container_classes, scrape_images)
    )
    scraping_thread.start()
    
    return jsonify({"status": "success", "message": "Scraping started"})

@app.route('/api/get_updates', methods=['GET'])
def get_updates():
    if data_queue.empty():
        return jsonify({"status": "no_data"})
    
    updates = []
    while not data_queue.empty():
        updates.append(data_queue.get())
    
    return jsonify({"status": "success", "data": updates})

@app.route('/api/stop_scraping', methods=['POST'])
def stop_scraping():
    global scraping_active, browser_instance
    
    scraping_active = False
    if browser_instance:
        try:
            browser_instance.close()
        except:
            pass
    
    return jsonify({"status": "success", "message": "Scraping stopped"})

@app.route('/api/check_status', methods=['GET'])
def check_status():
    return jsonify({
        "scraping_active": scraping_active,
        "browser_open": browser_instance is not None and browser_instance.is_connected()
    })

@app.route('/api/download_data', methods=['GET'])
def download_data():
    if not os.path.exists(f'static/{output_file}'):
        return jsonify({"status": "error", "message": "No data available"}), 404
    
    with open(f'static/{output_file}', 'r') as f:
        data = json.load(f)
    
    # Create in-memory file
    mem_file = io.BytesIO()
    mem_file.write(json.dumps(data, indent=2).encode('utf-8'))
    mem_file.seek(0)
    
    return send_file(
        mem_file,
        mimetype='application/json',
        as_attachment=True,
        download_name='scraped_data.json'
    )

@app.route('/')
def serve_frontend():
    return send_from_directory('.', 'index.html')

if __name__ == '__main__':
    os.makedirs('static', exist_ok=True)
    app.run(debug=True, threaded=True)
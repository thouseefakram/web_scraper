from flask import Flask, request, jsonify, send_from_directory
import json
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
import os
from flask_cors import CORS
from flask import send_from_directory
import base64

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# Serve static files
@app.route('/')
def serve_frontend():
    return send_from_directory('.', 'index.html')

@app.route('/api/scrape', methods=['POST'])
def scrape():
    # Get form data
    data = request.get_json()
    target_url = data.get('target_url')
    container_class = data.get('container_class')
    output_file = data.get('output_file', 'scraped_data.json')
    need_login = data.get('need_login', 'no')
    login_url = data.get('login_url', '')
    scrape_images = data.get('scrape_images', 'no')

    # Validate inputs
    if not target_url or not container_class:
        return jsonify({
            'status': 'error',
            'message': 'Target URL and Container Class are required fields'
        }), 400

    # Run the scraper
    try:
        result = run_scraper(target_url, container_class, output_file, need_login, login_url, scrape_images)
        return jsonify({
            'status': 'success',
            'message': 'Scraping completed successfully!',
            'output_file': output_file,
            'data': result
        })
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

def run_scraper(target_url, container_class, output_file, need_login, login_url, scrape_images):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()

        try:
            if need_login.lower() == "yes":
                # Open login page for manual login
                page.goto(login_url)
                # Wait for manual login
                page.wait_for_timeout(30000)  # Wait 30 seconds for manual login
                # After login, go directly to target URL
                page.goto(target_url)
            else:
                # Navigate directly to the target page if no login needed
                page.goto(target_url)

            # Wait for selector with timeout and custom error message
            try:
                page.wait_for_selector(
                    f'.{container_class.replace(" ", ".")}',
                    timeout=10000,  # 10 seconds timeout
                    state='attached'
                )
            except PlaywrightTimeoutError:
                raise Exception(f"No elements found with class name: '{container_class}'. Please check the class name and try again.")

            # Scrape content inside the container
            containers = page.query_selector_all(f'.{container_class.replace(" ", ".")}')
            
            if not containers:
                raise Exception(f"Class name '{container_class}' exists but no elements found. The elements might be dynamically loaded.")

            data = []

            for idx, container in enumerate(containers, 1):
                # Get text content
                content = container.inner_text().strip().split("\n")
                content = [part.strip() for part in content if part.strip()]  # Filter out empty strings
                
                container_data = {"container_number": idx}
                
                # Add text content
                for i, part in enumerate(content, 1):
                    container_data[f"content-{i}"] = part

                # Add images if requested
                if scrape_images.lower() == "yes":
                    images = container.query_selector_all('img')
                    image_data = []
                    for img_idx, img in enumerate(images, 1):
                        try:
                            # Get image source
                            src = img.get_attribute('src')
                            if src:
                                if src.startswith('data:image'):
                                    # Handle base64 encoded images
                                    image_data.append({
                                        f"image-{img_idx}": src
                                    })
                                else:
                                    # Download and encode external images
                                    img_bytes = img.screenshot()
                                    encoded_image = base64.b64encode(img_bytes).decode('utf-8')
                                    image_data.append({
                                        f"image-{img_idx}": f"data:image/png;base64,{encoded_image}"
                                    })
                        except Exception as e:
                            print(f"Error processing image: {e}")
                            continue
                    
                    if image_data:
                        container_data["images"] = image_data

                data.append(container_data)

            # Save to JSON file
            os.makedirs('static', exist_ok=True)
            with open(os.path.join('static', output_file), "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)

            return data

        except Exception as e:
            raise Exception(f"Scraping failed: {str(e)}")
        finally:
            browser.close()

if __name__ == '__main__':
    os.makedirs('static', exist_ok=True)
    app.run(debug=True)
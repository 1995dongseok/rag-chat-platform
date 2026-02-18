import requests
from bs4 import BeautifulSoup

def fetch_url_content(url: str) -> str:
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, "html.parser")
        
        content = soup.find('main') or soup.find('article') or soup.find('body')
        
        if content:
            for tag in content(["script", "style", "nav", "footer", "header", "aside"]):
                tag.decompose()
            text = content.get_text(separator="\n", strip=True)
        else:
            text = soup.get_text(separator="\n", strip=True)
            
        return f"[Source URL]: {url}\n\n{text}"
    except Exception as e:
        return f"Error: {str(e)}"
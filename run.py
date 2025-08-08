import subprocess
import uvicorn
from main import app

if __name__ == "__main__":
    
    subprocess.run(["playwright", "install", "chromium"], check=True)
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=7860,
        proxy_headers=True,
        forwarded_allow_ips="*"
    )


  

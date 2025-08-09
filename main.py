from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse, Response
from playwright.async_api import async_playwright
import os, uuid, shutil, asyncio, time, stat
from collections import defaultdict

app = FastAPI(
    title="Brat Generator By RaolByte",
    description="API for generating BRAT-style text images & videos.",
    version="1.0.1",
)

def _ensure_dir(path: str) -> str:
    """
    Ensures the directory can be created and written to. If it fails, falls back to /tmp.
    Sets 0777 permissions for safety in non-root containers.
    """
    try:
        os.makedirs(path, exist_ok=True)
        os.chmod(path, stat.S_IRWXU | stat.S_IRWXG | stat.S_IRWXO)  # 0o777
        return path
    except Exception:
        fallback = os.path.join("/tmp", os.path.basename(path))
        os.makedirs(fallback, exist_ok=True)
        os.chmod(fallback, stat.S_IRWXU | stat.S_IRWXG | stat.S_IRWXO)
        return fallback

OUTPUT_DIR = _ensure_dir(os.environ.get("OUTPUT_DIR", os.path.join(os.getcwd(), "output")))
TMP_DIR    = _ensure_dir(os.environ.get("TMP_DIR",     os.path.join(os.getcwd(), "tmp_brat")))

REQUEST_LIMIT = 10   # Max requests allowed
TIME_WINDOW   = 60   # Time window in seconds (1 minute)
BAN_DURATION  = 300  # Ban duration in seconds (5 minutes)

request_logs: dict[str, list[float]] = defaultdict(list)
banned_ips: dict[str, float] = {}

def get_client_ip(request: Request) -> str:
    cf = request.headers.get("CF-Connecting-IP")
    if cf:
        return cf.strip()
    xff = request.headers.get("X-Forwarded-For")
    if xff:
        return xff.split(",")[0].strip()
    return (request.client.host or "").strip()

@app.middleware("http")
async def anti_ddos_middleware(request: Request, call_next):
    ip = get_client_ip(request)
    now = time.time()

    if ip in banned_ips:
        if now < banned_ips[ip]:
            return JSONResponse(
                status_code=429,
                content={"error": "IP is blocked for 5 minutes due to too many requests."},
            )
        else:
            del banned_ips[ip]

    window = [ts for ts in request_logs[ip] if now - ts < TIME_WINDOW]
    window.append(now)
    request_logs[ip] = window

    if len(request_logs[ip]) > REQUEST_LIMIT:
        banned_ips[ip] = now + BAN_DURATION
        return JSONResponse(
            status_code=429,
            content={"error": "Too many requests. IP is blocked for 5 minutes."},
        )

    return await call_next(request)


async def delete_file_after_delay(filepath: str, delay: int = 600):
    await asyncio.sleep(delay)
    try:
        if os.path.exists(filepath):
            os.remove(filepath)
    except Exception:
        pass
    
@app.get("/maker/brat", tags=["maker"], summary="Generate BRAT text image")
async def generate_brat(
    request: Request,
    text: str = Query(..., description="Text to be inserted into the BRAT image"),
    background: str | None = Query(None, description="Background color (e.g., #000000)"),
    color: str | None = Query(None, description="Text color (e.g., #FFFFFF)"),
):
    text = (text or "").strip()
    if not text:
        return JSONResponse(status_code=400, content={"error": "Text cannot be empty."})

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(args=["--no-sandbox"])
            context = await browser.new_context(viewport={"width": 1536, "height": 695})
            page = await context.new_page()
            await page.goto("https://www.bratgenerator.com/", wait_until="domcontentloaded")

            try:
                await page.click("text=Accept", timeout=3000)
            except Exception:
                pass

            await page.click("#toggleButtonWhite")
            await page.click("#textOverlay")
            await page.click("#textInput")
            await page.fill("#textInput", text)

            await page.evaluate(
                """(data) => {
                    if (data.background) $('.node__content.clearfix').css('background-color', data.background);
                    if (data.color) $('.textFitted').css('color', data.color);
                }""",
                {"background": background, "color": color},
            )

            await asyncio.sleep(0.5)

            element = await page.query_selector("#textOverlay")
            if not element:
                await browser.close()
                return JSONResponse(status_code=500, content={"error": "Target element not found."})
            box = await element.bounding_box()
            if not box:
                await browser.close()
                return JSONResponse(status_code=500, content={"error": "Failed to read element bounding box."})

            filename = f"brat_{uuid.uuid4().hex[:8]}.png"
            filepath = os.path.join(OUTPUT_DIR, filename)

            screenshot = await page.screenshot(
                clip={"x": box["x"], "y": box["y"], "width": 500, "height": 440}
            )
            with open(filepath, "wb") as f:
                f.write(screenshot)

            await context.close()
            await browser.close()

        asyncio.create_task(delete_file_after_delay(filepath))
        base_url = str(request.base_url).rstrip("/")
        return {"status": "success", "image_url": f"{base_url}/download/file/{filename}"}

    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"Failed to generate image: {str(e)}"})

@app.get("/maker/bratvid", tags=["maker"], summary="Create animated video from BRAT text")
async def generate_brat_video(
    request: Request,
    text: str = Query(..., description="Sentence to be animated (space-separated)"),
    background: str | None = Query(None, description="Background color (e.g., #000000)"),
    color: str | None = Query(None, description="Text color (e.g., #FFFFFF)"),
):
    text = (text or "").strip()
    if not text:
        return JSONResponse(status_code=400, content={"error": "Text cannot be empty."})

    words = text.split()
    if not words:
        return JSONResponse(status_code=400, content={"error": "Text must contain at least one word."})

    temp_dir = _ensure_dir(os.path.join(TMP_DIR, str(uuid.uuid4())))

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(args=["--no-sandbox"])
            context = await browser.new_context(viewport={"width": 1536, "height": 695})
            page = await context.new_page()
            await page.goto("https://www.bratgenerator.com/", wait_until="domcontentloaded")

            try:
                await page.click("text=Accept", timeout=3000)
            except Exception:
                pass

            await page.click("#toggleButtonWhite")
            await page.click("#textOverlay")
            await page.click("#textInput")

            for i in range(len(words)):
                partial_text = " ".join(words[: i + 1])
                await page.fill("#textInput", partial_text)

                await page.evaluate(
                    """(data) => {
                        if (data.background) $('.node__content.clearfix').css('background-color', data.background);
                        if (data.color) $('.textFitted').css('color', data.color);
                    }""",
                    {"background": background, "color": color},
                )

                await asyncio.sleep(0.2)

                element = await page.query_selector("#textOverlay")
                if not element:
                    await context.close()
                    await browser.close()
                    shutil.rmtree(temp_dir, ignore_errors=True)
                    return JSONResponse(status_code=500, content={"error": "Target element not found."})
                box = await element.bounding_box()
                if not box:
                    await context.close()
                    await browser.close()
                    shutil.rmtree(temp_dir, ignore_errors=True)
                    return JSONResponse(status_code=500, content={"error": "Failed to read element bounding box."})

                screenshot = await page.screenshot(
                    clip={"x": box["x"], "y": box["y"], "width": 500, "height": 440}
                )
                frame_path = os.path.join(temp_dir, f"frame{i:03d}.png")
                with open(frame_path, "wb") as f:
                    f.write(screenshot)

            await context.close()
            await browser.close()

        # Render video with ffmpeg
        output_filename = f"bratvid_{uuid.uuid4().hex[:8]}.mp4"
        output_path = os.path.join(OUTPUT_DIR, output_filename)

        ffmpeg_cmd = [
            "ffmpeg",
            "-y",
            "-framerate", "1.428",
            "-i", os.path.join(temp_dir, "frame%03d.png"),
            "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2,fps=30",
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-pix_fmt", "yuv420p",
            output_path,
        ]

        process = await asyncio.create_subprocess_exec(
            *ffmpeg_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await process.communicate()

        if process.returncode != 0:
            shutil.rmtree(temp_dir, ignore_errors=True)
            return JSONResponse(status_code=500, content={"error": stderr.decode()})

        asyncio.create_task(delete_file_after_delay(output_path))
        base_url = str(request.base_url).rstrip("/")
        return {"status": "success", "video_url": f"{base_url}/download/file/{output_filename}"}

    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

@app.get("/download/file/{filename}")
async def download_file(filename: str):
    filepath = os.path.join(OUTPUT_DIR, filename)
    if not os.path.exists(filepath):
        return JSONResponse(status_code=404, content={"error": "File not found"})
        
    with open(filepath, "rb") as f:
        data = f.read()
    return Response(data, media_type="application/octet-stream")

@app.get("/")
async def root():
    return {"status": "ok", "service": "brat-generator", "output_dir": OUTPUT_DIR, "tmp_dir": TMP_DIR}

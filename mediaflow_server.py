# ============================================================
#  MediaFlow — mediaflow_server.py
#  FastAPI + PostgreSQL + yt-dlp
#  Đã fix: TikTok MP4, download trigger, format handling
# ============================================================

from fastapi import FastAPI, HTTPException, Header, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from collections import defaultdict
from sqlalchemy import create_engine, Column, Integer, String, DateTime, BigInteger, Text
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
import uuid, time, re, logging, os, yt_dlp

# ============================================================
#  CẤU HÌNH — SỬA Ở ĐÂY
# ============================================================
DB_USER       = os.getenv("DB_USER",       "postgres")
DB_PASSWORD   = os.getenv("DB_PASSWORD",   "18112006")      
DB_HOST       = os.getenv("DB_HOST",       "localhost")
DB_PORT       = os.getenv("DB_PORT",       "5432")
DB_NAME       = os.getenv("DB_NAME",       "mediaflow")
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "mediaflow-admin-2025")
DOWNLOAD_DIR  = os.getenv("DOWNLOAD_DIR",  "downloads")

os.makedirs(DOWNLOAD_DIR, exist_ok=True)

ALLOWED_ORIGINS = [
    "http://localhost:5500",
    "http://127.0.0.1:5500",
    "http://localhost:3000",
    os.getenv("FRONTEND_URL", ""),
]

MAX_WRONG_KEY  = 10
BLOCK_SECONDS  = 3600
MAX_REQ_MINUTE = 30

# ============================================================
#  LOGGING
# ============================================================
logging.basicConfig(
    level   = logging.INFO,
    format  = "%(asctime)s [%(levelname)s] %(message)s",
    handlers= [logging.FileHandler("mediaflow.log"), logging.StreamHandler()]
)
log = logging.getLogger("mediaflow")

# ============================================================
#  DATABASE
# ============================================================
DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
engine       = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
Base         = declarative_base()

class HistoryModel(Base):
    __tablename__ = "download_history"
    id         = Column(Integer,  primary_key=True, index=True)
    platform   = Column(String(20))
    title      = Column(String(200))
    quality    = Column(String(10))
    format     = Column(String(10))
    size       = Column(String(20), default="~0 MB")
    source_url = Column(Text,       nullable=True)
    ip_address = Column(String(50), nullable=True)
    created_at = Column(DateTime,   default=datetime.now)

class FileModel(Base):
    __tablename__ = "files"
    id           = Column(Integer,    primary_key=True, index=True)
    filename     = Column(String(200))
    file_size    = Column(BigInteger, default=0)
    download_url = Column(Text,       nullable=True)
    platform     = Column(String(20), nullable=True)
    format       = Column(String(10), nullable=True)
    quality      = Column(String(10), nullable=True)
    created_at   = Column(DateTime,   default=datetime.now)

Base.metadata.create_all(bind=engine)

# ============================================================
#  APP + RATE LIMITER
# ============================================================
limiter           = Limiter(key_func=get_remote_address)
wrong_key_tracker = defaultdict(lambda: {"count": 0, "blocked_until": 0})
request_tracker   = defaultdict(list)

app = FastAPI(title="MediaFlow API", version="2.4.1")
app.state.limiter = limiter

# Serve file tĩnh → /files/ten_file.mp4
app.mount("/files", StaticFiles(directory=DOWNLOAD_DIR), name="files")

@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(status_code=429, content={"detail": "Quá nhiều yêu cầu! Thử lại sau."})

# ── CORS ─────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins = [o for o in ALLOWED_ORIGINS if o],
    allow_methods = ["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers = ["*"],
)

# ── Security Middleware ───────────────────────────────────────
class SecurityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        ip  = request.client.host
        now = time.time()
        t   = wrong_key_tracker[ip]

        if t["blocked_until"] > now:
            remaining = int(t["blocked_until"] - now)
            return JSONResponse(status_code=403, content={"detail": f"IP bị khóa. Thử lại sau {remaining}s."})

        request_tracker[ip] = [x for x in request_tracker[ip] if now - x < 60]
        if len(request_tracker[ip]) >= MAX_REQ_MINUTE:
            return JSONResponse(status_code=429, content={"detail": "Quá nhiều yêu cầu!"})
        request_tracker[ip].append(now)

        path = request.url.path
        for bad in ["/wp-admin", "/phpMyAdmin", "/.env", "/.git", "/etc/passwd"]:
            if path.startswith(bad):
                return JSONResponse(status_code=404, content={"detail": "Not found"})

        ua = request.headers.get("user-agent", "").lower()
        for bot in ["sqlmap", "nikto", "nmap", "masscan", "zgrab"]:
            if bot in ua:
                return JSONResponse(status_code=403, content={"detail": "Forbidden"})

        log.info(f"[REQ] {ip} {request.method} {path}")
        return await call_next(request)

app.add_middleware(SecurityMiddleware)

# ============================================================
#  DEPENDENCY
# ============================================================
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def verify_key(request: Request, x_api_key: str = Header(...)):
    ip  = request.client.host
    now = time.time()
    t   = wrong_key_tracker[ip]

    if t["blocked_until"] > now:
        raise HTTPException(403, "IP bị khóa!")

    if x_api_key != ADMIN_API_KEY:
        t["count"] += 1
        log.warning(f"[WRONG KEY] {ip} — lần {t['count']}/{MAX_WRONG_KEY}")
        if t["count"] >= MAX_WRONG_KEY:
            t["blocked_until"] = now + BLOCK_SECONDS
            t["count"] = 0
            raise HTTPException(403, f"IP bị khóa {BLOCK_SECONDS // 60} phút!")
        raise HTTPException(403, f"API key sai! Còn {MAX_WRONG_KEY - t['count']} lần.")

    t["count"]         = 0
    t["blocked_until"] = 0

# ============================================================
#  SCHEMAS
# ============================================================
class AnalyzeRequest(BaseModel):
    url:      str
    platform: Optional[str] = "unknown"

class DownloadRequest(BaseModel):
    url:      str
    platform: Optional[str] = "unknown"
    quality:  Optional[str] = "best"
    format:   Optional[str] = "MP4"

class ToolRequest(BaseModel):
    filePath: Optional[str] = ""

class ShareRequest(BaseModel):
    platform: Optional[str] = "copy"
    url:      Optional[str] = ""

class CloudRequest(BaseModel):
    filePath: Optional[str] = ""

# ============================================================
#  HELPERS
# ============================================================
def detect_platform(url: str) -> str:
    if "tiktok.com"   in url: return "tiktok"
    if "youtube.com"  in url: return "youtube"
    if "youtu.be"     in url: return "youtube"
    if "facebook.com" in url: return "facebook"
    if "fb.watch"     in url: return "facebook"
    return "unknown"

def validate_url(url: str) -> bool:
    pattern = re.compile(r'^https?://[^\s/$.?#].[^\s]*$', re.IGNORECASE)
    return bool(pattern.match(url)) and len(url) < 2048

def scan_safe(url: str) -> bool:
    bad = ["javascript:", "data:", "vbscript:", "../", "<script", "onerror="]
    return not any(b in url.lower() for b in bad)

def fmt_date(dt) -> str:
    return dt.strftime("%H:%M %d/%m/%Y") if dt else ""

def get_ip(request: Request) -> str:
    fwd = request.headers.get("X-Forwarded-For")
    return fwd.split(",")[0].strip() if fwd else request.client.host

# ============================================================
#  YT-DLP FORMAT — xử lý đúng từng nền tảng
# ============================================================
def get_ydl_opts(platform: str, quality: str, fmt: str, output_path: str) -> dict:
    fmt_lower = fmt.lower()
    is_audio  = quality == "Audio" or fmt_lower in ["mp3", "flac", "wav", "m4a"]

    # ── AUDIO (MP3, FLAC, WAV) ───────────────────────────────
    if is_audio:
        codec = fmt_lower if fmt_lower in ["mp3", "flac", "wav", "m4a"] else "mp3"
        return {
            "format":        "bestaudio/best",
            "outtmpl":       output_path,
            "noplaylist":    True,
            "quiet":         True,
            "no_warnings":   True,
            "postprocessors": [{
                "key":              "FFmpegExtractAudio",
                "preferredcodec":   codec,
                "preferredquality": "192",
            }],
        }

    # ── TIKTOK — không hỗ trợ chọn height cụ thể ────────────
    # TikTok chỉ có 1 độ phân giải duy nhất mỗi video
    if platform == "tiktok":
        return {
            "format":              "bestvideo+bestaudio/best",
            "outtmpl":             output_path,
            "noplaylist":          True,
            "quiet":               True,
            "no_warnings":         True,
            "merge_output_format": "mp4",
        }

    # ── YOUTUBE / FACEBOOK — chọn quality theo height ────────
    height_map = {"4K": 2160, "1080p": 1080, "720p": 720, "480p": 480, "best": 1080}
    height     = height_map.get(quality, 1080)

    return {
        "format":              f"bestvideo[height<={height}][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<={height}]+bestaudio/best",
        "outtmpl":             output_path,
        "noplaylist":          True,
        "quiet":               True,
        "no_warnings":         True,
        "merge_output_format": "mp4",
    }

# ============================================================
#  YT-DLP — Lấy thông tin video (không tải)
# ============================================================
def fetch_video_info(url: str) -> dict:
    opts = {"quiet": True, "no_warnings": True, "skip_download": True, "noplaylist": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info     = ydl.extract_info(url, download=False)
        duration = info.get("duration", 0) or 0
        mins, secs = divmod(int(duration), 60)
        return {
            "title":     info.get("title", "Video"),
            "duration":  f"{mins}:{secs:02d}",
            "uploader":  info.get("uploader", ""),
            "thumbnail": info.get("thumbnail", ""),
            "platform":  info.get("extractor_key", "").lower(),
        }

# ============================================================
#  YT-DLP — Tải video thật
# ============================================================
def do_download(url: str, platform: str, quality: str, fmt: str, output_id: str) -> dict:
    output_path = os.path.join(DOWNLOAD_DIR, f"{output_id}.%(ext)s")
    opts        = get_ydl_opts(platform, quality, fmt, output_path)

    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])

    # Tìm file vừa tải trong thư mục downloads
    for f in sorted(os.listdir(DOWNLOAD_DIR)):
        if f.startswith(output_id):
            full_path = os.path.join(DOWNLOAD_DIR, f)
            return {
                "filename":  f,
                "file_size": os.path.getsize(full_path),
            }

    raise Exception("Không tìm thấy file sau khi tải!")

# ============================================================
#  HEALTH
# ============================================================
@app.get("/api/health")
def health():
    return {
        "status":    "UP",
        "service":   "MediaFlow — FastAPI + PostgreSQL + yt-dlp",
        "version":   "2.4.1",
        "yt_dlp":    yt_dlp.version.__version__,
        "protected": True,
    }

# ============================================================
#  ANALYZE
# ============================================================
@app.post("/api/media/analyze")
@limiter.limit("20/minute")
def analyze(request: Request, req: AnalyzeRequest, _=Depends(verify_key)):
    if not req.url or not validate_url(req.url):
        raise HTTPException(400, "URL không hợp lệ!")
    if not scan_safe(req.url):
        raise HTTPException(400, "URL không an toàn!")

    platform = detect_platform(req.url) if req.platform == "unknown" else req.platform

    try:
        info = fetch_video_info(req.url)
        return {
            "title":    info["title"],
            "meta":     f"{platform.capitalize()} · {info['duration']} · {info['uploader']}",
            "platform": platform,
            "thumbnail":info["thumbnail"],
            "safe":     True,
            "availableQualities": ["best", "1080p", "720p", "480p", "Audio"],
        }
    except Exception as e:
        log.error(f"[ANALYZE ERROR] {e}")
        return {
            "title":    "Video đã phát hiện",
            "meta":     f"{platform.capitalize()} · Sẵn sàng tải",
            "platform": platform,
            "safe":     True,
            "availableQualities": ["best", "1080p", "720p", "480p", "Audio"],
        }

# ============================================================
#  DOWNLOAD
# ============================================================
@app.post("/api/media/download")
@limiter.limit("10/minute")
def download(request: Request, req: DownloadRequest,
             db: Session = Depends(get_db), _=Depends(verify_key)):
    if not req.url or not validate_url(req.url):
        raise HTTPException(400, "URL không hợp lệ!")
    if not scan_safe(req.url):
        raise HTTPException(400, "URL không an toàn!")

    platform  = detect_platform(req.url) if req.platform == "unknown" else req.platform
    output_id = f"{platform}_{uuid.uuid4().hex[:8]}"
    ip        = get_ip(request)

    log.info(f"[DOWNLOAD START] {ip} ← {platform} {req.quality} {req.format} ← {req.url[:60]}")

    try:
        result    = do_download(req.url, platform, req.quality, req.format, output_id)
        filename  = result["filename"]
        file_size = result["file_size"]
    except Exception as e:
        log.error(f"[DOWNLOAD ERROR] {e}")
        raise HTTPException(500, f"Tải thất bại: {str(e)}")

    # Lưu vào database
    try:
        db.add(FileModel(
            filename=filename, file_size=file_size,
            download_url=f"/files/{filename}",
            platform=platform, format=req.format, quality=req.quality,
        ))
        db.add(HistoryModel(
            platform=platform,
            title=f"{platform.capitalize()} — {filename}",
            quality=req.quality, format=req.format,
            size=f"{round(file_size / (1024 * 1024), 1)} MB",
            source_url=req.url, ip_address=ip,
        ))
        db.commit()
    except Exception as e:
        log.error(f"[DB ERROR] {e}")

    log.info(f"[DOWNLOAD OK] {filename} — {round(file_size/(1024*1024),1)} MB")

    # Tạo token 1 lần dùng để browser tải file không cần header
    dl_token = uuid.uuid4().hex
    download_tokens[dl_token] = filename

    return {
        "filename":    filename,
        "fileSize":    file_size,
        "sizeMB":      round(file_size / (1024 * 1024), 1),
        "downloadUrl": f"/api/download/{dl_token}",
        "token":       dl_token,
        "status":      "success",
    }

# ── Endpoint tải file về máy ─────────────────────────────────

# Lưu token tạm thời để xác thực download (token → filename)
download_tokens: dict = {}

@app.get("/api/download/{token}")
def serve_file(token: str):
    # Kiểm tra token hợp lệ
    filename = download_tokens.get(token)
    if not filename:
        raise HTTPException(403, "Link tải đã hết hạn hoặc không hợp lệ!")

    # Chặn path traversal
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(400, "Tên file không hợp lệ!")

    path = os.path.join(DOWNLOAD_DIR, filename)
    if not os.path.exists(path):
        raise HTTPException(404, "File không tồn tại!")

    # Xóa token sau khi dùng (1 lần duy nhất)
    del download_tokens[token]

    return FileResponse(
        path,
        media_type="application/octet-stream",
        filename=filename,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ============================================================
#  HISTORY
# ============================================================
@app.get("/api/history")
def get_history(db: Session = Depends(get_db), _=Depends(verify_key)):
    items = db.query(HistoryModel).order_by(HistoryModel.created_at.desc()).limit(50).all()
    return [
        {"platform": h.platform, "title": h.title, "quality": h.quality,
         "format": h.format, "size": h.size, "date": fmt_date(h.created_at)}
        for h in items
    ]

@app.delete("/api/history/{hid}")
def delete_history(hid: int, db: Session = Depends(get_db), _=Depends(verify_key)):
    item = db.query(HistoryModel).filter(HistoryModel.id == hid).first()
    if not item: raise HTTPException(404, "Không tìm thấy!")
    db.delete(item); db.commit()
    return {"message": "Đã xóa!"}

# ============================================================
#  FILES
# ============================================================
@app.get("/api/files")
def get_files(db: Session = Depends(get_db), _=Depends(verify_key)):
    files = db.query(FileModel).order_by(FileModel.created_at.desc()).limit(50).all()
    return [
        {"id": f.id, "filename": f.filename, "fileSize": f.file_size,
         "downloadUrl": f.download_url, "platform": f.platform,
         "format": f.format, "quality": f.quality, "date": fmt_date(f.created_at)}
        for f in files
    ]

@app.delete("/api/files/{fid}")
def delete_file(fid: int, db: Session = Depends(get_db), _=Depends(verify_key)):
    f = db.query(FileModel).filter(FileModel.id == fid).first()
    if not f: raise HTTPException(404, "Không tìm thấy!")
    path = os.path.join(DOWNLOAD_DIR, f.filename)
    if os.path.exists(path): os.remove(path)
    db.delete(f); db.commit()
    return {"message": "Đã xóa!"}

# ============================================================
#  TOOLS
# ============================================================
TOOL_LABELS = {
    "MP3": "→ MP3",  "MP4": "→ MP4",   "FLAC": "→ FLAC", "WAV": "→ WAV",
    "JPG": "→ JPG",  "PNG": "→ PNG",   "WEBP": "→ WEBP",
    "removeWatermark": "Xóa Watermark", "resize": "Resize",
    "crop": "Crop",  "compress": "Nén ảnh", "gallery": "Tạo Gallery",
    "downloadSub": "Tải phụ đề",   "embedSub": "Nhúng phụ đề",
    "downloadThumb": "Tải Thumbnail",
    "saveFile": "Lưu file",        "renameFile": "Đổi tên",
    "deleteFile": "Xóa file",      "historyLog": "Lịch sử",
    "saveToDrive": "Google Drive", "saveToOneDrive": "OneDrive",
}

@app.post("/api/tools/{action}")
@limiter.limit("15/minute")
def use_tool(request: Request, action: str,
             req: ToolRequest = ToolRequest(), _=Depends(verify_key)):
    if action not in TOOL_LABELS:
        raise HTTPException(404, f"Tool không tồn tại: {action}")
    ext_map = {"MP3":"mp3","MP4":"mp4","FLAC":"flac","WAV":"wav","JPG":"jpg","PNG":"png","WEBP":"webp"}
    output  = req.filePath
    if action in ext_map and output:
        output = f"{output.rsplit('.', 1)[0]}.{ext_map[action]}"
    return {"action": action, "label": TOOL_LABELS[action],
            "output": output or f"output_{uuid.uuid4().hex[:6]}", "status": "success"}

# ============================================================
#  SHARE
# ============================================================
SHARE_BASE = {
    "facebook": "https://www.facebook.com/sharer/sharer.php?u=",
    "telegram": "https://t.me/share/url?url=",
    "zalo":     "https://zalo.me/share?u=",
}

@app.post("/api/share")
def share(req: ShareRequest, _=Depends(verify_key)):
    base = SHARE_BASE.get(req.platform, "")
    return {"shareUrl": f"{base}{req.url}" if base else req.url, "status": "success"}

@app.post("/api/share/link")
def generate_link(_=Depends(verify_key)):
    return {"link": f"https://mediaflow.app/share/{uuid.uuid4().hex[:10]}", "expiresIn": "24h"}

# ============================================================
#  CLOUD
# ============================================================
@app.post("/api/cloud/drive")
def save_to_drive(req: CloudRequest, _=Depends(verify_key)):
    return {"driveUrl": "https://drive.google.com", "status": "coming_soon"}

@app.post("/api/cloud/onedrive")
def save_to_onedrive(req: CloudRequest, _=Depends(verify_key)):
    return {"oneDriveUrl": "https://onedrive.live.com", "status": "coming_soon"}

# ============================================================
#  CHẠY
# ============================================================
if __name__ == "__main__":
    import uvicorn
    print("=" * 52)
    print("  MediaFlow Backend — FastAPI + yt-dlp")
    print(f"  Admin Key  : {ADMIN_API_KEY}")
    print(f"  Downloads  : ./{DOWNLOAD_DIR}/")
    print("  API        : http://localhost:8080/api")
    print("  Docs       : http://localhost:8080/docs")
    print("=" * 52)
    uvicorn.run("mediaflow_server:app", host="0.0.0.0", port=8080, reload=True)
"""Explicit folder uploads and a loopback-only native folder chooser."""
from pathlib import Path, PurePosixPath
import asyncio, json, os, re, shutil, subprocess, sys, threading, uuid, zipfile
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from . import folders, native_picker, public_privacy

router = APIRouter(prefix='/api/folders', tags=['폴더 선택·업로드'])
ROOT = Path(__file__).resolve().parents[1]
EXTENSIONS = {'.txt', '.md', '.csv', '.xlsx', '.docx', '.hwpx', '.pdf'}
MAX_TOTAL = 50*1024*1024
# The shared server has 1 GB. A Word file is read whole, about 7 MB of memory per MB unzipped
# (measured 2026-11-05), so a compressed document is bounded by what it unpacks to.
PUBLIC_UNZIPPED = 60*1024*1024
public_scan = asyncio.Lock()
picker_lock = threading.Lock()


def personal_details_in(path):
    # In its own process: see app/public_scan.py. A file that cannot be read is not published.
    service=Path(__file__).resolve().parents[1]
    done=subprocess.run([sys.executable,'-X','utf8','-m','app.public_scan',str(path)],cwd=service,capture_output=True,text=True,encoding='utf-8',timeout=300)
    if done.returncode:raise HTTPException(413,'문서가 너무 크거나 복잡해서 내용을 확인하지 못했습니다. 나누어 올려 주세요.')
    return json.loads(done.stdout.strip().splitlines()[-1])


def unzipped_size(path):
    if path.suffix.lower() not in {'.xlsx', '.docx', '.hwpx'}: return 0
    try:
        with zipfile.ZipFile(path) as archive: return sum(e.file_size for e in archive.infolist())
    except (OSError, zipfile.BadZipFile): return 0

def local_picker_allowed(request):
    # Both peer and URL must be loopback: a tunnel's local peer alone is insufficient.
    return (not getattr(request.app.state, 'public_demo', False)
            and request.client and request.client.host in {'127.0.0.1', '::1'}
            and request.url.hostname in {'127.0.0.1', 'localhost', '::1'}
            and not request.headers.get('cf-connecting-ip')
            and not request.headers.get('x-forwarded-for')
            and request.headers.get('origin', '').rstrip('/') == str(request.base_url).rstrip('/'))

def relative_path(value):
    if not value or '\\' in value or ':' in value or value.startswith('/'):
        raise HTTPException(422, '폴더 안의 상대 경로만 업로드할 수 있습니다.')
    parts=value.split('/')
    if len(parts)>9 or any(not p or p in {'.','..'} or p.startswith('.') or p.endswith((' ','.')) or len(p)>120
                          or re.search(r'[<>"|?*\x00-\x1f]',p)
                          or p.split('.')[0].upper() in {'CON','PRN','AUX','NUL',*[f'COM{i}' for i in range(1,10)],*[f'LPT{i}' for i in range(1,10)]}
                          for p in parts):
        raise HTTPException(422, '지원하지 않는 파일 경로입니다. 숨김·연결점 자료는 제외하세요.')
    path=PurePosixPath(value)
    if path.suffix.lower() not in EXTENSIONS:
        raise HTTPException(422, 'TXT·MD·CSV·XLSX·DOCX·HWPX·PDF만 업로드할 수 있습니다.')
    return path

@router.post('/choose-local')
def choose_local(request:Request):
    if not local_picker_allowed(request):
        raise HTTPException(403, '이 PC 폴더 선택은 앱 PC의 localhost 화면에서만 사용할 수 있습니다. 외부 접속은 폴더 자료 업로드를 사용하세요.')
    if os.name!='nt':raise HTTPException(400, '현재 탐색기 선택은 Windows에서 지원합니다. 경로 입력을 사용하세요.')
    if not picker_lock.acquire(blocking=False):raise HTTPException(409, '이미 열린 폴더 선택 창을 먼저 닫으세요.')
    try:
        paths=native_picker.choose_paths('folder')
        path=paths[0] if paths else ''
        if path:folders.roots_checked([path])
        return {'path':path,'cancelled':not bool(path)}
    except TimeoutError:
        raise HTTPException(408,'폴더 선택 시간이 지났습니다. 다시 선택하세요.') from None
    except (OSError, RuntimeError, ValueError):
        raise HTTPException(503,'폴더 선택 창을 열지 못했습니다. 다시 시도해 주세요.') from None
    finally:picker_lock.release()

@router.post('/uploads',status_code=201)
async def upload(request:Request, name:str=Form(...), paths:str=Form(...), situation:str=Form('',max_length=3000), public_consent:bool=Form(False), files:list[UploadFile]=File(...)):
    public=getattr(request.app.state,'public_demo',False)
    if public and not public_consent:raise HTTPException(422,'공개 시연 자료 공유 안내를 확인하세요.')
    if not 2<=len(name.strip())<=100:raise HTTPException(422,'자료함 이름은 2~100자로 입력하세요.')
    if not 1<=len(files)<=100:raise HTTPException(422,'한 번에 파일 1~100개를 선택하세요.')
    try:values=json.loads(paths)
    except (ValueError,TypeError):raise HTTPException(422,'선택한 폴더 경로를 확인하세요.') from None
    if not isinstance(values,list) or len(values)!=len(files) or any(not isinstance(v,str) for v in values):raise HTTPException(422,'파일과 폴더 경로가 일치하지 않습니다.')
    safe=[relative_path(v) for v in values]
    if len({str(v).casefold() for v in safe})!=len(safe):raise HTTPException(422,'같은 경로의 파일이 중복됩니다. 폴더 이름을 구분하세요.')
    base=ROOT/('synthetic-folders/uploads' if public else 'data/folder-uploads')
    base.mkdir(parents=True,exist_ok=True)
    folders.roots_checked([str(base)])  # Existing symlink/junction and public-boundary guard.
    dest=base/uuid.uuid4().hex;dest.mkdir()
    total=0
    try:
        for path,file in zip(safe,files):
            target=dest.joinpath(*path.parts);target.parent.mkdir(parents=True,exist_ok=True)
            size=0
            with target.open('xb') as stream:
                while chunk:=await file.read(65536):
                    size+=len(chunk);total+=len(chunk)
                    if size>folders.MAX_BYTES or total>MAX_TOTAL:raise HTTPException(413,'파일당 20MB·전체 50MB까지 업로드할 수 있습니다.')
                    stream.write(chunk)
            if public:
                # Read what each file says before anything else does; a file with personal details is refused and removed.
                kinds=public_privacy.found(str(path))
                if not kinds:
                    # A sheet is read row by row, so only documents read whole are bounded here.
                    if target.suffix.lower()!='.xlsx' and unzipped_size(target)>PUBLIC_UNZIPPED:raise HTTPException(413,'압축을 풀면 60MB가 넘는 문서는 공개 시연에 올릴 수 없습니다. 나누어 올려 주세요.')
                    # One at a time, so several large uploads cannot add up past the server's memory.
                    async with public_scan:
                        kinds=await run_in_threadpool(personal_details_in,target)
                if kinds:raise HTTPException(422,public_privacy.refusal(str(path),kinds))
        result=folders.connect(folders.Connect(name=name.strip(),roots=[str(dest)],situation=situation))
        result['import_notice']='선택한 파일의 업로드 사본입니다. 원래 PC 폴더의 추가·수정은 자동 동기화하지 않습니다.'
        return result
    except Exception:
        # Only the freshly generated upload directory can be removed on failure.
        if dest.parent==base and re.fullmatch('[0-9a-f]{32}',dest.name):shutil.rmtree(dest)
        raise
    finally:
        for file in files:await file.close()

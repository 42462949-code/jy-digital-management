"""Windows-only, user-configured PDF report and conservative WeChat UI automation."""
import os, sys, json, time, uuid, logging, subprocess, ctypes, struct
from pathlib import Path
from datetime import datetime
from xml.sax.saxutils import escape
from core import DEFAULT, VN, URL, TASK_NAME, validate, save_config, next_boundary, is_due, Ledger
BASE = Path(__file__).resolve().parent
CONFIG = BASE/'config.json'
SERVICE = 'JiayangReport-Workbench'
if sys.platform != 'win32':
    raise SystemExit('This application requires Windows 10/11.')
try:
    ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
except Exception:
    pass
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
import keyring, pyautogui as mouse, win32gui, win32con, win32process, win32clipboard
from PIL import Image, ImageChops, ImageStat
import psutil
from pywinauto import Desktop
from playwright.sync_api import sync_playwright
mouse.FAILSAFE = True
mouse.PAUSE = .25
(BASE/'logs').mkdir(exist_ok=True)
(BASE/'reports').mkdir(exist_ok=True)
(BASE/'calibration').mkdir(exist_ok=True)
logging.basicConfig(filename=BASE/'logs'/'reporter.log', level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s', encoding='utf-8')

def load():
    return {**DEFAULT, **(json.loads(CONFIG.read_text(encoding='utf-8')) if CONFIG.exists() else {})}

def desktop_ready():
    user = ctypes.windll.user32
    user.OpenInputDesktop.restype = ctypes.c_void_p
    desk = user.OpenInputDesktop(0, False, 0x100)
    if not desk:
        raise RuntimeError('Windows 未登录或已锁屏，停止发送。')
    try:
        if not user.SwitchDesktop(ctypes.c_void_p(desk)):
            raise RuntimeError('屏幕已锁定，停止发送。')
    finally:
        user.CloseDesktop(ctypes.c_void_p(desk))

def wechat():
    desktop_ready()
    windows=[]
    def visit(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            try:
                pid=win32process.GetWindowThreadProcessId(hwnd)[1]
                if psutil.Process(pid).name().lower() in ('wechat.exe','weixin.exe') and win32gui.GetWindowText(hwnd) in ('微信','WeChat','Weixin'):
                    windows.append(hwnd)
            except (psutil.Error, OSError): pass
    win32gui.EnumWindows(visit,None)
    if len(windows)!=1:
        raise RuntimeError('请打开并登录一个微信主窗口（不能有多个微信主窗口）。')
    hwnd=windows[0]
    win32gui.ShowWindow(hwnd, win32con.SW_MAXIMIZE)
    try:
        win32gui.SetForegroundWindow(hwnd)
    except Exception:
        raise RuntimeError('无法把微信放到前台，请手动点击微信后重试。')
    time.sleep(1)
    if win32gui.GetForegroundWindow()!=hwnd:
        raise RuntimeError('微信不在前台，停止操作。')
    return hwnd

def clipboard_text(text):
    win32clipboard.OpenClipboard()
    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT,text)
    finally: win32clipboard.CloseClipboard()

def search_account(account):
    mouse.hotkey('ctrl','f');time.sleep(.5)
    clipboard_text(account);mouse.hotkey('ctrl','a');mouse.hotkey('ctrl','v');time.sleep(2)

def crop(rect):
    time.sleep(.2)
    x,y,w,h=rect
    return mouse.screenshot(region=(x,y,w,h)).convert('RGB')

def image_matches(path,rect):
    ref=Image.open(path).convert('RGB');now=crop(rect)
    if ref.size!=now.size: return False
    # Tiny antialiasing variations are tolerated; changed content should fail closed.
    diff=ImageChops.difference(ref,now)
    mean=sum(ImageStat.Stat(diff).mean)/(3*255)
    pixels=list(diff.convert('L').getdata())
    changed=sum(v>28 for v in pixels)/max(1,len(pixels))
    return mean<.015 and changed<.045

def select_region(prompt):
    messagebox.showinfo('框选位置',prompt+'\n\n点击确定后，用鼠标拖出矩形，Esc 取消。请准确框选文字及头像，避开闪烁光标。')
    shot=mouse.screenshot()
    from PIL import ImageTk
    overlay=tk.Toplevel();overlay.overrideredirect(True);overlay.attributes('-topmost',True)
    overlay.geometry(f'{shot.width}x{shot.height}+0+0')
    photo=ImageTk.PhotoImage(shot);canvas=tk.Canvas(overlay,highlightthickness=0,cursor='crosshair');canvas.pack(fill='both',expand=True);canvas.create_image(0,0,image=photo,anchor='nw')
    result=[];origin=[];box=[None]
    def down(e): origin[:]=[e.x,e.y];box[0]=canvas.create_rectangle(e.x,e.y,e.x,e.y,outline='#ff3232',width=2)
    def move(e):
        if origin: canvas.coords(box[0],origin[0],origin[1],e.x,e.y)
    def up(e):
        if origin:
            x,y=min(origin[0],e.x),min(origin[1],e.y);w,h=abs(e.x-origin[0]),abs(e.y-origin[1])
            if w>=20 and h>=12: result.extend([x,y,w,h]);overlay.destroy()
    canvas.bind('<ButtonPress-1>',down);canvas.bind('<B1-Motion>',move);canvas.bind('<ButtonRelease-1>',up);overlay.bind('<Escape>',lambda e:overlay.destroy());overlay.grab_set();overlay.wait_window()
    if not result: raise RuntimeError('已取消框选。')
    return result

def calibrate(account):
    hwnd=wechat();size=list(mouse.size())
    search_account(account)
    if not messagebox.askyesno('核对收件人',f'请核对微信搜索结果，确认它确实属于账号 {account}。\n如果无结果、同名无法确认或账号不符，请选“否”。\n\n是否已核对无误？'):
        raise RuntimeError('未确认联系人。')
    wechat();result=select_region('框选该联系人的完整搜索结果行，包含头像和名称。不要包括其他联系人。')
    rid=uuid.uuid4().hex
    resultfile=BASE/'calibration'/f'{rid}-result.png';crop(result).save(resultfile)
    mouse.click(result[0]+result[2]//2,result[1]+result[3]//2);time.sleep(1.5)
    header=select_region('框选已打开聊天窗口顶部的联系人名称及头像（尽量包含唯一标识）。')
    headerfile=BASE/'calibration'/f'{rid}-header.png';crop(header).save(headerfile)
    compose=select_region('框选右侧最下方的消息编辑区，包含粘贴文件后会显示附件文件名的位置，不能包括聊天历史。')
    send=select_region('框选右下角的“发送”按钮。此时不会点击发送。')
    return {'screen':size,'window':list(win32gui.GetWindowRect(hwnd)),'result':result,'result_image':str(resultfile.relative_to(BASE)),'header':header,'header_image':str(headerfile.relative_to(BASE)),'compose':compose,'send':send}

def open_chat(account,cal):
    hwnd=wechat()
    if list(mouse.size())!=cal['screen'] or list(win32gui.GetWindowRect(hwnd))!=cal['window']:
        raise RuntimeError('屏幕分辨率或微信窗口尺寸变了，请重新校准。')
    search_account(account)
    if not image_matches(BASE/cal['result_image'],cal['result']):
        raise RuntimeError(f'{account} 的搜索结果与校准图不一致，停止发送。')
    x,y,w,h=cal['result'];mouse.click(x+w//2,y+h//2);time.sleep(1.5)
    if not image_matches(BASE/cal['header_image'],cal['header']):
        raise RuntimeError(f'{account} 的聊天标题与校准图不一致，停止发送。')
    return hwnd

def paste_file(path):
    payload=struct.pack('IiiII',20,0,0,0,1)+(str(path.resolve())+'\0\0').encode('utf-16le')
    win32clipboard.OpenClipboard()
    try:
        win32clipboard.EmptyClipboard();win32clipboard.SetClipboardData(win32con.CF_HDROP,payload)
    finally: win32clipboard.CloseClipboard()
    mouse.hotkey('ctrl','v');time.sleep(2)

def attachment_visible(hwnd, filename, rect):
    x,y,w,h=rect
    root=Desktop(backend='uia').window(handle=hwnd)
    for control in root.descendants():
        try:
            bounds=control.rectangle();text=control.window_text()
            if filename in text and x<=bounds.left<x+w and y<=bounds.top<y+h and bounds.right<=x+w+5 and bounds.bottom<=y+h+5:
                return True
        except Exception: pass
    return False

def send_pdf(account,path,cal,before_send):
    hwnd=open_chat(account,cal)
    x,y,w,h=cal['compose'];mouse.click(x+w//2,y+h//2)
    # Do not overwrite or transmit an existing draft message.
    root=Desktop(backend='uia').window(handle=hwnd)
    editors=[]
    for control in root.descendants(control_type='Edit'):
        bounds=control.rectangle()
        if x<=bounds.left<x+w and y<=bounds.top<y+h: editors.append(control)
    if len(editors)!=1 or editors[0].window_text().strip():
        raise RuntimeError('无法确认消息编辑区为空，或微信未开放辅助功能。请清空草稿并检查后重试。')
    import re
    for control in root.descendants():
        bounds=control.rectangle()
        if x<=bounds.left<x+w and y<=bounds.top<y+h and re.search(r'\.(?:pdf|xlsx?|docx?|zip|png|jpe?g)\b',control.window_text(),re.I):
            raise RuntimeError('编辑区已有附件，停止发送；请人工检查草稿。')
    paste_file(path)
    if not attachment_visible(hwnd,path.name,cal['compose']):
        raise RuntimeError('无法在编辑区核对 PDF 文件名，未点击发送。可能需要开启微信辅助功能；请勿启用定时任务。')
    if win32gui.GetForegroundWindow()!=hwnd or not image_matches(BASE/cal['header_image'],cal['header']):
        raise RuntimeError('联系人窗口发生变化，未点击发送。')
    before_send()  # Durable duplicate guard precedes the irreversible click.
    x,y,w,h=cal['send'];mouse.click(x+w//2,y+h//2);time.sleep(2)
    if attachment_visible(hwnd,path.name,cal['compose']):
        raise RuntimeError('已点击发送，但附件仍在编辑区；结果不确定，不会自动重试。')
    logging.info('Send button clicked; delivery not independently verified: %s %s',account,path.name)

def pdf_report(config,workbench=False):
    password=keyring.get_password(SERVICE,config['username'])
    if password is None: raise RuntimeError('请先在配置窗口保存管理系统密码。')
    with sync_playwright() as p:
        context=p.chromium.launch_persistent_context(str(BASE/'browser-profile'),headless=not workbench,viewport={'width':1440,'height':1100},locale='zh-CN',timezone_id='Asia/Ho_Chi_Minh')
        try:
            page=context.pages[0] if context.pages else context.new_page()
            page.goto(URL,wait_until='domcontentloaded',timeout=90000)
            page.wait_for_function("typeof login==='function' && typeof loadPublishedData==='function'",timeout=90000)
            page.evaluate('loadPublishedData()')
            page.evaluate('login()')
            page.locator('#username').fill(config['username']);page.locator('#password').fill(password);page.locator('#loginSubmit').click()
            try: page.wait_for_selector('.workspace',timeout=15000)
            except Exception: raise RuntimeError('管理系统登录失败，请检查用户名和密码。')
            if workbench:
                messagebox.showinfo('专用工作台','请在打开的浏览器中核对或导入最新生产数据。\n\n这是独立浏览器，普通 Chrome/Edge 里的本地数据不会自动同步到这里。\n请在这个工作台维护报表数据，完成后关闭全部浏览器窗口。')
                while any(not tab.is_closed() for tab in context.pages):
                    try: page.wait_for_timeout(300)
                    except Exception:
                        if not context.pages or all(tab.is_closed() for tab in context.pages): break
                        raise
                return None
            if not config.get('data_verified'): raise RuntimeError('请先打开专用工作台核对数据，并在配置中勾选已核对。')
            page.evaluate('setLanguage("zh");navigate(7)')
            page.wait_for_selector('#dashboardUnit')
            count=page.evaluate("Number(document.querySelectorAll('.cards .card b')[3]?.textContent.replace(/[^0-9]/g,''))")
            if not count: raise RuntimeError('生产数据为空，未生成或发送 PDF。请先在专用工作台导入生产数据。')
            stamp=datetime.now(VN).strftime('%Y-%m-%d %H:%M:%S')
            page.evaluate("stamp=>{const note=document.createElement('div');note.textContent='佳洋 · 生产数据看板 | 越南时间 '+stamp+' | 数据为专用工作台当前保存内容';note.style='font-size:12px;color:#607087;margin:0 0 12px';document.querySelector('#content').prepend(note)}",stamp)
            page.add_style_tag(content='@media print{body{background:white}.workspace{margin:0!important;width:100%!important;height:auto!important;overflow:visible!important}.topbar,.top-actions,.heading button{display:none!important}.content{padding:0!important}.cards,.panel{break-inside:avoid}.chartgrid{display:grid;grid-template-columns:1.6fr 1fr}.card{padding:15px}*{-webkit-print-color-adjust:exact;print-color-adjust:exact}}')
            page.emulate_media(media='print');page.evaluate('document.fonts.ready');page.wait_for_timeout(600)
            path=BASE/'reports'/('Production-'+datetime.now(VN).strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:6]+'.pdf')
            page.pdf(path=str(path),format='A4',landscape=True,scale=.75,print_background=True,margin={'top':'8mm','bottom':'8mm','left':'8mm','right':'8mm'})
            if path.stat().st_size<1024: raise RuntimeError('PDF 文件生成异常。')
            logging.info('Generated PDF with %s production records: %s',count,path.name)
            return path
        finally: context.close()

def task(config,enabled):
    if not enabled:
        subprocess.run(['schtasks','/Delete','/TN',TASK_NAME,'/F'],capture_output=True)
        return
    validate(config)
    sid=subprocess.check_output(['whoami','/user','/fo','csv','/nh'],text=True).strip().split(',')[-1].strip('"')
    exe=BASE/'.venv'/'Scripts'/'pythonw.exe'
    xml=f'''<?xml version="1.0" encoding="UTF-16"?><Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task"><RegistrationInfo><Description>Production PDF to configured WeChat contacts at Vietnam time {config['time']}</Description></RegistrationInfo><Triggers><CalendarTrigger><StartBoundary>{next_boundary(config['time'])}</StartBoundary><Enabled>true</Enabled><ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay></CalendarTrigger></Triggers><Principals><Principal id="Author"><UserId>{escape(sid)}</UserId><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals><Settings><MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy><DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries><StopIfGoingOnBatteries>false</StopIfGoingOnBatteries><StartWhenAvailable>false</StartWhenAvailable><ExecutionTimeLimit>PT10M</ExecutionTimeLimit><Enabled>true</Enabled></Settings><Actions Context="Author"><Exec><Command>{escape(str(exe))}</Command><Arguments>"{escape(str(BASE/'reporter.py'))}" --scheduled</Arguments><WorkingDirectory>{escape(str(BASE))}</WorkingDirectory></Exec></Actions></Task>'''
    path=BASE/'task.xml';path.write_text(xml,encoding='utf-16')
    result=subprocess.run(['schtasks','/Create','/TN',TASK_NAME,'/XML',str(path),'/F'],capture_output=True)
    if result.returncode: raise RuntimeError('无法创建任务：'+result.stderr.decode('mbcs',errors='replace'))

def scheduled():
    import msvcrt
    with (BASE/'send.lock').open('a+b') as lock:
        lock.seek(0);lock.write(b'0');lock.flush();lock.seek(0)
        try: msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        except OSError: return
        config=load();validate(config)
        if not config['enabled'] or not is_due(config['time']):
            logging.info('Skipped: disabled or outside Vietnam send window');return
        desktop_ready()
        for account in config['recipients']:
            if account not in config['calibrations'] or not config['tests'].get(account): raise RuntimeError('联系人未完成校准和测试。')
        report=pdf_report(config);ledger=Ledger(BASE/'delivery.sqlite');day=datetime.now(VN).date().isoformat()
        for account in config['recipients']:
            if ledger.conn.execute('SELECT 1 FROM attempts WHERE day=? AND recipient=?',(day,account)).fetchone(): continue
            try:
                def reserve():
                    if not ledger.reserve(day,account,report): raise RuntimeError('该收件人今天已有发送尝试，不重复发送。')
                send_pdf(account,report,config['calibrations'][account],reserve)
                ledger.finish(day,account,'send_clicked')
            except Exception:
                ledger.finish(day,account,'needs_manual_check')
                logging.exception('Recipient failed: %s',account)
                try: mouse.screenshot().save(BASE/'logs'/f'error-{day}-{uuid.uuid4().hex[:6]}.png')
                except Exception: pass
                # A pending attachment could be transmitted by subsequent actions; stop this run.
                raise

def gui():
    config=load();root=tk.Tk();root.title('佳洋 · 微信报表助手');root.geometry('670x710');root.minsize(640,690)
    root.option_add('*Font',('Microsoft YaHei UI',10))
    frame=ttk.Frame(root,padding=24);frame.pack(fill='both',expand=True)
    ttk.Label(frame,text='生产看板 · PDF 定时发送',font=('Microsoft YaHei UI',18,'bold')).pack(anchor='w')
    ttk.Label(frame,text='个人微信 / 越南时间 UTC+7 / Windows 当前登录用户').pack(anchor='w',pady=(4,18))
    timevar=tk.StringVar(value=config['time']);uservar=tk.StringVar(value=config['username']);passwordvar=tk.StringVar()
    verified=tk.BooleanVar(value=config.get('data_verified',False));status=tk.StringVar()
    row=ttk.Frame(frame);row.pack(fill='x');ttk.Label(row,text='每日越南时间（24小时制）').pack(side='left');ttk.Entry(row,textvariable=timevar,width=9).pack(side='left',padx=12)
    ttk.Label(frame,text='收件人微信账号：一行一个，可增删（不要填昵称）').pack(anchor='w',pady=(14,5))
    recipients=tk.Text(frame,height=4,width=50);recipients.pack(fill='x');recipients.insert('1.0','\n'.join(config['recipients']))
    row=ttk.Frame(frame);row.pack(fill='x',pady=(14,6));ttk.Label(row,text='管理系统账号').pack(side='left');ttk.Entry(row,textvariable=uservar,width=18).pack(side='left',padx=8);ttk.Label(row,text='密码').pack(side='left');ttk.Entry(row,textvariable=passwordvar,show='●',width=18).pack(side='left',padx=8)
    ttk.Label(frame,text='密码留空则保留原密码，密码存入 Windows 凭据管理器。',foreground='#617286').pack(anchor='w')
    ttk.Checkbutton(frame,text='我已在专用工作台核对最新生产数据，并检查过 PDF 内容',variable=verified).pack(anchor='w',pady=(10,8))
    selected=tk.StringVar();accountbox=ttk.Combobox(frame,textvariable=selected,state='readonly',values=config['recipients']);accountbox.pack(fill='x')
    if config['recipients']: selected.set(config['recipients'][0])
    def refresh():
        complete=sum(bool(config.get('tests',{}).get(a)) for a in config['recipients'])
        status.set(('定时任务：已启用' if config['enabled'] else '定时任务：未启用')+f"   越南时间 {config['time']}\n收件人 {len(config['recipients'])} 人，已测试 {complete} 人")
    def safe(action):
        try: action();refresh()
        except Exception as e:
            logging.exception('Interactive operation failed')
            messagebox.showerror('操作未完成',str(e))
    def save():
        nonlocal config
        nextconfig={**config,'time':timevar.get().strip(),'username':uservar.get().strip(),'recipients':[s.strip() for s in recipients.get('1.0','end').splitlines() if s.strip()],'data_verified':verified.get(),'enabled':False}
        validate(nextconfig)
        if passwordvar.get(): keyring.set_password(SERVICE,nextconfig['username'],passwordvar.get())
        if not keyring.get_password(SERVICE,nextconfig['username']): raise RuntimeError('首次保存请填写管理系统密码。')
        task(nextconfig,False);save_config(CONFIG,nextconfig);config=nextconfig;passwordvar.set('');accountbox['values']=config['recipients']
        if selected.get() not in config['recipients']: selected.set(config['recipients'][0])
        messagebox.showinfo('已保存','设置已保存；原定时任务已暂停。修改完成后请点击“启用定时”。')
    def workbench():
        if not CONFIG.exists(): raise RuntimeError('请先填写并保存设置。')
        subprocess.Popen([sys.executable,str(BASE/'reporter.py'),'--workbench'],cwd=BASE)
    def preview():
        if not CONFIG.exists(): raise RuntimeError('请先保存设置。')
        root.withdraw()
        try: path=pdf_report(config);os.startfile(path)
        finally: root.deiconify()
    def calibration():
        account=selected.get()
        if account not in config['recipients']: raise RuntimeError('请选择已保存的收件人。')
        if config['enabled']: pause()
        root.withdraw()
        try:
            config['calibrations'][account]=calibrate(account);config['tests'].pop(account,None);save_config(CONFIG,config)
        finally: root.deiconify()
        messagebox.showinfo('已校准','已保存微信界面位置。下一步进行一次测试发送。\n微信版本、分辨率、缩放或联系人名称变化后需要重新校准。')
    def test():
        account=selected.get()
        if account not in config.get('calibrations',{}): raise RuntimeError('请先校准所选联系人。')
        if not messagebox.askyesno('测试发送',f'这会将当前生产看板 PDF 实际发送给 {account}。\n请确认微信窗口和联系人正确，测试期间不要操作鼠标键盘。\n\n现在测试？'): return
        root.withdraw()
        try:
            path=pdf_report(config)
            send_pdf(account,path,config['calibrations'][account],lambda:None)
        finally: root.deiconify()
        if messagebox.askyesno('核对测试结果','请打开微信人工确认：PDF 已发到正确联系人、能打开且内容正确？\n程序只能核对点击发送和编辑区变化，无法独立证明对方已收到。'):
            config['tests'][account]=datetime.now(VN).isoformat();save_config(CONFIG,config)
    def enable():
        saved=load()
        if saved!=config or timevar.get().strip()!=config['time'] or uservar.get().strip()!=config['username'] or [s.strip() for s in recipients.get('1.0','end').splitlines() if s.strip()]!=config['recipients'] or passwordvar.get() or verified.get()!=config['data_verified']:
            raise RuntimeError('请先保存修改后的设置。')
        validate(config)
        if not config.get('data_verified'): raise RuntimeError('请先核对专用工作台数据和 PDF，并保存勾选。')
        if not all(config['tests'].get(a) for a in config['recipients']): raise RuntimeError('每个收件人均需完成校准及测试发送。')
        task(config,True);config['enabled']=True;save_config(CONFIG,config)
        messagebox.showinfo('已启用',f"每天越南时间 {config['time']} 执行。\n需保持电脑开机、不休眠、不锁屏，微信登录。\n请在任务开始前关闭专用工作台浏览器，以释放浏览器数据目录。\n未按时执行不会自动补发。")
    def pause():
        task(config,False);config['enabled']=False;save_config(CONFIG,config)
    buttons=ttk.Frame(frame);buttons.pack(fill='x',pady=14)
    items=[('1 保存设置',save),('2 打开专用工作台',workbench),('3 预览 PDF',preview),('4 校准所选联系人',calibration),('5 测试发送给所选联系人',test),('6 启用定时',enable),('暂停定时',pause),('查看日志 / PDF',lambda:os.startfile(BASE))]
    for index,(text,fn) in enumerate(items):
        ttk.Button(buttons,text=text,command=lambda f=fn:safe(f)).grid(row=index//2,column=index%2,sticky='ew',padx=3,pady=4)
    buttons.columnconfigure((0,1),weight=1)
    ttk.Label(frame,textvariable=status,foreground='#246379',wraplength=590).pack(anchor='w',pady=(2,8))
    ttk.Label(frame,text='微信界面不匹配、锁屏、PDF 数据为空时停止发送。发送点击后的不确定结果不会自动重试。\n窗口校准及微信版本兼容性必须在本机验证。鼠标移到屏幕左上角可中止后续鼠标操作。',foreground='#617286',wraplength=590).pack(anchor='w')
    refresh();root.mainloop()

if __name__=='__main__':
    try:
        if '--scheduled' in sys.argv: scheduled()
        elif '--workbench' in sys.argv:
            root=tk.Tk();root.withdraw()
            try: pdf_report(load(),workbench=True)
            finally: root.destroy()
        else: gui()
    except Exception as error:
        logging.exception('Reporter failed')
        if '--scheduled' not in sys.argv: messagebox.showerror('佳洋报表助手',str(error))
        sys.exit(1)

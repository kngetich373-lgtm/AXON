import os, shutil, subprocess, sys, tkinter as tk

SAFE_APPS={"kitty":["kitty"],"terminal":["kitty"],"files":["thunar"],"browser":["xdg-open","https://www.google.com"],"wireshark":["wireshark"],"code":["code"],"vscode":["code"],"obsidian":["obsidian"]}
SAFE_TERMINAL_COMMANDS={"sudo apt update":"sudo apt update"}

def open_app(name):
    key=name.lower().strip(); cmd=SAFE_APPS.get(key)
    if not cmd: return False,f"No governed launcher for '{name}'."
    if shutil.which(cmd[0]) is None: return False,f"{cmd[0]} is not installed or not on PATH."
    try: subprocess.Popen(cmd,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); return True,f"Opened {name}."
    except Exception as e: return False,f"Could not open {name}: {e}"

def run_safe_terminal_command(command):
    cmd=SAFE_TERMINAL_COMMANDS.get(command.lower().strip())
    if not cmd: return False,"That command is not in AXON's governed safe-command list."
    if shutil.which("kitty") is None: return False,"Kitty is not installed."
    subprocess.Popen(["kitty","--hold","bash","-lc",cmd],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    return True,f"Opened Kitty and started: {cmd}"

def system_status():
    import psutil
    return {"cpu":psutil.cpu_percent(interval=0.05),"ram":psutil.virtual_memory().percent,"disk":psutil.disk_usage('/').percent,"python":sys.version.split()[0],"host":os.uname().nodename}

def launch_calculator():
    win=tk.Toplevel(); win.title("AXON Kids Calculator"); win.geometry("380x560"); win.minsize(340,500); win.configure(bg="#080d18")
    expr=tk.StringVar(); tk.Label(win,text="🧮  AXON KIDS CALCULATOR",fg="#f4f7ff",bg="#080d18",font=("DejaVu Sans",16,"bold")).pack(pady=16)
    entry=tk.Entry(win,textvariable=expr,justify="right",font=("DejaVu Sans",22),bg="#11192a",fg="#fff",insertbackground="#fff",relief="flat"); entry.pack(fill="x",padx=20,ipady=12)
    grid=tk.Frame(win,bg="#080d18"); grid.pack(padx=16,pady=18,fill="both",expand=True)
    buttons=[("7","8","9","÷"),("4","5","6","×"),("1","2","3","−"),("0",".","=","+"),("C","(",")","⌫")]
    def press(v):
        if v=="C": expr.set("")
        elif v=="⌫": expr.set(expr.get()[:-1])
        elif v=="=":
            try:
                s=expr.get().replace("÷","/").replace("×","*").replace("−","-")
                if any(c not in "0123456789.+-*/() " for c in s): raise ValueError
                expr.set(str(eval(s,{"__builtins__":{}},{})))
            except Exception: expr.set("Try again")
        else: expr.set(expr.get()+v)
    for r,row in enumerate(buttons):
        for c,v in enumerate(row): tk.Button(grid,text=v,command=lambda x=v:press(x),font=("DejaVu Sans",14,"bold"),bg="#151f35",fg="#fff",activebackground="#8b5cf6",activeforeground="#fff",relief="flat").grid(row=r,column=c,padx=5,pady=5,sticky="nsew")
    for i in range(5): grid.rowconfigure(i,weight=1)
    for i in range(4): grid.columnconfigure(i,weight=1)
    return win

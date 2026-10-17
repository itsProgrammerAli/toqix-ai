import subprocess

CMDS = [
    "tar -xzf toqix_sound_final.tar.gz",
    "git add toqix/prompt_engine.py toqix/knowledge.py",
    "git -c user.name=\"TOQIX AI\" -c user.email=\"itsprogrammerali@gmail.com\" commit -m \"Sound v2 final: strip quoted line from visual prompt; refresh sound knowledge entries\"",
]

log = open("/home/toqix/step2_deploy.log", "a")
for cmd in CMDS:
    log.write("$ " + cmd + "\n")
    print("$ " + cmd, flush=True)
    p = subprocess.run(cmd, shell=True, cwd="/home/toqix/toqix-ai", capture_output=True, text=True)
    log.write(p.stdout)
    log.write(p.stderr)
    log.write("[exit " + str(p.returncode) + "]\n")
    log.flush()
    print(p.stdout, flush=True)
    print(p.stderr, flush=True)
log.write("DONE\n")
log.close()
print("DONE", flush=True)

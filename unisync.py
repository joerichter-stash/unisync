#!/usr/bin/python3

import os, sys
import signal
import pyinotify
from pyinotify import EventsCodes as EC
import subprocess
from subprocess import PIPE
from collections import deque
import threading
import time


def log(*msg):
    print(*msg, file=sys.stderr)


_LOCAL = 0
_REMOTE = 1


class CMD_Context:
    process = None
    cmd = None

    def __enter__(self):
        t = threading.Thread(target=self.run_cmd, daemon=True)
        t.start()

    def run_cmd(self):
        if self.process or not self.cmd:
            return
        if self.input_text:
            self.process = subprocess.Popen(self.cmd, stdin=PIPE)
            self.process.communicate(input=self.input_text.encode())
        else:
            self.process = subprocess.Popen(self.cmd)

    def __exit__(self, exc_type, exc_value, exc_tb):
        #log("Leaving CMD_Context...")
        #log("Exc_type:", exc_type, "Exc_val:", exc_value, "Exc_tb:", exc_tb)
        if self.process:
            self.process.terminate()

class OSD_Context(CMD_Context):

    def __init__(self, text, status=None, max_delay=0):
        if os.path.isfile("/usr/bin/osd_cat") and 'DISPLAY' in os.environ:
            self.input_text = text
            color = ['-c' + ('lightgreen' if not status else 'red')]
            delay = ['-d' + str(max_delay)]
            self.cmd = ["osd_cat", "-O2", "-o10", "-i10"] + delay + color


class UnisonSync(object):

    def __init__(self, roots_profile=None):
        self.queue = deque()
        self.e_run= threading.Event()
        self.last_update = 0
        self.roots = []
        self.profile = None

        if len(roots_profile) == 1:
            profile_path = os.environ['HOME']+"/.unison/%s.prf" % roots_profile[0]
            self.parse_config(profile_path)
            self.profile = roots_profile[0]
        else:
            self.roots = roots_profile[:2] if roots_profile else []
        if len(self.roots) != 2:
            raise NameError("could not find sync-roots")
        log("roots:", self.roots)
        signal.signal(signal.SIGALRM, self.wakeup_handler)


    def sync(self, paths=[]):
        r_paths = [os.path.relpath(i, self.roots[_LOCAL]) for i in set(paths)]
        r_paths = disjunct_toplevel(r_paths)
        log("sync_paths:", r_paths)

        r_paths = [i for sl in zip(['-path']*len(r_paths), r_paths) for i in sl]

        cmd = ['unison', '-auto', '-batch', '-dumbtty', '-terse']
        if self.profile:
            cmd += [self.profile]
        else:
            cmd += [self.roots[_LOCAL], self.roots[_REMOTE]]

        cmd += r_paths

        with OSD_Context("[syncing]"):
            status = subprocess.run(cmd)

        log("Status:", "Success" if status.returncode == 0 else "Error Code: " + str(status.returncode), "\n--")
        if status.returncode != 0:
            with OSD_Context("[sync failed]", status="error"):
                time.sleep(10)

        #TODO exit on serious return-code or try to recover
        return status.returncode == 0


    def add_path(self, changed_path):
        self.last_update = time.time()
        if len(self.queue) == 0 or self.queue[-1] != changed_path:
            self.queue.append(changed_path)

            # XXX continuous events may prevent start -> use fixed batches?
            signal.setitimer(signal.ITIMER_REAL, 0.2) # sync X seconds after last event


    def wakeup_handler(self, signum, frame):
        #log("awakened") #hello
        self.e_run.set()


    def schedule_sync(self, update_interv=2):
        while(True):
            # blocks
            self.e_run.wait()
            self.e_run.clear()

            path_list = [self.queue.popleft() for _ in range(len(self.queue))]
            log("sync!  #files:", len(path_list))
            self.sync(path_list)


    def parse_config(self, conf_file):
        with open(conf_file, "r") as conf:
            for l in conf.readlines():
                if len(l) <= 2 or l.startswith("#"):
                    continue
                key, value = (i.strip() for i in l.split("=", maxsplit=1))
                if key == "root":
                    self.roots.append(value)


def check_flags(flag, mask):
    """returns if @flag is included in @mask"""
    return flag & mask == flag


MODIFICATION_MASK = EC.OP_FLAGS["IN_DELETE"] |\
                EC.OP_FLAGS["IN_DELETE_SELF"] |\
                EC.OP_FLAGS["IN_MOVED_FROM"] |\
                EC.OP_FLAGS["IN_MOVED_TO"] |\
                EC.OP_FLAGS["IN_ATTRIB"] |\
                EC.OP_FLAGS["IN_CLOSE_WRITE"] |\
                EC.OP_FLAGS["IN_CREATE"] |\
                EC.SPECIAL_FLAGS['IN_ISDIR']

class EventProcessor(pyinotify.ProcessEvent):

    def __init__(self, wm, notify_cb):
        self.watch_manager = wm
        self.notify_cb = notify_cb



    def process_default(self, event):
        log("Path:", event.pathname,"  <--Event:", event.maskname)
        in_create_op =  EC.OP_FLAGS["IN_CREATE"]

        # XXX: checks not working for copyied dir
        if not check_flags(event.mask, MODIFICATION_MASK):
            return
        # filter create events for files
        if check_flags(in_create_op, event.mask) and not \
                check_flags(EC.SPECIAL_FLAGS['IN_ISDIR'], event.mask):
            return

        #log("trigger update for:", event.pathname,"  <-- Event Name:", event.maskname)
        if not self.notify_cb:
            return

        log("Adding-Path:", event.pathname,"  <--Event:", event.maskname)
        self.notify_cb(event.pathname)


# currently only top-level links are watched
def observe_dir(src_dir, notify_cb=None):
    watch_manager = pyinotify.WatchManager()
    obs_events = MODIFICATION_MASK
    watch_manager.add_watch(src_dir, obs_events, rec=True, auto_add=True)

    # add top-level links
    for entry in os.scandir(src_dir):
        if(entry.is_symlink()):
            log("observing symlink:", entry.path)
            watch_manager.add_watch(entry.path, obs_events, rec=True, auto_add=True)

            # XXX rec=True is not working for links -- explicitly adding links to watch list
            # should also include their subdirs as auto_add does.
            # this should be fixed in: pyinotify: __walk_rec()
            for p,d,f in os.walk(entry.path):
                for di in d:
                    watch_manager.add_watch("%s/%s" % (p,di), obs_events, rec=True, auto_add=True)

    event_notifier = pyinotify.Notifier(watch_manager, EventProcessor(watch_manager, notify_cb))
    event_notifier.loop()


def disjunct_toplevel(files):
    toplist = []
    opf = ''
    for i in sorted(files):
        opf = os.path.commonpath( (opf,i) )
        if not opf:
            opf = i
            toplist.append(opf)
    return toplist


def main(argv=sys.argv):

    if len(argv) > 1:
        usync = UnisonSync(argv[1:])

        # initial sync
        if usync.sync():
            # XXX daemon-thread may interrupt unison subprocess, but it should be able to handle that
            sync_loop = threading.Thread(target=usync.schedule_sync, daemon=True)
            sync_loop.start()
            observe_dir(usync.roots[_LOCAL], usync.add_path)
        else:
            log("initial sync failed");
            sys.exit(-1)

    else:
        log("usage: <profile>|<src-dir dst-dir>")


if __name__ == "__main__":
    #observe_dir("/tmp/test1")
    main()

#!/usr/bin/python
#
# Navi-X CLI
# Copyright (C) 2010  Robert Thomson
# 
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
# 
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
# 
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#

import re
import sys
import cmd
import cPickle as pickle
import os.path
import time
import urllib, urllib2
from pprint import pprint
from subprocess import Popen, PIPE
from fnmatch import fnmatch
from cookielib import CookieJar
import textwrap
import platform
#
import scraper

homedir = os.path.expanduser("~")
DOWNLOADPATH=homedir
for x in ('Downloads', 'Download', 'My Documents'):
    tmppath = os.path.join(homedir, x)
    if os.path.isdir(tmppath):
        DOWNLOADPATH=tmppath
        break
if platform.system() == 'Windows':
    PAGER_CMD = ["more"]
else:
    PAGER_CMD = ["less", "-eFX"]

def chdir(path, verbose=True):
    global DOWNLOADPATH
    tmppath = os.path.abspath(os.path.join(DOWNLOADPATH,
            os.path.expanduser(path)))
    if os.path.isdir(tmppath):
        os.chdir(tmppath)
        DOWNLOADPATH=tmppath
        if verbose:
            print "Download path is now %s" % tmppath
    elif verbose:
        print "Could not change to %s" % tmppath

chdir(DOWNLOADPATH, False)

def dcode(s):
    if type(s) == unicode:
        return s
    return s.decode('utf-8', 'replace')

exit_until_index = False # set to true in a cmd and keep returning until we're at the idx again

class myURLOpener(urllib.FancyURLopener):
    def http_error_206(self, url, fp, errcode, errmsg, headers, data=None):
        pass
myUrlClass = myURLOpener()

cookiejar = CookieJar()

USER_AGENT="Mozilla/5.0 (Windows; U; Windows NT 6.1; ru; rv:1.9.2b5) Gecko/20091204 Firefox/3.6b5"

def request(url, referer=None, ua=USER_AGENT, data=None, **kwargs):
    d = { "User-Agent" : ua }
    if referer:
        d['Referer'] = referer
    d.update(kwargs)
    r = urllib2.Request(url, data, d)
    return r

def ratestring(kbps):
    if kbps > 1024:
        return "%0.2f MB/s" % (kbps/1024)
    return "%d KB/s" % (kbps)

def download(res, filename):
    length = res.info().get('Content-Length', None)
    strlength = length and ("%dk" % (int(length)/1024)) or "Unknown"
    i = 0
    starttime = time.time()
    data = res.read(4096)
    count = len(data)
    out = None
    while data:
        if out is None:
            fname = filename
            i = 1
            if res.getcode() == 206: # partial file transfer
                # FIXME - seek to right location, in-case
                out = file(fname, "ab")
            else:
                while os.path.exists(fname):
                    fname = "%s.%d" % (fname, i)
                    i = i + 1
                out = file(fname, "wb")
            print "Downloading to %s" % fname
        out.write(data)
        data = res.read(4096)
        count += len(data)
        kbps = int(count / (int(time.time() - starttime) or 1) / 1024.0)
        sys.stdout.write("\r\033[K[%dk / %s] (~%s)" % (count//1024, strlength, ratestring(kbps)))
        sys.stdout.flush()
    out.close()
    print ""

class Cache(object):
    def __init__(self, filename):
        if os.path.exists(filename):
            self.data = pickle.load(file(filename,'rb'))
        else:
            self.data = {}
        self.filename = filename
    def __setitem__(self, k, v):
        self.data[k] = (time.time(), v)
    def __getitem__(self, k):
        tm, v = self.data[k]
        if (time.time()-tm) > 3600:
            del self.data[k]
            raise KeyError()
        return v
    def get(self, k, default=None):
        try:
            return self.data[k]
        except KeyError:
            return default
    def __contains__(self, k):
        if k in self.data:
            tm = self.data[k][0]
            if (time.time()-tm) > 3550:
                return True
        return False
    def save(self):
        pickle.dump(self.data, file(self.filename,'wb'))

def parse_pls(url):
    import re
    fd = urllib2.urlopen(url)
    d = {}
    indesc = False
    for line in fd:
        line = dcode(line.strip())
        if indesc:
            if line.endswith("/description"):
                indesc = False
            line = line[:-12]
            d['description'] += '\n' + line
            continue
        if re.search("^#?$", line):
            if d and 'type' in d:
                yield d
            d = {}
            continue
        if line.startswith('#'):
            continue
        if '=' in line:
            k,v = line.split('=', 1)
            if k == 'description':
                if v.endswith("/description"):
                    v = v[:-12]
                else:
                    indesc = True
            d[k] = v
            continue
    if d and 'type' in d:
        yield d

class Item(dict):
    def __init__(self, d):
        dict.__init__(self, d)
        self._v = None
    @property
    def v(self):
        if self._v:
            return self._v
        if self['type'] == 'playlist':
            self._v = Playlist(self['URL'])
            return self._v
        if self['type'] == 'video':
            self._v = Video(self)
            return self._v
        if self['type'] == 'audio':
            self._v = Audio(self)
            return self._v

class Video(dict):
    def __str__(self):
        return 'Video(%s)' % (self.get('name', None)
            or self.get('URL',None) or hex(id(self)))
    def __repr__(self):
        return '<Video %s>' % (self.get('name', None)
            or self.get('URL',None) or hex(id(self)))

class Audio(dict):
    def __str__(self):
        return 'Audio(%s)' % (self.get('name', None)
            or self.get('URL',None) or hex(id(self)))
    def __repr__(self):
        return '<Audio %s>' % (self.get('name', None)
            or self.get('URL',None) or hex(id(self)))

class Playlist(list):
    def __init__(self, url):
        self.url = url
        self.d = d = {}
        for x in parse_pls(url):
            i = Item(x)
            if 'URL' in x:
                d[x['URL']] = i
            self.append(i)

class BaseCmd(cmd.Cmd):
    def do_EOF(self, line=None):
        print ""
        return True
    def postcmd(self, stop, line):
        global exit_until_index
        if exit_until_index:
            if hasattr(self, '__isindex'):
                exit_until_index = False
                return False
            else:
                return True
        return stop
    def emptyline(self):
        pass

class PlaylistCmd(BaseCmd):
    def __init__(self, name, playlist, *args, **kwargs):
        name = re.sub('\[\/?COLOR.*?\]','', name)
        self.prompt = name + "> "
        self.playlist = playlist
        BaseCmd.__init__(self, *args, **kwargs)
    def do_info(self, line):
        d = self._getd(line)
        if d is None:
            print "!! Cannot find %s" % line
            return
        if 'name' in d:
            for x in textwrap.wrap(d['name'], 70):
                print x
            print '-'*min(len(d['name']), 70)
        if 'description' in d:
            for l in dcode(d['description']).split('\n'):
                for x in textwrap.wrap(l):
                    if type(x) == unicode:
                        print x.encode('utf-8')
                    else:
                        try: print dcode(x)
                        except: print x.decode('iso-8859-1', 'replace')
        if 'URL' in d:
            print '[URL=%s]' % d['URL']
    do_show = do_info
    def do_list(self, line):
        line = line.strip()
        i = -1
        types = { 'playlist' : 'pls', 'vid' : 'vid' }
        pipe = Popen(PAGER_CMD, stdin=PIPE)
        for x in self.playlist:
            i += 1
            name = re.sub('\[\/?COLOR.*?\]','', x['name'])
            if line and not fnmatch(name, line):
                continue
            typ = types.get(x['type'], None) or x['type']
            out = "[%-3d] (%s) %s\n" % (i, typ, name)
            pipe.stdin.write(out.encode('utf-8','ignore'))
        pipe.stdin.close()
        pipe.wait()
    do_ls = do_list
    def do_cd(self, line):
        if line == "..":
            return True
        if line == "/":
            global exit_until_index
            exit_until_index = True
            return True
        if line.startswith("http"):
            pl = PlaylistCmd(line, Playlist(line))
            pl.onecmd("ls")
            pl.cmdloop()
            return
        elif os.path.isfile(line):
            line = os.path.abspath(line)
            pl = PlaylistCmd(line, Playlist("file://"+line))
            pl.onecmd("ls")
            pl.cmdloop()
        d = self._getd(line)
        if d is None:
            print "!! Cannot cd to %s" % line
            return
        if d['type'] == 'playlist':
            pl = PlaylistCmd(d['name'], d.v)
            pl.onecmd("ls")
            pl.cmdloop()
        else:
            print "!! Cannot cd to %s" % line
    def do_more(self, line):
        d = self._getd(line)
        if d is None:
            print "!! Cannot more %s" % line
            return
        if 'URL' in d and 'type' in d:
            if d['type'] in ('video', 'audio'):
                print "!! Cannot view binary data as a text file"
                return
            req = request(d['URL'])
            g = urllib2.urlopen(req)
            pipe = Popen(PAGER_CMD, stdin=PIPE)
            while True:
                b = g.read(512)
                if not b:
                    break
                try:
                    pipe.stdin.write(b)
                except IOError:
                    break
            pipe.stdin.close()
            pipe.wait()
            print ""
    def do_search(self, line):
        pl = Playlist("http://navix.turner3d.net/playlist/search/%s" % (
            urllib.quote_plus(line)))
        if len(pl) > 0:
            pc=PlaylistCmd("Results for '%s'" % line, pl)
            pc.onecmd("ls")
            pc.cmdloop()
        else:
            print "No results for '%s'" % line
    def do_dump(self, line):
        d = self._getd(line)
        if d is None:
            print "!! Cannot show %s" % line
            return
        pprint(d)
    def _getd(self, line):
        try:
            return self.playlist[int(line.strip())]
        except:
            return None

    def do_proc(self, line):
        d = self._getd(line)
        if d is None:
            print "!! Error calling proc with argument: %s" % line
            return
        if 'processor' in d:
            purl = "%s?url=%s" % (d['processor'], urllib.quote(d['URL']))
            print "Processing with %s" % purl
            print urllib2.urlopen(purl).read()
            print
        else:
            print "No processor required for", d['URL']

    def do_lcd(self, line):
        global DOWNLOADPATH
        chdir(line)

    def do_lls(self, line):
        if platform.system() == 'Windows':
            os.system("dir %s" % line.strip())
        else:
            os.system("ls %s" % line.strip())

    def do_get(self, line):
        fname = None
        if re.search('\d+ (to|as) .+', line):
            line, fname = line.split(' to ', 1)
        d = self._getd(line)
        if d is None:
            print "!! Error calling get with argument: %s" % line
            return
        if 'URL' in d and 'name' in d:
            if fname:
                if '/' not in fname:
                    fname = os.path.join(DOWNLOADPATH, fname)
            else:
                fname = d['name']
                fname = fname.rsplit("/",1)[-1].replace(" ","_") + ".avi"
                fname = os.path.join(DOWNLOADPATH, fname)
            if os.path.exists(fname):
                byterange = "Range: bytes=%s-" % (os.path.getsize(fname)+1)
            else:
                byterange = None
            try:
                if 'processor' in d:
                    res = scraper.navix_get(d['processor'], d['URL'], byterange=byterange, verbose=0)
                else:
                    browser = scraper.Browser()
                    if byterange:
                        res = browser.get(d['URL'], Range=byterange)
                    else:
                        res = browser.get(d['URL'])
                download(res, fname)
            except:
                import traceback
                traceback.print_exc()

    def do_getall(self, line):
        for x in line.split(";"):
            self.do_get(x)

    def do_play(self, line):
        d = self._getd(line)
        if d is None:
            print "!! Error calling play with argument: %s" % line
            return
        res = None
        if 'processor' in d and 'URL' in d:
            res = scraper.navix_get(d['processor'], d['URL'], verbose=0)
        elif 'URL' in d:
            res = urllib.urlopen(request(d['URL']))
        if res:
            mplayer = Popen(['mplayer', '-cache-min', '5', '-cache', '102400' '-'], stdin=PIPE)
            while True:
                bytes = res.read(16384)
                if not bytes:
                    break
                try:
                    mplayer.stdin.write(bytes)
                except:
                    res.close()
                    break
            mplayer.stdin.close()
        else:
            print "Missing some info required to play"

    def do_reload(self, line):
        reload(scraper)

if __name__ == '__main__':
    pl = Playlist("http://navix.turner3d.net/playlist/index.plx")
    plc = PlaylistCmd("index", pl)
    plc.__isindex = True
    plc.onecmd("ls")
    plc.cmdloop()

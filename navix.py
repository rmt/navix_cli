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
import logging
import urllib, urllib2
from pprint import pprint, pformat
from subprocess import Popen, PIPE
from fnmatch import fnmatch
import textwrap
import platform
import mimetypes
import traceback
import cookielib
#
from navix_lib import do_request, make_request
import navix_lib

# globals
PLSEARCHPATH = ['./navix.plx', '~/.navix.plx', '/etc/navix/playlist']
if platform.system() == 'Windows':
    PAGER_CMD = ["more"]
else:
    PAGER_CMD = ["less", "-eFX"]
DOWNLOADPATH=os.path.abspath('.') # current dir
exit_until_index = False # set to true in a cmd and keep returning until we're at the idx again
homedir = os.path.expanduser("~")


def chdir(path, verbose=True):
    "Change the download directory"
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

def dcode(s):
    if type(s) == unicode:
        return s
    return s.decode('utf-8', 'replace')

class myURLOpener(urllib.FancyURLopener):
    def http_error_206(self, url, fp, errcode, errmsg, headers, data=None):
        pass
myUrlClass = myURLOpener()

USER_AGENT="Mozilla/5.0 (Windows; U; Windows NT 6.1; ru; rv:1.9.2b5) Gecko/20091204 Firefox/3.6b5"

def request(url, referer=None, ua=USER_AGENT, data=None, **kwargs):
    "Make a request instance, setting User-Agent & referer if given"
    d = { "User-Agent" : ua }
    if referer:
        d['Referer'] = referer
    d.update(kwargs)
    r = urllib2.Request(url, data, d)
    return r

def ratestring(kbps):
    "Return the download rate in a human-friendly format."
    if kbps > 1024:
        return "%0.2f MB/s" % (kbps/1024)
    return "%d KB/s" % (kbps)

def guess_extension_from_url(url):
    m = re.search(r"\.(?P<ext>avi|flv|mpg|mp4|mpeg|ogv|mp3|flac|ogg)([?&]|$)", url, re.I)
    if m:
        return m.group('ext').lower()
    return None

def guess_extension(response):
    "Return an extension based on the Content-Type header in the response"
    if not response:
        return None
    ct = response.info().get('content-type')
    if ct:
        mimetype = ct.split(';')[0]
        ext = mimetypes.guess_extension(mimetype)
        if ext:
            return ext
        # otherwise try based on URL
        mimetype, _ = mimetypes.guess_type(response.geturl())
        if mimetype:
            ext = mimetypes.guess_extension(mimetype)
        return ext
    return None

def download(res, filename):
    """Download the HTTP response object to the given filename
    using VT100 codes to interactively show the progress"""
    length = res.info().get('Content-Length', None)
    strlength = length and ("%dk" % (int(length)/1024)) or "Unknown"
    i = 0 # if the destination file exists, add .$i to it
    starttime = time.time() # for rate calculation
    buf = res.read(4096) # 4k block size
    bytecount = len(buf)
    out = None
    while buf:
        if out is None:
            fname = filename
            i = 1
            if res.getcode() == 206: # partial file transfer
                # TODO / FIXME - seek to right location, in-case
                out = file(fname, "ab")
            else:
                while os.path.exists(fname):
                    fname = "%s.%d" % (fname, i)
                    i = i + 1
                out = file(fname, "wb")
            print "Downloading to %s" % fname
        out.write(buf)
        buf = res.read(4096)
        bytecount += len(buf)
        kbps = int(bytecount / (int(time.time() - starttime) or 1) / 1024.0)
        sys.stdout.write("\r\033[K[%dk / %s] (~%s)" % (bytecount//1024, strlength, ratestring(kbps)))
        sys.stdout.flush()
    out.close()
    print ""
# download

def parse_navix_pls(url):
    """Parse a navi-x format playlist entries, ignoring any type-less entries

    The Navi-X playlist has some header key/value pairs for
    the playlist, followed by a blank line (or '#' only) followed
    by blank/# separated entries, each of which has a 'type' key
    specifying the type.  Each entry may have a description, which
    will be the description up until a line ending with '/description'

    headerkey1=blah
    headerkey2=foo

    type=video
    name=Cool Video
    infotag=92m
    thumb=http://example.com/CoolVideo123_thumb.jpg
    URL=http://example.com/CoolVideo123
    proc=http://myprocs.com/proc/example.com
    description=A Cool Video about
    stuff and some other stuff/description
    #
    type=video
    name=Cool Video 2
    ...
    """
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
# parse_navix_pls

class Item(dict):
    """Represents an item in a Playlist"""
    def __str__(self):
        if self.type and self.name:
            return 'Item(%r,%r)' % (
                self.type.lower().capitalize(),
                self.name,)
        return 'Item(%s)' % (dict.__str__(self),)

    def __repr__(self):
        return pformat(dict(self))

    @property
    def type(self):
        return self.get('type', None)

    @property
    def name(self):
        return self.get('name', None)

    @property
    def url(self):
        return self.get('URL', None)

    @property
    def processor(self):
        return self.get('processor', None)

    @property
    def infotag(self):
        return self.get('infotag', None)
# Item

class Playlist(list):
    def __init__(self, url):
        self.url = url
        self.d = d = {}
        try:
            gen = parse_navix_pls(url)
        except urllib2.HTTPError:
            return
        for x in gen:
            item = Item(x)
            if item.url:
                d[item.url] = item
            self.append(item)
# Playlist

class BaseCmd(cmd.Cmd):
    """Custom Cmd base class with extra features:
    * Support recursive exiting of Cmd loop's
    * Don't error if given an empty line.
    * The EOF character will exit this Cmd loop.
    * Provide a help command that displays docstrings
    """
    def do_EOF(self, line=None):
        print ""
        return True

    def postcmd(self, stop, line):
        "Support recursive exiting"
        global exit_until_index
        if exit_until_index:
            if hasattr(self, '__isindex'):
                exit_until_index = False
                return False
            else:
                return True
        return stop

    def emptyline(self):
        "Newlines aren't error conditions"
        pass

    def default(self, line):
        if line.startswith('!'):
            os.system(line[1:])
        else:
            print "*** Unknown syntax: %s" % line

    def do_help(self, line):
        "help [command]"
        if line == '':
            cmdfuncs = [x for x in dir(self) if x.startswith('do_')]
            cmdfuncs.sort()
            # only print comments with a docstring
            for cmd in cmdfuncs:
                doc = getattr(self, cmd).__doc__
                if doc:
                    print "%s: %s" % (cmd[3:], doc.split('\n')[0])
        else:
            # call the help method if it exists
            cmd = getattr(self, 'help_%s' % (line.strip()), None)
            if cmd:
                return cmd()
            # otherwise print the docstring
            cmd = getattr(self, 'do_%s' % (line.strip()), None)
            if cmd:
                if cmd.__doc__:
                    print cmd.__doc__
                else:
                    print "%s: No help available" % (line)
            else:
                print "%s: Not a valid command"
# BaseCmd

class PlaylistCmd(BaseCmd):
    """Provides a command-line interface for navigating a playlist."""
    def __init__(self, name, playlist, *args, **kwargs):
        # strip Navi-X playlist colors from the title name
        name = re.sub('\[\/?COLOR.*?\]','', name)
        self.prompt = name + "> "
        self.playlist = playlist
        BaseCmd.__init__(self, *args, **kwargs)

    def _getd(self, line):
        "Convert a number into an Item"
        try:
            return self.playlist[int(line.strip())]
        except:
            return None

    def do_show(self, line):
        "show <num>: show a human summary of the entry"
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

    def do_info(self, line):
        self.do_show(line)

    def do_ls(self, line):
        "ls: list the entries in the current playlist"
        line = line.strip()
        i = -1
        typealiases = { 'playlist' : 'pls', }
        pipe = Popen(PAGER_CMD, stdin=PIPE)
        for item in self.playlist:
            i += 1
            name = re.sub('\[\/?COLOR.*?\]','', item['name'])
            if line and not fnmatch(name, line):
                continue
            typ = typealiases.get(item.type, item.type)
            if item.infotag:
                name = "%s [%s]" % (name, item.infotag)
            out = "[%3d] (%s) %s\n" % (i, typ, name)
            pipe.stdin.write(out.encode('utf-8','ignore'))
        pipe.stdin.close()
        pipe.wait()

    def do_cd(self, line):
        "cd <num> | cd .. | cd /: change to the given playlist, up one level, or back to the main index"
        if line == "..":
            return True
        if line == "/":
            global exit_until_index
            exit_until_index = True
            return True
        if line.startswith("http"):
            try:
                pl = PlaylistCmd(line, Playlist(line))
            except Exception, e:
                print e
                return
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
            pl = PlaylistCmd(d['name'], Playlist(d['URL']))
            pl.onecmd("ls")
            pl.cmdloop()
        else:
            print "!! Cannot cd to %s" % line

    def do_more(self, line):
        "Open a URL directly and display the output"
        item = self._getd(line)
        if item is None:
            print "!! Cannot more %s" % line
            return
        if item.url and item.type:
            if item.type in ('video', 'audio'):
                print "!! Cannot view binary data as a text file"
                return
            req = request(item.url)
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
        "search <string>: search the Navi-X database for the given string"
        pl = Playlist("http://navix.turner3d.net/playlist/search/%s" % (
            urllib.quote_plus(line)))
        if len(pl) > 0:
            pc=PlaylistCmd("Results for '%s'" % line, pl)
            pc.onecmd("ls")
            pc.cmdloop()
        else:
            print "No results for '%s'" % line

    def do_dump(self, line):
        "dump <num>: show debugging dictionary for item"
        d = self._getd(line)
        if d is None:
            print "!! Cannot show %s" % line
            return
        pprint(d)

    def do_proc(self, line):
        "proc <num>: Display the output of the given processor for the item"
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
        "lcd <dir>: change the current local directory"
        global DOWNLOADPATH
        chdir(line)

    def do_lls(self, line):
        "list the contents of the current local directory (passing arguments to the command)"
        if platform.system() == 'Windows':
            os.system("dir %s" % line.strip())
        else:
            os.system("ls %s" % line.strip())

    def do_get(self, line):
        "get <num> [to <filename>]: download the specified item"
        fname = None
        if re.search('\d+ to .+', line):
            line, fname = line.split(' to ', 1)
        d = self._getd(line)
        if d is None:
            print "!! Error calling get with argument: %s" % line
            return
        if 'URL' in d and 'name' in d:
            if fname:
                if '/' not in fname:
                    fname = os.path.abspath(os.path.join(DOWNLOADPATH, fname))
            else:
                fname = d['name']
                # add extension (.EXT will get it from the Content-Type later)
                ext = guess_extension_from_url(d['URL']) or "EXT"
                fname = fname + "." + ext
                # cleanup filename
                fname = fname.rsplit("/",1)[-1].replace(" ","_")
                fname = re.sub(r"&amp;|[;:()\/&\[\]*%#@!?]", "_", fname)
                fname = re.sub(r"__+","_", fname)
                fname = re.sub(r"\.\.+",".", fname)
                fname = fname.replace("_.", ".")
                fname = os.path.join(DOWNLOADPATH, fname)

            # evaluate NIPL processor
            try:
                request = make_request(d['URL'], d.get('processor', None))
            except:
                traceback.print_exc()
                return

            if not request:
                print "Could not download %s" % (d['URL'])
                return
            try:
                res = urllib2.urlopen(request)
            except:
                traceback.print_exc()
                res = None
            if not res:
                print "Could not download %s" % (d)
                return

            # guess filename extension if pending
            if fname.endswith(".EXT"):
                ext = guess_extension(res)
                if ext:
                    fname = fname[:-4] + ext
            # download the sucker
            print "Downloading %s" % (res.geturl())
            try:
                download(res, fname)
            except:
                traceback.print_exc()

    def do_getall(self, line):
        "getall <num>[;<num>][;<num> as myname.avi]: download multiple files in sequence"
        for x in line.split(";"):
            self.do_get(x)

    def do_geturl(self, line):
        "geturl <filename>;<url>;<processor url>: download a URL using the given processor URL"
        try:
            filename, url, proc = line.split(";", 2)
        except:
            print "Usage: geturl filename;url;processor"
            return
        try:
            request = make_request(url.strip(), proc.strip())
            res = urllib2.urlopen(request)
            download(res, filename.strip())
        except:
            traceback.print_exc()

    def do_play(self, line):
        "Try to play this video using mplayer (stream from stdin)"
        if platform.system() == 'Windows':
            print "!! No streaming support on Windows, sorry. Try 'get' instead."
            return
        d = self._getd(line)
        if d is None:
            print "!! Error calling play with argument: %s" % line
            return
        #
        request = make_request(d['URL'], d.get('processor',None))
        res = urllib2.urlopen(request)
        if res:
            mplayer = Popen(['mplayer', '-cache-min', '5', '-noconsolecontrols', '-cache', '2048', '/dev/stdin'], stdin=PIPE)
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
# PlaylistCmd


def main(args):
    global DOWNLOADPATH, PAGER_CMD, PLSEARCHPATH, homedir
    # set the default playlist

    if len(sys.argv) > 1:
        if os.path.exists(sys.argv[1]):
            pl = Playlist("file://"+sys.argv[1])
        else:
            pl = Playlist(sys.argv[1])
    else:
        localpl = None
        for plfile in PLSEARCHPATH:
            plfile = os.path.abspath(os.path.expanduser(plfile))
            if os.path.exists(plfile):
                localpl = "file://"+plfile
                break
        if localpl:
            print "Using local playlist %s" % localpl
            pl = Playlist(localpl)
        else:
            pl = Playlist("http://navix.turner3d.net/playlist/index.plx")
    if not os.access(DOWNLOADPATH, os.W_OK):
        # find a writable download directory
        for x in ('~/Downloads', '~/My Downloads', '~/Videos', '~'):
            tmppath = os.path.expanduser(x)
            if os.path.isdir(tmppath) and os.access(tmppath, os.W_OK):
                DOWNLOADPATH=tmppath
                break
    # chdir to the download dir
    chdir(DOWNLOADPATH, False)

    # load & run the playlist menu
    plc = PlaylistCmd("index", pl)
    plc.__isindex = True # used in 'cd /'
    plc.onecmd("ls")
    plc.cmdloop()

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    #navix_lib.DEBUGLEVEL = 20
    main(sys.argv)

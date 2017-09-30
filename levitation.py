#!/usr/bin/env python3

import xml.dom.minidom
from calendar import timegm
import datetime
import os
import os.path
import re
import socket
import struct
import codecs
import sys
import time
import urllib.parse
import ipaddress
import pickle
import unicodedata
from optparse import OptionParser

# The encoding for input, output and internal representation. Leave alone.
ENCODING = 'UTF-8'
# The XML namespace we support.
XMLNS = 'http://www.mediawiki.org/xml/export-0.10/'
MAX_INT64 = 0xFFFFFFFFFFFFFFFF


def tzoffset():
    r = time.strftime('%z')
    if r == '' or r == '%z':
        return None

    return r


def tzoffsetorzero():
    r = tzoffset()
    if r == None:
        return '+0000'

    return r

def singletext(node):
    res = ''
    for child in node.childNodes:
        if child.nodeType != node.TEXT_NODE:
            raise XMLError('singletext child %s is not text' % (child.toxml()))
        res += child.data
    return res


def out(text):
    sys.stdout.write(text)


def progress(text):
    out('progress ' + text + '\n')


def open_file(fn):
    if not os.path.exists(fn):
        # create the file if it doesn't exist yet
        with open(fn, 'w+b') as f:
            f.write(b'')

    # use r+b instead of w+b so the file isn't truncated on open
    return open(fn, 'r+b')


class Meta:
    def __init__(self, file):
        # L: The revision id
        # L: The datetime
        # L: The page id
        # QQ: 128 bits for IPv6. Big enough to hold IPv4 and any other ids, too
        # B: Flags about the page (minor, written by ip or deleted user)
        self.struct = struct.Struct('=LLLQQB')

        self.fh = open_file(file)

        self.domain = 'unknown.invalid'
        self.nstoid = self.idtons = {}
        self.maxrev = -1

    def write(self, rev, time, page, author, minor):
        flags = 0
        if minor:
            flags += 1

        if author.isip:
            flags += 2

        if author.isdel:
            flags += 4

        data = self.struct.pack(
            rev,
            timegm(time.utctimetuple()),
            page,
            (author.id >> 64) & MAX_INT64,
            author.id & MAX_INT64,
            flags
            )

        self.maxrev = max(self.maxrev, rev)

        self.fh.seek(rev * self.struct.size, os.SEEK_SET)
        self.fh.write(data)

    def read(self, rev):
        self.fh.seek(rev * self.struct.size)
        data = self.fh.read(self.struct.size)

        if len(data) < self.struct.size:
            return None

        data = self.struct.unpack(data)


        d = {
            'rev':    data[0],
            'epoch':  data[1],
            'time':   datetime.datetime.utcfromtimestamp(data[1]),
            'page':   data[2],
            'user':   (data[3] << 64) | data[4],
            'minor':  False,
            'isip':   False,
            'isdel':  False,
            }

        if d['rev'] != 0:
            d['exists'] = True
        else:
            d['exists'] = False

        d['day'] = d['time'].strftime('%Y-%m-%d')
        flags = data[5]

        if flags & 1:
            d['minor'] = True

        if flags & 2:
            d['isip'] = True
            d['user'] = str(ipaddress.ip_address(d['user']))

        if flags & 4:
            d['isdel'] = True

        return d


class StringStore:
    def __init__(self, file):
        # B: size of string (max 255)
        # I: flags need more space due to the occasional large Namespace ID
        # 255s:
        #   - The string, possibly trimmed to fit.
        #   - We trim to 255 because:
        #           https://www.mediawiki.org/wiki/Page_title_size_limitations
        #   - This means comments are the only thing that will be trimmed.
        #   - If the length of a comment is close to 255, just assume it's
        #   trimmed.
        #
        self.struct = struct.Struct('=BI255s')
        self.maxid = -1

        self.fh = open_file(file)

    def write(self, id, text, flags = 1):
        ba = bytes(text, ENCODING)
        if len(ba) > 255:
            progress('warning: trimming %s bytes long text: %s' % (len(ba), ba))
            text = text[:255]

        # try cutting off one unicode character at a time. this helps with
        # decoding later when the string ends with a multibyte character.
        while len(ba) > 255:
            ba = bytes(text, ENCODING)
            text = text[:-1]

        data = self.struct.pack(len(ba), flags, ba)

        self.maxid = max(self.maxid, id)

        self.fh.seek(id * self.struct.size)
        self.fh.write(data)

    def read(self, id):
        self.fh.seek(id * self.struct.size)
        packed = self.fh.read(self.struct.size)
        data = None

        if len(packed) < self.struct.size:
            # There is no such entry.
            d = {'len': 0, 'flags': 0, 'text': ''}
        else:
            data = self.struct.unpack(packed)
            d = {
                'len':   data[0],
                'flags': data[1],
                'text':  data[2][:data[0]].decode(ENCODING)
                }

        return d


class User:
    def __init__(self, node, meta):
        self.id = 0
        self.name = None
        self.isip = self.isdel = False

        if node.hasAttribute('deleted') and node.getAttribute('deleted') == 'deleted':
            self.isdel = True

        for lv1 in node.childNodes:
            if lv1.nodeType != lv1.ELEMENT_NODE:
                continue

            if lv1.tagName == 'username':
                self.name = singletext(lv1)
            elif lv1.tagName == 'id':
                self.id = int(singletext(lv1))
            elif lv1.tagName == 'ip':
                self.isip = True
                self.id = int(ipaddress.ip_address(singletext(lv1)))

        if not (self.isip or self.isdel):
            meta['user'].write(self.id, self.name)


class Revision:
    def __init__(self, node, page, meta):
        self.id = 0
        self.minor = False
        self.timestamp = self.text = self.comment = self.user = None
        self.page = page
        self.meta = meta
        self.dom = node

        for lv1 in self.dom.childNodes:
            if lv1.nodeType != lv1.ELEMENT_NODE:
                continue

            if lv1.tagName == 'id':
                self.id = int(singletext(lv1))
            elif lv1.tagName == 'timestamp':
                self.timestamp = datetime.datetime.strptime(singletext(lv1), "%Y-%m-%dT%H:%M:%SZ")
            elif lv1.tagName == 'contributor':
                self.user = User(lv1, self.meta)
            elif lv1.tagName == 'minor':
                self.minor = True
            elif lv1.tagName == 'comment':
                self.comment = singletext(lv1)
            elif lv1.tagName == 'text':
                self.text = singletext(lv1)

        self.meta['meta'].write(self.id, self.timestamp, self.page, self.user, self.minor)

        if self.comment:
            self.meta['comm'].write(self.id, self.comment)

        out('blob\nmark :{}\ndata {}\n'.format(self.id, len(bytes(self.text, ENCODING))))
        out(self.text + '\n')


class Page:
    def __init__(self, meta):
        self.title = self.fulltitle = ''
        self.nsid = 0
        self.id = 0
        self.meta = meta

    def setTitle(self, title):
        self.fulltitle = title
        split = self.fulltitle.split(':', 1)

        if len(split) > 1 and (split[0] in self.meta['meta'].nstoid):
            self.nsid = self.meta['meta'].nstoid[split[0]]
            self.title = split[1]
        else:
            self.nsid = self.meta['meta'].nstoid['']
            self.title = self.fulltitle

    def setID(self, id):
        self.id = id
        self.saveTitle()

    def saveTitle(self):
        if self.id != -1 and self.title != '':
            self.meta['page'].write(self.id, self.title, self.nsid)

    def addRevision(self, dom):
        Revision(dom, self.id, self.meta)


class XMLError(ValueError):
    pass


class CancelException(Exception):
    pass


class ParserHandler:
    def __init__(self, writer):
        self.writer = writer

    def attrSplit(self, attrs):
        if attrs == None:
            return {}
        r = {}
        for k, v in attrs.items():
            nk = self.nsSplit(k)
            r[nk] = v

        return r

    def start(self, name, attrs):
        name = self.nsSplit(name)
        self.writer.startElement(name, self.attrSplit(attrs))

    def end(self, name):
        name = self.nsSplit(name)
        self.writer.endElement(name)

    def data(self, data):
        self.writer.characters(data)


class ExpatHandler(ParserHandler):
    def run(self, what):
        self.nssepa = ' '
        self.expat = xml.parsers.expat.ParserCreate(namespace_separator = self.nssepa)
        self.expat.StartElementHandler  = self.start
        self.expat.EndElementHandler    = self.end
        self.expat.CharacterDataHandler = self.data
        self.expat.ParseFile(what.buffer)

    def nsSplit(self, name):
        s = name.split(self.nssepa, 1)
        if len(s) == 2:
            return (s[0], s[1])
        else:
            return ('', s[0])


class LxmlHandler(ParserHandler):
    def run(self, what):
        self.lxml = etree.XMLParser(target = self)
        etree.parse(what, self.lxml)

    def nsSplit(self, name):
        s = name.split('}', 1)

        if len(s) == 2:
            return (s[0][1:], s[1])
        else:
            return ('', s[0])

    def close(self):
        self.lxml = None


class StackManager:
    """Object to manage a stack of handlers for walking XML.

    At each time there are three 'active' handlers:

    0.  A handler to be called when the start of a sub-element has been read.
        This handler gets called with the tag of the element, and the dict of
        its attributes. This handler needs to return a new tuple of handlers,
        which will remain active until after the end of the sub-element has been
        read. Then we revert to the previous set of active handlers.

    1.  A handler to be called when the end of the current element has been
        read. This handler gets called with the tag of the element.

    2.  A handler to be called for text nodes. This gets called with the content
        of the text node.

    Usage:
      parser = ExpatParser(StackManager((start_doc, consume_text, end_doc))
      parser.run(sys.sys.stdin)

    Attributes:
      active: tuple of active handlers.
      stack: stack of tuples of previously active handlers, ready to be
          reinstated.
    """

    def __init__(self, initial_handlers):
        self.active = initial_handlers
        self.stack = []

    def push(self, handlers=(None, None, None)):
        """Replace the active handlers.

        Args:
          handlers: the tuple of new handlers.
        """
        self.stack.append(self.active)
        self.active = handlers

    def pop(self):
        """Revert to the previous set of active handlers."""
        if not self.stack:
            raise XMLError('more closing than opening tags')
        self.active = self.stack.pop()

    def startElement(self, tag, attrs):
        """Process the start of an element.

        That means calling the active start-of-element handler, and making a new
        set of handler active.
        """
        if self.active[0]:
            self.push(self.active[0](tag, attrs))
        else:
            # Ignore deeper elements, as there was not handler to tell us how to
            # process them.
            self.push()

    def endElement(self, name):
        """Process the end of an element."""
        if self.active[1]:
            self.active[1](name)
        self.pop()

    def characters(self, content):
        """Process a text node."""
        if self.active[2]:
            self.active[2](content)


class Cases(object):
    """Handler that dispatches to passed handlers.

    Attributes:
      cases: dict, mapping unqualified tag names to handlers to dispatch to.
    """

    def __init__(self, **kwargs):
        self.cases = kwargs

    def __call__(self, tag, attrs):
        if tag[1] in self.cases:
            return self.cases[tag[1]](tag, attrs)
        return (None, None, None)


class Capture(object):
    """Handler to save an element into a DOM.

    Attributes:
      cb: callable to be called with the root element of the DOM when the
          capture is done.
    """

    def __init__(self, cb=None):
        self.cb = cb
        self._dom = self._currentnode = None

    def __call__(self, tag, attrs):
        if self._dom or self._currentnode:
            raise XMLError("Capture requested while already in progress.")
        self._dom = xml.dom.getDOMImplementation().createDocument(
                tag[0], tag[1], None)
        self._currentnode = self._dom.documentElement
        for k, v in attrs.items():
            self._currentnode.setAttributeNS(k[0], k[1], v)
        return (self.start_sub, self.finish, self.handle_text)

    def finish(self, tag):
        if not self._dom or not self._currentnode:
            raise XMLError("Capture termination requested while not in progress.")
        if self.cb:
          self.cb(self._dom.documentElement)
        self._dom = self._currentnode = None

    def start_sub(self, tag, attrs):
        self._currentnode = self._currentnode.appendChild(
                self._dom.createElementNS(tag[0], tag[1]))
        for k, v in attrs.items():
            self._currentnode.setAttributeNS(k[0], k[1], v)
        return (self.start_sub, self.end_sub, self.handle_text)

    def end_sub(self, tag):
        self._currentnode = self._currentnode.parentNode

    def handle_text(self, content):
        self._currentnode.appendChild(self._dom.createTextNode(content))


class BlobWriter:
    """Object to parse Mediawiki XML and write out blobs.

    Attributes:
      canceled: bool, whether we canceled the operation.
      imported: int, number of pages imported so far.
      meta: dict, containing metadata, such as file locations and mediawikie
          namespace to id mapping.
      page: Current page being processed.
      parser: xml parser that this object is driven by.
    """

    def __init__(self, meta):
        self.imported = 0
        self.canceled = False
        self.meta = meta
        self.parser = self.page = None

    def parse(self, parser):
        self.parser = parser(StackManager((self.start_root, None, None)))
        try:
            self.parser.run(sys.stdin)
        except CancelException:
            if not self.canceled:
                raise

    def start_root(self, tag, attrs):
        if tag[0] != XMLNS:
            raise XMLError('XML document needs to be in MediaWiki Export Format 0.10')
        if tag[1] != 'mediawiki':
            raise XMLError('document tag is not <mediawiki>')
        return (
            Cases(
                page=self.start_page,
                siteinfo=lambda tag, attrs: (
                    Cases(
                        base=Capture(self.process_captured_base),
                        namespaces=lambda tag, attrs: (
                            Cases(
                                namespace=Capture(self.process_captured_namespace)
                            ),
                            None,
                            None,
                        ),
                    ),
                    None,
                    None,
                ),
            ),
            None,
            None,
        )

    def process_captured_base(self, node):
        self.meta['meta'].domain = urllib.parse.urlparse(singletext(node)).hostname

    def process_captured_namespace(self, node):
        key = int(node.getAttribute('key'))
        name = singletext(node)
        self.meta['meta'].idtons[key] = name
        self.meta['meta'].nstoid[name] = key

    def start_page(self, tag, attrs):
        if self.page:
            raise XMLError("Page capture requested while already in progress.")
        self.page = Page(self.meta)
        return (
            Cases(
                title=Capture(self.process_captured_title),
                id=Capture(self.process_captured_page_id),
                revision=Capture(self.process_captured_revision),
            ),
            self.end_page,
            None,
        )

    def end_page(self, name):
        if not self.page:
            raise XMLError("Page termination requested while not in progress.")
        self.page = None
        self.imported += 1
        max = self.meta['options'].IMPORT_MAX
        if max > 0 and self.imported >= max:
            self.canceled = True
            raise CancelException()

    def process_captured_title(self, node):
        self.page.setTitle(singletext(node))
        progress('   ' + self.page.fulltitle)

    def process_captured_page_id(self, node):
        self.page.setID(int(singletext(node)))

    def process_captured_revision(self, node):
        self.page.addRevision(node)


def sanitize(s):
   return s.replace('/', '\x1c')


class Committer:
    def __init__(self, meta):
        self.meta = meta
        if tzoffset() == None:
            progress('warning: using %s as local time offset since your system refuses to tell me the right one;' \
                'commit (but not author) times will most likely be wrong' % tzoffsetorzero())

    def work(self):
        # start commit id from the top to avoid hitting any ids in the XML
        commit = sys.maxsize

        rev = 0
        day = ''
        meta = self.meta['meta'].read(rev)

        while meta:
            rev += 1
            if not meta['exists']:
                meta = self.meta['meta'].read(rev)
                continue

            page = self.meta['page'].read(meta['page'])
            comm = self.meta['comm'].read(meta['rev'])
            namespace = '%d-%s' % (page['flags'], self.meta['meta'].idtons[page['flags']])

            path = sanitize(namespace)
            # delay sanitizing title so the dir structure captures the char
            title = page['text']

            for i in range(0, min(self.meta['options'].DEEPNESS, len(title))):
                path = os.path.join(path,
                                    codecs.encode(
                                        bytes(title[i], ENCODING),
                                        'hex').decode(ENCODING))

            path = os.path.join(path, sanitize(title) + '.mediawiki')

            filename = os.path.normpath(path)

            if meta['minor']:
                minor = ' (minor)'
            else:
                minor = ''

            msg = comm['text'] + '\n\nLevitation import of page %d rev %d%s.\n' % (meta['page'], meta['rev'], minor)

            if commit == sys.maxsize:
                fromline = ''
            else:
                fromline = 'from :%d\n' % (commit + 1)

            if day != meta['day']:
                day = meta['day']
                progress('   ' + day)

            if meta['isip']:
                author = meta['user']
                authoruid = 'ip-' + author
            elif meta['isdel']:
                author = '[deleted user]'
                authoruid = 'deleted'
            else:
                authoruid = 'uid-' + str(meta['user'])
                author = self.meta['user'].read(meta['user'])['text']

            # Check which committime should be used
            if self.meta['options'].WIKITIME:
                # Use the committime read from the dumpfile
                committime = meta['epoch']
                offset = '+0000'
            else:
                # Use the current systemtime
                committime = time.time()
                offset = tzoffsetorzero()

            out(
                'commit refs/heads/master\n' +
                'mark :%d\n' % commit +
                'author %s <%s@git.%s> %d +0000\n' % (author, authoruid, self.meta['meta'].domain, meta['epoch']) +
                'committer %s %d %s\n' % (self.meta['options'].COMMITTER, committime, offset) +
                'data %d\n%s\n' % (len(bytes(msg, ENCODING)), msg) +
                fromline +
                'M 100644 :%d %s\n' % (meta['rev'], filename)
                )

            commit -= 1
            meta = self.meta['meta'].read(rev)


class LevitationImport:
    def __init__(self):
        (options, _args) = self.parse_args(sys.argv[1:])
        # Select parser. Prefer lxml, fall back to Expat.
        parser = None
        try:
            if options.NOLXML:
                raise SkipParserException()

            global etree
            from lxml import etree
            parser = LxmlHandler
            progress('Using lxml parser.')
        except (ImportError, SkipParserException):
            import xml.parsers.expat
            parser = ExpatHandler
            progress('Using Expat parser.')

        if options.OVERWRITE:
            # clear the info files
            for each in ['meta.pkl', options.METAFILE, options.COMMFILE, options.USERFILE, options.PAGEFILE]:
                with open(each, 'wb+') as f:
                    f.write('')

        meta = {
            'options': options,
            'meta': Meta(options.METAFILE),
            'comm': StringStore(options.COMMFILE),
            'user': StringStore(options.USERFILE),
            'page': StringStore(options.PAGEFILE),
            }

        try:
            with open('meta.pkl', 'rb') as f:
                idtons = pickle.load(f)
            meta['meta'].idtons = idtons
            meta['meta'].nstoid = dict( (v,k) for k,v in idtons.items() )
        except (FileNotFoundError, EOFError):
            pass

        if options.ONLYBLOB:
            progress('Step 1: Creating blobs.')
            BlobWriter(meta).parse(parser)
            with open('meta.pkl', 'wb') as f:
                pickle.dump(meta['meta'].idtons, f)
        else:
            progress('Step 2: Writing commits.')
            Committer(meta).work()


        meta['meta'].fh.close()
        meta['comm'].fh.close()
        meta['user'].fh.close()
        meta['page'].fh.close()


    def parse_args(self, args):
        usage = 'Usage: git init --bare repo && bzcat pages-meta-history.xml.bz2 | \\\n' \
                '       %prog [options] | GIT_DIR=repo git fast-import | sed \'s/^progress //\''
        parser = OptionParser(usage=usage)
        parser.add_option("-m", "--max", dest="IMPORT_MAX", metavar="IMPORT_MAX",
                help="Specify the maxium pages to import, -1 for all (default: 100)",
                default=100, type="int")

        parser.add_option("-d", "--deepness", dest="DEEPNESS", metavar="DEEPNESS",
                help="Specify the deepness of the result directory structure (default: 3)",
                default=3, type="int")

        parser.add_option("-c", "--committer", dest="COMMITTER", metavar="COMITTER",
                help="git \"Committer\" used while doing the commits (default: \"Levitation <levitation@scytale.name>\")",
                default="Levitation <levitation@scytale.name>")

        parser.add_option("-w", "--wikitime", dest="WIKITIME",
                help="When set, the commit time will be set to the revision creation, not the current system time", action="store_true",
                default=False)

        parser.add_option("-M", "--metafile", dest="METAFILE", metavar="META",
                help="File for storing meta information (17 bytes/rev) (default: import-meta)",
                default="import-meta")

        parser.add_option("-C", "--commfile", dest="COMMFILE", metavar="COMM",
                help="File for storing comment information (257 bytes/rev) (default: import-comm)",
                default="import-comm")

        parser.add_option("-U", "--userfile", dest="USERFILE", metavar="USER",
                help="File for storing author information (257 bytes/author) (default: import-user)",
                default="import-user")

        parser.add_option("-P", "--pagefile", dest="PAGEFILE", metavar="PAGE",
                help="File for storing page information (257 bytes/page) (default: import-page)",
                default="import-page")

        parser.add_option("--no-lxml", dest="NOLXML",
                help="Do not use the lxml parser, even if it is available", action="store_true",
                default=False)

        parser.add_option("--only-blobs", dest="ONLYBLOB",
                help="Do not do commit yet. More files are expected.", action="store_true",
                default=False)

        parser.add_option("--overwrite", dest="OVERWRITE",
                help="Overwrite information files", action="store_true",
                default=False)

        (options, args) = parser.parse_args(args)
        return (options, args)


class SkipParserException(Exception):
    pass


if __name__ == '__main__':
    LevitationImport()

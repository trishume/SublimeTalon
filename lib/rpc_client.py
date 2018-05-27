from xmlrpc.server import SimpleXMLRPCDispatcher
from collections import defaultdict
from xml.sax.saxutils import escape
import queue
import ctypes
import json
import re
import socket
import struct
import sys
import threading
import time
import traceback
import xmlrpc.client as xmlrpclib

mutex = threading.Lock()

class opaque(object):
    items = {}

    @classmethod
    def load(cls, marshall, s):
        marshall.append(cls.items[s])
        marshall.type = 'opaque'
        marshall._value = 0

    @classmethod
    def dump(cls, marshall, value, append):
        key = '<%s %#x>' % (value.__class__.__name__, id(value))
        cls.items[key] = value
        append('<value><opaque>%s</opaque></value>' % escape(key))

class OpaqueEncoder(json.JSONEncoder):
    def default(self, value):
        key = '<%s %#x>' % (value.__class__.__name__, id(value))
        return json.dumps(key)

dispatch = defaultdict(lambda: opaque.dump)
dispatch.update(xmlrpclib.Marshaller.dispatch)
xmlrpclib.Marshaller.dispatch = dispatch
xmlrpclib.Marshaller.dispatch[type(0)] = lambda _, v, append: append("<value><i8>%d</i8></value>" % v)
# xmlrpclib.Marshaller.dispatch[type(0L)] = lambda _, v, append: append("<value><i8>%d</i8></value>" % v)
xmlrpclib.Unmarshaller.dispatch['opaque'] = opaque.load

def wrap(f):
    name = repr(f)
    if hasattr(f, '__name__'): name = f.__name__ or ''
    if hasattr(f, '__module__'): module = f.__module__ or ''

    def wrapper(*a, **kw):
        try:
            with mutex:
                return f(*a, **kw)
        except Exception as e:
            msg = 'Failed on calling {}.{} with args: {}, kwargs: {}\nException: {}' \
                .format(module, name, a, kw, str(error[0]))
            print('[!!!] ERROR:', msg)
            raise e

    wrapper.__name__ = name
    return wrapper


def register_module(module):
    for name, function in module.__dict__.items():
        if hasattr(function, '__call__'):
            server.register_function(wrap(function), name)


class ReverseConn(object):
    def __init__(self, path):
        self.path = path
        self.buf = ''
        self.q = queue.Queue()
        self.lock = threading.Lock()
        self.retry_event = threading.Event()

    def recvsize(self, n):
        while len(self.buf) < n:
            data = self.s.recv(1024)
            if not data:
                raise socket.error()
            self.buf += data
        out = self.buf[:n]
        self.buf = self.buf[n:]
        return out

    def receive(self):
        size, = struct.unpack('>I', self.recvsize(4))
        return self.recvsize(size)

    def respond(self, msg):
        with self.lock:
            self.s.send(struct.pack('>BI', 0, len(msg)))
            self.s.send(msg)

    def emit(self, cmd, args):
        self.q.put((cmd, args))

    def is_connected(self):
        return (self.s is not None)

    def kick(self):
        self.retry_event.set()

    def serve(self):
        while True:
            data = self.receive()
            resp = server._marshaled_dispatch(data)
            self.respond(resp)

    def connect_thread(self):
        while True:
            self.s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                self.s.connect(self.path)
            except Exception:
                # print('connection failed')
                self.s = None
                self.retry_event.wait()
                self.retry_event.clear()
                continue
            try:
                self.serve()
            except Exception:
                traceback.print_exc()
                print('Talon connection lost')
                try: self.close()
                except Exception: pass

    def emit_thread(self):
        while True:
            try:
                cmd, d = self.q.get()
                if not self.s:
                    continue
                d['cmd'] = cmd
                msg = json.dumps(d, cls=OpaqueEncoder)
                with self.lock:
                    self.s.send(struct.pack('>BI', 1, len(msg)))
                    self.s.send(msg.encode('utf-8'))
            except Exception:
                traceback.print_exc()
                self.close()

    def close(self):
        try:
            self.s.shutdown(socket.SHUT_RDWR)
            self.s.close()
        except: pass
        self.s = None

    def spawn(self):
        t = threading.Thread(target=self.connect_thread)
        t.daemon = True
        t.start()
        t = threading.Thread(target=self.emit_thread)
        t.daemon = True
        t.start()

def test_stuff_add(a,b):
    return a+b

server = SimpleXMLRPCDispatcher(allow_none=True)
# register_module(idc)
server.register_function(wrap(test_stuff_add), 'test_stuff_add')
server.register_introspection_functions()

conn = ReverseConn('/tmp/talon_editor_socket')
conn.spawn()

# time.sleep(2)
# conn.emit("test", {'a':"lol hi", 'b':5})
# time.sleep(2)


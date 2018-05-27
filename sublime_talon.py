import sublime
import sublime_plugin
import time

from .lib import rpc_client

# state_tracker = StateTracker()

class RpcTestCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        start = time.perf_counter()
        print(rpc_client.conn.is_connected())

        # rpc_client.conn.emit("test", {'a':"lol hi", 'b':5})
        # print("lol")

        # regions = self.view.find_by_selector("entity, variable, meta.generic-name")
        # print(len(regions))

        # regions = self.view.find_all("[a-zA-Z][a-zA-Z0-9_]*")
        # print(len(regions))

        state_tracker = StateTracker()
        state_tracker.update(self.view)

        end = time.perf_counter()
        print("test: ", end - start)

class BufferState(object):
    def __init__(self):
        self.last_bg_edit = -1
        self.bg_symbols = None
        self.last_fg_edit = -1
        self.fg_symbols = None

class StateTracker(object):
    def __init__(self):
        self.buffers = {}

    def _update_bg_buffer(self, state, view):
        if view.change_count() == state.last_bg_edit:
            return

        state.last_bg_edit = view.change_count()
        print("bg updating", view.file_name())

        regions = view.find_by_selector("entity.name, variable.other.member, variable.other.readwrite.member")
        idents = set()
        for region in regions:
            for s in view.substr(region).split("::"):
                idents.add(s)

        # for (_, sym) in view.symbols():
        #     idents.add(sym)

        # TODO add selector for record fields

        state.bg_symbols = idents

    def _update_fg_buffer(self, state, view):
        if view.change_count() == state.last_fg_edit:
            return

        state.last_fg_edit = view.change_count()
        print("fg updating", view.file_name())

        # TODO extract comment regions and exclude those
        # TODO only search +/- 50 line window
        # regions = view.find_all("[a-zA-Z_][a-zA-Z0-9_]*")
        # idents = set()
        # for region in regions:
        #     idents.add(view.substr(region))

        extractions = []
        view.find_all("([a-zA-Z_][a-zA-Z0-9_]*)", 0, "\\1", extractions)
        # print(extractions[0:10])
        idents = set(extractions)

        state.fg_symbols = idents

    def update(self, view):
        window = view.window()
        active_buffer = window.active_view().buffer_id()

        new_buffers = {}
        for view in window.views():
            buf_id = view.buffer_id()
            buf_state = self.buffers.get(buf_id)
            if buf_state is None:
                buf_state = BufferState()

            if view.buffer_id() == active_buffer:
                self._update_fg_buffer(buf_state, view)
            else:
                self._update_bg_buffer(buf_state, view)

            new_buffers[buf_id] = buf_state

        self.buffers = new_buffers

    def get_top_symbols(self, view):
        symbols = set()

        for k, buf in self.buffers.items():
            if buf.bg_symbols is not None:
                symbols.update(buf.bg_symbols)

        active_state = self.buffers.get(view.buffer_id())
        if active_state:
            symbols.update(active_state.fg_symbols)

        print("got top symbols: ", len(symbols))

        return list(symbols)


class TalonListener(sublime_plugin.EventListener):
    def __init__(self):
        self.last_tick = 0.0
        self.state_tracker = StateTracker()

    def _update(self, view):
        if not rpc_client.conn.is_connected():
            rpc_client.conn.kick()
            return

        start = time.perf_counter()

        self.state_tracker.update(view)
        top_symbols = self.state_tracker.get_top_symbols(view)

        rpc_client.conn.emit("update_symbols", {'symbols':top_symbols})

        end = time.perf_counter()
        print("update: ", end - start)

    def _kick(self, view):
        if view is None:
            return

        now = time.perf_counter()
        if now < self.last_tick + 2.0:
            return
        self.last_tick = now

        self._update(view)

    def on_modified_async(self, view):
        self._kick(view)

    def on_load_async(self, view):
        self._kick(view)

    def on_activated_async(self, view):
        self._kick(view)

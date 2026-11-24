# -*- coding: utf-8 -*-
"""
Plugin Win11Tabs para o Editor de Texto (xed) do Linux Mint:
1. Barra de guias (abas) sempre visível no topo, mesmo com apenas 1 guia aberta,
   com botão '+' integrado na barra de abas (estilo Bloco de Notas do Windows 11).
2. Persistência automática de sessão local (~/.config/xed/session_state.json):
   - Salva automaticamente tudo o que você escreve em abas de rascunho ("Sem título")
     e em arquivos abertos, em tempo real (a cada digitação) e ao fechar a janela,
     SEM exigir que você salve/baixe um arquivo .txt no computador.
   - Ao fechar o Editor de Texto (no X da janela, Alt+F4 ou Ctrl+Q), não exibe o diálogo
     pedindo para salvar arquivo: guarda tudo na sessão local e fecha imediatamente.
   - Ao abrir o Editor de Texto novamente, restaura todas as abas e todo o texto
     que você havia escrito exatamente onde parou.
"""

import json
import os
from gi.repository import GObject, Gio, GLib, Gtk, Gdk, Xed

SESSION_DIR = os.path.expanduser("~/.config/xed")
SESSION_FILE = os.path.join(SESSION_DIR, "session_state.json")


def find_xed_notebook(widget):
    if isinstance(widget, Xed.Notebook):
        return widget
    if isinstance(widget, Gtk.Container):
        for child in widget.get_children():
            res = find_xed_notebook(child)
            if res is not None:
                return res
    return None


class Win11TabsPlugin(GObject.Object, Xed.WindowActivatable):
    __gtype_name__ = "Win11TabsPlugin"

    window = GObject.Property(type=Xed.Window)

    def __init__(self):
        GObject.Object.__init__(self)
        self._notebook = None
        self._window_closing = False
        self._restoring = True
        self._save_timer_id = 0
        self._handlers = []
        self._nb_handlers = []
        self._widget_handlers = []
        self._doc_handlers = {}
        self._accel_group = None
        self._plus_box = None

    def do_activate(self):
        os.makedirs(SESSION_DIR, exist_ok=True)
        self._window_closing = False
        self._restoring = True

        # 1. Encontra o Xed.Notebook principal da janela
        self._notebook = find_xed_notebook(self.window)
        if self._notebook is not None:
            self._notebook.set_show_tabs(True)
            self._notebook.set_scrollable(True)
            h1 = self._notebook.connect("notify::show-tabs", self._on_notify_show_tabs)
            h2 = self._notebook.connect("switch-page", self._on_switch_page)
            h3 = self._notebook.connect("page-reordered", self._on_page_reordered)
            self._nb_handlers.extend([h1, h2, h3])
            self._setup_new_tab_button()

        # 2. Aplica estilo CSS inspirado nas guias do Bloco de Notas do Windows 11
        self._apply_win11_tab_css()

        # 3. Atalhos de teclado: Ctrl+T (Nova guia), Ctrl+Tab / Ctrl+Shift+Tab (Alternar guias)
        self._setup_shortcuts()

        # 4. Intercepta fechamento da janela (X da janela, Alt+F4, Ctrl+Q e menu Arquivo -> Sair)
        self._hook_quit_menu()
        self._handlers.append(self.window.connect("key-press-event", self._on_window_key_press))
        self._handlers.append(self.window.connect("delete-event", self._on_window_delete))
        self._handlers.append(self.window.connect("tab-added", self._on_tab_added))
        self._handlers.append(self.window.connect("tab-removed", self._on_tab_removed))

        for doc in self.window.get_documents():
            self._connect_document(doc)

        # 5. Restaura as guias e rascunhos de texto da sessão anterior
        GLib.timeout_add(150, self._restore_session_tabs)

    def do_deactivate(self):
        if self._save_timer_id > 0:
            GLib.source_remove(self._save_timer_id)
            self._save_timer_id = 0

        for h in self._handlers:
            try:
                self.window.disconnect(h)
            except Exception:
                pass
        self._handlers.clear()

        for w, h in self._widget_handlers:
            try:
                w.disconnect(h)
            except Exception:
                pass
        self._widget_handlers.clear()

        if self._notebook is not None:
            for h in self._nb_handlers:
                try:
                    self._notebook.disconnect(h)
                except Exception:
                    pass
            self._nb_handlers.clear()
            if self._plus_box is not None:
                try:
                    self._notebook.set_action_widget(None, Gtk.PackType.END)
                except Exception:
                    pass
                self._plus_box = None

        for doc, hlist in list(self._doc_handlers.items()):
            for h in hlist:
                try:
                    doc.disconnect(h)
                except Exception:
                    pass
        self._doc_handlers.clear()

        if self._accel_group is not None:
            try:
                self.window.remove_accel_group(self._accel_group)
            except Exception:
                pass
            self._accel_group = None

    def _hook_quit_menu(self):
        try:
            ui_manager = self.window.get_ui_manager()
            if not ui_manager:
                return
            quit_item = ui_manager.get_widget("/MenuBar/FileMenu/FileQuitMenu")
            if quit_item is not None:
                h = quit_item.connect("button-press-event", lambda *a: self._prepare_silent_close())
                self._widget_handlers.append((quit_item, h))
        except Exception:
            pass

    def _on_window_key_press(self, window, event):
        # Se o usuário pressionar Ctrl+Q, salva a sessão e fecha silenciosamente sem popup
        state = event.state & Gtk.accelerator_get_default_mod_mask()
        if state == Gdk.ModifierType.CONTROL_MASK and event.keyval in (Gdk.KEY_q, Gdk.KEY_Q):
            self._prepare_silent_close()
            self.window.close()
            return True
        return False

    def _prepare_silent_close(self):
        """Salva todo o estado das guias/rascunhos na sessão local e limpa a flag modified
        para que o xed feche instantaneamente sem exigir salvar um arquivo .txt no disco."""
        if not self._restoring:
            self._write_session_to_disk()
        self._window_closing = True
        for doc in self.window.get_documents():
            try:
                doc.set_modified(False)
            except Exception:
                pass
        return False

    def _on_window_delete(self, window, event):
        self._prepare_silent_close()
        return False

    def _on_notify_show_tabs(self, notebook, pspec):
        if not notebook.get_show_tabs():
            notebook.set_show_tabs(True)

    def _on_switch_page(self, notebook, page, page_num):
        if not self._restoring and not self._window_closing:
            self._schedule_save_session()

    def _on_page_reordered(self, notebook, child, page_num):
        if not self._restoring and not self._window_closing:
            self._schedule_save_session()

    def _setup_new_tab_button(self):
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        btn = Gtk.Button.new_from_icon_name("list-add-symbolic", Gtk.IconSize.MENU)
        btn.set_relief(Gtk.ReliefStyle.NONE)
        btn.set_tooltip_text("Nova guia (Ctrl+T)")
        btn.set_focus_on_click(False)
        btn.connect("clicked", lambda b: self.window.create_tab(True))
        box.pack_start(btn, False, False, 4)
        box.show_all()
        self._plus_box = box
        self._notebook.set_action_widget(box, Gtk.PackType.END)

    def _apply_win11_tab_css(self):
        try:
            css = b"""
            notebook > header.top {
                padding-top: 3px;
                padding-left: 6px;
            }
            notebook > header.top > tabs > tab {
                min-height: 28px;
                padding: 4px 10px;
                margin-right: 3px;
                border-radius: 7px 7px 0 0;
            }
            """
            provider = Gtk.CssProvider()
            provider.load_from_data(css)
            screen = Gdk.Screen.get_default()
            if screen is not None:
                Gtk.StyleContext.add_provider_for_screen(
                    screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
                )
        except Exception:
            pass

    def _setup_shortcuts(self):
        self._accel_group = Gtk.AccelGroup()
        self.window.add_accel_group(self._accel_group)

        # Ctrl+T -> Nova guia
        key_t, mod_t = Gtk.accelerator_parse("<Control>t")
        self._accel_group.connect(
            key_t,
            mod_t,
            Gtk.AccelFlags.VISIBLE,
            lambda *a: (self.window.create_tab(True), True)[1],
        )

        # Ctrl+Tab -> Próxima guia
        key_tab, mod_tab = Gtk.accelerator_parse("<Control>Tab")
        self._accel_group.connect(
            key_tab,
            mod_tab,
            Gtk.AccelFlags.VISIBLE,
            self._on_ctrl_tab_next,
        )

        # Ctrl+Shift+Tab -> Guia anterior
        key_stab, mod_stab = Gtk.accelerator_parse("<Control><Shift>ISO_Left_Tab")
        self._accel_group.connect(
            key_stab,
            mod_stab,
            Gtk.AccelFlags.VISIBLE,
            self._on_ctrl_tab_prev,
        )

    def _on_ctrl_tab_next(self, *args):
        if self._notebook is not None:
            n = self._notebook.get_n_pages()
            if n > 1:
                cur = self._notebook.get_current_page()
                self._notebook.set_current_page((cur + 1) % n)
        return True

    def _on_ctrl_tab_prev(self, *args):
        if self._notebook is not None:
            n = self._notebook.get_n_pages()
            if n > 1:
                cur = self._notebook.get_current_page()
                self._notebook.set_current_page((cur - 1 + n) % n)
        return True

    def _connect_document(self, doc):
        if doc in self._doc_handlers:
            return
        h1 = doc.connect("changed", lambda d: self._schedule_save_session())
        h2 = doc.connect("loaded", lambda d, *a: self._schedule_save_session())
        h3 = doc.connect("saved", lambda d, *a: self._schedule_save_session())
        self._doc_handlers[doc] = [h1, h2, h3]

    def _on_tab_added(self, window, tab):
        if self._notebook is not None and not self._notebook.get_show_tabs():
            self._notebook.set_show_tabs(True)
        doc = tab.get_document()
        if doc is not None:
            self._connect_document(doc)
        if not self._restoring and not self._window_closing:
            self._schedule_save_session()

    def _on_tab_removed(self, window, tab):
        if self._notebook is not None and not self._notebook.get_show_tabs():
            self._notebook.set_show_tabs(True)
        doc = tab.get_document()
        if doc in self._doc_handlers:
            for h in self._doc_handlers.pop(doc):
                try:
                    doc.disconnect(h)
                except Exception:
                    pass
        if not self._window_closing and not self._restoring:
            self._write_session_to_disk()

    def _schedule_save_session(self):
        if self._restoring or self._window_closing:
            return
        if self._save_timer_id > 0:
            GLib.source_remove(self._save_timer_id)
        self._save_timer_id = GLib.timeout_add(300, self._on_save_timer)

    def _on_save_timer(self):
        self._save_timer_id = 0
        if not self._restoring and not self._window_closing:
            self._write_session_to_disk()
        return False

    def _get_doc_text_and_cursor(self, doc):
        start, end = doc.get_bounds()
        text = doc.get_text(start, end, True)
        try:
            insert_mark = doc.get_insert()
            cursor_iter = doc.get_iter_at_mark(insert_mark)
            cursor_offset = cursor_iter.get_offset()
        except Exception:
            cursor_offset = len(text)
        return text, cursor_offset

    def _get_ordered_documents(self):
        docs = []
        if self._notebook is not None:
            n = self._notebook.get_n_pages()
            for i in range(n):
                page = self._notebook.get_nth_page(i)
                if hasattr(page, "get_document"):
                    doc = page.get_document()
                    if doc is not None:
                        docs.append(doc)
        if not docs:
            docs = list(self.window.get_documents())
        return docs

    def _write_session_to_disk(self):
        if self._restoring:
            return False
        docs = self._get_ordered_documents()
        active_doc = self.window.get_active_document()
        tabs_data = []
        active_index = 0

        for doc in docs:
            loc = doc.get_location()
            uri = loc.get_uri() if loc is not None else None
            text, cursor_offset = self._get_doc_text_and_cursor(doc)
            is_modified = bool(doc.get_modified())

            # Ignora aba vazia "Sem título" se ela for a única aba e estiver em branco
            if uri is None and text == "" and len(docs) == 1:
                continue

            if doc == active_doc:
                active_index = len(tabs_data)

            entry = {
                "uri": uri,
                "cursor_offset": cursor_offset,
                "unsaved": True if uri is None else is_modified,
            }
            if uri is None or is_modified:
                entry["text"] = text
            tabs_data.append(entry)

        try:
            with open(SESSION_FILE, "w", encoding="utf-8") as f:
                json.dump(
                    {"active_index": active_index, "tabs": tabs_data},
                    f,
                    ensure_ascii=False,
                    indent=2,
                )
        except Exception:
            pass
        return False

    def _populate_draft_doc(self, doc, text, cursor_offset):
        try:
            doc.begin_not_undoable_action()
            doc.set_text(text)
            doc.end_not_undoable_action()
        except Exception:
            doc.set_text(text)
        try:
            it = doc.get_iter_at_offset(cursor_offset)
            doc.place_cursor(it)
        except Exception:
            pass

    def _restore_session_tabs(self):
        self._restoring = True
        try:
            saved_tabs = []
            saved_active_idx = 0
            if os.path.exists(SESSION_FILE):
                with open(SESSION_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if "tabs" in data:
                        saved_tabs = data.get("tabs", [])
                        saved_active_idx = data.get("active_index", 0)
                    elif "uris" in data:
                        saved_tabs = [{"uri": u, "unsaved": False} for u in data.get("uris", [])]

            if not saved_tabs:
                return False

            initial_docs = self._get_ordered_documents()
            opened_with_files = [
                d.get_location().get_uri()
                for d in initial_docs
                if d.get_location() is not None
            ]

            reusable_blank_tab = None
            if (
                len(initial_docs) == 1
                and initial_docs[0].get_location() is None
                and self._get_doc_text_and_cursor(initial_docs[0])[0] == ""
            ):
                reusable_blank_tab = Xed.Tab.get_from_document(initial_docs[0])

            created_tabs = []
            clicked_active_tab = self.window.get_active_tab() if opened_with_files else None

            for entry in saved_tabs:
                uri = entry.get("uri")
                text = entry.get("text", "")
                cursor_offset = entry.get("cursor_offset", 0)
                unsaved = entry.get("unsaved", False)

                if uri is None:
                    if reusable_blank_tab is not None:
                        tab = reusable_blank_tab
                        reusable_blank_tab = None
                    else:
                        tab = self.window.create_tab(False)
                    doc = tab.get_document()
                    self._connect_document(doc)
                    self._populate_draft_doc(doc, text, cursor_offset)
                    created_tabs.append(tab)
                else:
                    if uri in opened_with_files:
                        for d in initial_docs:
                            if d.get_location() and d.get_location().get_uri() == uri:
                                t = Xed.Tab.get_from_document(d)
                                if t is not None:
                                    created_tabs.append(t)
                                if unsaved and "text" in entry:
                                    d.connect(
                                        "loaded",
                                        lambda doc_loaded, *a, txt=text, cur=cursor_offset: self._populate_draft_doc(
                                            doc_loaded, txt, cur
                                        ),
                                    )
                                break
                        continue

                    gfile = Gio.File.new_for_uri(uri)
                    if gfile.query_exists(None):
                        tab = self.window.create_tab_from_location(
                            gfile, None, 0, 0, False, False
                        )
                        if tab is not None:
                            doc = tab.get_document()
                            self._connect_document(doc)
                            if unsaved and "text" in entry:
                                doc.connect(
                                    "loaded",
                                    lambda doc_loaded, *a, txt=text, cur=cursor_offset: self._populate_draft_doc(
                                        doc_loaded, txt, cur
                                    ),
                                )
                            created_tabs.append(tab)

            if reusable_blank_tab is not None and len(created_tabs) > 0:
                try:
                    self.window.close_tab(reusable_blank_tab)
                except Exception:
                    pass

            if clicked_active_tab is not None:
                self.window.set_active_tab(clicked_active_tab)
            elif created_tabs:
                idx = max(0, min(len(created_tabs) - 1, saved_active_idx))
                self.window.set_active_tab(created_tabs[idx])
        except Exception:
            pass
        finally:
            self._restoring = False
            self._write_session_to_disk()
        return False

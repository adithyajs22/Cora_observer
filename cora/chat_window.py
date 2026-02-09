import sys
import threading
import os

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QPixmap, QAction
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QVBoxLayout, QHBoxLayout,
    QLabel, QTextEdit, QPushButton,
    QScrollArea, QFrame, QFileDialog,
    QMenu
)

try:
    import speech_recognition as sr
except ImportError:
    sr = None

AGENT_ICON = "cora.webp"


class ChatWindow(QMainWindow):
    send_message_signal = pyqtSignal(str)
    ai_response_signal = pyqtSignal(str)
    stream_token_signal = pyqtSignal(str)
    stream_finished_signal = pyqtSignal()
    stop_signal = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.listening = False
        self.recognizer = sr.Recognizer() if sr else None

        self.init_ui()
        self.stream_token_signal.connect(self.append_stream_token)
        self.ai_response_signal.connect(self.add_ai_message)
        self.stream_finished_signal.connect(self.on_stream_finished)

    # ---------------- UI ---------------- #

    def init_ui(self):
        self.setWindowTitle("CORA · Contextual Observer")
        self.resize(480, 720)

        self.setStyleSheet("""
        QMainWindow {
            background: #0b0f14;
        }
        QScrollBar:vertical {
            width: 6px;
            background: transparent;
        }
        QScrollBar::handle:vertical {
            background: #1f2937;
            border-radius: 3px;
        }
        """)

        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        self.create_header(layout)
        self.create_chat_area(layout)
        self.create_input_bar(layout)

        self.add_ai("Cora is online. I’m observing and ready.")

    def create_header(self, parent):
        bar = QFrame()
        bar.setFixedHeight(60)
        bar.setStyleSheet("""
        QFrame {
            background: #0f172a;
            border-radius: 16px;
            border: 1px solid #1f2937;
        }
        """)

        h = QHBoxLayout(bar)
        h.setContentsMargins(18, 10, 18, 10)

        title = QLabel("CORA")
        title.setStyleSheet("""
        QLabel {
            color: #e5e7eb;
            font-size: 18px;
            font-weight: 600;
            letter-spacing: 0.5px;
        }
        """)

        status = QLabel("● Active")
        status.setStyleSheet("""
        QLabel {
            color: #22c55e;
            font-size: 12px;
        }
        """)

        h.addWidget(title)
        h.addWidget(status)
        h.addStretch()

        parent.addWidget(bar)

    def create_chat_area(self, parent):
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet("QScrollArea { border: none; }")

        self.chat_widget = QWidget()
        self.chat_layout = QVBoxLayout(self.chat_widget)
        self.chat_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.chat_layout.setSpacing(14)

        self.scroll.setWidget(self.chat_widget)
        parent.addWidget(self.scroll, 1)

    def create_input_bar(self, parent):
        bar = QFrame()
        bar.setStyleSheet("""
        QFrame {
            background: #0f172a;
            border-radius: 20px;
            border: 1px solid #1f2937;
        }
        """)

        h = QHBoxLayout(bar)
        h.setContentsMargins(14, 12, 14, 12)
        h.setSpacing(10)

        self.input = QTextEdit()
        self.input.setPlaceholderText("Message Cora…")
        self.input.setMaximumHeight(80)
        self.input.setStyleSheet("""
        QTextEdit {
            background: transparent;
            border: none;
            color: #e5e7eb;
            font-size: 14px;
            padding: 6px;
        }
        QTextEdit::placeholder {
            color: #6b7280;
        }
        """)
        self.input.textChanged.connect(self.update_send_button_state)

        attach = QPushButton("📎")
        attach.clicked.connect(self.attach_file)
        attach.setStyleSheet(self.icon_btn_style())

        self.mic = QPushButton("🎤")
        self.mic.clicked.connect(self.toggle_voice)
        self.mic.setStyleSheet(self.icon_btn_style())

        self.send = QPushButton("➤")
        # Initialize disabled
        self.send.setEnabled(False) 
        self.send.clicked.connect(self.on_send_click)
        self.send.setStyleSheet("""
        QPushButton {
            background: #2563eb;
            border-radius: 14px;
            padding: 8px 16px;
            color: white;
            font-size: 14px;
        }
        QPushButton:hover {
            background: #3b82f6;
        }
        QPushButton:disabled {
            background: #1e293b;
            color: #64748b;
        }
        """)

        h.addWidget(self.input, 1)
        h.addWidget(attach)
        h.addWidget(self.mic)
        h.addWidget(self.send)

        parent.addWidget(bar)
        
        self.is_generating = False

    def icon_btn_style(self):
        return """
        QPushButton {
            background: transparent;
            color: #9ca3af;
            font-size: 16px;
            border: none;
            padding: 6px;
        }
        QPushButton:hover {
            color: #e5e7eb;
        }
        """

    def update_send_button_state(self):
        # Only enable if text exists AND we are not generating (or if generating, it's always enabled as Stop)
        if self.is_generating:
            self.send.setEnabled(True)
        else:
            has_text = bool(self.input.toPlainText().strip())
            self.send.setEnabled(has_text)

    def on_send_click(self):
        if self.is_generating:
            # Stop action
            self.stop_signal.emit()
            # We don't immediately toggle back, wait for backend to confirm stop or just toggle UI?
            # For responsiveness, toggle UI now.
            self.set_generating_state(False)
            self.add_ai("Stopped.")
        else:
            self.on_send()

    def set_generating_state(self, is_generating):
        self.is_generating = is_generating
        if is_generating:
            self.send.setText("⏹") # Stop icon
            self.send.setEnabled(True)
            self.send.setStyleSheet("""
            QPushButton {
                background: #dc2626;
                border-radius: 14px;
                padding: 8px 16px;
                color: white;
                font-size: 14px;
            }
            QPushButton:hover {
                background: #ef4444;
            }
            """)
        else:
            self.send.setText("➤")
            self.send.setStyleSheet("""
            QPushButton {
                background: #2563eb;
                border-radius: 14px;
                padding: 8px 16px;
                color: white;
                font-size: 14px;
            }
            QPushButton:hover {
                background: #3b82f6;
            }
            QPushButton:disabled {
                background: #1e293b;
                color: #64748b;
            }
            """)
            self.update_send_button_state()

    # ---------------- Chat Bubbles ---------------- #

    def bubble(self, text, role, attachment=None):
        row = QHBoxLayout()

        bg = "#2563eb" if role == "user" else "#020617"
        # Role-based border
        border = "#1d4ed8" if role == "user" else "#1f2937"

        frame = QFrame()
        frame.setStyleSheet(f"""
        QFrame {{
            background: {bg};
            border-radius: 18px;
            border: 1px solid {border};
            padding: 8px 12px;
        }}
        """)
        
        # Context Menu
        frame.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        frame.customContextMenuRequested.connect(lambda pos: self.show_context_menu(pos, frame, role, text))

        v = QVBoxLayout(frame)
        v.setSpacing(4)
        v.setContentsMargins(0, 0, 0, 0)

        if role == "ai" and os.path.exists(AGENT_ICON):
            icon = QLabel()
            pix = QPixmap(AGENT_ICON).scaled(24, 24, Qt.AspectRatioMode.KeepAspectRatio)
            icon.setPixmap(pix)
            # icon.setStyleSheet("border: none; background: transparent;") # basic clean
            v.addWidget(icon)

        msg = QLabel(text)
        msg.setWordWrap(True)
        msg.setStyleSheet("""
        QLabel {
            color: #e5e7eb;
            font-size: 14px;
            line-height: 1.4;
            background: transparent;
            border: none;
        }
        """)
        msg.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        v.addWidget(msg)

        if attachment:
            att = QLabel(f"📎 {os.path.basename(attachment)}")
            att.setStyleSheet("""
            QLabel {
                color: #93c5fd;
                font-size: 12px;
                background: transparent;
                border: none;
            }
            """)
            v.addWidget(att)

        if role == "user":
            row.addStretch()
            row.addWidget(frame)
        else:
            row.addWidget(frame)
            row.addStretch()

        container = QWidget()
        container.setLayout(row)
        self.chat_layout.addWidget(container)

        QTimer.singleShot(50, self.scroll_to_bottom)

    def show_context_menu(self, pos, widget, role, text):
        menu = QMenu()
        menu.setStyleSheet("""
        QMenu {
            background-color: #1f2937;
            color: white;
            border: 1px solid #374151;
        }
        QMenu::item:selected {
            background-color: #374151;
        }
        """)
        
        if role == "user":
            edit_action = QAction("Edit", self)
            edit_action.triggered.connect(lambda: self.edit_message(text))
            menu.addAction(edit_action)
        elif role == "ai":
            regen_action = QAction("Regenerate", self)
            regen_action.triggered.connect(self.regenerate_last_user_message)
            menu.addAction(regen_action)
            
        copy_action = QAction("Copy", self)
        copy_action.triggered.connect(lambda: QApplication.clipboard().setText(text))
        menu.addAction(copy_action)
        
        menu.exec(widget.mapToGlobal(pos))

    def edit_message(self, original_text):
        # Simpler: Just prompt to send corrected message. 
        # Truly editing past history is complex in this architecture without ID tracking.
        # We will treat "Edit" as "Copy to input, let user fix, and send new".
        
        # 1. Put text in input
        self.input.setText(original_text)
        self.input.setFocus()
        self.update_send_button_state()
        
        # Optional: Ask user if they want to 'edit' (which effectively means resending)
        # For now, just placing it in input is a good "Edit" workflow for a simple chat app.
        
    def regenerate_last_user_message(self):
        # We need to find the last user message text.
        # This is a bit hacky without a message model list, but we can iterate the layout.
        
        last_user_text = ""
        # Iterate backwards
        count = self.chat_layout.count()
        
        # Retrieval from UI:
        for i in range(count - 1, -1, -1):
            container = self.chat_layout.itemAt(i).widget()
            if not container: continue
            layout = container.layout()
            if not layout: continue
            
            # Check alignment: User messages have spacer at start (index 0 is stretch)
            # Actually: user layout is [Stretch, Frame]. AI is [Frame, Stretch].
            
            # Check if User
            if layout.count() > 0:
                first_item = layout.itemAt(0)
                if first_item and first_item.spacerItem(): # It's a spacer -> User message
                    # Frame is at index 1
                    frame = layout.itemAt(1).widget()
                    if frame:
                        # Find Label
                        labels = frame.findChildren(QLabel)
                        for lbl in labels:
                            if lbl.wordWrap(): # It's the message body
                                last_user_text = lbl.text()
                                break
                    if last_user_text:
                        break
        
        if last_user_text:
            self.on_send(text=last_user_text) # Re-send custom method
            
    def add_user(self, text, attachment=None):
        self.bubble(text, "user", attachment)

    def add_ai(self, text):
        self.bubble(text, "ai")
        # Legacy: If we get text, it's usually a full message OR start of stream. 
        # But main.py now handles stream finishing.
        # If text is not empty and not "Stopped.", maybe keep generating state?
        # Actually, for "Stopped." we manually set state in on_send_click.
        pass

    def on_stream_finished(self):
        self.set_generating_state(False)
        self.enable_input() # Redundant but safe
        self.input.setFocus()

    def on_send(self, text=None):
        if not text:
            text = self.input.toPlainText().strip()
            
        if not text:
            # Should be disabled, but double check
            return

        self.input.clear()
        self.disable_input()
        self.stop_listening()
        self.set_generating_state(True) # Start generating state

        self.add_user(text)
        self.send_message_signal.emit(text)

    def attach_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Attach File")
        if path:
            self.add_user("Attached a file", attachment=path)

    def toggle_voice(self):
        if not self.recognizer:
            self.input.setPlaceholderText("Voice unavailable")
            return

        if self.listening:
            self.stop_listening()
        else:
            self.start_listening()

    def start_listening(self):
        self.listening = True
        self.mic.setText("⏹")
        threading.Thread(target=self.listen_voice, daemon=True).start()

    def stop_listening(self):
        self.listening = False
        self.mic.setText("🎤")

    def listen_voice(self):
        if not self.recognizer or not sr:
             print("Voice Error: SpeechRecognition not initialized.")
             return
        try:
            print("Listening for voice...")
            with sr.Microphone() as source:
                self.recognizer.adjust_for_ambient_noise(source, duration=0.5)
                # Reduced timeout to fail faster if no audio
                audio = self.recognizer.listen(source, timeout=7, phrase_time_limit=10)
                print("Voice captured. Recognizing...")
                text = self.recognizer.recognize_google(audio)
                print(f"Recognized: {text}")
                
                # We need to emit or use QTimer to update UI on main thread
                # USING partial or default arg to bind 'text' value safely
                QTimer.singleShot(0, lambda t=text: self.process_voice_result(t))
        except sr.WaitTimeoutError:
            print("Voice Timeout: No speech detected.")
            QTimer.singleShot(0, lambda: self.input.setPlaceholderText("No speech detected. Try again."))
        except sr.UnknownValueError:
            print("Voice Error: Could not understand audio.")
            QTimer.singleShot(0, lambda: self.input.setPlaceholderText("Could not understand. Try again."))
        except Exception as e:
            print(f"Voice Error: {e}")
            QTimer.singleShot(0, lambda: self.input.setPlaceholderText(f"Error: {str(e)[:20]}..."))
        finally:
            QTimer.singleShot(0, self.stop_listening)

    def process_voice_result(self, text):
        print(f"DEBUG: Processing voice result: {text}")
        self.input.setText(text)
        # Force process events or just call send. 
        # Since this is running in QTimer (Main Thread), it should be fine.
        # Check if text was set
        if self.input.toPlainText().strip() == text:
             self.on_send()
        else:
             print("DEBUG: Input mismatch. Forcing send with arg.")
             # Fallback if on_send relies strictly on UI state which might lag? 
             # No, standard PyQt logic says setText updates model immediately.
             self.on_send()

    def disable_input(self):
        self.input.setDisabled(True)
        self.send.setDisabled(True)

    def enable_input(self):
        self.input.setDisabled(False)
        self.send.setDisabled(False)

    def scroll_to_bottom(self):
        self.scroll.verticalScrollBar().setValue(
            self.scroll.verticalScrollBar().maximum()
        )

    # --- Compatibility ---
    def add_ai_message(self, text):
        self.add_ai(text)

    def append_stream_token(self, token):
        count = self.chat_layout.count()
        if count == 0:
            return

        container = self.chat_layout.itemAt(count - 1).widget()
        if not container:
            return

        labels = container.findChildren(QLabel)
        for lbl in labels:
            if lbl.wordWrap():
                lbl.setText(lbl.text() + token)
                self.scroll_to_bottom()
                break


if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = ChatWindow()
    win.show()
    sys.exit(app.exec())

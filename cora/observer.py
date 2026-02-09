import time
import mss
import ollama
from PIL import Image
import io
import config
import json
import re
from PyQt6.QtCore import QObject, pyqtSignal

class ObserverSignal(QObject):
    suggestion_ready = pyqtSignal(object) # json payload
    prepare_capture = pyqtSignal()
    finished_capture = pyqtSignal()

class Observer:
    def __init__(self):
        self.running = False
        self.paused = False
        self.stop_flag = False
        self.signals = ObserverSignal()
        self.model = config.OLLAMA_MODEL 
        
    def stop_chat(self):
        self.stop_flag = True
        print("Stopping generation...")

    def capture_screen(self):
        try:
            # 1. Hide UI (Prevent recursion)
            self.signals.prepare_capture.emit()
            time.sleep(0.3) # Give UI time to vanish
            
            with mss.mss() as sct:
                monitor = sct.monitors[1]
                sct_img = sct.grab(monitor)
                img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
                # Downscale for performance, but keep readable (1024px minimum for text)
                img.thumbnail((1024, 1024)) 
                
            # 2. Restore UI
            self.signals.finished_capture.emit()
            return img
            
        except Exception as e:
            print(f"Screen Capture Error: {e}")
            self.signals.finished_capture.emit() # Always restore
            return None

    def _image_to_bytes(self, image):
        if not image: return None
        with io.BytesIO() as output:
            image.save(output, format='JPEG', quality=80)
            return output.getvalue()

    def pause(self):
        self.paused = True
        print("Observer Paused for Chat.")

    def resume(self):
        self.paused = False
        print("Observer Resumed.")

    def analyze(self, image):
        try:
            image_bytes = self._image_to_bytes(image)
            # print("Silent Analysis...") 
            
            response = ollama.chat(model=self.model, messages=[
                {
                    'role': 'user',
                    'content': config.SYSTEM_PROMPT,
                    'images': [image_bytes]
                }
            ])
            text = response['message']['content'].strip()
            
            # Clean JSON (sometimes LLMs add markdown)
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()
                
            data = json.loads(text)
            
            # Confidence Check
            confidence = data.get("confidence", 0.0)
            if confidence >= config.PROACTIVE_THRESHOLD:
                return data
            else:
                # print(f"Low Confidence ({confidence}): {data.get('reason')}")
                return None
                
        except json.JSONDecodeError:
            print("Observer: Failed to parse JSON from AI.")
            # print(text) 
            return None
        except Exception as e:
            print(f"Ollama Silent Error: {e}")
            return None

    def stream_chat_with_screen(self, user_query):
        self.stop_flag = False
        try:
            print("Capturing screen for chat...")
            img = self.capture_screen()
            image_bytes = self._image_to_bytes(img)
            
            if not image_bytes:
                yield "Error: Could not capture screen."
                return

            print(f"Streaming from Ollama ({self.model})...")
            
            full_prompt = f"{config.CHAT_SYSTEM_PROMPT}\n\nUSER: {user_query}\nCORA:"
            
            stream = ollama.chat(model=self.model, messages=[
                {
                    'role': 'user',
                    'content': full_prompt,
                    'images': [image_bytes]
                }
            ], stream=True)
            
            for chunk in stream:
                if self.stop_flag:
                    print("Generation stopped by user.")
                    break
                content = chunk['message']['content']
                yield content
                
        except Exception as e:
            print(f"Chat Error: {e}")
            yield f"Error: {e}"

    def loop(self):
        print("Observer started (Silent Mode)...")
        self.running = True
        while self.running:
            if self.paused:
                time.sleep(1)
                continue

            try:
                # 1. Capture
                img = self.capture_screen()
                
                # 2. Analyze (Silent Mode)
                payload = self.analyze(img)
                
                if payload:
                    print(f"✨ PROACTIVE ({payload['confidence']}): {payload['reason']}")
                    self.signals.suggestion_ready.emit(payload)
                
            except Exception as e:
                print(f"Observer Loop Error: {e}")
            
            # Wait for next cycle
            time.sleep(config.CHECK_INTERVAL)

    def stop(self):
        self.running = False
